"""
Unit tests for the complete-action measure and the atom decomposition.

Each plain-code test runs with a judge that fails if it is called, so a pass shows the plain code decided it.
The judge's own part is tested with a canned judge. No test calls a model or touches a database.
"""

import json
import uuid
from contextlib import contextmanager
from functools import partial
from types import SimpleNamespace

import pytest

from cosa.agents.prediction_engine.accuracy_comparators import (
    compare_complete_action_multiple_choice,
    compare_complete_action_open_ended,
    compare_complete_action_open_ended_batch,
    compare_complete_action_yes_no,
    compare_multiple_choice,
    compare_open_ended,
    compare_open_ended_batch,
    compare_yes_no,
    decompose_atoms,
    get_comparator,
)
from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult


def failing_judge( predicted_text, actual_text ):
    """The transport that fails if called: the plain-code part must not need the judge."""
    raise AssertionError( f"the judge was called with {predicted_text!r} and {actual_text!r}" )


def judge_saying( keeps, invents_nothing ):
    """A canned judge that records its calls and answers as told."""
    calls = []
    def judge( predicted_text, actual_text ):
        calls.append( ( predicted_text, actual_text ) )
        return { "keeps_every_restriction": keeps, "invents_nothing": invents_nothing }
    judge.calls = calls
    return judge


CARD = { "questions": [
    { "header": "Approach", "multi_select": False, "options": [ { "label": "Proceed" }, { "label": "Skip" } ] },
    { "header": "Tags",     "multi_select": True,  "options": [ { "label": "A" }, { "label": "B" }, { "label": "C" } ] },
] }


# ---- yes/no: the plain-code part ----------------------------------------------------------------

def test_a_right_stance_with_no_condition_on_either_side_passes_without_the_judge():
    match, detail = compare_complete_action_yes_no( { "value": "yes" }, { "value": "yes" }, judge=failing_judge )
    assert match is True and detail[ "conditions_by" ] == "plain_code" and detail[ "plain_code_match" ] is True


def test_a_wrong_stance_fails_without_the_judge():
    match, detail = compare_complete_action_yes_no( { "value": "no" }, { "value": "yes" }, judge=failing_judge )
    assert match is False and detail[ "conditions_by" ] == "not_reached" and detail[ "abstained" ] is False


def test_the_same_condition_in_other_case_passes_without_the_judge():
    predicted = { "value": "yes", "qualifier": "Leave the configuration alone " }
    actual    = { "value": "yes [comment: leave the configuration alone]" }
    assert compare_complete_action_yes_no( predicted, actual, judge=failing_judge )[ 0 ] is True


def test_an_abstention_is_no_success_and_never_calls_the_judge():
    match, detail = compare_complete_action_yes_no( None, { "value": "yes" }, judge=failing_judge )
    assert ( match, detail[ "abstained" ], detail[ "plain_code_match" ] ) == ( False, True, False )


def test_a_forecast_with_no_stance_counts_as_abstained():
    match, detail = compare_complete_action_yes_no( { "value": "maybe" }, { "value": "yes" }, judge=failing_judge )
    assert ( match, detail[ "abstained" ] ) == ( False, True )


def test_an_answer_that_is_missing_is_not_scored():
    assert compare_complete_action_yes_no( { "value": "yes" }, None ) == ( None, { "reason": "missing_data" } )


def test_the_stance_only_bridge_still_leaves_an_abstention_out_of_the_total():
    """The bridge leaves an abstained field out of total.

    The new measure charges it as no success.
    """
    predicted = { "answers": { "Tags": [ "A" ] } }
    actual    = { "answers": { "Approach": "Proceed", "Tags": [ "A" ] } }
    _, bridge = compare_multiple_choice( predicted, actual, CARD, per_field=True )
    match, new = compare_complete_action_multiple_choice( predicted, actual, CARD, judge=failing_judge )
    assert ( bridge[ "total" ], bridge[ "abstained" ] ) == ( 1, 1 )
    assert ( match, new[ "fields_total" ], new[ "fields_passed" ], new[ "fields_abstained" ] ) == ( False, 2, 1, 1 )


