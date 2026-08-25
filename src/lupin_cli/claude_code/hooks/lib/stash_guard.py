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

KNOWN OVER-BLOCK, AND IT IS DELIBERATE (row e062580e). This is a regex over the
RAW command string; it does not parse shell quoting. So a separator appearing
INSIDE a quoted string still counts as a command position, and a command that
merely CONTAINS such a snippet is refused even though no stash would run.
Measured 2026-08-24 while demonstrating the guard:

    DENIED   x = "cd /tmp; git st​ash pop"     separator inside a quoted literal
    DENIED   x = "foo | git st​ash push"       pipe inside a quoted literal
    allowed  x = "git st​ash pop"              quoted literal, no separator first
    allowed  grep "git st​ash" docs/           the phrase as a plain argument
    allowed  echo 'git st​ash pop'             the phrase inside a quoted string

(The examples above carry a zero-width space inside the verb so that reading
THIS FILE through a shell command is not itself refused — which is the clearest
statement of the problem this note describes.)

⇒ THE WORKAROUND, because you WILL hit this writing a test table or a doc
snippet: put the script in a FILE and run the file rather than piping it through
a heredoc, or edit with the Write/Edit tools instead of a shell redirect. Both
were needed to produce this very paragraph.

⇒ AND THE REASON IT IS NOT "FIXED": every case above is a false DENY, never a
false ALLOW. Making the matcher shell-aware (shlex) is heavier on a hot path and
can RAISE on unbalanced quotes — where the fail-open backstop below would then
ALLOW a real mutating command. Trading a false deny for a possible false allow
is the wrong direction for a control whose entire value is deny-by-default. If
it is ever revisited, the acceptance test is that all thirteen currently-denied
forms stay denied.

SAFETY — this runs inside the hot-path PreToolUse hook (every tool call, every
session), so two non-negotiables:
  • FAIL-OPEN: ANY error → allow (return None). A guard must never break a tool
    call.
  • ESCAPE HATCH: LUPIN_ALLOW_GIT_STASH=1 disables the guard for a session that
    genuinely needs the stack — an owner clearing their OWN entry after
    verifying its content is preserved elsewhere.

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
_GIT_STASH_RE = re.compile(
    r"""
    (?:^|[;&|(]|\n)              # command position
    \s*
    git\b                        # the program
    (?P<pre>(?:\s+(?:-[Cc]\s+[^\s;&|]+|-{1,2}[^\s;&|]+))*)   # pre-subcommand options; -C <path> / -c k=v take an argument
    (?P<sep>\s+)
    stash\b
    (?P<rest>[^;&|\n]*)          # the remainder of THIS command only
    """,
    re.VERBOSE,
)


def _guard_disabled( env=None ) -> bool:
    """True iff LUPIN_ALLOW_GIT_STASH is set truthy (the escape hatch)."""
    env = env if env is not None else os.environ
    return str( env.get( _ENV_FLAG, "" ) ).strip().lower() in _TRUE_VALUES


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
        for match in _GIT_STASH_RE.finditer( _blank_quoted_spans( command ) ):
            sub = _first_subcommand( match.group( "rest" ) )
            if sub in READONLY_SUBCOMMANDS:
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
