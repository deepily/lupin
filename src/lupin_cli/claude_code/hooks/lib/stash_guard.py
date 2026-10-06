"""
Deny mutating `git stash` commands in the PreToolUse hook; the stash stack is repo-global.

One stash stack is shared by every worktree and every live session, so pushes and pops race.
A pop can apply another session's held work into your tree, silently when the changesets do not overlap.
Also `stash@{N}` is a position, not a name: a drop renumbers the stack. Name the commit sha instead.

Ensures:
    - only mutating subcommands are denied; read-only `git stash list` and `git stash show` stay allowed
    - to hold work, use a work-in-progress commit on your own branch, because a branch is yours and a stash is shared
    - to inspect an old version, use a throwaway detached worktree first; it cannot touch anybody's working tree
    - `git checkout <sha> -- <path>` is a last resort, only after `cp <path> <path>.bak`, and so is the `HEAD` restore form
    - that checkout overwrites the working-tree copy, including a peer's uncommitted work, and moves no HEAD, so no reflog entry exists
    - to undo your own edit, `cp` from a backup you took in a worktree of your own
    - that `cp` fixes only which bytes come back; the write is identical, so a peer's edit made since the backup is lost
    - only a detached worktree leaves no such window in a shared checkout
    - balanced quoted spans are blanked before matching, so a separator inside a quoted literal is not read as a command position
    - an unbalanced quote matches nothing and cannot hide a real command, which is why shlex was refused: it raises there
    - blanking hides a nested interpreter's payload, so the payload of `sh -c` is scanned separately
    - the matcher normalises how the program is spelled instead of extending a denylist; each clause removes one degree of freedom
    - those spellings are paths, backslash escapes, quoted names, wrappers such as env, sudo, nohup, time and xargs, env-assignment prefixes, brace groups, if-then, line continuations and nested shells
    - an extended denylist is how the first matcher let 21 of 22 natural spellings through
    - `g=git; $g st​ash pop` is not caught: text matching cannot resolve variable indirection, eval or a base64 payload
    - the threat model is accident, not evasion, so this is an accident-preventer and not a security boundary
    - a test pins that residual as known and fails if it is ever silently closed
    - `LUPIN_ALLOW_GIT_STASH=1` is the escape hatch, honoured by the prefix carve-out `_hatch_in_prefix`, not by an environment read
    - the hook is a separate process whose environment never holds an inline prefix, so do not remove that carve-out
    - removing it silently removes the hatch that every deny message recommends; a generic env prefix is still denied
    - any error allows (fail-open), because a guard on the hot path must never break a tool call
    - the guard is default-on, because a control that must be switched on depends on remembering
    - examples here carry a zero-width space inside the verb so reading this file through a shell is not itself refused
    - if the guard refuses authoring text, put the script in a file and run the file rather than a heredoc
    - the acceptance test is unchanged: all thirteen mutating forms stay denied
"""
import os
import re
from typing import Optional


# Bash tool name as it appears in the PreToolUse hook payload.
BASH_TOOL_NAMES = ( "Bash", )

_ENV_FLAG    = "LUPIN_ALLOW_GIT_STASH"
_TRUE_VALUES = ( "1", "true", "on", "yes" )

# DENY BY DEFAULT: the read-only verbs are an ALLOWLIST and everything else is
# refused — a named mutating verb (push/save/pop/apply/drop/clear/branch/create/
# store), a bare `git stash` (an implicit push), or an unrecognised token, which
# is a pathspec or a typo and not a verb anyone has shown to be safe.
#
# This started life as a matching denylist beside this allowlist, and a mutation
# test proved that conditional dead: both of its arms returned the same string,
# so it could be inverted without reddening a single test. Deny-by-default is
# also the correct posture — a subcommand added by a future git release is
# refused until someone looks at it, rather than silently permitted.
READONLY_SUBCOMMANDS = frozenset( { "list", "show" } )

