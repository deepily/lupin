"""
Unit tests for the replay's complete-action figures.

They cover the switch-off pin on every record, the fields each record gains when on, and the summary.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay import replay_loop
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, complete_action_summary, replay
from cosa.rest.db.vector_store_models import EMBEDDING_DIM

SHA    = "0" * 64
NOON   = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
SENDER = "claude.code@lupin.deepily.ai#00000001"


def _ask( engine, ask_id, axis, minutes, answer ):
    message  = f"Should the synthetic worker {ask_id} proceed?"
    category, _ = engine.classifier.classify( message, sender_id=SENDER )
    asked    = NOON + timedelta( minutes=minutes )
    vector   = [ 0.0 ] * EMBEDDING_DIM
    vector[ axis ] = 20.0
    return { "id": ask_id, "question": message, "category": category, "decision_value": answer, "ratification_state": "not_required",
             "data_origin": "organic", "response_type": "yes_no", "question_embedding": vector, "created_at": "2026-11-10",
             "owner_user_id": "u1", "answer_source": "human", "responded_at": asked + timedelta( minutes=1 ), "title": f"W {ask_id}",
             "message": message, "sender_id": SENDER, "asked_at": asked, "recipient_id": "u1", "response_options": None, "actual_value": answer }


@pytest.fixture
def engine():
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "embedded" )
    yield eng
    PredictionEngine.reset()


def _asks( engine ):
    return [ _ask( engine, "a", 1, 0, "yes" ), _ask( engine, "b", 1, 10, "yes" ), _ask( engine, "c", 2, 20, "yes [comment: only the old files]" ) ]


def test_switch_off_pin_a_record_holds_no_complete_action_key( engine ):
    run = replay( _asks( engine ), engine, SHA )
    assert all( "complete_action" not in r[ "meta" ] and "complete_action_decided" not in r[ "meta" ] for r in run[ "records" ][ ENGINE_ARM ] )


def test_switch_off_pin_score_with_the_default_is_the_stance_score():
    answer = "yes [comment: only the old files]"
    assert replay_loop._score( "yes_no", { "value": "yes" }, answer, None ) is True
    assert replay_loop._score( "yes_no", { "value": "yes" }, answer, None, complete_action=True ) is False


def test_on_each_record_carries_the_stance_score_and_the_whole_action_score_apart( engine ):
    run = replay( _asks( engine ), engine, SHA, complete_action=True, baselines={} )
    records = run[ "records" ][ ENGINE_ARM ]
    # a: no earlier case, so no forecast, an abstention: decided, not a success. b: yes against yes. c: no vector match, abstention.
    assert [ r[ "meta" ][ "correct" ] for r in records ] == [ False, True, False ]
    assert [ r[ "meta" ][ "complete_action" ] for r in records ] == [ False, True, False ]
    assert [ r[ "meta" ][ "complete_action_decided" ] for r in records ] == [ True, True, True ]


def test_the_summary_publishes_coverage_and_pass_rate_on_the_cards_it_answers():
    def record( passed, decided ):
        return { "meta": { "complete_action": passed, "complete_action_decided": decided } }
    run = { "records": { ENGINE_ARM: [ record( True, True ), record( False, True ), record( False, False ), record( False, False ) ] } }
    assert complete_action_summary( run ) == { "cards": 4, "decided": 2, "coverage": 0.5, "passed": 1, "pass_rate": 0.5, "complete_action_accuracy": 0.25 }


def test_the_summary_of_an_empty_run_is_zero_not_an_error():
    assert complete_action_summary( { "records": { ENGINE_ARM: [] } } ) == { "cards": 0, "decided": 0, "coverage": 0.0, "passed": 0, "pass_rate": 0.0, "complete_action_accuracy": 0.0 }
