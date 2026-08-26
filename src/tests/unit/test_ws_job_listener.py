"""
Real-socket tests for the queue-WS producer (WsJobEventListener / ws_recv_events).

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

import ws_job_listener as arm                                  # noqa: E402
# ⚠️ MOVED WITH THE CODE, 2026-08-26 (row e2099400 §2 Step 2). These tests used to
# import v1_eval_arm; the listener now lives in ws_job_listener so it survives the V1
# excision. The alias stays `arm` so the move is a one-line diff and every assertion
# below is verifiably the SAME assertion — a relocation that also rewrites its tests
# cannot tell you the behaviour was preserved.


# ---------------------------------------------------------------------------
# A real, in-process websockets server that auths then streams a scripted set
# of frames — a genuine socket the listener connects to over TCP.
# ---------------------------------------------------------------------------
class _ScriptedWsServer:
    """Auth a client, stream `frames` (list of dicts), then hold the connection open."""

    def __init__( self, frames, *, auth_type="auth_success" ):
        self.frames  = frames
        self.auth_type = auth_type
        self.host     = "127.0.0.1"
        self.port     = None
        self._loop    = None
        self._thread  = None
        self._server  = None
        self._ready   = threading.Event()

    async def _handler( self, ws ):
        raw = await ws.recv()                       # the client's auth_request
        json.loads( raw )                           # (shape-tolerant: we only need it to arrive)
        await ws.send( json.dumps( { "type": self.auth_type } ) )
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
    def _make( frames, **kwargs ):
        srv = _ScriptedWsServer( frames, **kwargs ).start()
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


# ---------------------------------------------------------------------------
# THE LOUD-FAILURE PATHS (Chloé 🗼, row 43fca908).
#
# Everything above proves the seam when the socket behaves. The refusal machinery
# below — auth rejected, transport dead, listener never ready, stop before start —
# had NO test and NO execution: 7 statements + 5 partial branches uncovered at
# efb69f7c, and they are precisely the code that decides whether a bad paired run
# stops or continues. A guard nobody has ever seen fire is a comment.
#
# Same discipline as the file above: real sockets wherever a real socket can produce
# the condition. The one exception is documented at its own test.
# ---------------------------------------------------------------------------
def test_auth_error_frame_refuses_at_start( server_factory ):
    """
    The server rejects the JWT — start() must RAISE, not return a listener that quietly
    buffers nothing. A silent auth failure is the harness's worst shape: every job then
    times out in ws_recv_events and the run reports a v1 arm that "measured" no spans.

    Real socket: a genuine websockets server answering the auth_request with auth_error.
    """
    srv      = server_factory( [], auth_type="auth_error" )
    listener = arm.WsJobEventListener( srv.base_url, token="bad-jwt", session_id="s-authfail",
                                       collect_timeout=1.0, connect_timeout=3.0 )
    with pytest.raises( arm.EvalIntegrityError, match="auth_error" ):
        listener.start()
    listener.stop()


def test_connect_failure_is_captured_and_reraised_by_start():
    """
    Nothing is listening — the transport failure must surface OUT of start(), carrying the
    real exception rather than an invented one. This is the pinned-worktree server being
    down, which is the likeliest real-world failure of the whole arm.

    Real socket: a genuine refused TCP connect on a closed port (bound, then released).
    """
    import socket
    probe = socket.socket()
    probe.bind( ( "127.0.0.1", 0 ) )
    dead_port = probe.getsockname()[ 1 ]
    probe.close()                                   # nothing listens here now

    listener = arm.WsJobEventListener( f"http://127.0.0.1:{dead_port}", token="jwt",
                                       session_id="s-dead", connect_timeout=3.0 )
    with pytest.raises( ( ConnectionRefusedError, OSError ) ):
        listener.start()
    assert listener._error is not None               # captured, not swallowed
    listener.stop()


def test_a_frame_of_an_unrelated_type_is_skipped_not_buffered( server_factory ):
    """
    The queue socket carries more than transitions (notifications, audio, time ticks). An
    unrelated frame must be SKIPPED and the loop continue — if it were buffered under a
    None job_id, or worse ended the loop, the job's own frames after it would be lost.

    RED if the type guard is widened: the unrelated frame lands in the returned list.
    """
    frames = [
        { "type": "notification", "text": "unrelated traffic" },
        _frame( "j1", "queued",    "2026-08-16T12:00:00+00:00" ),
        _frame( "j1", "completed", "2026-08-16T12:00:02+00:00", from_state="queued" ),
    ]
    srv      = server_factory( frames )
    listener = arm.WsJobEventListener( srv.base_url, token="jwt", session_id="s-noise",
                                       collect_timeout=5.0 ).start()
    try:
        got = listener.ws_recv_events( "j1" )
        assert [ e[ "type" ] for e in got ] == [ "job_state_transition" ] * 2   # never the notification
        assert [ e[ "to_state" ] for e in got ] == [ "queued", "completed" ]
    finally:
        listener.stop()


def test_start_refuses_when_the_listener_never_becomes_ready():
    """
    start() must not return a listener that is not connected. Its readiness wait is the only
    thing standing between "the socket is live" and a run that measures nothing.

    THE ONE SUBSTITUTION IN THIS FILE, and why: `_serve` sets the ready flag in a `finally`,
    so on a real socket EVERY outcome — success, auth failure, refused connect, handshake
    timeout — sets it well inside the wait. There is no real-network way to make a thread
    hang past the deadline deterministically. So the THREAD BODY is replaced with a sleep;
    the code under test is start()'s readiness contract, which runs unmodified.
    """
    import time as _time

    class _NeverReady( arm.WsJobEventListener ):
        def _thread_main( self ):
            _time.sleep( 5.0 )                       # never reaches _serve's finally in time

    listener = _NeverReady( "http://127.0.0.1:1", token="jwt", session_id="s-hang",
                            connect_timeout=0.05 )
    with pytest.raises( arm.EvalIntegrityError, match="did not become ready" ):
        listener.start()


def test_stop_is_safe_before_start():
    """
    stop() on a listener that was never started must be a no-op. The paired bridge calls
    stop() in a finally; if start() raised, that finally still runs — so this path is
    reached on EVERY failed run, and an AttributeError here would bury the real error.
    """
    listener = arm.WsJobEventListener( "http://127.0.0.1:1", token="jwt", session_id="s-nostart" )
    listener.stop()                                  # must not raise
    assert listener._stop.is_set()


def test_make_ws_recv_events_returns_a_live_listener_and_its_bound_callable( server_factory ):
    """
    The factory the run wrapper actually calls — and the one no test had ever invoked.
    It must hand back BOTH the listener (so the caller keeps stop()) and a callable that
    is that listener's own ws_recv_events, wired to the same buffer.

    RED if it returns only the callable, or a callable off a different instance: the caller
    would then have no way to stop the thread, and the run would leak a socket per pass.
    """
    frames = [
        _frame( "j9", "queued",    "2026-08-16T12:00:00+00:00" ),
        _frame( "j9", "completed", "2026-08-16T12:00:01+00:00", from_state="queued" ),
    ]
    srv                    = server_factory( frames )
    listener, recv_events  = arm.make_ws_recv_events( srv.base_url, token="jwt",
                                                      session_id="s-factory", collect_timeout=5.0 )
    try:
        assert isinstance( listener, arm.WsJobEventListener )
        assert recv_events.__self__ is listener      # the SAME instance, not a second socket
        assert [ e[ "to_state" ] for e in recv_events( "j9" ) ] == [ "queued", "completed" ]
    finally:
        listener.stop()