# ---- yes/no: the judge's part -------------------------------------------------------------------

def test_a_differing_condition_without_a_judge_is_undecided_not_failed():
    match, detail = compare_complete_action_yes_no( { "value": "yes" }, { "value": "yes [comment: leave the configuration alone]" } )
    assert match is None and detail[ "reason" ] == "judge_required" and detail[ "plain_code_match" ] is True


def test_the_judge_decides_a_differing_condition():
    judge = judge_saying( True, True )
    match, detail = compare_complete_action_yes_no( { "value": "yes", "qualifier": "keep the config" }, { "value": "yes [comment: leave the configuration alone]" }, judge=judge )
    assert match is True and detail[ "conditions_by" ] == "judge" and judge.calls == [ ( "keep the config", "leave the configuration alone" ) ]


@pytest.mark.parametrize( "keeps, invents_nothing", [ ( False, True ), ( True, False ) ] )
def test_the_judge_must_say_both_things( keeps, invents_nothing ):
    match, _ = compare_complete_action_yes_no( { "value": "yes" }, { "value": "yes [comment: only the old files]" }, judge=judge_saying( keeps, invents_nothing ) )
    assert match is False


# ---- multiple choice ----------------------------------------------------------------------------

def test_every_field_exact_passes_without_the_judge():
    answers = { "answers": { "Approach": "Proceed", "Tags": [ "A", "B" ] } }
    match, detail = compare_complete_action_multiple_choice( answers, answers, CARD, judge=failing_judge )
    assert match is True and ( detail[ "fields_total" ], detail[ "fields_passed" ] ) == ( 2, 2 )
    assert detail[ "atoms" ][ "precision" ] == 1.0 and detail[ "atoms" ][ "recall" ] == 1.0


def test_one_inexact_field_fails_the_card_and_the_atoms_say_how():
    predicted = { "answers": { "Approach": "Skip", "Tags": [ "A", "C" ] } }
    actual    = { "answers": { "Approach": "Proceed", "Tags": [ "A", "B" ] } }
    match, detail = compare_complete_action_multiple_choice( predicted, actual, CARD, judge=failing_judge )
    atoms = detail[ "atoms" ]
    assert match is False and detail[ "fields_passed" ] == 0
    assert atoms[ "contradictions" ] == [ ( "Approach", "Skip" ) ]
    assert atoms[ "additions" ] == [ ( "Tags", "C" ) ]
    assert atoms[ "omissions" ] == [ ( "Tags", "B" ) ]
    assert ( atoms[ "precision" ], atoms[ "recall" ] ) == ( 1 / 3, 1 / 3 )


def test_a_forecast_with_no_answers_is_an_abstention():
    for predicted in ( None, { "answers": {} } ):
        match, detail = compare_complete_action_multiple_choice( predicted, { "answers": { "Approach": "Proceed" } }, CARD, judge=failing_judge )
        assert ( match, detail[ "abstained" ] ) == ( False, True )


def test_an_answer_that_is_missing_or_empty_is_not_scored():
    assert compare_complete_action_multiple_choice( { "answers": { "A": "x" } }, None, CARD ) == ( None, { "reason": "missing_data" } )
    assert compare_complete_action_multiple_choice( { "answers": { "A": "x" } }, { "answers": {} }, CARD ) == ( None, { "reason": "empty_answers" } )


def test_a_malformed_schema_is_reported_and_the_card_still_scored():
    answers = { "answers": { "H": "a" } }
    match, detail = compare_complete_action_multiple_choice( answers, answers, "nonsense" )
    assert match is True and detail[ "schema_reason" ] == "malformed_schema"


# ---- the decomposition --------------------------------------------------------------------------

def test_decompose_flags_each_miss_under_one_name_only():
    result = decompose_atoms( [ ( "q", "a" ), ( "q", "x" ), ( "r", "z" ) ], [ ( "q", "b" ), ( "r", "y" ) ], single_groups={ "q" } )
    assert result[ "contradictions" ] == [ ( "q", "a" ), ( "q", "x" ) ]     # two picks in a single group the answer filled with b
    assert result[ "omissions" ] == [ ( "r", "y" ) ]                      # ( q, b ) is covered by the contradictions, so it is not counted again
    assert result[ "additions" ] == [ ( "r", "z" ) ]                      # group r is not single, so z is only unsupported


