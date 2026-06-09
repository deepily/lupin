#!/usr/bin/env python3
"""
Unit tests for the arbiter router — GET/POST /api/arbiter/fleet-snapshot
(arbiter design `03` §10.4, redline C2).

Uses a minimal FastAPI app mounting ONLY the arbiter router with the
require_api_key_or_jwt dependency overridden, so the HTTP routing + status
codes + serialization are exercised without the auth DB (a :7999-eligible
unit test — no persistent state, fast). 100% coverage of routers/arbiter.py.
"""
import os
import sys

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.routers import arbiter
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
import cosa.rest.arbiter_snapshot_store as store


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router( arbiter.router )
    # Override the credential (X-API-Key / JWT) so we test routing, not auth-DB.
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    store.clear_snapshot()
    yield TestClient( app )
    store.clear_snapshot()


def test_get_awaiting_before_any_push( client ):
    r = client.get( "/api/arbiter/fleet-snapshot" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "status" ] == "awaiting"
    assert body[ "session_count" ] == 0 and body[ "sessions" ] == [ ] and body[ "generated_at" ] is None


def test_post_then_get_roundtrip( client ):
    snap = {
        "generated_at"  : "2026-06-06T22:41:00+00:00",
        "session_count" : 1,
        "sessions"      : [ { "session_id": "s1", "persona": "Ann", "state": "working",
                              "holding_on": "none", "stuck": False,
                              "liveness": { "bridge_age_s": 4, "event_age_s": 120,
                                            "freshest_age_s": 4, "verdict": "LIVE" } } ],
    }
    post = client.post( "/api/arbiter/fleet-snapshot", json=snap )
    assert post.status_code == 200
    assert post.json() == { "status": "ok", "session_count": 1 }

    got = client.get( "/api/arbiter/fleet-snapshot" )
    assert got.status_code == 200
    body = got.json()
    assert body[ "session_count" ] == 1
    assert body[ "sessions" ][ 0 ][ "liveness" ][ "verdict" ] == "LIVE"   # state/liveness preserved


def test_post_defaults_when_minimal_body( client ):
    """Pydantic fills defaults: session_count=0, sessions=[] (no hand-rolled validation)."""
    post = client.post( "/api/arbiter/fleet-snapshot", json={ } )
    assert post.status_code == 200
    assert post.json() == { "status": "ok", "session_count": 0 }
    assert store.get_snapshot()[ "sessions" ] == [ ]


def test_post_rejects_negative_session_count( client ):
    """session_count has ge=0 — a negative value is a 422 (Pydantic-validated)."""
    r = client.post( "/api/arbiter/fleet-snapshot", json={ "session_count": -1 } )
    assert r.status_code == 422


# ── GET /api/arbiter/fleet-state (L4) — :7999 reverse-proxy PULL from :8001/state ──
# The httpx call boundary `_pull_arbiter_state` is monkeypatched, so NO live :8001
# is needed: success path (fake returns) + unreachable path (fake raises httpx error).

def test_fleet_state_success_echoes_upstream( client, monkeypatch ):
    """Reachable :8001 → the proxy returns the upstream composite verbatim (200)."""
    composite = {
        "status"       : "ok",
        "service"      : "lupin-arbiter-app",
        "version"      : "x.y.z",
        "generated_at"   : "2026-06-07T22:00:00+00:00",
        "health_watcher" : { "containers": { } },
        "fleet_arbiter"  : { "status": "ok", "session_count": 1, "sessions": [ ] },
    }
    monkeypatch.setattr( arbiter, "_pull_arbiter_state", lambda url, timeout: composite )
    r = client.get( "/api/arbiter/fleet-state" )
    assert r.status_code == 200
    body = r.json()
    # Every upstream key is echoed VERBATIM …
    assert { k: body[ k ] for k in composite } == composite
    # … plus the ONE :7999-local injection (Fleet-Status §4.1): a non-empty IANA zone.
    assert isinstance( body[ "app_timezone" ], str ) and body[ "app_timezone" ]


def test_fleet_state_injects_configured_app_timezone( client, monkeypatch ):
    """app_timezone is injected from the config key 'app timezone' (Fleet-Status §4.1)."""
    from cosa.rest.dependencies.config import get_config_manager
    expected = get_config_manager().get( "app timezone", default="America/New_York" )
    monkeypatch.setattr( arbiter, "_pull_arbiter_state", lambda url, timeout: { "status": "ok" } )
    body = client.get( "/api/arbiter/fleet-state" ).json()
    assert body[ "app_timezone" ] == expected


def test_fleet_state_non_dict_upstream_not_enriched( client, monkeypatch ):
    """Defensive: a non-dict upstream body passes through untouched (no injection, no crash)."""
    monkeypatch.setattr( arbiter, "_pull_arbiter_state", lambda url, timeout: [ "weird", "but", "json" ] )
    r = client.get( "/api/arbiter/fleet-state" )
    assert r.status_code == 200 and r.json() == [ "weird", "but", "json" ]


def test_fleet_state_unreachable_when_pull_fails( client, monkeypatch ):
    """Any httpx failure → explicit unreachable envelope (HTTP 200, null sections)."""
    def _boom( url, timeout ):
        raise httpx.ConnectError( "connection refused" )
    monkeypatch.setattr( arbiter, "_pull_arbiter_state", _boom )
    r = client.get( "/api/arbiter/fleet-state" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "status" ]  == "unreachable"
    assert body[ "service" ] == "lupin-arbiter-app"
    assert body[ "health_watcher" ] is None and body[ "fleet_arbiter" ] is None
    # app_timezone is intentionally OMITTED on the unreachable envelope (§4.1) → client falls back to browser-local.
    assert "app_timezone" not in body
    # NEGATIVE: the OLD generic keys are GONE from the proxy envelope (contract break, not additive)
    assert "loop_a" not in body and "loop_b_fleet" not in body
    assert "ConnectError" in body[ "detail" ]


def test_fleet_state_reads_configured_url_and_timeout( client, monkeypatch ):
    """The proxy pulls the configured URL + int timeout from the shared config singleton."""
    captured = { }
    def _capture( url, timeout ):
        captured[ "url" ]     = url
        captured[ "timeout" ] = timeout
        return { "status": "ok" }
    monkeypatch.setattr( arbiter, "_pull_arbiter_state", _capture )
    client.get( "/api/arbiter/fleet-state" )
    assert captured[ "url" ]     == "http://host.docker.internal:8001/state"
    assert captured[ "timeout" ] == 5 and isinstance( captured[ "timeout" ], int )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
