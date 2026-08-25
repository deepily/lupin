"""
Unit tests for the stash guard (bug 1ebc9be3).

The guard denies the MUTATING `git stash` verbs from the PreToolUse hook,
because the stash stack is repo-global rather than per-worktree: a pop can
apply another session's held work into your tree and — when the changesets do
not overlap — do it silently, leaving you to commit their files under your name.

Coverage target is 100% lines AND branches on stash_guard.py (Lupin-wide gate).
The one exclusion is the fail-open `except Exception` backstop, which carries a
same-line pragma explaining why it is genuinely unreachable.
"""
import pytest

from lupin_cli.claude_code.hooks.lib.stash_guard import (
    stash_deny_reason,
    build_stash_deny_response,
    _guard_disabled,
    _first_subcommand,
    _deny_reason_for,
    _blank_quoted_spans,
    READONLY_SUBCOMMANDS,
)

# The named verbs that mutate the shared stack. The guard does NOT read this
# list — it denies by default and allows only READONLY_SUBCOMMANDS — but every
# one of these must still be refused, so they are enumerated here as the
# behavioural contract rather than as an implementation detail.
MUTATING_SUBCOMMANDS = (
    "push", "save", "pop", "apply", "drop", "clear", "branch", "create", "store",
)


def _deny( command, **kw ):
    """Run the guard over one Bash command with the guard forced ON."""
    kw.setdefault( "enabled", True )
    return stash_deny_reason( "Bash", { "command": command }, **kw )


# ---------------------------------------------------------------------------
# The mutating verbs — every one of them must be denied
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "verb", sorted( MUTATING_SUBCOMMANDS ) )
def test_every_mutating_subcommand_is_denied( verb ):

    reason = _deny( f"git stash {verb}" )
    assert reason is not None
    assert verb in reason


def test_bare_git_stash_is_denied_as_a_push():
    """A bare `git stash` IS a push — the absent subcommand must not read as safe."""
    reason = _deny( "git stash" )
    assert reason is not None
    assert "git stash push" in reason


def test_flags_only_is_still_a_push():
    """`git stash -u` has no subcommand token, so it is the implicit push."""
    reason = _deny( "git stash -u --keep-index" )
    assert reason is not None
    assert "git stash push" in reason


def test_unrecognised_token_after_stash_is_denied():
    """A pathspec or typo is not a known-safe verb — deny rather than guess."""
    reason = _deny( "git stash frobnicate" )
    assert reason is not None
    assert "frobnicate" in reason


# ---------------------------------------------------------------------------
# The read-only verbs — inspecting the stack is how you decide what to do
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "verb", sorted( READONLY_SUBCOMMANDS ) )
def test_readonly_subcommands_are_allowed( verb ):

    assert _deny( f"git stash {verb}" ) is None


def test_readonly_flags_do_not_turn_it_into_a_push():

    assert _deny( "git stash list --stat" ) is None


def test_a_readonly_call_does_not_mask_a_later_mutating_one():
    """The loop must keep scanning past an allowed match, not stop at it."""
    reason = _deny( "git stash list && git stash pop" )
    assert reason is not None
    assert "git stash pop" in reason


# ---------------------------------------------------------------------------
# Command position — this is what keeps the guard off ordinary text
# ---------------------------------------------------------------------------

def test_denied_after_a_shell_separator():

    assert _deny( "cd /srv && git stash pop" ) is not None
    assert _deny( "true; git stash drop" )     is not None
    assert _deny( "false || git stash apply" ) is not None
    assert _deny( "( git stash clear )" )      is not None
    assert _deny( "echo hi\ngit stash push" )  is not None


def test_the_words_inside_an_argument_are_not_a_command():
    """`git` sits inside a quoted argument here, not at a command slot."""
    assert _deny( 'grep -r "git stash pop" src/' ) is None
    assert _deny( "echo 'git stash drop'" )        is None


def test_pre_subcommand_options_are_skipped():
    """`-C <path>` and `--git-dir=` sit between `git` and its subcommand."""
    assert _deny( "git -C /srv/repo stash pop" )          is not None
    assert _deny( "git --git-dir=/srv/.git stash apply" ) is not None
    assert _deny( "git -c user.name=x stash push" )       is not None


def test_a_non_option_token_before_stash_is_not_a_stash_call():
    """`git commit -m stash` must not be mistaken for `git stash`."""
    assert _deny( "git commit -m stash" ) is None


def test_unrelated_git_commands_are_untouched():

    assert _deny( "git status" )                    is None
    assert _deny( "git checkout HEAD -- src/a.py" ) is None


def test_the_match_does_not_run_past_a_separator():
    """`rest` is bounded to one command, so a pipe ends it."""
    assert _deny( "git stash list | wc -l" ) is None


# ---------------------------------------------------------------------------
# Gating: the escape hatch, the tool name, and malformed input
# ---------------------------------------------------------------------------

def test_escape_hatch_allows_the_mutating_verbs():

    assert stash_deny_reason(
        "Bash", { "command": "git stash drop abc1234" },
        env={ "LUPIN_ALLOW_GIT_STASH": "1" },
    ) is None


def test_guard_is_on_when_the_escape_hatch_is_absent():
    """Default-ON: an empty env must still deny."""
    assert stash_deny_reason( "Bash", { "command": "git stash pop" }, env={} ) is not None


def test_enabled_false_short_circuits():

    assert _deny( "git stash pop", enabled=False ) is None


def test_non_bash_tools_are_untouched():

    assert stash_deny_reason( "Read", { "command": "git stash pop" }, enabled=True ) is None


@pytest.mark.parametrize( "tool_input", [ None, "git stash pop", 42, [] ] )
def test_a_non_dict_tool_input_is_ignored( tool_input ):

    assert stash_deny_reason( "Bash", tool_input, enabled=True ) is None