def test_decompose_with_nothing_on_a_side_gives_one_for_that_side():
    both  = decompose_atoms( [], [] )
    extra = decompose_atoms( [ ( "q", "a" ) ], [] )
    lost  = decompose_atoms( [], [ ( "q", "a" ) ] )
    assert ( both[ "precision" ], both[ "recall" ] ) == ( 1.0, 1.0 )
    assert ( extra[ "precision" ], extra[ "recall" ], extra[ "additions" ] ) == ( 0.0, 1.0, [ ( "q", "a" ) ] )
    assert ( lost[ "precision" ], lost[ "recall" ], lost[ "omissions" ] ) == ( 1.0, 0.0, [ ( "q", "a" ) ] )


# ---- open-ended and batch -----------------------------------------------------------------------

def test_open_ended_same_words_pass_without_the_judge_and_carry_the_similarity_verdict():
    match, detail = compare_complete_action_open_ended( { "value": "Use the cache" }, { "value": "use the cache " }, judge=failing_judge )
    assert match is True and detail[ "similarity_match" ] is True and detail[ "plain_code_match" ] is True


def test_open_ended_abstention_and_missing_answer():
    assert compare_complete_action_open_ended( None, { "value": "x" }, judge=failing_judge )[ 0 ] is False
    assert compare_complete_action_open_ended( { "value": "  " }, { "value": "x" }, judge=failing_judge )[ 1 ][ "abstained" ] is True
    assert compare_complete_action_open_ended( { "value": "x" }, None ) == ( None, { "reason": "missing_data" } )


def test_open_ended_different_words_need_the_judge():
    predicted, actual = { "value": "cache it" }, { "value": "use the cache" }
    assert compare_complete_action_open_ended( predicted, actual )[ 0 ] is None
    judge = judge_saying( True, True )
    match, detail = compare_complete_action_open_ended( predicted, actual, judge=judge )
    assert match is True and detail[ "judge" ][ "invents_nothing" ] is True and detail[ "similarity_match" ] is False


def test_open_ended_text_similar_by_embedding_is_still_judged_by_the_measure():
    """Text similarity says yes; the complete-action measure does not take its word for it."""
    actual = { "value": "use the cache", "_embedding_similarity": 0.99 }
    match, detail = compare_complete_action_open_ended( { "value": "cache it" }, actual, judge=judge_saying( False, True ) )
    assert detail[ "similarity_match" ] is True and match is False


def test_batch_every_question_must_pass():
    actual = { "answers": { "Q1": "same", "Q2": "other words", "Q3": "third" } }
    judge  = judge_saying( True, True )
    match, detail = compare_complete_action_open_ended_batch( { "answers": { "Q1": "same", "Q2": "different", "Q3": "third" } }, actual, judge=judge )
    assert match is True and detail[ "fields_passed" ] == 3 and judge.calls == [ ( "different", "other words" ) ]
    failing = compare_complete_action_open_ended_batch( { "answers": { "Q1": "same", "Q2": "different", "Q3": "third" } }, actual, judge=judge_saying( True, False ) )
    assert failing[ 0 ] is False


def test_batch_a_left_out_question_is_abstained_and_fails():
    match, detail = compare_complete_action_open_ended_batch( { "answers": { "Q1": "same" } }, { "answers": { "Q1": "same", "Q2": "x" } }, judge=failing_judge )
    assert ( match, detail[ "fields_abstained" ], detail[ "abstained" ] ) == ( False, 1, True )


def test_batch_without_a_judge_is_undecided_unless_a_field_already_failed():
    actual = { "answers": { "Q1": "same", "Q2": "other" } }
    match, detail = compare_complete_action_open_ended_batch( { "answers": { "Q1": "same", "Q2": "different" } }, actual )
    assert match is None and detail[ "reason" ] == "judge_required"
    assert compare_complete_action_open_ended_batch( { "answers": { "Q1": "same", "Q2": "different" } }, { "answers": { "Q1": "x", "Q2": "other" } }, judge=judge_saying( False, False ) )[ 0 ] is False


