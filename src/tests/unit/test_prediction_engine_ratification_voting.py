#!/usr/bin/env python3
"""
Unit tests for ratification-aware CBR voting (thumbs up/down training signal).

A thumbs-up case (ratification_state="approved") UP-WEIGHTS its decision_value in the
majority tally; a thumbs-down case ("rejected") casts a NEGATIVE vote against its value
so the engine actively STEERS AWAY (Rick's decision 2026-06-03 — negative example, not
exclude). Ordinary cases (pending/not_required/missing) contribute 1.0.

Covers (all mocked — no DB, no server → :7999-eligible):
  - _ratified_weight()      : approved / rejected / ordinary mapping
  - _bounded_consistency()  : positive-mass normalization, all-negative → 0, clamp
  - yes_no path             : approved boost; rejected steers the winner
  - multiple_choice path    : a rejected case flips the single-select winner

Stage 3 (multi-select + open-ended coverage extension):
  - multiple_choice multi-select : weighted inclusion threshold over positive case
    mass; rejected removes an option; approved pushes a minority option in;
    all-steered-away → cold start; steered-away header omitted; fallback never
    picks a negatively-weighted option
  - open_ended / open_ended_batch : rejected cases never BE the answer (exact match
    + llm_fallback); approved exact match preferred; all-rejected → cold start;
    synthesis prompt carries user_verdict annotations
"""

import json
from unittest.mock import MagicMock

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine


def _make_engine():
    """PredictionEngine with mocked embedding store (default vote weights = 2.0/2.0)."""
    engine = PredictionEngine( debug=True )
    engine._embedding_store    = MagicMock()
    engine._embedding_provider = MagicMock()
    return engine


# ── _ratified_weight ──────────────────────────────────────────────────────────
class TestRatifiedWeight:
    def test_approved_returns_positive_approved_weight( self ):
        eng = _make_engine()
        eng.hint_vote_approved_weight = 2.0
        assert eng._ratified_weight( { "ratification_state": "approved" } ) == 2.0

    def test_rejected_returns_negative_rejected_weight( self ):
        eng = _make_engine()
        eng.hint_vote_rejected_weight = 2.0
        assert eng._ratified_weight( { "ratification_state": "rejected" } ) == -2.0

    def test_ordinary_states_return_one( self ):
        eng = _make_engine()
        for state in ( "pending", "not_required", "", None ):
            assert eng._ratified_weight( { "ratification_state": state } ) == 1.0
        assert eng._ratified_weight( {} ) == 1.0   # missing key

    def test_state_is_case_insensitive( self ):
        eng = _make_engine()
        eng.hint_vote_approved_weight = 3.0
        assert eng._ratified_weight( { "ratification_state": "APPROVED" } ) == 3.0


# ── _bounded_consistency ──────────────────────────────────────────────────────
class TestBoundedConsistency:
    def test_normalizes_by_positive_mass( self ):
        # winner 2.0 of positive mass (2.0 + 1.0) → 2/3
        votes = { "a": 2.0, "b": 1.0 }
        assert abs( PredictionEngine._bounded_consistency( votes, "a" ) - ( 2.0 / 3.0 ) ) < 1e-9

    def test_negative_votes_excluded_from_mass( self ):
        # winner 1.0; negative tally ignored in denominator → 1.0/1.0 = 1.0
        votes = { "a": 1.0, "b": -2.0 }
        assert PredictionEngine._bounded_consistency( votes, "a" ) == 1.0

    def test_all_negative_returns_zero( self ):
        votes = { "a": -1.0, "b": -2.0 }
        assert PredictionEngine._bounded_consistency( votes, "a" ) == 0.0

    def test_result_is_clamped_to_unit_interval( self ):
        votes = { "a": 5.0, "b": 1.0 }
        c = PredictionEngine._bounded_consistency( votes, "a" )
        assert 0.0 <= c <= 1.0