@pytest.mark.parametrize( "command", [ "", None, 42, { "nested": True } ] )
def test_a_missing_or_non_string_command_is_ignored( command ):

    assert stash_deny_reason( "Bash", { "command": command }, enabled=True ) is None


def test_absent_command_key_is_ignored():

    assert stash_deny_reason( "Bash", {}, enabled=True ) is None


# ---------------------------------------------------------------------------
# Helpers, exercised directly for branch coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "value,expected", [
    ( "1",     True  ),
    ( "true",  True  ),
    ( "ON",    True  ),
    ( " yes ", True  ),
    ( "0",     False ),
    ( "",      False ),
    ( "maybe", False ),
] )
def test_guard_disabled_reads_the_flag( value, expected ):

    assert _guard_disabled( { "LUPIN_ALLOW_GIT_STASH": value } ) is expected


def test_guard_disabled_defaults_to_false_on_an_empty_env():

    assert _guard_disabled( {} ) is False


def test_guard_disabled_falls_back_to_os_environ( monkeypatch ):

    monkeypatch.setenv( "LUPIN_ALLOW_GIT_STASH", "true" )
    assert _guard_disabled() is True


def test_first_subcommand_skips_flags_and_lowercases():

    assert _first_subcommand( " -u --keep-index POP extra" ) == "pop"


def test_first_subcommand_is_none_when_only_flags_follow():

    assert _first_subcommand( " -u --keep-index" ) is None
    assert _first_subcommand( "" )                 is None


def test_deny_reason_names_push_for_an_absent_subcommand():

    assert "git stash push" in _deny_reason_for( None )


def test_deny_reason_names_the_offending_verb():

    assert "git stash apply" in _deny_reason_for( "apply" )


def test_deny_reason_carries_the_substitutes_and_the_escape_hatch():
    """The message has to be actionable — a bare refusal just gets worked around."""
    reason = _deny_reason_for( "pop" )
    assert "WIP commit on your own branch"  in reason
    assert "git checkout <sha> -- <path>"   in reason
    assert "LUPIN_ALLOW_GIT_STASH=1"        in reason
    assert "stash@{N}"                      in reason
    assert "1ebc9be3"                       in reason


def test_readonly_verbs_are_named_as_still_allowed():

    assert "git stash list" in _deny_reason_for( "pop" )


# ---------------------------------------------------------------------------
# The deny envelope
# ---------------------------------------------------------------------------

def test_build_stash_deny_response_shape():

    envelope = build_stash_deny_response( "because" )
    assert envelope == {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : "because",
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
# Row e062580e — a separator inside a QUOTED span is not a command position
# ══════════════════════════════════════════════════════════════════════════════
#
# THE DEFECT, as John measured it: `_GIT_STASH_RE` finds the phrase in "command
# position" — start-of-string or just after `; & | ( \n` — over the RAW string, with no
# notion of shell quoting. So a separator inside a quoted literal counted, and a heredoc
# or test table listing these commands was refused wholesale. Before the fix these three
# DENIED; the probe reported MISMATCHES: 3.
#
# It is a false DENY, never a false ALLOW, so it was never an escape — the cost lands on
# authoring, which is exactly how a guard gets switched off by the first person it
# inconveniences. It bit John demonstrating it, then bit the seat that fixed it twice:
# once writing the probe, once writing the patch.
#
# ⚠️ THIS BLOCK IS ITSELF THE END-TO-END PROOF. It was appended through a heredoc whose
# text contains the phrase after a separator inside quotes. Before the fix the live
# PreToolUse hook refused that write outright. If this test file exists, the hook let it
# through — which no unit assertion below can demonstrate, because they all call the
# matcher directly rather than crossing the hook.

QUOTED_FALSE_DENIES = [
    'x = "cd /tmp; git stash pop"',
    'x = "foo | git stash push"',
    'x = "( git stash pop )"',
]


@pytest.mark.parametrize( "command", QUOTED_FALSE_DENIES )
def test_a_separator_inside_a_quoted_span_is_not_a_command_position( command ):
    assert stash_deny_reason( "Bash", { "command": command }, enabled=True ) is None, (
        f"denied a quoted literal: {command!r}. The separator is inside quotes, so no "
        "command runs there — this is the row e062580e false deny."
    )


def test_a_real_command_after_a_quoted_one_is_still_denied():
    """THE CONTROL THAT KEEPS THE FIX HONEST. Blanking quoted spans must not blank the
    command that follows them — otherwise the fix has bought authoring comfort by
    putting a hole in a deny-by-default guard."""
    command = 'x = "a; git stash pop"; git stash pop'
    assert stash_deny_reason( "Bash", { "command": command }, enabled=True ) is not None


def test_an_unbalanced_quote_does_not_hide_a_real_command():
    """THE TRADE THE ROW SAYS TO REFUSE: a false deny swapped for a false ALLOW.

    A naive strip runs from the opening quote to end-of-string and swallows whatever
    follows. This pattern requires a CLOSING quote, so an unbalanced span matches
    nothing and the text is left exactly as it was. Measured identically before and
    after the fix."""
    command = 'echo "oops ; git stash pop'
    assert stash_deny_reason( "Bash", { "command": command }, enabled=True ) is not None


def test_blanking_uses_a_space_so_it_cannot_manufacture_a_command_position():
    """Deletion could butt two fragments together into a separator nobody typed; a
    space can only ever separate. `git` here is not in command position either way."""
    assert _blank_quoted_spans( 'a="x"git stash pop' ) == 'a= git stash pop'


def test_unbalanced_input_is_returned_unchanged():
    raw = 'echo "still open'
    assert _blank_quoted_spans( raw ) == raw