def test_batch_abstention_and_missing_answers():
    assert compare_complete_action_open_ended_batch( None, { "answers": { "Q": "x" } }, judge=failing_judge )[ 0 ] is False
    assert compare_complete_action_open_ended_batch( { "answers": {} }, { "answers": { "Q": "x" } } )[ 1 ][ "abstained" ] is True
    assert compare_complete_action_open_ended_batch( { "answers": { "Q": "x" } }, None ) == ( None, { "reason": "missing_data" } )
    assert compare_complete_action_open_ended_batch( { "answers": { "Q": "x" } }, { "answers": {} } ) == ( None, { "reason": "empty_answers" } )


# ---- get_comparator and the switch --------------------------------------------------------------

@pytest.mark.parametrize( "response_type, expected", [
    ( "yes_no", compare_complete_action_yes_no ),
    ( "multiple_choice", compare_complete_action_multiple_choice ),
    ( "open_ended", compare_complete_action_open_ended ),
    ( "open_ended_batch", compare_complete_action_open_ended_batch ),
    ( "unknown", compare_complete_action_open_ended ),
] )
def test_every_response_type_gets_its_complete_action_comparator( response_type, expected ):
    comparator = get_comparator( response_type, complete_action=True )
    assert ( comparator.func if isinstance( comparator, partial ) else comparator ) is expected


def test_the_judge_and_schema_reach_the_bound_comparator():
    judge = judge_saying( True, True )
    assert get_comparator( "yes_no", complete_action=True, judge=judge ).keywords[ "judge" ] is judge
    assert get_comparator( "multiple_choice", complete_action=True, response_options=CARD ).keywords[ "response_options" ] is CARD
    assert get_comparator( "multiple_choice", complete_action=True ).keywords[ "response_options" ] == {}
    assert get_comparator( "open_ended", complete_action=True, open_ended_threshold=0.9 ).keywords[ "threshold" ] == 0.9


def test_switch_off_binding_is_exactly_the_old_one():
    """Pin: with the switch off every response type is bound as it was before this change."""
    assert get_comparator( "yes_no" ) is compare_yes_no
    assert get_comparator( "open_ended" ) is compare_open_ended
    assert get_comparator( "open_ended_batch" ) is compare_open_ended_batch
    assert get_comparator( "multiple_choice", response_options=CARD ).func is compare_multiple_choice
    assert get_comparator( "multiple_choice", response_options=CARD, complete_action=False, judge=failing_judge ).keywords == { "response_options": CARD }


def test_the_switch_ships_off_and_is_in_the_ini():
    assert cfg.DEFAULT_COMPLETE_ACTION_SCORING_ENABLED is False
    assert cfg.DEFAULT_LOOKUP_NEITHER_FORECAST_ENABLED is False


# ---- record_outcome picks the comparator by the switch ------------------------------------------

@pytest.fixture
def engine():
    PredictionEngine.reset()
    built = PredictionEngine( debug=False )
    yield built
    PredictionEngine.reset()