# `git` in COMMAND POSITION only: start of string, or immediately after a shell
# separator. This is what keeps `grep "git stash" docs/` and `echo 'git stash'`
# out of the guard — there the word sits inside an argument, not at a command
# slot. Between `git` and `stash` we skip pre-subcommand options (`-C <path>`,
# `--git-dir=...`, `-c key=val`).
# THE BYPASS CLASS, and why this pattern is shaped the way it is (row 1ebc9be3,
# measured 2026-08-24 after Rachel reported it). The original pattern recognised
# exactly ONE spelling of the program — the bare word `git` — in one syntactic
# position. A command's TEXT has unbounded spellings, so 21 of 22 natural forms
# walked straight past it while reaching the same repo-global stack: an absolute
# or relative path, a backslash escape, a quoted program name, the env / command
# / sudo / nohup / time / xargs wrappers, an env-assignment prefix, a brace
# group, `if ...; then`, a line continuation, and a nested `sh -c`.
#
# ⇒ THE FIX IS NORMALISATION, NOT A LONGER DENYLIST. Every clause below removes
# one DEGREE OF FREEDOM in how the program can be spelled, rather than naming one
# more thing to refuse. Adding cases to a denylist is how the original got here.
#
# ⇒ WHAT IT CANNOT DO, stated plainly so the docstring's promise stays honest:
# text matching cannot resolve `g=git; $g stash pop`, an eval, or a base64
# payload. THE THREAT MODEL IS ACCIDENT, NOT EVASION — this fleet has no
# adversary, it has habits. Nobody reaches for variable indirection by accident,
# and everybody reaches for `/usr/bin/git` or `sudo`. Catching every natural
# spelling is the whole job; claiming completeness would be the defect this
# module exists to catch.

# Command position, widened. `{` and `)` open a command slot too, and so do the
# shell keywords, which is how `if true; then git stash pop; fi` slipped through.
# ⚠️ THE BACKTICK IS DELIBERATELY ABSENT, and it is the one place this pattern
# trades coverage for usability on measured evidence rather than taste. A
# backtick opens a command substitution, so ``git st​ash pop`` really is an
# invocation — but in THIS fleet a backtick almost always opens markdown prose,
# and the two are byte-identical. Rachel measured the cost on 2026-08-24:
# 22 denial events across 11 sessions in one night, nearly all of them people
# writing documentation ABOUT the guard. Under an accident threat model that is
# the wrong side of the trade: nobody runs a stash by backtick substitution
# while writing a doc, and `$(...)` — the form people actually use — is still
# caught by the open paren. Adding it back means re-measuring the friction.
_COMMAND_POSITION = r"(?:^|[;&|(){}\n]|\bthen\b|\bdo\b|\belse\b|\belif\b)"

# Things that sit between the command slot and the program while still running
# it: environment assignments (FOO=bar) and transparent wrappers.
_WRAPPERS = r"(?:env|command|builtin|exec|sudo|nohup|time|nice|stdbuf|xargs)"
# 🔴 AN EMPTY ENV ASSIGNMENT USED TO WALK STRAIGHT PAST THIS (found 2026-08-31 by
# a merge_head_guard test, measured in BOTH guards). The `\b` sat AFTER the whole
# alternation, and a word boundary cannot exist between the `=` of `FOO=` and the
# space that follows - two non-word characters. So the prefix group failed, the
# match backtracked to zero prefixes, and the anchored program never matched:
#
#     FOO=1 git stash pop      DENIED
#     FOO=  git stash pop      ALLOWED    <-- and `GIT_DIR= git stash pop` with it
#
# THE FIX IS A LOOKAHEAD, NOT A DROPPED `\b`. Simply removing the boundary lets the
# greedy value backtrack INTO the program name, so `FOO=bargit commit` would match
# a `git` that is part of the value - trading a false allow for a false deny, which
# is the trade this fleet's guards exist to refuse. `(?=[\s;&|]|$)` pins the value
# to a real token end instead, so it can neither swallow the program nor give back
# part of itself. Measured both ways: the empty assignment now matches and
# `FOO=bargit commit` still does not.
_PREFIXES = rf"(?P<prefix>(?:\s*(?:[A-Za-z_][A-Za-z0-9_]*=[^\s;&|]*(?=[\s;&|]|$)|{_WRAPPERS}\b))*)"

