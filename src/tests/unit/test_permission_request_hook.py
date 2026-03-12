"""
Unit tests for the PermissionRequest hook and build_permission_decision helper.

Tests cover:
    - build_permission_decision() — allow, deny+message, deny+interrupt, allow ignores extras
    - _format_tool_description() — Bash, Bash long, Write, Edit, generic, no input
    - _acknowledge_buffered_messages() — empty, single, multiple, truncation
    - _forward_to_user() — yes→allow, no→deny, timeout→deny, error→deny, import fail→deny
    - main() — full flow with empty buffer, full flow with buffered messages
    - Phase 5: buffer-redirect (deny + course-change when buffer has content)
    - Phase 5: auto-allow low-risk tools (Read, Grep, Glob)
"""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock, call


# ── Imports under test ───────────────────────────────────────────────────────

from lupin_cli.claude_code.hooks.lib.hook_common import build_permission_decision

# Import hook module functions directly
from lupin_cli.claude_code.hooks.permission_request import (
    _format_tool_description,
    _acknowledge_buffered_messages,
    _forward_to_user,
    SYNC_TIMEOUT_SECONDS,
    DEFAULT_ON_TIMEOUT,
    AUTO_ALLOW_TOOLS,
    main
)


# ═════════════════════════════════════════════════════════════════════════════
# TestBuildPermissionDecision
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildPermissionDecision:
    """Tests for build_permission_decision() helper in hook_common.py."""

    def test_allow_basic( self ):
        """Allow decision has correct structure."""
        result = build_permission_decision( "allow" )
        assert result == {
            "hookSpecificOutput": {
                "decision": { "behavior": "allow" }
            }
        }

    def test_deny_basic( self ):
        """Deny decision without message has correct structure."""
        result = build_permission_decision( "deny" )
        assert result == {
            "hookSpecificOutput": {
                "decision": { "behavior": "deny" }
            }
        }

    def test_deny_with_message( self ):
        """Deny decision includes message when provided."""
        result = build_permission_decision( "deny", message="Not authorized" )
        decision = result[ "hookSpecificOutput" ][ "decision" ]
        assert decision[ "behavior" ] == "deny"
        assert decision[ "message" ] == "Not authorized"
        assert "interrupt" not in decision

    def test_deny_with_interrupt( self ):
        """Deny decision includes interrupt flag when True."""
        result = build_permission_decision( "deny", interrupt=True )
        decision = result[ "hookSpecificOutput" ][ "decision" ]
        assert decision[ "behavior" ] == "deny"
        assert decision[ "interrupt" ] is True

    def test_deny_with_message_and_interrupt( self ):
        """Deny decision includes both message and interrupt."""
        result = build_permission_decision( "deny", message="Blocked", interrupt=True )
        decision = result[ "hookSpecificOutput" ][ "decision" ]
        assert decision[ "behavior" ] == "deny"
        assert decision[ "message" ] == "Blocked"
        assert decision[ "interrupt" ] is True

    def test_allow_ignores_message( self ):
        """Allow decision ignores message parameter."""
        result = build_permission_decision( "allow", message="Should be ignored" )
        decision = result[ "hookSpecificOutput" ][ "decision" ]
        assert decision == { "behavior": "allow" }
        assert "message" not in decision

    def test_allow_ignores_interrupt( self ):
        """Allow decision ignores interrupt parameter."""
        result = build_permission_decision( "allow", interrupt=True )
        decision = result[ "hookSpecificOutput" ][ "decision" ]
        assert decision == { "behavior": "allow" }
        assert "interrupt" not in decision

    def test_deny_interrupt_false_not_included( self ):
        """Deny with interrupt=False does not include interrupt key."""
        result = build_permission_decision( "deny", interrupt=False )
        decision = result[ "hookSpecificOutput" ][ "decision" ]
        assert "interrupt" not in decision


# ═════════════════════════════════════════════════════════════════════════════
# TestFormatToolDescription
# ═════════════════════════════════════════════════════════════════════════════

