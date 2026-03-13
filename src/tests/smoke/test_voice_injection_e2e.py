#!/usr/bin/env python3
"""
Smoke test — end-to-end voice injection via UserPromptSubmit hook.

Tests the complete flow: write JSONL buffer -> pipe mock payload through
hook -> verify additionalContext output -> verify buffer consumed.
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


def test_e2e_voice_injection():
    """Write buffer -> run hook -> verify context injection + buffer consumed."""
    from lupin_cli.claude_code.hooks import user_prompt_submit

    session_id = "e2etest1-fake-uuid-1234-567890abcdef"
    hash_part  = session_id[:8]

    with tempfile.TemporaryDirectory() as tmp_dir:
        sessions_dir = Path( tmp_dir ) / ".claude" / "sessions"
        sessions_dir.mkdir( parents=True, exist_ok=True )

        # Write JSONL buffer
        buffer_path = sessions_dir / f"cc-buffer-{hash_part}.jsonl"
        entries = [
            {
                "message"     : "show me git status",
                "priority"    : "normal",
                "job_id"      : hash_part,
                "sender_id"   : "user@example.com",
                "timestamp"   : "2026-03-06T10:00:00+00:00",
                "buffered_at" : "2026-03-06T10:00:00+00:00",
            },
            {
                "message"     : "also run the unit tests",
                "priority"    : "normal",
                "job_id"      : hash_part,
                "sender_id"   : "user@example.com",
                "timestamp"   : "2026-03-06T10:00:05+00:00",
                "buffered_at" : "2026-03-06T10:00:05+00:00",
            }
        ]
        with open( buffer_path, "w" ) as f:
            for entry in entries:
                f.write( json.dumps( entry ) + "\n" )

        assert buffer_path.exists(), "Buffer file should exist before hook"

        # Run hook
        payload  = { "session_id": session_id }
        captured = io.StringIO()

        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", sessions_dir ), \
             patch( "sys.stdin", io.StringIO( json.dumps( payload ) ) ), \
             patch( "sys.stdout", captured ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_claude_session_id",
                    return_value=session_id ):
            try:
                user_prompt_submit.main()
            except SystemExit:
                pass

        # Parse output
        output = captured.getvalue().strip()
        assert output, "Hook should produce output"
        result = json.loads( output )

        # Verify additionalContext
        assert "hookSpecificOutput" in result, "Should have hookSpecificOutput"
        ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
        assert "[Voice]: show me git status" in ctx
        assert "[Voice]: also run the unit tests" in ctx
        assert "IMPORTANT:" in ctx

        # Verify buffer consumed
        assert not buffer_path.exists(), "Buffer file should be consumed after drain"

    print( "E2E voice injection test PASSED" )


def test_e2e_empty_prompt_passthrough():
    """Empty buffer -> hook emits {} -> normal prompt flow."""
    from lupin_cli.claude_code.hooks import user_prompt_submit

    session_id = "nobuffe1-fake-uuid"
    captured   = io.StringIO()

    with tempfile.TemporaryDirectory() as tmp_dir:
        sessions_dir = Path( tmp_dir ) / ".claude" / "sessions"
        sessions_dir.mkdir( parents=True, exist_ok=True )

        payload = { "session_id": session_id }

        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR", sessions_dir ), \
             patch( "sys.stdin", io.StringIO( json.dumps( payload ) ) ), \
             patch( "sys.stdout", captured ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_claude_session_id",
                    return_value=session_id ):
            try:
                user_prompt_submit.main()
            except SystemExit:
                pass

    result = json.loads( captured.getvalue().strip() )
    assert result == {}, f"Expected empty dict, got: {result}"

    print( "E2E empty prompt passthrough test PASSED" )


def test_listener_tmux_inject_mocked():
    """Listener injects message text via tmux (literal + Enter, mocked subprocess)."""
    from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener

    listener = CCNotificationListener.__new__( CCNotificationListener )
    listener.session_id_hash   = "abc12345"
    listener._tmux_session_arg = "test-project"
    listener._tmux_session     = None
    listener.log_file_path     = None
    listener._log_file         = None
    listener._centralized_log  = None
    listener.LOG_PREFIX        = "[CC-Listener]"
    listener.verbose           = False
    listener.debug             = False

    with patch( "subprocess.run" ) as mock_run, \
         patch( "time.sleep" ) as mock_sleep:
        listener._inject_via_tmux( "run the tests" )

    # Verify two subprocess calls: literal text then Enter
    assert mock_run.call_count == 2
    mock_run.assert_any_call(
        [ "tmux", "send-keys", "-t", "test-project", "-l", "run the tests" ],
        capture_output=True, timeout=2
    )
    mock_run.assert_any_call(
        [ "tmux", "send-keys", "-t", "test-project", "Enter" ],
        capture_output=True, timeout=2
    )
    mock_sleep.assert_called_once_with( 0.25 )

    print( "Listener tmux inject test PASSED" )


if __name__ == "__main__":
    test_e2e_voice_injection()
    test_e2e_empty_prompt_passthrough()
    test_listener_tmux_inject_mocked()
    print( "\nAll voice injection E2E smoke tests PASSED" )
