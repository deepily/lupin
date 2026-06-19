"""
Unit tests for the Notification hook.

Tests cover:
    - Type-specific TTS: permission_prompt, idle_prompt, default, missing message
    - Message truncation at 80 chars
    - Voice drain called
    - Empty payload → immediate {}
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.notification import main


# ═════════════════════════════════════════════════════════════════════════════
# TestTypeSpecificTTS
# ═════════════════════════════════════════════════════════════════════════════

class TestTypeSpecificTTS:
    """Tests for type-specific TTS message formatting."""

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_permission_prompt_with_message( self, mock_read, mock_log, mock_session,
                                              mock_drain, mock_send, mock_emit, mock_resolve ):
        """permission_prompt includes the full message text with high priority."""
        mock_read.return_value = {
            "type"       : "permission_prompt",
            "message"    : "Claude Code needs your attention",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Claude Code needs your attention"
        assert mock_send.call_args[ 1 ][ "priority" ] == "high"

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_permission_prompt_no_message( self, mock_read, mock_log, mock_session,
                                            mock_drain, mock_send, mock_emit, mock_resolve ):
        """permission_prompt without message uses generic fallback with high priority."""
        mock_read.return_value = {
            "type"       : "permission_prompt",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Permission prompt"
        assert mock_send.call_args[ 1 ][ "priority" ] == "high"

    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_prompt_with_message( self, mock_read, mock_log, mock_session,
                                        mock_drain, mock_send, mock_emit, mock_resolve,
                                        mock_emit_idle, mock_get_persona ):
        """idle_prompt includes the message text AND emits a kind-tagged fleet event."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "message"    : "Waiting for response",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Waiting for response"
        # Step 1.3: the idle branch emits the 4th-signal event with the resolved
        # persona name (dict → name); TTS message is unchanged.
        mock_emit_idle.assert_called_once_with( "abc12345", persona="Tiffany" )

    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_prompt_no_message( self, mock_read, mock_log, mock_session,
                                      mock_drain, mock_send, mock_emit, mock_resolve,
                                      mock_emit_idle, mock_get_persona ):
        """idle_prompt without message uses generic fallback; emits with persona=None
        when no persona is allocated (covers the non-dict branch)."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Claude is waiting for input"
        mock_emit_idle.assert_called_once_with( "abc12345", persona=None )

    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_non_idle_branch_does_not_emit_fleet_event( self, mock_read, mock_log, mock_session,
                                                        mock_drain, mock_send, mock_emit, mock_resolve,
                                                        mock_emit_idle ):
        """permission_prompt (and any non-idle type) MUST NOT emit the idle_prompt event."""
        mock_read.return_value = {
            "type"       : "permission_prompt",
            "message"    : "needs you",
            "session_id" : "abc12345"
        }

        main()

        mock_emit_idle.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_default_type_with_message( self, mock_read, mock_log, mock_session,
                                         mock_drain, mock_send, mock_emit, mock_resolve ):
        """Default notification type includes message text."""
        mock_read.return_value = {
            "type"       : "info",
            "message"    : "Build completed",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Notification (info): Build completed"

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_default_type_no_message( self, mock_read, mock_log, mock_session,
                                       mock_drain, mock_send, mock_emit, mock_resolve ):
        """Default notification type without message shows type only."""
        mock_read.return_value = {
            "type"       : "warning",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Notification: warning"

    # ── §6: idle_prompt delivers pending peer DMs instead of drain-and-discard ──

    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_prompt_delivers_pending_dms_not_discard( self, mock_read, mock_log, mock_session,
                                                           mock_drain, mock_deliver, mock_send,
                                                           mock_emit, mock_resolve, mock_emit_idle,
                                                           mock_persona ):
        """At idle_prompt, a pending peer DM is DELIVERED via deliver_pending_peer_dms
        (tmux-wake), NOT drain-and-discarded — Notification emit_json is ignored by
        CC, so tmux is the only path to an idle pane (§6)."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "message"    : "idle",
            "session_id" : "abc12345",
        }
        main()
        mock_deliver.assert_called_once_with( "abc12345" )
        mock_drain.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_non_idle_uses_drain_not_deliver( self, mock_read, mock_log, mock_session,
                                              mock_drain, mock_deliver, mock_send,
                                              mock_emit, mock_resolve ):
        """A non-idle notification keeps the legacy drain-and-acknowledge (no DM
        delivery) — DM delivery is gated to idle_prompt."""
        mock_read.return_value = {
            "type"       : "permission_prompt",
            "message"    : "needs you",
            "session_id" : "abc12345",
        }
        main()
        mock_drain.assert_called_once_with( "abc12345" )
        mock_deliver.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# TestMessageTruncation
# ═════════════════════════════════════════════════════════════════════════════

class TestMessageTruncation:
    """Tests for message truncation in default notification type."""

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_long_message_truncated_at_80( self, mock_read, mock_log, mock_session,
                                            mock_drain, mock_send, mock_emit, mock_resolve ):
        """Messages longer than 80 chars are truncated with ellipsis."""
        long_msg = "X" * 100
        mock_read.return_value = {
            "type"       : "info",
            "message"    : long_msg,
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "X" * 80 + "..." in call_msg
        assert len( long_msg ) not in [ len( call_msg ) ]  # Confirm truncation happened


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceDrain
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceDrain:
    """Tests for voice buffer drain in Notification hook."""

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_drain_called( self, mock_read, mock_log, mock_session,
                            mock_drain, mock_send, mock_emit, mock_resolve ):
        """Voice drain is called with resolved session_id."""
        mock_read.return_value = {
            "type"    : "info",
            "message" : "test"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )


# ═════════════════════════════════════════════════════════════════════════════
# TestEmptyPayload
# ═════════════════════════════════════════════════════════════════════════════

class TestEmptyPayload:
    """Tests for empty payload handling."""

    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input", return_value={} )
    def test_empty_payload_emits_empty( self, mock_read, mock_emit ):
        """Empty payload immediately emits {} and exits."""
        with pytest.raises( SystemExit ):
            main()

        mock_emit.assert_called_once_with( {} )
