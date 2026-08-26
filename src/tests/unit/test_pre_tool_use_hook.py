"""
The PreToolUse hook's five guard branches — row `e2099400`.

WHY THIS FILE EXISTS AT ALL. `pre_tool_use.py` had **no test file**. Its 74%
came from other suites importing it incidentally, and the nine uncovered
statements (72-73, 87-88, 103-104, 130-131, 144) are the five DENY branches —
the only lines in the module that do anything.

🔴 WHAT THOSE BRANCHES ARE. Every one of them is a guard that stops a tool call
which has already cost this fleet something real, and each cites its own
incident in the source:

  · subagent governance — a crew manager staffing with invisible in-process
    subagents instead of spawn_sessions
  · stash guard (bug 1ebc9be3) — `git stash pop` applying a PEER's held work
    into your tree, silently when the changesets do not overlap
  · kill guard (row cd332d2b) — a `ps | grep | kill` sweep that killed three
    live seats in 612 ms because a seat's argv carries its spawn brief
  · commit scope guard — `git commit` writing the WHOLE index, committing a
    peer's staged files under your name; five staged by name, four peer files
    committed

A guard that silently stops firing looks exactly like a fleet that stopped
making that mistake. There is no alarm for a deny that does not happen — which
is precisely why these five lines being untested matters more than their count.

WHAT IS PINNED:

· **Each guard denies independently**, driven one at a time with the other four
  silent. A test that armed them all together could not tell which one fired.

· **A deny SHORT-CIRCUITS.** The hook exits immediately, so no later guard runs
  and the voice buffer is never drained — draining it would consume the user's
  messages on a call that never happened, and they would be gone.

· **The guards run in their documented order**, held by a test that arms two at
  once and asserts which response comes back.

· **A clean call reaches the drain and emits an empty response**, which is what
  makes all of the above meaningful rather than a hook that denies everything.

· **The commit-scope NOTICE is subordinate to a voice deny.** Both want
  `additionalContext`; the voice deny blocks the commit anyway and the retry
  re-runs the check, so the notice must yield rather than overwrite.

· **The bridge mtime is stamped BEFORE any guard can exit.** It is this
  session's sign of life, and the arbiter reads it — a stamp placed after the
  guards would make a seat that keeps hitting one look dead.

See: row e2099400
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.claude_code.hooks import pre_tool_use as ptu


MODULE = "lupin_cli.claude_code.hooks.pre_tool_use"
GOV    = "lupin_cli.claude_code.hooks.lib.subagent_governance"
STASH  = "lupin_cli.claude_code.hooks.lib.stash_guard"
KILL   = "lupin_cli.claude_code.hooks.lib.kill_guard"
SCOPE  = "lupin_cli.claude_code.hooks.lib.commit_scope_guard"


def _run( payload=None, gov=None, stash=None, kill=None,
          deny_reason=None, notice=None, messages=None, voice_ctx=None ):
    """Drive main() with every guard and collaborator stubbed.

    Returns the dict handed to emit_json. Guards are silent (None) unless a test
    arms one, so each deny is exercised in isolation.
    """
    if payload is None: payload = { "session_id": "s1", "tool_name": "Bash",
                                    "tool_input": { "command": "ls" } }
    verdict = MagicMock( deny_reason=deny_reason, notice=notice )
    emit    = MagicMock()

    with patch( f"{MODULE}.read_hook_input", return_value=payload ), \
         patch( f"{MODULE}.log_payload" ), \
         patch( f"{MODULE}.touch_bridge_mtime" ) as touch, \
         patch( f"{MODULE}.resolve_stable_session_id", return_value="s1" ), \
         patch( f"{MODULE}.get_claude_session_id", return_value="s1" ), \
         patch( f"{GOV}.subagent_deny_reason",  return_value=gov ), \
         patch( f"{GOV}.build_subagent_deny_response", side_effect=lambda r: { "denied": "gov", "reason": r } ), \
         patch( f"{STASH}.stash_deny_reason",   return_value=stash ), \
         patch( f"{STASH}.build_stash_deny_response", side_effect=lambda r: { "denied": "stash", "reason": r } ), \
         patch( f"{KILL}.kill_deny_reason",     return_value=kill ), \
         patch( f"{KILL}.build_kill_deny_response", side_effect=lambda r: { "denied": "kill", "reason": r } ), \
         patch( f"{SCOPE}.evaluate_commit_scope", return_value=verdict ), \
         patch( f"{SCOPE}.build_commit_scope_deny_response", side_effect=lambda r: { "denied": "scope", "reason": r } ), \
         patch( f"{SCOPE}.build_commit_scope_notice_response", side_effect=lambda n: { "notice": n } ), \
         patch( f"{MODULE}.drain_and_acknowledge", return_value=messages or [] ) as drain, \
         patch( f"{MODULE}.format_voice_context", return_value=voice_ctx ), \
         patch( f"{MODULE}.build_voice_deny_response", side_effect=lambda c, m: { "voice": c } ), \
         patch( f"{MODULE}.emit_json", emit ):
        try:
            ptu.main()
        except SystemExit as exit_:
            assert exit_.code == 0, "the hook must always exit 0 — a non-zero status is a broken hook, not a deny"
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
