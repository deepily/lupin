"""
Unit tests for the PreToolUse hook.

Tests cover:
    - No tool TTS sent (verify send_tts NOT called)
    - Voice drain called with correct session_id
    - Empty payload → immediate {}
    - session_id fallback via get_claude_session_id
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.pre_tool_use import main


# ═════════════════════════════════════════════════════════════════════════════
# TestNoToolTTS
# ═════════════════════════════════════════════════════════════════════════════

class TestNoToolTTS:
    """PreToolUse should NOT announce tools — PostToolUse handles that."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_no_tts_for_bash( self, mock_read, mock_log, mock_session,
                               mock_drain, mock_emit ):
        """Bash tool does NOT trigger TTS in PreToolUse."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "npm test" },
            "session_id" : "abc12345"
        }

        main()

        # send_tts is not even imported in pre_tool_use anymore
        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_no_tts_for_write( self, mock_read, mock_log, mock_session,
                                mock_drain, mock_emit ):
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

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_drain_called_with_payload_session_id( self, mock_read, mock_log, mock_session,
                                                    mock_drain, mock_emit ):
        """Drain uses session_id from payload when available."""
        mock_read.return_value = {
            "tool_name"  : "Grep",
            "tool_input" : { "pattern": "foo" },
            "session_id" : "payload99"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "payload99" )

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_drain, mock_emit ):
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
