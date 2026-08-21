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
        self.ask_calls    = []
        self.resume_calls = []
        self.submit_calls = []

    def ask( self, **kwargs ):
        self.ask_calls.append( kwargs )
        return self._result

    def resume( self, **kwargs ):
        self.resume_calls.append( kwargs )
        return self._result

    def submit( self, **kwargs ):
        self.submit_calls.append( kwargs )
        return self._result


def _app( current_user, flow ):
    app = FastAPI()
    app.include_router( v2_ask.router )
    app.dependency_overrides[ v2_ask.get_current_user ] = lambda: current_user
    app.dependency_overrides[ v2_ask.get_ask_flow ]      = lambda: flow
    return app


# ────────────────────────────────────────────────────────────── endpoint

# ── /api/v2/submit — the door beside ask (step 10, Rick's entry-point ruling) ──

def test_submit_happy_path_returns_full_response():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/submit",
                        json={ "command": "agent router go to weather",
                               "args": { "location": "Boston" } } )
    assert resp.status_code == 200
    assert resp.json()[ "path" ] == "agent"


def test_submit_passes_the_command_and_args_through_untouched():
    """
    The point of this door: the caller has already decided, so nothing re-derives it.
    A submit that quietly re-routed would be paying an LLM to recompute a stated fact.
    """
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    client.post( "/api/v2/submit",
                 json={ "command": "agent router go to weather",
                        "args": { "location": "Boston" },
                        "question": "what is the weather in Boston" } )
    call = flow.submit_calls[ 0 ]
    assert call[ "command" ]  == "agent router go to weather"
    assert call[ "args" ]     == { "location": "Boston" }
    assert call[ "question" ] == "what is the weather in Boston"


def test_submit_takes_identity_from_the_token_not_the_body():
    """
    Same rule as ask, and it matters more here: a submit body is machine-written, so a
    caller that could name its own user_id would be an impersonation door.
    """
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    client.post( "/api/v2/submit",
                 json={ "command": "agent router go to weather", "args": {},
                        "user_id": "someone-else", "user_email": "attacker@x.com" } )
    call = flow.submit_calls[ 0 ]
    assert call[ "user_id" ]    == "u1"
    assert call[ "user_email" ] == "u@x.com"


def test_submit_defaults_the_session_id_when_no_websocket_is_supplied():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    client.post( "/api/v2/submit", json={ "command": "agent router go to weather", "args": {} } )
    call = flow.submit_calls[ 0 ]
    assert call[ "session_id" ]   == "api-u1"
    assert call[ "websocket_id" ] == "api-u1"


def test_submit_uses_a_supplied_websocket_id_for_both():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    client.post( "/api/v2/submit",
                 json={ "command": "agent router go to weather", "args": {},
                        "websocket_id": "wise-penguin" } )
    call = flow.submit_calls[ 0 ]
    assert call[ "session_id" ]   == "wise-penguin"
    assert call[ "websocket_id" ] == "wise-penguin"


def test_submit_without_a_command_is_rejected_by_the_model():
    """`command` is required here where `question` is required on ask — that IS the door."""
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/submit", json={ "args": { "location": "Boston" } } )
    assert resp.status_code == 422
    assert flow.submit_calls == [], "a body with no command must never reach the flow"


def test_submit_does_not_require_a_question():
    """
    The difference from ask, stated as a test. ask cannot work without prose; submit was
    handed the conclusion that prose would have produced.
    """
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/submit", json={ "command": "agent router go to date and time" } )
    assert resp.status_code == 200
    assert flow.submit_calls[ 0 ][ "question" ] is None
    assert flow.submit_calls[ 0 ][ "args" ] == {}


