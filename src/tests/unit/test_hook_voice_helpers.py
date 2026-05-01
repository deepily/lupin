"""
Unit tests for shared hook voice helpers in hook_common.py.

Tests cover:
    - format_tool_summary() — Bash with/without command, Write/Edit with path, unknown tool
    - acknowledge_drained() — empty list, single message, truncation
    - drain_and_acknowledge() — integration (mocked drain)
    - TOOLS_SILENT / TOOLS_ANNOUNCE membership checks
    - format_voice_context() — empty, single, multiple, missing text field
    - build_additional_context() — empty → {}, non-empty → wrapped dict
    - build_stop_block() — returns top-level decision + reason
    - is_mcp_voice_tool() — cosa-voice prefix → True, regular → False, empty → False
    - Stop block counter — increment, get, reset, max exceeded
"""

import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.lib.hook_common import (
    format_tool_summary,
    acknowledge_drained,
    drain_and_acknowledge,
    format_voice_context,
    build_additional_context,
    build_stop_block,
    is_mcp_voice_tool,
    get_stop_block_count,
    increment_stop_block_count,
    reset_stop_block_count,
    MAX_STOP_BLOCKS,
    MCP_VOICE_PREFIX,
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
        """Single message is a no-op (auto-response moved to CCNotificationListener)."""
        acknowledge_drained( [ { "message": "Hello world" } ] )
        mock_send.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.send_tts" )
    def test_truncation_at_32_chars( self, mock_send ):
        """Long messages are a no-op (auto-response moved to CCNotificationListener)."""
        long_text = "A" * 50
        acknowledge_drained( [ { "message": long_text } ] )
        mock_send.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.send_tts" )
    def test_text_key_fallback( self, mock_send ):
        """Text key messages are a no-op (auto-response moved to CCNotificationListener)."""
        acknowledge_drained( [ { "text": "Via text key" } ] )
        mock_send.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.send_tts" )
    def test_tts_failure_non_fatal( self, mock_send ):
        """Multiple messages are a no-op (auto-response moved to CCNotificationListener)."""
        msgs = [ { "message": "First" }, { "message": "Second" } ]
        acknowledge_drained( msgs )  # Should not raise
        mock_send.assert_not_called()


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


# ═════════════════════════════════════════════════════════════════════════════
# TestFormatVoiceContext
# ═════════════════════════════════════════════════════════════════════════════

class TestFormatVoiceContext:
    """Tests for format_voice_context()."""

    def test_empty_list_returns_empty_string( self ):
        """Empty message list returns empty string."""
        assert format_voice_context( [] ) == ""

    def test_single_message( self ):
        """Single message gets [Voice] prefix."""
        msgs   = [ { "message": "check the tests" } ]
        result = format_voice_context( msgs )
        assert result == "[Voice]: check the tests"

    def test_multiple_messages( self ):
        """Multiple messages are joined with newlines."""
        msgs = [
            { "message": "first thing" },
            { "message": "second thing" }
        ]
        result = format_voice_context( msgs )
        assert result == "[Voice]: first thing\n[Voice]: second thing"

    def test_missing_text_field_uses_text_key( self ):
        """Falls back to 'text' key when 'message' key is missing."""
        msgs   = [ { "text": "via text key" } ]
        result = format_voice_context( msgs )
        assert result == "[Voice]: via text key"

    def test_blank_messages_skipped( self ):
        """Blank/whitespace-only messages are skipped."""
        msgs = [
            { "message": "" },
            { "message": "  " },
            { "message": "real content" }
        ]
        result = format_voice_context( msgs )
        assert result == "[Voice]: real content"

    def test_all_blank_returns_empty( self ):
        """All blank messages returns empty string."""
        msgs = [ { "message": "" }, { "message": "  " } ]
        assert format_voice_context( msgs ) == ""

    def test_whitespace_stripped( self ):
        """Leading/trailing whitespace is stripped from messages."""
        msgs   = [ { "message": "  hello world  " } ]
        result = format_voice_context( msgs )
        assert result == "[Voice]: hello world"


# ═════════════════════════════════════════════════════════════════════════════
# TestBuildAdditionalContext
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildAdditionalContext:
    """Tests for build_additional_context()."""

    def test_empty_string_returns_empty_dict( self ):
        """Empty context string returns {} (passthrough)."""
        assert build_additional_context( "", "UserPromptSubmit" ) == {}

    def test_none_returns_empty_dict( self ):
        """None context returns {} (passthrough)."""
        assert build_additional_context( None, "UserPromptSubmit" ) == {}

    def test_non_empty_returns_wrapped_dict( self ):
        """Non-empty context is wrapped in hookSpecificOutput with hookEventName + additionalContext."""
        result = build_additional_context( "[Voice]: hello", "UserPromptSubmit" )
        assert result == {
            "hookSpecificOutput": {
                "hookEventName"   : "UserPromptSubmit",
                "additionalContext": "[Voice]: hello"
            }
        }

    def test_event_name_is_propagated( self ):
        """The hook_event_name parameter must round-trip into the output dict."""
        result = build_additional_context( "ctx", "PostToolUse" )
        assert result[ "hookSpecificOutput" ][ "hookEventName" ] == "PostToolUse"


# ═════════════════════════════════════════════════════════════════════════════
# TestBuildStopBlock
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildStopBlock:
    """Tests for build_stop_block()."""

    def test_returns_decision_block( self ):
        """Returns top-level decision: block with reason."""
        result = build_stop_block( "[Voice]: focus on linting" )
        assert result == {
            "decision": "block",
            "reason"  : "[Voice]: focus on linting"
        }

    def test_not_wrapped_in_hook_specific_output( self ):
        """Stop block is NOT wrapped in hookSpecificOutput."""
        result = build_stop_block( "test reason" )
        assert "hookSpecificOutput" not in result


# ═════════════════════════════════════════════════════════════════════════════
# TestIsMcpVoiceTool
# ═════════════════════════════════════════════════════════════════════════════

class TestIsMcpVoiceTool:
    """Tests for is_mcp_voice_tool()."""

    def test_cosa_voice_notify( self ):
        """mcp__cosa-voice__notify is a voice tool."""
        assert is_mcp_voice_tool( "mcp__cosa-voice__notify" ) is True

    def test_cosa_voice_converse( self ):
        """mcp__cosa-voice__converse is a voice tool."""
        assert is_mcp_voice_tool( "mcp__cosa-voice__converse" ) is True

    def test_cosa_voice_ask_yes_no( self ):
        """mcp__cosa-voice__ask_yes_no is a voice tool."""
        assert is_mcp_voice_tool( "mcp__cosa-voice__ask_yes_no" ) is True

    def test_regular_tool_returns_false( self ):
        """Regular tool (Bash) is not a voice tool."""
        assert is_mcp_voice_tool( "Bash" ) is False

    def test_empty_string_returns_false( self ):
        """Empty tool name returns False."""
        assert is_mcp_voice_tool( "" ) is False

    def test_none_returns_false( self ):
        """None tool name returns False."""
        assert is_mcp_voice_tool( None ) is False

    def test_other_mcp_tool_returns_false( self ):
        """Non-voice MCP tool returns False."""
        assert is_mcp_voice_tool( "mcp__other-server__func" ) is False


# ═════════════════════════════════════════════════════════════════════════════
# TestStopBlockCounter
# ═════════════════════════════════════════════════════════════════════════════

class TestStopBlockCounter:
    """Tests for stop block counter helpers (get, increment, reset)."""

    def test_initial_count_is_zero( self, tmp_path, monkeypatch ):
        """Fresh session has count 0."""
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.lib.hook_common._stop_counter_path",
            lambda sid: tmp_path / f"counter-{sid}"
        )
        assert get_stop_block_count( "test1234" ) == 0

    def test_increment_returns_new_count( self, tmp_path, monkeypatch ):
        """Increment returns 1 on first call, 2 on second."""
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.lib.hook_common._stop_counter_path",
            lambda sid: tmp_path / f"counter-{sid}"
        )
        assert increment_stop_block_count( "test1234" ) == 1
        assert increment_stop_block_count( "test1234" ) == 2
        assert increment_stop_block_count( "test1234" ) == 3

    def test_reset_clears_count( self, tmp_path, monkeypatch ):
        """Reset brings count back to 0."""
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.lib.hook_common._stop_counter_path",
            lambda sid: tmp_path / f"counter-{sid}"
        )
        increment_stop_block_count( "test1234" )
        increment_stop_block_count( "test1234" )
        reset_stop_block_count( "test1234" )
        assert get_stop_block_count( "test1234" ) == 0

    def test_max_stop_blocks_constant( self ):
        """MAX_STOP_BLOCKS is 3."""
        assert MAX_STOP_BLOCKS == 3
