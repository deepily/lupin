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

from lupin_cli.claude_code.hooks.stop import main, _summarize_task, _should_ask_anything_else
from lupin_cli.notifications.notification_models import NotificationPriority
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

    def test_neither_with_comment( self ):
        """'neither [comment: re-frame please]' → ('neither', 're-frame please')."""
        answer, qualifier = extract_qualifier_comment( "neither [comment: re-frame please]" )
        assert answer == "neither"
        assert qualifier == "re-frame please"

    def test_neither_no_comment( self ):
        """'neither' → ('neither', None)."""
        answer, qualifier = extract_qualifier_comment( "neither" )
        assert answer == "neither"
        assert qualifier is None

    def test_neither_case_insensitive( self ):
        """'NEITHER' → ('neither', None)."""
        answer, qualifier = extract_qualifier_comment( "NEITHER" )
        assert answer == "neither"
        assert qualifier is None

    def test_neither_with_whitespace( self ):
        """'  neither  ' → ('neither', None) after stripping."""
        answer, qualifier = extract_qualifier_comment( "  neither  " )
        assert answer == "neither"
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
            mock_instance.get_gist.assert_called_once_with(
                "I fixed all the linting errors in the codebase",
                prompt_key="prompt template for stop hook gist"
            )

    def test_gister_exception_returns_none( self ):
        """Mock Gister exception → returns None."""
        with patch( "cosa.memory.gister.Gister", side_effect=RuntimeError( "LLM down" ) ):
            result = _summarize_task( "Some assistant message" )
            assert result is None


# ═════════════════════════════════════════════════════════════════════════════
# TestShouldAskAnythingElse (Two-Signal Gate)
# ═════════════════════════════════════════════════════════════════════════════

class TestShouldAskAnythingElse:
    """Tests for _should_ask_anything_else() two-signal gate."""

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    def test_none_message_returns_false( self, mock_log ):
        """None last_assistant_message → False (Signal 1)."""
        assert _should_ask_anything_else( None, "abc12345" ) is False

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    def test_empty_message_returns_false( self, mock_log ):
        """Empty string → False (Signal 1)."""
        assert _should_ask_anything_else( "", "abc12345" ) is False

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    def test_whitespace_message_returns_false( self, mock_log ):
        """Whitespace-only → False (Signal 1)."""
        assert _should_ask_anything_else( "   \n\t  ", "abc12345" ) is False

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_turn_elapsed_seconds", return_value=3.5 )
    def test_short_turn_returns_false( self, mock_elapsed, mock_log ):
        """Turn < MIN_TURN_DURATION_SECONDS → False (Signal 2)."""
        assert _should_ask_anything_else( "I did some work", "abc12345" ) is False

    @patch( "lupin_cli.claude_code.hooks.stop.get_turn_elapsed_seconds", return_value=60.0 )
    def test_long_turn_with_message_returns_true( self, mock_elapsed ):
        """Has message + turn > threshold → True."""
        assert _should_ask_anything_else( "I fixed the bug and updated tests", "abc12345" ) is True

    @patch( "lupin_cli.claude_code.hooks.stop.get_turn_elapsed_seconds", return_value=None )
    def test_no_marker_returns_true( self, mock_elapsed ):
        """No turn marker (None elapsed) → True (safe fallback)."""
        assert _should_ask_anything_else( "I did work", "abc12345" ) is True

    @patch( "lupin_cli.claude_code.hooks.stop.get_turn_elapsed_seconds", return_value=10.0 )
    def test_exactly_at_threshold_returns_true( self, mock_elapsed ):
        """Elapsed == threshold → True (not strictly less than)."""
        assert _should_ask_anything_else( "Done", "abc12345" ) is True

    @patch( "lupin_cli.claude_code.hooks.stop.get_turn_elapsed_seconds", return_value=9.9 )
    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    def test_just_below_threshold_returns_false( self, mock_log, mock_elapsed ):
        """Elapsed just below threshold → False."""
        assert _should_ask_anything_else( "Done", "abc12345" ) is False


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

