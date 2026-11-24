"""
Unit tests for the lookup engine's neither forecast.

Every vote is planted: the cases are written out with their answers and the expected winner is a literal.
The vote itself is three_way_stance.three_way_forecast; these tests assert the engine adds no second one.
No test touches a database or a model: the case loader and the session are replaced.
"""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cosa.agents.prediction_engine import three_way_shadow, three_way_stance
from cosa.agents.prediction_engine.config import STRATEGY_CBR_MAJORITY, STRATEGY_COLD_START
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine, REASON_NEITHER_MAJORITY
from cosa.agents.prediction_engine.prediction_result import PredictionResult

ASKED  = datetime( 2026, 11, 20, 12, 0, tzinfo=timezone.utc )
ASK    = [ 1.0, 0.0, 0.0 ]
# Four vectors at cosine 0.894 to the ask and at most 0.8 to each other: four independent votes.
SPREAD = [ [ 1.0, 0.5, 0.0 ], [ 1.0, -0.5, 0.0 ], [ 1.0, 0.0, 0.5 ], [ 1.0, 0.0, -0.5 ] ]


def _case( case_id, answer, vector ):
    return { "id": case_id, "decision_value": answer, "ratification_state": "not_required", "response_type": "yes_no",
             "question_embedding": vector, "owner_user_id": "u1", "answer_source": "human",
             "responded_at": ASKED - timedelta( days=1 ), "category": "c", "title": "t", "message": "m", "sender_id": "s",
             "asked_at": ASKED - timedelta( days=1, minutes=1 ) }


def _planted( *answers ):
    return [ _case( f"c{i}", answer, SPREAD[ i ] ) for i, answer in enumerate( answers ) ]


@pytest.fixture
def engine( monkeypatch ):
    PredictionEngine.reset()
    built = PredictionEngine( debug=False )
    built.lookup_neither_forecast_enabled = True
    built._embedding_store = MagicMock()
    @contextmanager
    def fake_db():
        yield SimpleNamespace()
    monkeypatch.setattr( "cosa.rest.db.database.get_db", fake_db )
    yield built
    PredictionEngine.reset()


def _vote( engine, monkeypatch, cases, embedding=ASK, owner="u1" ):
    monkeypatch.setattr( three_way_shadow, "live_cases", lambda session, owner_user_id: cases )
    return engine._predict_yes_no( "Proceed?", "permission", embedding, owner_user_id=owner, ask_context={ "title": "T", "sender_id": "S" } )


def test_neither_wins_and_is_forecast_with_its_own_probability( engine, monkeypatch ):
    result = _vote( engine, monkeypatch, _planted( "neither", "neither", "neither", "yes" ) )
    assert ( result.predicted_value, result.strategy ) == ( "neither", STRATEGY_CBR_MAJORITY )
    assert result.confidence == result.metadata[ "probabilities" ][ "neither" ] and result.confidence > 0.5
    assert result.metadata[ "three_way" ] is True


def test_yes_and_no_still_win_when_the_planted_votes_say_so( engine, monkeypatch ):
    assert _vote( engine, monkeypatch, _planted( "yes", "yes", "yes", "neither" ) ).predicted_value == "yes"
    assert _vote( engine, monkeypatch, _planted( "no", "no", "no", "no" ) ).predicted_value == "no"


def test_the_winning_stances_qualifier_travels_with_the_forecast( engine, monkeypatch ):
    result = _vote( engine, monkeypatch, _planted( "neither [comment: re-frame it]", "neither", "neither", "yes" ) )
    assert ( result.predicted_value, result.predicted_qualifier ) == ( "neither", "re-frame it" )


def test_there_is_one_vote_and_the_old_one_is_never_run( engine, monkeypatch ):
    calls = []
    real  = three_way_stance.three_way_forecast
    monkeypatch.setattr( three_way_stance, "three_way_forecast", lambda *a: calls.append( a ) or real( *a ) )
    result = _vote( engine, monkeypatch, _planted( "neither", "neither", "neither", "neither" ) )
    assert len( calls ) == 1 and calls[ 0 ][ 2 ] == engine.recency_half_life_days
    engine._embedding_store.find_similar.assert_not_called()
    assert result.metadata.get( "reason" ) != REASON_NEITHER_MAJORITY


def test_the_ask_carries_the_title_and_sender_it_was_given( engine, monkeypatch ):
    seen = {}
    monkeypatch.setattr( three_way_stance, "three_way_forecast", lambda ask, cases, half: seen.update( ask ) or { "neighbour_ids": [] } )
    _vote( engine, monkeypatch, [] )
    assert ( seen[ "title" ], seen[ "sender_id" ], seen[ "message" ], seen[ "owner_user_id" ] ) == ( "T", "S", "Proceed?", "u1" )


