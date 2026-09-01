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


# ──────────────────────────────────────────────────────────────────────────
# THE BYPASS CLASS (row 1ebc9be3, reported by Rachel, measured 2026-08-24)
#
# The guard used to recognise ONE spelling of the program — the bare word `git`
# — in one syntactic position. Measured against 22 natural forms, 21 walked
# past it while reaching the same repo-global stack.
#
# These tests are the CLASS, not a list of the 21. Each names the degree of
# freedom it removes, so a future edit that reintroduces one fails with a
# sentence saying which.

BYPASS_FORMS = [
    # how the program is spelled
    ( "/usr/bin/git stash pop",                "absolute path" ),
    ( "/usr/local/bin/git stash pop",          "another absolute path" ),
    ( "./git stash pop",                       "relative path" ),
    ( "\\git stash pop",                       "backslash-escaped name" ),
    ( "'git' stash pop",                       "single-quoted program name" ),
    ( '"git" stash pop',                       "double-quoted program name" ),
    ( "g\\it stash pop",                       "escape inside the name" ),
    # wrappers that still run git
    ( "env git stash pop",                     "via env" ),
    ( "command git stash pop",                 "via the command builtin" ),
    ( "sudo git stash pop",                    "via sudo" ),
    ( "nohup git stash pop",                   "via nohup" ),
    ( "time git stash pop",                    "via time" ),
    ( "xargs git stash pop",                   "via xargs" ),
    # environment assignment before the program
    ( "GIT_DIR=/x/.git git stash pop",         "env assignment prefix" ),
    # nested interpreters
    ( "sh -c 'git stash pop'",                 "nested sh -c, single quotes" ),
    ( 'sh -c "git stash pop"',                 "nested sh -c, double quotes" ),
    ( "bash -c 'echo x; git stash pop'",       "nested bash -c with a separator" ),
    # command positions the original class did not cover
    ( "{ git stash pop; }",                    "brace group" ),
    ( "if true; then git stash pop; fi",       "inside an if/then" ),
    # line continuation
    ( "git \\\n  stash pop",                   "backslash line continuation" ),
]


@pytest.mark.parametrize( "command,label", BYPASS_FORMS, ids=[ b[ 1 ] for b in BYPASS_FORMS ] )
def test_bypass_forms_are_denied( command, label ):
    """
    Every spelling that reaches the shared stack must be refused.

    Ensures:
        - the guard denies the form, naming which degree of freedom regressed
    """
    assert stash_deny_reason( "Bash", { "command": command }, enabled=True ) is not None, (
        f"BYPASS REOPENED — {label}: {command!r} reaches the same repo-global stack "
        "and is no longer denied. The fix is normalisation (remove the degree of "
        "freedom), never another entry in a denylist."
    )


def test_nested_shell_payload_is_scanned_and_the_over_block_stays_fixed():
    """
    The two halves of the quoting question, which pull in opposite directions.

    Blanking quoted spans fixed a false deny (row e062580e) and, measured after
    the fact, turned nested shells from DENY into ALLOW — a false deny traded
    for a false ALLOW, the exact trade the row said to refuse. Reaching into an
    INTERPRETER'S payload while still blanking every other quoted span is what
    lets both hold at once.

    Ensures:
        - an interpreter payload is scanned as the command it becomes
        - a quoted string that is merely TEXT is still not a command position
    """
    assert stash_deny_reason(
        "Bash", { "command": "bash -c 'echo x; git stash pop'" }, enabled=True
    ) is not None, "an interpreter's payload must be scanned as a command"

    assert stash_deny_reason(
        "Bash", { "command": 'x = "cd /tmp; git stash pop"' }, enabled=True
    ) is None, "a separator inside a quoted literal is not a command position"


def test_read_only_verbs_survive_every_spelling():
    """
    Normalisation must not turn the allowed verbs into denied ones.

    Ensures:
        - list/show stay allowed through a path, a wrapper and an interpreter
    """
    for command in (
        "/usr/bin/git stash list",
        "sudo git stash show",
        "sh -c 'git stash list'",
        "env git stash show -p",
    ):
        assert stash_deny_reason( "Bash", { "command": command }, enabled=True ) is None, \
            f"read-only verb wrongly denied: {command!r}"


