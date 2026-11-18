"""
The yes/no vote reads each case's stance through the one parser.

A "neither" answer votes as "neither", and a case whose answer the parser does not
recognise casts no vote. The old vote counted both as "no".
"""

from unittest.mock import MagicMock

import pytest

from cosa.agents.prediction_engine.config import STRATEGY_CBR_MAJORITY, STRATEGY_COLD_START
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine, REASON_NEITHER_MAJORITY


@pytest.fixture
def engine():
    """An engine with a stubbed store, reset around each test."""
    PredictionEngine.reset()
    built = PredictionEngine( debug=False )
    built._embedding_store    = MagicMock()
    built._embedding_provider = MagicMock()
    yield built
    PredictionEngine.reset()


def _vote( engine, answers ):
    """Run the real yes/no vote over cases carrying these stored answers."""
    engine._embedding_store.find_similar.return_value = [
        ( 100.0 - index, { "decision_value": answer } ) for index, answer in enumerate( answers )
    ]
    return engine._predict_yes_no( "Proceed?", "permission", [ 0.1 ] * 768 )


def test_neither_reaches_the_vote_as_neither( engine ):
    result = _vote( engine, [ "neither [comment: re-frame it]", "neither", "yes" ] )
    assert result.metadata[ "votes" ] == { "neither": 2.0, "yes": 1.0 }


def test_a_neither_majority_gives_no_hint_until_phase_8( engine ):
    """Pinned abstention: the three-way stance work lifts it and rewrites this test."""
    result = _vote( engine, [ "neither", "neither", "yes" ] )
    assert result.strategy == STRATEGY_COLD_START
    assert result.predicted_value is None
    assert result.metadata[ "reason" ] == REASON_NEITHER_MAJORITY


def test_a_yes_majority_with_a_neither_in_the_tally_still_hints_yes( engine ):
    result = _vote( engine, [ "yes", "yes", "neither" ] )
    assert ( result.predicted_value, result.metadata[ "votes" ] ) == ( "yes", { "yes": 2.0, "neither": 1.0 } )


def test_a_case_with_no_recognised_stance_casts_no_vote( engine ):
    result = _vote( engine, [ "yes", "Maybe later", "not now" ] )
    assert result.metadata[ "votes" ] == { "yes": 1.0 }
    assert result.similar_case_count == 3


def test_cases_that_are_all_unrecognised_leave_the_engine_cold( engine ):
    result = _vote( engine, [ "Maybe later", "nope" ] )
    assert result.strategy == STRATEGY_COLD_START
    assert result.metadata[ "reason" ] == "no_recognised_stance"


def test_a_no_lead_under_the_margin_is_still_suppressed( engine ):
    result = _vote( engine, [ "no", "yes" ] )
    assert ( result.predicted_value, result.metadata[ "no_suppressed_by_prior" ] ) == ( "yes", True )
    assert result.strategy == STRATEGY_CBR_MAJORITY


def test_the_same_vote_with_an_unrecognised_case_added_does_not_move_the_tally( engine ):
    with_noise = _vote( engine, [ "yes", "no", "no", "Maybe" ] )
    without    = _vote( engine, [ "yes", "no", "no" ] )
    assert with_noise.metadata[ "votes" ] == without.metadata[ "votes" ]