def _disable_idle_detection_fixture():
    """
    Shared autouse fixture body: disables idle_detection so tests that exercise
    the legacy immediate-ask path keep hitting it after the 2026-04-29 idle-aware
    Stop hook landing. See:
        src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
    Apply via @pytest.fixture(autouse=True) wrapping in each test class that
    expects _ask_anything_else (legacy) instead of _arm_idle_waiter (deferred).
    """
    return ( "lupin_cli.claude_code.hooks.stop.load_idle_settings",
             lambda: { "enabled": False, "backoff_minutes": [ ] } )


class TestVoiceDrain:

    @pytest.fixture( autouse=True )
    def _disable_idle( self, monkeypatch ):
        target, value = _disable_idle_detection_fixture()
        monkeypatch.setattr( target, value )

    """Tests for voice buffer drain in Stop hook."""

    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_drain, mock_emit, mock_reset, mock_ask, mock_resolve ):
        """When payload has no session_id, falls back to session bridge."""
        mock_read.return_value = { "stop_hook_active": False }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )

    @patch( "lupin_cli.claude_code.hooks.stop.load_idle_settings",
            return_value={ "enabled": False, "backoff_minutes": [ ] } )
    @patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False )
    @patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="ask" )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_drain_before_ask( self, mock_read, mock_log, mock_session,
                                mock_drain, mock_emit, mock_reset, mock_ask, mock_gate, mock_resolve,
                                mock_behavior, mock_sp, mock_hb, mock_idle_settings ):
        """Drain is called before _ask_anything_else when no voice input and gate passes."""
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "abc12345" )
        mock_ask.assert_called_once_with( "abc12345", None, cwd=None )


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

    @pytest.fixture( autouse=True )
    def _disable_idle( self, monkeypatch ):
        target, value = _disable_idle_detection_fixture()
        monkeypatch.setattr( target, value )

    """Tests for voice-driven stop blocking."""

    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                       mock_get_count, mock_inc, mock_resolve ):
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

    @patch( "lupin_cli.claude_code.hooks.stop.load_idle_settings",
            return_value={ "enabled": False, "backoff_minutes": [ ] } )
    @patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False )
    @patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="ask" )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_no_voice_calls_ask_anything_else( self, mock_read, mock_log, mock_session,
                                                mock_drain, mock_emit, mock_reset, mock_ask, mock_gate, mock_resolve,
                                                mock_behavior, mock_sp, mock_hb, mock_idle_settings ):
        """No voice input + idle behavior 'ask' → calls _ask_anything_else and emits its result."""
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }

        main()

        mock_reset.assert_called_once_with( "abc12345" )
        mock_ask.assert_called_once_with( "abc12345", None, cwd=None )
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
# TestConversationModeGate (Bug B — Session c7333045, 2026-04-28)
# ═════════════════════════════════════════════════════════════════════════════

