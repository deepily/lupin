"""
Admin gate on three REST routes.

GET  /api/debug/websocket-state  (routers/system.py)
POST /api/reset-queues           (routers/queues.py)

Each route refuses an anonymous caller (401) and a signed-in non-admin (403).
Each answers an admin. The identity comes in through the real `require_admin` chain.
Only `auth_middleware.get_current_user` is overridden, so reverting a route's
`Depends( require_admin )` turns the refusal tests red.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.rest.auth as auth
import cosa.rest.auth_middleware as auth_middleware
from cosa.rest.routers import system, queues

ADMIN = { "uid": "admin-1", "email": "a@x.test", "roles": [ "admin", "user" ] }
USER  = { "uid": "user-1",  "email": "u@x.test", "roles": [ "user" ] }


def _client( identity=None ):
    """
    Build a TestClient over the two routers.

    Requires:
        - identity is a user dict or None (anonymous)

    Ensures:
        - signed-in identities satisfy get_current_user in both auth modules
        - queue dependencies are fakes that record clear()
    """
    app = FastAPI()
    app.include_router( system.router )
    app.include_router( queues.router )

    fake_queue = MagicMock()
    fake_queue.size.return_value = 0
    for dep in ( queues.get_todo_queue, queues.get_running_queue, queues.get_done_queue,
                 queues.get_dead_queue, queues.get_notification_queue ):
        app.dependency_overrides[ dep ] = lambda: fake_queue

    if identity is not None:
        async def _who(): return identity
        app.dependency_overrides[ auth_middleware.get_current_user ] = _who
        app.dependency_overrides[ auth.get_current_user ]            = _who

    client             = TestClient( app )
    client.fake_queue  = fake_queue
    return client


@pytest.fixture
def stub_main( monkeypatch ):
    """Stand in for lupin_app.main so the debug route can read a manager."""
    mgr = types.SimpleNamespace(
        active_connections={}, session_to_user={}, user_sessions={},
        session_subscriptions={}, session_timestamps={},
        single_session_per_user=False
    )
    mod = types.ModuleType( "lupin_app.main" )
    mod.websocket_manager = mgr
    monkeypatch.setitem( sys.modules, "lupin_app.main", mod )
    return mgr


# ── GET /api/debug/websocket-state ───────────────────────────────────────────

def test_websocket_state_refuses_anonymous( stub_main ):
    assert _client().get( "/api/debug/websocket-state" ).status_code == 401


def test_websocket_state_refuses_non_admin( stub_main ):
    assert _client( USER ).get( "/api/debug/websocket-state" ).status_code == 403


def test_websocket_state_answers_admin( stub_main ):
    resp = _client( ADMIN ).get( "/api/debug/websocket-state" )
    assert resp.status_code == 200
    assert "active_connections" in resp.json()


# ── POST /api/reset-queues ───────────────────────────────────────────────────

def test_reset_queues_refuses_anonymous():
    client = _client()
    assert client.post( "/api/reset-queues" ).status_code == 401
    client.fake_queue.clear.assert_not_called()


def test_reset_queues_refuses_non_admin():
    client = _client( USER )
    assert client.post( "/api/reset-queues" ).status_code == 403
    client.fake_queue.clear.assert_not_called()


def test_reset_queues_answers_admin():
    client = _client( ADMIN )
    resp   = client.post( "/api/reset-queues" )
    assert resp.status_code == 200
    assert resp.json()[ "status" ] == "success"
    assert client.fake_queue.clear.call_count == 5
