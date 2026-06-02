"""
Unit tests for lever D (pull-able AFK inbox) of the messaging-coordination plane.

Covers (all mocked — no DB, no server → :7999-eligible):
  - repo `get_undelivered_for_recipient` query wiring
  - `_project_undelivered_notification` projection
  - `GET /notifications/undelivered` endpoint (success / bad-uuid 400 / error 500)
  - websocket `_compute_undelivered_count` surfacing helper (count / fail-safe 0)

The full DB- + WS-backed integration test runs on :8000 (scheduled).
"""

import uuid
import types
import asyncio
import contextlib

import pytest
from fastapi import HTTPException

from cosa.rest.routers import notifications as nmod
from cosa.rest.routers import websocket as wsmod
from cosa.rest.db.repositories.notification_repository import NotificationRepository
import cosa.rest.db.database as dbmod
import cosa.rest.db.repositories.notification_repository as repomod


VALID_UUID = "12345678-1234-1234-1234-123456789abc"


def _fake_notif( **kw ):
    base = {
        "id": uuid.UUID( VALID_UUID ), "sender_id": "claude.code@lupin.deepily.ai#abcd1234",
        "title": "t", "message": "m", "abstract": "a", "type": "task", "priority": "high",
        "state": "created", "job_id": None, "created_at": None,
    }
    base.update( kw )
    return types.SimpleNamespace( **base )


# ── repo query wiring ────────────────────────────────────────────────────────
class _FakeQuery:
    def __init__( self, result ): self.result = result
    def filter( self, *a, **k ): return self
    def order_by( self, *a, **k ): return self
    def limit( self, n ): return self
    def all( self ): return self.result
    def count( self ): return len( self.result )


class _FakeSession:
    def __init__( self, result ): self.result = result
    def query( self, model ): return _FakeQuery( self.result )


class TestRepoQuery:
    def test_returns_session_query_result( self ):
        sentinel = [ _fake_notif(), _fake_notif() ]
        repo = NotificationRepository( _FakeSession( sentinel ) )
        out  = repo.get_undelivered_for_recipient( uuid.UUID( VALID_UUID ) )
        assert out == sentinel

    def test_count_returns_unbounded_total( self ):
        sentinel = [ _fake_notif(), _fake_notif(), _fake_notif() ]
        repo = NotificationRepository( _FakeSession( sentinel ) )
        assert repo.count_undelivered_for_recipient( uuid.UUID( VALID_UUID ) ) == 3


# ── projection ───────────────────────────────────────────────────────────────
class TestProjection:
    def test_projects_fields( self ):
        d = nmod._project_undelivered_notification( _fake_notif() )
        assert d[ "id" ] == VALID_UUID
        assert d[ "message" ] == "m" and d[ "type" ] == "task" and d[ "state" ] == "created"
        assert d[ "created_at" ] is None

    def test_created_at_isoformat( self ):
        import datetime
        n = _fake_notif( created_at=datetime.datetime( 2026, 6, 2, 12, 0, 0 ) )
        d = nmod._project_undelivered_notification( n )
        assert d[ "created_at" ].startswith( "2026-06-02T12:00:00" )


# ── endpoint ─────────────────────────────────────────────────────────────────
def _patch_db( monkeypatch, repo ):
    @contextlib.contextmanager
    def fake_get_db():
        yield "SESSION"
    monkeypatch.setattr( nmod, "get_db", fake_get_db )
    monkeypatch.setattr( nmod, "NotificationRepository", lambda session: repo )
    # get_local_timestamp() needs app/config context absent in a bare unit test.
    monkeypatch.setattr( nmod, "get_local_timestamp", lambda: "2026-06-02T00:00:00" )


class TestUndeliveredEndpoint:
    def test_success( self, monkeypatch ):
        repo = types.SimpleNamespace( get_undelivered_for_recipient=lambda rid, limit: [ _fake_notif(), _fake_notif() ] )
        _patch_db( monkeypatch, repo )
        out = asyncio.run( nmod.get_undelivered_notifications( authenticated_user_id=VALID_UUID, limit=100 ) )
        assert out[ "status" ] == "success"
        assert out[ "undelivered_count" ] == 2
        assert len( out[ "notifications" ] ) == 2

    def test_bad_uuid_raises_400( self, monkeypatch ):
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.get_undelivered_notifications( authenticated_user_id="not-a-uuid", limit=100 ) )
        assert exc.value.status_code == 400

    def test_repo_error_raises_500( self, monkeypatch ):
        def boom( rid, limit ):
            raise RuntimeError( "db down" )
        repo = types.SimpleNamespace( get_undelivered_for_recipient=boom )
        _patch_db( monkeypatch, repo )
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.get_undelivered_notifications( authenticated_user_id=VALID_UUID, limit=100 ) )
        assert exc.value.status_code == 500


# ── websocket surfacing helper ───────────────────────────────────────────────
class TestComputeUndeliveredCount:
    def test_returns_count( self, monkeypatch ):
        @contextlib.contextmanager
        def fake_get_db():
            yield "SESSION"
        monkeypatch.setattr( dbmod, "get_db", fake_get_db )
        monkeypatch.setattr( repomod, "NotificationRepository",
                             lambda session: types.SimpleNamespace( count_undelivered_for_recipient=lambda rid: 3 ) )
        assert wsmod._compute_undelivered_count( VALID_UUID ) == 3

    def test_bad_uuid_returns_zero( self ):
        assert wsmod._compute_undelivered_count( "not-a-uuid" ) == 0

    def test_db_error_returns_zero( self, monkeypatch ):
        def boom():
            raise RuntimeError( "no db" )
        monkeypatch.setattr( dbmod, "get_db", boom )
        assert wsmod._compute_undelivered_count( VALID_UUID ) == 0
