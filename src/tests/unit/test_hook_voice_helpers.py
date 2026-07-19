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
    build_peer_dm_reminder,
    is_injected_peer_dm,
    PEER_DM_FRAME_PREFIX,
    enrich_voice_context,
    deliver_pending_peer_dms,
    inject_qualifier_via_tmux,
    MAX_STOP_BLOCKS,
    MCP_VOICE_PREFIX,
    VOICE_LINE_PREFIX,
    VOICE_ACK_RIDER,
    BREVITY_TAG,
    PEER_DM_BREVITY_RIDER,
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


# ═════════════════════════════════════════════════════════════════════════════
# TestBuildPeerDmReminder — §6a peer-DM framing (notification-native AI↔AI)
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildPeerDmReminder:
    """Tests for build_peer_dm_reminder() — the SINGLE source of peer-DM framing."""

    def test_full_envelope( self ):
        """Full envelope: system-reminder wrapper, persona+icon label, ids, body, reply affordance."""
        r = build_peer_dm_reminder(
            "Build is green, ready for review.",
            persona="maría", icon="🌸", msg_id="m-1", thread_id="t-1"
        )
        assert r.startswith( "<system-reminder>" )
        assert r.endswith( "</system-reminder>" )
        assert "PEER DM from maría 🌸" in r
        assert "message_id m-1" in r
        assert "thread t-1" in r
        assert "Build is green, ready for review." in r
        # dm_send reply affordance threads via reply_to + thread_id
        assert 'dm_send( recipient="maría"' in r
        assert 'reply_to="m-1"' in r
        assert 'thread_id="t-1"' in r

    def test_persona_fallback( self ):
        """Missing persona falls back to 'a peer session' — in label AND reply affordance."""
        r = build_peer_dm_reminder( "body", persona=None )
        assert "PEER DM from a peer session" in r
        assert 'recipient="a peer session"' in r

    def test_icon_id_thread_fallbacks_to_empty( self ):
        """Missing icon/msg_id/thread_id degrade to empty strings (no 'None' leakage)."""
        r = build_peer_dm_reminder( "body", persona="maría", icon=None, msg_id=None, thread_id=None )
        # icon empty → label is just the persona (no trailing space)
        assert "PEER DM from maría (message_id , thread ):" in r
        assert "None" not in r

    def test_no_voice_rider_strings( self ):
        """A peer DM is NOT human voice — none of the speakerphone/TTS rider language."""
        r       = build_peer_dm_reminder( "body", persona="maría", icon="🌸", msg_id="m1", thread_id="t1" )
        lowered = r.lower()
        assert "user spoke"   not in lowered
        assert "speakerphone" not in lowered
        assert "notify("      not in r
        assert "tts"          not in lowered

    def test_one_way_omits_reply_affordance( self ):
        """bug 8894e597: one_way=True (arbiter-authored advisory) → NO dm_send reply
        affordance (the arbiter has no inbox — bug 9694fb11), replaced by the honest
        one-way notice naming resumed work as the acknowledgment. Header + body intact."""
        r = build_peer_dm_reminder(
            "you appear STUCK — status?", persona="heartbeat-arbiter", icon="🛰️",
            msg_id="m-1", thread_id="t-1", one_way=True,
        )
        # still a framed peer-DM block with the header + body
        assert r.startswith( "<system-reminder>" ) and r.endswith( "</system-reminder>" )
        assert "PEER DM from heartbeat-arbiter 🛰️" in r
        assert "you appear STUCK — status?" in r
        # the FALSE reply affordance is gone
        assert "dm_send" not in r
        assert "Reply via" not in r
        # the honest one-way signal path is present
        assert "ONE-WAY" in r and "no inbox" in r
        assert "resuming work" in r and "acknowledgment" in r

    def test_default_stays_bidirectional_when_one_way_false( self ):
        """Regression guard: the DEFAULT (one_way=False) still emits the dm_send
        affordance — genuine peer DMs are untouched by the 8894e597 arbiter variant."""
        r = build_peer_dm_reminder( "body", persona="maría", icon="🌸", msg_id="m1", thread_id="t1" )
        assert 'dm_send( recipient="maría"' in r
        assert "ONE-WAY" not in r


