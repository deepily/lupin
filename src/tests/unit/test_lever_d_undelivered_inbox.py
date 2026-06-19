"""
Unit tests for lever D (pull-able AFK inbox) of the messaging-coordination plane.

Covers (all mocked — no DB, no server → :7999-eligible):
  - repo `get_undelivered_for_recipient` query wiring
  - repo `dismiss_undelivered_for_recipient` query wiring (reset-button backing)
  - `_project_undelivered_notification` projection
  - `GET /notifications/undelivered` endpoint (success / bad-uuid 400 / error 500)
  - `POST /notifications/undelivered/dismiss` endpoint (success / bad-uuid 400 / error 500)
  - websocket `_compute_undelivered_count` surfacing helper (count / fail-safe 0)

The full DB- + WS-backed integration test runs on :8000 (scheduled).
"""

import sys
import uuid
import types
import asyncio
import contextlib
from unittest.mock import patch

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
    def __init__( self, result ):
        self.result       = result
        self.filter_calls = 0           # storm-guard: 1 base filter, +1 when age-capped
        self.update_calls = 0           # dismiss path: bulk is_hidden=True update
        self.update_values = None       # retained so tests can assert what was set
    def filter( self, *a, **k ):
        self.filter_calls += 1
        return self
    def order_by( self, *a, **k ): return self
    def limit( self, n ): return self
    def all( self ): return self.result
    def count( self ): return len( self.result )
    def update( self, values, synchronize_session=False ):
        self.update_calls  += 1
        self.update_values  = values
        return len( self.result )       # SQLAlchemy returns the rowcount affected


class _FakeSession:
    def __init__( self, result ):
        self.result      = result
        self.last_query  = None         # retained so tests can inspect filter wiring
        self.flush_calls = 0
    def query( self, model ):
        self.last_query = _FakeQuery( self.result )
        return self.last_query
    def flush( self ):
        self.flush_calls += 1


class TestRepoQuery:
    def test_returns_session_query_result( self ):
        sentinel = [ _fake_notif(), _fake_notif() ]
        sess = _FakeSession( sentinel )
        repo = NotificationRepository( sess )
        out  = repo.get_undelivered_for_recipient( uuid.UUID( VALID_UUID ) )
        assert out == sentinel
        assert sess.last_query.filter_calls == 1          # no age cap → base filter only

    def test_get_applies_age_filter_when_capped( self ):
        sess = _FakeSession( [ _fake_notif() ] )
        repo = NotificationRepository( sess )
        repo.get_undelivered_for_recipient( uuid.UUID( VALID_UUID ), max_age_hours=24 )
        assert sess.last_query.filter_calls == 2          # base + created_at cutoff filter

    def test_count_returns_unbounded_total( self ):
        sentinel = [ _fake_notif(), _fake_notif(), _fake_notif() ]
        sess = _FakeSession( sentinel )
        repo = NotificationRepository( sess )
        assert repo.count_undelivered_for_recipient( uuid.UUID( VALID_UUID ) ) == 3
        assert sess.last_query.filter_calls == 1          # no age cap → base filter only

    def test_count_applies_age_filter_when_capped( self ):
        sess = _FakeSession( [ _fake_notif() ] )
        repo = NotificationRepository( sess )
        repo.count_undelivered_for_recipient( uuid.UUID( VALID_UUID ), max_age_hours=24 )
        assert sess.last_query.filter_calls == 2          # base + created_at cutoff filter

    def test_dismiss_returns_rowcount_and_flushes( self ):
        sess = _FakeSession( [ _fake_notif(), _fake_notif() ] )
        repo = NotificationRepository( sess )
        out  = repo.dismiss_undelivered_for_recipient( uuid.UUID( VALID_UUID ) )
        assert out == 2                                   # rowcount from the bulk update
        assert sess.last_query.update_calls == 1
        assert sess.last_query.update_values is not None  # is_hidden=True payload set
        assert sess.last_query.filter_calls == 1          # no age cap → base filter only
        assert sess.flush_calls == 1                      # change is flushed

    def test_dismiss_applies_age_filter_when_capped( self ):
        sess = _FakeSession( [ _fake_notif() ] )
        repo = NotificationRepository( sess )
        repo.dismiss_undelivered_for_recipient( uuid.UUID( VALID_UUID ), max_age_hours=24 )
        assert sess.last_query.filter_calls == 2          # base + created_at cutoff filter (mirrors count)
        assert sess.last_query.update_calls == 1


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
    # _undelivered_max_age_hours() reads main_module.config_mgr — stub it out.
    monkeypatch.setattr( nmod, "_undelivered_max_age_hours", lambda: 24 )


