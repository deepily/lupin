"""
A peer DM arriving mid-turn must not deny a tool call — row bb1a9062.

THE DEFECT. The PreToolUse hook drains this session's message buffer before every
tool call. That buffer carries BOTH kinds of inbound line: a human voice line and a
peer DM between seats. The hook denied the tool call whenever the drain rendered
ANY content, with the fixed reason "A user-initiated voice message was received" —
so a DM from a peer, or from the context tick, blocked the call and named the user
as the cause. Measured on the row: 29 of 30 interrupted tool results had a peer DM
delivered within ±5 s, against a 5.4% baseline; one seat logged 19 of 19.

THE FIELD THAT TELLS THEM APART is `direction` on each buffered line. The listener
writes it (`cc_notification_listener._buffer_message`): "ai_to_ai" for a peer DM,
defaulting to "human_to_ai" otherwise. `hook_common._context_has_human_voice` reads
it structurally — never by sniffing the rendered text for "[Voice]: ".

⚠️ WHY THESE TESTS DO NOT MOCK THE FORMATTER OR THE DENY BUILDER. The older
`_run` driver in test_pre_tool_use_hook.py patches `format_voice_context` and
`build_voice_deny_response` to arm the guards one at a time, and `format_voice_context`
returns a string with no idea what kind of line produced it. A test at that altitude
cannot see this defect: it enters where a real buffer line, carrying its real
`direction`, is rendered and judged. So only the buffer drain and the side-effecting
seams are stubbed here; the rendering and the decision run for real.
"""

import contextlib
import json

from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks import pre_tool_use as ptu
from lupin_cli.claude_code.hooks.lib.hook_common import (
    PEER_DM_FRAME_PREFIX, VOICE_ACK_RIDER, VOICE_LINE_PREFIX,
)


MODULE = "lupin_cli.claude_code.hooks.pre_tool_use"
GOV    = "lupin_cli.claude_code.hooks.lib.subagent_governance"
STASH  = "lupin_cli.claude_code.hooks.lib.stash_guard"
KILL   = "lupin_cli.claude_code.hooks.lib.kill_guard"
SCOPE  = "lupin_cli.claude_code.hooks.lib.commit_scope_guard"
MERGE  = "lupin_cli.claude_code.hooks.lib.merge_head_guard"

USER_VOICE_REASON = "user-initiated voice message"


def _peer_dm( body, persona="maria", icon="🌸", notification_id="n-1", thread_id="t-1" ):
    """A buffer line shaped exactly as the listener writes a peer DM."""
    return {
        "message"         : body,
        "priority"        : "normal",
        "job_id"          : "c129172c",
        "sender_id"       : "claude.code@lupin.deepily.ai#abe7d752",
        "notification_id" : notification_id,
        "direction"       : "ai_to_ai",
        "sender_persona"  : persona,
        "sender_icon"     : icon,
        "reply_to"        : None,
        "thread_id"       : thread_id,
    }


def _voice( body ):
    """A buffer line shaped as the listener writes a human-direction message."""
    return {
        "message"         : body,
        "priority"        : "normal",
        "job_id"          : "c129172c",
        "sender_id"       : "",
        "notification_id" : "v-1",
        "direction"       : "human_to_ai",
        "sender_persona"  : None,
        "sender_icon"     : None,
        "reply_to"        : None,
        "thread_id"       : None,
    }


def _run( messages, notice=None ):
    """
    Drive the real hook main() over a buffer of `messages`.

    Requires:
        - messages is a list of buffer-line dicts
        - notice is a commit-scope notice string, or None

    Ensures:
        - every guard ahead of the drain is silent, so only the drain decides
        - format_voice_context, _context_has_human_voice, build_voice_deny_response
          and the notice builder all run UNMOCKED
        - returns the single dict the hook emitted
    """
    payload = { "session_id": "s1", "tool_name": "Bash", "tool_input": { "command": "ls" } }
    verdict = MagicMock( deny_reason=None, notice=notice )
    emit    = MagicMock()

    with contextlib.ExitStack() as stack:
        def _p( *args, **kwargs ):
            return stack.enter_context( patch( *args, **kwargs ) )

        _p( f"{MODULE}.read_hook_input", return_value=payload )
        _p( f"{MODULE}.log_payload" )
        _p( f"{MODULE}.touch_bridge_mtime" )
        _p( f"{MODULE}.resolve_stable_session_id", return_value="s1" )
        _p( f"{MODULE}.get_claude_session_id", return_value="s1" )
        _p( f"{GOV}.subagent_deny_reason", return_value=None )
        _p( f"{STASH}.stash_deny_reason", return_value=None )
        _p( f"{KILL}.kill_deny_reason", return_value=None )
        _p( f"{MERGE}.merge_head_deny_reason", return_value=None )
        _p( f"{SCOPE}.evaluate_commit_scope", return_value=verdict )
        _p( f"{MODULE}.drain_and_acknowledge", return_value=messages )
        _p( f"{MODULE}.emit_json", emit )

        ptu.main()

    emit.assert_called_once()
    return emit.call_args.args[ 0 ]