def test_submit_with_no_user_id_in_the_token_is_401():
    flow = FakeFlow()
    client = TestClient( _app( { "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/submit", json={ "command": "agent router go to weather", "args": {} } )
    assert resp.status_code == 401
    assert flow.submit_calls == []


def test_submit_with_no_email_in_the_token_is_401():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1" }, flow ) )
    resp = client.post( "/api/v2/submit", json={ "command": "agent router go to weather", "args": {} } )
    assert resp.status_code == 401
    assert flow.submit_calls == []


def test_submit_and_ask_are_separate_doors_on_the_same_flow():
    """
    Neither call may leak into the other's list. They share a flow and a response model,
    which is exactly the condition under which a wiring slip goes unnoticed.
    """
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    client.post( "/api/v2/ask",    json={ "question": "weather in Boston" } )
    client.post( "/api/v2/submit", json={ "command": "agent router go to weather", "args": {} } )
    assert len( flow.ask_calls )    == 1
    assert len( flow.submit_calls ) == 1
    assert "command"  not in flow.ask_calls[ 0 ]
    assert "question" in flow.submit_calls[ 0 ]



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
    assert flow.ask_calls[ 0 ][ "user_id" ] == "u1"
    assert flow.ask_calls[ 0 ][ "user_email" ] == "u@x.com"
    # no websocket_id supplied → session_id synthesized from uid
    assert flow.ask_calls[ 0 ][ "session_id" ] == "api-u1"


def test_ask_uses_supplied_websocket_id():
    flow = FakeFlow()
    client = TestClient( _app( { "uid": "u1", "email": "u@x.com" }, flow ) )
    resp = client.post( "/api/v2/ask",
                        json={ "question": "hi", "websocket_id": "ws-42", "speak": False, "interactive": False } )
    assert resp.status_code == 200
    call = flow.ask_calls[ 0 ]
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
            captured[ "kwargs" ]   = kwargs
            captured[ "cache" ]    = cache
            captured[ "executor" ] = executor

    monkeypatch.setattr( "cosa.rest.v2.cache.V2Cache", lambda *a, **k: types.SimpleNamespace( tag="cache" ) )
    monkeypatch.setattr( "cosa.rest.v2.router_client.RouterClient", lambda *a, **k: types.SimpleNamespace( tag="router" ) )
    monkeypatch.setattr( "cosa.agents.runtime_argument_expeditor.expeditor.RuntimeArgumentExpeditor",
                         lambda *a, **k: types.SimpleNamespace( tag="expeditor" ) )
    monkeypatch.setattr( "cosa.rest.v2.executor.make_executor",
                         lambda name, todo_queue=None: types.SimpleNamespace( tag=f"exe:{name}", queue=todo_queue ) )
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
        # NON-DEFAULT on purpose. Both default to False, so leaving them out would
        # let a literal False in build_ask_flow pass as though it had read the key.
        "debug auto"                     : True,
        "debug inject bugs"              : True,
        # ⚠️ these two being EQUAL is why the companion test below exists — a swap
        # between them is invisible here (Pocholo, on 54c71571).
        "crud for dataframes agents enabled" : "false",
        # NON-DEFAULT on both, for the same reason: the threshold's default is 90.0 and
        # the enable flag's is True, so the shipped values would let a literal pass as a
        # read key. The pair is what ARMS the near-match ask (step 6b) — a build that
        # dropped them would leave every request routing past a 95% match in silence.
        "similarity threshold confirmation"  : 77.5,
        "similarity confirmation enabled"    : False,
    } )
    flow, enabled = v2_ask.build_ask_flow( cfg )
    assert enabled is True
    assert captured[ "kwargs" ][ "writeback_enabled" ] is True
    assert captured[ "kwargs" ][ "similarity_floor" ] == 90.0
    assert captured[ "kwargs" ][ "trace_dir" ] is None   # "" coerced

    # THE INI→FLOW HALF. The step-4 parity fixture sets auto_debug/inject_bugs on
    # the flow object directly, so it proves flow→agent and never crosses this half:
    # replacing these two reads with literal False left the whole suite green
    # (Pocholo, on 91f2e09b). Same for the CRUD flag, which is read right beside them.
    assert captured[ "kwargs" ][ "auto_debug" ]   is True,  "the flow ignored `debug auto`"
    assert captured[ "kwargs" ][ "inject_bugs" ]  is True,  "the flow ignored `debug inject bugs`"
    assert captured[ "kwargs" ][ "crud_enabled" ] is False, "the flow ignored `crud for dataframes agents enabled`"
    assert captured[ "kwargs" ][ "confirmation_threshold" ] == 77.5, "the flow ignored `similarity threshold confirmation`"
    assert captured[ "kwargs" ][ "confirmation_enabled" ]   is False, "the flow ignored `similarity confirmation enabled`"


