"""
Real-socket tests for the v1-arm WS producer (WsJobEventListener / ws_recv_events).

This is the seam that feeds the paired v1 baseline: it captures job_state_transition
frames off the live queue WebSocket and hands one job's frames to parse_transitions.
Per Mr. Radio's constraint, these tests run against a REAL in-process websockets server
(genuine TCP, real auth handshake, real frames) — NEVER a mock that returns the shape we
hope for. The whole paired row exists because a harness that authenticates but measures
wrong fails quietly; a shape-mock here would reproduce exactly that blind spot.

What is proven:
  · happy path — queued→running→completed frames arriving AFTER connect are all captured
    (the connect-before-push guarantee: no early frame is missed), reduced correctly.
  · filtering — a job's wait is satisfied only by ITS OWN frames, never another job's.
  · refuse-on-timeout — a job that never terminalizes RAISES, never returns a partial span.
  · refuse-on-empty — a job with zero frames RAISES too (not an empty result).

Venue: :7999-eligible — hermetic, no Lupin server, no inference, sub-second (own socket).
"""

import asyncio
import json
import os
import sys
import threading

import pytest

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SCRIPTS = os.path.join( _LUPIN_ROOT, "src", "scripts" )
    if _SCRIPTS not in sys.path:
        sys.path.insert( 0, _SCRIPTS )

import v1_eval_arm as arm                                     # noqa: E402


# ---------------------------------------------------------------------------
# A real, in-process websockets server that auths then streams a scripted set
# of frames — a genuine socket the listener connects to over TCP.
# ---------------------------------------------------------------------------
class _ScriptedWsServer:
    """Auth a client, stream `frames` (list of dicts), then hold the connection open."""

    def __init__( self, frames ):
        self.frames  = frames
        self.host     = "127.0.0.1"
        self.port     = None
        self._loop    = None
        self._thread  = None
        self._server  = None
        self._ready   = threading.Event()

    async def _handler( self, ws ):
        raw = await ws.recv()                       # the client's auth_request
        json.loads( raw )                           # (shape-tolerant: we only need it to arrive)
        await ws.send( json.dumps( { "type": "auth_success" } ) )
        for frame in self.frames:
            await ws.send( json.dumps( frame ) )
        await ws.wait_closed()                      # keep the socket open until the client stops

    async def _serve( self ):
        from websockets.asyncio.server import serve
        self._server = await serve( self._handler, self.host, 0 )
        self.port    = self._server.sockets[ 0 ].getsockname()[ 1 ]
        self._ready.set()

    def _run( self ):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop( self._loop )
        self._loop.create_task( self._serve() )
        self._loop.run_forever()

    def start( self ):
        self._thread = threading.Thread( target=self._run, name="scripted-ws-server", daemon=True )
        self._thread.start()
        assert self._ready.wait( 5.0 ), "scripted WS server did not bind"
        return self

    @property
    def base_url( self ):
        return f"http://{self.host}:{self.port}"

    def stop( self ):
        if self._loop is not None:
            self._loop.call_soon_threadsafe( self._loop.stop )
        if self._thread is not None:
            self._thread.join( timeout=3.0 )


def _frame( job_id, to_state, ts, *, from_state="pending", metadata=None ):
    """A job_state_transition frame in the SHIPPED flat shape the server emits."""
    f = { "type": "job_state_transition", "job_id": job_id,
          "from_state": from_state, "to_state": to_state, "timestamp": ts }
    if metadata is not None:
        f[ "metadata" ] = metadata
    return f


@pytest.fixture
def server_factory():
    """Yield a factory that starts scripted servers and tears them ALL down after."""
    started = []
    def _make( frames ):
        srv = _ScriptedWsServer( frames ).start()
        started.append( srv )
        return srv
    yield _make
    for srv in started:
        srv.stop()


# ---------------------------------------------------------------------------
# Happy path — all frames after connect are captured and reduce correctly.
# ---------------------------------------------------------------------------
def test_captures_full_transition_sequence_and_reduces( server_factory ):
    frames = [
        _frame( "j1", "queued",    "2026-08-16T12:00:00+00:00" ),
        _frame( "j1", "running",   "2026-08-16T12:00:01+00:00" ),
        _frame( "j1", "completed", "2026-08-16T12:00:03+00:00", from_state="running",
                metadata={ "agent_type": "MathAgent" } ),
    ]
    srv      = server_factory( frames )
    listener = arm.WsJobEventListener( srv.base_url, token="jwt", session_id="s-happy",
                                       collect_timeout=5.0 ).start()
    try:
        got = listener.ws_recv_events( "j1" )
        assert [ e[ "to_state" ] for e in got ] == [ "queued", "running", "completed" ]
        # The reduction the arm actually consumes:
        reduced = arm.parse_transitions( got )
        assert reduced[ "queued_ts" ]    is not None
        assert reduced[ "running_ts" ]   is not None
        assert reduced[ "completed_ts" ] is not None
        assert reduced[ "metadata" ]     == { "agent_type": "MathAgent" }
    finally:
        listener.stop()


