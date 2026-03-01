"""
Unit tests for the Stop hook.

Tests cover:
    - stop_hook_active extraction + TTS
    - Voice drain called with correct session_id
    - Empty payload → immediate {}
    - session_id resolution via get_claude_session_id
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.stop import main


# ═════════════════════════════════════════════════════════════════════════════
# TestStopTTS
# ═════════════════════════════════════════════════════════════════════════════

class TestStopTTS:
    """Tests for stop_hook_active TTS message."""

    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_stop_active_true( self, mock_read, mock_log, mock_session,
                                mock_drain, mock_send, mock_emit ):
        """TTS includes stop_hook_active=True."""
        mock_read.return_value = {
            "stop_hook_active" : True,
            "session_id"       : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "Stop — active=True" in call_msg

    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_stop_active_missing( self, mock_read, mock_log, mock_session,
                                   mock_drain, mock_send, mock_emit ):
        """TTS shows NOT_PRESENT when stop_hook_active is absent."""
        mock_read.return_value = { "session_id": "abc12345" }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "active=NOT_PRESENT" in call_msg


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceDrain
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceDrain:
    """Tests for voice buffer drain in Stop hook."""

    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_drain, mock_send, mock_emit ):
        """When payload has no session_id, falls back to session bridge."""
        mock_read.return_value = { "stop_hook_active": False }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )

    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_drain_before_tts( self, mock_read, mock_log, mock_session,
                                mock_drain, mock_send, mock_emit ):
        """Drain is called before TTS."""
        mock_read.return_value = {
            "stop_hook_active" : True,
            "session_id"       : "abc12345"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "abc12345" )
        mock_send.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# TestEmptyPayload
# ═════════════════════════════════════════════════════════════════════════════

class TestEmptyPayload:
    """Tests for empty payload handling."""

    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input", return_value={} )
    def test_empty_payload_emits_empty( self, mock_read, mock_emit ):
        """Empty payload immediately emits {} and exits."""
        with pytest.raises( SystemExit ):
            main()

        mock_emit.assert_called_once_with( {} )