class TestUndeliveredEndpoint:
    def test_success( self, monkeypatch ):
        captured = {}
        def _get( rid, limit, max_age_hours ):
            captured[ "max_age_hours" ] = max_age_hours
            return [ _fake_notif(), _fake_notif() ]
        repo = types.SimpleNamespace( get_undelivered_for_recipient=_get )
        _patch_db( monkeypatch, repo )
        out = asyncio.run( nmod.get_undelivered_notifications( authenticated_user_id=VALID_UUID, limit=100 ) )
        assert out[ "status" ] == "success"
        assert out[ "undelivered_count" ] == 2
        assert len( out[ "notifications" ] ) == 2
        assert captured[ "max_age_hours" ] == 24          # endpoint passes the configured cap through

    def test_bad_uuid_raises_400( self, monkeypatch ):
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.get_undelivered_notifications( authenticated_user_id="not-a-uuid", limit=100 ) )
        assert exc.value.status_code == 400

    def test_repo_error_raises_500( self, monkeypatch ):
        def boom( rid, limit, max_age_hours ):
            raise RuntimeError( "db down" )
        repo = types.SimpleNamespace( get_undelivered_for_recipient=boom )
        _patch_db( monkeypatch, repo )
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.get_undelivered_notifications( authenticated_user_id=VALID_UUID, limit=100 ) )
        assert exc.value.status_code == 500


# ── dismiss (reset) endpoint ─────────────────────────────────────────────────
class TestDismissUndeliveredEndpoint:
    def test_success_zeroes_badge( self, monkeypatch ):
        captured = {}
        def _dismiss( rid, max_age_hours ):
            captured[ "dismiss_age" ] = max_age_hours
            return 5
        def _count( rid, max_age_hours ):
            captured[ "count_age" ] = max_age_hours
            return 0                                       # post-dismiss the badge is empty
        repo = types.SimpleNamespace(
            dismiss_undelivered_for_recipient = _dismiss,
            count_undelivered_for_recipient   = _count,
        )
        _patch_db( monkeypatch, repo )
        out = asyncio.run( nmod.dismiss_undelivered_notifications( authenticated_user_id=VALID_UUID ) )
        assert out[ "status" ] == "success"
        assert out[ "dismissed_count" ]   == 5
        assert out[ "undelivered_count" ] == 0             # surfaced back to the UI as the new badge
        assert captured[ "dismiss_age" ] == 24 and captured[ "count_age" ] == 24   # both honor the cap

    def test_bad_uuid_raises_400( self, monkeypatch ):
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.dismiss_undelivered_notifications( authenticated_user_id="not-a-uuid" ) )
        assert exc.value.status_code == 400

    def test_repo_error_raises_500( self, monkeypatch ):
        def boom( rid, max_age_hours ):
            raise RuntimeError( "db down" )
        repo = types.SimpleNamespace( dismiss_undelivered_for_recipient=boom )
        _patch_db( monkeypatch, repo )
        with pytest.raises( HTTPException ) as exc:
            asyncio.run( nmod.dismiss_undelivered_notifications( authenticated_user_id=VALID_UUID ) )
        assert exc.value.status_code == 500


# ── websocket surfacing helper ───────────────────────────────────────────────
class TestComputeUndeliveredCount:
    def test_returns_count( self, monkeypatch ):
        @contextlib.contextmanager
        def fake_get_db():
            yield "SESSION"
        captured = {}
        def _count( rid, max_age_hours ):
            captured[ "max_age_hours" ] = max_age_hours
            return 3
        monkeypatch.setattr( dbmod, "get_db", fake_get_db )
        monkeypatch.setattr( repomod, "NotificationRepository",
                             lambda session: types.SimpleNamespace( count_undelivered_for_recipient=_count ) )
        monkeypatch.setattr( wsmod, "_undelivered_max_age_hours", lambda: 24 )
        assert wsmod._compute_undelivered_count( VALID_UUID ) == 3
        assert captured[ "max_age_hours" ] == 24          # count call carries the configured cap

    def test_bad_uuid_returns_zero( self, monkeypatch ):
        monkeypatch.setattr( wsmod, "_undelivered_max_age_hours", lambda: 24 )
        assert wsmod._compute_undelivered_count( "not-a-uuid" ) == 0

    def test_db_error_returns_zero( self, monkeypatch ):
        def boom():
            raise RuntimeError( "no db" )
        monkeypatch.setattr( wsmod, "_undelivered_max_age_hours", lambda: 24 )
        monkeypatch.setattr( dbmod, "get_db", boom )
        assert wsmod._compute_undelivered_count( VALID_UUID ) == 0


# ── undelivered age-cap resolver helpers (storm guard) ───────────────────────
class TestUndeliveredMaxAgeHours:
    def _fake_main( self, value ):
        return types.SimpleNamespace(
            config_mgr=types.SimpleNamespace( get=lambda key, default, return_type: value )
        )

    def test_notifications_helper_reads_config( self ):
        with patch.dict( sys.modules, { "lupin_app.main": self._fake_main( 24 ) } ):
            assert nmod._undelivered_max_age_hours() == 24

    def test_websocket_helper_reads_config( self ):
        with patch.dict( sys.modules, { "lupin_app.main": self._fake_main( 12 ) } ):
            assert wsmod._undelivered_max_age_hours() == 12