def test_no_context_gives_the_ask_blank_title_and_sender( engine, monkeypatch ):
    seen = {}
    monkeypatch.setattr( three_way_shadow, "live_cases", lambda session, owner_user_id: [] )
    monkeypatch.setattr( three_way_stance, "three_way_forecast", lambda ask, cases, half: seen.update( ask ) or { "neighbour_ids": [] } )
    engine._predict_yes_no( "Proceed?", "permission", ASK, owner_user_id="u1" )
    assert ( seen[ "title" ], seen[ "sender_id" ] ) == ( "", "" )


@pytest.mark.parametrize( "embedding, owner, cases, reason", [
    ( None, "u1", [], "no_embedding" ),
    ( ASK, None, [], "no_owner" ),
    ( ASK, "u1", [], "no_neighbours" ),
] )
def test_each_missing_input_is_a_named_cold_start( engine, monkeypatch, embedding, owner, cases, reason ):
    result = _vote( engine, monkeypatch, cases, embedding=embedding, owner=owner )
    assert ( result.strategy, result.predicted_value, result.metadata[ "reason" ] ) == ( STRATEGY_COLD_START, None, reason )


def test_predict_core_hands_the_notification_to_the_vote_only_with_the_switch_on( engine, monkeypatch ):
    seen = []
    monkeypatch.setattr( engine, "_predict_yes_no", lambda *a, **k: seen.append( k ) or PredictionResult( "yes_no", "c", STRATEGY_COLD_START ) )
    monkeypatch.setattr( engine, "classifier", SimpleNamespace( classify=lambda message, sender_id=None: ( "c", 1.0 ) ) )
    notification = { "message": "Proceed?", "response_type": "yes_no", "sender_id": "S", "recipient_id": "u1" }
    engine._predict_core( notification, query_vector=ASK )
    engine.lookup_neither_forecast_enabled = False
    engine._predict_core( notification, query_vector=ASK )
    assert seen[ 0 ][ "ask_context" ] is notification and "ask_context" not in seen[ 1 ]


# ---- switch-off pins ----------------------------------------------------------------------------

def test_switch_off_pin_the_old_vote_runs_and_the_three_way_vote_is_never_called( engine, monkeypatch ):
    """With the switch off a neither majority abstains as before.

    The three-way module is not touched.
    """
    engine.lookup_neither_forecast_enabled = False
    monkeypatch.setattr( three_way_stance, "three_way_forecast", lambda *a: pytest.fail( "the three-way vote ran with the switch off" ) )
    monkeypatch.setattr( three_way_shadow, "live_cases", lambda *a: pytest.fail( "cases were loaded with the switch off" ) )
    engine._embedding_store.find_similar.return_value = [ ( 100.0 - i, { "decision_value": a } ) for i, a in enumerate( [ "neither", "neither", "yes" ] ) ]
    result = engine._predict_yes_no( "Proceed?", "permission", ASK )
    assert ( result.strategy, result.predicted_value, result.metadata[ "reason" ] ) == ( STRATEGY_COLD_START, None, REASON_NEITHER_MAJORITY )


def test_switch_off_pin_the_default_is_false():
    from cosa.agents.prediction_engine import config
    assert config.DEFAULT_LOOKUP_NEITHER_FORECAST_ENABLED is False
    PredictionEngine.reset()
    try:
        assert PredictionEngine( debug=False ).lookup_neither_forecast_enabled is False
    finally:
        PredictionEngine.reset()


# ---- each open-ended path is scored by the complete-action measure ------------------------------

@pytest.mark.parametrize( "response_type, predicted, actual", [
    ( "open_ended", "use the cache", "Use the cache" ),
    ( "open_ended_batch", { "answers": { "Q1": "use the cache" } }, json.dumps( { "answers": { "Q1": "Use the cache" } } ) ),
] )
def test_the_open_ended_paths_are_scored_by_the_complete_action_measure( engine, monkeypatch, response_type, predicted, actual ):
    engine.complete_action_scoring_enabled = True
    monkeypatch.setattr( engine, "_enrich_with_embedding_similarity", lambda *a, **k: None )
    seen = {}

    class Repo:
        def __init__( self, session ): pass
        def update_outcome( self, **kwargs ): seen.update( kwargs ); return True

    monkeypatch.setattr( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", Repo )
    monkeypatch.setattr( engine, "_store_decision", lambda *a, **k: None )
    result = PredictionResult( response_type, "c", "cbr_majority_vote", predicted_value=predicted, confidence=0.9 )
    engine.record_outcome( str( uuid.uuid4() ), result, actual, response_type, None, None )
    assert seen[ "accuracy_match" ] is True and seen[ "accuracy_detail" ][ "plain_code_match" ] is True
    assert "similarity_match" in seen[ "accuracy_detail" ]
