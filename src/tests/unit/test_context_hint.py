"""
The baseline forecast as a card shows it, from payload to settle.

Everything runs over in-memory SQLite with the real run_arm and a stand-in for the SDK, so no test calls a model.

Each test names what it would catch:
  - a payload state a client has no text for                        -> test_payload_for_*
  - an event sent with display off, or no event with it on          -> test_the_event_*
  - a restart leaving a card with no terminal state                 -> test_settle_*
  - a job failure reaching the ask                                  -> test_a_failure_*
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import cosa.agents.prediction_engine.context_baseline as cb
import cosa.agents.prediction_engine.context_hint as ch
import cosa.agents.prediction_engine.episode_view as ev
from cosa.agents.prediction_engine.principles_forecast import CapGate
from cosa.research.preference_replay import scratch_db  # noqa: F401  registers the one shared SQLite hooks for JSONB and Vector
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog

T0        = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
RECIPIENT = uuid.UUID( "00000000-0000-4000-8000-0000000000cc" )
SENDER    = "claude.code@lupin.deepily.ai#ab12cd34"
YES       = '{"answer": "yes", "confidence": 0.9}'
CHOICES   = { "questions": [ { "header": "Plan", "question": "Which plan?", "options": [ { "label": "A" }, { "label": "B" } ] } ] }


@pytest.fixture
def factory( monkeypatch ):
    """Give a session factory over empty copies of the tables the job and the hint read or write."""
    engine = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in ( Notification, PredictionLog, PredictionArmForecast ): model.__table__.create( engine )
    monkeypatch.setattr( ev, "pool_limit", lambda: 50 )
    yield lambda: Session( engine )
    engine.dispose()


def ask( factory, **extra ):
    """Insert one ask and return its id as text."""
    row = dict( id=uuid.uuid4(), sender_id=SENDER, recipient_id=RECIPIENT, title="Ship it?", message="Should the worker ship?", abstract="the plan",
                type="task", priority="medium", created_at=T0, response_requested=True, response_type="yes_no", response_default="no", timeout_seconds=120 )
    row.update( extra )
    with factory() as db:
        db.add( Notification( **row ) )
        db.commit()
    return str( row[ "id" ] )


def baseline( tmp_path, reply=YES ):
    """Build a baseline whose model always answers with reply."""
    async def query( prompt, options ):
        yield AssistantMessage( content=[ TextBlock( reply ) ], model=options.model )
    return cb.ContextBaseline( "haiku-x", 5, cb.ALL_LAYERS, cb.open_ledger( str( tmp_path / "ledger.jsonl" ) ), query_fn=query )


def arm_rows( factory ):
    """All sibling rows."""
    with factory() as db: return db.query( PredictionArmForecast ).all()


@pytest.mark.parametrize( "kind,review,injected,expected", [
    ( "yes_no", False, False, True ), ( "multiple_choice", False, False, True ),
    ( "open_ended", False, False, False ), ( "yes_no", True, False, False ), ( "yes_no", False, True, False ),
] )
def test_only_a_plain_yes_no_or_choice_card_is_forecast( kind, review, injected, expected ):
    assert ch.should_forecast( kind, review, injected ) is expected


def test_the_ready_payload_carries_the_value_the_confidence_and_the_metric():
    assert ch.ready_payload( { "value": "yes", "confidence": 0.91234 }, "cosine" ) == {
        "state": "ready", "retrieval_metric": "cosine", "strategy": "context_baseline", "predicted_value": "yes", "confidence": 0.912 }
    choice = ch.ready_payload( { "answers": { "Plan": "A" }, "confidence": 0.5 }, "dot" )
    assert choice[ "predicted_value" ] == { "answers": { "Plan": "A" } } and choice[ "retrieval_metric" ] == "dot"


def test_payload_for_names_every_state_a_card_can_be_in( factory, tmp_path ):
    nid = ask( factory )
    asked = T0
    assert ch.payload_for( None, asked, asked + timedelta( seconds=29 ), "cosine" ) == { "state": "forecasting" }
    assert ch.payload_for( None, asked, asked + timedelta( seconds=30 ), "cosine" ) == { "state": "forecast_timed_out" }, "still no row 30 seconds on"
    asyncio.run( cb.run_context_forecast( nid, session_factory=factory, c0=baseline( tmp_path ), gate=CapGate( 1 ), enabled=True ) )
    ready = ch.payload_for( arm_rows( factory )[ 0 ], asked, asked + timedelta( seconds=5 ), "cosine" )
    assert ready[ "state" ] == "ready" and ready[ "predicted_value" ] == "yes" and ready[ "confidence" ] == 0.9
    class Row:
        forecast = None
        forecast_ready_at = None
        abstention_reason = "model_error: ModelCallTimeout"
    assert ch.payload_for( Row, asked, asked, "cosine" ) == { "state": "unavailable", "reason": "model_error: ModelCallTimeout" }
    Row.abstention_reason = "forecast_timed_out"
    assert ch.payload_for( Row, asked, asked, "cosine" ) == { "state": "forecast_timed_out" }


def test_read_payload_reads_the_row_and_the_ask_time_from_the_database( factory, tmp_path ):
    nid = ask( factory )
    assert ch.read_payload( factory, nid, T0 + timedelta( seconds=1 ), "cosine" ) == { "state": "forecasting" }
    asyncio.run( cb.run_context_forecast( nid, session_factory=factory, c0=baseline( tmp_path ), gate=CapGate( 1 ), enabled=True ) )
    assert ch.read_payload( factory, nid, T0 + timedelta( seconds=1 ), "cosine" )[ "state" ] == "ready"
    assert ch.read_payload( factory, str( uuid.uuid4() ), T0, "cosine" ) is None
    with pytest.raises( ValueError ): ch.read_payload( factory, "not-a-uuid", T0, "cosine" )


@pytest.fixture
def switches( monkeypatch ):
    """Set the two switches the module reads."""
    state = { "forecast": True, "display": True }
    monkeypatch.setattr( cb, "context_forecast_enabled", lambda: state[ "forecast" ] )
    monkeypatch.setattr( cb, "context_display_enabled", lambda: state[ "display" ] )
    return state


def test_settle_stores_the_terminal_state_for_an_answered_card_with_no_row( factory, switches ):
    nid = ask( factory )
    assert ch.settle_unfinished( factory, nid ) is True
    row = arm_rows( factory )[ 0 ]
    assert ( row.arm, row.forecast, row.forecast_ready_at, row.abstention_reason ) == ( "C0", None, None, "forecast_timed_out" )
    assert ch.read_payload( factory, nid, T0, "cosine" ) == { "state": "forecast_timed_out" }, "the card reads the stored state, not the clock"
    assert ch.settle_unfinished( factory, nid ) is False and len( arm_rows( factory ) ) == 1, "a second settle changes nothing"


def test_settle_leaves_alone_a_card_that_has_a_row_or_is_not_the_jobs_to_forecast( factory, switches, tmp_path ):
    done = ask( factory )
    asyncio.run( cb.run_context_forecast( done, session_factory=factory, c0=baseline( tmp_path ), gate=CapGate( 1 ), enabled=True ) )
    assert ch.settle_unfinished( factory, done ) is False
    assert ch.settle_unfinished( factory, ask( factory, response_type="open_ended" ) ) is False
    assert ch.settle_unfinished( factory, ask( factory, response_options={ "review_card": True } ) ) is False
    injected = ask( factory )
    with factory() as db:
        db.add( PredictionLog( notification_id=uuid.UUID( injected ), response_type="yes_no", category="c", prediction_confidence=0.0, prediction_strategy="test_override",
                               similar_case_count=0, forecast_source="test_override", predicted_at=T0 ) )
        db.commit()
    assert ch.settle_unfinished( factory, injected ) is False
    assert len( arm_rows( factory ) ) == 1


def test_settle_does_nothing_with_the_switch_off_and_refuses_a_card_that_does_not_exist( factory, switches ):
    nid = ask( factory )
    switches[ "forecast" ] = False
    assert ch.settle_unfinished( factory, nid ) is False and arm_rows( factory ) == []
    switches[ "forecast" ] = True
    with pytest.raises( LookupError ): ch.settle_unfinished( factory, str( uuid.uuid4() ) )


def run_publish( factory, nid, run, emitted, clock=None ):
    """Run the job and the publish for one card, recording each event."""
    return asyncio.run( ch.run_and_publish( nid, lambda event, data: emitted.append( ( event, data ) ), "cosine", session_factory=factory, run=run, clock=clock ) )


def job( tmp_path, **kwargs ):
    """Build the job stand-in: the real run_context_forecast over a stand-in model."""
    async def run( nid, session_factory ):
        return await cb.run_context_forecast( nid, session_factory=session_factory, c0=baseline( tmp_path, **kwargs ), gate=CapGate( 1 ), enabled=True )
    return run


def test_the_event_carries_the_ready_payload_when_display_is_on( factory, switches, tmp_path ):
    nid, emitted = ask( factory ), []
    result = run_publish( factory, nid, job( tmp_path ), emitted )
    assert result[ "status" ] == "ran" and len( emitted ) == 1
    event, data = emitted[ 0 ]
    assert event == "prediction_hint_updated" and data[ "notification_id" ] == nid
    assert data[ "context_forecast" ][ "state" ] == "ready" and data[ "context_forecast" ][ "predicted_value" ] == "yes"


def test_the_event_is_not_sent_with_display_off_but_the_job_still_ran( factory, switches, tmp_path ):
    switches[ "display" ] = False
    emitted = []
    result  = run_publish( factory, ask( factory ), job( tmp_path ), emitted )
    assert result[ "status" ] == "ran" and emitted == [] and len( arm_rows( factory ) ) == 1


def test_the_event_carries_the_not_ready_state_when_the_job_failed( factory, switches, tmp_path ):
    emitted = []
    run_publish( factory, ask( factory ), job( tmp_path, reply="no idea" ), emitted )
    assert emitted[ 0 ][ 1 ][ "context_forecast" ] == { "state": "unavailable", "reason": "unreadable_forecast" }


def test_a_failure_of_the_job_the_read_or_the_emit_never_reaches_the_ask( factory, switches, tmp_path, capsys ):
    async def exploding( nid, session_factory ): raise RuntimeError( "the job broke" )
    emitted = []
    assert run_publish( factory, ask( factory ), exploding, emitted ) is None and emitted == []
    assert "Job for" in capsys.readouterr().out
    def refusing( event, data ): raise RuntimeError( "socket gone" )
    result = asyncio.run( ch.run_and_publish( ask( factory ), refusing, "cosine", session_factory=factory, run=job( tmp_path ) ) )
    assert result[ "status" ] == "ran" and "Publish for" in capsys.readouterr().out


def test_nothing_is_sent_for_a_card_the_database_no_longer_has( factory, switches ):
    emitted = []
    async def run( nid, session_factory ): return { "status": "not_run", "reason": "x" }
    run_publish( factory, str( uuid.uuid4() ), run, emitted )
    assert emitted == []


def test_the_defaults_are_the_real_job_the_apps_sessions_and_the_wall_clock( factory, switches, monkeypatch, tmp_path ):
    import cosa.rest.db.database as database
    monkeypatch.setattr( database, "get_db", factory )
    monkeypatch.setattr( cb, "get_baseline", lambda: ( baseline( tmp_path ), CapGate( 1 ) ) )
    monkeypatch.setattr( cb, "switch_enabled", lambda key: True )
    emitted = []
    result  = asyncio.run( ch.run_and_publish( ask( factory ), lambda event, data: emitted.append( data ), "cosine" ) )
    assert result[ "status" ] == "ran" and emitted[ 0 ][ "context_forecast" ][ "state" ] == "ready"