# ═════════════════════════════════════════════════════════════════════════════
# TestFormatVoiceContextPeerDm — §6a ai_to_ai branch of format_voice_context
# ═════════════════════════════════════════════════════════════════════════════

class TestFormatVoiceContextPeerDm:
    """Tests for the direction=='ai_to_ai' branch of format_voice_context()."""

    def test_ai_to_ai_becomes_peer_block_not_voice_line( self ):
        """An ai_to_ai entry renders as a peer-DM block — NOT a '[Voice]:' line."""
        msgs = [ {
            "message"        : "peer hello",
            "direction"      : "ai_to_ai",
            "sender_persona" : "maría",
            "sender_icon"    : "🌸",
            "notification_id": "m1",
            "thread_id"      : "t1",
        } ]
        result = format_voice_context( msgs )
        assert result.startswith( "<system-reminder>" )
        assert VOICE_LINE_PREFIX not in result
        assert "PEER DM from maría 🌸" in result
        assert "peer hello" in result

    def test_mixed_voice_and_dm( self ):
        """A mixed buffer yields a [Voice]: line AND a peer-DM block, newline-joined."""
        msgs = [
            { "message": "spoke this", "direction": "human_to_ai" },
            { "message": "dm body", "direction": "ai_to_ai", "sender_persona": "maría" },
        ]
        result = format_voice_context( msgs )
        assert f"{VOICE_LINE_PREFIX}spoke this" in result
        assert "PEER DM from maría" in result

    def test_blank_ai_to_ai_skipped( self ):
        """A whitespace-only ai_to_ai body is skipped (no empty peer block)."""
        msgs = [ { "message": "   ", "direction": "ai_to_ai", "sender_persona": "maría" } ]
        assert format_voice_context( msgs ) == ""

    def test_notification_id_preferred_over_id( self ):
        """notification_id wins when both present (the buffer's canonical id key)."""
        msgs = [ {
            "message"        : "body",
            "direction"      : "ai_to_ai",
            "sender_persona" : "maría",
            "notification_id": "nid",
            "id"             : "other",
        } ]
        result = format_voice_context( msgs )
        assert "message_id nid" in result
        assert "other" not in result

    def test_id_fallback_when_no_notification_id( self ):
        """Falls back to the 'id' key when notification_id is absent."""
        msgs = [ {
            "message"        : "body",
            "direction"      : "ai_to_ai",
            "sender_persona" : "maría",
            "id"             : "fallback-id",
        } ]
        result = format_voice_context( msgs )
        assert "fallback-id" in result


# ═════════════════════════════════════════════════════════════════════════════
# TestEnrichVoiceContext — §6a pure-DM skip of the voice-acknowledge rider
# ═════════════════════════════════════════════════════════════════════════════

