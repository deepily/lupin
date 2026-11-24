"""
The two stored forecasts a decision row records in shadow, read back.

The full-answer arm's rows come from the real producer: context_baseline.run_context_forecast over a stand-in model.
Each reader is told what it stored, and the tests read the row back through it.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import cosa.agents.prediction_engine.context_baseline as cb
import cosa.agents.prediction_engine.episode_view as ev
import cosa.agents.prediction_engine.full_answer as fa
from cosa.agents.decision_proxy import shadow_stances as ss
from cosa.agents.prediction_engine.principles_forecast import CapGate
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the one shared SQLite hooks for JSONB and Vector
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog

T0        = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
RECIPIENT = uuid.UUID( "00000000-0000-4000-8000-0000000000bb" )
SENDER    = "claude.code@lupin.deepily.ai#ab12cd34"
OLD_REPLY = json.dumps( { "answer": "yes", "confidence": 0.9 } )


@pytest.fixture
def factory( monkeypatch ):
    """Give a session factory over empty copies of the three tables the readers touch."""
    engine = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in ( Notification, PredictionLog, PredictionArmForecast ): model.__table__.create( engine )
    monkeypatch.setattr( ev, "pool_limit", lambda: 50 )
    yield lambda: Session( engine )
    engine.dispose()


def ask( factory ):
    """Insert one yes/no ask and return its id as text."""
    row = dict( id=uuid.uuid4(), sender_id=SENDER, recipient_id=RECIPIENT, title="Ship it?", message="Should the worker ship?", abstract="the plan",
                type="task", priority="medium", created_at=T0, response_requested=True, response_type="yes_no", response_default="no", timeout_seconds=120 )
    with factory() as db:
        db.add( Notification( **row ) )
        db.commit()
    return str( row[ "id" ] )


def full_reply( yes, no, neither ):
    """Build a full-answer yes/no reply the parser accepts, with these three probabilities."""
    return json.dumps( { "probabilities": { "yes": yes, "no": no, "neither": neither }, "acts": { act: 0.1 for act in fa.ACTS },
                         "qualification": { "probability": 0.25, "conditions": [ { "text": "leave config alone", "modifies_option_id": None } ] },
                         "gist": "yes, but leave config alone", "whole_card_probability": 0.6 } )


def run_c0( factory, tmp_path, nid, text, full=True ):
    """Run the real baseline job on one ask, with a stand-in model that always answers text."""
    async def query( prompt, options ):
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )
    c0 = cb.ContextBaseline( "haiku-x", 5, cb.ALL_LAYERS, cb.open_ledger( str( tmp_path / "ledger.jsonl" ) ), query_fn=query, full=full )
    return asyncio.run( cb.run_context_forecast( nid, session_factory=factory, c0=c0, gate=CapGate( 2 ), enabled=True ) )


def read_full( factory, nid ):
    with factory() as db: return ss.full_answer_stance( db, nid )


# --------------------------------------------------------------------------- the full-answer arm
@pytest.mark.parametrize( "probabilities, value", [ ( ( 0.7, 0.2, 0.1 ), "yes" ), ( ( 0.1, 0.2, 0.7 ), "neither" ), ( ( 0.2, 0.7, 0.1 ), "no" ) ] )
def test_a_finished_full_answer_forecast_reads_back_as_its_stance_and_probabilities( factory, tmp_path, monkeypatch, probabilities, value ):
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: True )
    nid = ask( factory )
    assert run_c0( factory, tmp_path, nid, full_reply( *probabilities ) ) == { "status": "ran", "reason": None }
    stance = read_full( factory, nid )
    assert stance[ "value" ] == value
    assert stance[ "probabilities" ] == dict( zip( ( "yes", "no", "neither" ), probabilities ) )
    assert stance[ "confidence" ] == max( probabilities )


def test_an_ask_with_no_baseline_row_says_so( factory ):
    assert read_full( factory, ask( factory ) ) == { "status": ss.STATUS_NO_BASELINE_ROW }


def test_an_abstention_names_its_reason_and_has_no_value( factory, tmp_path, monkeypatch ):
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: True )
    nid = ask( factory )
    run_c0( factory, tmp_path, nid, json.dumps( { "abstain": True, "reason": "unclear" } ) )
    assert read_full( factory, nid ) == { "status": ss.STATUS_UNAVAILABLE, "reason": fa.REASON_MODEL_ABSTAINED }


def test_a_forecast_in_the_old_reply_format_has_no_probabilities( factory, tmp_path, monkeypatch ):
    monkeypatch.setattr( fa, "full_answer_enabled", lambda: False )
    nid = ask( factory )
    assert run_c0( factory, tmp_path, nid, OLD_REPLY, full=False )[ "status" ] == "ran"
    assert read_full( factory, nid ) == { "status": ss.STATUS_NO_PROBABILITIES }


@pytest.mark.parametrize( "forecast", [
    { "value": "maybe", "probabilities": { "yes": 0.5, "no": 0.3, "neither": 0.2 }, "confidence": 0.5 },
    { "value": "yes", "probabilities": [ 0.5, 0.3, 0.2 ], "confidence": 0.5 },
    { "value": "yes", "confidence": 0.5 },
    [ "yes" ],
] )
def test_a_stored_forecast_that_is_not_a_three_stance_record_has_no_probabilities( factory, forecast ):
    nid = ask( factory )
    with factory() as db:
        db.add( PredictionArmForecast( notification_id=uuid.UUID( nid ), arm=cb.ARM, forecast=forecast, forecast_ready_at=T0 ) )
        db.commit()
    assert read_full( factory, nid ) == { "status": ss.STATUS_NO_PROBABILITIES }


def test_a_row_with_a_forecast_but_no_ready_time_is_unavailable( factory ):
    nid = ask( factory )
    with factory() as db:
        db.add( PredictionArmForecast( notification_id=uuid.UUID( nid ), arm=cb.ARM, forecast={ "value": "yes" }, abstention_reason="forecast_timed_out" ) )
        db.commit()
    assert read_full( factory, nid ) == { "status": ss.STATUS_UNAVAILABLE, "reason": "forecast_timed_out" }


def test_another_arms_row_is_not_read_as_the_baseline( factory ):
    nid = ask( factory )
    with factory() as db:
        db.add( PredictionArmForecast( notification_id=uuid.UUID( nid ), arm="B1", forecast={ "value": "yes", "probabilities": { "yes": 1.0, "no": 0.0, "neither": 0.0 } }, forecast_ready_at=T0 ) )
        db.commit()
    assert read_full( factory, nid ) == { "status": ss.STATUS_NO_BASELINE_ROW }


def test_an_id_that_is_not_a_uuid_raises_for_the_caller_to_name( factory ):
    with pytest.raises( ValueError ), factory() as db: ss.full_answer_stance( db, "n-1" )


# --------------------------------------------------------------------------- the lookup three-way stance
def three_way_reader( row ):
    """Read the three-way stance through a repository that answers with row."""
    repo = MagicMock()
    repo.return_value.get_by_notification_id.return_value = row
    with patch( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository", repo ):
        return ss.stored_three_way_stance( MagicMock(), "n-1" )


STORED = { "value": "neither", "confidence": 0.5, "probabilities": { "yes": 0.3, "no": 0.2, "neither": 0.5 }, "neighbours": 4 }


def test_a_stored_three_way_stance_comes_back_as_stored():
    assert three_way_reader( SimpleNamespace( three_way_shadow=STORED ) ) == STORED


def test_a_notification_with_no_row_says_so():
    assert three_way_reader( None ) == { "status": ss.STATUS_NO_FORECAST_ROW }


@pytest.mark.parametrize( "stored", [ None, [], "", 0, {} ] )
def test_an_empty_column_reads_as_not_recorded( stored ):
    assert three_way_reader( SimpleNamespace( three_way_shadow=stored ) ) == { "status": ss.STATUS_NOT_RECORDED }


@pytest.mark.parametrize( "stored, type_name", [ ( [ "neither" ], "list" ), ( "oops", "str" ), ( 5, "int" ) ] )
def test_a_stored_value_that_is_not_a_dict_is_named_malformed( stored, type_name ):
    assert three_way_reader( SimpleNamespace( three_way_shadow=stored ) ) == { "status": ss.STATUS_MALFORMED, "stored_type": type_name }
