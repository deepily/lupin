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
