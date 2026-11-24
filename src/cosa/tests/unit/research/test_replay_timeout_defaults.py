"""
Unit tests for the replay's timeout-default switch.

A timed-out card holds the card's own default, not a choice.
With the switch on, the replay neither scores that card nor hands it to a baseline as a case.
With the switch off, every row counts as before.
"""
from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, prior_majority_arm, replay
from cosa.rest.db.vector_store_models import EMBEDDING_DIM

SHA    = "0" * 64
NOON   = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
SENDER = "claude.code@lupin.deepily.ai#00000001"
MESSAGE = "Should the synthetic worker proceed?"


@pytest.fixture
def engine():
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    yield eng
    PredictionEngine.reset()


def _ask( engine, ask_id, answer, minutes, timeout_default, source="human" ):
    category, _ = engine.classifier.classify( MESSAGE, sender_id=SENDER )
    vector      = [ 0.0 ] * EMBEDDING_DIM
    vector[ 1 ] = 20.0
    return { "id": ask_id, "question": MESSAGE, "category": category, "decision_value": answer, "ratification_state": "not_required",
             "data_origin": "organic", "response_type": "yes_no", "question_embedding": vector, "created_at": "2026-11-10",
             "owner_user_id": "u1", "answer_source": source, "timeout_default": timeout_default,
             "responded_at": NOON + timedelta( minutes=minutes, seconds=30 ), "title": "W", "message": MESSAGE, "sender_id": SENDER,
             "asked_at": NOON + timedelta( minutes=minutes ), "recipient_id": "u1", "response_options": None, "actual_value": answer }


def _asks( engine ):
    # two timed-out "no" defaults, one human "yes", then a timed-out "no" asked last
    return [ _ask( engine, "t1", "no", 0, True, "unknown" ), _ask( engine, "t2", "no", 10, True, "unknown" ),
             _ask( engine, "h1", "yes", 20, False ), _ask( engine, "t3", "no", 60, True, "unknown" ) ]


def _run( engine, switch ):
    engine._embedding_store = None
    engine.timeout_defaults_excluded_enabled = switch
    return replay( _asks( engine ), engine, SHA, baselines={ "prior_majority": prior_majority_arm } )


def test_with_the_switch_on_a_timeout_default_casts_no_vote_and_is_not_scored( engine ):
    run = _run( engine, True )
    assert run[ "timeout_defaults" ] == 3
    assert [ r[ "meta" ][ "notification_id" ] for r in run[ "records" ][ ENGINE_ARM ] ] == [ "h1" ]
    assert run[ "records" ][ "prior_majority" ][ 0 ][ "meta" ][ "forecast" ] is None   # no non-timeout case was visible before h1


def test_with_the_switch_off_a_timeout_default_casts_a_vote_and_is_scored( engine ):
    run = _run( engine, False )
    assert run[ "timeout_defaults" ] == 0
    assert [ r[ "meta" ][ "notification_id" ] for r in run[ "records" ][ ENGINE_ARM ] ] == [ "t1", "t2", "h1", "t3" ]
    assert run[ "records" ][ "prior_majority" ][ 2 ][ "meta" ][ "forecast" ] == { "value": "no" }   # h1 sees the two timeout "no" cases


def test_the_switch_ships_off( engine ):
    assert engine.timeout_defaults_excluded_enabled is False
