#!/usr/bin/env python3
"""
Unit tests for the cosa-voice conversation mode router.

Tests the GET / POST endpoints at /api/cosa-voice/conversation-mode/{session_id}:
    - GET reads conversation_mode_active from the session bridge
    - POST writes the flag AND queues a conversation_mode_changed notification
    - 404 when bridge file is missing
    - 500 when bridge found but write fails

The router was migrated 2026-04-29 from ad-hoc `ws_manager.emit_to_user(...)`
calls to the canonical notification subsystem via `notification_queue.push_notification(
type="conversation_mode_changed", payload={...})`. Tests verify the migrated
contract: a single push_notification call carrying the payload dict, instead
of a top-level WS event with positional args. See:
    src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md

Uses a tmp SESSION_DIR via patch + a mock NotificationFifoQueue so tests don't
mutate real bridge files or require a live server.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_session_file( sessions_dir, pid, session_id ):
    path = sessions_dir / f"cc-{pid}.json"
    data = {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "cwd"               : "/tmp",
        "ppid"              : os.getpid(),
    }
    with open( path, "w" ) as f:
        json.dump( data, f )
    return path


def _push_kwargs( mock_nq, call_index=0 ):
    """Extract kwargs from the Nth push_notification call on a mock queue."""
    return mock_nq.push_notification.call_args_list[ call_index ].kwargs


# ── Tests: GET endpoint ──────────────────────────────────────────────────────

class TestGetConversationModeEndpoint:

    @pytest.mark.asyncio
    async def test_returns_default_false_when_flag_missing( self ):
        """GET reads False when bridge has no conversation_mode_active field."""
        from cosa.rest.routers.conversation_mode import get_conversation_mode_endpoint

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "endpoint-1111-2222-3333-444455556666"
            _write_session_file( sessions_dir, os.getpid(), sid )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await get_conversation_mode_endpoint( sid, authenticated_user_id="user@test.com" )

            body = json.loads( resp.body.decode() )
            assert body == { "session_id": sid, "active": False }

    @pytest.mark.asyncio
    async def test_returns_true_when_flag_set( self ):
        """GET reads True when bridge has conversation_mode_active=True."""
        from cosa.rest.routers.conversation_mode import get_conversation_mode_endpoint

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "endpoint-2222-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )
            # Pre-set the flag
            with open( path ) as f:
                data = json.load( f )
            data[ "conversation_mode_active" ] = True
            with open( path, "w" ) as f:
                json.dump( data, f )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await get_conversation_mode_endpoint( sid, authenticated_user_id="user@test.com" )

            body = json.loads( resp.body.decode() )
            assert body == { "session_id": sid, "active": True }

    @pytest.mark.asyncio
    async def test_returns_404_when_bridge_missing( self ):
        """GET raises 404 when session_id does not match any bridge file."""
        from cosa.rest.routers.conversation_mode import get_conversation_mode_endpoint

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                with pytest.raises( HTTPException ) as exc_info:
                    await get_conversation_mode_endpoint( "nonexistent", authenticated_user_id="user@test.com" )

            assert exc_info.value.status_code == 404


# ── Tests: POST endpoint ─────────────────────────────────────────────────────

class TestSetConversationModeEndpoint:

    @pytest.mark.asyncio
    async def test_post_writes_bridge_and_pushes_notification( self ):
        """POST writes flag to bridge and pushes conversation_mode_changed notification."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "post1111-1111-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Bridge mutated
            with open( path ) as f:
                data = json.load( f )
            assert data[ "conversation_mode_active" ] is True

            # Single push_notification call carrying the migrated shape
            mock_nq.push_notification.assert_called_once()
            kw = _push_kwargs( mock_nq )
            assert kw[ "type"     ] == "conversation_mode_changed"
            assert kw[ "user_id"  ] == "user@test.com"
            assert kw[ "payload"  ] == { "session_id": sid, "active": True }
            assert kw[ "suppress_ding" ]      is True
            assert kw[ "response_requested" ] is False

            # Response shape
            body = json.loads( resp.body.decode() )
            assert body[ "session_id" ] == sid
            assert body[ "active" ] is True
            assert body[ "broadcast_delivered" ] is True

    @pytest.mark.asyncio
    async def test_post_with_active_false_round_trip( self ):
        """POST active=False clears the flag and pushes a notification."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "post2222-1111-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )
            with open( path ) as f:
                data = json.load( f )
            data[ "conversation_mode_active" ] = True
            with open( path, "w" ) as f:
                json.dump( data, f )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid,
                    body=ConversationModeBody( active=False ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            with open( path ) as f:
                data = json.load( f )
            assert data[ "conversation_mode_active" ] is False

            body = json.loads( resp.body.decode() )
            assert body[ "active" ] is False

    @pytest.mark.asyncio
    async def test_post_returns_404_when_bridge_missing( self ):
        """POST returns 404 when no bridge matches session_id."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                with pytest.raises( HTTPException ) as exc_info:
                    await set_conversation_mode_endpoint(
                        session_id="nonexistent",
                        body=ConversationModeBody( active=True ),
                        authenticated_user_id="user@test.com",
                        notification_queue=mock_nq
                    )

            assert exc_info.value.status_code == 404
            mock_nq.push_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_succeeds_even_if_push_fails( self ):
        """POST is canonical write; notification-push failure is logged but does not fail the request."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "post3333-1111-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )

            mock_nq = MagicMock()
            mock_nq.push_notification.side_effect = RuntimeError( "queue dispatch broken" )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Bridge write still happened
            with open( path ) as f:
                data = json.load( f )
            assert data[ "conversation_mode_active" ] is True

            body = json.loads( resp.body.decode() )
            assert body[ "active" ] is True
            assert body[ "broadcast_delivered" ] is False


# ── Tests: auto-displace (mutual exclusion across sessions) ──────────────────


class TestAutoDisplaceOnActivate:
    """
    The mutex contract: when session B activates, ANY other bridge with
    conversation_mode_active=true must be flipped off, with a separate
    conversation_mode_changed notification carrying displaced=True and
    displaced_by=<B's session_id> in the payload. The activate-then-displace
    sequence is serialized by an asyncio.Lock at module scope.
    """

    @pytest.mark.asyncio
    async def test_activate_displaces_existing_active_session( self ):
        """A is active; activate B → A flipped off + displaced notification + B activated."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "displa-a1-1111-2222-3333-444455556666"
            sid_b = "displa-b2-1111-2222-3333-444455556666"
            path_a = _write_session_file( sessions_dir, 70001, sid_a )
            path_b = _write_session_file( sessions_dir, 70002, sid_b )

            # Pre-set A active
            with open( path_a ) as f:
                data_a = json.load( f )
            data_a[ "conversation_mode_active" ] = True
            with open( path_a, "w" ) as f:
                json.dump( data_a, f )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # A's bridge flipped off
            with open( path_a ) as f:
                data_a = json.load( f )
            assert data_a[ "conversation_mode_active" ] is False

            # B's bridge flipped on
            with open( path_b ) as f:
                data_b = json.load( f )
            assert data_b[ "conversation_mode_active" ] is True

            # Three push_notification calls per displacement:
            #   1) conversation_mode_changed (displaced=True) — UI sync for A
            #   2) user_initiated_message (action:exit_conversation_mode) — listener
            #      injects deactivation reminder into A's tmux pane so the
            #      model's in-context state catches up to the bridge flip
            #   3) activate for B
            assert mock_nq.push_notification.call_count == 3

            # First call: displaced notification for A
            kw_first = _push_kwargs( mock_nq, 0 )
            assert kw_first[ "type"    ] == "conversation_mode_changed"
            assert kw_first[ "user_id" ] == "user@test.com"
            assert kw_first[ "payload" ] == {
                "session_id"   : sid_a,
                "active"       : False,
                "displaced"    : True,
                "displaced_by" : sid_b
            }

            # Second call: action push for A's listener
            kw_action = _push_kwargs( mock_nq, 1 )
            assert kw_action[ "type"   ] == "user_initiated_message"
            assert kw_action[ "title"  ] == "action:exit_conversation_mode"
            assert kw_action[ "job_id" ] == sid_a[:8]

            # Third call: B's activate notification (no displaced flag)
            kw_third = _push_kwargs( mock_nq, 2 )
            assert kw_third[ "type"    ] == "conversation_mode_changed"
            assert kw_third[ "payload" ] == { "session_id": sid_b, "active": True }

            # Response payload includes the displaced session id
            body = json.loads( resp.body.decode() )
            assert body[ "session_id" ] == sid_b
            assert body[ "active" ] is True
            assert body[ "displaced_sessions" ] == [ sid_a ]

    @pytest.mark.asyncio
    async def test_activate_with_no_other_active_pushes_only_activate( self ):
        """No other bridges active → only B's activate notification pushed; displaced_sessions is empty."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_b = "soloact-1-1111-2222-3333-444455556666"
            _write_session_file( sessions_dir, os.getpid(), sid_b )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Exactly one push — the activate
            assert mock_nq.push_notification.call_count == 1
            kw = _push_kwargs( mock_nq )
            assert kw[ "payload" ] == { "session_id": sid_b, "active": True }

            body = json.loads( resp.body.decode() )
            assert body[ "displaced_sessions" ] == []

    @pytest.mark.asyncio
    async def test_activate_displaces_multiple_active_sessions( self ):
        """Three pre-active sessions → all three displaced, four total pushes (3 displaced + 1 activate)."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sids = [
                "multi-a1-1111-2222-3333-444455556666",
                "multi-a2-1111-2222-3333-444455556666",
                "multi-a3-1111-2222-3333-444455556666",
            ]
            sid_b = "multi-b9-1111-2222-3333-444455556666"
            paths = []
            for i, sid in enumerate( sids ):
                p = _write_session_file( sessions_dir, 80001 + i, sid )
                with open( p ) as f:
                    data = json.load( f )
                data[ "conversation_mode_active" ] = True
                with open( p, "w" ) as f:
                    json.dump( data, f )
                paths.append( p )
            _write_session_file( sessions_dir, 80100, sid_b )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # All three pre-active bridges flipped off
            for p in paths:
                with open( p ) as f:
                    data = json.load( f )
                assert data[ "conversation_mode_active" ] is False

            # Per-displaced-session push pair (displaced WS event + action push) ×3
            # plus the final activate push for B = 7 total.
            assert mock_nq.push_notification.call_count == 7

            # Last call is the activate event for B
            last_kw = _push_kwargs( mock_nq, -1 )
            assert last_kw[ "payload" ] == { "session_id": sid_b, "active": True }

            # Action pushes interleaved with displaced pushes — each displaced
            # session got an action:exit_conversation_mode targeted at its hash
            action_calls = [
                _push_kwargs( mock_nq, i ) for i in range( 6 )
                if _push_kwargs( mock_nq, i ).get( "title" ) == "action:exit_conversation_mode"
            ]
            assert len( action_calls ) == 3
            action_job_ids = sorted( c[ "job_id" ] for c in action_calls )
            assert action_job_ids == sorted( s[:8] for s in sids )

            body = json.loads( resp.body.decode() )
            assert sorted( body[ "displaced_sessions" ] ) == sorted( sids )

    @pytest.mark.asyncio
    async def test_deactivate_does_not_scan_or_displace( self ):
        """active=false bypasses the lock + scan; only pushes its own deactivate notification."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "deact1-1-1111-2222-3333-444455556666"
            sid_b = "deact1-2-1111-2222-3333-444455556666"
            path_a = _write_session_file( sessions_dir, 90001, sid_a )
            _write_session_file( sessions_dir, 90002, sid_b )
            # A is active; we are deactivating B (which is not active) — A must NOT be touched
            with open( path_a ) as f:
                data_a = json.load( f )
            data_a[ "conversation_mode_active" ] = True
            with open( path_a, "w" ) as f:
                json.dump( data_a, f )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=False ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # A is untouched — deactivate path skips the scan
            with open( path_a ) as f:
                data_a = json.load( f )
            assert data_a[ "conversation_mode_active" ] is True

            # Exactly one push — B's deactivate event
            assert mock_nq.push_notification.call_count == 1
            kw = _push_kwargs( mock_nq )
            assert kw[ "payload" ] == { "session_id": sid_b, "active": False }

            body = json.loads( resp.body.decode() )
            assert body[ "active" ] is False
            assert body[ "displaced_sessions" ] == []

    @pytest.mark.asyncio
    async def test_displace_push_failure_does_not_block_activate( self ):
        """If displaced-event push raises, the bridge writes still happen and B still activates."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "wsfail-a-1111-2222-3333-444455556666"
            sid_b = "wsfail-b-1111-2222-3333-444455556666"
            path_a = _write_session_file( sessions_dir, 70001, sid_a )
            path_b = _write_session_file( sessions_dir, 70002, sid_b )
            with open( path_a ) as f:
                data_a = json.load( f )
            data_a[ "conversation_mode_active" ] = True
            with open( path_a, "w" ) as f:
                json.dump( data_a, f )

            # First push (displaced for A) raises; second (action for A) and
            # third (activate for B) succeed. Both displaced-event and action
            # pushes are best-effort — failure of one does not block the other
            # or the activate write.
            mock_nq = MagicMock()
            mock_nq.push_notification.side_effect = [ RuntimeError( "queue ded" ), None, None ]

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Both bridge writes succeeded despite push failure
            with open( path_a ) as f:
                assert json.load( f )[ "conversation_mode_active" ] is False
            with open( path_b ) as f:
                assert json.load( f )[ "conversation_mode_active" ] is True

            body = json.loads( resp.body.decode() )
            assert body[ "active" ] is True
            assert body[ "displaced_sessions" ] == [ sid_a ]

    @pytest.mark.asyncio
    async def test_self_activation_does_not_displace_self( self ):
        """Activating an already-active session is a no-op displacement (exclude_session_id filters it)."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "selfact1-1111-2222-3333-444455556666"
            path_a = _write_session_file( sessions_dir, os.getpid(), sid_a )
            with open( path_a ) as f:
                data = json.load( f )
            data[ "conversation_mode_active" ] = True
            with open( path_a, "w" ) as f:
                json.dump( data, f )

            mock_nq = MagicMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_a,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    notification_queue=mock_nq
                )

            # Only one push — self's activate event. No spurious displaced event.
            assert mock_nq.push_notification.call_count == 1

            body = json.loads( resp.body.decode() )
            assert body[ "displaced_sessions" ] == []


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