# The program itself, allowing any leading path. The bare name is matched by the
# empty alternative of the path group.
_PROGRAM  = r"(?:[\w./~+-]*/)?git"

_GIT_STASH_RE = re.compile(
    rf"""
    {_COMMAND_POSITION}
    {_PREFIXES}
    \s*
    {_PROGRAM}\b                 # the program, however it is spelled
    (?P<pre>(?:\s+(?:-[Cc]\s+[^\s;&|]+|-{{1,2}}[^\s;&|]+))*)   # pre-subcommand options; -C <path> / -c k=v take an argument
    (?P<sep>\s+)
    stash\b
    (?P<rest>[^;&|\n]*)          # the remainder of THIS command only
    """,
    re.VERBOSE,
)

# Nested interpreters: `sh -c '<payload>'` runs the payload as a command, so the
# payload must be scanned as one. This is the arm that repairs the regression
# _blank_quoted_spans introduced — blanking the quoted span hid the payload, so
# `bash -c 'echo x; git stash pop'` DENIED before that change and was ALLOWED
# after it. Recursing here restores the deny WITHOUT reopening the over-block,
# because only an interpreter's payload is reached into; every other quoted span
# is still blanked.
_NESTED_SHELL_RE = re.compile(
    r"""\b(?:ba|z|k|da)?sh\s+(?:-[A-Za-z]+\s+)*-c\s*(?P<q>['"])(?P<payload>.*?)(?P=q)""",
    re.VERBOSE | re.DOTALL,
)


def _guard_disabled( env=None ) -> bool:
    """True iff LUPIN_ALLOW_GIT_STASH is set truthy (the escape hatch)."""
    env = env if env is not None else os.environ
    return str( env.get( _ENV_FLAG, "" ) ).strip().lower() in _TRUE_VALUES


# The escape hatch written the way the deny message tells you to write it:
# `LUPIN_ALLOW_GIT_STASH=1 git st​ash drop <sha>`.
_INLINE_FLAG_RE = re.compile( rf"\b{_ENV_FLAG}=(?P<value>[^\s;&|]*)" )


def _hatch_in_prefix( prefix ) -> bool:
    """
    True iff an env-assignment prefix carries the escape-hatch flag, truthy.

    The deny message tells the reader to re-run with `LUPIN_ALLOW_GIT_STASH=1` inline.
    The hook is a separate process, so its os.environ never holds an inline `VAR=1 cmd` prefix.
    Closing the env-assignment bypass would close that hatch too, so the flag is read from the command.

    Requires:
        - prefix is the matched env-assignment / wrapper span, or None

    Ensures:
        - True only when the flag is assigned a truthy value in this invocation's
          own prefix, not somewhere else in the line, so `echo FLAG=1` before an
          unrelated mutation cannot disable the guard for it
        - never raises
    """
    if not prefix:
        return False
    found = _INLINE_FLAG_RE.search( prefix )
    if not found:
        return False
    return found.group( "value" ).strip().strip( "'\"" ).lower() in _TRUE_VALUES


def _first_subcommand( rest: str ) -> Optional[ str ]:
    """
    The first non-flag token after `stash`, or None for a bare `git stash`.

    Requires:
        - rest is the text following the `stash` token within one command

    Ensures:
        - returns the lowercased subcommand token when one is present
        - returns None when only flags follow (e.g. `git stash -u`), which is a
          bare push and must be treated as mutating by the caller
    """
    for token in rest.split():
        if token.startswith( "-" ):
            continue
        return token.lower()
    return None


