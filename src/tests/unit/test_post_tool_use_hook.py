"""
Unit tests for the PostToolUse hook.

Tests cover:
    - Smart TTS: silent tool → no send_tts, announce tool → formatted, unknown → name-only
    - Voice drain called with correct session_id
    - Empty payload → immediate {}
    - Full main() flow with mocked I/O
    - Phase 4: additionalContext injection from drained messages
"""

import json
import sys
import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.post_tool_use import main


@pytest.fixture( autouse=True )
def _stub_bridge_touch():
    """
    Stub the v2.1 bridge-mtime liveness stamp for every test in this module.

    main() now calls touch_bridge_mtime() on every tool call (arbiter design
    `03` §10.1). Stubbing it keeps these unit tests free of real filesystem
    side effects (the stamp does a real os.utime against the resolved bridge)
    and lets the dedicated stamp test assert the call. Autouse so the existing
    tests inherit the stub without per-method decorators.
    """
    with patch( "lupin_cli.claude_code.hooks.post_tool_use.touch_bridge_mtime" ) as m:
        yield m


# ═════════════════════════════════════════════════════════════════════════════
# TestSmartTTS
# ═════════════════════════════════════════════════════════════════════════════

class TestSmartTTS:
    """Tests for smart TTS filtering in PostToolUse."""

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_silent_tool_no_tts( self, mock_read, mock_log, mock_session,
                                  mock_send, mock_drain, mock_emit, mock_resolve ):
        """Read tool (silent) does not send TTS."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : { "file_path": "/tmp/test.py" },
            "session_id" : "abc12345"
        }

        main()

        mock_send.assert_not_called()
        mock_drain.assert_called_once_with( "abc12345" )
        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_grep_silent( self, mock_read, mock_log, mock_session,
                           mock_send, mock_drain, mock_emit, mock_resolve ):
        """Grep tool (silent) does not send TTS."""
        mock_read.return_value = {
            "tool_name"  : "Grep",
            "tool_input" : { "pattern": "foo" },
            "session_id" : "abc12345"
        }

        main()

        mock_send.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_bash_announced_with_command( self, mock_read, mock_log, mock_session,
                                          mock_send, mock_drain, mock_emit, mock_resolve ):
        """Bash tool (announce) sends formatted TTS with command snippet."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "npm test" },
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Done: Bash: npm test"

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_write_announced_with_basename( self, mock_read, mock_log, mock_session,
                                             mock_send, mock_drain, mock_emit, mock_resolve ):
        """Write tool (announce) sends TTS with file basename."""
        mock_read.return_value = {
            "tool_name"  : "Write",
            "tool_input" : { "file_path": "/home/user/project/main.py" },
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Done: Write: main.py"

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_non_voice_mcp_tool_announced_name_only( self, mock_read, mock_log, mock_session,
                                                      mock_send, mock_drain, mock_emit, mock_resolve ):
        """Non-voice MCP/unknown tool sends TTS with name only."""
        mock_read.return_value = {
            "tool_name"  : "mcp__other-server__func",
            "tool_input" : { "param": "value" },
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Done: mcp__other-server__func"


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceDrain
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceDrain:
    """Tests for voice buffer drain in PostToolUse."""

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_send, mock_drain, mock_emit, mock_resolve ):
        """When payload has no session_id, falls back to session bridge."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "ls" }
            # No session_id key
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_drain_uses_payload_session_id( self, mock_read, mock_log, mock_session,
                                             mock_send, mock_drain, mock_emit, mock_resolve ):
        """Drain uses session_id from payload when available."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : {},
            "session_id" : "payload99"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "payload99" )


# ═════════════════════════════════════════════════════════════════════════════
# TestEmptyPayload
# ═════════════════════════════════════════════════════════════════════════════

class TestEmptyPayload:
    """Tests for empty payload handling."""

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input", return_value={} )
    def test_empty_payload_emits_empty( self, mock_read, mock_emit ):
        """Empty payload immediately emits {} and exits."""
        with pytest.raises( SystemExit ):
            main()

        mock_emit.assert_called_once_with( {} )


# ═════════════════════════════════════════════════════════════════════════════
# TestContextInjection (Phase 4)
# ═════════════════════════════════════════════════════════════════════════════

class TestContextInjection:
    """Tests for additionalContext injection from drained voice messages."""

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_drained_messages_emit_additional_context( self, mock_read, mock_log, mock_session,
                                                        mock_send, mock_drain, mock_emit, mock_resolve ):
        """Drained messages emit hookSpecificOutput.additionalContext."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "ls" },
            "session_id" : "abc12345"
        }
        mock_drain.return_value = [ { "message": "also check the tests" } ]

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        assert "hookSpecificOutput" in emitted
        assert "[Voice]: also check the tests" in emitted[ "hookSpecificOutput" ][ "additionalContext" ]

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_no_messages_emit_empty( self, mock_read, mock_log, mock_session,
                                      mock_send, mock_drain, mock_emit, mock_resolve ):
        """No drained messages emits {} (passthrough)."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "ls" },
            "session_id" : "abc12345"
        }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_multiple_messages_joined( self, mock_read, mock_log, mock_session,
                                        mock_send, mock_drain, mock_emit, mock_resolve ):
        """Multiple drained messages are joined with newlines in additionalContext."""
        mock_read.return_value = {
            "tool_name"  : "Write",
            "tool_input" : { "file_path": "/tmp/foo.py" },
            "session_id" : "abc12345"
        }
        mock_drain.return_value = [
            { "message": "first thing" },
            { "message": "second thing" }
        ]

        main()

        emitted = mock_emit.call_args[ 0 ][ 0 ]
        ctx     = emitted[ "hookSpecificOutput" ][ "additionalContext" ]
        assert "[Voice]: first thing" in ctx
        assert "[Voice]: second thing" in ctx
        assert "\n" in ctx