def test_ordinary_commands_are_untouched():
    """
    The guard sits on EVERY tool call, so a false deny is expensive.

    Ensures:
        - commands that merely mention the word, or use git for anything else,
          are allowed
    """
    for command in (
        'grep "git stash" docs/',
        "echo 'git stash pop'",
        "git commit -m 'no git stash here'",
        "git status",
        "git log --oneline -5",
        "ls /usr/bin/git",
        "cat stash_guard.py",
    ):
        assert stash_deny_reason( "Bash", { "command": command }, enabled=True ) is None, \
            f"false deny on an ordinary command: {command!r}"


def test_an_interpreter_with_an_empty_payload_is_skipped():
    """
    `sh -c ''` matches the nested-interpreter pattern but carries nothing to
    scan. The empty payload is skipped rather than fed to the matcher as an
    empty string.

    Ensures:
        - an empty interpreter payload is allowed and does not raise
        - a real command elsewhere in the same line is still caught, so the skip
          cannot swallow the rest of the scan
    """
    assert stash_deny_reason( "Bash", { "command": "sh -c ''" }, enabled=True ) is None
    assert stash_deny_reason(
        "Bash", { "command": "sh -c ''; git stash pop" }, enabled=True
    ) is not None


def test_the_inline_escape_hatch_is_honoured():
    """
    THE DENY MESSAGE'S OWN INSTRUCTION MUST BE TRUE.

    Every deny tells the reader to "re-run with LUPIN_ALLOW_GIT_STASH=1". This
    test is the permanent guarantee that doing so works, because it silently did
    NOT for most of this guard's life and nobody noticed (row 1ebc9be3).

    The history is worth keeping. The hook is a separate process and never sees
    an inline `VAR=1 cmd` prefix in its os.environ. The inline form appeared to
    work only because the env assignment pushed `git` out of command position,
    so the matcher failed to match — the hatch was indistinguishable from the
    env-assignment BYPASS. Closing that bypass closed the hatch with it, which is
    how the defect surfaced at all.

    Ensures:
        - the flag is read from the COMMAND, with the hook's own environment
          explicitly clean, so this cannot pass for the old accidental reason
        - a mutating verb is allowed through when the flag prefixes it
        - the flag is NOT required to be in the hook's environment
    """
    clean = { }          # the flag deliberately absent from the hook's env

    for command in (
        "LUPIN_ALLOW_GIT_STASH=1 git stash drop",
        "LUPIN_ALLOW_GIT_STASH=true git stash pop",
        "LUPIN_ALLOW_GIT_STASH=1 /usr/bin/git stash push -- some/path",
    ):
        assert stash_deny_reason( "Bash", { "command": command }, env=clean ) is None, (
            f"THE ESCAPE HATCH IS BROKEN for {command!r}. The deny message tells "
            "every reader to re-run with this flag; if that instruction is false, "
            "the guard is lying to the person it just blocked."
        )


def test_an_unrelated_env_assignment_is_still_denied():
    """
    The other side of the hatch, so honouring it cannot become a bypass.

    Ensures:
        - a non-flag assignment before git does NOT disable the guard
        - a WRONG value for the flag does not disable it either
        - the flag mentioned outside this invocation's own prefix does not
          disable it — `echo` first, real mutation second
    """
    clean = { }

    for command in (
        "FOO=1 git stash pop",
        "LUPIN_ALLOW_GIT_STASH=0 git stash pop",
        "LUPIN_ALLOW_GIT_STASH=nope git stash pop",
        "echo LUPIN_ALLOW_GIT_STASH=1; git stash pop",
    ):
        assert stash_deny_reason( "Bash", { "command": command }, env=clean ) is not None, (
            f"the hatch leaked into {command!r} — it must apply only to the "
            "invocation whose own prefix carries a truthy flag"
        )