def _deny_reason_for( subcommand: Optional[ str ] ) -> str:
    """Compose the deny text, naming the offending verb and its substitute."""
    verb = subcommand or "push"
    return (
        f"`git stash {verb}` is denied: the stash stack is REPO-GLOBAL, not "
        "per-worktree. This repo has ~50 worktrees and several live sessions, so "
        "your push races theirs and your pop can apply ANOTHER SESSION'S work "
        "into your tree — silently, if the changesets do not overlap, and then "
        "commit it under your name. That is not hypothetical; it happened on "
        "2026-08-23 (bug 1ebc9be3).\n"
        "USE INSTEAD:\n"
        "  · to HOLD work — a WIP commit on your own branch;\n"
        "  · to INSPECT an old version — a throwaway detached worktree at that "
        "sha. Prefer this: it cannot touch anybody's working tree.\n"
        "  · `git checkout <sha> -- <path>` is a LAST RESORT and only after "
        "`cp <path> <path>.bak` — it OVERWRITES the working-tree copy, including "
        "a peer's uncommitted work, and moves no HEAD, so there is no reflog "
        "entry to recover from.\n"
        "  · to undo your OWN edit — `cp` from a backup you took, in a worktree "
        "of your own. The `cp` fixes only WHICH BYTES come back; the write is "
        "identical, so it still overwrites a peer's edit made since your backup. "
        "Only a detached worktree closes that window.\n"
        "`git stash list` and `git stash show` are read-only and still allowed. "
        "If you own an entry and must clear it, name the COMMIT SHA (never "
        "`stash@{N}` — indices renumber on every drop) and re-run with "
        "LUPIN_ALLOW_GIT_STASH=1."
    )


# BALANCED quoted spans are blanked before matching (row e062580e, 2026-08-24).
#
# THE FALSE DENY THIS REMOVES. `_GIT_STASH_RE` looks for the phrase in "command
# position" -- start-of-string or just after one of `; & | ( \n`. It is a regex over
# the RAW string and knows nothing about shell quoting, so a separator INSIDE a quoted
# literal counted as a command position. Measured before the fix, three false denies:
# a semicolon, a pipe, and a paren, each inside a quoted literal.
#
# So a heredoc, a test table, or a doc snippet listing those commands was refused
# wholesale. That is authoring friction on a guard whose entire value is that nobody
# turns it off, and the row exists because it bit its own author within minutes of him
# demonstrating it. It then bit the seat that fixed it TWICE -- once writing the probe
# that measured it, once writing the patch that removed it.
#
# WHY THIS DOES NOT TRADE A FALSE DENY FOR A FALSE ALLOW, which is the trade the row
# says to refuse. The pattern requires a CLOSING quote, so it matches only BALANCED
# spans. An unbalanced quote -- where a naive strip would swallow to end-of-string and
# hide a real command -- matches nothing, and the text is left exactly as it was.
# Measured both ways: an unbalanced quote followed by a real mutating command still
# DENIES, before and after this change.
#
# Blanking to a SPACE rather than deleting: deletion could butt two fragments together
# and manufacture a command position nobody typed. A space can only ever separate.
#
# Still a regex, still total, so the fail-open backstop keeps its meaning -- this adds
# no path that can raise. shlex was considered and refused: it RAISES on unbalanced
# quotes, and the backstop would then ALLOW a real mutation.
_QUOTED_SPAN_RE = re.compile( '"[^"]*"' + "|" + "'[^']*'" )


def _blank_quoted_spans( command ):
    """
    Replace every balanced quoted span of a command with a single space.

    Ensures:
        - returns <command> with every balanced single- or double-quoted span
          replaced by a single space
        - returns <command> unchanged where quotes are unbalanced
        - never raises
    """
    return _QUOTED_SPAN_RE.sub( " ", command )


# Escapes and quotes used INSIDE a program name: `\git`, `g\it`, `'git'`,
# `"git"`. A backslash before a word character is shell noise that changes
# nothing about which program runs, and quoting a bare word is the same word.
_INNER_ESCAPE_RE = re.compile( r"\\(?=\w)" )
_BARE_QUOTE_RE   = re.compile( r"""(?<![\w])(['"])(\w[\w./-]*)\1""" )

