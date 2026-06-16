"""
Unit tests for the PreToolUse hook.

Tests cover:
    - No tool TTS sent (verify send_tts NOT called)
    - Voice drain called with correct session_id
    - Empty payload → immediate {}
    - session_id fallback via get_claude_session_id
    - Phase 4: additionalContext injection from drained messages
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.pre_tool_use import main


@pytest.fixture( autouse=True )
def _stub_bridge_touch():
    """
    Stub the bridge-mtime liveness stamp for every test in this module.

    main() now calls touch_bridge_mtime() at the START of every tool call
    (arbiter signs-of-life Fix 1) — mirroring PostToolUse. Stubbing it keeps
    these unit tests free of real filesystem side effects (the stamp does a real
    os.utime against the resolved bridge) and lets the dedicated stamp tests
    assert the call. Autouse so the existing tests inherit the stub without
    per-method decorators.
    """
    with patch( "lupin_cli.claude_code.hooks.pre_tool_use.touch_bridge_mtime" ) as m:
        yield m


# ═════════════════════════════════════════════════════════════════════════════
# TestNoToolTTS
# ═════════════════════════════════════════════════════════════════════════════

class TestNoToolTTS:
    """PreToolUse should NOT announce tools — PostToolUse handles that."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_no_tts_for_bash( self, mock_read, mock_log, mock_session,
                               mock_drain, mock_emit, mock_resolve ):
        """Bash tool does NOT trigger TTS in PreToolUse."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "npm test" },
            "session_id" : "abc12345"
        }

        main()

        # send_tts is not even imported in pre_tool_use anymore
        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_no_tts_for_write( self, mock_read, mock_log, mock_session,
                                mock_drain, mock_emit, mock_resolve ):
        """Write tool does NOT trigger TTS in PreToolUse."""
        mock_read.return_value = {
            "tool_name"  : "Write",
            "tool_input" : { "file_path": "/tmp/test.py" },
            "session_id" : "abc12345"
        }

        main()

        mock_emit.assert_called_once_with( {} )


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceDrain
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceDrain:
    """Tests for voice buffer drain in PreToolUse."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_drain_called_with_payload_session_id( self, mock_read, mock_log, mock_session,
                                                    mock_drain, mock_emit, mock_resolve ):
        """Drain uses session_id from payload when available."""
        mock_read.return_value = {
            "tool_name"  : "Grep",
            "tool_input" : { "pattern": "foo" },
            "session_id" : "payload99"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "payload99" )

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_drain, mock_emit, mock_resolve ):
        """When payload has no session_id, falls back to session bridge."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : {}
            # No session_id key
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )


# ═════════════════════════════════════════════════════════════════════════════
# TestEmptyPayload
# ═════════════════════════════════════════════════════════════════════════════

class TestEmptyPayload:
    """Tests for empty payload handling."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input", return_value={} )
    def test_empty_payload_emits_empty( self, mock_read, mock_emit ):
        """Empty payload immediately emits {} and exits."""
        with pytest.raises( SystemExit ):
            main()

        mock_emit.assert_called_once_with( {} )


# ═════════════════════════════════════════════════════════════════════════════
# TestContextInjection (Phase 4)
# ═════════════════════════════════════════════════════════════════════════════

class TestContextInjection:
    """Tests for additionalContext injection from drained voice messages."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_drained_messages_emit_additional_context( self, mock_read, mock_log, mock_session,
                                                        mock_drain, mock_emit, mock_resolve ):
        """Drained messages emit hookSpecificOutput.additionalContext."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "ls" },
            "session_id" : "abc12345"
        }
        mock_drain.return_value = [ { "message": "also check the tests" } ]

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert "hookSpecificOutput" in emitted
        assert "[Voice]: also check the tests" in emitted[ "hookSpecificOutput" ][ "additionalContext" ]

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_no_messages_emit_empty( self, mock_read, mock_log, mock_session,
                                      mock_drain, mock_emit, mock_resolve ):
        """No drained messages emits {} (passthrough)."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : {},
            "session_id" : "abc12345"
        }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_multiple_messages_joined( self, mock_read, mock_log, mock_session,
                                        mock_drain, mock_emit, mock_resolve ):
        """Multiple drained messages are joined with newlines in additionalContext."""
        mock_read.return_value = {
            "tool_name"  : "Edit",
            "tool_input" : { "file_path": "/tmp/foo.py" },
            "session_id" : "abc12345"
        }
        mock_drain.return_value = [
            { "message": "first thing" },
            { "message": "second thing" }
        ]

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        ctx     = emitted[ "hookSpecificOutput" ][ "additionalContext" ]
        assert "[Voice]: first thing" in ctx
        assert "[Voice]: second thing" in ctx
        assert "\n" in ctx


# ═════════════════════════════════════════════════════════════════════════════
# TestLivenessStamp (arbiter signs-of-life Fix 1)
# ═════════════════════════════════════════════════════════════════════════════

class TestLivenessStamp:
    """PreToolUse bumps the bridge mtime at the START of a tool call (Fix 1)."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_touch_fires_once_per_tool_call( self, mock_read, mock_log, mock_session,
                                             mock_drain, mock_emit, mock_resolve,
                                             _stub_bridge_touch ):
        """A normal tool call bumps the bridge mtime exactly once, at the start."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "sleep 30" },   # long in-flight tool → start-stamp matters
            "session_id" : "abc12345"
        }

        main()

        _stub_bridge_touch.assert_called_once_with()

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    def test_no_touch_on_empty_payload( self, mock_emit, mock_read, _stub_bridge_touch ):
        """An empty payload exits before the stamp — no liveness lie on a no-op turn."""
        with pytest.raises( SystemExit ):
            main()

        _stub_bridge_touch.assert_not_called()