def test_prose_in_backticks_is_not_a_command( ):
    """
    Writing ABOUT the guard must not be blocked by the guard.

    Rachel measured the cost on 2026-08-24: 22 denial events across 11 sessions
    in one night, nearly all of them people documenting this very module. A
    backtick genuinely does open a command substitution, so this is a real trade
    — but the two forms are byte-identical in text, and under an accident threat
    model the documentation case dominates by orders of magnitude.

    Ensures:
        - markdown prose mentioning the verb is allowed
        - the form people actually use for substitution, $(...), is still denied
    """
    prose = "cat > notes.md <<'EOF'\nThe guard denies `git stash pop`.\nEOF"
    assert stash_deny_reason( "Bash", { "command": prose }, enabled=True ) is None, \
        "writing documentation about the guard must not be refused by the guard"

    assert stash_deny_reason(
        "Bash", { "command": "x=$(git stash pop)" }, enabled=True
    ) is not None, "$(...) substitution is a real invocation and must stay denied"


def test_variable_indirection_is_the_named_residual():
    """
    THE LIMIT, ASSERTED SO IT CANNOT BE FORGOTTEN.

    `g=git; $g stash pop` cannot be resolved from text, and neither can eval or
    a base64 payload. This test PINS that as known and accepted rather than
    letting the guard imply a completeness it does not have.

    The threat model is ACCIDENT, not evasion (Cheech, 2026-08-24): this fleet
    has no adversary, it has habits. Nobody reaches for variable indirection by
    accident; everybody reaches for /usr/bin/git and sudo.

    Ensures:
        - the residual is allowed, and this test says why on purpose
        - if a future change DOES catch it, this test fails and someone updates
          the docstring's honesty rather than quietly gaining a promise
    """
    assert stash_deny_reason(
        "Bash", { "command": "g=git; $g stash pop" }, enabled=True
    ) is None, (
        "variable indirection is now caught — good, but the module docstring "
        "still calls it a residual. Update the docstring and this test together."
    )


# ═════════════════════════════════════════════════════════════════════════════
# THE EMPTY-ENV-ASSIGNMENT BYPASS (found 2026-08-31, fixed the same day)
# ═════════════════════════════════════════════════════════════════════════════

def test_an_empty_env_assignment_does_not_bypass_the_guard():
    """
    `GIT_DIR= git stash pop` was ALLOWED. A word boundary cannot sit between the
    `=` of an empty assignment and the space after it — both are non-word
    characters — so the prefix group failed, the match fell back to zero prefixes,
    and the anchored program never matched. Bypass #23, in a guard whose whole
    value is that a miss lets through a command that had to be refused.

    Found by a merge_head_guard test asserting the falsy spellings of its own
    hatch, which is the kind of place these keep turning up: a test aimed at one
    thing measuring the matcher underneath it.
    """
    for command in ( "FOO= git stash pop", "GIT_DIR= git stash pop", "EDITOR= git stash drop" ):
        assert stash_deny_reason( "Bash", { "command": command }, enabled=True ) is not None, \
            f"the empty assignment bypassed the guard: {command!r}"


def test_the_empty_assignment_fix_did_not_buy_a_false_deny():
    """
    THE CONTROL FOR THE FIX. Dropping the boundary outright would let the greedy
    value backtrack INTO the program name, so a `git` that is part of an
    assignment's VALUE would be read as a command — a false allow traded for a
    false deny. The lookahead pins the value to a real token end instead.
    """
    assert stash_deny_reason( "Bash", { "command": "FOO=bargit stash pop" }, enabled=True ) is None, \
        "matched a `git` that is part of an env value, not a command"


def test_the_read_only_verbs_survive_the_empty_assignment_fix():
    """A widened matcher must not start refusing the two allowed subcommands."""
    for command in ( "FOO= git stash list", "GIT_DIR= git stash show" ):
        assert stash_deny_reason( "Bash", { "command": command }, enabled=True ) is None, \
            f"a read-only verb was refused: {command!r}"
