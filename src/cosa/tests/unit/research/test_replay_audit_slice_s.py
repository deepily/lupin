"""
Unit tests for the replay switch and the three-way report probability scores.
"""
from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay import replay_loop
from cosa.research.preference_replay import three_way_report as report
from cosa.research.preference_replay.calibration_fit import multiclass_brier, neither_recall_precision
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, replay
from cosa.rest.db.vector_store_models import EMBEDDING_DIM

SHA    = "0" * 64
NOON   = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
SENDER = "claude.code@lupin.deepily.ai#00000001"
CARD   = { "questions": [ { "header": "Mode", "options": [ { "label": "Fast" }, { "label": "Safe" } ] },
                          { "header": "DB", "options": [ { "label": "Postgres" }, { "label": "SQLite" } ] } ] }


def _p( yes, no, neither ): return { "yes": yes, "no": no, "neither": neither }


def test_b3_score_reads_a_typed_other_per_field_only_when_told_the_switch_is_on():
    predicted = { "answers": { "Mode": "Fast", "DB": "Postgres" } }
    actual    = { "answers": { "Mode": "Fast", "DB": "Use DuckDB" } }
    assert replay_loop._score( "multiple_choice", predicted, actual, CARD ) is False
    assert replay_loop._score( "multiple_choice", predicted, actual, CARD, per_field=True ) is True


@pytest.fixture
def engine():
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "embedded" )
    yield eng
    PredictionEngine.reset()


@pytest.mark.parametrize( "switch", [ True, False ] )
def test_b3_replay_scores_with_the_switch_the_engine_reads( engine, monkeypatch, switch ):
    engine.per_field_mc_enabled = switch
    seen = []
    real = replay_loop._score
    def spy( *args, **kwargs ):
        seen.append( kwargs.get( "per_field" ) )
        return real( *args, **kwargs )
    monkeypatch.setattr( replay_loop, "_score", spy )
    message = "Should the synthetic worker proceed?"
    category, _ = engine.classifier.classify( message, sender_id=SENDER )
    vector = [ 0.0 ] * EMBEDDING_DIM
    vector[ 1 ] = 20.0
    ask = { "id": "a", "question": message, "category": category, "decision_value": "yes", "ratification_state": "not_required",
            "data_origin": "organic", "response_type": "yes_no", "question_embedding": vector, "created_at": "2026-11-10",
            "owner_user_id": "u1", "answer_source": "human", "responded_at": NOON + timedelta( minutes = 1 ), "title": "W",
            "message": message, "sender_id": SENDER, "asked_at": NOON, "recipient_id": "u1", "response_options": None, "actual_value": "yes" }
    replay( [ ask ], engine, SHA )
    assert seen and set( seen ) == { switch }


def _records( name, forecasts ):
    return [ { "arm": name, "meta": { "notification_id": f"a{i}", "correct": True, "response_type": "yes_no", "forecast": f } }
             for i, f in enumerate( forecasts ) ]


def _run( challenger, margin ):
    n = len( challenger )
    return { "records": { report.THREE_WAY_ARM: _records( report.THREE_WAY_ARM, challenger ), ENGINE_ARM: _records( ENGINE_ARM, margin ),
                          report.BASELINE_ARM: _records( report.BASELINE_ARM, [ { "value": "yes" } ] * n ) },
             "not_replayable": 0, "unrebuildable_cases": 0, "families": 1 }


ANSWERS = [ "yes", "no", "neither", "neither" ]


def _asks(): return [ { "id": f"a{i}", "actual_value": { "value": a } } for i, a in enumerate( ANSWERS ) ]


def test_b4_the_arm_keeps_the_three_probabilities_in_its_forecast():
    arm  = report.make_three_way_arm( 14 )
    case = lambda i, answer: { "id": f"c{i}", "question": "q", "category": "permission", "decision_value": answer,
                               "ratification_state": "not_required", "data_origin": "organic", "response_type": "yes_no",
                               "question_embedding": [ 1.0, 0.0 ], "created_at": "x", "owner_user_id": "user-1",
                               "answer_source": "human", "responded_at": NOON - timedelta( days=1 ) }
    ask = { "id": "ask", "response_type": "yes_no", "category": "permission", "title": "T", "message": "M", "sender_id": SENDER,
            "asked_at": NOON, "question_embedding": [ 1.0, 0.0 ], "owner_user_id": "user-1" }
    got = arm( ask, [ case( 0, "no" ) ] )
    assert set( got[ "probabilities" ] ) == { "yes", "no", "neither" } and sum( got[ "probabilities" ].values() ) == pytest.approx( 1.0 )


def test_b4_the_report_calls_both_scorers_on_the_probabilities_the_arm_forecast():
    probs = [ _p( .8, .1, .1 ), _p( .2, .7, .1 ), _p( .1, .2, .7 ), _p( .5, .3, .2 ) ]
    run   = _run( [ { "value": "yes", "probabilities": p } for p in probs ], [ { "value": "yes" } ] * 4 )
    got   = report.build_report( run, _asks(), 6, neither_threshold=0.5 )[ "arms" ][ report.THREE_WAY_ARM ][ "probability_scores" ]
    assert got[ "scored" ] == 4 and got[ "without_probabilities" ] == 0
    assert got[ "multiclass_brier" ] == multiclass_brier( probs, ANSWERS )
    assert got[ "neither" ] == neither_recall_precision( probs, ANSWERS, 0.5 )
    assert got[ "neither_threshold" ] == 0.5 and got[ "neither" ][ "recall" ] == 0.5


def test_b4_an_arm_with_no_probabilities_is_counted_and_not_scored():
    run = _run( [ { "value": "yes" }, None, { "value": "no" }, { "value": "no" } ], [ { "value": "yes" } ] * 4 )
    got = report.build_report( run, _asks(), 6, neither_threshold=0.5 )[ "arms" ]
    assert got[ ENGINE_ARM ][ "probability_scores" ] == { "scored": 0, "without_probabilities": 4 }
    assert got[ report.THREE_WAY_ARM ][ "probability_scores" ] == { "scored": 0, "without_probabilities": 4 }


def test_b4_a_forecast_whose_answer_is_not_a_stance_is_left_out_and_counted():
    run  = _run( [ { "value": "yes", "probabilities": _p( .8, .1, .1 ) } ] * 4, [ { "value": "yes" } ] * 4 )
    asks = _asks()
    asks[ 0 ][ "actual_value" ] = { "value": "maybe" }
    got  = report.build_report( run, asks, 6, neither_threshold=0.5 )[ "arms" ][ report.THREE_WAY_ARM ][ "probability_scores" ]
    assert ( got[ "scored" ], got[ "without_probabilities" ] ) == ( 3, 1 )


def test_b4_no_threshold_is_chosen_here_so_without_one_only_the_brier_is_reported():
    probs = [ _p( .8, .1, .1 ) ] * 4
    run   = _run( [ { "value": "yes", "probabilities": p } for p in probs ], [ { "value": "yes" } ] * 4 )
    got   = report.build_report( run, _asks(), 6 )[ "arms" ][ report.THREE_WAY_ARM ][ "probability_scores" ]
    assert "multiclass_brier" in got and "neither" not in got and "neither_threshold" not in got
