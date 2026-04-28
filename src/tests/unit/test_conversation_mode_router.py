#!/usr/bin/env python3
"""
Unit tests for the cosa-voice conversation mode router.

Tests the GET / POST endpoints at /api/cosa-voice/conversation-mode/{session_id}:
    - GET reads conversation_mode_active from the session bridge
    - POST writes the flag AND broadcasts a conversation_mode_changed WS event
    - 404 when bridge file is missing
    - 500 when bridge found but write fails

Uses a tmp SESSION_DIR via patch + a mock WebSocketManager so tests don't
mutate real bridge files or require a live server.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
    async def test_post_writes_bridge_and_broadcasts( self ):
        """POST writes flag to bridge and emits conversation_mode_changed to authenticated user."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "post1111-1111-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )

            mock_ws = AsyncMock()
            mock_ws.emit_to_user.return_value = True

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    ws_manager=mock_ws
                )

            # Bridge mutated
            with open( path ) as f:
                data = json.load( f )
            assert data[ "conversation_mode_active" ] is True

            # Broadcast called with right args
            mock_ws.emit_to_user.assert_awaited_once_with(
                "user@test.com",
                "conversation_mode_changed",
                { "session_id": sid, "conversation_mode_active": True }
            )

            # Response shape
            body = json.loads( resp.body.decode() )
            assert body[ "session_id" ] == sid
            assert body[ "active" ] is True
            assert body[ "broadcast_delivered" ] is True

    @pytest.mark.asyncio
    async def test_post_with_active_false_round_trip( self ):
        """POST active=False clears the flag and broadcasts."""
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

            mock_ws = AsyncMock()
            mock_ws.emit_to_user.return_value = True

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid,
                    body=ConversationModeBody( active=False ),
                    authenticated_user_id="user@test.com",
                    ws_manager=mock_ws
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
            mock_ws = AsyncMock()

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                with pytest.raises( HTTPException ) as exc_info:
                    await set_conversation_mode_endpoint(
                        session_id="nonexistent",
                        body=ConversationModeBody( active=True ),
                        authenticated_user_id="user@test.com",
                        ws_manager=mock_ws
                    )

            assert exc_info.value.status_code == 404
            mock_ws.emit_to_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_post_succeeds_even_if_broadcast_fails( self ):
        """POST is canonical write; broadcast failure is logged but does not fail the request."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "post3333-1111-2222-3333-444455556666"
            path = _write_session_file( sessions_dir, os.getpid(), sid )

            mock_ws = AsyncMock()
            mock_ws.emit_to_user.side_effect = RuntimeError( "ws connection broken" )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    ws_manager=mock_ws
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
    conversation_mode_changed WS event carrying displaced=true and
    displaced_by=<B's session_id>. The activate-then-displace sequence is
    serialized by an asyncio.Lock at module scope.
    """

    @pytest.mark.asyncio
    async def test_activate_displaces_existing_active_session( self ):
        """A is active; activate B → A flipped off + displaced event + B activated."""
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

            mock_ws = AsyncMock()
            mock_ws.emit_to_user.return_value = True

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    ws_manager=mock_ws
                )

            # A's bridge flipped off
            with open( path_a ) as f:
                data_a = json.load( f )
            assert data_a[ "conversation_mode_active" ] is False

            # B's bridge flipped on
            with open( path_b ) as f:
                data_b = json.load( f )
            assert data_b[ "conversation_mode_active" ] is True

            # Two WS broadcasts: first the displaced event for A, then the activate for B
            calls = mock_ws.emit_to_user.await_args_list
            assert len( calls ) == 2

            # First call: displaced event for A
            user_arg, event_arg, payload_arg = calls[0].args
            assert user_arg == "user@test.com"
            assert event_arg == "conversation_mode_changed"
            assert payload_arg == {
                "session_id"               : sid_a,
                "conversation_mode_active" : False,
                "displaced"                : True,
                "displaced_by"             : sid_b
            }

            # Second call: B's activate event (no displaced flag)
            _u, _e, payload_b = calls[1].args
            assert payload_b == { "session_id": sid_b, "conversation_mode_active": True }

            # Response payload includes the displaced session id
            body = json.loads( resp.body.decode() )
            assert body[ "session_id" ] == sid_b
            assert body[ "active" ] is True
            assert body[ "displaced_sessions" ] == [ sid_a ]

    @pytest.mark.asyncio
    async def test_activate_with_no_other_active_emits_only_activate_event( self ):
        """No other bridges active → only B's activate event broadcasts; displaced_sessions is empty."""
        from cosa.rest.routers.conversation_mode import (
            set_conversation_mode_endpoint, ConversationModeBody
        )

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_b = "soloact-1-1111-2222-3333-444455556666"
            _write_session_file( sessions_dir, os.getpid(), sid_b )

            mock_ws = AsyncMock()
            mock_ws.emit_to_user.return_value = True

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    ws_manager=mock_ws
                )

            # Exactly one broadcast — the activate
            assert mock_ws.emit_to_user.await_count == 1
            _u, _e, payload = mock_ws.emit_to_user.await_args.args
            assert payload == { "session_id": sid_b, "conversation_mode_active": True }

            body = json.loads( resp.body.decode() )
            assert body[ "displaced_sessions" ] == []

    @pytest.mark.asyncio
    async def test_activate_displaces_multiple_active_sessions( self ):
        """Three pre-active sessions → all three displaced, four total broadcasts (3 displaced + 1 activate)."""
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

            mock_ws = AsyncMock()
            mock_ws.emit_to_user.return_value = True

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    ws_manager=mock_ws
                )

            # All three pre-active bridges flipped off
            for p in paths:
                with open( p ) as f:
                    data = json.load( f )
                assert data[ "conversation_mode_active" ] is False

            # 3 displaced events + 1 activate event = 4 total
            assert mock_ws.emit_to_user.await_count == 4

            # Last call is the activate event for B
            last_payload = mock_ws.emit_to_user.await_args_list[-1].args[2]
            assert last_payload == { "session_id": sid_b, "conversation_mode_active": True }

            body = json.loads( resp.body.decode() )
            assert sorted( body[ "displaced_sessions" ] ) == sorted( sids )

    @pytest.mark.asyncio
    async def test_deactivate_does_not_scan_or_displace( self ):
        """active=false bypasses the lock + scan; only emits its own deactivate event."""
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

            mock_ws = AsyncMock()
            mock_ws.emit_to_user.return_value = True

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=False ),
                    authenticated_user_id="user@test.com",
                    ws_manager=mock_ws
                )

            # A is untouched — deactivate path skips the scan
            with open( path_a ) as f:
                data_a = json.load( f )
            assert data_a[ "conversation_mode_active" ] is True

            # Exactly one broadcast — B's deactivate event
            assert mock_ws.emit_to_user.await_count == 1
            _u, _e, payload = mock_ws.emit_to_user.await_args.args
            assert payload == { "session_id": sid_b, "conversation_mode_active": False }

            body = json.loads( resp.body.decode() )
            assert body[ "active" ] is False
            assert body[ "displaced_sessions" ] == []

    @pytest.mark.asyncio
    async def test_displace_broadcast_failure_does_not_block_activate( self ):
        """If displaced-event broadcast raises, the bridge writes still happen and B still activates."""
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

            # First emit (displaced event for A) raises; second (activate for B) succeeds
            mock_ws = AsyncMock()
            mock_ws.emit_to_user.side_effect = [ RuntimeError( "ws ded" ), True ]

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_b,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    ws_manager=mock_ws
                )

            # Both bridge writes succeeded despite WS failure
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

            mock_ws = AsyncMock()
            mock_ws.emit_to_user.return_value = True

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                resp = await set_conversation_mode_endpoint(
                    session_id=sid_a,
                    body=ConversationModeBody( active=True ),
                    authenticated_user_id="user@test.com",
                    ws_manager=mock_ws
                )

            # Only one broadcast — self's activate event. No spurious displaced event.
            assert mock_ws.emit_to_user.await_count == 1

            body = json.loads( resp.body.decode() )
            assert body[ "displaced_sessions" ] == []


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
