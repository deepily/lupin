#!/usr/bin/env python3
"""
Unit tests for the CJ Flow v2 ask endpoint (unit D) — routers/v2_ask.py.

Hermetic: the endpoint is mounted on a bare FastAPI app and both its
dependencies (get_current_user, get_ask_flow) are overridden with fakes via
app.dependency_overrides, so NO auth backend and NO real AskFlow stack are
touched. build_ask_flow / get_ask_flow are exercised directly with the lazily
imported collaborator classes monkeypatched at their source modules — the INI
reads and the fail-loud writeback wiring run without a live Postgres or model
server. :7999-eligible. 100% lines + branches on v2_ask.py.
"""

import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from cosa.rest.routers import v2_ask


# ────────────────────────────────────────────────────────────── result fixture

def _full_result( **overrides ):
    base = {
        "path"          : "agent",     "status"      : "done",   "route_reason" : "args_complete",
        "answer"        : "sunny",     "answer_raw"  : "sunny",  "command"      : "agent router go to weather",
        "args_known"    : [ "location" ], "args_missing": [],
        "pending_id"    : None,        "job_id"      : None,     "snapshot_id"  : "snap-1",
        "similarity"    : 12.5,        "wrote_snapshot": True,   "cache_hit"    : False,
        "spoke"         : True,        "timings_ms"  : { "t_recv": 0.0 }, "trace_id": "abc123",
        "error"         : None,
    }
    base.update( overrides )
    return base


class FakeFlow:
    def __init__( self, result=None ):
        self._result      = result if result is not None else _full_result()
        self.run_calls    = []
        self.resume_calls = []

    def run( self, **kwargs ):
        self.run_calls.append( kwargs )
        return self._result

    def resume( self, **kwargs ):
        self.resume_calls.append( kwargs )
        return self._result


def _app( current_user, flow ):
    app = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: current_user
    app.dependency_overrides[ v2_ask.get_ask_flow ]      = lambda: flow
    return app


# ────────────────────────────────────────────────────────────── endpoint

def test_ask_happy_path_returns_full_response():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/ask", json={ "question": "weather in Boston" } )
    assert resp.status_code == 200
    body = resp.json()
    assert body[ "path" ] == "agent"
    assert body[ "snapshot_id" ] == "snap-1"
    assert body[ "trace_id" ] == "abc123"
    # token-sourced identity, not the client body
    assert flow.run_calls[ 0 ][ "user_id" ] == "u1"
    assert flow.run_calls[ 0 ][ "user_email" ] == "u@x.com"
    # no websocket_id supplied → session_id synthesized from uid
    assert flow.run_calls[ 0 ][ "session_id" ] == "api-u1"


def test_ask_uses_supplied_websocket_id():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/ask",
                        json={ "question": "hi", "websocket_id": "ws-42", "speak": False, "interactive": False } )
    assert resp.status_code == 200
    call = flow.run_calls[ 0 ]
    assert call[ "session_id" ] == "ws-42"
    assert call[ "websocket_id" ] == "ws-42"
    assert call[ "speak" ] is False
    assert call[ "interactive" ] is False


