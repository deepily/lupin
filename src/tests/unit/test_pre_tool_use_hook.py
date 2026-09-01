"""
Unit tests for the PreToolUse hook.

Tests cover:
    - No tool TTS sent (verify send_tts NOT called)
    - Voice drain called with correct session_id
    - Empty payload → immediate {}
    - session_id fallback via get_claude_session_id
    - Phase 4: additionalContext injection from drained messages
"""

import contextlib
import sys
import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.pre_tool_use import main
from lupin_cli.claude_code.hooks import pre_tool_use as ptu   # guard-branch tests below drive main() through the module


@pytest.fixture( autouse=True )
def _stub_bridge_touch():
    """
    Stub the bridge-mtime liveness stamp for every test in this module.

    main() now calls touch_bridge_mtime() at the START of every tool call
    (arbiter signs-of-life Fix 1) — mirroring PostToolUse. Stubbing it keeps
    these unit tests free of real filesystem side effects (the stamp does a real
    os.utime against the resolved bridge) and lets the dedicated stamp tests
    assert the call. Autouse so the existing tests inherit the stub without
    per-method decorators.
    """
    with patch( "lupin_cli.claude_code.hooks.pre_tool_use.touch_bridge_mtime" ) as m:
        yield m


# ═════════════════════════════════════════════════════════════════════════════
# TestNoToolTTS
# ═════════════════════════════════════════════════════════════════════════════

class TestNoToolTTS:
    """PreToolUse should NOT announce tools — PostToolUse handles that."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_no_tts_for_bash( self, mock_read, mock_log, mock_session,
                               mock_drain, mock_emit, mock_resolve ):
        """Bash tool does NOT trigger TTS in PreToolUse."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "npm test" },
            "session_id" : "abc12345"
        }

        main()

        # send_tts is not even imported in pre_tool_use anymore
        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_no_tts_for_write( self, mock_read, mock_log, mock_session,
                                mock_drain, mock_emit, mock_resolve ):
        """Write tool does NOT trigger TTS in PreToolUse."""
        mock_read.return_value = {
            "tool_name"  : "Write",
            "tool_input" : { "file_path": "/tmp/test.py" },
            "session_id" : "abc12345"
        }

        main()

        mock_emit.assert_called_once_with( {} )


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceDrain
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceDrain:
    """Tests for voice buffer drain in PreToolUse."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_drain_called_with_payload_session_id( self, mock_read, mock_log, mock_session,
                                                    mock_drain, mock_emit, mock_resolve ):
        """Drain uses session_id from payload when available."""
        mock_read.return_value = {
            "tool_name"  : "Grep",
            "tool_input" : { "pattern": "foo" },
            "session_id" : "payload99"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "payload99" )

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_session_id_fallback( self, mock_read, mock_log, mock_session,
                                   mock_drain, mock_emit, mock_resolve ):
        """When payload has no session_id, falls back to session bridge."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : {}
            # No session_id key
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )


# ═════════════════════════════════════════════════════════════════════════════
# TestEmptyPayload
# ═════════════════════════════════════════════════════════════════════════════

