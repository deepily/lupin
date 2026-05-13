"""
Integration-style tests for Phase 2 threading: each inbound text-injection
callsite invokes speakerphone_wrap (or speakerphone_reminder_block) with the
correct source label and session_id.

Per Phase 2 + Phase 5 of
src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md.

These are NOT full end-to-end tests of each hook — those would require
heavy fixture setup. Instead, each test mocks the helper, drives the
specific threading path, and asserts the helper was invoked correctly.
"""

import io
import json
import sys
from unittest.mock import patch, MagicMock

import pytest


# ── cc_notification_listener._inject_via_tmux ────────────────────────────────

class TestListenerTmuxInjectThreading:

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_wrap" )
    @patch( "lupin_cli.claude_code.hooks.lib.cc_notification_listener.subprocess.run" )
    def test_inject_via_tmux_calls_speakerphone_wrap( self, mock_run, mock_wrap ):
        """
        _inject_via_tmux must invoke speakerphone_wrap(text, source='voice',
        session_id=<hash>) before tmux send-keys.
        """
        from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener

        # speakerphone_wrap returns a marker we can verify was passed to tmux
        mock_wrap.return_value = "WRAPPED_OUTPUT_SENTINEL"

        listener = CCNotificationListener(
            session_id_hash = "abc12345",
            buffer_path     = "/tmp/test_buffer.jsonl",
            host            = "localhost",
            port            = 7999,
            email           = "test@example.com",
            password        = "test-pw",
        )

        # Force a tmux session resolution so injection proceeds
        listener._tmux_session = "test-tmux"

        listener._inject_via_tmux( "Hello, what's the status?" )

        # Assert wrap was called once with correct kwargs
        mock_wrap.assert_called_once()
        _, kwargs = mock_wrap.call_args
        assert kwargs[ "source" ] == "voice"
        assert kwargs[ "session_id" ] == "abc12345"
        # Positional arg: the message text
        assert mock_wrap.call_args[ 0 ][ 0 ] == "Hello, what's the status?"

        # Assert wrapped output was passed to tmux (not the raw text)
        # First subprocess.run call is the literal-text type
        type_call = mock_run.call_args_list[ 0 ]
        cmd_args = type_call[ 0 ][ 0 ]
        # tmux send-keys -t {session} -l {text} → text is at index 4
        assert "WRAPPED_OUTPUT_SENTINEL" in cmd_args


# ── inject_qualifier_via_tmux ────────────────────────────────────────────────

class TestInjectQualifierViaTmuxThreading:

    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id" )
    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_wrap" )
    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.subprocess.Popen" )
    def test_inject_qualifier_calls_speakerphone_wrap( self, mock_popen, mock_wrap, mock_find ):
        """
        inject_qualifier_via_tmux must invoke speakerphone_wrap(text,
        source='hook-idle-prompt', session_id=<sid>) before tmux send-keys.
        """
        from lupin_cli.claude_code.hooks.lib.hook_common import inject_qualifier_via_tmux

        # Resolve a tmux session via the bridge mock
        mock_find.return_value = { "tmux_session": "test-tmux" }
        mock_wrap.return_value  = "WRAPPED_QUALIFIER_SENTINEL"

        inject_qualifier_via_tmux(
            session_id = "sid-9999",
            text       = "actually fix the test"
        )

        # Wrap called with correct kwargs
        mock_wrap.assert_called_once()
        _, kwargs = mock_wrap.call_args
        assert kwargs[ "source" ] == "hook-idle-prompt"
        assert kwargs[ "session_id" ] == "sid-9999"
        assert mock_wrap.call_args[ 0 ][ 0 ] == "actually fix the test"

        # Wrapped output passed to subprocess.Popen
        popen_call = mock_popen.call_args
        cmd_list   = popen_call[ 0 ][ 0 ]
        # Look for our sentinel in the command list (it's $3 in the bash invocation)
        assert "WRAPPED_QUALIFIER_SENTINEL" in cmd_list


# ── user_prompt_submit speakerphone_reminder_block ───────────────────────────────

