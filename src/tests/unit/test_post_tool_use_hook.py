"""
Unit tests for the PostToolUse hook.

Tests cover:
    - Smart TTS: silent tool → no send_tts, announce tool → formatted, unknown → name-only
    - Voice drain called with correct session_id
    - Empty payload → immediate {}
    - Full main() flow with mocked I/O
"""

import json
import sys
import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.post_tool_use import main


# ═════════════════════════════════════════════════════════════════════════════
# TestSmartTTS
# ═════════════════════════════════════════════════════════════════════════════

class TestSmartTTS:
    """Tests for smart TTS filtering in PostToolUse."""

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_silent_tool_no_tts( self, mock_read, mock_log, mock_session,
                                  mock_send, mock_drain, mock_emit ):
        """Read tool (silent) does not send TTS."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : { "file_path": "/tmp/test.py" },
            "session_id" : "abc12345"
        }

        main()

        mock_send.assert_not_called()
        mock_drain.assert_called_once_with( "abc12345" )
        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_grep_silent( self, mock_read, mock_log, mock_session,
                           mock_send, mock_drain, mock_emit ):
        """Grep tool (silent) does not send TTS."""
        mock_read.return_value = {
            "tool_name"  : "Grep",
            "tool_input" : { "pattern": "foo" },
            "session_id" : "abc12345"
        }

        main()

        mock_send.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_bash_announced_with_command( self, mock_read, mock_log, mock_session,
                                          mock_send, mock_drain, mock_emit ):
        """Bash tool (announce) sends formatted TTS with command snippet."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "npm test" },
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Done: Bash: npm test"

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_write_announced_with_basename( self, mock_read, mock_log, mock_session,
                                             mock_send, mock_drain, mock_emit ):
        """Write tool (announce) sends TTS with file basename."""
        mock_read.return_value = {
            "tool_name"  : "Write",
            "tool_input" : { "file_path": "/home/user/project/main.py" },
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Done: Write: main.py"

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_mcp_tool_announced_name_only( self, mock_read, mock_log, mock_session,
                                            mock_send, mock_drain, mock_emit ):
        """MCP/unknown tool sends TTS with name only."""
        mock_read.return_value = {
            "tool_name"  : "mcp__cosa-voice__notify",
            "tool_input" : { "message": "hello" },
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Done: mcp__cosa-voice__notify"


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceDrain
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceDrain:
    """Tests for voice buffer drain in PostToolUse."""

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_send, mock_drain, mock_emit ):
        """When payload has no session_id, falls back to session bridge."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "ls" }
            # No session_id key
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_drain_uses_payload_session_id( self, mock_read, mock_log, mock_session,
                                             mock_send, mock_drain, mock_emit ):
        """Drain uses session_id from payload when available."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : {},
            "session_id" : "payload99"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "payload99" )


# ═════════════════════════════════════════════════════════════════════════════
# TestEmptyPayload
# ═════════════════════════════════════════════════════════════════════════════

class TestEmptyPayload:
    """Tests for empty payload handling."""

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input", return_value={} )
    def test_empty_payload_emits_empty( self, mock_read, mock_emit ):
        """Empty payload immediately emits {} and exits."""
        with pytest.raises( SystemExit ):
            main()

        mock_emit.assert_called_once_with( {} )
