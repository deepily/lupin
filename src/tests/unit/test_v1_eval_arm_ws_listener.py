"""
Unit tests for WsJobEventListener — the v1 arm's COLLECTION path (row 2d5aa0be).

WHY THIS FILE EXISTS. v1_eval_arm.py sat at 77% with all 65 uncovered statements in this
one class and its factory. That is not ordinary live-IO debt: `_default_collect_fn` builds
its collect_fn from `ws_recv_events`, and `parse_transitions` turns those frames into the
completion timestamps the entire v1 baseline is computed from. The arm's `ok` predicate is
literally "a span could be computed" — meaning this class saw both transitions. A coverage
waiver here waives the instrument, not a print statement.

THE ROW ASKED WHETHER THIS IS TESTABLE WITHOUT A LIVE SERVER. It is. `_serve` does its
`import websockets` INSIDE the function, so a fake module in sys.modules reaches it with no
production change. Exactly ONE line touches the network — `websockets.connect(...)` — and
everything around it (URL derivation, the auth handshake, frame dispatch, per-job
buffering, the terminal-state wait, the timeout refusal, thread lifecycle) is ordinary
logic a fake socket exercises directly.

⚠️ WHAT THESE TESTS DO NOT PROVE. The fake speaks the frame shape this class EXPECTS. They
cannot prove the shipped server emits that shape — that is what the live run against the
pinned worktree checks. They prove the collector behaves correctly GIVEN the contract,
which is the half that was untested.
"""

import asyncio
import json
import os
import sys
import threading
import time
import types

import pytest


def _load_module():
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import v1_eval_arm
    return v1_eval_arm


v1 = _load_module()


# ---------------------------------------------------------------------------
# The fake socket. One class, no production seam added.
# ---------------------------------------------------------------------------
class _FakeWs:
    """An async websocket that replays seeded frames, then idles on harmless ticks."""

    def __init__( self, seeded, idle_frame='{"type": "connect"}', idle_delay=0.005 ):
        self.sent        = []
        self._seeded     = list( seeded )
        self._idle       = idle_frame
        self._idle_delay = idle_delay

    async def send( self, payload ):
        self.sent.append( payload )

    async def recv( self ):
        if self._seeded:
            return self._seeded.pop( 0 )
        # Idle traffic the loop ignores, so stop() is observed promptly instead of
        # waiting out the real 1.0s recv timeout on every test.
        await asyncio.sleep( self._idle_delay )
        return self._idle


class _FakeConnect:
    """The async context manager `websockets.connect(...)` returns."""

    def __init__( self, ws, fail=None ):
        self.ws          = ws
        self.fail        = fail
        self.url         = None
        self.open_kwargs = None

    def __call__( self, url, **kwargs ):
        self.url         = url
        self.open_kwargs = kwargs
        if self.fail is not None:
            raise self.fail
        return self

    async def __aenter__( self ):
        return self.ws

    async def __aexit__( self, *exc ):
        return False


def _install_fake_websockets( monkeypatch, ws=None, fail=None ):
    """Put a fake `websockets` module where `_serve`'s local import will find it."""
    connect        = _FakeConnect( ws, fail=fail )
    module         = types.ModuleType( "websockets" )
    module.connect = connect
    monkeypatch.setitem( sys.modules, "websockets", module )
    return connect


_AUTH_OK = '{"type": "auth_success"}'


def _transition( job_id, to_state, timestamp="2026-08-25T18:00:00" ):
    return json.dumps( {
        "type"      : "job_state_transition",
        "job_id"    : job_id,
        "to_state"  : to_state,
        "timestamp" : timestamp,
    } )


@pytest.fixture
def listener_factory( monkeypatch ):
    """Build started listeners against a fake socket and guarantee they are stopped."""
    built = []

    def _build( seeded=(), *, fail=None, collect_timeout=0.5, connect_timeout=1.0,
                session_id="v1-eval-listener", base_url="http://localhost:7997",
                start=True ):
        ws      = _FakeWs( seeded )
        connect = _install_fake_websockets( monkeypatch, ws, fail=fail )
        obj     = v1.WsJobEventListener( base_url, "tok", session_id,
                                         collect_timeout=collect_timeout,
                                         connect_timeout=connect_timeout )
        built.append( obj )
        if start: obj.start()
        return obj, ws, connect

    yield _build
    for obj in built: obj.stop()


# ---------------------------------------------------------------------------
# _ws_url — scheme derivation
# ---------------------------------------------------------------------------
def test_ws_url_maps_http_to_ws_and_https_to_wss():
    plain  = v1.WsJobEventListener( "http://localhost:7997", "tok", "sid" )
    secure = v1.WsJobEventListener( "https://example.com",   "tok", "sid" )
    assert plain._ws_url()  == "ws://localhost:7997/ws/queue/sid"
    assert secure._ws_url() == "wss://example.com/ws/queue/sid"


