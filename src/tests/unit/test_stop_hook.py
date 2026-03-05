"""
Unit tests for the Stop hook.

Tests cover:
    - stop_hook_active extraction (no voice input → notify_user_sync)
    - Voice drain called with correct session_id
    - Empty payload → immediate {}
    - session_id resolution via get_claude_session_id
    - Phase 4: voice input → block with reason
    - Phase 4: stop_hook_active=True → immediate {} (loop prevention)
    - Phase 4: block counter at max → allow stop + reset
    - Phase 4: block counter increments on each block
    - Phase 5: notify_user_sync "Anything else?" flow
    - Phase 5: extract_qualifier_comment regex parsing
"""

import sys
import pytest
from unittest.mock import patch, MagicMock, call

from lupin_cli.claude_code.hooks.stop import main, extract_qualifier_comment


# ═════════════════════════════════════════════════════════════════════════════
# TestExtractQualifierComment
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractQualifierComment:
    """Tests for extract_qualifier_comment() regex parsing."""

    def test_yes_with_comment( self ):
        """'yes [comment: fix the tests]' → ('yes', 'fix the tests')."""
        answer, qualifier = extract_qualifier_comment( "yes [comment: fix the tests]" )
        assert answer == "yes"
        assert qualifier == "fix the tests"

    def test_no_with_comment( self ):
        """'no [comment: not ready]' → ('no', 'not ready')."""
        answer, qualifier = extract_qualifier_comment( "no [comment: not ready]" )
        assert answer == "no"
        assert qualifier == "not ready"

    def test_yes_without_comment( self ):
        """'yes' → ('yes', None)."""
        answer, qualifier = extract_qualifier_comment( "yes" )
        assert answer == "yes"
        assert qualifier is None

    def test_no_without_comment( self ):
        """'no' → ('no', None)."""
        answer, qualifier = extract_qualifier_comment( "no" )
        assert answer == "no"
        assert qualifier is None

    def test_case_insensitive( self ):
        """'YES [comment: do it]' → ('yes', 'do it')."""
        answer, qualifier = extract_qualifier_comment( "YES [comment: do it]" )
        assert answer == "yes"
        assert qualifier == "do it"

    def test_whitespace_handling( self ):
        """' yes  ' → ('yes', None) after stripping."""
        answer, qualifier = extract_qualifier_comment( "  yes  " )
        assert answer == "yes"
        assert qualifier is None

    def test_none_input( self ):
        """None → (None, None)."""
        answer, qualifier = extract_qualifier_comment( None )
        assert answer is None
        assert qualifier is None

    def test_empty_string( self ):
        """'' → (None, None)."""
        answer, qualifier = extract_qualifier_comment( "" )
        assert answer is None
        assert qualifier is None


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceDrain
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceDrain:
    """Tests for voice buffer drain in Stop hook."""

    @patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_drain, mock_emit, mock_reset, mock_ask ):
        """When payload has no session_id, falls back to session bridge."""
        mock_read.return_value = { "stop_hook_active": False }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )

    @patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_drain_before_ask( self, mock_read, mock_log, mock_session,
                                mock_drain, mock_emit, mock_reset, mock_ask ):
        """Drain is called before _ask_anything_else when no voice input."""
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "abc12345" )
        mock_ask.assert_called_once_with( "abc12345" )


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

    @patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_no_voice_calls_ask_anything_else( self, mock_read, mock_log, mock_session,
                                                mock_drain, mock_emit, mock_reset, mock_ask ):
        """No voice input → calls _ask_anything_else and emits its result."""
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }

        main()

        mock_reset.assert_called_once_with( "abc12345" )
        mock_ask.assert_called_once_with( "abc12345" )
        mock_emit.assert_called_once_with( {} )


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


# ═════════════════════════════════════════════════════════════════════════════
# TestNotifyUserSync (Phase 5 — "Anything else?" flow)
# ═════════════════════════════════════════════════════════════════════════════

class TestNotifyUserSync:
    """Tests for the notify_user_sync 'Anything else?' branch."""

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_user_says_yes_blocks_stop( self, mock_notify, mock_sender, mock_read,
                                         mock_log, mock_session, mock_drain, mock_emit, mock_reset ):
        """User says 'yes' → block with continuation reason."""
        mock_response = MagicMock()
        mock_response.response_value = "yes"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        # Need to unpatch _ask_anything_else so it runs the real code
        # which calls notify_user_sync (which we've patched)
        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        assert "continue working" in emitted[ "reason" ]

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_user_says_yes_with_qualifier( self, mock_notify, mock_sender, mock_read,
                                            mock_log, mock_session, mock_drain, mock_emit, mock_reset ):
        """User says 'yes [comment: fix tests]' → block with qualifier in reason."""
        mock_response = MagicMock()
        mock_response.response_value = "yes [comment: fix the tests]"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        assert "fix the tests" in emitted[ "reason" ]
        assert "They said" in emitted[ "reason" ]

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_user_says_no_allows_stop( self, mock_notify, mock_sender, mock_read,
                                        mock_log, mock_session, mock_drain, mock_emit, mock_reset ):
        """User says 'no' → allow stop (emit {})."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_timeout_allows_stop( self, mock_notify, mock_sender, mock_read,
                                   mock_log, mock_session, mock_drain, mock_emit, mock_reset ):
        """Timeout (default 'no') → allow stop (emit {})."""
        mock_response = MagicMock()
        mock_response.response_value = "no"  # Default on timeout
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync", side_effect=ConnectionError( "server down" ) )
    def test_server_error_allows_stop( self, mock_notify, mock_sender, mock_read,
                                        mock_log, mock_session, mock_drain, mock_emit,
                                        mock_reset, mock_tts ):
        """Server error → allow stop gracefully (emit {})."""
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_notify_called_with_correct_params( self, mock_notify, mock_sender, mock_read,
                                                 mock_log, mock_session, mock_drain, mock_emit, mock_reset ):
        """Verify notify_user_sync is called with 5min timeout, default 'no', display_qualifier_widget=True."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        # Verify the NotificationRequest was built correctly
        call_args = mock_notify.call_args
        request = call_args[ 0 ][ 0 ]  # First positional arg
        assert request.timeout_seconds == 300
        assert request.response_default == "no"
        assert request.display_qualifier_widget is True
        assert request.title == "Continue Session?"