class TestConversationModeGate:

    @pytest.fixture( autouse=True )
    def _disable_idle( self, monkeypatch ):
        target, value = _disable_idle_detection_fixture()
        monkeypatch.setattr( target, value )

    """
    When the session is in conversation mode the hook suppresses ONLY the
    interactive surfaces — the voice-buffer drain/inject path and the blocking
    "Anything else?" prompt (the user is holding a continuous voice dialogue at
    a distance). §3 split (2026-06-09): the heartbeat self-poke + breadcrumb
    are NOT suppressed — the poke's work-owed oracle is the gate.
    """

    @patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="none" )
    @patch( "lupin_cli.claude_code.hooks.stop._has_pending_voice", return_value=False )
    @patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop._try_auto_narrate" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_sync" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_speakerphone_suppresses_only_interactive_paths( self, mock_read, mock_log, mock_conv,
                                                  mock_session, mock_resolve, mock_drain,
                                                  mock_emit, mock_notify, mock_send_tts,
                                                  mock_try_auto_narrate, mock_hb,
                                                  mock_voice_peek, mock_behavior ):
        """speakerphone_on=True → emit {}, run auto-narrate safety net AND the
        heartbeat (§3 split, 2026-06-09 — the heartbeat is NO LONGER skipped),
        but NO drain, NO blocking notify, NO direct TTS via the prompt paths.

        `_try_auto_narrate` (Phase 4 Layer 3) is patched as a no-op here so the
        send_tts assertion specifically covers the prompt-path code; auto-narrate
        has its own tests at TestAutoNarrate*. The heartbeat poke matrix lives
        in test_stop_hook_heartbeat.py::TestMainSpeakerphonePokeMatrix. See:
        src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md
        """
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }

        with pytest.raises( SystemExit ):
            main()

        # The gate fired with the resolved session_id
        mock_conv.assert_called_once_with( "abc12345" )
        # Allow the stop, no block payload
        mock_emit.assert_called_once_with( {} )
        # The auto-narrate safety net DOES run (this is intentional in conv mode)
        mock_try_auto_narrate.assert_called_once_with( "abc12345", mock_read.return_value )
        # §3 regression flip: the heartbeat DOES run for speakerphone sessions
        # (this exact assertion was impossible pre-split — the :990 early-exit
        # bailed before the poke; see the 2026.06.09 brief §2)
        mock_hb.assert_called_once_with( "abc12345", None )
        # The interactive side effects MUST NOT fire
        mock_drain.assert_not_called()
        mock_notify.assert_not_called()
        # send_tts was patched separately from _try_auto_narrate, so this asserts
        # nothing in main()'s prompt path bypassed the gate to call TTS.
        mock_send_tts.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.load_idle_settings",
            return_value={ "enabled": False, "backoff_minutes": [ ] } )
    @patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="ask" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_notification_mode_runs_normal_flow( self, mock_read, mock_log, mock_conv,
                                                  mock_session, mock_resolve, mock_emit,
                                                  mock_ask, mock_reset, mock_drain,
                                                  mock_behavior, mock_hb, mock_idle_settings ):
        """speakerphone_on=False + idle behavior 'ask' → falls through to the ask path."""
        mock_read.return_value = {
            "stop_hook_active" : False,
            "session_id"       : "abc12345"
        }

        main()

        mock_conv.assert_called_once_with( "abc12345" )
        # Standard flow: drain ran, ask_anything_else fired (empty buffer path)
        mock_drain.assert_called_once_with( "abc12345" )
        mock_ask.assert_called_once()
        mock_emit.assert_called_once_with( {} )


# ═════════════════════════════════════════════════════════════════════════════
# TestBlockCounter (Phase 4)
# ═════════════════════════════════════════════════════════════════════════════