def _record( engine, monkeypatch, predicted_value, actual_value ):
    seen = {}

    class Repo:
        def __init__( self, session ): pass
        def update_outcome( self, **kwargs ): seen.update( kwargs ); return True

    @contextmanager
    def fake_db():
        yield SimpleNamespace( commit=lambda: None )

    monkeypatch.setattr( "cosa.rest.db.database.get_db", fake_db )
    monkeypatch.setattr( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", Repo )
    monkeypatch.setattr( engine, "_store_decision", lambda *a, **k: None )
    result = PredictionResult( "yes_no", "c", "cbr_majority_vote", predicted_value=predicted_value, confidence=0.9 )
    engine.record_outcome( str( uuid.uuid4() ), result, actual_value, "yes_no", None, None )
    return seen


def test_record_outcome_with_the_switch_off_scores_the_stance_only( engine, monkeypatch ):
    seen = _record( engine, monkeypatch, "yes", "yes [comment: leave it alone]" )
    assert seen[ "accuracy_match" ] is True and "stance" not in seen[ "accuracy_detail" ]


def test_record_outcome_with_the_switch_on_scores_the_whole_action( engine, monkeypatch ):
    engine.complete_action_scoring_enabled = True
    seen = _record( engine, monkeypatch, "yes", "yes [comment: leave it alone]" )
    assert seen[ "accuracy_match" ] is None and seen[ "accuracy_detail" ][ "reason" ] == "judge_required"


def test_config_version_moves_with_each_new_switch_and_not_when_off( engine ):
    base = engine.config_version()
    engine.lookup_neither_forecast_enabled = True
    with_lookup = engine.config_version()
    engine.complete_action_scoring_enabled = True
    with_both = engine.config_version()
    engine.lookup_neither_forecast_enabled = False
    engine.complete_action_scoring_enabled = False
    assert len( { base, with_lookup, with_both } ) == 3 and engine.config_version() == base


# ---- the six worked examples, as literals -------------------------------------------------------
# The expert's table is not in the plan, so these six are written here from the plan's own descriptions:
# three give a verdict, and three (1, 5, 6) are the open ones. For an open one only the plain-code part is pinned.

def test_example_2_forecast_and_answer_carry_the_same_condition():
    forecast = { "value": "yes", "qualifier": "leave the configuration alone" }
    answer   = { "value": "yes [comment: leave the configuration alone]" }
    match, detail = compare_complete_action_yes_no( forecast, answer, judge=failing_judge )
    assert ( match, detail[ "plain_code_match" ] ) == ( True, True )


def test_example_3_the_forecast_has_the_wrong_stance():
    match, detail = compare_complete_action_yes_no( { "value": "no" }, { "value": "yes [comment: go ahead]" }, judge=failing_judge )
    assert ( match, detail[ "plain_code_match" ] ) == ( False, False )


def test_example_4_a_multiple_choice_forecast_matches_every_field():
    answer = { "answers": { "Approach": "Proceed", "Tags": [ "A" ] } }
    match, detail = compare_complete_action_multiple_choice( answer, answer, CARD, judge=failing_judge )
    assert ( match, detail[ "fields_passed" ] ) == ( True, 2 )


def test_example_1_open_a_bare_yes_against_a_yes_with_a_restriction_plain_code_part_only():
    """Depends on the forecast.

    The stance is right; whether the missing restriction matters is the judge's and Rick's.
    """
    match, detail = compare_complete_action_yes_no( { "value": "yes" }, { "value": "yes [comment: but leave the configuration alone]" } )
    assert ( match, detail[ "plain_code_match" ], detail[ "conditions_by" ] ) == ( None, True, "undecided" )


def test_example_5_open_partial_overlap_plain_code_part_only():
    """Partial diagnostic overlap.

    The plain code fails the card and reports the overlap; the credit is Rick's to rule.
    """
    forecast = { "answers": { "Approach": "Proceed", "Tags": [ "A", "B" ] } }
    answer   = { "answers": { "Approach": "Proceed", "Tags": [ "A", "C" ] } }
    match, detail = compare_complete_action_multiple_choice( forecast, answer, CARD, judge=failing_judge )
    atoms = detail[ "atoms" ]
    assert match is False and ( detail[ "fields_passed" ], detail[ "fields_total" ] ) == ( 1, 2 )
    assert ( atoms[ "precision" ], atoms[ "recall" ], atoms[ "additions" ], atoms[ "omissions" ] ) == ( 2 / 3, 2 / 3, [ ( "Tags", "B" ) ], [ ( "Tags", "C" ) ] )


def test_example_6_open_a_neither_forecast_against_a_no_with_a_reason_plain_code_part_only():
    """Assess the reason separately.

    The plain code scores the stance and leaves the reason to the judge.
    """
    match, detail = compare_complete_action_yes_no( { "value": "neither", "qualifier": "ask first" }, { "value": "no [comment: too risky]" }, judge=failing_judge )
    assert ( match, detail[ "plain_code_match" ] ) == ( False, False )
    assert detail[ "stance" ][ "predicted_qualifier" ] == "ask first" and detail[ "stance" ][ "actual_qualifier" ] == "too risky"
