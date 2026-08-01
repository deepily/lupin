"""
Unit tests for the late-answer handback pull inbox (§4.4) — Section D, unit tier.

Covers (all mocked — no DB, no server → :7999-eligible):
  - repo `get_answers_owed_for_persona` query WIRING (the three owed terms + the
    optional age/since terms)
  - `_project_owed_answer` — the replayed-answer envelope (rulings 6/7): question
    + answer + responded_at, and the earlier-session flag
  - `GET /notifications/answers-owed` — success + SERVE-DOES-NOT-ACK receipt gate
  - `POST /notifications/answers-owed/ack` — success / 404 / 422 (ack-on-consume)

⚠️ WIRING ONLY — NOT the exclusion proof. This fake session returns its result
unconditionally; it CANNOT evaluate the owed predicate, so it proves the query is
BUILT with the right terms, never that Postgres EXCLUDES a forged-default row. The
true per-term insert-then-exclude proofs (B-V2 / C-V3 / D-V3) and the
cursor-on-responded_at proof (D-V4) are the :8000 real-DB twins (Rachel's tier) —
an empty result here would be equally consistent with an empty table.
"""

import uuid
import types
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from cosa.rest.routers import notifications as nmod
from cosa.rest.db.repositories.notification_repository import NotificationRepository


VALID_UUID = "12345678-1234-1234-1234-123456789abc"


def _fake_owed( **kw ):
    base = {
        "id"                  : uuid.UUID( VALID_UUID ),
        "sender_id"           : "claude.code@lupin.deepily.ai#abcd1234",
        "sender_persona"      : "tiberius",
        "title"               : "action:ask",
        "message"             : "Ship it?",
        "abstract"            : None,
        "response_value"      : { "value": "yes", "source": "ui" },
        "responded_at"        : datetime( 2026, 8, 1, 12, 0, tzinfo=timezone.utc ),
        "created_at"          : datetime( 2026, 8, 1, 11, 0, tzinfo=timezone.utc ),
        "job_id"              : None,
    }
    base.update( kw )
    return types.SimpleNamespace( **base )


class _FakeQuery:
    def __init__( self, result ):
        self.result         = result
        self.filter_calls   = 0
        self.order_by_cols  = None
    def filter( self, *a, **k ):
        self.filter_calls += 1
        return self
    def order_by( self, *cols ):
        self.order_by_cols = cols
        return self
    def limit( self, n ): return self
    def all( self ): return self.result


class _FakeSession:
    def __init__( self, result ):
        self.result     = result
        self.last_query = None
    def query( self, model ):
        self.last_query = _FakeQuery( self.result )
        return self.last_query


# ── repo query wiring ────────────────────────────────────────────────────────
class TestOwedQueryWiring:
    def test_returns_session_result_with_three_base_terms( self ):
        sentinel = [ _fake_owed(), _fake_owed() ]
        sess = _FakeSession( sentinel )
        out  = NotificationRepository( sess ).get_answers_owed_for_persona( "tiberius" )
        assert out == sentinel
        # One .filter() carrying the four owed terms (persona + response_requested +
        # responded_at-NOT-NULL + answer_delivered_at-IS-NULL); no age/since term.
        assert sess.last_query.filter_calls == 1

    def test_age_cap_adds_a_term( self ):
        sess = _FakeSession( [ _fake_owed() ] )
        NotificationRepository( sess ).get_answers_owed_for_persona( "tiberius", max_age_hours=24 )
        assert sess.last_query.filter_calls == 2          # base + created_at cutoff

    def test_since_cursor_adds_a_term( self ):
        sess = _FakeSession( [ _fake_owed() ] )
        cursor = datetime( 2026, 8, 1, 10, 0, tzinfo=timezone.utc )
        NotificationRepository( sess ).get_answers_owed_for_persona( "tiberius", since=cursor )
        assert sess.last_query.filter_calls == 2          # base + responded_at cursor

    def test_orders_on_responded_at_not_created_at( self ):
        # D-V4 wiring form: the sort key must be responded_at (the real cursor
        # proof — a 20h-old ask answered 2m ago still delivers — is Rachel's :8000 twin).
        sess = _FakeSession( [ _fake_owed() ] )
        NotificationRepository( sess ).get_answers_owed_for_persona( "tiberius" )
        ( sort_col, ) = sess.last_query.order_by_cols
        assert "responded_at" in str( sort_col )
        assert "created_at" not in str( sort_col )


# ── projection: the replayed-answer envelope (rulings 6/7) ───────────────────
class TestOwedProjection:
    def test_carries_question_and_answer_and_responded_at( self ):
        env = nmod._project_owed_answer( _fake_owed() )
        assert env[ "question" ] == "Ship it?"              # original ask — never a bare answer
        assert env[ "response_value" ] == { "value": "yes", "source": "ui" }
        assert env[ "responded_at" ] == "2026-08-01T12:00:00+00:00"
        assert env[ "sender_persona" ] == "tiberius"
        assert env[ "session_hash8" ] == "abcd1234"

    def test_from_earlier_session_true_when_hashes_differ( self ):
        env = nmod._project_owed_answer( _fake_owed(), requesting_session_hash8="ffff9999" )
        assert env[ "from_earlier_session" ] is True        # ruling 6 — delivered, FLAGGED

    def test_from_earlier_session_false_when_same_hash( self ):
        env = nmod._project_owed_answer( _fake_owed(), requesting_session_hash8="abcd1234" )
        assert env[ "from_earlier_session" ] is False

    def test_from_earlier_session_false_when_no_requesting_hash( self ):
        env = nmod._project_owed_answer( _fake_owed(), requesting_session_hash8=None )
        assert env[ "from_earlier_session" ] is False

    def test_session_hash8_none_when_sender_has_no_suffix( self ):
        env = nmod._project_owed_answer( _fake_owed( sender_id="claude.code@lupin.deepily.ai" ) )
        assert env[ "session_hash8" ] is None