class TestUserPromptSubmitThreading:
    """
    Verify user_prompt_submit.main() invokes speakerphone_reminder_block with
    the correct source label, and combines its output with voice_ctx
    when both are present.

    The hook is driven via stdin JSON and reads many bridge helpers; these
    tests mock the heavy collaborators and verify the threading contract.
    """

    def _run_main_with_payload( self, payload_dict, mocks ):
        """Helper: invoke main() with a stdin payload and a stdout capture."""
        # Patch read_hook_input to return our payload directly (avoids stdin)
        mocks[ "read_hook_input" ].return_value = payload_dict

        # Capture emit_json output
        emitted = { }
        def _capture( data ):
            emitted[ "data" ] = data
        mocks[ "emit_json" ].side_effect = _capture

        from lupin_cli.claude_code.hooks import user_prompt_submit
        user_prompt_submit.main()

        return emitted.get( "data", { } )

    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.write_turn_start_marker" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.kill_idle_waiter" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.set_idle_detection_field" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.get_claude_session_id" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.resolve_stable_session_id" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.format_voice_context" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.enrich_voice_context" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.build_additional_context" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.speakerphone_reminder_block" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.emit_json" )
    def test_calls_reminder_block_with_terminal_typed_source(
        self,
        emit_json_m, read_input_m, log_m, reminder_m,
        build_ctx_m, enrich_m, format_voice_m,
        drain_m, resolve_m, get_sid_m,
        set_idle_m, kill_idle_m, write_marker_m
    ):
        # No voice messages → tests the terminal-typed-only branch
        drain_m.return_value      = [ ]
        format_voice_m.return_value = ""
        resolve_m.return_value    = "stable-sid-12345"
        get_sid_m.return_value    = "stable-sid-12345"
        reminder_m.return_value   = "REMINDER_BLOCK_SENTINEL"
        build_ctx_m.return_value  = { "additionalContext": "REMINDER_BLOCK_SENTINEL" }

        result = self._run_main_with_payload(
            { "session_id": "stable-sid-12345" },
            { "read_hook_input": read_input_m, "emit_json": emit_json_m }
        )

        # Reminder helper invoked with terminal-typed source + resolved session_id
        reminder_m.assert_called_once_with( "terminal-typed", "stable-sid-12345" )

        # When voice_ctx empty + reminder non-empty: emit additionalContext with reminder
        # (hook_event_name="UserPromptSubmit" required by Claude Code schema)
        build_ctx_m.assert_called_once_with( "REMINDER_BLOCK_SENTINEL", "UserPromptSubmit" )

    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.write_turn_start_marker" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.kill_idle_waiter" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.set_idle_detection_field" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.get_claude_session_id" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.resolve_stable_session_id" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.format_voice_context" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.enrich_voice_context" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.build_additional_context" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.speakerphone_reminder_block" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.emit_json" )
    def test_combines_voice_ctx_and_reminder_when_both_present(
        self,
        emit_json_m, read_input_m, log_m, reminder_m,
        build_ctx_m, enrich_m, format_voice_m,
        drain_m, resolve_m, get_sid_m,
        set_idle_m, kill_idle_m, write_marker_m
    ):
        # Voice messages present + speakerphone active → combine both
        drain_m.return_value      = [ { "msg": "test" } ]
        format_voice_m.return_value = "FORMATTED_VOICE"
        enrich_m.return_value     = "ENRICHED_VOICE"
        resolve_m.return_value    = "stable-sid-67890"
        get_sid_m.return_value    = "stable-sid-67890"
        reminder_m.return_value   = "REMINDER_BLOCK_SENTINEL"
        build_ctx_m.return_value  = { "additionalContext": "..." }

        result = self._run_main_with_payload(
            { "session_id": "stable-sid-67890" },
            { "read_hook_input": read_input_m, "emit_json": emit_json_m }
        )

        # Reminder called
        reminder_m.assert_called_once_with( "terminal-typed", "stable-sid-67890" )
        # additionalContext built from enriched + reminder concatenation
        build_ctx_m.assert_called_once()
        ctx_arg = build_ctx_m.call_args[ 0 ][ 0 ]
        assert "ENRICHED_VOICE" in ctx_arg
        assert "REMINDER_BLOCK_SENTINEL" in ctx_arg

    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.write_turn_start_marker" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.kill_idle_waiter" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.set_idle_detection_field" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.get_claude_session_id" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.resolve_stable_session_id" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.format_voice_context" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.enrich_voice_context" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.build_additional_context" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.speakerphone_reminder_block" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.read_hook_input" )
    @patch( "lupin_cli.claude_code.hooks.user_prompt_submit.emit_json" )
    def test_passes_through_when_no_voice_no_reminder(
        self,
        emit_json_m, read_input_m, log_m, reminder_m,
        build_ctx_m, enrich_m, format_voice_m,
        drain_m, resolve_m, get_sid_m,
        set_idle_m, kill_idle_m, write_marker_m
    ):
        # Notification mode (no reminder) + no voice → emit empty {}
        drain_m.return_value      = [ ]
        format_voice_m.return_value = ""
        resolve_m.return_value    = "stable-sid-11111"
        get_sid_m.return_value    = "stable-sid-11111"
        reminder_m.return_value   = ""

        self._run_main_with_payload(
            { "session_id": "stable-sid-11111" },
            { "read_hook_input": read_input_m, "emit_json": emit_json_m }
        )

        emit_json_m.assert_called_once_with( { } )
        # build_additional_context should NOT be invoked in this branch
        build_ctx_m.assert_not_called()
