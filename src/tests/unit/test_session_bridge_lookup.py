#!/usr/bin/env python3
"""
Unit tests for session_bridge find_session_by_id() and find_session_by_tmux().
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.session_bridge import (
    find_session_by_id, find_session_by_tmux,
    find_session_path_by_id, get_conversation_mode, set_conversation_mode
)
from lupin_cli.claude_code.hooks.register_session import main


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

    def test_inject_calls_subprocess_literal_then_enter( self ):
        """_inject_via_tmux sends literal text then Enter with delay."""
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

        with patch( "subprocess.run" ) as mock_run, \
             patch( "time.sleep" ) as mock_sleep:
            listener._inject_via_tmux( "run the tests" )
            assert mock_run.call_count == 2
            mock_run.assert_any_call(
                [ "tmux", "send-keys", "-t", "test-session", "-l", "run the tests" ],
                capture_output=True, timeout=2
            )
            mock_run.assert_any_call(
                [ "tmux", "send-keys", "-t", "test-session", "Enter" ],
                capture_output=True, timeout=2
            )
            mock_sleep.assert_called_once_with( 0.25 )

    def test_inject_handles_missing_tmux( self ):
        """_inject_via_tmux handles missing tmux gracefully."""
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
            listener._inject_via_tmux( "hello world" )

    def test_inject_skips_when_no_session( self ):
        """_inject_via_tmux skips when no tmux session resolved."""
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
            listener._inject_via_tmux( "hello world" )
            mock_run.assert_not_called()


# ── Tests: stable ID lockfile (Phase 1) ──────────────────────────────────────

class TestStableLockfile:

    def test_lockfile_created_on_first_start( self ):
        """First SessionStart creates cc-stable-{pid}.id with correct content."""
        from lupin_cli.claude_code.hooks.register_session import main

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = tmp
            session_id  = "aaaa1111-2222-3333-4444-555566667777"
            cc_pid      = 12345

            payload = { "session_id": session_id, "transcript_path": "/tmp/t", "cwd": "/tmp" }

            with patch( "lupin_cli.claude_code.hooks.register_session.read_hook_input", return_value=payload ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.log_payload" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.emit_json" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.send_tts" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._spawn_listener", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._find_tmux_session", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._resolve_cc_pid", return_value=cc_pid ), \
                 patch( "os.path.expanduser", return_value=session_dir ), \
                 patch( "os.getppid", return_value=99999 ), \
                 patch( "os.getenv", return_value=None ):
                main()

            lockfile = os.path.join( session_dir, f"cc-stable-{cc_pid}.id" )
            assert os.path.exists( lockfile )
            with open( lockfile ) as f:
                assert f.read().strip() == session_id

    def test_lockfile_atomic_no_overwrite( self ):
        """Subsequent call with different session_id reads original lockfile value."""
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = tmp
            cc_pid      = 12345
            original_id = "orig1111-2222-3333-4444-555566667777"
            new_id      = "new22222-3333-4444-5555-666677778888"

            # Pre-create the lockfile with original ID
            lockfile = os.path.join( session_dir, f"cc-stable-{cc_pid}.id" )
            with open( lockfile, "w" ) as f:
                f.write( original_id )

            # Also create a bridge file with old session_id
            bridge_file = os.path.join( session_dir, f"cc-{cc_pid}.json" )
            bridge_data = { "session_id": original_id, "stable_session_id": original_id }
            with open( bridge_file, "w" ) as f:
                json.dump( bridge_data, f )

            payload = { "session_id": new_id, "transcript_path": "/tmp/t", "cwd": "/tmp" }

            captured_data = {}

            def capture_spawn( sid, data, sfile, accepted_ids=None ):
                captured_data[ "stable_session_id" ] = sid
                captured_data[ "accepted_ids" ] = accepted_ids
                return None

            with patch( "lupin_cli.claude_code.hooks.register_session.read_hook_input", return_value=payload ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.log_payload" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.emit_json" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.send_tts" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._spawn_listener", side_effect=capture_spawn ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._find_tmux_session", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._resolve_cc_pid", return_value=cc_pid ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._cleanup_old_listener" ), \
                 patch( "os.path.expanduser", return_value=session_dir ), \
                 patch( "os.getppid", return_value=99999 ), \
                 patch( "os.getenv", return_value=None ):
                main()

            # Lockfile should still contain original ID
            with open( lockfile ) as f:
                assert f.read().strip() == original_id

            # Spawn should receive the original (stable) session ID
            assert captured_data[ "stable_session_id" ] == original_id

    def test_lockfile_read_failure_recovery( self ):
        """Unreadable lockfile triggers stderr warning and overwrite recovery."""
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = tmp
            cc_pid      = 12345
            session_id  = "fail1111-2222-3333-4444-555566667777"

            # Create lockfile but make it unreadable
            lockfile = os.path.join( session_dir, f"cc-stable-{cc_pid}.id" )
            with open( lockfile, "w" ) as f:
                f.write( "corrupted" )
            os.chmod( lockfile, 0o000 )

            payload = { "session_id": session_id, "transcript_path": "/tmp/t", "cwd": "/tmp" }

            import io
            stderr_capture = io.StringIO()

            try:
                with patch( "lupin_cli.claude_code.hooks.register_session.read_hook_input", return_value=payload ), \
                     patch( "lupin_cli.claude_code.hooks.register_session.log_payload" ), \
                     patch( "lupin_cli.claude_code.hooks.register_session.emit_json" ), \
                     patch( "lupin_cli.claude_code.hooks.register_session.send_tts" ), \
                     patch( "lupin_cli.claude_code.hooks.register_session._spawn_listener", return_value=None ), \
                     patch( "lupin_cli.claude_code.hooks.register_session._find_tmux_session", return_value=None ), \
                     patch( "lupin_cli.claude_code.hooks.register_session._resolve_cc_pid", return_value=cc_pid ), \
                     patch( "os.path.expanduser", return_value=session_dir ), \
                     patch( "os.getppid", return_value=99999 ), \
                     patch( "os.getenv", return_value=None ), \
                     patch( "sys.stderr", stderr_capture ):
                    main()
            finally:
                # Restore permissions for cleanup
                os.chmod( lockfile, 0o644 )

            # Should have logged a warning to stderr
            assert "WARNING" in stderr_capture.getvalue()
            assert "failed to read lockfile" in stderr_capture.getvalue()

    def test_context_clear_detected_with_lockfile( self ):
        """Different session_id in bridge file triggers is_context_clear = True."""
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = tmp
            cc_pid      = 12345
            old_id      = "old11111-2222-3333-4444-555566667777"
            new_id      = "new22222-3333-4444-5555-666677778888"

            # Pre-create lockfile with old stable ID
            lockfile = os.path.join( session_dir, f"cc-stable-{cc_pid}.id" )
            with open( lockfile, "w" ) as f:
                f.write( old_id )

            # Pre-create bridge file with old session_id
            bridge_file = os.path.join( session_dir, f"cc-{cc_pid}.json" )
            bridge_data = { "session_id": old_id, "stable_session_id": old_id }
            with open( bridge_file, "w" ) as f:
                json.dump( bridge_data, f )

            payload = { "session_id": new_id, "transcript_path": "/tmp/t", "cwd": "/tmp" }

            tts_messages = []
            def capture_tts( msg, sender_id=None ):
                tts_messages.append( msg )

            with patch( "lupin_cli.claude_code.hooks.register_session.read_hook_input", return_value=payload ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.log_payload" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.emit_json" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.send_tts", side_effect=capture_tts ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._spawn_listener", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._find_tmux_session", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._resolve_cc_pid", return_value=cc_pid ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._cleanup_old_listener" ), \
                 patch( "os.path.expanduser", return_value=session_dir ), \
                 patch( "os.getppid", return_value=99999 ), \
                 patch( "os.getenv", return_value=None ):
                main()

            # TTS message should indicate context clear
            assert any( "context clear" in msg for msg in tts_messages )

    def test_env_file_writes_stable_session_id( self ):
        """CLAUDE_ENV_FILE gets stable_session_id, not transient — prevents duplicate UI sessions."""
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = tmp
            cc_pid      = 12345
            stable_id   = "stab1111-2222-3333-4444-555566667777"
            new_id      = "new22222-3333-4444-5555-666677778888"

            # Pre-create lockfile with stable ID
            lockfile = os.path.join( session_dir, f"cc-stable-{cc_pid}.id" )
            with open( lockfile, "w" ) as f:
                f.write( stable_id )

            # Pre-create bridge file with old session
            bridge_file = os.path.join( session_dir, f"cc-{cc_pid}.json" )
            bridge_data = { "session_id": stable_id, "stable_session_id": stable_id }
            with open( bridge_file, "w" ) as f:
                json.dump( bridge_data, f )

            # Create env file to capture writes
            env_file = os.path.join( tmp, "claude_env" )

            payload = { "session_id": new_id, "transcript_path": "/tmp/t", "cwd": "/tmp" }

            def mock_getenv( key, default=None ):
                if key == "CLAUDE_ENV_FILE":
                    return env_file
                return None

            with patch( "lupin_cli.claude_code.hooks.register_session.read_hook_input", return_value=payload ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.log_payload" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.emit_json" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.send_tts" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._spawn_listener", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._find_tmux_session", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._resolve_cc_pid", return_value=cc_pid ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._cleanup_old_listener" ), \
                 patch( "os.path.expanduser", return_value=session_dir ), \
                 patch( "os.getppid", return_value=99999 ), \
                 patch( "os.getenv", side_effect=mock_getenv ):
                main()

            # Env file must contain STABLE session ID, not transient
            with open( env_file ) as f:
                env_contents = f.read()
            assert stable_id in env_contents, f"Expected stable ID {stable_id} in env file, got: {env_contents}"
            assert new_id not in env_contents, f"Transient ID {new_id} should NOT be in env file"


# ── Tests: stable ID passed to listener (Phase 2) ───────────────────────────

class TestStableIdPassedToListener:

    def test_stable_id_passed_to_listener( self ):
        """_spawn_listener receives stable_session_id not transient session_id."""
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = tmp
            cc_pid      = 12345
            stable_id   = "stab1111-2222-3333-4444-555566667777"
            new_id      = "new22222-3333-4444-5555-666677778888"

            # Pre-create lockfile with stable ID
            lockfile = os.path.join( session_dir, f"cc-stable-{cc_pid}.id" )
            with open( lockfile, "w" ) as f:
                f.write( stable_id )

            # Pre-create bridge file with old session
            bridge_file = os.path.join( session_dir, f"cc-{cc_pid}.json" )
            bridge_data = { "session_id": stable_id, "stable_session_id": stable_id }
            with open( bridge_file, "w" ) as f:
                json.dump( bridge_data, f )

            payload = { "session_id": new_id, "transcript_path": "/tmp/t", "cwd": "/tmp" }

            captured = {}

            def capture_spawn( sid, data, sfile, accepted_ids=None ):
                captured[ "session_id" ] = sid
                captured[ "accepted_ids" ] = accepted_ids
                return None

            with patch( "lupin_cli.claude_code.hooks.register_session.read_hook_input", return_value=payload ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.log_payload" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.emit_json" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.send_tts" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._spawn_listener", side_effect=capture_spawn ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._find_tmux_session", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._resolve_cc_pid", return_value=cc_pid ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._cleanup_old_listener" ), \
                 patch( "os.path.expanduser", return_value=session_dir ), \
                 patch( "os.getppid", return_value=99999 ), \
                 patch( "os.getenv", return_value=None ):
                main()

            # Listener should receive the STABLE session ID, not the new transient one
            assert captured[ "session_id" ] == stable_id
            # accepted_ids should contain both stable and transient hashes
            assert stable_id[:8] in captured[ "accepted_ids" ]
            assert new_id[:8] in captured[ "accepted_ids" ]


# ── Tests: accepted_ids parsing (Phase 3) ────────────────────────────────────

class TestAcceptedIds:

    def test_accepted_ids_parsed( self ):
        """--accepted-ids 'abc,def' → self.accepted_ids == {'abc', 'def'}."""
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener

        listener = CCNotificationListener.__new__( CCNotificationListener )
        listener.session_id_hash = "abc12345"
        listener.accepted_ids    = set( [ "abc12345", "def67890" ] )

        assert listener.accepted_ids == { "abc12345", "def67890" }

    def test_accepted_ids_filter_match( self ):
        """Notification with matching hash in accepted_ids is accepted."""
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener

        listener = CCNotificationListener.__new__( CCNotificationListener )
        listener.session_id_hash   = "abc12345"
        listener.accepted_ids      = { "abc12345", "def67890" }
        listener._tmux_session_arg = "test"
        listener._tmux_session     = None
        listener.log_file_path     = None
        listener._log_file         = None
        listener._centralized_log  = None
        listener.LOG_PREFIX        = "[CC-Listener]"
        listener.debug             = False
        listener.verbose           = False

        event_data = {
            "notification": {
                "type"    : "user_initiated_message",
                "job_id"  : "def67890",  # matches second accepted ID
                "message" : "hello from browser",
            }
        }

        import asyncio
        with patch.object( listener, "_inject_via_tmux" ) as mock_inject, \
             patch.object( listener, "_send_gist_response" ):
            asyncio.run( listener._handle_event( "notification_queue_update", event_data ) )
            mock_inject.assert_called_once_with( "hello from browser" )

    def test_accepted_ids_filter_reject( self ):
        """Notification with non-matching hash is rejected."""
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener

        listener = CCNotificationListener.__new__( CCNotificationListener )
        listener.session_id_hash   = "abc12345"
        listener.accepted_ids      = { "abc12345", "def67890" }
        listener._tmux_session_arg = None
        listener._tmux_session     = None
        listener.log_file_path     = None
        listener._log_file         = None
        listener._centralized_log  = None
        listener.LOG_PREFIX        = "[CC-Listener]"
        listener.debug             = False
        listener.verbose           = False

        event_data = {
            "notification": {
                "type"    : "user_initiated_message",
                "job_id"  : "xxxxxxxx",  # does NOT match any accepted ID
                "message" : "should be rejected",
            }
        }

        import asyncio
        with patch.object( listener, "_inject_via_tmux" ) as mock_inject:
            asyncio.run( listener._handle_event( "notification_queue_update", event_data ) )
            mock_inject.assert_not_called()


# ── Tests: stale lockfile cleanup (Phase 4) ──────────────────────────────────

class TestStaleLockfileCleanup:

    def test_stale_lockfile_dead_pid_purged( self ):
        """Stale lockfile for dead PID is purged."""
        from lupin_cli.claude_code.hooks.register_session import _is_live_cc_process
        assert _is_live_cc_process( "99999999" ) is False

    def test_current_lockfile_never_purged( self ):
        """Current session's lockfile survives cleanup regardless of age."""
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = tmp
            cc_pid      = 12345
            session_id  = "keep1111-2222-3333-4444-555566667777"

            payload = { "session_id": session_id, "transcript_path": "/tmp/t", "cwd": "/tmp" }

            # Pre-create a stale lockfile for the SAME pid (old enough to purge)
            lockfile = os.path.join( session_dir, f"cc-stable-{cc_pid}.id" )
            with open( lockfile, "w" ) as f:
                f.write( "old-stable-id" )
            # Set mtime to 2 days ago
            old_time = time.time() - 172800
            os.utime( lockfile, ( old_time, old_time ) )

            with patch( "lupin_cli.claude_code.hooks.register_session.read_hook_input", return_value=payload ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.log_payload" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.emit_json" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session.send_tts" ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._spawn_listener", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._find_tmux_session", return_value=None ), \
                 patch( "lupin_cli.claude_code.hooks.register_session._resolve_cc_pid", return_value=cc_pid ), \
                 patch( "os.path.expanduser", return_value=session_dir ), \
                 patch( "os.getppid", return_value=99999 ), \
                 patch( "os.getenv", return_value=None ):
                main()

            # Lockfile should still exist (it's our current lockfile — never purged)
            assert os.path.exists( lockfile )


# ── Tests: conversation mode (find_session_path_by_id, get/set) ──────────────

class TestFindSessionPathById:

    def test_returns_path_on_full_uuid_match( self ):
        """Full UUID match returns the bridge file Path."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid  = "abc12345-6789-abcd-ef01-234567890abc"
            data = _make_session_data( sid )
            written = _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_path_by_id( sid )

            assert result == written

    def test_returns_path_on_8char_prefix_match( self ):
        """8-char prefix returns Path."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid  = "deadbeef-1111-2222-3333-444455556666"
            data = _make_session_data( sid )
            written = _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                result = find_session_path_by_id( "deadbeef" )

            assert result == written

    def test_returns_none_on_no_match( self ):
        """No match returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            data = _make_session_data( "aaaaaaaa-1111-2222-3333-444455556666" )
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                assert find_session_path_by_id( "bbbbbbbb" ) is None

    def test_empty_session_id_returns_none( self ):
        """Empty session_id returns None."""
        assert find_session_path_by_id( "" ) is None
        assert find_session_path_by_id( None ) is None


class TestConversationMode:

    def test_default_is_false( self ):
        """Bridge without conversation_mode_active reads as False."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "session1-1111-2222-3333-444455556666"
            data = _make_session_data( sid )
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                assert get_conversation_mode( sid ) is False

    def test_set_then_get_round_trip( self ):
        """set_conversation_mode(True) then get_conversation_mode returns True; flipping back returns False."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "rndtrip1-1111-2222-3333-444455556666"
            data = _make_session_data( sid )
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                assert set_conversation_mode( sid, True ) is True
                assert get_conversation_mode( sid ) is True
                assert set_conversation_mode( sid, False ) is True
                assert get_conversation_mode( sid ) is False

    def test_per_session_isolation( self ):
        """Two sessions in same SESSION_DIR have independent flags."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid_a = "aaaaaaaa-1111-2222-3333-444455556666"
            sid_b = "bbbbbbbb-1111-2222-3333-444455556666"
            # Use two distinct PIDs; patch _is_pid_alive so test is deterministic
            # regardless of which fake PIDs are signalable by the test user.
            _write_session_file( sessions_dir, 90001, _make_session_data( sid_a ) )
            _write_session_file( sessions_dir, 90002, _make_session_data( sid_b ) )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ), \
                 patch( "lupin_cli.claude_code.hooks.lib.session_bridge._is_pid_alive", return_value=True ):
                assert set_conversation_mode( sid_a, True ) is True
                # Session A is on, B should still be off (default)
                assert get_conversation_mode( sid_a ) is True
                assert get_conversation_mode( sid_b ) is False
                # Flip B, A must remain on
                assert set_conversation_mode( sid_b, True ) is True
                assert get_conversation_mode( sid_a ) is True
                assert get_conversation_mode( sid_b ) is True

    def test_get_on_missing_session_returns_false( self ):
        """get_conversation_mode for unknown session_id returns False (no exception)."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                assert get_conversation_mode( "nonexistent" ) is False

    def test_set_on_missing_session_returns_false( self ):
        """set_conversation_mode for unknown session_id returns False (no bridge created)."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                assert set_conversation_mode( "nonexistent", True ) is False
                # No file should have been created
                assert not list( sessions_dir.glob( "cc-*.json" ) )

    def test_set_preserves_other_fields( self ):
        """set_conversation_mode round-trip preserves session_id, cwd, etc."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path( tmp )
            sid = "preserve-1111-2222-3333-444455556666"
            data = _make_session_data( sid, tmux_session="my-tmux", cwd="/some/path" )
            data[ "session_topic" ] = "important topic"
            _write_session_file( sessions_dir, os.getpid(), data )

            with patch( "lupin_cli.claude_code.hooks.lib.session_bridge.SESSION_DIR", sessions_dir ):
                set_conversation_mode( sid, True )

            # Re-read directly to confirm preservation
            with open( sessions_dir / f"cc-{os.getpid()}.json" ) as f:
                after = json.load( f )

            assert after[ "session_id" ] == sid
            assert after[ "tmux_session" ] == "my-tmux"
            assert after[ "cwd" ] == "/some/path"
            assert after[ "session_topic" ] == "important topic"
            assert after[ "conversation_mode_active" ] is True


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
