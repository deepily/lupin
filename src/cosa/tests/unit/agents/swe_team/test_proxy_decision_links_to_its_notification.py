"""
A proxy_decisions row carries the id of the notification that asked the question.

The orchestrator used to mint a fresh uuid for every row, so no row joined to notifications.
The first test drives the whole chain with only the HTTP post faked. That is the real SSE reader,
the real dispatcher, the real orchestrator gate and the real repository, into in-memory SQLite.
It reads the row back in a fresh session. The rest hold each hop on its own.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cosa.research.preference_replay.scratch_db   # noqa: F401  registers the SQLite type hooks, JSONB included
import cosa.agents.utils.agent_notification_dispatcher as dispatcher_module
from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher, take_last_ask_notification_id
from cosa.rest.postgres_models import ProxyDecision
from lupin_cli.notifications import notify_user_sync as nus
from lupin_cli.notifications.notification_models import NotificationResponse

NID = "5f0c1d52-8a43-4c07-9d2a-3b6f1e7a9c10"


@pytest.fixture
def factory():
    engine = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    ProxyDecision.__table__.create( engine )
    yield sessionmaker( bind=engine )
    engine.dispose()


def _orchestrator( action="suggest", value="approved" ):
    o = SweTeamOrchestrator(
        task_description="Build X", config=SweTeamConfig( dry_run=True, trust_mode="disabled" ), job_id="swe-1"
    )
    o._ask_before_act = False
    o.proxy = MagicMock()
    o.proxy.trust_mode = "active"
    o.proxy.evaluate.return_value = MagicMock(
        action=action, value=value, category="testing", confidence=0.9, trust_level=3, reason="r"
    )
    return o


def _sse_post( *frames ):
    """A fake requests.post whose streamed body is the given SSE data frames."""
    response             = MagicMock( status_code=200 )
    response.iter_lines  = lambda *a, **k: iter( [ ( "data: " + f ).encode() for f in frames ] )
    return MagicMock( return_value=response )


def _gate( o, team_io, factory ):
    """Run _gated_confirmation against the real repository, writing into the SQLite factory."""
    def get_db():
        from contextlib import contextmanager

        @contextmanager
        def ctx():
            with factory() as s:
                yield s
        return ctx()

    with patch( "cosa.rest.db.database.get_db", get_db ), \
         patch.object( o, "_persist_trust_feedback" ), \
         patch.object( o, "_emit_proxy_summary_notification" ), \
         patch.object( o, "_notify", AsyncMock() ):
        return asyncio.new_event_loop().run_until_complete( o._gated_confirmation( "deploy?", "lead", "no", 60, None, team_io ) )


def _rows( factory ):
    with factory() as fresh:
        return fresh.query( ProxyDecision ).all()


class _RealDispatcherIO:
    """team_io whose ask_confirmation is the real dispatcher's, over a faked HTTP post."""
    def __init__( self ):
        self.dispatcher = AgentNotificationDispatcher( agent_type="swe.team", supports_role=True )

    async def ask_confirmation( self, question, role, default, timeout, abstract ):
        return await self.dispatcher.ask_confirmation( question, default=default, timeout=timeout, abstract=abstract, role=role )

    async def notify_progress( self, *a, **k ): pass


def test_the_stored_notification_id_is_the_id_of_the_notification_that_carried_the_question( factory, monkeypatch ):
    """Mutation test: put `str( uuid.uuid4() )` back in the orchestrator and this reddens."""
    monkeypatch.setenv( "LUPIN_ALLOW_HUMAN_ASK_IN_TESTS", "1" )
    post = _sse_post( '{"status": "ack", "notification_id": "%s"}' % NID,
                      '{"status": "responded", "response": "yes", "default_used": false}' )
    with patch.object( nus.requests, "post", post ):
        approved = _gate( _orchestrator(), _RealDispatcherIO(), factory )
    rows = _rows( factory )
    assert approved is True
    assert [ r.notification_id for r in rows ] == [ NID ]
    assert rows[ 0 ].metadata_json[ "user_answer" ] is True


