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
        self._result   = result if result is not None else _full_result()
        self.run_calls = []

    def run( self, **kwargs ):
        self.run_calls.append( kwargs )
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