class TestEnrichVoiceContext:
    """Tests for enrich_voice_context() — rider decided STRUCTURALLY from message direction (§6a, F2)."""

    def test_empty_passthrough( self ):
        """Empty input returns empty (passthrough)."""
        assert enrich_voice_context( "", [] ) == ""

    def test_pure_peer_dm_unchanged_no_rider( self ):
        """A pure peer-DM context (all ai_to_ai messages) is returned UNCHANGED — no TTS rider."""
        msgs     = [ { "message": "body", "direction": "ai_to_ai", "sender_persona": "maría" } ]
        dm_block = format_voice_context( msgs )
        result   = enrich_voice_context( dm_block, msgs )
        assert result == dm_block
        assert VOICE_ACK_RIDER not in result

    def test_voice_only_keeps_rider( self ):
        """A voice-only context (a human_to_ai message) keeps the notify()-acknowledge rider."""
        msgs   = [ { "message": "hello", "direction": "human_to_ai" } ]
        ctx    = format_voice_context( msgs )
        result = enrich_voice_context( ctx, msgs )
        assert result.startswith( f"{VOICE_LINE_PREFIX}hello" )
        assert VOICE_ACK_RIDER in result

    def test_mixed_voice_and_dm_keeps_rider( self ):
        """A mixed context (voice + DM) keeps the rider — the voice line still needs it."""
        msgs = [
            { "message": "spoke this", "direction": "human_to_ai" },
            { "message": "dm body", "direction": "ai_to_ai", "sender_persona": "maría" },
        ]
        result = enrich_voice_context( format_voice_context( msgs ), msgs )
        assert VOICE_ACK_RIDER in result

    def test_messages_none_defaults_to_no_rider( self ):
        """messages=None is the §6a-safe default — never attach the human rider blindly."""
        result = enrich_voice_context( f"{VOICE_LINE_PREFIX}hello" )
        assert result == f"{VOICE_LINE_PREFIX}hello"
        assert VOICE_ACK_RIDER not in result

    def test_blank_human_voice_does_not_count_as_voice( self ):
        """A BLANK human_to_ai message contributes no [Voice]: line → structurally
        not voice → a context that renders only a peer DM gets NO rider."""
        msgs = [
            { "message": "   ", "direction": "human_to_ai" },          # blank → skipped
            { "message": "dm body", "direction": "ai_to_ai", "sender_persona": "maría" },
        ]
        ctx    = format_voice_context( msgs )   # only the DM block renders
        result = enrich_voice_context( ctx, msgs )
        assert VOICE_ACK_RIDER not in result

    def test_f2_voice_marker_inside_dm_body_no_rider( self ):
        """
        F2 REGRESSION (Cheech 2026-06-15): a peer DM whose BODY literally contains
        "[Voice]: " must NOT trigger the human-voice rider. The old substring sniff
        leaked the rider here; the structural direction check does not.
        """
        msgs   = [ {
            "message"        : "the reviewer wrote [Voice]: do X — please action",
            "direction"      : "ai_to_ai",
            "sender_persona" : "maría",
        } ]
        ctx    = format_voice_context( msgs )
        assert VOICE_LINE_PREFIX in ctx          # the substring IS present in the body…
        result = enrich_voice_context( ctx, msgs )
        assert VOICE_ACK_RIDER not in result  # …but structurally it's a pure peer DM → NO rider
        assert result == ctx


# ═════════════════════════════════════════════════════════════════════════════
# TestBrevityRiders — Rick's brevity mandate, 2026-07-19 (tasks 6a3941b8 + 314671cd)
# ═════════════════════════════════════════════════════════════════════════════

class TestBrevityRiders:
    """The brevity tag rides both injection surfaces — voice-ack and peer-DM."""

    def test_voice_ack_rider_carries_brevity_tag( self ):
        """The STT/voice rider carries the tag (task 6a3941b8)."""
        assert BREVITY_TAG in VOICE_ACK_RIDER

    def test_voice_ack_rider_stays_under_byte_ceiling( self ):
        """
        The ratchet (Maria's net-smaller constraint): this rider is appended to EVERY
        spoken utterance, so its byte cost is a standing budget, not a one-time choice.
        The pre-brevity-mandate rider was 325 chars; folding the tag in had to make the
        payload SMALLER, not bigger. 260 leaves trim headroom without licensing regrowth.
        """
        assert len( VOICE_ACK_RIDER ) < 260, (
            f"voice rider grew to {len( VOICE_ACK_RIDER )} chars — it rides every "
            f"utterance; trim it rather than raising this ceiling"
        )

    def test_escape_clause_wording_is_asked_not_content_requires( self ):
        """
        LOAD-BEARING (Rick's amendment): the exception must read "ONLY WHEN ASKED".
        "when the content requires it" was drafted and rejected the same hour — a
        self-assessed exception hands length-discretion back to the verbose author,
        which makes the rule a receipt instead of a control.
        """
        assert "ONLY WHEN ASKED" in BREVITY_TAG
        assert "content requires" not in BREVITY_TAG.lower()

    def test_peer_dm_reply_affordance_carries_brevity_rider( self ):
        """A bidirectional peer DM carries the rider (task 314671cd)."""
        block = build_peer_dm_reminder( "status?", persona="maría", icon="🌸",
                                        msg_id="m1", thread_id="t1" )
        assert PEER_DM_BREVITY_RIDER in block
        assert "dm_send(" in block

    def test_one_way_advisory_suppresses_brevity_rider( self ):
        """
        An arbiter one-way advisory takes NO reply (bug 8894e597), so a rider that
        shapes replies is pure byte cost — suppressed.
        """
        block = build_peer_dm_reminder( "poke", persona="arbiter", one_way=True )
        assert PEER_DM_BREVITY_RIDER not in block
        assert BREVITY_TAG not in block
        assert "ONE-WAY advisory" in block

    def test_riders_share_one_tag_constant_no_drift( self ):
        """Both surfaces derive from ONE tag — never re-typed literals (46a17f5a)."""
        assert BREVITY_TAG in VOICE_ACK_RIDER
        assert BREVITY_TAG in PEER_DM_BREVITY_RIDER