def test_the_shadow_row_carries_the_id_too( factory, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ALLOW_HUMAN_ASK_IN_TESTS", "1" )
    post = _sse_post( '{"status": "ack", "notification_id": "%s"}' % NID,
                      '{"status": "responded", "response": "no", "default_used": false}' )
    with patch.object( nus.requests, "post", post ):
        _gate( _orchestrator( action="shadow", value=None ), _RealDispatcherIO(), factory )
    row = _rows( factory )[ 0 ]
    assert ( row.notification_id, row.action ) == ( NID, "shadow" )


def test_an_auto_approval_has_no_carrying_notification_so_it_keeps_a_fresh_id( factory ):
    team_io = MagicMock( ask_confirmation=AsyncMock(), notify_progress=AsyncMock() )
    _gate( _orchestrator( action="act" ), team_io, factory )
    row = _rows( factory )[ 0 ]
    assert row.notification_id and row.notification_id != NID
    team_io.ask_confirmation.assert_not_called()


def test_an_ask_that_reported_no_id_falls_back_to_a_fresh_one_rather_than_a_stale_one( factory ):
    dispatcher_module._last_ask_notification_id.set( NID )     # left behind by an earlier ask in this task
    team_io = MagicMock( ask_confirmation=AsyncMock( return_value=True ), notify_progress=AsyncMock() )
    _gate( _orchestrator(), team_io, factory )
    assert _rows( factory )[ 0 ].notification_id != NID


# ---- the hops on their own ----------------------------------------------------------------------

def _send( *frames, monkeypatch=None ):
    request = nus.NotificationRequest( message="q?", response_type=nus.ResponseType.YES_NO, target_user="t@example.com", response_default="no" )
    with patch.object( nus.requests, "post", _sse_post( *frames ) ):
        return nus.notify_user_sync( request )


@pytest.mark.parametrize( "terminal, status", [
    ( '{"status": "responded", "response": "yes", "default_used": false}', "responded" ),
    ( '{"status": "expired", "response": "no", "default_used": true, "timeout": true}', "expired" ),
    ( '{"status": "expired", "response": null, "default_used": false}', "expired_no_default" ),
    ( '{"status": "offline", "response": "yes", "default_used": true}', "offline" ),
    ( '{"status": "error", "message": "boom"}', "error" ),
] )
def test_every_terminal_answer_carries_the_ack_id( terminal, status, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ALLOW_HUMAN_ASK_IN_TESTS", "1" )
    response = _send( '{"status": "ack", "notification_id": "%s"}' % NID, terminal )
    assert ( response.status, response.notification_id ) == ( status, NID )


def test_an_answer_with_no_ack_frame_has_no_id( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ALLOW_HUMAN_ASK_IN_TESTS", "1" )
    assert _send( '{"status": "responded", "response": "yes", "default_used": false}' ).notification_id is None


@pytest.mark.parametrize( "row, state", [
    ( { "responded_at": "2026-11-20T10:00:00", "response_value": { "value": "yes" } }, "responded" ),
    ( { "responded_at": None, "response_value": { "value": "no" } }, "expired" ),
] )
def test_a_reattached_answer_keeps_the_id( row, state ):
    with patch.object( nus.time, "sleep" ):
        out = nus._reattach_after_stream_death( NID, 5.0, "http://x", {}, poll_fn=lambda nid: row, poll_interval=0.0 )
    assert ( out.status, out.notification_id ) == ( state, NID )


def test_a_reattach_that_runs_out_of_budget_keeps_the_id():
    out = nus._reattach_after_stream_death( NID, 0.0, "http://x", {}, poll_fn=lambda nid: { "responded_at": None, "response_value": None }, poll_interval=0.0 )
    assert ( out.exit_code, out.notification_id ) == ( 2, NID )


def test_the_dispatcher_hands_the_id_over_once_and_then_forgets_it():
    dispatcher = AgentNotificationDispatcher( agent_type="swe.team", supports_role=True )
    reply      = NotificationResponse( response_value="yes", exit_code=0, status="responded", notification_id=NID )
    with patch.object( dispatcher_module, "_notify_user_sync", return_value=reply ):
        assert asyncio.new_event_loop().run_until_complete( dispatcher.ask_confirmation( "q?", role="lead" ) ) is True
    assert take_last_ask_notification_id() == NID
    assert take_last_ask_notification_id() is None