def test_ask_401_when_uid_missing():
    flow = FakeFlow()
    client = TestClient( _app( { "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/ask", json={ "question": "hi" } )
    assert resp.status_code == 401
    assert "id not found" in resp.json()[ "detail" ]


def test_ask_401_when_email_missing():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1" }, flow ) )
    resp = client.post( "/api/v2/ask", json={ "question": "hi" } )
    assert resp.status_code == 401
    assert "email not found" in resp.json()[ "detail" ]


def test_ask_422_on_empty_question():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/ask", json={ "question": "" } )
    assert resp.status_code == 422


def test_ask_422_on_oversized_question():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/ask", json={ "question": "x" * 4001 } )
    assert resp.status_code == 422


# ────────────────────────────────────────────────────────────── resume endpoint (DoD 4)

def test_resume_happy_path_forwards_to_flow():
    flow = FakeFlow( _full_result( path="agent", route_reason="resumed", answer="sunny" ) )
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/resume", json={ "pending_id": "pend-1", "answer": "Boston" } )
    assert resp.status_code == 200
    assert resp.json()[ "route_reason" ] == "resumed"
    call = flow.resume_calls[ 0 ]
    assert call[ "pending_id" ] == "pend-1"
    assert call[ "answer" ] == "Boston"
    # no websocket_id → synthesized from uid, forwarded to the flow
    assert call[ "websocket_id" ] == "api-u1"
    assert call[ "speak" ] is True


def test_resume_uses_supplied_websocket_id_and_speak():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/resume",
                        json={ "pending_id": "p", "answer": "Boston", "websocket_id": "ws-9", "speak": False } )
    assert resp.status_code == 200
    call = flow.resume_calls[ 0 ]
    assert call[ "websocket_id" ] == "ws-9"
    assert call[ "speak" ] is False


def test_resume_401_when_uid_missing():
    flow = FakeFlow()
    client = TestClient( _app( { "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/resume", json={ "pending_id": "p", "answer": "x" } )
    assert resp.status_code == 401
    assert "id not found" in resp.json()[ "detail" ]


def test_resume_401_when_email_missing():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1" }, flow ) )
    resp = client.post( "/api/v2/resume", json={ "pending_id": "p", "answer": "x" } )
    assert resp.status_code == 401
    assert "email not found" in resp.json()[ "detail" ]


def test_resume_422_on_empty_answer():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/resume", json={ "pending_id": "p", "answer": "" } )
    assert resp.status_code == 422


def test_resume_422_on_missing_pending_id():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/resume", json={ "answer": "Boston" } )
    assert resp.status_code == 422


# ────────────────────────────────────────────────────────────── build_ask_flow

class _FakeConfig:
    def __init__( self, values ):
        self._values = values

    def get( self, key, default=None, return_type="string", silent=False ):
        return self._values.get( key, default )


def _patch_stack( monkeypatch, captured ):
    """Monkeypatch the lazily-imported collaborator classes at their source
    modules so build_ask_flow wires fakes — no live Postgres/model server."""
    class _FakeAskFlow:
        def __init__( self, cache, router, expeditor, executor, pending, **kwargs ):
            captured[ "kwargs" ] = kwargs
            captured[ "cache" ]  = cache

    monkeypatch.setattr( "cosa.rest.v2.cache.V2Cache", lambda *a, **k: types.SimpleNamespace( tag="cache" ) )
    monkeypatch.setattr( "cosa.rest.v2.router_client.RouterClient", lambda *a, **k: types.SimpleNamespace( tag="router" ) )
    monkeypatch.setattr( "cosa.agents.runtime_argument_expeditor.expeditor.RuntimeArgumentExpeditor",
                         lambda *a, **k: types.SimpleNamespace( tag="expeditor" ) )
    monkeypatch.setattr( "cosa.rest.v2.executor.make_executor", lambda name: types.SimpleNamespace( tag=f"exe:{name}" ) )
    monkeypatch.setattr( "cosa.rest.v2.pending.PendingRequests", lambda *a, **k: types.SimpleNamespace( tag="pending" ) )
    monkeypatch.setattr( "cosa.rest.v2.flow.AskFlow", _FakeAskFlow )


def test_build_ask_flow_wires_from_ini( monkeypatch ):
    captured = {}
    _patch_stack( monkeypatch, captured )
    cfg = _FakeConfig( {
        "v2 flow enabled"                : True,
        "v2 executor"                    : "inline",
        "v2 snapshot writeback enabled"  : True,
        "v2 similarity floor"            : 90.0,
        "v2 trace dir"                   : "",     # empty → coerced to None
    } )
    flow, enabled = v2_ask.build_ask_flow( cfg )
    assert enabled is True
    assert captured[ "kwargs" ][ "writeback_enabled" ] is True
    assert captured[ "kwargs" ][ "similarity_floor" ] == 90.0
    assert captured[ "kwargs" ][ "trace_dir" ] is None   # "" coerced


def test_build_ask_flow_disabled_flag( monkeypatch ):
    captured = {}
    _patch_stack( monkeypatch, captured )
    cfg = _FakeConfig( { "v2 flow enabled": False, "v2 trace dir": "/tmp/traces" } )
    flow, enabled = v2_ask.build_ask_flow( cfg )
    assert enabled is False
    assert captured[ "kwargs" ][ "trace_dir" ] == "/tmp/traces"   # non-empty kept


# ────────────────────────────────────────────────────────────── get_ask_flow gate

def test_get_ask_flow_returns_flow_when_enabled( monkeypatch ):
    v2_ask._ASK_FLOW_CACHE.clear()
    sentinel = object()
    monkeypatch.setattr( v2_ask, "ConfigurationManager", lambda **k: types.SimpleNamespace( tag="cfg" ) )
    monkeypatch.setattr( v2_ask, "build_ask_flow", lambda cm: ( sentinel, True ) )
    assert v2_ask.get_ask_flow() is sentinel


def test_get_ask_flow_503_when_disabled( monkeypatch ):
    v2_ask._ASK_FLOW_CACHE.clear()
    monkeypatch.setattr( v2_ask, "ConfigurationManager", lambda **k: types.SimpleNamespace( tag="cfg" ) )
    monkeypatch.setattr( v2_ask, "build_ask_flow", lambda cm: ( object(), False ) )
    with pytest.raises( HTTPException ) as exc:
        v2_ask.get_ask_flow()
    assert exc.value.status_code == 503


def test_get_ask_flow_caches_build( monkeypatch ):
    v2_ask._ASK_FLOW_CACHE.clear()
    calls = { "n": 0 }
    cfg_obj = types.SimpleNamespace( tag="cfg" )
    monkeypatch.setattr( v2_ask, "ConfigurationManager", lambda **k: cfg_obj )

    def _counting_build( cm ):
        calls[ "n" ] += 1
        return ( object(), True )

    monkeypatch.setattr( v2_ask, "build_ask_flow", _counting_build )
    v2_ask.get_ask_flow()
    v2_ask.get_ask_flow()
    assert calls[ "n" ] == 1   # second call hits the id(config_mgr) cache


# ──────────────────────────────────────────── the event loop stays free (row 1c36199e)

class ThreadRecordingFlow:
    """Records which thread the flow body actually ran on."""

    def __init__( self ):
        import threading
        self.flow_thread = None
        self._threading  = threading
        self._result     = _full_result()

    def _record( self, **kwargs ):
        self.flow_thread = self._threading.get_ident()
        return self._result

    run    = _record
    resume = _record


def _loop_thread_app( flow, box ):
    """The v2 router plus a probe that reports the thread the event loop runs on."""
    import threading

    app = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: { "uid": "u1", "email": "u@x.com" }
    app.dependency_overrides[ v2_ask.get_ask_flow ]     = lambda: flow

    @app.get( "/loop-thread" )
    async def loop_thread():          # async, so it runs ON the loop
        box[ "loop_thread" ] = threading.get_ident()
        return { "ok": True }

    return app


def _assert_flow_ran_off_the_loop( fire_request ):
    """
    Assert the blocking flow call did NOT execute on the event loop's thread.

    WHY THIS SHAPE, and not "probe /health during a slow call": I wrote that test
    first and it was WORTHLESS — it passed with the sync call restored. TestClient
    does not hold one shared event loop across concurrent requests the way a live
    uvicorn worker does, so the block it was meant to detect never manifested and
    the assertion could not go red. An assertion that cannot fail is not a guard.

    Thread identity is the same property, observable in a hermetic test: if the
    handler awaits the flow through run_in_threadpool, the flow body runs on a
    worker thread; if it calls the flow directly, the flow body runs on the loop's
    own thread — which is precisely what makes a ~70s call block /health in
    production (row 1c36199e).
    """
    flow = ThreadRecordingFlow()
    box  = {}
    client = TestClient( _loop_thread_app( flow, box ) )

    client.get( "/loop-thread" )
    resp = fire_request( client )

    assert resp.status_code == 200
    assert box[ "loop_thread" ] is not None
    assert flow.flow_thread  is not None
    assert flow.flow_thread != box[ "loop_thread" ], (
        "the flow ran ON the event loop's thread — a slow call there blocks /health "
        "and every other request; it must go through run_in_threadpool."
    )


def test_ask_runs_the_flow_off_the_event_loop():
    """RED ON REVERT: call flow.run() directly in the handler and the flow body
    executes on the loop's own thread, so the identities match and this fails."""
    _assert_flow_ran_off_the_loop(
        lambda c: c.post( "/api/v2/ask", json={ "question": "weather in Boston" } ) )


def test_resume_runs_the_flow_off_the_event_loop():
    """The same for resume — the second turn of every disambiguation.

    RED ON REVERT: restore the direct flow.resume() call and this fails."""
    _assert_flow_ran_off_the_loop(
        lambda c: c.post( "/api/v2/resume", json={ "pending_id": "p1", "answer": "Boston" } ) )


# ─────────────────────────── the SYMPTOM arm: /health under a real uvicorn loop

class BlockingFlow:
    """A flow whose call blocks until released, and that announces when it started."""

    def __init__( self ):
        import threading
        self.started = threading.Event()
        self.release = threading.Event()
        self._result = _full_result()

    def _block( self, **kwargs ):
        self.started.set()
        self.release.wait( timeout=15 )
        return self._result

    run    = _block
    resume = _block


def _free_port():
    import socket
    s = socket.socket(); s.bind( ( "127.0.0.1", 0 ) ); port = s.getsockname()[ 1 ]; s.close()
    return port


def _health_codes_during( path, payload ):
    """
    Serve the REAL v2 router on a real single-worker uvicorn loop, put one request
    in flight, and report what /health answers while it is running.

    WHY A REAL SERVER, when every other test here uses TestClient: TestClient does
    not hold one shared event loop across concurrent requests, so a handler that
    blocks the loop does not block anything observable through it. The first
    version of this test used TestClient and PASSED with the blocking call restored
    — it could not fail, so it guarded nothing. A real uvicorn worker reproduces
    the production shape, and there the difference is total: blocking on the loop
    gives TIMEOUT on every probe, off the loop gives 200 on every probe.

    This is the SYMPTOM arm. The thread-identity tests above are the MECHANISM arm,
    and they are not interchangeable: work moved to another thread that still
    starves the loop would pass the identity check and fail this one. Keep both.
    """
    import threading, time
    import uvicorn, requests

    flow = BlockingFlow()
    app  = _app( { "uid": "u1", "email": "u@x.com" }, flow )

    @app.get( "/health" )
    async def health():                       # async — served ON the loop
        return { "ok": True }

    port   = _free_port()
    server = uvicorn.Server( uvicorn.Config( app, host="127.0.0.1", port=port, log_level="error" ) )
    thread = threading.Thread( target=server.run, daemon=True )
    thread.start()
    try:
        for _ in range( 200 ):                # wait for bind
            try:
                requests.get( f"http://127.0.0.1:{port}/health", timeout=0.5 ); break
            except Exception: time.sleep( 0.05 )

        caller = threading.Thread(
            target=lambda: requests.post( f"http://127.0.0.1:{port}{path}", json=payload, timeout=20 ),
            daemon=True )
        caller.start()
        assert flow.started.wait( timeout=10 ), "the blocking call never started — the probes would prove nothing"

        codes = []
        for _ in range( 5 ):
            try:
                codes.append( requests.get( f"http://127.0.0.1:{port}/health", timeout=1.0 ).status_code )
            except requests.exceptions.Timeout:
                codes.append( "TIMEOUT" )
        return codes
    finally:
        flow.release.set()
        server.should_exit = True
        thread.join( timeout=10 )


@pytest.mark.timeout( 120 )
def test_health_still_answers_while_an_ask_is_in_flight():
    """
    RED ON REVERT: call flow.run() directly in the handler and every probe here
    returns TIMEOUT instead of 200 — measured, not asserted from theory.
    """
    codes = _health_codes_during( "/api/v2/ask", { "question": "weather in Boston" } )
    assert codes == [ 200 ] * 5, f"/health degraded while an ask was in flight: {codes}"


@pytest.mark.timeout( 120 )
def test_health_still_answers_while_a_resume_is_in_flight():
    """resume is the second turn of every disambiguation — a blocked loop here
    stalls exactly the conversations a user is already waiting on."""
    codes = _health_codes_during( "/api/v2/resume", { "pending_id": "p1", "answer": "Boston" } )
    assert codes == [ 200 ] * 5, f"/health degraded while a resume was in flight: {codes}"

