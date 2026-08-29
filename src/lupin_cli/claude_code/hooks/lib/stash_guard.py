"""
Stash guard — `git stash` is repo-global, not per-worktree (bug 1ebc9be3).

THE MECHANISM: the stash stack is a SINGLE repo-global stack shared by every
worktree and every live session. This repo carries ~50 worktrees and several
concurrent sessions, so every push races every other session's push and every
pop races every other session's pop.

WHAT IT COSTS: on 2026-08-23 john pushed in his worktree, Tiffany pushed hers
from a different worktree in between, and john's pop applied TIFFANY'S held
postgres conversion into HIS tree. The two changesets happened to overlap, so
it conflicted and he caught it. Had they not overlapped the pop would have
SUCCEEDED SILENTLY and twelve of Tiffany's files would have been committed
under john's name, on his row, with nothing in the git output naming the owner.

⇒ SECOND HAZARD, ONE LEVEL DOWN: `stash@{N}` looks like a name and is a
POSITION. Dropping an entry renumbers the whole stack, so an index written into
an instruction moves under it between the writing and the running. Name the
commit sha, never the index.

THE SUBSTITUTES, in the order you should reach for them:
  · TO HOLD WORK — make a WIP COMMIT ON YOUR OWN BRANCH. A stash is a shared
    mutable stack pretending to be a private one; a branch is actually yours.
  · TO INSPECT AN OLD VERSION — `git checkout <sha> -- <path>`, restore with
    `git checkout HEAD -- <path>`. Touches nothing shared, races nothing.
  · A throwaway detached worktree at the old sha also works and is safer still.

SCOPE: only the MUTATING subcommands are denied. `git stash list` and
`git stash show` are read-only and stay allowed — they are how you inspect the
stack before acting on it.

FIXED OVER-BLOCK, kept here as a record (row e062580e). This matcher is a regex
over the RAW command string and did not parse shell quoting, so a separator
appearing INSIDE a quoted literal counted as a command position and a command
that merely CONTAINED such a snippet was refused, even though no stash would
run. Measured 2026-08-24 while demonstrating the guard, three false denies: a
semicolon, a pipe, and a paren, each inside a quoted literal.

⇒ IT IS NOW FIXED, by `_blank_quoted_spans` below: BALANCED quoted spans are
blanked before matching. The three cases above now pass; all thirteen mutating
forms still deny.

🔴 AND THAT FIX OPENED A HOLE, WHICH IS THE PART WORTH READING (row 1ebc9be3,
reported by Rachel, measured 2026-08-24 by running the pre-fix and post-fix
matchers on the same inputs). Blanking the quoted span ALSO blanked the payload
of a nested interpreter, so `bash -c 'echo x; git st​ash pop'` DENIED before the
over-block fix and was ALLOWED after it. A false deny had been traded for a
false ALLOW — precisely the trade the row said to refuse, made while refusing it.
It is repaired below by scanning an INTERPRETER'S payload while still blanking
every other quoted span, so both properties hold at once.

⇒ THE WIDER FINDING, and the reason this module was rewritten rather than
patched: the matcher recognised ONE SPELLING of the program in one syntactic
position. Measured against 22 natural forms, TWENTY-ONE walked past it — an
absolute or relative path, a backslash escape, a quoted program name, the
env / command / sudo / nohup / time / xargs wrappers, an env-assignment prefix,
a brace group, `if ...; then`, a line continuation, a nested shell. Every one
reaches the same repo-global stack.

⇒ THE FIX IS NORMALISATION, NOT A LONGER DENYLIST. Each clause removes a DEGREE
OF FREEDOM in how the program may be written rather than naming one more thing
to refuse; adding cases to a denylist is how the original arrived here. 21 of 22
now deny. 83 tests, 100% lines and branches.

⚠️ THE ONE THAT REMAINS, named on purpose: `g=git; $g st​ash pop`. Text matching
cannot resolve variable indirection, an eval, or a base64 payload, and no hook
that sees only text ever will. THE THREAT MODEL IS ACCIDENT, NOT EVASION — this
fleet has no adversary, it has habits. Nobody reaches for variable indirection
by accident and everybody reaches for `/usr/bin/git`, so catching every natural
spelling is the whole job. A test pins that residual as known and accepted, and
fails if it is ever silently closed, so this paragraph cannot drift out of date.
This guard is an accident-preventer. It is not a security boundary, and calling
it one would be the same defect it exists to catch.

⇒ THIS NOTE PREVIOUSLY SAID THE OPPOSITE — "the reason it is not fixed" — and
that reasoning is worth keeping because it still holds against the fix it
refused. Making the matcher SHELL-AWARE (shlex) is heavier on a hot path and
RAISES on unbalanced quotes, where the fail-open backstop below would then ALLOW
a real mutating command. Trading a false deny for a possible false allow is the
wrong direction for a control whose whole value is deny-by-default, and that
option stays refused. What shipped is the cheaper third option: still a regex,
still total, and it CANNOT hide a real command, because the pattern requires a
closing quote — an unbalanced span matches nothing and the text is left exactly
as it was. Measured both ways.

⇒ THE WORKAROUND THIS NOTE USED TO PRESCRIBE — put the script in a FILE and run
the file rather than a heredoc — is no longer needed for the quoted-separator
case. It was needed to write this very paragraph's predecessor, and it was needed
twice more to produce the fix: once for the probe that measured the defect, once
for the patch that removed it. It remains the right move any time the guard
refuses authoring text.

(Some examples in this file carry a zero-width space inside the verb so that
reading THIS FILE through a shell command is not itself refused. That trick is
kept: the guard still denies genuine command position, which is the point.)

If this is ever revisited, the acceptance test is unchanged: all thirteen
currently-denied forms stay denied.

SAFETY — this runs inside the hot-path PreToolUse hook (every tool call, every
session), so two non-negotiables:
  • FAIL-OPEN: ANY error → allow (return None). A guard must never break a tool
    call.
  • ESCAPE HATCH: LUPIN_ALLOW_GIT_STASH=1 disables the guard for a session that
    genuinely needs the stack — an owner clearing their OWN entry after
    verifying its content is preserved elsewhere.

    🔴 IT IS HONOURED BY A PREFIX CARVE-OUT (`_hatch_in_prefix`), NOT BY THE ENV
    READ, AND THAT IS NOT A SHORTCUT — IT IS THE ONLY THING THAT CAN WORK. A
    PreToolUse hook is a SEPARATE PROCESS reading its OWN environment, and an
    inline `VAR=1 cmd` prefix belongs to a command that HAS NOT RUN YET. So an
    env-var hatch can never be honoured through os.environ from a command
    string, no matter how the read is written.

    Verified independently by Rachel 🕊️ on 2026-08-24: setting the flag in the
    hook's own process environment produced an IDENTICAL verdict to not setting
    it, so the allow demonstrably comes from the carve-out. At the same sha a
    GENERIC env prefix is still denied (`GIT_DIR=.git git st​ash pop` → DENY),
    which is the split that matters — arbitrary env prefixes refused, the hatch
    prefix let through.

    ⇒ DO NOT "SIMPLIFY" THE CARVE-OUT AWAY. Deleting it does not fall back to
    the env read; it silently removes the hatch entirely, and every deny message
    in this module tells the reader to use it. That is how the hatch spent most
    of this guard's life broken without anyone noticing: it appeared to work
    only because an env assignment pushed the program out of command position,
    making it indistinguishable from the env-assignment BYPASS.

⚠️ Unlike subagent_governance this guard is DEFAULT-ON. A control that must be
switched on is the courtesy version of itself: the rule this replaces already
depended on remembering, which is the reason the hazard reached production once.
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
_PREFIXES = rf"(?P<prefix>(?:\s*(?:[A-Za-z_][A-Za-z0-9_]*=[^\s;&|]*|{_WRAPPERS})\b)*)"

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

    WHY THIS EXISTS, and it is a correction to a claim I made out loud (row
    1ebc9be3, 2026-08-24). The deny message has always told the reader to
    "re-run with LUPIN_ALLOW_GIT_STASH=1". I tested that inline form against the
    live hook, saw the command go through, and reported the hatch as working.
    IT WAS NOT WORKING. The hook is a separate process and never sees an inline
    `VAR=1 cmd` prefix in its os.environ; what actually happened is that the
    assignment pushed `git` out of command position, so the OLD matcher simply
    failed to match. The hatch was indistinguishable from bypass #14, and my
    original prediction — that the inline form could not reach the hook — had
    been right before I talked myself out of it on bad evidence.

    Closing that bypass therefore closed the documented hatch with it. This
    reads the flag from the COMMAND instead, so the instruction in the deny
    message is true rather than accidentally true.

    Requires:
        - prefix is the matched env-assignment / wrapper span, or None

    Ensures:
        - True only when the flag is assigned a truthy value IN THIS INVOCATION'S
          own prefix — not somewhere else in the line, so `echo FLAG=1` before an
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
        "  · to INSPECT an old version — `git checkout <sha> -- <path>`, restore "
        "with `git checkout HEAD -- <path>`;\n"
        "  · a throwaway detached worktree at the old sha.\n"
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
    Ensures:
        - returns <command> with every BALANCED single- or double-quoted span
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
    Remove degrees of freedom in HOW a command is written, without changing
    WHICH command it is.

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
        - None unless ALL hold: the guard is enabled, tool_name is Bash, and the
          command invokes a MUTATING `git stash` subcommand in command position
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