# ═════════════════════════════════════════════════════════════════════════════
# TestBridgeLivenessStamp (v2.1 direct-state visibility — arbiter design 03 §10.1)
# ═════════════════════════════════════════════════════════════════════════════

class TestBridgeLivenessStamp:
    """The PostToolUse bridge-mtime stamp (single hook, C3) fires per tool call."""

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_touch_fires_once_per_tool_call( self, mock_read, mock_log, mock_session,
                                             mock_send, mock_drain, mock_emit, mock_resolve,
                                             _stub_bridge_touch ):
        """A normal tool call bumps the bridge mtime exactly once."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : { "file_path": "/tmp/test.py" },
            "session_id" : "abc12345"
        }

        main()

        _stub_bridge_touch.assert_called_once_with()

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    def test_no_touch_on_empty_payload( self, mock_emit, mock_read, _stub_bridge_touch ):
        """An empty payload exits before the stamp — no liveness lie on a no-op turn."""
        with pytest.raises( SystemExit ):
            main()

        _stub_bridge_touch.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# TestCosaVoiceIdleReset (covers the mcp__cosa-voice__ idle-waiter branch)
# ═════════════════════════════════════════════════════════════════════════════

class TestCosaVoiceIdleReset:
    """A cosa-voice tool kills the pending idle waiter + bumps last_interaction_at."""

    @patch( "lupin_cli.claude_code.hooks.post_tool_use.set_idle_detection_field" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.kill_idle_waiter" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input" )
    def test_cosa_voice_tool_resets_idle( self, mock_read, mock_log, mock_session,
                                          mock_send, mock_drain, mock_emit, mock_resolve,
                                          mock_kill, mock_set_field ):
        """A cosa-voice notify/ask kills the idle waiter and stamps last_interaction_at."""
        mock_read.return_value = {
            "tool_name"  : "mcp__cosa-voice__notify",
            "tool_input" : { "message": "hi" },
            "session_id" : "abc12345"
        }

        main()

        mock_kill.assert_called_once_with( "abc12345" )
        assert mock_set_field.call_count == 1
        # session_id positional + a last_interaction_at ISO string keyword
        assert mock_set_field.call_args[ 0 ][ 0 ] == "abc12345"
        assert "last_interaction_at" in mock_set_field.call_args[ 1 ]


class TestTaskStoreMirrorSeam:
    """Phase-2 write path: Task* events route to the task-store mirror."""

    @staticmethod
    def _run( tool_name, mirror_mock ):
        payload = {
            "tool_name"     : tool_name,
            "tool_input"    : { "subject": "s" },
            "tool_response" : { "task": { "id": "1" } },
            "session_id"    : "abc12345",
        }
        with patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input", return_value=payload ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" ), \
             patch( "lupin_cli.claude_code.hooks.lib.task_store_mirror.mirror_task_tool_event", mirror_mock ):
            main()
        return payload

    @pytest.mark.parametrize( "tool_name", [ "TaskCreate", "TaskUpdate" ] )
    def test_task_tools_route_to_mirror( self, tool_name ):
        mirror = MagicMock( return_value={ "action": "disabled" } )
        payload = self._run( tool_name, mirror )
        mirror.assert_called_once_with( payload, "abc12345" )

    @pytest.mark.parametrize( "tool_name", [ "TaskGet", "TaskList", "Read", "Bash" ] )
    def test_non_task_write_tools_do_not_touch_the_mirror( self, tool_name ):
        mirror = MagicMock()
        self._run( tool_name, mirror )
        mirror.assert_not_called()


class TestTaskTransitionProgressBeacon:
    """
    Arbiter signs-of-life Fix 2: a task-store WRITE (harness OR MCP) emits ONE
    kind="task_transition" fleet PROGRESS beacon; non-write tools emit nothing.
    """

    @staticmethod
    def _run( tool_name, emit_mock ):
        payload = {
            "tool_name"     : tool_name,
            "tool_input"    : { "subject": "s" },
            "tool_response" : { "task": { "id": "1" } },
            "session_id"    : "abc12345",
        }
        with patch( "lupin_cli.claude_code.hooks.post_tool_use.read_hook_input", return_value=payload ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.get_claude_session_id", return_value="abc12345" ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.send_tts" ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.drain_and_acknowledge", return_value=[] ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.emit_json" ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.kill_idle_waiter" ), \
             patch( "lupin_cli.claude_code.hooks.post_tool_use.set_idle_detection_field" ), \
             patch( "lupin_cli.claude_code.hooks.lib.task_store_mirror.mirror_task_tool_event", MagicMock() ), \
             patch( "lupin_cli.claude_code.hooks.lib.heartbeat_events.emit_task_transition", emit_mock ):
            main()

    @pytest.mark.parametrize( "tool_name", [
        "TaskCreate", "TaskUpdate",
        "mcp__cosa-voice__task_create", "mcp__cosa-voice__task_transition",
    ] )
    def test_task_store_writes_emit_progress_beacon( self, tool_name ):
        """Every task-store WRITE — harness AND MCP — emits one beacon for the session."""
        emit = MagicMock( return_value=True )
        self._run( tool_name, emit )
        emit.assert_called_once_with( "abc12345" )

    @pytest.mark.parametrize( "tool_name", [
        "TaskGet", "TaskList", "Read", "Bash", "mcp__cosa-voice__notify",
    ] )
    def test_non_write_tools_emit_no_progress_beacon( self, tool_name ):
        """Reads, non-task tools, and other MCP verbs must NOT emit a progress beacon."""
        emit = MagicMock()
        self._run( tool_name, emit )
        emit.assert_not_called()