# ═════════════════════════════════════════════════════════════════════════════
# TestDeliverPendingPeerDms — §6 buffer-drain + tmux delivery of peer DMs
# ═════════════════════════════════════════════════════════════════════════════

class TestDeliverPendingPeerDms:
    """Tests for deliver_pending_peer_dms() — drain buffer, tmux-deliver DMs, return voice."""

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.inject_qualifier_via_tmux" )
    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.drain_voice_buffer" )
    def test_injects_each_ai_to_ai_wrap_false( self, mock_drain, mock_inject ):
        """Each ai_to_ai entry is tmux-injected verbatim (wrap=False), framed as a peer DM."""
        mock_drain.return_value = [
            { "message": "dm one", "direction": "ai_to_ai", "sender_persona": "maría",
              "sender_icon": "🌸", "notification_id": "m1", "thread_id": "t1" },
            { "message": "dm two", "direction": "ai_to_ai", "sender_persona": "john", "id": "m2" },
        ]
        result = deliver_pending_peer_dms( "abc12345" )

        assert result == []                       # no voice messages
        assert mock_inject.call_count == 2
        for call in mock_inject.call_args_list:
            assert call.kwargs.get( "wrap" ) is False
            assert call.args[ 0 ] == "abc12345"   # session_id threaded through
        # First injected block carries the framed body + persona
        first_text = mock_inject.call_args_list[ 0 ].args[ 1 ]
        assert "dm one" in first_text and "maría" in first_text
        # Second uses the id fallback (no notification_id)
        second_text = mock_inject.call_args_list[ 1 ].args[ 1 ]
        assert "message_id m2" in second_text

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.inject_qualifier_via_tmux" )
    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.drain_voice_buffer" )
    def test_returns_voice_messages_not_injected( self, mock_drain, mock_inject ):
        """Non-DM (voice) entries are returned for the caller, NOT tmux-delivered here."""
        voice = { "message": "spoke this", "direction": "human_to_ai" }
        mock_drain.return_value = [
            voice,
            { "message": "dm body", "direction": "ai_to_ai", "sender_persona": "maría" },
        ]
        result = deliver_pending_peer_dms( "abc12345" )
        assert result == [ voice ]
        assert mock_inject.call_count == 1

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.inject_qualifier_via_tmux" )
    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.drain_voice_buffer" )
    def test_blank_body_ai_to_ai_skipped( self, mock_drain, mock_inject ):
        """A whitespace-only ai_to_ai body is skipped — no injection, not returned."""
        mock_drain.return_value = [ { "message": "   ", "direction": "ai_to_ai", "sender_persona": "maría" } ]
        result = deliver_pending_peer_dms( "abc12345" )
        assert result == []
        mock_inject.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.inject_qualifier_via_tmux" )
    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.drain_voice_buffer",
            side_effect=Exception( "drain boom" ) )
    def test_drain_exception_returns_empty( self, mock_drain, mock_inject ):
        """A drain failure returns [] and never injects (self-isolating)."""
        result = deliver_pending_peer_dms( "abc12345" )
        assert result == []
        mock_inject.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# TestInjectQualifierWrapParam — §6a wrap=False verbatim path + isolation