class TestFormatToolDescription:
    """Tests for _format_tool_description()."""

    def test_bash_with_command( self ):
        """Bash tool shows command text."""
        result = _format_tool_description( "Bash", { "command": "npm test" } )
        assert result == "Bash: npm test"

    def test_bash_long_command_truncated( self ):
        """Bash command longer than 100 chars is truncated."""
        long_cmd = "x" * 150
        result   = _format_tool_description( "Bash", { "command": long_cmd } )
        assert result == f"Bash: {'x' * 100}..."
        assert len( result ) == len( "Bash: " ) + 100 + 3  # "Bash: " + 100 chars + "..."

    def test_bash_no_command( self ):
        """Bash with no command key shows just 'Bash'."""
        result = _format_tool_description( "Bash", {} )
        assert result == "Bash"

    def test_write_with_path( self ):
        """Write tool shows basename of file."""
        result = _format_tool_description( "Write", { "file_path": "/home/user/project/main.py" } )
        assert result == "Write: main.py"

    def test_edit_with_path( self ):
        """Edit tool shows basename of file."""
        result = _format_tool_description( "Edit", { "file_path": "/src/utils/helper.js" } )
        assert result == "Edit: helper.js"

    def test_write_no_path( self ):
        """Write with no file_path shows just 'Write'."""
        result = _format_tool_description( "Write", {} )
        assert result == "Write"

    def test_generic_tool( self ):
        """Non-special tool returns just the tool name."""
        result = _format_tool_description( "Read", { "file_path": "/some/file" } )
        assert result == "Read"

    def test_empty_tool_name( self ):
        """Empty tool name returns 'unknown tool'."""
        result = _format_tool_description( "", {} )
        assert result == "unknown tool"

    def test_none_tool_input( self ):
        """None tool_input is handled gracefully."""
        result = _format_tool_description( "Bash", None )
        assert result == "Bash"


# ═════════════════════════════════════════════════════════════════════════════
# TestAcknowledgeBufferedMessages
# ═════════════════════════════════════════════════════════════════════════════

class TestAcknowledgeBufferedMessages:
    """Tests for _acknowledge_buffered_messages()."""

    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    def test_empty_list_does_nothing( self, mock_send ):
        """Empty message list sends no TTS."""
        _acknowledge_buffered_messages( [] )
        mock_send.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    def test_single_message( self, mock_send ):
        """Single buffered message sends one TTS."""
        _acknowledge_buffered_messages( [ { "message": "Hello world" } ] )
        mock_send.assert_called_once()
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "Received: Hello world" in call_msg

    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    def test_multiple_messages( self, mock_send ):
        """Multiple buffered messages send one TTS per message."""
        msgs = [
            { "message": "First" },
            { "message": "Second" },
            { "message": "Third" }
        ]
        _acknowledge_buffered_messages( msgs )
        assert mock_send.call_count == 3

    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    def test_message_truncated_at_32_chars( self, mock_send ):
        """Long messages are truncated at 32 chars in acknowledgment."""
        long_text = "A" * 50
        _acknowledge_buffered_messages( [ { "message": long_text } ] )
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "A" * 32 + "..." in call_msg

    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    def test_short_message_not_truncated( self, mock_send ):
        """Short messages are not truncated."""
        _acknowledge_buffered_messages( [ { "message": "Short" } ] )
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "Received: Short" in call_msg
        assert "..." not in call_msg

    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts", side_effect=Exception( "TTS failed" ) )
    def test_tts_failure_non_fatal( self, mock_send ):
        """TTS failure does not crash the acknowledgment loop."""
        msgs = [ { "message": "First" }, { "message": "Second" } ]
        # Should not raise
        _acknowledge_buffered_messages( msgs )
        assert mock_send.call_count == 2

    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    def test_text_key_fallback( self, mock_send ):
        """Falls back to 'text' key when 'message' key is missing."""
        _acknowledge_buffered_messages( [ { "text": "Via text key" } ] )
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "Via text key" in call_msg


