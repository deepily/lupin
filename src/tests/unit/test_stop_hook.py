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
    - Gister-powered task summarization (_summarize_task)
    - LLM-based qualifier classification (classify_qualifier)
    - Qualifier routing: question vs instruction
"""

import sys
import pytest
from unittest.mock import patch, MagicMock, call

from lupin_cli.claude_code.hooks.stop import main, _summarize_task
from cosa.utils.notification_utils import extract_qualifier_comment


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
# TestSummarizeTask
# ═════════════════════════════════════════════════════════════════════════════

class TestSummarizeTask:
    """Tests for _summarize_task() Gister integration."""

    def test_none_input( self ):
        """None input → None."""
        assert _summarize_task( None ) is None

    def test_empty_string( self ):
        """Empty string → None."""
        assert _summarize_task( "" ) is None

    def test_whitespace_only( self ):
        """Whitespace-only → None."""
        assert _summarize_task( "   " ) is None

    @patch( "lupin_cli.claude_code.hooks.stop.Gister", create=True )
    def test_returns_gist( self, MockGisterClass ):
        """Mock Gister returns gist → returns that gist."""
        # We need to patch at the import site inside the function
        with patch( "cosa.memory.gister.Gister" ) as MockGister:
            mock_instance = MagicMock()
            mock_instance.get_gist.return_value = "fixed linting errors"
            MockGister.return_value = mock_instance

            result = _summarize_task( "I fixed all the linting errors in the codebase" )
            assert result == "fixed linting errors"

    def test_gister_exception_returns_none( self ):
        """Mock Gister exception → returns None."""
        with patch( "cosa.memory.gister.Gister", side_effect=RuntimeError( "LLM down" ) ):
            result = _summarize_task( "Some assistant message" )
            assert result is None


# ═════════════════════════════════════════════════════════════════════════════
# TestClassifyQualifier — COMMENTED OUT
# classify_qualifier() is commented out in stop.py because its synchronous
# LLM call to phi4 exceeds Claude Code's stop hook subprocess timeout (~5-10s).
# Preserved for future use in non-time-critical contexts.
# ═════════════════════════════════════════════════════════════════════════════

# class TestClassifyQualifier:
#     """Tests for classify_qualifier() LLM intent classification."""
#
#     @patch( "cosa.agents.llm_client_factory.LlmClientFactory" )
#     @patch( "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor" )
#     @patch( "cosa.utils.util.get_file_as_string", return_value="template {utterance}" )
#     @patch( "cosa.utils.util.get_project_root", return_value="/mock/root" )
#     @patch( "cosa.config.configuration_manager.ConfigurationManager" )
#     def test_returns_question_classification( self, MockConfig, mock_root, mock_file,
#                                                MockProcessor, MockFactory ):
#         ...
#
#     @patch( "cosa.agents.llm_client_factory.LlmClientFactory" )
#     @patch( "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor" )
#     @patch( "cosa.utils.util.get_file_as_string", return_value="template {utterance}" )
#     @patch( "cosa.utils.util.get_project_root", return_value="/mock/root" )
#     @patch( "cosa.config.configuration_manager.ConfigurationManager" )
#     def test_returns_instruction_classification( self, MockConfig, mock_root, mock_file,
#                                                   MockProcessor, MockFactory ):
#         ...
#
#     def test_llm_failure_returns_none( self ):
#         ...
#
#     @patch( "cosa.agents.llm_client_factory.LlmClientFactory" )
#     @patch( "cosa.agents.io_models.utils.prompt_template_processor.PromptTemplateProcessor" )
#     @patch( "cosa.utils.util.get_file_as_string", return_value="template {utterance}" )
#     @patch( "cosa.utils.util.get_project_root", return_value="/mock/root" )
#     @patch( "cosa.config.configuration_manager.ConfigurationManager" )
#     def test_xml_parse_error_returns_none( self, MockConfig, mock_root, mock_file,
#                                             MockProcessor, MockFactory ):
#         ...


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
        mock_ask.assert_called_once_with( "abc12345", None )


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
        mock_ask.assert_called_once_with( "abc12345", None )
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

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_user_says_yes_blocks_stop( self, mock_notify, mock_sender, mock_read,
                                         mock_log, mock_session, mock_drain, mock_emit,
                                         mock_reset, mock_summarize ):
        """User says 'yes' → block with continuation reason."""
        mock_response = MagicMock()
        mock_response.response_value = "yes"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        assert "continue working" in emitted[ "reason" ]

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.stop.inject_qualifier_via_tmux" )
    def test_qualifier_question_routes_correctly( self, mock_inject, mock_notify, mock_sender, mock_read,
                                                     mock_log, mock_session, mock_drain, mock_emit,
                                                     mock_reset, mock_summarize ):
        """Qualifier ending with '?' → injected via tmux, stop blocked."""
        mock_response = MagicMock()
        mock_response.response_value = "yes [comment: how many tests passed?]"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        mock_inject.assert_called_once_with( "abc12345", "how many tests passed?" )

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.stop.inject_qualifier_via_tmux" )
    def test_qualifier_instruction_routes_correctly( self, mock_inject, mock_notify, mock_sender, mock_read,
                                                       mock_log, mock_session, mock_drain, mock_emit,
                                                       mock_reset, mock_summarize ):
        """Qualifier without '?' → injected via tmux, stop blocked."""
        mock_response = MagicMock()
        mock_response.response_value = "yes [comment: fix the linting errors]"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        mock_inject.assert_called_once_with( "abc12345", "fix the linting errors" )

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value="fixed linting errors" )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_notify_message_includes_gist( self, mock_notify, mock_sender, mock_read,
                                             mock_log, mock_session, mock_drain, mock_emit,
                                             mock_reset, mock_summarize ):
        """When _summarize_task returns a gist, notification message includes it."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        request = mock_notify.call_args[ 0 ][ 0 ]
        assert "fixed linting errors" in request.message
        assert "I'm finished" in request.message

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_notify_message_fallback( self, mock_notify, mock_sender, mock_read,
                                        mock_log, mock_session, mock_drain, mock_emit,
                                        mock_reset, mock_summarize ):
        """When _summarize_task returns None, falls back to generic message."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        request = mock_notify.call_args[ 0 ][ 0 ]
        assert "finished the current task" in request.message

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_user_says_no_allows_stop( self, mock_notify, mock_sender, mock_read,
                                        mock_log, mock_session, mock_drain, mock_emit,
                                        mock_reset, mock_summarize ):
        """User says plain 'no' → allow stop (emit {})."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.stop.inject_qualifier_via_tmux" )
    def test_no_with_qualifier_instruction_blocks_stop( self, mock_inject, mock_notify, mock_sender, mock_read,
                                                          mock_log, mock_session, mock_drain, mock_emit,
                                                          mock_reset, mock_summarize ):
        """'no [comment: say hi]' → blocks stop, qualifier injected via tmux."""
        mock_response = MagicMock()
        mock_response.exit_code      = 0
        mock_response.response_value = "no [comment: say hi using a high-priority notification]"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        mock_inject.assert_called_once_with( "abc12345", "say hi using a high-priority notification" )

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.stop.inject_qualifier_via_tmux" )
    def test_no_with_qualifier_question_blocks_stop( self, mock_inject, mock_notify, mock_sender, mock_read,
                                                        mock_log, mock_session, mock_drain, mock_emit,
                                                        mock_reset, mock_summarize ):
        """'no [comment: what time is it?]' → blocks stop, qualifier injected via tmux."""
        mock_response = MagicMock()
        mock_response.exit_code      = 0
        mock_response.response_value = "no [comment: what time is it?]"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        mock_inject.assert_called_once_with( "abc12345", "what time is it?" )

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_timeout_allows_stop( self, mock_notify, mock_sender, mock_read,
                                   mock_log, mock_session, mock_drain, mock_emit,
                                   mock_reset, mock_summarize ):
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

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    def test_notify_called_with_correct_params( self, mock_notify, mock_sender, mock_read,
                                                 mock_log, mock_session, mock_drain, mock_emit,
                                                 mock_reset, mock_summarize ):
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

    @patch( "lupin_cli.claude_code.hooks.stop._summarize_task", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.stop.inject_qualifier_via_tmux" )
    def test_plain_yes_does_not_inject( self, mock_inject, mock_notify, mock_sender, mock_read,
                                          mock_log, mock_session, mock_drain, mock_emit,
                                          mock_reset, mock_summarize ):
        """Plain 'yes' (no qualifier) → blocks stop, does NOT inject via tmux."""
        mock_response = MagicMock()
        mock_response.response_value = "yes"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        assert "continue working" in emitted[ "reason" ]
        mock_inject.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# TestInjectQualifierViaTmux
# ═════════════════════════════════════════════════════════════════════════════

class TestInjectQualifierViaTmux:
    """Tests for inject_qualifier_via_tmux() in hook_common."""

    @patch( "subprocess.Popen" )
    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id" )
    def test_spawns_popen( self, mock_find, mock_popen ):
        """Valid session → spawns Popen with tmux send-keys command."""
        mock_find.return_value = { "tmux_session": "lupin", "session_id": "abc12345" }

        from lupin_cli.claude_code.hooks.lib.hook_common import inject_qualifier_via_tmux
        inject_qualifier_via_tmux( "abc12345", "fix the tests" )

        mock_popen.assert_called_once()
        args = mock_popen.call_args[ 0 ][ 0 ]
        # Verify bash positional args structure
        assert args[ 0 ] == "bash"
        assert args[ 1 ] == "-c"
        assert "tmux send-keys" in args[ 2 ]
        assert args[ 5 ] == "lupin"      # $2 = tmux_session
        assert args[ 6 ] == "fix the tests"  # $3 = text
        # Verify detached
        assert mock_popen.call_args[ 1 ][ "start_new_session" ] is True

    @patch( "subprocess.Popen" )
    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id" )
    def test_no_session_skips( self, mock_find, mock_popen ):
        """No session found → Popen NOT called, no exception."""
        mock_find.return_value = None

        from lupin_cli.claude_code.hooks.lib.hook_common import inject_qualifier_via_tmux
        inject_qualifier_via_tmux( "abc12345", "fix the tests" )

        mock_popen.assert_not_called()

    @patch( "subprocess.Popen" )
    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id" )
    def test_special_chars_safe( self, mock_find, mock_popen ):
        """Special chars in text → passed as separate positional arg, not embedded in shell."""
        mock_find.return_value = { "tmux_session": "lupin", "session_id": "abc12345" }

        from lupin_cli.claude_code.hooks.lib.hook_common import inject_qualifier_via_tmux
        inject_qualifier_via_tmux( "abc12345", "it's a test; echo pwned" )

        mock_popen.assert_called_once()
        args = mock_popen.call_args[ 0 ][ 0 ]
        # Text is a separate positional arg ($3), NOT embedded in the shell string
        assert args[ 6 ] == "it's a test; echo pwned"
        # The shell command template does NOT contain the text
        assert "it's a test" not in args[ 2 ]