# ── yes_no path ───────────────────────────────────────────────────────────────
class TestYesNoRatificationVoting:
    def test_rejected_yes_steers_winner_to_no( self ):
        """Two 'yes' cases would win 2-1, but one is thumbs-downed → 'no' wins."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": "yes", "ratification_state": "rejected" } ),  # -2
            ( 90.0, { "decision_value": "yes", "ratification_state": "pending"  } ),  # +1
            ( 85.0, { "decision_value": "no",  "ratification_state": "pending"  } ),  # +1
        ]
        result = eng._predict_yes_no( "Ship it?", "deployment", [ 0.1 ] * 768 )
        assert result.predicted_value == "no"          # steered away from down-voted 'yes'
        assert 0.0 <= result.confidence <= 1.0

    def test_approved_yes_wins_over_unrated_no( self ):
        """A single approved 'yes' (weight 2) beats one ordinary 'no' (weight 1)."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": "yes", "ratification_state": "approved" } ),  # +2
            ( 90.0, { "decision_value": "no",  "ratification_state": "pending"  } ),  # +1
        ]
        result = eng._predict_yes_no( "Ship it?", "deployment", [ 0.1 ] * 768 )
        assert result.predicted_value == "yes"
        assert 0.0 <= result.confidence <= 1.0


# ── multiple_choice (single-select) path ──────────────────────────────────────
class TestMultipleChoiceRatificationVoting:
    def test_rejected_case_flips_single_select_winner( self ):
        """Postgres would win 2-1 raw, but one Postgres case is thumbs-downed → Mongo wins."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": json.dumps( { "answers": { "DB": "PostgreSQL" } } ), "ratification_state": "rejected" } ),  # -2
            ( 90.0, { "decision_value": json.dumps( { "answers": { "DB": "PostgreSQL" } } ), "ratification_state": "pending"  } ),  # +1
            ( 85.0, { "decision_value": json.dumps( { "answers": { "DB": "MongoDB"    } } ), "ratification_state": "pending"  } ),  # +1
        ]
        result = eng._predict_multiple_choice( "Which DB?", "approach", [ 0.1 ] * 768 )
        assert result.predicted_value == { "answers": { "DB": "MongoDB" } }
        assert 0.0 <= result.confidence <= 1.0

    def test_unrated_cases_behave_as_plain_majority( self ):
        """With no ratifications, weighting reduces to the original majority vote."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": json.dumps( { "answers": { "DB": "PostgreSQL" } } ) } ),
            ( 90.0, { "decision_value": json.dumps( { "answers": { "DB": "PostgreSQL" } } ) } ),
            ( 85.0, { "decision_value": json.dumps( { "answers": { "DB": "MongoDB"    } } ) } ),
        ]
        result = eng._predict_multiple_choice( "Which DB?", "approach", [ 0.1 ] * 768 )
        assert result.predicted_value == { "answers": { "DB": "PostgreSQL" } }   # 2 vs 1


# ── multiple_choice (multi-select) path — Stage 3 ────────────────────────────
def _ms_case( options_by_header, state=None ):
    """( similarity, record ) for a multi-select case; options_by_header e.g. {"Feat": ["A","B"]}."""
    record = { "decision_value": json.dumps( { "answers": options_by_header } ) }
    if state is not None:
        record[ "ratification_state" ] = state
    return ( 90.0, record )