# ═════════════════════════════════════════════════════════════════════════════
# TestForwardToUser
# ═════════════════════════════════════════════════════════════════════════════

class TestForwardToUser:
    """Tests for _forward_to_user() with mocked notification infrastructure."""

    @patch( "lupin_cli.claude_code.hooks.permission_request.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.build_sender_id_for_cc" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.NotificationRequest" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.ResponseType" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.NotificationPriority" )
    def test_user_yes_returns_allow( self, mock_priority, mock_rtype, mock_req_cls, mock_sender, mock_sync ):
        """User responding 'yes' returns 'allow'."""
        mock_response = MagicMock()
        mock_response.response_value = "yes"
        mock_sync.return_value = mock_response

        result = _forward_to_user( "Bash: npm test", "abc12345" )
        assert result == "allow"

    @patch( "lupin_cli.claude_code.hooks.permission_request.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.build_sender_id_for_cc" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.NotificationRequest" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.ResponseType" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.NotificationPriority" )
    def test_user_no_returns_deny( self, mock_priority, mock_rtype, mock_req_cls, mock_sender, mock_sync ):
        """User responding 'no' returns 'deny'."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_sync.return_value = mock_response

        result = _forward_to_user( "Write: config.py", "abc12345" )
        assert result == "deny"

    @patch( "lupin_cli.claude_code.hooks.permission_request.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.build_sender_id_for_cc" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.NotificationRequest" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.ResponseType" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.NotificationPriority" )
    def test_timeout_returns_deny( self, mock_priority, mock_rtype, mock_req_cls, mock_sender, mock_sync ):
        """Timeout (None response) returns 'deny'."""
        mock_response = MagicMock()
        mock_response.response_value = None
        mock_sync.return_value = mock_response

        result = _forward_to_user( "Edit: main.py", "abc12345" )
        assert result == "deny"

    @patch( "lupin_cli.claude_code.hooks.permission_request.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.build_sender_id_for_cc" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.NotificationRequest" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.ResponseType" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.NotificationPriority" )
    def test_exception_returns_deny( self, mock_priority, mock_rtype, mock_req_cls, mock_sender, mock_sync ):
        """Exception during notification returns 'deny'."""
        mock_sync.side_effect = Exception( "Connection refused" )

        result = _forward_to_user( "Bash: rm -rf /", "abc12345" )
        assert result == "deny"

    def test_import_failure_returns_deny( self ):
        """Import failure returns 'deny' (no notification infrastructure)."""
        with patch.dict( "sys.modules", { "lupin_cli.notifications.notification_models": None } ):
            # The function catches all exceptions including ImportError
            # We'll test by patching the imports inside the function to fail
            with patch(
                "lupin_cli.claude_code.hooks.permission_request.NotificationRequest",
                side_effect=ImportError( "No module" )
            ):
                result = _forward_to_user( "Read: file.py", "abc12345" )
                assert result == "deny"


# ═════════════════════════════════════════════════════════════════════════════
# TestMainFlow
# ═════════════════════════════════════════════════════════════════════════════

class TestMainFlow:
    """Tests for main() — full hook flow with mocked I/O."""

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._forward_to_user", return_value="allow" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_full_flow_empty_buffer_allow( self, mock_read, mock_log, mock_session,
                                            mock_drain, mock_forward, mock_emit, mock_resolve ):
        """Full flow: empty buffer, user allows."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "npm test" },
            "session_id" : "abc12345"
        }

        main()

        # Verify phases executed
        mock_read.assert_called_once()
        mock_log.assert_called_once_with( "permission_request", mock_read.return_value )
        mock_drain.assert_called_once_with( "abc12345" )
        mock_forward.assert_called_once_with( "Bash: npm test", "abc12345" )

        # Verify emit_json got allow decision
        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "hookSpecificOutput" ][ "decision" ][ "behavior" ] == "allow"

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._forward_to_user", return_value="deny" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._acknowledge_buffered_messages" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_full_flow_with_buffered_messages_redirects( self, mock_read, mock_log, mock_session,
                                                          mock_drain, mock_ack, mock_forward,
                                                          mock_send, mock_emit, mock_resolve ):
        """Phase 5: buffered messages → deny + redirect (Path B), no sync forward."""
        mock_read.return_value = {
            "tool_name"  : "Write",
            "tool_input" : { "file_path": "/src/main.py" },
            "session_id" : "abc12345"
        }
        buffered = [ { "message": "actually focus on linting first" } ]
        mock_drain.return_value = buffered

        with pytest.raises( SystemExit ):
            main()

        # Buffer was drained and acknowledged
        mock_drain.assert_called_once_with( "abc12345" )
        mock_ack.assert_called_once_with( buffered )

        # Forward NOT called (short-circuited by buffer redirect)
        mock_forward.assert_not_called()

        # Emit is deny with redirect message containing voice content
        emitted  = mock_emit.call_args[ 0 ][ 0 ]
        decision = emitted[ "hookSpecificOutput" ][ "decision" ]
        assert decision[ "behavior" ] == "deny"
        assert "[Voice]: actually focus on linting first" in decision[ "message" ]
        assert "before you asked for permission" in decision[ "message" ]

    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input", return_value={} )
    def test_empty_payload_denies( self, mock_read, mock_emit ):
        """Empty payload results in deny with message."""
        with pytest.raises( SystemExit ):
            main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "hookSpecificOutput" ][ "decision" ][ "behavior" ] == "deny"
        assert "Empty hook payload" in emitted[ "hookSpecificOutput" ][ "decision" ][ "message" ]

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._forward_to_user", return_value="allow" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_drain, mock_forward, mock_emit, mock_resolve ):
        """When payload has no session_id, falls back to session bridge."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "echo test" }
            # No session_id key → uses non-auto-allow tool to hit Path C
        }

        main()

        mock_drain.assert_called_once_with( "fallback1" )
        mock_forward.assert_called_once_with( "Bash: echo test", "fallback1" )


# ═════════════════════════════════════════════════════════════════════════════
# TestConstants
# ═════════════════════════════════════════════════════════════════════════════

class TestConstants:
    """Tests for hook constants."""

    def test_sync_timeout_under_30s( self ):
        """SYNC_TIMEOUT_SECONDS must be under 30s (CC hook timeout)."""
        assert SYNC_TIMEOUT_SECONDS < 30

    def test_default_on_timeout_is_deny( self ):
        """DEFAULT_ON_TIMEOUT must be 'deny' for security."""
        assert DEFAULT_ON_TIMEOUT == "deny"

    def test_auto_allow_tools_contains_read_tools( self ):
        """AUTO_ALLOW_TOOLS contains Read, Grep, Glob."""
        for tool in ( "Read", "Grep", "Glob" ):
            assert tool in AUTO_ALLOW_TOOLS

    def test_auto_allow_tools_excludes_mutating( self ):
        """AUTO_ALLOW_TOOLS does NOT contain mutating tools."""
        for tool in ( "Bash", "Write", "Edit" ):
            assert tool not in AUTO_ALLOW_TOOLS


# ═════════════════════════════════════════════════════════════════════════════
# TestAutoAllow (Phase 5)
# ═════════════════════════════════════════════════════════════════════════════

class TestAutoAllow:
    """Tests for auto-allow of low-risk tools (Path A)."""

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_read_auto_allowed( self, mock_read, mock_log, mock_session,
                                 mock_drain, mock_send, mock_emit, mock_resolve ):
        """Read tool is auto-allowed without sync or drain."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : { "file_path": "/tmp/test" },
            "session_id" : "abc12345"
        }

        with pytest.raises( SystemExit ):
            main()

        # Auto-allow → no drain
        mock_drain.assert_not_called()

        # TTS sent with auto-allow message
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "Auto-allow" in call_msg
        assert "Read" in call_msg

        # Decision is allow
        emitted  = mock_emit.call_args[ 0 ][ 0 ]
        decision = emitted[ "hookSpecificOutput" ][ "decision" ]
        assert decision[ "behavior" ] == "allow"

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_grep_auto_allowed( self, mock_read, mock_log, mock_session,
                                 mock_drain, mock_send, mock_emit, mock_resolve ):
        """Grep tool is auto-allowed."""
        mock_read.return_value = {
            "tool_name"  : "Grep",
            "tool_input" : { "pattern": "foo" },
            "session_id" : "abc12345"
        }

        with pytest.raises( SystemExit ):
            main()

        mock_drain.assert_not_called()
        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "hookSpecificOutput" ][ "decision" ][ "behavior" ] == "allow"

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._forward_to_user", return_value="allow" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_bash_not_auto_allowed( self, mock_read, mock_log, mock_session,
                                     mock_drain, mock_forward, mock_send, mock_emit, mock_resolve ):
        """Bash tool is NOT auto-allowed — goes through sync flow."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "npm test" },
            "session_id" : "abc12345"
        }

        main()

        # Drain and forward both called (full sync flow)
        mock_drain.assert_called_once()
        mock_forward.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# TestBufferRedirect (Phase 5)
# ═════════════════════════════════════════════════════════════════════════════

class TestBufferRedirect:
    """Tests for buffer-redirect logic (Path B) — deny + course-change."""

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._forward_to_user" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._acknowledge_buffered_messages" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_buffer_content_denies_with_redirect( self, mock_read, mock_log, mock_session,
                                                    mock_drain, mock_ack, mock_forward,
                                                    mock_send, mock_emit, mock_resolve ):
        """Buffer has content → deny with redirect message."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "rm -rf /tmp/stuff" },
            "session_id" : "abc12345"
        }
        mock_drain.return_value = [ { "message": "wait, check the config first" } ]

        with pytest.raises( SystemExit ):
            main()

        emitted  = mock_emit.call_args[ 0 ][ 0 ]
        decision = emitted[ "hookSpecificOutput" ][ "decision" ]
        assert decision[ "behavior" ] == "deny"
        assert "[Voice]: wait, check the config first" in decision[ "message" ]

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._forward_to_user" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._acknowledge_buffered_messages" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_buffer_content_skips_sync_forward( self, mock_read, mock_log, mock_session,
                                                  mock_drain, mock_ack, mock_forward,
                                                  mock_send, mock_emit, mock_resolve ):
        """Buffer content short-circuits — sync forward NOT called."""
        mock_read.return_value = {
            "tool_name"  : "Write",
            "tool_input" : { "file_path": "/tmp/foo.py" },
            "session_id" : "abc12345"
        }
        mock_drain.return_value = [ { "message": "hold on" } ]

        with pytest.raises( SystemExit ):
            main()

        mock_forward.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._forward_to_user" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._acknowledge_buffered_messages" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_buffer_content_sends_tts_confirmation( self, mock_read, mock_log, mock_session,
                                                      mock_drain, mock_ack, mock_forward,
                                                      mock_send, mock_emit, mock_resolve ):
        """Buffer redirect sends TTS confirmation."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "ls" },
            "session_id" : "abc12345"
        }
        mock_drain.return_value = [ { "message": "one more thing" } ]

        with pytest.raises( SystemExit ):
            main()

        # At least one send_tts call with redirect message
        tts_calls = [ c[ 0 ][ 0 ] for c in mock_send.call_args_list ]
        assert any( "redirecting" in msg.lower() for msg in tts_calls )

    @patch( "lupin_cli.claude_code.hooks.permission_request.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.permission_request.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.permission_request._forward_to_user", return_value="allow" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.drain_voice_buffer", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.permission_request.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.permission_request.read_hook_input" )
    def test_empty_buffer_falls_through_to_sync( self, mock_read, mock_log, mock_session,
                                                   mock_drain, mock_forward, mock_send, mock_emit, mock_resolve ):
        """Empty buffer → falls through to sync forward (existing Path C)."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "npm test" },
            "session_id" : "abc12345"
        }

        main()

        mock_forward.assert_called_once()
        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "hookSpecificOutput" ][ "decision" ][ "behavior" ] == "allow"