# ---------------------------------------------------------------------------
# Filtering — a job's wait is satisfied only by its own frames.
# ---------------------------------------------------------------------------
def test_filters_by_job_id( server_factory ):
    frames = [
        _frame( "jA", "queued",    "2026-08-16T12:00:00+00:00" ),
        _frame( "jB", "queued",    "2026-08-16T12:00:00+00:00" ),
        _frame( "jB", "running",   "2026-08-16T12:00:01+00:00" ),
        _frame( "jB", "completed", "2026-08-16T12:00:02+00:00", from_state="running" ),
    ]
    srv      = server_factory( frames )
    listener = arm.WsJobEventListener( srv.base_url, token="jwt", session_id="s-filter",
                                       collect_timeout=5.0 ).start()
    try:
        got = listener.ws_recv_events( "jB" )
        assert { e[ "job_id" ] for e in got } == { "jB" }         # never jA's frame
        assert [ e[ "to_state" ] for e in got ] == [ "queued", "running", "completed" ]
    finally:
        listener.stop()


# ---------------------------------------------------------------------------
# Refuse loudly — a job that never terminalizes RAISES, never a partial span.
# ---------------------------------------------------------------------------
def test_raises_on_timeout_with_partial_frames( server_factory ):
    frames = [
        _frame( "j1", "queued",  "2026-08-16T12:00:00+00:00" ),
        _frame( "j1", "running", "2026-08-16T12:00:01+00:00" ),   # never completes
    ]
    srv      = server_factory( frames )
    listener = arm.WsJobEventListener( srv.base_url, token="jwt", session_id="s-partial",
                                       collect_timeout=0.5 ).start()
    try:
        with pytest.raises( arm.EvalIntegrityError, match="refusing to return a partial span" ):
            listener.ws_recv_events( "j1" )
    finally:
        listener.stop()


def test_raises_on_timeout_with_no_frames_at_all( server_factory ):
    srv      = server_factory( [] )                              # server auths, emits nothing
    listener = arm.WsJobEventListener( srv.base_url, token="jwt", session_id="s-empty",
                                       collect_timeout=0.5 ).start()
    try:
        with pytest.raises( arm.EvalIntegrityError, match="no\\s+terminal state" ):
            listener.ws_recv_events( "ghost-job" )
    finally:
        listener.stop()


# ---------------------------------------------------------------------------
# Emitter-contract bind (John's review): the frames above are hand-rolled, so an
# emitter rename (to_state→state, dropped job_id) would pass them and break the real
# run silently. This test drives the REAL emit_job_state_transition, captures what it
# actually emits, wraps it the way websocket_manager does, and runs THAT through the
# same reduction the arm consumes — so drift in the shipped emitter goes RED here.
# ---------------------------------------------------------------------------
def test_real_emitter_frame_matches_what_the_producer_reads():
    from cosa.rest.queue_util import emit_job_state_transition
    from cosa.rest.job_state  import JobState

    captured = {}
    class _CapturingMgr:
        # emit_job_state_transition routes to emit_to_user_and_admins_sync when a user_id
        # is given, else emit — capture both so the test binds whichever path ships.
        def emit( self, event, data ):
            captured[ "event" ] = event; captured[ "data" ] = data
        def emit_to_user_and_admins_sync( self, user_id, event, data ):
            captured[ "event" ] = event; captured[ "data" ] = data

    emit_job_state_transition(
        _CapturingMgr(), "j1", JobState.RUNNING, JobState.COMPLETED,
        user_id="u1", metadata={ "agent_type": "MathAgent" },
    )

    assert captured[ "event" ] == "job_state_transition"
    data = captured[ "data" ]
    # The fields the producer + parse_transitions actually read — if the emitter renames
    # or drops any of these, these asserts fail (the silent-drift the hand-rolled test missed).
    assert data[ "job_id" ]   == "j1"
    assert data[ "to_state" ] == "completed"          # JobState.COMPLETED.value — must equal what parse expects
    assert isinstance( data[ "timestamp" ], str )
    assert data[ "metadata" ] == { "agent_type": "MathAgent" }

    # The shipped completed value must be one the producer treats as terminal.
    assert data[ "to_state" ] in arm._TERMINAL_STATES

    # End-to-end: wrap exactly as websocket_manager does ({type, timestamp, **data}) and
    # reduce it the way the arm will — a real completed frame must yield a completed_ts.
    wire    = { "type": captured[ "event" ], "timestamp": data[ "timestamp" ], **data }
    reduced = arm.parse_transitions( [ wire ] )
    assert reduced[ "completed_ts" ] is not None
    assert reduced[ "metadata" ]     == { "agent_type": "MathAgent" }
