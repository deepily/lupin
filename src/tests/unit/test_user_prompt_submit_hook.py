#!/usr/bin/env python3
"""
Unit tests for the UserPromptSubmit hook.

Tests voice buffer drain -> format -> inject as additionalContext flow.
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_buffer_entry( message, job_id="abc12345" ):
    """Build a JSONL buffer entry dict."""
    return {
        "message"   : message,
        "priority"  : "normal",
        "job_id"    : job_id,
        "sender_id" : "test@example.com",
        "timestamp" : "2026-03-06T10:00:00+00:00",
        "buffered_at" : "2026-03-06T10:00:00+00:00",
    }


def _write_buffer( tmp_dir, session_id, entries ):
    """Write JSONL buffer file and return path."""
    sessions_dir = Path( tmp_dir ) / ".claude" / "sessions"
    sessions_dir.mkdir( parents=True, exist_ok=True )
    hash_part   = session_id[:8]
    buffer_path = sessions_dir / f"cc-buffer-{hash_part}.jsonl"
    with open( buffer_path, "w" ) as f:
        for entry in entries:
            f.write( json.dumps( entry ) + "\n" )
    return buffer_path


def _run_hook_main( payload, tmp_dir, session_id="abc12345-fake-uuid" ):
    """
    Run the UserPromptSubmit hook main() with mocked stdin/stdout.

    Returns the emitted JSON dict.
    """
    import io
    from lupin_cli.claude_code.hooks import user_prompt_submit
    from cosa.config.configuration_manager import ConfigurationManager

    # Seed the ConfigurationManager singleton BEFORE capturing stdout — at a
    # virgin (hermetic) module boundary the hook's CM instantiation would
    # otherwise print its init banner into the captured stream and corrupt
    # the JSON parse below.
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    captured = io.StringIO()

    with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR",
                Path( tmp_dir ) / ".claude" / "sessions" ), \
         patch( "sys.stdin", io.StringIO( json.dumps( payload ) ) ), \
         patch( "sys.stdout", captured ), \
         patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
         patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_claude_session_id",
                return_value=session_id ), \
         patch( "lupin_cli.claude_code.hooks.user_prompt_submit.resolve_stable_session_id",
                side_effect=lambda x: x ):
        try:
            user_prompt_submit.main()
        except SystemExit:
            pass

    output = captured.getvalue().strip()
    if output:
        return json.loads( output )
    return {}


# ── Tests ────────────────────────────────────────────────────────────────────

class TestUserPromptSubmitHook:
    """Tests for user_prompt_submit.py hook."""

    def test_empty_payload_returns_empty( self ):
        """Empty payload -> {}."""
        import io
        from lupin_cli.claude_code.hooks import user_prompt_submit

        captured = io.StringIO()
        with patch( "sys.stdin", io.StringIO( "{}" ) ), \
             patch( "sys.stdout", captured ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_claude_session_id",
                    return_value="abc12345" ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.resolve_stable_session_id",
                    side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR",
                    Path( "/nonexistent" ) ):
            try:
                user_prompt_submit.main()
            except SystemExit:
                pass

        result = json.loads( captured.getvalue().strip() )
        assert result == {}

    def test_no_buffer_returns_rider_only( self ):
        """No JSONL buffer file -> rider only (always-fire post-Phase-5b)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )
            # Phase 5b: the rider fires on every turn (when session_id
            # resolves), so the hook always emits hookSpecificOutput. With
            # no buffered voice content, the additionalContext is the
            # rider block alone (no [Voice]: prefix lines).
            assert "hookSpecificOutput" in result
            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "<system-reminder>" in ctx
            assert "[Voice]" not in ctx

    def test_buffer_with_messages_injects_context( self ):
        """JSONL buffer with messages -> additionalContext."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [ _make_buffer_entry( "list all Python files" ) ]
            _write_buffer( tmp_dir, "abc12345", entries )

            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )

            assert "hookSpecificOutput" in result
            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "[Voice]: list all Python files" in ctx

    def test_buffer_consumed_after_drain( self ):
        """Buffer file is deleted after drain."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [ _make_buffer_entry( "hello" ) ]
            buf     = _write_buffer( tmp_dir, "abc12345", entries )

            payload = { "session_id": "abc12345-fake-uuid" }
            _run_hook_main( payload, tmp_dir )

            assert not buf.exists()

    def test_multiple_messages_combined( self ):
        """Multiple messages are combined into context."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [
                _make_buffer_entry( "first message" ),
                _make_buffer_entry( "second message" ),
            ]
            _write_buffer( tmp_dir, "abc12345", entries )

            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )

            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "[Voice]: first message" in ctx
            assert "[Voice]: second message" in ctx

    def test_empty_buffer_file_returns_rider_only( self ):
        """Empty buffer file -> rider only (always-fire post-Phase-5b)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_buffer( tmp_dir, "abc12345", [] )

            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )
            # Phase 5b: rider fires on every turn (when session_id
            # resolves). An empty buffer drains to zero voice messages, so
            # additionalContext is the rider block alone.
            assert "hookSpecificOutput" in result
            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "<system-reminder>" in ctx
            assert "[Voice]" not in ctx

    def test_session_id_from_payload( self ):
        """session_id from payload is used for buffer lookup."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [ _make_buffer_entry( "payload session", job_id="deadbeef" ) ]
            _write_buffer( tmp_dir, "deadbeef", entries )

            payload = { "session_id": "deadbeef-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir, session_id="deadbeef-fake-uuid" )

            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "[Voice]: payload session" in ctx

    def test_enrich_voice_context_appended( self ):
        """Enriched context includes IMPORTANT reminder."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [ _make_buffer_entry( "do something" ) ]
            _write_buffer( tmp_dir, "abc12345", entries )

            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )

            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "IMPORTANT:" in ctx
            assert "mcp__cosa-voice__notify()" in ctx


class TestHeartbeatPokeReset:
    """Genuine user re-engagement reopens the heartbeat self-poke budget."""

    def test_reset_poke_count_called_on_prompt( self ):
        """UserPromptSubmit resets the per-session heartbeat poke counter."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = { "session_id": "abc12345-fake-uuid" }
            with patch( "lupin_cli.claude_code.hooks.user_prompt_submit.reset_poke_count" ) as mock_reset:
                _run_hook_main( payload, tmp_dir )
            mock_reset.assert_called_once_with( "abc12345-fake-uuid" )

    def test_reset_skipped_on_empty_payload( self ):
        """Empty payload exits before session resolution → no reset attempted."""
        import io
        from lupin_cli.claude_code.hooks import user_prompt_submit

        captured = io.StringIO()
        with patch( "sys.stdin", io.StringIO( "{}" ) ), \
             patch( "sys.stdout", captured ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.reset_poke_count" ) as mock_reset:
            try:
                user_prompt_submit.main()
            except SystemExit:
                pass

        mock_reset.assert_not_called()


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
