#!/usr/bin/env python3
"""
Unit tests for cosa_voice_mcp conversation mode tools.

Tests:
    - _flip_conversation_mode() writes the bridge file
    - enter_conversation_mode / exit_conversation_mode round-trip
    - get_session_info() reflects conversation_mode_active

Bridge state is mocked via _get_cc_metadata + a tmp SESSION_DIR so tests don't
mutate the real ~/.claude/sessions/cc-*.json files.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_session_file( sessions_dir, pid, session_id ):
    """Write a minimal bridge file at sessions_dir/cc-{pid}.json."""
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


# ── Tests: _flip_conversation_mode helper ────────────────────────────────────

class TestFlipConversationMode:

    def test_flip_to_true_writes_bridge( self ):
        """_flip_conversation_mode(True) writes conversation_mode_active=True to the bridge."""
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "aaaaaaaa-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )

            fake_meta = {
                "session_id"        : sid,
                "stable_session_id" : sid,
                "_bridge_path"      : str( bridge_path ),
            }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = cosa_voice_mcp._flip_conversation_mode( True )

            assert result[ "status" ] == "ok"
            assert result[ "conversation_mode_active" ] is True
            # Verify the write actually landed
            with open( bridge_path ) as f:
                data = json.load( f )
            assert data[ "conversation_mode_active" ] is True

    def test_flip_to_false_writes_bridge( self ):
        """_flip_conversation_mode(False) writes conversation_mode_active=False."""
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "bbbbbbbb-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )
            # Pre-set to True
            with open( bridge_path ) as f:
                data = json.load( f )
            data[ "conversation_mode_active" ] = True
            with open( bridge_path, "w" ) as f:
                json.dump( data, f )

            fake_meta = { "session_id": sid, "stable_session_id": sid, "_bridge_path": str( bridge_path ) }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = cosa_voice_mcp._flip_conversation_mode( False )

            assert result[ "status" ] == "ok"
            assert result[ "conversation_mode_active" ] is False
            with open( bridge_path ) as f:
                data = json.load( f )
            assert data[ "conversation_mode_active" ] is False

    def test_flip_returns_error_when_bridge_missing( self ):
        """_flip_conversation_mode returns status=error when no bridge can be located."""
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # No bridge file written
            fake_meta = { "session_id": "no-such-session", "stable_session_id": "no-such-session" }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = cosa_voice_mcp._flip_conversation_mode( True )

            assert result[ "status" ] == "error"
            assert "session_id" in result
            assert "Bridge file not found" in result[ "reason" ] or "write failed" in result[ "reason" ]


# ── Tests: enter/exit @mcp.tool wrappers ─────────────────────────────────────

class TestEnterExitConversationMode:

    def test_enter_then_exit_round_trip( self ):
        """enter_conversation_mode flips True; exit_conversation_mode flips False."""
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "round123-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )
            fake_meta = { "session_id": sid, "stable_session_id": sid, "_bridge_path": str( bridge_path ) }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):

                # FastMCP tool wrappers expose .fn for the underlying callable
                enter_fn = cosa_voice_mcp.enter_conversation_mode.fn \
                    if hasattr( cosa_voice_mcp.enter_conversation_mode, "fn" ) \
                    else cosa_voice_mcp.enter_conversation_mode
                exit_fn  = cosa_voice_mcp.exit_conversation_mode.fn \
                    if hasattr( cosa_voice_mcp.exit_conversation_mode, "fn" ) \
                    else cosa_voice_mcp.exit_conversation_mode

                r1 = enter_fn()
                assert r1[ "status" ] == "ok"
                assert r1[ "conversation_mode_active" ] is True

                r2 = exit_fn()
                assert r2[ "status" ] == "ok"
                assert r2[ "conversation_mode_active" ] is False

                # Verify final on-disk state
                with open( bridge_path ) as f:
                    data = json.load( f )
                assert data[ "conversation_mode_active" ] is False


# ── Tests: get_session_info() reflects flag ──────────────────────────────────

class TestGetSessionInfoConversationMode:

    def test_get_session_info_default_false( self ):
        """When conversation_mode_active is missing or False in bridge, info reports False."""
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "info0001-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )
            fake_meta = {
                "session_id"               : sid,
                "stable_session_id"        : sid,
                "_bridge_path"             : str( bridge_path ),
                "source"                   : "session_file",
                "conversation_mode_active" : False,
            }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@test.deepily.ai#info0001" ):
                gsi_fn = cosa_voice_mcp.get_session_info.fn \
                    if hasattr( cosa_voice_mcp.get_session_info, "fn" ) \
                    else cosa_voice_mcp.get_session_info
                info = gsi_fn()

            assert info[ "conversation_mode_active" ] is False

    def test_get_session_info_reflects_true( self ):
        """When conversation_mode_active=True in bridge metadata, info reports True."""
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "info0002-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )
            fake_meta = {
                "session_id"               : sid,
                "stable_session_id"        : sid,
                "_bridge_path"             : str( bridge_path ),
                "source"                   : "session_file",
                "conversation_mode_active" : True,
            }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@test.deepily.ai#info0002" ):
                gsi_fn = cosa_voice_mcp.get_session_info.fn \
                    if hasattr( cosa_voice_mcp.get_session_info, "fn" ) \
                    else cosa_voice_mcp.get_session_info
                info = gsi_fn()

            assert info[ "conversation_mode_active" ] is True


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