class TestMultiSelectRatificationVoting:
    def test_unrated_cases_behave_as_raw_counts( self ):
        """No ratifications → identical to the original >=50%-of-cases inclusion rule."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _ms_case( { "Feat": [ "A", "B" ] } ),
            _ms_case( { "Feat": [ "A" ] } ),
            _ms_case( { "Feat": [ "C" ] } ),
        ]
        result = eng._predict_multiple_choice( "Which features?", "approach", [ 0.1 ] * 768 )
        # A: 2/3 >= 0.5 in; B: 1/3 out; C: 1/3 out
        assert result.predicted_value == { "answers": { "Feat": [ "A" ] } }

    def test_rejected_case_removes_option_from_selection( self ):
        """'B' would be included 2/3 raw, but a thumbs-downed B-only case steers it out."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _ms_case( { "Feat": [ "A", "B" ] } ),
            _ms_case( { "Feat": [ "B" ] }, state="rejected" ),
            _ms_case( { "Feat": [ "A" ] } ),
        ]
        result = eng._predict_multiple_choice( "Which features?", "approach", [ 0.1 ] * 768 )
        # positive mass = 2 (rejected contributes none); A = 2 >= 1.0 in; B = 1-2 = -1 → never selected
        assert result.predicted_value == { "answers": { "Feat": [ "A" ] } }

    def test_approved_case_pushes_minority_option_in( self ):
        """'B' is 1/3 raw (excluded), but its case is thumbs-upped → weighted in."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _ms_case( { "Feat": [ "A" ] } ),
            _ms_case( { "Feat": [ "A" ] } ),
            _ms_case( { "Feat": [ "A", "B" ] }, state="approved" ),
        ]
        result = eng._predict_multiple_choice( "Which features?", "approach", [ 0.1 ] * 768 )
        # mass = 1+1+2 = 4, threshold 2.0; A = 4 in; B = 2 >= 2.0 in (raw: 1/3 < 0.5 out)
        assert result.predicted_value == { "answers": { "Feat": [ "A", "B" ] } }

    def test_all_options_steered_away_returns_cold_start( self ):
        """Every case thumbs-downed → no positive signal → cold start, not a guess."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _ms_case( { "Feat": [ "A" ] }, state="rejected" ),
            _ms_case( { "Feat": [ "B" ] }, state="rejected" ),
        ]
        result = eng._predict_multiple_choice( "Which features?", "approach", [ 0.1 ] * 768 )
        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "all_multi_select_options_steered_away"

    def test_steered_away_header_is_omitted_others_survive( self ):
        """A fully down-voted header is dropped; sibling headers still predict."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _ms_case( { "Keep": [ "A" ], "Drop": [ "X" ] } ),
            _ms_case( { "Drop": [ "X" ] }, state="rejected" ),
        ]
        result = eng._predict_multiple_choice( "Which?", "approach", [ 0.1 ] * 768 )
        # Drop.X = 1 - 2 = -1 → header omitted; Keep.A = 1 >= 0.5*mass(2) = 1.0 → in
        assert result.predicted_value == { "answers": { "Keep": [ "A" ] } }

    def test_fallback_never_picks_negatively_weighted_option( self ):
        """Below-threshold fallback picks the best POSITIVE option, not the down-voted one."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _ms_case( { "Feat": [ "A" ] } ),
            _ms_case( { "Feat": [ "B" ] } ),
            _ms_case( { "Feat": [ "C" ] } ),
            _ms_case( { "Feat": [ "A" ] }, state="rejected" ),
        ]
        result = eng._predict_multiple_choice( "Which features?", "approach", [ 0.1 ] * 768 )
        # mass = 3, threshold 1.5; A = 1-2 = -1, B = 1, C = 1 → none reach 1.5 →
        # fallback = highest positive (B or C — first max), never A
        selected = result.predicted_value[ "answers" ][ "Feat" ]
        assert len( selected ) == 1 and selected[ 0 ] in ( "B", "C" )


# ── open_ended path — Stage 3 steer-away ─────────────────────────────────────
def _oe_case( similarity, question, answer, state=None ):
    record = { "question": question, "decision_value": answer }
    if state is not None:
        record[ "ratification_state" ] = state
    return ( similarity, record )