class TestAPeerDmDoesNotDeny:

    def test_a_buffer_holding_only_a_peer_dm_does_not_deny( self ):
        out = _run( [ _peer_dm( "review approved — merge when green" ) ] )
        assert "permissionDecision" not in out[ "hookSpecificOutput" ]

    def test_the_peer_dm_is_still_delivered_as_additional_context( self ):
        out = _run( [ _peer_dm( "review approved — merge when green" ) ] )
        spec = out[ "hookSpecificOutput" ]
        assert spec[ "hookEventName" ] == "PreToolUse"
        assert "review approved — merge when green" in spec[ "additionalContext" ]
        assert f"{PEER_DM_FRAME_PREFIX}maria 🌸" in spec[ "additionalContext" ]

    def test_a_peer_dm_never_names_the_user_as_the_cause( self ):
        out = _run( [ _peer_dm( "status?" ) ] )
        assert USER_VOICE_REASON not in json.dumps( out )

    def test_a_peer_dm_carries_no_voice_acknowledge_rider( self ):
        out = _run( [ _peer_dm( "status?" ) ] )
        assert VOICE_ACK_RIDER not in out[ "hookSpecificOutput" ][ "additionalContext" ]

    def test_several_peer_dms_including_the_context_tick_do_not_deny( self ):
        """The context tick is a system DM with no persona seat behind it (row
        evidence, María's instance 3 and Mr. Radio's instance 7)."""
        out = _run( [
            _peer_dm( "over your context budget — 51.5%", persona=None, icon=None, notification_id="n-2" ),
            _peer_dm( "rio here, arm 2 is green", persona="rio", icon="⚡", notification_id="n-3" ),
        ] )
        spec = out[ "hookSpecificOutput" ]
        assert "permissionDecision" not in spec
        assert "over your context budget — 51.5%" in spec[ "additionalContext" ]
        assert "rio here, arm 2 is green" in spec[ "additionalContext" ]

    def test_the_decision_reads_direction_not_the_text( self ):
        """A DM body that literally contains the voice marker is still a DM."""
        out = _run( [ _peer_dm( f"quoting the hook: {VOICE_LINE_PREFIX}stop everything" ) ] )
        assert "permissionDecision" not in out[ "hookSpecificOutput" ]

    def test_a_blank_voice_line_beside_a_peer_dm_does_not_deny( self ):
        """A blank human-direction line renders nothing, so nothing human was said."""
        out = _run( [ _voice( "   " ), _peer_dm( "status?" ) ] )
        assert "permissionDecision" not in out[ "hookSpecificOutput" ]


class TestHumanVoiceStillTakesPrecedence:
    """The control arm: without these, "never denies" would pass on a hook that
    stopped denying anything at all."""

    def test_a_human_voice_message_denies_the_tool_call( self ):
        out  = _run( [ _voice( "stop, wrong branch" ) ] )
        spec = out[ "hookSpecificOutput" ]
        assert spec[ "permissionDecision" ] == "deny"
        assert USER_VOICE_REASON in spec[ "permissionDecisionReason" ]
        assert f"{VOICE_LINE_PREFIX}stop, wrong branch" in spec[ "additionalContext" ]
        assert VOICE_ACK_RIDER in spec[ "additionalContext" ]

    def test_a_voice_line_beside_a_peer_dm_still_denies_and_carries_both( self ):
        out  = _run( [ _peer_dm( "status?" ), _voice( "stop, wrong branch" ) ] )
        spec = out[ "hookSpecificOutput" ]
        assert spec[ "permissionDecision" ] == "deny"
        assert "stop, wrong branch" in spec[ "additionalContext" ]
        assert "status?" in spec[ "additionalContext" ]

    def test_a_voice_deny_still_outranks_a_commit_scope_notice( self ):
        out  = _run( [ _voice( "wait" ) ], notice="commit NOT REVIEWED" )
        spec = out[ "hookSpecificOutput" ]
        assert spec[ "permissionDecision" ] == "deny"
        assert "commit NOT REVIEWED" not in spec[ "additionalContext" ]


class TestAPeerDmAndACommitNoticeShareTheContext:

    def test_both_reach_the_seat_and_the_call_is_allowed( self ):
        out  = _run( [ _peer_dm( "status?" ) ], notice="commit NOT REVIEWED — pathspec unparsed" )
        spec = out[ "hookSpecificOutput" ]
        assert "permissionDecision" not in spec
        assert "status?" in spec[ "additionalContext" ]
        assert "commit NOT REVIEWED — pathspec unparsed" in spec[ "additionalContext" ]

    def test_an_empty_buffer_with_a_notice_emits_the_notice_alone( self ):
        out = _run( [], notice="commit NOT REVIEWED" )
        assert out == { "hookSpecificOutput": { "hookEventName": "PreToolUse",
                                                "additionalContext": "commit NOT REVIEWED" } }

    def test_an_empty_buffer_and_no_notice_emits_an_empty_object( self ):
        assert _run( [] ) == {}