def test_build_ask_flow_hands_the_queue_to_the_executor( monkeypatch ):
    """Step 12: `v2 executor = queued` needs the live todo queue, and build_ask_flow
    is the only place it can arrive. A build that read the name and dropped the queue
    would raise inside make_executor at boot — or, worse, silently build an inline
    executor and run every watchdog's job on the watchdog's own thread."""
    captured = {}
    _patch_stack( monkeypatch, captured )
    cfg   = _FakeConfig( { "v2 flow enabled": True, "v2 executor": "queued", "v2 trace dir": "" } )
    queue = types.SimpleNamespace( tag="todo-queue" )
    v2_ask.build_ask_flow( cfg, todo_queue=queue )
    assert captured[ "executor" ].tag   == "exe:queued"
    assert captured[ "executor" ].queue is queue


@pytest.mark.parametrize( "auto,inject", [ ( True, False ), ( False, True ) ] )
def test_the_two_debug_keys_are_not_cross_wired( monkeypatch, auto, inject ):
    """
    The companion to test_build_ask_flow_wires_from_ini, which sets both keys True —
    so SWAPPING the two reads passes there and only there (Pocholo, on 54c71571).
    Here they always differ, in both directions, so a swap fails one row or the other.

    RED ON REVERT: read `debug inject bugs` into auto_debug and vice versa.
    """
    captured = {}
    _patch_stack( monkeypatch, captured )
    cfg = _FakeConfig( {
        "v2 flow enabled"    : True,
        "v2 executor"        : "inline",
        "v2 trace dir"       : "",
        "debug auto"         : auto,
        "debug inject bugs"  : inject,
    } )
    v2_ask.build_ask_flow( cfg )
    assert captured[ "kwargs" ][ "auto_debug" ]  is auto
    assert captured[ "kwargs" ][ "inject_bugs" ] is inject


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

    ask    = _record
    submit = _record
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
    """RED ON REVERT: call flow.ask() directly in the handler and the flow body
    executes on the loop's own thread, so the identities match and this fails."""
    _assert_flow_ran_off_the_loop(
        lambda c: c.post( "/api/v2/ask", json={ "question": "weather in Boston" } ) )


def test_submit_runs_the_flow_off_the_event_loop():
    """MECHANISM arm for the second front door.

    `submit` skips the head — no routing, no expeditor, no cache read — but it
    still RUNS THE AGENT, so it holds the caller for the agent's full span. The
    head is the cheap part; skipping it does not make the call short.

    RED ON REVERT: restore the direct flow.submit() call and the flow body runs on
    the loop's own thread, so the identities match and this fails."""
    _assert_flow_ran_off_the_loop(
        lambda c: c.post( "/api/v2/submit", json={ "command": "agent router go to weather" } ) )


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

    ask    = _block
    submit = _block
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
    RED ON REVERT: call flow.ask() directly in the handler and every probe here
    returns TIMEOUT instead of 200 — measured, not asserted from theory.
    """
    codes = _health_codes_during( "/api/v2/ask", { "question": "weather in Boston" } )
    assert codes == [ 200 ] * 5, f"/health degraded while an ask was in flight: {codes}"


@pytest.mark.timeout( 120 )
def test_health_still_answers_while_a_submit_is_in_flight():
    """SYMPTOM arm for /api/v2/submit. The two arms are not interchangeable: work
    moved to another thread that still starves the loop passes the identity check
    and fails this one."""
    codes = _health_codes_during( "/api/v2/submit", { "command": "agent router go to weather" } )
    assert codes == [ 200 ] * 5, f"/health degraded while a submit was in flight: {codes}"


@pytest.mark.timeout( 120 )
def test_health_still_answers_while_a_resume_is_in_flight():
    """resume is the second turn of every disambiguation — a blocked loop here
    stalls exactly the conversations a user is already waiting on."""
    codes = _health_codes_during( "/api/v2/resume", { "pending_id": "p1", "answer": "Boston" } )
    assert codes == [ 200 ] * 5, f"/health degraded while a resume was in flight: {codes}"

