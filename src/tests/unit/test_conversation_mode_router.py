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


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