class TestBlockCounter:
    """Tests for stop block counter safety valve."""

    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_stop_block_count", return_value=3 )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_max_blocks_allows_stop( self, mock_read, mock_log, mock_session,
                                      mock_drain, mock_send, mock_emit, mock_get_count, mock_reset, mock_resolve ):
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

    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                           mock_get_count, mock_inc, mock_resolve ):
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

    @pytest.fixture( autouse=True )
    def _force_immediate_ask_path( self, monkeypatch ):
        """
        These tests exercise the legacy immediate-ask ("Anything else?") path.
        Reaching it now requires THREE conditions, all forced here for the class:
          1. The Thread A enum = "ask" — `_stop_hook_idle_behavior()` → "ask"
             (default is "idle_announce": v2.1 direct-state visibility owns
             liveness, so a no-poke Stop announces idle + allows the stop rather
             than asking). See 2026.06.06-heartbeat-poke-scaffold-vs-v2.1.
          2. The heartbeat does NOT poke — `_run_heartbeat()` → None (so Branch C
             falls through to the idle-behavior gate).
          3. idle_detection.enabled is False — so the "ask" path takes the
             immediate-ask branch (not the deferred waiter). After the 2026-04-29
             idle-aware landing, the ask only fires when this is False.
        """
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior",
            lambda: "ask"
        )
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.stop._run_heartbeat",
            lambda *a, **k: None
        )
        monkeypatch.setattr(
            "lupin_cli.claude_code.hooks.stop.load_idle_settings",
            lambda: { "enabled": False, "backoff_minutes": [ ] }
        )

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                         mock_reset, mock_summarize, mock_resolve, mock_gate ):
        """User says 'yes' → block with continuation reason."""
        mock_response = MagicMock()
        mock_response.response_value = "yes"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        assert "continue working" in emitted[ "reason" ]

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                                     mock_reset, mock_summarize, mock_resolve, mock_gate ):
        """Qualifier ending with '?' → injected via tmux, stop blocked."""
        mock_response = MagicMock()
        mock_response.response_value = "yes [comment: how many tests passed?]"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        mock_inject.assert_called_once_with( "abc12345", "how many tests passed?" )

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                                       mock_reset, mock_summarize, mock_resolve, mock_gate ):
        """Qualifier without '?' → injected via tmux, stop blocked."""
        mock_response = MagicMock()
        mock_response.response_value = "yes [comment: fix the linting errors]"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert emitted[ "decision" ] == "block"
        mock_inject.assert_called_once_with( "abc12345", "fix the linting errors" )

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                             mock_reset, mock_summarize, mock_resolve, mock_gate ):
        """When _summarize_task returns a gist, notification message includes it."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        request = mock_notify.call_args[ 0 ][ 0 ]
        assert "fixed linting errors" in request.message
        assert "I'm finished" in request.message

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                        mock_reset, mock_summarize, mock_resolve, mock_gate ):
        """When _summarize_task returns None, falls back to generic message."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        request = mock_notify.call_args[ 0 ][ 0 ]
        assert "finished the current task" in request.message

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                        mock_reset, mock_summarize, mock_resolve, mock_gate ):
        """User says plain 'no' → allow stop (emit {})."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                                          mock_reset, mock_summarize, mock_resolve, mock_gate ):
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

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                                        mock_reset, mock_summarize, mock_resolve, mock_gate ):
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

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                   mock_reset, mock_summarize, mock_resolve, mock_gate ):
        """Timeout (default 'no') → allow stop (emit {})."""
        mock_response = MagicMock()
        mock_response.response_value = "no"  # Default on timeout
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                        mock_reset, mock_tts, mock_resolve, mock_gate ):
        """Server error → allow stop gracefully (emit {})."""
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                                 mock_reset, mock_summarize, mock_resolve, mock_gate ):
        """Verify notify_user_sync is called with MEDIUM priority, 60s timeout, 'Stop hook: Anything else?' title."""
        mock_response = MagicMock()
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }

        main()

        # Verify the NotificationRequest was built correctly
        call_args = mock_notify.call_args
        request = call_args[ 0 ][ 0 ]  # First positional arg
        assert request.priority == NotificationPriority.MEDIUM
        assert request.timeout_seconds == 60
        assert request.response_default == "no"
        assert request.display_qualifier_widget is True
        assert request.title == "Stop hook: Anything else?"

    @patch( "lupin_cli.claude_code.hooks.stop._should_ask_anything_else", return_value=True )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
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
                                          mock_reset, mock_summarize, mock_resolve, mock_gate ):
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

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_wrap",
            side_effect=lambda text, **_kw: text )
    @patch( "subprocess.Popen" )
    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id" )
    def test_spawns_popen( self, mock_find, mock_popen, _mock_wrap ):
        """Valid session → spawns Popen with tmux send-keys command.

        Patches hook_common.speakerphone_wrap to identity so the assertion
        focuses on the bash-positional-args structure (security boundary),
        not the per-turn rider content (covered by test_speakerphone_wrap.py).
        """
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

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_wrap",
            side_effect=lambda text, **_kw: text )
    @patch( "subprocess.Popen" )
    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id" )
    def test_special_chars_safe( self, mock_find, mock_popen, _mock_wrap ):
        """Special chars in text → passed as separate positional arg, not embedded in shell.

        Patches hook_common.speakerphone_wrap to identity so the assertion
        targets the bash-positional-args injection boundary, not the per-turn
        rider content.
        """
        mock_find.return_value = { "tmux_session": "lupin", "session_id": "abc12345" }

        from lupin_cli.claude_code.hooks.lib.hook_common import inject_qualifier_via_tmux
        inject_qualifier_via_tmux( "abc12345", "it's a test; echo pwned" )

        mock_popen.assert_called_once()
        args = mock_popen.call_args[ 0 ][ 0 ]
        # Text is a separate positional arg ($3), NOT embedded in the shell string
        assert args[ 6 ] == "it's a test; echo pwned"
        # The shell command template does NOT contain the text
        assert "it's a test" not in args[ 2 ]