class TestEmptyPayload:
    """Tests for empty payload handling."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input", return_value={} )
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

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_drained_messages_emit_additional_context( self, mock_read, mock_log, mock_session,
                                                        mock_drain, mock_emit, mock_resolve ):
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

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_no_messages_emit_empty( self, mock_read, mock_log, mock_session,
                                      mock_drain, mock_emit, mock_resolve ):
        """No drained messages emits {} (passthrough)."""
        mock_read.return_value = {
            "tool_name"  : "Read",
            "tool_input" : {},
            "session_id" : "abc12345"
        }

        main()

        mock_emit.assert_called_once_with( {} )

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_multiple_messages_joined( self, mock_read, mock_log, mock_session,
                                        mock_drain, mock_emit, mock_resolve ):
        """Multiple drained messages are joined with newlines in additionalContext."""
        mock_read.return_value = {
            "tool_name"  : "Edit",
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
# TestLivenessStamp (arbiter signs-of-life Fix 1)
# ═════════════════════════════════════════════════════════════════════════════

class TestLivenessStamp:
    """PreToolUse bumps the bridge mtime at the START of a tool call (Fix 1)."""

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input" )
    def test_touch_fires_once_per_tool_call( self, mock_read, mock_log, mock_session,
                                             mock_drain, mock_emit, mock_resolve,
                                             _stub_bridge_touch ):
        """A normal tool call bumps the bridge mtime exactly once, at the start."""
        mock_read.return_value = {
            "tool_name"  : "Bash",
            "tool_input" : { "command": "sleep 30" },   # long in-flight tool → start-stamp matters
            "session_id" : "abc12345"
        }

        main()

        _stub_bridge_touch.assert_called_once_with()

    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.read_hook_input", return_value={} )
    @patch( "lupin_cli.claude_code.hooks.pre_tool_use.emit_json" )
    def test_no_touch_on_empty_payload( self, mock_emit, mock_read, _stub_bridge_touch ):
        """An empty payload exits before the stamp — no liveness lie on a no-op turn."""
        with pytest.raises( SystemExit ):
            main()

        _stub_bridge_touch.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# THE FIVE GUARD BRANCHES — row e2099400
#
# Added 2026-08-26. The tests above cover the drain, the liveness stamp and the
# empty-payload exit. What had NO coverage at all were lines 72-73, 87-88,
# 103-104, 130-131 and 144 — the five DENY branches, which are the only lines in
# the module that stop anything.
#
# 🔴 Each guards against something that has already cost this fleet, and each
# cites its own incident in the source: subagent governance (a crew manager
# staffing with invisible in-process subagents); the stash guard (bug 1ebc9be3 —
# `git stash pop` applying a peer's held work into your tree, silently when the
# changesets do not overlap); the kill guard (row cd332d2b — a `ps | grep | kill`
# sweep that killed three live seats in 612 ms); the commit scope guard (`git
# commit` writing the WHOLE index and committing a peer's staged files under your
# name).
#
# A guard that silently stops firing is indistinguishable from a fleet that
# stopped making that mistake. There is no alarm for a deny that does not happen.
#
# ⚠️ These use their own driver (`_run` below) rather than the decorator stack
# above, because each guard has to be armed ALONE — armed together, no test could
# say which one fired.
# ═════════════════════════════════════════════════════════════════════════════

MODULE = "lupin_cli.claude_code.hooks.pre_tool_use"
GOV    = "lupin_cli.claude_code.hooks.lib.subagent_governance"
STASH  = "lupin_cli.claude_code.hooks.lib.stash_guard"
KILL   = "lupin_cli.claude_code.hooks.lib.kill_guard"
SCOPE  = "lupin_cli.claude_code.hooks.lib.commit_scope_guard"
MERGE  = "lupin_cli.claude_code.hooks.lib.merge_head_guard"


def _run( payload=None, gov=None, stash=None, kill=None, merge=None,
          deny_reason=None, notice=None, messages=None, voice_ctx=None ):
    """Drive main() with every guard and collaborator stubbed.

    Returns the dict handed to emit_json. Guards are silent (None) unless a test
    arms one, so each deny is exercised in isolation.
    """
    if payload is None: payload = { "session_id": "s1", "tool_name": "Bash",
                                    "tool_input": { "command": "ls" } }
    verdict = MagicMock( deny_reason=deny_reason, notice=notice )
    emit    = MagicMock()

    # ExitStack, NOT a nested `with` chain. CPython caps a function at 20
    # statically nested blocks, and the fifth guard's two patches crossed it —
    # `SyntaxError: too many statically nested blocks`, which surfaces as a
    # COLLECTION ERROR rather than a failure, so nothing in the suite runs and no
    # test says why. A flat stack has no such ceiling and the sixth guard will not
    # rediscover this.
    with contextlib.ExitStack() as stack:
        def _p( *args, **kwargs ):
            return stack.enter_context( patch( *args, **kwargs ) )

        _p( f"{MODULE}.read_hook_input", return_value=payload )
        _p( f"{MODULE}.log_payload" )
        touch = _p( f"{MODULE}.touch_bridge_mtime" )
        _p( f"{MODULE}.resolve_stable_session_id", return_value="s1" )
        _p( f"{MODULE}.get_claude_session_id", return_value="s1" )

        _p( f"{GOV}.subagent_deny_reason",  return_value=gov )
        _p( f"{GOV}.build_subagent_deny_response", side_effect=lambda r: { "denied": "gov", "reason": r } )
        _p( f"{STASH}.stash_deny_reason",   return_value=stash )
        _p( f"{STASH}.build_stash_deny_response", side_effect=lambda r: { "denied": "stash", "reason": r } )
        _p( f"{KILL}.kill_deny_reason",     return_value=kill )
        _p( f"{KILL}.build_kill_deny_response", side_effect=lambda r: { "denied": "kill", "reason": r } )
        _p( f"{MERGE}.merge_head_deny_reason", return_value=merge )
        _p( f"{MERGE}.build_merge_head_deny_response", side_effect=lambda r: { "denied": "merge", "reason": r } )
        _p( f"{SCOPE}.evaluate_commit_scope", return_value=verdict )
        _p( f"{SCOPE}.build_commit_scope_deny_response", side_effect=lambda r: { "denied": "scope", "reason": r } )
        _p( f"{SCOPE}.build_commit_scope_notice_response", side_effect=lambda n: { "notice": n } )

        drain = _p( f"{MODULE}.drain_and_acknowledge", return_value=messages or [] )
        _p( f"{MODULE}.format_voice_context", return_value=voice_ctx )
        _p( f"{MODULE}.build_voice_deny_response", side_effect=lambda c, m: { "voice": c } )
        _p( f"{MODULE}.emit_json", emit )

        try:
            ptu.main()
        except SystemExit as exit_:
            assert exit_.code == 0, "the hook must always exit 0 - a non-zero status is a broken hook, not a deny"
    return emit.call_args.args[ 0 ], drain, touch


class TestEachGuardDeniesIndependently:
    """One at a time, the other four silent — otherwise a test cannot tell which
    guard fired."""

    def test_subagent_governance_denies( self ):
        out, _, _ = _run( gov="crew managers staff via spawn_sessions" )
        assert out[ "denied" ] == "gov"

    def test_the_stash_guard_denies( self ):
        out, _, _ = _run( stash="git stash is repo-global" )
        assert out[ "denied" ] == "stash"

    def test_the_kill_guard_denies( self ):
        out, _, _ = _run( kill="unscoped kill sweep" )
        assert out[ "denied" ] == "kill"

    def test_the_commit_scope_guard_denies( self ):
        out, _, _ = _run( deny_reason="peer files staged" )
        assert out[ "denied" ] == "scope"

    def test_the_merge_head_guard_denies( self ):
        out, _, _ = _run( merge="a merge is live in this tree" )
        assert out[ "denied" ] == "merge"

    def test_the_merge_head_guard_is_reached_before_the_commit_scope_guard( self ):
        """
        ORDER IS LOAD-BEARING, and this is the only test that can see it.

        Both guards trigger on the same command. A live merge is the harder stop
        and its message is the one the committer needs first — being told which
        peer file is staged, while a merge silently waits to be concluded, sends
        the seat off to fix the wrong thing. Armed together, the merge guard wins.
        """
        out, _, _ = _run( merge="a merge is live", deny_reason="peer files staged" )
        assert out[ "denied" ] == "merge", (
            "the commit scope guard answered first - a live merge must be refused "
            "before the index is discussed"
        )

    def test_the_reason_is_carried_into_the_response( self ):
        """A refusal that does not say why is a wall, not a guard."""
        out, _, _ = _run( stash="git stash is repo-global (bug 1ebc9be3)" )
        assert "1ebc9be3" in out[ "reason" ]

    def test_a_clean_call_denies_nothing( self ):
        """THE CONTROL. A hook that denied unconditionally would satisfy all
        four tests above."""
        out, _, _ = _run()
        assert out == {}


class TestADenyShortCircuits:

    def test_the_voice_buffer_is_not_drained_on_a_deny( self ):
        """Draining consumes the user's messages. On a call that never happened
        they would be gone, and nothing would report it."""
        _, drain, _ = _run( stash="denied" )
        drain.assert_not_called()

    def test_a_later_guard_does_not_run_after_an_earlier_deny( self ):
        with patch( f"{KILL}.kill_deny_reason" ) as kill_check:
            _run( gov="denied" )
        kill_check.assert_not_called()

    @pytest.mark.parametrize( "armed, expected", [
        ( { "gov": "g", "stash": "s" },                  "gov" ),
        ( { "stash": "s", "kill": "k" },                 "stash" ),
        ( { "kill": "k", "deny_reason": "c" },           "kill" ),
    ] )
    def test_the_guards_fire_in_their_documented_order( self, armed, expected ):
        out, _, _ = _run( **armed )
        assert out[ "denied" ] == expected


class TestTheDrainPath:

    def test_buffered_voice_takes_precedence_over_an_empty_response( self ):
        out, _, _ = _run( messages=[ { "text": "hello" } ], voice_ctx="hello" )
        assert out == { "voice": "hello" }

    def test_a_commit_scope_notice_is_emitted_when_nothing_else_claims_it( self ):
        out, _, _ = _run( notice="4 files staged by a peer went unreviewed" )
        assert "unreviewed" in out[ "notice" ]

    def test_a_voice_deny_outranks_the_notice( self ):
        """Both want additionalContext. The voice deny blocks the commit anyway
        and the retry re-runs the scope check with the buffer drained."""
        out, _, _ = _run( messages=[ { "text": "wait" } ], voice_ctx="wait",
                          notice="something went unreviewed" )
        assert out == { "voice": "wait" }

    def test_no_voice_and_no_notice_emits_an_empty_object( self ):
        out, _, _ = _run()
        assert out == {}


class TestLivenessAndInput:

    def test_the_bridge_is_stamped_before_any_guard_can_exit( self ):
        """It is this session's sign of life and the arbiter reads it. Stamped
        after the guards, a seat that keeps hitting one would read as dead."""
        _, _, touch = _run( gov="denied" )
        touch.assert_called_once()

    def test_the_bridge_is_stamped_on_a_clean_call_too( self ):
        _, _, touch = _run()
        touch.assert_called_once()

    def test_an_empty_payload_emits_an_empty_object_and_stops( self ):
        emit = MagicMock()
        with patch( f"{MODULE}.read_hook_input", return_value=None ), \
             patch( f"{MODULE}.touch_bridge_mtime" ) as touch, \
             patch( f"{MODULE}.emit_json", emit ):
            with pytest.raises( SystemExit ) as exit_:
                ptu.main()
        assert exit_.value.code == 0
        assert emit.call_args.args[ 0 ] == {}
        touch.assert_not_called()

    def test_a_payload_without_a_session_id_falls_back_to_the_bridge( self ):
        """resolve_stable_session_id returns "" for an absent id; the fallback
        is what keeps the guards keyed to a real seat."""
        with patch( f"{MODULE}.read_hook_input", return_value={ "tool_name": "Bash" } ), \
             patch( f"{MODULE}.log_payload" ), patch( f"{MODULE}.touch_bridge_mtime" ), \
             patch( f"{MODULE}.resolve_stable_session_id", return_value="" ), \
             patch( f"{MODULE}.get_claude_session_id", return_value="from-bridge" ) as fallback, \
             patch( f"{GOV}.subagent_deny_reason", return_value=None ), \
             patch( f"{STASH}.stash_deny_reason", return_value=None ), \
             patch( f"{KILL}.kill_deny_reason", return_value=None ), \
             patch( f"{SCOPE}.evaluate_commit_scope",
                    return_value=MagicMock( deny_reason=None, notice=None ) ), \
             patch( f"{MODULE}.drain_and_acknowledge", return_value=[] ), \
             patch( f"{MODULE}.format_voice_context", return_value=None ), \
             patch( f"{MODULE}.emit_json" ):
            ptu.main()
        fallback.assert_called_once()