# ── endpoints ────────────────────────────────────────────────────────────────
def _ctx_db( repo ):
    gd = Mock()
    gd.return_value.__enter__ = Mock( return_value=Mock() )
    gd.return_value.__exit__  = Mock( return_value=False )
    return gd


class TestAnswersOwedEndpoints:
    def _patch_main( self ):
        cfg = Mock(); cfg.get.return_value = 24
        m = Mock(); m.config_mgr = cfg
        import sys
        pkg = Mock(); pkg.main = m
        return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": m } )

    def test_get_answers_owed_success_and_does_not_ack( self ):
        repo = Mock()
        repo.get_answers_owed_for_persona.return_value = [ _fake_owed() ]
        with patch.object( nmod, "get_db", _ctx_db( repo ) ), \
             patch.object( nmod, "NotificationRepository", return_value=repo ), \
             patch.object( nmod, "get_local_timestamp", return_value="T" ), \
             self._patch_main(), patch( "builtins.print" ):
            out = asyncio.run( nmod.get_answers_owed(
                authenticated_user_id="svc", persona="tiberius", session_hash8="ffff9999",
                since=None, limit=100 ) )
        assert out[ "status" ] == "success"
        assert out[ "owed_count" ] == 1
        assert out[ "answers" ][ 0 ][ "from_earlier_session" ] is True
        # SERVING must NEVER stamp answer_delivered_at — only /ack does (§4.3 setter b).
        repo.mark_answer_delivered.assert_not_called()

    def test_get_answers_owed_bad_since_400( self ):
        repo = Mock()
        with patch.object( nmod, "get_db", _ctx_db( repo ) ), \
             patch.object( nmod, "NotificationRepository", return_value=repo ), \
             self._patch_main(), patch( "builtins.print" ):
            with pytest.raises( HTTPException ) as ei:
                asyncio.run( nmod.get_answers_owed(
                    authenticated_user_id="svc", persona="tiberius", session_hash8=None,
                    since="not-a-timestamp", limit=100 ) )
        assert ei.value.status_code == 400

    def test_get_answers_owed_error_500( self ):
        repo = Mock()
        repo.get_answers_owed_for_persona.side_effect = RuntimeError( "db down" )
        with patch.object( nmod, "get_db", _ctx_db( repo ) ), \
             patch.object( nmod, "NotificationRepository", return_value=repo ), \
             self._patch_main(), patch( "builtins.print" ):
            with pytest.raises( HTTPException ) as ei:
                asyncio.run( nmod.get_answers_owed(
                    authenticated_user_id="svc", persona="tiberius", session_hash8=None,
                    since=None, limit=100 ) )
        assert ei.value.status_code == 500

    def test_ack_success_marks_delivered( self ):
        repo = Mock()
        repo.mark_answer_delivered.return_value = _fake_owed()   # found
        with patch.object( nmod, "get_db", _ctx_db( repo ) ), \
             patch.object( nmod, "NotificationRepository", return_value=repo ), \
             patch.object( nmod, "get_local_timestamp", return_value="T" ), \
             patch( "builtins.print" ):
            out = asyncio.run( nmod.ack_answer_owed(
                authenticated_user_id="svc", request_body={ "notification_id": VALID_UUID } ) )
        assert out[ "status" ] == "success"
        repo.mark_answer_delivered.assert_called_once()

    def test_ack_missing_id_422( self ):
        with pytest.raises( HTTPException ) as ei:
            asyncio.run( nmod.ack_answer_owed( authenticated_user_id="svc", request_body={} ) )
        assert ei.value.status_code == 422

    def test_ack_not_found_404( self ):
        repo = Mock()
        repo.mark_answer_delivered.return_value = None          # row absent
        with patch.object( nmod, "get_db", _ctx_db( repo ) ), \
             patch.object( nmod, "NotificationRepository", return_value=repo ), \
             patch( "builtins.print" ):
            with pytest.raises( HTTPException ) as ei:
                asyncio.run( nmod.ack_answer_owed(
                    authenticated_user_id="svc", request_body={ "notification_id": VALID_UUID } ) )
        assert ei.value.status_code == 404


def isolated_unit_test():
    """Run this module's tests in isolation for the smoke-runner harness."""
    import time
    start = time.time()
    code = pytest.main( [ __file__, "-q", "-p", "no:cacheprovider" ] )
    return ( code == 0 ), time.time() - start, f"pytest exit {code}"


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} answers-owed handback tests in {secs:.3f}s — {msg}" )
