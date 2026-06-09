#!/usr/bin/env python3
"""
Unit tests for cosa_voice_mcp conversation mode tools.

Tests:
    - _flip_speakerphone() writes the bridge file
    - enable_speakerphone / disable_speakerphone round-trip
    - get_session_info() reflects speakerphone_on

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
        "cc_pid"            : os.getpid(),
    }
    with open( path, "w" ) as f:
        json.dump( data, f )
    return path


# ── Tests: _flip_speakerphone helper ────────────────────────────────────

class TestFlipConversationMode:

    def test_flip_to_true_writes_bridge( self ):
        """_flip_speakerphone(True) writes speakerphone_on=True to the bridge."""
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
                result = cosa_voice_mcp._flip_speakerphone( True )

            assert result[ "status" ] == "ok"
            assert result[ "speakerphone_on" ] is True
            # Verify the write actually landed
            with open( bridge_path ) as f:
                data = json.load( f )
            assert data[ "speakerphone_on" ] is True

    def test_flip_to_false_writes_bridge( self ):
        """_flip_speakerphone(False) writes speakerphone_on=False."""
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "bbbbbbbb-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )
            # Pre-set to True
            with open( bridge_path ) as f:
                data = json.load( f )
            data[ "speakerphone_on" ] = True
            with open( bridge_path, "w" ) as f:
                json.dump( data, f )

            fake_meta = { "session_id": sid, "stable_session_id": sid, "_bridge_path": str( bridge_path ) }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = cosa_voice_mcp._flip_speakerphone( False )

            assert result[ "status" ] == "ok"
            assert result[ "speakerphone_on" ] is False
            with open( bridge_path ) as f:
                data = json.load( f )
            assert data[ "speakerphone_on" ] is False

    def test_flip_returns_error_when_bridge_missing( self ):
        """_flip_speakerphone returns status=error when no bridge can be located."""
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # No bridge file written
            fake_meta = { "session_id": "no-such-session", "stable_session_id": "no-such-session" }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = cosa_voice_mcp._flip_speakerphone( True )

            assert result[ "status" ] == "error"
            assert "session_id" in result
            # After the 2026-04-28 refactor the helper tries the HTTP endpoint
            # first; on 404+fallback failure the reason carries the chained
            # diagnostic. Accept any of the failure markers.
            failure_markers = (
                "Bridge file not found",
                "write failed",
                "HTTP path failed",
                "fallback failed",
            )
            assert any( m in result[ "reason" ] for m in failure_markers ), result[ "reason" ]


# ── Tests: enter/exit @mcp.tool wrappers ─────────────────────────────────────

class TestEnterExitConversationMode:

    def test_enter_then_exit_round_trip( self ):
        """enable_speakerphone flips True; disable_speakerphone flips False."""
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "round123-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )
            fake_meta = { "session_id": sid, "stable_session_id": sid, "_bridge_path": str( bridge_path ) }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):

                # FastMCP tool wrappers expose .fn for the underlying callable
                enter_fn = cosa_voice_mcp.enable_speakerphone.fn \
                    if hasattr( cosa_voice_mcp.enable_speakerphone, "fn" ) \
                    else cosa_voice_mcp.enable_speakerphone
                exit_fn  = cosa_voice_mcp.disable_speakerphone.fn \
                    if hasattr( cosa_voice_mcp.disable_speakerphone, "fn" ) \
                    else cosa_voice_mcp.disable_speakerphone

                r1 = enter_fn()
                assert r1[ "status" ] == "ok"
                assert r1[ "speakerphone_on" ] is True

                r2 = exit_fn()
                assert r2[ "status" ] == "ok"
                assert r2[ "speakerphone_on" ] is False

                # Verify final on-disk state
                with open( bridge_path ) as f:
                    data = json.load( f )
                assert data[ "speakerphone_on" ] is False


# ── Tests: get_session_info() reflects flag ──────────────────────────────────

class TestGetSessionInfoConversationMode:

    def test_get_session_info_default_false( self ):
        """When speakerphone_on is missing or False in bridge, info reports False."""
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
                "speakerphone_on" : False,
            }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@test.deepily.ai#info0001" ):
                gsi_fn = cosa_voice_mcp.get_session_info.fn \
                    if hasattr( cosa_voice_mcp.get_session_info, "fn" ) \
                    else cosa_voice_mcp.get_session_info
                info = gsi_fn()

            assert info[ "speakerphone_on" ] is False

    def test_get_session_info_reflects_true( self ):
        """When speakerphone_on=True in bridge metadata, info reports True."""
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
                "speakerphone_on" : True,
            }

            with patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@test.deepily.ai#info0002" ):
                gsi_fn = cosa_voice_mcp.get_session_info.fn \
                    if hasattr( cosa_voice_mcp.get_session_info, "fn" ) \
                    else cosa_voice_mcp.get_session_info
                info = gsi_fn()

            assert info[ "speakerphone_on" ] is True


# ── Tests: HTTP path + fallback (2026-04-28 refactor) ────────────────────────


class TestFlipConversationModeHttpPath:
    """
    The refactored _flip_speakerphone tries the canonical HTTP endpoint
    POST /api/cosa-voice/speakerphone/{sid} first, falling back to a
    direct bridge-file write on connection failures. These tests exercise:
      - HTTP success path → returned dict carries displaced_sessions + ui_sync=broadcast
      - HTTP unreachable (ConnectionError) → fallback to bridge write
      - Login auth failure → fallback to bridge write
      - Endpoint 5xx → fallback to bridge write
    """

    def _make_response( self, status_code, body=None ):
        from unittest.mock import MagicMock
        m = MagicMock()
        m.status_code = status_code
        if body is not None:
            m.json = MagicMock( return_value=body )
            m.text = json.dumps( body )
        else:
            m.text = ""
        return m

    def test_http_success_returns_broadcast_marker_and_displaced_sessions( self ):
        """When login + toggle endpoint both 200, returned dict reports broadcast + displaced list."""
        from unittest.mock import MagicMock, patch as mock_patch
        from lupin_mcp import cosa_voice_mcp

        sid = "httpok01-1111-2222-3333-444455556666"
        fake_meta = { "session_id": sid, "stable_session_id": sid }

        login_resp = self._make_response( 200, { "tokens": { "access_token": "fake-jwt" } } )
        toggle_resp = self._make_response( 200, {
            "session_id"          : sid,
            "active"              : True,
            "broadcast_delivered" : True,
            "displaced_sessions"  : [ "other-sid-1234" ]
        } )

        # The helper imports get_hook_credentials inside the function via
        # `from lupin_cli.claude_code.hooks.lib.hook_credentials import ...`
        # so we patch the canonical path.
        with mock_patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
             mock_patch( "lupin_mcp.cosa_voice_mcp.requests.post",
                         side_effect=[ login_resp, toggle_resp ] ) as mock_post, \
             mock_patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials",
                         return_value=( "test@deepily.ai", "secret" ) ):
            result = cosa_voice_mcp._flip_speakerphone( True )

        assert result[ "status" ] == "ok"
        assert result[ "session_id" ] == sid
        assert result[ "speakerphone_on" ] is True
        assert result[ "displaced_sessions" ] == [ "other-sid-1234" ]
        assert result[ "ui_sync" ] == "broadcast"

        # Two POSTs: /auth/login and /api/cosa-voice/speakerphone/{sid}
        assert mock_post.call_count == 2
        login_call = mock_post.call_args_list[0]
        toggle_call = mock_post.call_args_list[1]
        assert login_call.args[0].endswith( "/auth/login" )
        assert toggle_call.args[0].endswith( f"/api/cosa-voice/speakerphone/{sid}" )
        # Toggle call carries the bearer token
        assert toggle_call.kwargs[ "headers" ][ "Authorization" ] == "Bearer fake-jwt"

    def test_http_connection_error_falls_back_to_bridge_write( self ):
        """ConnectionError on login → fallback path writes the bridge directly."""
        from unittest.mock import patch as mock_patch
        from lupin_mcp import cosa_voice_mcp
        import requests

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "fallback-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )
            fake_meta = { "session_id": sid, "stable_session_id": sid }

            with mock_patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 mock_patch( "lupin_mcp.cosa_voice_mcp.requests.post",
                             side_effect=requests.ConnectionError( "server down" ) ), \
                 mock_patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials",
                             return_value=( "test@deepily.ai", "secret" ) ), \
                 mock_patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = cosa_voice_mcp._flip_speakerphone( True )

            assert result[ "status" ] == "ok"
            assert result[ "speakerphone_on" ] is True
            assert "deferred" in result[ "ui_sync" ]
            # Bridge actually got written (fallback path)
            with open( bridge_path ) as f:
                data = json.load( f )
            assert data[ "speakerphone_on" ] is True

    def test_http_login_401_falls_back_to_bridge_write( self ):
        """Auth failure on login → fallback path."""
        from unittest.mock import patch as mock_patch
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "auth401-x-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )
            fake_meta = { "session_id": sid, "stable_session_id": sid }

            login_401 = self._make_response( 401, { "detail": "bad credentials" } )

            with mock_patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 mock_patch( "lupin_mcp.cosa_voice_mcp.requests.post", return_value=login_401 ), \
                 mock_patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials",
                             return_value=( "test@deepily.ai", "wrong-password" ) ), \
                 mock_patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = cosa_voice_mcp._flip_speakerphone( True )

            assert result[ "status" ] == "ok"
            assert result[ "speakerphone_on" ] is True
            assert "deferred" in result[ "ui_sync" ]
            with open( bridge_path ) as f:
                data = json.load( f )
            assert data[ "speakerphone_on" ] is True

    def test_endpoint_500_falls_back_to_bridge_write( self ):
        """5xx from toggle endpoint → fallback path."""
        from unittest.mock import patch as mock_patch
        from lupin_mcp import cosa_voice_mcp

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "ep500-vx-1111-2222-3333-444455556666"
            bridge_path = _write_session_file( sessions_dir, os.getpid(), sid )
            fake_meta = { "session_id": sid, "stable_session_id": sid }

            login_ok    = self._make_response( 200, { "tokens": { "access_token": "fake-jwt" } } )
            toggle_500  = self._make_response( 500, { "detail": "internal" } )

            with mock_patch( "lupin_mcp.cosa_voice_mcp._get_cc_metadata", return_value=fake_meta ), \
                 mock_patch( "lupin_mcp.cosa_voice_mcp.requests.post",
                             side_effect=[ login_ok, toggle_500 ] ), \
                 mock_patch( "lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials",
                             return_value=( "test@deepily.ai", "secret" ) ), \
                 mock_patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = cosa_voice_mcp._flip_speakerphone( True )

            assert result[ "status" ] == "ok"
            assert result[ "speakerphone_on" ] is True
            assert "deferred" in result[ "ui_sync" ]
            with open( bridge_path ) as f:
                data = json.load( f )
            assert data[ "speakerphone_on" ] is True


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