# ═════════════════════════════════════════════════════════════════════════════

class TestInjectQualifierWrapParam:
    """Tests for the wrap param + defensive branches of inject_qualifier_via_tmux()."""

    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_wrap" )
    @patch( "subprocess.Popen" )
    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id" )
    def test_wrap_false_skips_speakerphone_wrap( self, mock_find, mock_popen, mock_wrap ):
        """wrap=False injects the text VERBATIM — speakerphone_wrap is never called (§6a peer DM)."""
        mock_find.return_value = { "tmux_session": "lupin" }
        block = "<system-reminder>\nPEER DM from maría\n</system-reminder>"

        inject_qualifier_via_tmux( "abc12345", block, wrap=False )

        mock_wrap.assert_not_called()
        mock_popen.assert_called_once()
        assert mock_popen.call_args[ 0 ][ 0 ][ 6 ] == block   # $3 = verbatim text

    @patch( "subprocess.Popen" )
    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id" )
    def test_no_tmux_session_in_bridge_skips( self, mock_find, mock_popen ):
        """Bridge data without a tmux_session key → skip (no Popen), no exception."""
        mock_find.return_value = { "session_id": "abc12345" }   # no tmux_session
        inject_qualifier_via_tmux( "abc12345", "text" )
        mock_popen.assert_not_called()

    @patch( "subprocess.Popen" )
    @patch( "lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_wrap",
            side_effect=RuntimeError( "wrap boom" ) )
    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id" )
    def test_wrap_exception_falls_through_with_raw_text( self, mock_find, mock_wrap, mock_popen ):
        """A speakerphone_wrap failure is non-fatal — falls through with the raw text."""
        mock_find.return_value = { "tmux_session": "lupin" }
        inject_qualifier_via_tmux( "abc12345", "raw text", wrap=True )
        mock_popen.assert_called_once()
        assert mock_popen.call_args[ 0 ][ 0 ][ 6 ] == "raw text"

    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id",
            side_effect=RuntimeError( "bridge boom" ) )
    def test_outer_exception_swallowed( self, mock_find ):
        """An error resolving the session is swallowed (hook must never crash CC)."""
        inject_qualifier_via_tmux( "abc12345", "text" )   # must not raise


# ═════════════════════════════════════════════════════════════════════════════
# TestIsInjectedPeerDm — bug d0d7f068 Part 2 (option C): the peer-DM inject
# predicate the Stop-hook poke-cap reset guard uses to NOT treat a DM/tap as
# genuine user re-engagement. Matched via the SHARED PEER_DM_FRAME_PREFIX.
# ═════════════════════════════════════════════════════════════════════════════

class TestIsInjectedPeerDm:
    def test_true_on_build_peer_dm_reminder_envelope( self ):
        """A real build_peer_dm_reminder envelope (the SINGLE source of framing) is
        recognized — derived from the shared constant, no re-typed literal."""
        dm = build_peer_dm_reminder( "where are we on X?", persona="mr radio", icon="🦉",
                                     msg_id="m1", thread_id="t1" )
        assert PEER_DM_FRAME_PREFIX in dm                 # frame really is present
        assert is_injected_peer_dm( dm ) is True

    def test_false_on_genuine_user_prompt( self ):
        """Real user typing carries no peer-DM frame → resets the cap (re-engagement)."""
        assert is_injected_peer_dm( "please fix the failing test" ) is False

    def test_false_on_non_string( self ):
        """Foreign hook-payload data (None / non-str) → False, never raises."""
        assert is_injected_peer_dm( None ) is False
        assert is_injected_peer_dm( { "prompt": "x" } ) is False