def test_ws_url_carries_the_session_id_the_server_routes_on():
    obj = v1.WsJobEventListener( "http://h:1/", "tok", "my-session" )
    assert obj._ws_url().endswith( "/ws/queue/my-session" )


# ---------------------------------------------------------------------------
# start() — the handshake
# ---------------------------------------------------------------------------
def test_start_sends_the_auth_request_and_blocks_until_auth_success( listener_factory ):
    obj, ws, connect = listener_factory( [ _AUTH_OK ] )

    assert connect.url == "ws://localhost:7997/ws/queue/v1-eval-listener"
    assert connect.open_kwargs[ "open_timeout" ] == 1.0
    assert len( ws.sent ) == 1
    sent = json.loads( ws.sent[ 0 ] )
    assert sent[ "type" ]       == "auth_request"
    assert sent[ "token" ]      == "tok"
    assert sent[ "session_id" ] == "v1-eval-listener"
    assert sent[ "subscribed_events" ] == list( v1._QUEUE_SUBSCRIBED_EVENTS )


def test_start_returns_self_so_it_chains( listener_factory ):
    obj, _, _ = listener_factory( [ _AUTH_OK ], start=False )
    assert obj.start() is obj


def test_a_connect_failure_is_raised_out_of_start( listener_factory ):
    """A dead server must fail the run at start(), not surface later as empty buffers."""
    with pytest.raises( ConnectionRefusedError ):
        listener_factory( [], fail=ConnectionRefusedError( "no listener on :7997" ) )


def test_auth_error_is_raised_out_of_start_as_an_integrity_failure( listener_factory ):
    with pytest.raises( v1.EvalIntegrityError ) as exc:
        listener_factory( [ '{"type": "auth_error", "reason": "bad token"}' ] )
    assert "auth_error" in str( exc.value )


def test_start_refuses_when_the_socket_never_authenticates( monkeypatch ):
    """
    No auth_success and no failure either — the socket is up and silent. start() must give
    up rather than hand back a listener that would buffer nothing forever.
    """
    class _SilentWs( _FakeWs ):
        async def recv( self ):
            await asyncio.sleep( 0.01 )
            return '{"type": "connect"}'

    _install_fake_websockets( monkeypatch, _SilentWs( [] ) )
    obj = v1.WsJobEventListener( "http://localhost:7997", "tok", connect_timeout=-1.9 )
    try:
        with pytest.raises( v1.EvalIntegrityError ) as exc:
            obj.start()
        assert "did not become ready" in str( exc.value )
    finally:
        obj.stop()


# ---------------------------------------------------------------------------
# ws_recv_events — buffering and the terminal-state wait
# ---------------------------------------------------------------------------
def test_frames_are_buffered_by_job_and_returned_in_arrival_order( listener_factory ):
    obj, _, _ = listener_factory( [
        _AUTH_OK,
        _transition( "job-a", "queued" ),
        _transition( "job-a", "running" ),
        _transition( "job-a", "completed" ),
    ] )
    events = obj.ws_recv_events( "job-a" )
    assert [ e[ "to_state" ] for e in events ] == [ "queued", "running", "completed" ]


def test_another_jobs_frames_do_not_satisfy_this_jobs_wait( listener_factory ):
    """Per-job demultiplexing: job-b completing must not release job-a's watcher."""
    obj, _, _ = listener_factory( [
        _AUTH_OK,
        _transition( "job-b", "completed" ),
        _transition( "job-a", "queued" ),
    ], collect_timeout=0.3 )
    with pytest.raises( v1.EvalIntegrityError ):
        obj.ws_recv_events( "job-a" )
    assert [ e[ "to_state" ] for e in obj.ws_recv_events( "job-b" ) ] == [ "completed" ]


@pytest.mark.parametrize( "terminal", [ "completed", "failed", "cancelled", "interrupted" ] )
def test_every_terminal_state_releases_the_wait( listener_factory, terminal ):
    obj, _, _ = listener_factory( [ _AUTH_OK, _transition( "j", terminal ) ] )
    assert obj.ws_recv_events( "j" )[ 0 ][ "to_state" ] == terminal


def test_stalled_is_not_terminal_and_the_watch_keeps_waiting( listener_factory ):
    """
    STALLED can recover to COMPLETED, so treating it as terminal would cut the span short.
    Documented in the class; asserted here so a future edit to _TERMINAL_STATES fails.
    """
    assert "stalled" not in v1._TERMINAL_STATES
    obj, _, _ = listener_factory( [ _AUTH_OK, _transition( "j", "stalled" ) ],
                                  collect_timeout=0.3 )
    with pytest.raises( v1.EvalIntegrityError ) as exc:
        obj.ws_recv_events( "j" )
    assert "stalled" in str( exc.value )