# A backslash-newline is a line continuation: the shell joins the two lines into
# ONE command, so `git \<newline> stash pop` is a single invocation.
_LINE_CONTINUATION_RE = re.compile( r"\\\s*\n\s*" )


def _normalise_spelling( command ):
    """
    Remove degrees of freedom in how a command is written, not which one it is.

    Requires:
        - command is a str

    Ensures:
        - line continuations are joined, so a wrapped invocation reads as one
        - a backslash before a word character is dropped (`\\git` -> `git`)
        - a quoted bare word is unquoted (`'git'` -> `git`)
        - returns a string; never raises
    """
    command = _LINE_CONTINUATION_RE.sub( " ", command )
    command = _BARE_QUOTE_RE.sub( r"\2", command )
    command = _INNER_ESCAPE_RE.sub( "", command )
    return command


def _scannable_forms( command ):
    """
    Every text that must be checked for a mutating stash, given one raw command.

    Requires:
        - command is a non-empty str

    Ensures:
        - yields the command with quoted spans blanked (the outer shell's view)
        - yields the payload of each nested `sh -c` / `bash -c` separately, so an
          interpreter's argument is scanned as the command it will become
        - every yielded form has had its spelling normalised
        - never raises
    """
    # ORDER MATTERS, and getting it wrong is itself a bypass — I shipped it the
    # other way round first and measured `'git' stash pop` sailing through.
    # Normalise FIRST: a quoted BARE WORD like `'git'` is just the word, but if
    # the spans are blanked first the program name disappears entirely.
    # Unquoting bare words cannot reopen the over-block, because that pattern
    # matches a single word with no spaces — `"cd /tmp; git stash pop"` is
    # untouched by it and is still blanked below.
    yield _blank_quoted_spans( _normalise_spelling( command ) )

    for nested in _NESTED_SHELL_RE.finditer( command ):
        payload = nested.group( "payload" )
        if payload:
            yield _normalise_spelling( payload )


def stash_deny_reason(
    tool_name,
    tool_input,
    *,
    enabled : Optional[ bool ] = None,
    env     = None,
) -> Optional[ str ]:
    """
    Return a deny-reason string iff a Bash call mutates the shared stash stack.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict) whose "command"
          key carries the shell command, when present
        - enabled is None (resolved from env) or injected for testing

    Ensures:
        - None unless all hold: the guard is enabled, tool_name is Bash, and the
          command invokes a mutating `git stash` subcommand in command position
        - None for read-only `git stash list` / `git stash show`
        - FAIL-OPEN: any unexpected error → None
    """
    try:
        if enabled is None:
            enabled = not _guard_disabled( env )
        if not enabled:
            return None
        if tool_name not in BASH_TOOL_NAMES:
            return None
        if not isinstance( tool_input, dict ):
            return None
        command = tool_input.get( "command", "" )
        if not isinstance( command, str ) or not command:
            return None
        for form in _scannable_forms( command ):
            for match in _GIT_STASH_RE.finditer( form ):
                sub = _first_subcommand( match.group( "rest" ) )
                if sub in READONLY_SUBCOMMANDS:
                    continue
                if _hatch_in_prefix( match.group( "prefix" ) ):
                    continue
                return _deny_reason_for( sub )
        return None
    except Exception:                    # pragma: no cover - fail-open backstop: every statement above is total over the validated inputs, so no input reaches it; kept because a hot-path guard must never raise
        return None


def build_stash_deny_response( reason: str ) -> dict:
    """
    Build the PreToolUse deny envelope (mirrors build_subagent_deny_response).

    Ensures:
        - returns { hookSpecificOutput: { hookEventName: "PreToolUse",
          permissionDecision: "deny", permissionDecisionReason: <reason> } }
    """
    return {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : reason,
        }
    }