class TestOpenEndedRatificationSteering:
    def test_all_cases_rejected_returns_cold_start( self ):
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _oe_case( 95.0, "What naming?", "snake_case", state="rejected" ),
            _oe_case( 90.0, "Which naming?", "camelCase", state="rejected" ),
        ]
        result = eng._predict_open_ended( "What naming?", "input", [ 0.1 ] * 768 )
        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "all_cases_rejected"

    def test_rejected_exact_match_never_returned( self ):
        """The exact-match case is thumbs-downed → tier 1 must NOT return it; the
        ordinary non-exact case answers via the llm_fallback retrieval instead."""
        eng = _make_engine()
        eng._llm_client = MagicMock()
        eng._llm_client.run.side_effect = RuntimeError( "no LLM in unit tests" )   # synthesis fails → fallback
        eng._embedding_store.find_similar.return_value = [
            _oe_case( 98.0, "What naming?", "SCREAMING_SNAKE", state="rejected" ),
            _oe_case( 90.0, "Which naming style?", "snake_case" ),
        ]
        result = eng._predict_open_ended( "What naming?", "input", [ 0.1 ] * 768 )
        assert result.predicted_value == "snake_case"          # steered away from the rejected answer
        assert result.metadata[ "tier" ] == "llm_fallback"
        assert abs( result.confidence - 0.90 ) < 0.001         # confidence from the answering case

    def test_approved_exact_match_preferred_over_higher_similarity_ordinary( self ):
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _oe_case( 95.0, "What naming?", "camelCase" ),
            _oe_case( 90.0, "What naming?", "snake_case", state="approved" ),
        ]
        result = eng._predict_open_ended( "What naming?", "input", [ 0.1 ] * 768 )
        assert result.predicted_value == "snake_case"          # human-confirmed wins
        assert result.metadata[ "tier" ] == "exact_match"
        assert abs( result.confidence - 0.90 ) < 0.001

    def test_first_ordinary_exact_match_wins_over_a_second( self ):
        """Two ordinary exact matches → the higher-similarity (first) one answers."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _oe_case( 95.0, "What naming?", "snake_case" ),
            _oe_case( 90.0, "What naming?", "kebab-case" ),
        ]
        result = eng._predict_open_ended( "What naming?", "input", [ 0.1 ] * 768 )
        assert result.predicted_value == "snake_case"
        assert abs( result.confidence - 0.95 ) < 0.001

    def test_exact_match_below_top_still_fires_tier_1( self ):
        """A non-rejected exact match deeper in the candidate list answers tier 1."""
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _oe_case( 95.0, "Which naming style do you like?", "camelCase" ),
            _oe_case( 90.0, "What naming?", "snake_case" ),
        ]
        result = eng._predict_open_ended( "What naming?", "input", [ 0.1 ] * 768 )
        assert result.predicted_value == "snake_case"
        assert result.metadata[ "tier" ] == "exact_match"

    def test_llm_fallback_skips_rejected_top_case( self ):
        """LLM failure → retrieval fallback answers with the best NON-rejected case."""
        eng = _make_engine()
        eng._llm_client = MagicMock()
        eng._llm_client.run.side_effect = RuntimeError( "no LLM in unit tests" )
        eng._embedding_store.find_similar.return_value = [
            _oe_case( 96.0, "Pick a deploy window", "Friday 5pm", state="rejected" ),
            _oe_case( 88.0, "Choose a deploy window", "Tuesday 10am" ),
        ]
        result = eng._predict_open_ended( "Best deploy window?", "scheduling", [ 0.1 ] * 768 )
        assert result.predicted_value == "Tuesday 10am"
        assert result.metadata[ "tier" ] == "llm_fallback"


# ── open_ended_batch path — Stage 3 steer-away (mirrors open_ended) ──────────
class TestOpenEndedBatchRatificationSteering:
    def test_all_cases_rejected_returns_cold_start( self ):
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _oe_case( 95.0, "Q1?", json.dumps( { "answers": { "H": "x" } } ), state="rejected" ),
        ]
        result = eng._predict_open_ended_batch( "Q1?", "input", [ 0.1 ] * 768 )
        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "all_cases_rejected"

    def test_approved_exact_match_preferred( self ):
        eng = _make_engine()
        eng._embedding_store.find_similar.return_value = [
            _oe_case( 95.0, "Batch Q?", json.dumps( { "answers": { "H": "old" } } ) ),
            _oe_case( 90.0, "Batch Q?", json.dumps( { "answers": { "H": "confirmed" } } ), state="approved" ),
        ]
        result = eng._predict_open_ended_batch( "Batch Q?", "input", [ 0.1 ] * 768 )
        assert result.predicted_value == { "answers": { "H": "confirmed" } }
        assert result.metadata[ "tier" ] == "exact_match"

    def test_llm_fallback_skips_rejected_top_case( self ):
        eng = _make_engine()
        eng._llm_client = MagicMock()
        eng._llm_client.run.side_effect = RuntimeError( "no LLM in unit tests" )
        eng._embedding_store.find_similar.return_value = [
            _oe_case( 96.0, "Q-a?", json.dumps( { "answers": { "H": "bad" } } ), state="rejected" ),
            _oe_case( 88.0, "Q-b?", json.dumps( { "answers": { "H": "good" } } ) ),
        ]
        result = eng._predict_open_ended_batch( "Q-c?", "input", [ 0.1 ] * 768 )
        assert result.predicted_value == { "answers": { "H": "good" } }
        assert result.metadata[ "tier" ] == "llm_fallback"


# ── synthesis prompt user_verdict annotations — Stage 3 ──────────────────────
class TestSynthesisPromptVerdictAnnotations:
    def test_prompt_carries_user_verdicts_only_for_ratified_cases( self, monkeypatch ):
        eng = _make_engine()
        monkeypatch.setattr(
            "cosa.utils.util.get_file_as_string",
            lambda path: "Q: {current_question}\nN: {case_count}\n{formatted_cases}\n{{PYDANTIC_XML_EXAMPLE}}"
        )
        cases = [
            _oe_case( 95.0, "Qa?", "Aa", state="approved" ),
            _oe_case( 90.0, "Qb?", "Ab", state="rejected" ),
            _oe_case( 85.0, "Qc?", "Ac" ),
        ]
        prompt = eng._build_synthesis_prompt( "Current?", cases )
        assert 'user_verdict="approved"' in prompt
        assert 'user_verdict="rejected"' in prompt
        assert prompt.count( "user_verdict" ) == 2   # ordinary case carries NO verdict attr
