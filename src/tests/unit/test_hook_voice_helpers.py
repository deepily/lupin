"""
Unit tests for shared hook voice helpers in hook_common.py.

Tests cover:
    - format_tool_summary() — Bash with/without command, Write/Edit with path, unknown tool
    - acknowledge_drained() — empty list, single message, truncation
    - drain_and_acknowledge() — integration (mocked drain)
    - TOOLS_SILENT / TOOLS_ANNOUNCE membership checks
"""

import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.lib.hook_common import (
    format_tool_summary,
    acknowledge_drained,
    drain_and_acknowledge,
    TOOLS_SILENT,
    TOOLS_ANNOUNCE
)


# ═════════════════════════════════════════════════════════════════════════════
# TestToolClassification
# ═════════════════════════════════════════════════════════════════════════════

class TestToolClassification:
    """Tests for TOOLS_SILENT and TOOLS_ANNOUNCE constants."""

    def test_silent_contains_read_tools( self ):
        """Read, Grep, Glob are in TOOLS_SILENT."""
        for tool in ( "Read", "Grep", "Glob" ):
            assert tool in TOOLS_SILENT

    def test_silent_contains_task_tools( self ):
        """TaskCreate, TaskUpdate, TaskGet, TaskList are in TOOLS_SILENT."""
        for tool in ( "TaskCreate", "TaskUpdate", "TaskGet", "TaskList" ):
            assert tool in TOOLS_SILENT

    def test_announce_contains_mutating_tools( self ):
        """Bash, Write, Edit are in TOOLS_ANNOUNCE."""
        for tool in ( "Bash", "Write", "Edit" ):
            assert tool in TOOLS_ANNOUNCE

    def test_no_overlap( self ):
        """TOOLS_SILENT and TOOLS_ANNOUNCE have no overlap."""
        assert TOOLS_SILENT.isdisjoint( TOOLS_ANNOUNCE )


# ═════════════════════════════════════════════════════════════════════════════
# TestFormatToolSummary
# ═════════════════════════════════════════════════════════════════════════════

class TestFormatToolSummary:
    """Tests for format_tool_summary()."""

    def test_bash_with_short_command( self ):
        """Bash tool shows command text."""
        result = format_tool_summary( "Bash", { "command": "npm test" } )
        assert result == "Bash: npm test"

    def test_bash_long_command_truncated_at_60( self ):
        """Bash command longer than 60 chars is truncated."""
        long_cmd = "x" * 80
        result   = format_tool_summary( "Bash", { "command": long_cmd } )
        assert result == f"Bash: {'x' * 60}..."
        assert len( result ) == len( "Bash: " ) + 60 + 3

    def test_bash_no_command( self ):
        """Bash with no command key shows just 'Bash'."""
        result = format_tool_summary( "Bash", {} )
        assert result == "Bash"

    def test_write_with_path( self ):
        """Write tool shows basename of file."""
        result = format_tool_summary( "Write", { "file_path": "/home/user/project/main.py" } )
        assert result == "Write: main.py"

    def test_edit_with_path( self ):
        """Edit tool shows basename of file."""
        result = format_tool_summary( "Edit", { "file_path": "/src/utils/helper.js" } )
        assert result == "Edit: helper.js"

    def test_write_no_path( self ):
        """Write with no file_path shows just 'Write'."""
        result = format_tool_summary( "Write", {} )
        assert result == "Write"

    def test_unknown_tool_returns_name( self ):
        """Non-special tool returns just the tool name."""
        result = format_tool_summary( "mcp__cosa-voice__notify", { "message": "hello" } )
        assert result == "mcp__cosa-voice__notify"

    def test_none_tool_input( self ):
        """None tool_input is handled gracefully."""
        result = format_tool_summary( "Bash", None )
        assert result == "Bash"


# ═════════════════════════════════════════════════════════════════════════════
# TestAcknowledgeDrained
# ═════════════════════════════════════════════════════════════════════════════

class TestAcknowledgeDrained:
    """Tests for acknowledge_drained()."""

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.send_tts" )
    def test_empty_list_does_nothing( self, mock_send ):
        """Empty message list sends no TTS."""
        acknowledge_drained( [] )
        mock_send.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.send_tts" )
    def test_single_message( self, mock_send ):
        """Single message sends one TTS with 'Received:' prefix."""
        acknowledge_drained( [ { "message": "Hello world" } ] )
        mock_send.assert_called_once()
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Received: Hello world"

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.send_tts" )
    def test_truncation_at_32_chars( self, mock_send ):
        """Long messages are truncated at 32 chars."""
        long_text = "A" * 50
        acknowledge_drained( [ { "message": long_text } ] )
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "A" * 32 + "..." in call_msg

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.send_tts" )
    def test_text_key_fallback( self, mock_send ):
        """Falls back to 'text' key when 'message' key is missing."""
        acknowledge_drained( [ { "text": "Via text key" } ] )
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "Via text key" in call_msg

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.send_tts", side_effect=Exception( "TTS failed" ) )
    def test_tts_failure_non_fatal( self, mock_send ):
        """TTS failure does not crash the acknowledgment loop."""
        msgs = [ { "message": "First" }, { "message": "Second" } ]
        acknowledge_drained( msgs )  # Should not raise
        assert mock_send.call_count == 2


# ═════════════════════════════════════════════════════════════════════════════
# TestDrainAndAcknowledge
# ═════════════════════════════════════════════════════════════════════════════

class TestDrainAndAcknowledge:
    """Tests for drain_and_acknowledge() convenience wrapper."""

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.acknowledge_drained" )
    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.drain_voice_buffer", return_value=[] )
    def test_empty_buffer( self, mock_drain, mock_ack ):
        """Empty buffer returns empty list, no acknowledgment."""
        result = drain_and_acknowledge( "abc12345" )
        assert result == []
        mock_drain.assert_called_once_with( "abc12345" )
        mock_ack.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.acknowledge_drained" )
    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.drain_voice_buffer" )
    def test_with_messages( self, mock_drain, mock_ack ):
        """Messages are drained and acknowledged."""
        msgs = [ { "message": "Hello" } ]
        mock_drain.return_value = msgs
        result = drain_and_acknowledge( "abc12345" )
        assert result == msgs
        mock_ack.assert_called_once_with( msgs )

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.drain_voice_buffer", side_effect=Exception( "Boom" ) )
    def test_exception_returns_empty( self, mock_drain ):
        """Exception during drain returns empty list."""
        result = drain_and_acknowledge( "abc12345" )
        assert result == []
