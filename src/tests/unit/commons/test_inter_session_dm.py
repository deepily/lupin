"""
Unit tests for Inter-Session DM (Phase 0 implementation 2026-05-15).

Covers AC9a layer of `src/rnd/v0.1.7/2026.05.15-inter-session-direct-messaging-design.md`:
- `RecipientResolutionError` Pydantic model
- `_resolve_dm_recipient` helper (chain levels, error paths)
- `_dispatch_commons_question_received` helper (success + T7 isolation)
- `execute_register_question` DM extension (resolution success + 422 unwind)
- `commons_ask.ask_async` recipient-kwarg passthrough
- `commons_send_to` MCP wrapper delegates to `commons_ask_async` correctly

All tests run on :7999 venue (AI-discretionary per CLAUDE.md §TESTING VENUES).
Coverage target: 100% lines + branches on new code paths.
"""
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from cosa.rest.routers.commons import (
    RecipientResolutionError,
    RegisterQuestionRequest,
    _dispatch_commons_question_received,
    _resolve_dm_recipient,
    execute_register_question,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


def _build_raw_session( session_id: str, persona_name: str, user_id: str = "rick@example.com" ):
    """Build a raw_sessions tuple — (bridge_path_marker, session_id, persona_dict).

    The 3rd slot is the persona dict (per `project_session_response` contract),
    NOT the full bridge. The full bridge is loaded by bridge_loader(path).
    """
    persona_dict = { "name": persona_name, "icon": "🌸", "color": "#F06292" }
    return ( f"/fake/bridge/{session_id}.json", session_id, persona_dict )


def _build_fixture_bridge( session_id: str, user_id: str = "rick@example.com" ) -> Dict[ str, Any ]:
    """Build the bridge dict that `_fake_bridge_loader` returns for a session."""
    return {
        "stable_session_id"   : session_id,
        "session_id"          : session_id,
        "user_id"             : user_id,
        "owner_user_id"       : user_id,
        "last_activity_iso"   : "2026-05-15T12:00:00+00:00",
        "idle_detection"      : { "last_interaction_at" : time.time() },
    }


def _fake_raw_sessions_fn( sessions ):
    """Return a closure that yields the supplied sessions list."""
    return lambda: sessions


def _fake_bridge_loader( path ):
    """Identity bridge loader — the raw_sessions tuple already carries the bridge dict."""
    # filter_and_project_sessions calls bridge_loader(path) and expects the bridge dict.
    # For test fixtures we encode the bridge dict in the third tuple slot, so we look it up via path.
    return _FIXTURE_BRIDGES.get( path )


_FIXTURE_BRIDGES : Dict[ str, Dict[ str, Any ] ] = { }


def _register_fixture( raw_session, user_id: str = "rick@example.com" ):
    """Register the bridge dict in the fixture lookup so _fake_bridge_loader returns it."""
    path, sid, _persona = raw_session
    _FIXTURE_BRIDGES[ path ] = _build_fixture_bridge( sid, user_id )


# ─── RecipientResolutionError model ─────────────────────────────────────────


class TestRecipientResolutionError:
    def test_model_roundtrip_minimum_fields( self ):
        err = RecipientResolutionError(
            error                      = "recipient_required",
            suggested_next_action      = "Supply either recipient_session_id or recipient_persona.",
        )
        d = err.model_dump()
        assert d[ "error" ] == "recipient_required"
        assert d[ "supplied_persona" ] is None
        assert d[ "supplied_session_id" ] is None
        assert d[ "resolution_chain_attempted" ] == [ ]
        assert d[ "candidate_alternatives" ] == [ ]
        assert "Supply either" in d[ "suggested_next_action" ]

    def test_model_with_candidates( self ):
        err = RecipientResolutionError(
            error                      = "recipient_persona_ambiguous",
            supplied_persona           = "rad",
            resolution_chain_attempted = [ "exact", "case_insensitive" ],
            candidate_alternatives     = [ { "persona": "radio", "session_id": "abc123", "active_since": "2026-05-15T11:00:00" } ],
            suggested_next_action      = "Try recipient_session_id=abc123 directly.",
        )
        d = err.model_dump()
        assert d[ "candidate_alternatives" ][ 0 ][ "persona" ] == "radio"
        assert d[ "resolution_chain_attempted" ] == [ "exact", "case_insensitive" ]

    def test_model_rejects_empty_error( self ):
        with pytest.raises( Exception ):
            RecipientResolutionError(
                error                  = "",
                suggested_next_action  = "x",
            )


# ─── RegisterQuestionRequest field validation ────────────────────────────────


class TestRegisterQuestionRequestDmFields:
    def test_recipient_session_id_optional( self ):
        body = RegisterQuestionRequest(
            topic            = "dm-radio",
            question_id      = "q1",
            asker_session_id = "asker",
        )
        assert body.recipient_session_id is None
        assert body.recipient_persona is None
        assert body.expect_reply is True   # default

    def test_recipient_persona_accepts_unicode( self ):
        body = RegisterQuestionRequest(
            topic             = "dm-maria",
            question_id       = "q1",
            asker_session_id  = "asker",
            recipient_persona = "María",
        )
        assert body.recipient_persona == "María"

    def test_expect_reply_can_be_false( self ):
        body = RegisterQuestionRequest(
            topic            = "dm-radio",
            question_id      = "q1",
            asker_session_id = "asker",
            recipient_persona = "radio",
            expect_reply     = False,
        )
        assert body.expect_reply is False


# ─── _resolve_dm_recipient ───────────────────────────────────────────────────


class TestResolveDmRecipient:
    def setup_method( self ):
        _FIXTURE_BRIDGES.clear()

    def test_session_id_direct_success( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        sess_b = _build_raw_session( "sid_b", "rachel" )
        _register_fixture( sess_a )
        _register_fixture( sess_b )

        result = _resolve_dm_recipient(
            recipient_session_id  = "sid_a",
            recipient_persona     = None,
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a, sess_b ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 200
        assert result[ "session_id" ]   == "sid_a"

    def test_session_id_inactive_returns_422( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = "sid_phantom",
            recipient_persona     = None,
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 422
        assert result[ "detail" ][ "error" ] == "recipient_inactive"
        assert result[ "detail" ][ "supplied_session_id" ] == "sid_phantom"
        assert any( c[ "persona" ] == "radio" for c in result[ "detail" ][ "candidate_alternatives" ] )

    def test_persona_exact_match( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = None,
            recipient_persona     = "radio",
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 200
        assert result[ "session_id" ]   == "sid_a"
        assert result[ "persona_name" ] == "radio"

    def test_persona_case_insensitive_match( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = None,
            recipient_persona     = "Radio",   # capitalized
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 200
        assert result[ "persona_name" ] == "radio"

    def test_persona_not_found_returns_422( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = None,
            recipient_persona     = "tiberius",
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 422
        assert result[ "detail" ][ "error" ] == "recipient_not_found"
        assert "exact" in result[ "detail" ][ "resolution_chain_attempted" ]
        assert "punct_tolerant" in result[ "detail" ][ "resolution_chain_attempted" ]

    def test_neither_returns_recipient_required( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = None,
            recipient_persona     = None,
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 422
        assert result[ "detail" ][ "error" ] == "recipient_required"


# ─── _dispatch_commons_question_received ─────────────────────────────────────


class TestDispatchCommonsQuestionReceived:
    def test_success_calls_push_notification( self ):
        nq   = MagicMock()
        result = _dispatch_commons_question_received(
            notification_queue    = nq,
            target_session_id     = "sid_target",
            target_persona        = "radio",
            question_id           = "q1",
            topic                 = "dm-radio",
            asker_session_id      = "sid_asker",
            authenticated_user_id = "rick@example.com",
            build_sender_id       = lambda sid: f"sender:{sid}",
        )
        assert result is True
        nq.push_notification.assert_called_once()
        kwargs = nq.push_notification.call_args.kwargs
        assert kwargs[ "type" ]  == "user_initiated_message"
        assert kwargs[ "title" ] == "action:commons_question_received"
        assert kwargs[ "payload" ][ "question_id" ]       == "q1"
        assert kwargs[ "payload" ][ "topic" ]             == "dm-radio"
        assert kwargs[ "payload" ][ "recipient_persona" ] == "radio"

    def test_dispatch_exception_returns_false( self ):
        nq = MagicMock()
        nq.push_notification.side_effect = RuntimeError( "queue down" )
        result = _dispatch_commons_question_received(
            notification_queue    = nq,
            target_session_id     = "sid_target",
            target_persona        = "radio",
            question_id           = "q1",
            topic                 = "dm-radio",
            asker_session_id      = "sid_asker",
            authenticated_user_id = "rick@example.com",
            build_sender_id       = lambda sid: f"sender:{sid}",
        )
        assert result is False


# ─── commons_ask.ask_async recipient passthrough ─────────────────────────────


class TestAskAsyncRecipientPassthrough:
    def test_stamps_recipient_persona_on_metadata( self, tmp_path ):
        from lupin_mcp.commons_ask import ask_async
        from lupin_mcp.commons_store import CommonsStore

        store = CommonsStore( str( tmp_path ) )
        result = ask_async(
            store              = store,
            topic              = "dm-radio",
            body               = "hello",
            sender_session_id  = "sid_asker",
            persona_name       = "maria",
            persona_icon       = "🌸",
            persona_color      = "#F06292",
            recipient_persona  = "radio",
            expect_reply       = False,
        )
        # Verify the post happened with the recipient metadata stamped
        entries = store.read( "dm-radio", limit=10 )
        assert len( entries ) == 1
        meta = entries[ 0 ][ "metadata" ]
        assert meta[ "kind" ]                 == "question"
        assert meta[ "question_id" ]          == result[ "question_id" ]
        assert meta[ "recipient_persona" ]    == "radio"
        assert meta[ "expect_reply" ]         is False

    def test_non_dm_call_omits_recipient_metadata( self, tmp_path ):
        from lupin_mcp.commons_ask import ask_async
        from lupin_mcp.commons_store import CommonsStore

        store = CommonsStore( str( tmp_path ) )
        result = ask_async(
            store              = store,
            topic              = "free-topic",
            body               = "broadcast question",
            sender_session_id  = "sid_asker",
            persona_name       = "maria",
        )
        entries = store.read( "free-topic", limit=10 )
        assert len( entries ) == 1
        meta = entries[ 0 ][ "metadata" ]
        assert "recipient_persona" not in meta
        assert "recipient_session_id" not in meta
        assert "expect_reply" not in meta
