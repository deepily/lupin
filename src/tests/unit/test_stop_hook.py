"""
Unit tests for the Stop hook.

Tests cover:
    - stop_hook_active extraction + TTS (no voice input → allow stop)
    - Voice drain called with correct session_id
    - Empty payload → immediate {}
    - session_id resolution via get_claude_session_id
    - Phase 4: voice input → block with reason
    - Phase 4: stop_hook_active=True → immediate {} (loop prevention)
    - Phase 4: block counter at max → allow stop + reset
    - Phase 4: block counter increments on each block
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.stop import main


# ═════════════════════════════════════════════════════════════════════════════
# TestStopTTS (no voice input — allow stop)
# ═════════════════════════════════════════════════════════════════════════════

class TestStopTTS:
    """Tests for stop_hook_active TTS message when no voice input (allow stop)."""

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_stop_active_missing_no_voice( self, mock_read, mock_log, mock_session,
                                            mock_drain, mock_send, mock_emit, mock_reset ):
        """No voice, no stop_hook_active → TTS shows NOT_PRESENT, allow stop."""
        mock_read.return_value = { "session_id": "abc12345" }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "active=NOT_PRESENT" in call_msg
        mock_emit.assert_called_once_with( {} )


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceDrain
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceDrain:
    """Tests for voice buffer drain in Stop hook."""

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_drain, mock_send, mock_emit, mock_reset ):
        """When payload has no session_id, falls back to session bridge."""
        mock_read.return_value = { "stop_hook_active": False }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_drain_before_tts( self, mock_read, mock_log, mock_session,
                                mock_drain, mock_send, mock_emit, mock_reset ):
        """Drain is called before TTS when no voice input."""
        mock_read.return_value = {
            "stop_hook_active" : False,
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


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceBlocking (Phase 4)
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceBlocking:
    """Tests for voice-driven stop blocking."""

    @patch( "lupin_cli.claude_code.hooks.stop.increment_stop_block_count", return_value=1 )
    @patch( "lupin_cli.claude_code.hooks.stop.get_stop_block_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_voice_input_blocks_stop( self, mock_read, mock_log, mock_session,
                                       mock_drain, mock_send, mock_emit,
                                       mock_get_count, mock_inc ):
        """Voice input → decision: block with voice content as reason."""
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }
        mock_drain.return_value = [ { "message": "focus on linting first" } ]

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        assert "[Voice]: focus on linting first" in emitted[ "reason" ]

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_no_voice_allows_stop( self, mock_read, mock_log, mock_session,
                                    mock_drain, mock_send, mock_emit, mock_reset ):
        """No voice input → allow stop (emit {})."""
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }

        main()

        mock_emit.assert_called_once_with( {} )
        mock_reset.assert_called_once_with( "abc12345" )


# ═════════════════════════════════════════════════════════════════════════════
# TestLoopPrevention (Phase 4)
# ═════════════════════════════════════════════════════════════════════════════

class TestLoopPrevention:
    """Tests for stop_hook_active=True loop prevention."""

    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_stop_active_true_allows_immediately( self, mock_read, mock_log, mock_session,
                                                    mock_drain, mock_emit ):
        """stop_hook_active=True → immediate {} (no drain, no block)."""
        mock_read.return_value = {
            "stop_hook_active" : True,
            "session_id"       : "abc12345"
        }

        with pytest.raises( SystemExit ):
            main()

        mock_drain.assert_not_called()
        mock_emit.assert_called_once_with( {} )


# ═════════════════════════════════════════════════════════════════════════════
# TestBlockCounter (Phase 4)
# ═════════════════════════════════════════════════════════════════════════════

class TestBlockCounter:
    """Tests for stop block counter safety valve."""

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_stop_block_count", return_value=3 )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_max_blocks_allows_stop( self, mock_read, mock_log, mock_session,
                                      mock_drain, mock_send, mock_emit, mock_get_count, mock_reset ):
        """Block count at MAX → allow stop + reset counter."""
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }
        mock_drain.return_value = [ { "message": "keep going" } ]

        main()

        # Should allow stop (emit {}) and reset
        mock_emit.assert_called_once_with( {} )
        mock_reset.assert_called_once_with( "abc12345" )
        # TTS should announce max blocks reached
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "max blocks reached" in call_msg

    @patch( "lupin_cli.claude_code.hooks.stop.increment_stop_block_count", return_value=2 )
    @patch( "lupin_cli.claude_code.hooks.stop.get_stop_block_count", return_value=1 )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_counter_increments_on_block( self, mock_read, mock_log, mock_session,
                                           mock_drain, mock_send, mock_emit,
                                           mock_get_count, mock_inc ):
        """Counter increments each time stop is blocked."""
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }
        mock_drain.return_value = [ { "message": "not done yet" } ]

        main()

        mock_inc.assert_called_once_with( "abc12345" )
        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