def test_a_late_terminal_frame_still_releases_a_blocked_waiter( listener_factory ):
    """The wait is condition-driven, not a poll of an already-full buffer."""
    obj, _, _ = listener_factory( [ _AUTH_OK ], collect_timeout=3.0 )
    result = {}

    def _wait():
        result[ "events" ] = obj.ws_recv_events( "slow-job" )

    waiter = threading.Thread( target=_wait )
    waiter.start()
    time.sleep( 0.05 )                       # let the waiter block on the condition
    with obj._cond:                          # deliver the frame the way _serve does
        obj._events.setdefault( "slow-job", [] ).append(
            { "type": "job_state_transition", "job_id": "slow-job", "to_state": "completed" } )
        obj._cond.notify_all()
    waiter.join( timeout=3.0 )
    assert not waiter.is_alive(), "a notified waiter must wake rather than wait out the timeout"
    assert result[ "events" ][ 0 ][ "to_state" ] == "completed"


# ---------------------------------------------------------------------------
# The refusal — the property the whole class exists for
# ---------------------------------------------------------------------------
def test_a_silent_job_raises_rather_than_returning_an_empty_buffer( listener_factory ):
    """
    An empty buffer returned as data becomes a span wrong in the direction nobody audits,
    and it feeds the go/no-go. It must fail the run loudly instead.
    """
    obj, _, _ = listener_factory( [ _AUTH_OK ], collect_timeout=0.2 )
    with pytest.raises( v1.EvalIntegrityError ) as exc:
        obj.ws_recv_events( "never-seen" )
    message = str( exc.value )
    assert "never-seen" in message
    assert "0 frame(s)" in message
    assert "refusing to return a partial" in message


def test_the_refusal_names_the_non_terminal_states_it_did_see( listener_factory ):
    """A timeout that does not say what it saw sends the reader to the logs for nothing."""
    obj, _, _ = listener_factory( [
        _AUTH_OK, _transition( "j", "queued" ), _transition( "j", "running" ),
    ], collect_timeout=0.25 )
    with pytest.raises( v1.EvalIntegrityError ) as exc:
        obj.ws_recv_events( "j" )
    message = str( exc.value )
    assert "2 frame(s)" in message and "queued" in message and "running" in message


def test_a_partial_buffer_is_never_returned_after_the_timeout( listener_factory ):
    """The frames stay buffered; what must not happen is handing them back as a span."""
    obj, _, _ = listener_factory( [ _AUTH_OK, _transition( "j", "running" ) ],
                                  collect_timeout=0.2 )
    with pytest.raises( v1.EvalIntegrityError ):
        obj.ws_recv_events( "j" )
    assert len( obj._events[ "j" ] ) == 1   # buffered, but refused — not silently dropped


# ---------------------------------------------------------------------------
# The recv tick — the loop stays responsive to stop() on a quiet socket
# ---------------------------------------------------------------------------
def test_a_quiet_socket_ticks_instead_of_blocking_forever( monkeypatch ):
    """
    `_serve` wraps recv in wait_for(timeout=1.0) so a silent socket re-checks _stop rather
    than hanging. This is the ONE test that pays the real 1s tick, deliberately.
    """
    class _MuteWs( _FakeWs ):
        async def recv( self ):
            if self._seeded: return self._seeded.pop( 0 )
            await asyncio.sleep( 30 )       # never answers; wait_for must cancel it

    _install_fake_websockets( monkeypatch, _MuteWs( [ _AUTH_OK ] ) )
    obj = v1.WsJobEventListener( "http://localhost:7997", "tok", connect_timeout=1.0 )
    obj.start()
    obj.stop()
    assert obj._thread is not None and not obj._thread.is_alive()


# ---------------------------------------------------------------------------
# stop() and the factory
# ---------------------------------------------------------------------------
def test_stop_ends_the_listener_thread( listener_factory ):
    obj, _, _ = listener_factory( [ _AUTH_OK ] )
    assert obj._thread.is_alive()
    obj.stop()
    assert not obj._thread.is_alive()


def test_stop_is_safe_before_start():
    """The run wrapper's finally-block calls stop() even when start() raised."""
    obj = v1.WsJobEventListener( "http://localhost:7997", "tok" )
    obj.stop()                                # no thread yet — must not raise
    assert obj._thread is None


def test_make_ws_recv_events_returns_a_started_listener_and_its_bound_reader( monkeypatch ):
    """
    The factory hands back the LISTENER as well as the callable on purpose: stop() has to
    stay in the caller's hands, or the run wrapper cannot close the socket it opened.
    """
    _install_fake_websockets( monkeypatch, _FakeWs( [ _AUTH_OK, _transition( "j", "completed" ) ] ) )
    listener, recv = v1.make_ws_recv_events( "http://localhost:7997", "tok", collect_timeout=1.0 )
    try:
        assert isinstance( listener, v1.WsJobEventListener )
        assert recv.__self__ is listener
        assert listener.collect_timeout == 1.0
        assert recv( "j" )[ 0 ][ "to_state" ] == "completed"
    finally:
        listener.stop()


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
