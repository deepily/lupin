#!/usr/bin/env python3
"""
Unit tests for session_bridge find_session_by_id() and find_session_by_tmux().
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.session_bridge import (
    find_session_by_id, find_session_by_tmux
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_session_file( sessions_dir, pid, data ):
    """Write a session bridge file cc-{pid}.json."""
    path = sessions_dir / f"cc-{pid}.json"
    with open( path, "w" ) as f:
        json.dump( data, f )
    return path


def _make_session_data( session_id, tmux_session=None, cwd="/tmp" ):
    """Build a session data dict."""
    data = {
        "session_id"        : session_id,
        "stable_session_id" : session_id,
        "cwd"               : cwd,
        "ppid"              : os.getpid(),  # Use current PID so liveness check passes
        "hook_ppid"         : 1,
    }
    if tmux_session is not None:
        data[ "tmux_session" ] = tmux_session
    return data


# ── Tests: find_session_by_id ────────────────────────────────────────────────

class TestFindSessionById:

    def test_full_uuid_match( self ):
        """Full UUID match returns session data."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid  = "abc12345-6789-abcd-ef01-234567890abc"
            data = _make_session_data( sid, tmux_session="lupin" )
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_by_id( sid )

            assert result is not None
            assert result[ "session_id" ] == sid

    def test_8char_prefix_match( self ):
        """8-char prefix match returns session data."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid  = "deadbeef-1234-5678-9abc-def012345678"
            data = _make_session_data( sid )
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_by_id( "deadbeef" )

            assert result is not None
            assert result[ "session_id" ] == sid

    def test_no_match_returns_none( self ):
        """No matching session -> None."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            data = _make_session_data( "abc12345-fake-uuid" )
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_by_id( "ffffffff" )

            assert result is None

    def test_empty_session_id_returns_none( self ):
        """Empty session_id -> None."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                assert find_session_by_id( "" ) is None
                assert find_session_by_id( None ) is None

    def test_dead_pid_skipped( self ):
        """Session files from dead PIDs are skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid  = "abc12345-fake-uuid"
            data = _make_session_data( sid )
            # Use a PID that doesn't exist
            _write_session_file( sessions_dir, 99999999, data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_by_id( "abc12345" )

            assert result is None

    def test_skips_buffer_and_listener_files( self ):
        """Buffer and listener files are not considered."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            # Write a buffer file (should be skipped)
            buf = sessions_dir / "cc-buffer-abc12345.jsonl"
            buf.write_text( '{"message": "test"}\n' )
            # Write a listener log (should be skipped)
            log = sessions_dir / "cc-listener-abc12345.log"
            log.write_text( "log line\n" )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_by_id( "abc12345" )

            assert result is None


# ── Tests: find_session_by_tmux ──────────────────────────────────────────────

class TestFindSessionByTmux:

    def test_exact_match( self ):
        """Exact tmux session name match."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            data = _make_session_data( "abc12345-fake-uuid", tmux_session="lupin" )
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_by_tmux( "lupin" )

            assert result is not None
            assert result[ "tmux_session" ] == "lupin"

    def test_no_match_returns_none( self ):
        """No matching tmux session -> None."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            data = _make_session_data( "abc12345-fake-uuid", tmux_session="other-project" )
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_by_tmux( "lupin" )

            assert result is None

    def test_empty_tmux_returns_none( self ):
        """Empty tmux_session -> None."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                assert find_session_by_tmux( "" ) is None
                assert find_session_by_tmux( None ) is None

    def test_dead_pid_skipped( self ):
        """Session files from dead PIDs are skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            data = _make_session_data( "abc12345-fake-uuid", tmux_session="lupin" )
            _write_session_file( sessions_dir, 99999999, data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_by_tmux( "lupin" )

            assert result is None

    def test_session_without_tmux_field_skipped( self ):
        """Sessions without tmux_session field are skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            data = _make_session_data( "abc12345-fake-uuid" )  # No tmux_session
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_by_tmux( "lupin" )

            assert result is None


# ── Tests: tmux discovery in register_session ────────────────────────────────

class TestFindTmuxSession:

    def test_returns_none_when_tmux_not_installed( self ):
        """_find_tmux_session returns None when tmux binary not found."""
        from lupin_cli.claude_code.hooks.register_session import _find_tmux_session

        with patch( "subprocess.run", side_effect=FileNotFoundError ):
            result = _find_tmux_session( os.getpid() )
            assert result is None

    def test_handles_subprocess_timeout( self ):
        """_find_tmux_session returns None on timeout."""
        import subprocess as sp
        from lupin_cli.claude_code.hooks.register_session import _find_tmux_session

        with patch( "subprocess.run", side_effect=sp.TimeoutExpired( "tmux", 2 ) ):
            result = _find_tmux_session( os.getpid() )
            assert result is None

    def test_matches_pane_pid( self ):
        """_find_tmux_session matches direct pane PID."""
        from lupin_cli.claude_code.hooks.register_session import _find_tmux_session

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = f"my-session {os.getpid()}\nother-session 99999\n"

        with patch( "subprocess.run", return_value=mock_result ):
            result = _find_tmux_session( os.getpid() )
            assert result == "my-session"

    def test_no_match_returns_none( self ):
        """_find_tmux_session returns None when no PID matches."""
        from lupin_cli.claude_code.hooks.register_session import _find_tmux_session

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "session1 11111\nsession2 22222\n"

        with patch( "subprocess.run", return_value=mock_result ):
            # Use a PID that won't match and whose /proc/{pid}/stat won't exist
            result = _find_tmux_session( 88888888 )
            assert result is None


# ── Tests: listener tmux trigger ─────────────────────────────────────────────

class TestListenerTmuxTrigger:

    def test_trigger_calls_subprocess( self ):
        """_trigger_tmux_enter calls tmux send-keys."""
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener

        listener = CCNotificationListener.__new__( CCNotificationListener )
        listener.session_id_hash   = "abc12345"
        listener._tmux_session_arg = "test-session"
        listener._tmux_session     = None
        listener.log_file_path     = None
        listener._log_file         = None
        listener._centralized_log  = None
        listener.LOG_PREFIX        = "[CC-Listener]"
        listener.verbose           = False

        with patch( "subprocess.run" ) as mock_run:
            listener._trigger_tmux_enter()
            mock_run.assert_called_once_with(
                [ "tmux", "send-keys", "-t", "test-session", "Enter" ],
                capture_output=True, timeout=2
            )

    def test_trigger_handles_missing_tmux( self ):
        """_trigger_tmux_enter handles missing tmux gracefully."""
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener

        listener = CCNotificationListener.__new__( CCNotificationListener )
        listener.session_id_hash   = "abc12345"
        listener._tmux_session_arg = None
        listener._tmux_session     = None
        listener.log_file_path     = None
        listener._log_file         = None
        listener._centralized_log  = None
        listener.LOG_PREFIX        = "[CC-Listener]"
        listener.verbose           = False

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id", return_value=None ):
            # Should not raise
            listener._trigger_tmux_enter()

    def test_trigger_skips_when_no_session( self ):
        """_trigger_tmux_enter skips when no tmux session resolved."""
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener

        listener = CCNotificationListener.__new__( CCNotificationListener )
        listener.session_id_hash   = "abc12345"
        listener._tmux_session_arg = None
        listener._tmux_session     = None
        listener.log_file_path     = None
        listener._log_file         = None
        listener._centralized_log  = None
        listener.LOG_PREFIX        = "[CC-Listener]"
        listener.verbose           = False

        with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id", return_value=None ), \
             patch( "subprocess.run" ) as mock_run:
            listener._trigger_tmux_enter()
            mock_run.assert_not_called()


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
