"""
Merge-head guard — a `git commit` during a live merge CONCLUDES that merge.

THE MECHANISM. A merge is a two-step operation over tree-global state: `git
merge` stages the result and leaves MERGE_HEAD set, and a later `git commit`
writes the merge commit. Between those two steps the merge belongs to the tree,
not to the session that started it, so ANY seat committing in that tree in the
meantime concludes somebody else's merge under its own message.

WHAT IT COST, 2026-08-31 (row f3306404, reported by Maya and Rachel). A merge one
seat had staged was live when another committed in the same tree. The commit
consumed it. Parentage was lost, the lane landed with one parent, all ten shas
came out non-ancestors, and a known-defective assertion went live on the working
branch. Four seats spent about an hour finding and repairing it, ending at
`f3e9b41a`. Nobody could see it happening while it happened.

WHY NO EXISTING HABIT CATCHES IT, which is the finding that made this worth a
hook rather than a note:

    git status                 says plainly that a merge is in progress
    git status --porcelain     says NOTHING once conflicts are resolved and staged
    git status --porcelain=v2  says NOTHING either

Measured on 2026-08-31 in a scratch repo: with a live MERGE_HEAD and the conflict
resolved and staged, v1 printed `M  f.txt` and v2 printed one `1 M.` line, while
the long form printed "All conflicts fixed but you are still merging."

⇒ So every script, alias and glance built on a machine-readable status is blind to
precisely the dangerous state, and it is blind in the SAFE-LOOKING direction.

THE RELIABLE CHECK IS PLUMBING:  `git rev-parse -q --verify MERGE_HEAD`
Exit 0 with a sha = a merge is live. Non-zero = none. Worktree-aware by
construction, because git resolves the ref through the worktree's own git dir.

🔴 DO NOT USE THE PATH FORM. `test -f .git/MERGE_HEAD` is wrong, and wrong in the
safe-looking direction: in a LINKED WORKTREE `.git` is a FILE, not a directory, so
the path does not exist and the test reports NO MERGE while one is live. Measured
in a scratch linked worktree with a live merge: the path test said no-merge and
`rev-parse` returned the sha. `test_merge_head_guard.py` measures all of that
against real git rather than asserting it.

The path form is right in ONE location — the main checkout — and wrong in every
linked worktree, which is where this fleet's work happens. DO NOT QUOTE A COUNT;
it moves daily as seats come and go. Re-derive it:

    git worktree list --porcelain | awk '/^worktree /{print $2}' \\
      | while read -r w; do [ -f "$w/.git" ] && echo linked; done | wc -l

Snapshot for scale only, not to be quoted: 102 linked of 103 trees, 2026-08-31.
Row f3306404 recorded 92 nine hours earlier, which is why the command is here and
the number is not.

WHAT THIS GUARD DOES: on a Bash `git commit` with MERGE_HEAD live in the target
tree, DENY, name the merge sha, and say what committing would do. Rick ruled the
shape by voice on 2026-08-31 ~20:05 EDT — a hard deny over a warning, because a
warning in a busy log is not a control.

SCOPE, as ratified:
  · DENY, not advise.
  · GLOBAL, not conditional on the branch. A guard with fewer conditions has fewer
    ways to be wrong, and stash_guard set that precedent.
  · ESCAPE HATCH for the seat that STARTED the merge and must finish it.
  · FAIL OPEN when the check itself errors.

⚠️ FOUR RESIDUALS, NAMED RATHER THAN HIDDEN.

1. A SQUASH MERGE IS INVISIBLE TO THIS CHECK, and it is the shape that produces
   the one-parent commit the founding incident recorded. Measured 2026-08-31:
   `git merge --squash` stages the merge, writes SQUASH_MSG, and sets NO
   MERGE_HEAD — `rev-parse -q --verify MERGE_HEAD` exits 1 while a merge is
   plainly in flight, and the resulting commit has one parent. SQUASH_MSG would
   be a viable second probe (git clears it on commit, so it cannot linger into a
   false deny), but widening the check beyond MERGE_HEAD is not this row's
   ratified scope. `test_merge_head_guard.py` pins the gap so it cannot drift out
   of mind, and the question is with the manager.

2. A PARTIAL COMMIT CANNOT CONSUME A MERGE — git refuses it first. Measured:
   `git commit -m x -- <paths>` during a live merge dies with "fatal: cannot do a
   partial commit during a merge", while a plain `git commit -m x` succeeds and
   produces a two-parent merge commit under the committer's own message. The
   guard still refuses the pathspec shape, deliberately: denying it costs a
   command git was going to reject anyway, and carving it out would add a
   condition whose only effect is another way to be wrong.

3. A `git commit` AT THE START OF A LINE INSIDE A HEREDOC IS REFUSED, and that
   is a CHOICE. ⚠️ THE FIRST CUT OF THIS NOTE SAID "quoted inside a heredoc",
   which is WIDER THAN WHAT IS TRUE, and the test written to pin it FAILED and
   corrected me. Measured: mid-line prose (`the rule is: git commit takes ...`)
   does NOT match, because `git` is not in command position there; a line that
   BEGINS `git commit` does, because a newline opens a command slot.
   `commit_scope_guard` strips heredoc bodies before matching, because text that
   is DATA read as COMMAND made it refuse the very commit carrying its own
   message. This guard deliberately does NOT strip, because the direction of harm
   differs: there a false deny blocks an honest commit at any time, whereas here
   it can only fire while a merge is ALREADY LIVE in the tree — a state in which
   being stopped and told so is nearly always the right outcome. Not stripping
   also means a heredoc that opens and never closes cannot hide a real commit
   behind it. The cost is one hatch prefix for a seat writing prose about
   `git commit` mid-merge, and a test pins the behaviour so it stays a decision
   rather than becoming a surprise.

4. `git merge --continue` ALSO CONCLUDES A MERGE, and this guard does not see it
   because it is not a `git commit`. Measured: with MERGE_HEAD live, it produces a
   two-parent merge commit and clears MERGE_HEAD, exactly as a plain commit does.
   Not covered because Rick ruled on the COMMIT, and because it differs in the one
   way that matters to the founding incident: it writes git's own default merge
   message rather than the running seat's, so a peer's merge does not land under
   somebody else's words. Ownership confusion still applies. Under an accident
   threat model this is thin — a seat types `git merge --continue` only when it
   believes it owns a merge, whereas `git commit` is what everyone types all day.

THREAT MODEL — ACCIDENT, NOT EVASION. The matcher is `commit_scope_guard`'s,
reused rather than re-spelled so there is one answer in the tree to "is this a
git commit". It recognises the natural spellings in command position and nothing
claims completeness; a seat determined to route around it can.

SAFETY — this runs inside the hot-path PreToolUse hook, so:
  • FAIL-OPEN: ANY error → allow (return None). The `git rev-parse` read is
    bounded by a timeout, and every failure mode of it — not a repo, git absent,
    a directory that does not exist, a slow disk — returns None and allows.
  • ESCAPE HATCH: `LUPIN_ALLOW_MERGE_COMMIT=1 git commit ...`.

    🔴 HONOURED BY A PREFIX CARVE-OUT, NOT AN ENV READ, and that is not a
    shortcut — it is the only thing that can work. A PreToolUse hook is a SEPARATE
    PROCESS reading its OWN environment, and an inline `VAR=1 cmd` prefix belongs
    to a command that HAS NOT RUN YET. stash_guard learned this the expensive way:
    its documented hatch was broken for most of its life and appeared to work only
    because the env assignment pushed the program out of command position. The
    process environment is ALSO honoured, for a session deliberately exported into
    merge work, but the prefix is what makes the deny message's instruction true.

⚠️ THE FRICTION THIS BUYS, stated so it can be re-measured rather than defended:
the seat that legitimately concludes its own merge must use the hatch every time.
That is the ratified trade — the alternative is guessing which seat owns a merge
from a tree that records no owner.
"""
import os
import re
import subprocess
from typing import Optional

from lupin_cli.claude_code.hooks.lib.commit_scope_guard import git_commit_match


BASH_TOOL_NAMES = ( "Bash", )

_ENV_FLAG    = "LUPIN_ALLOW_MERGE_COMMIT"
_TRUE_VALUES = ( "1", "true", "on", "yes" )

# How long the MERGE_HEAD read may take before the guard gives up and allows.
GIT_TIMEOUT_SECONDS = 5

# THE ONLY CHECK. Not a path test, not a status parse — see the module docstring
# for the measurement behind both refusals.
MERGE_HEAD_ARGV = ( "git", "rev-parse", "-q", "--verify", "MERGE_HEAD" )

_INLINE_FLAG_RE = re.compile( rf"\b{_ENV_FLAG}=(?P<value>[^\s;&|]*)" )

# `git -C <path> commit` runs in ANOTHER tree, so that is the tree whose merge
# state decides the verdict. Case-sensitive: `-c key=val` is a config override,
# not a directory.
_DASH_C_RE = re.compile( r"-C\s+(?P<path>[^\s;&|]+)" )

# 🔴 `cd <tree> && git commit` IS THE SHAPE THIS FLEET ACTUALLY USES, and without
# this the guard checks the wrong tree. MEASURED 2026-08-31 against the real hook,
# with a live merge in a linked worktree and the hook standing in the main checkout:
#
#     git -C <merge tree> commit       DENY     <- -C was already handled
#     cd <merge tree> && git commit    ALLOWED  <- the miss
#
# The Bash tool resets its working directory to the session root on every call, so a
# seat working in a worktree types `cd <worktree> && git ...` all day and the hook's
# own cwd is never the tree being committed to. A guard that misses that shape misses
# nearly every commit in the fleet.
#
# `cd` in COMMAND POSITION only, so a `cd` inside an argument is not read as one.
_CD_RE = re.compile(
    r"(?:^|[;&|(){}\n]|\bthen\b|\bdo\b|\belse\b)\s*cd\s+(?P<path>[^\s;&|]+)"
)


def _guard_disabled( env=None ) -> bool:
    """
    True iff the escape-hatch flag is set truthy in the process environment.

    Requires:
        - env is None (real os.environ) or a mapping injected for testing

    Ensures:
        - True only for a recognised truthy spelling of the flag
        - never raises
    """
    env = env if env is not None else os.environ
    return str( env.get( _ENV_FLAG, "" ) ).strip().lower() in _TRUE_VALUES


def _hatch_in_prefix( prefix ) -> bool:
    """
    True iff THIS invocation's own env-assignment prefix carries the hatch, truthy.

    Requires:
        - prefix is the matched env-assignment / wrapper span, or None

    Ensures:
        - reads the flag from the COMMAND, never from os.environ — see the module
          docstring for why an env read alone cannot honour an inline prefix
        - scoped to this invocation's prefix, so an unrelated `echo FLAG=1`
          earlier in the line cannot unlock a later commit
        - never raises
    """
    if not prefix: return False

    found = _INLINE_FLAG_RE.search( prefix )
    if not found: return False

    return found.group( "value" ).strip().strip( "'\"" ).lower() in _TRUE_VALUES


def _target_directory( command, match, cwd=None ):
    """
    The directory whose merge state governs this commit.

    Two things move a commit into another tree, and BOTH are common here:
      · `cd <path> && git commit` — the Bash tool resets its working directory to
        the session root every call, so a seat working in a worktree types this all
        day and the hook's cwd is never the tree being committed to
      · `git -C <path> commit` — moves the whole invocation

    They compose in that order, each relative to the last, which is exactly
    os.path.join's rule: a later absolute path wins outright.

    Requires:
        - command is the raw Bash command
        - match is the git_commit_match result for it
        - cwd is the directory the hook is standing in, or None for the process cwd

    Ensures:
        - returns cwd when the command names neither a cd nor a -C
        - otherwise returns the composed target, resolved against cwd, with ~ expanded
        - FALLS BACK TO cwd when the composed path is not an existing directory, so a
          `cd` misread out of a quoted literal checks the session's own tree rather
          than checking nowhere — the fallback is what makes the loose scan safe
        - only a `cd` BEFORE the commit counts; one after it has not run yet
        - never raises

    ⚠️ It follows the LAST `cd` before the commit and does not model subshells or
    conditionals. Under an accident threat model that is the whole job; a misread
    lands on the existence check above and degrades to today's behaviour.
    """
    base  = cwd or os.getcwd()
    parts = []

    for found in _CD_RE.finditer( command[ :match.start() ] ):
        path = found.group( "path" )
        if path != "-":                       # `cd -` is the previous directory, unknowable here
            parts = [ os.path.expanduser( path ) ]

    parts.extend( _DASH_C_RE.findall( match.group( "pre" ) or "" ) )

    if not parts: return cwd

    target = os.path.join( base, *parts )
    return target if os.path.isdir( target ) else cwd


def _live_merge_head( cwd=None ) -> Optional[ str ]:
    """
    The MERGE_HEAD sha iff a merge is live in <cwd>, else None.

    Requires:
        - cwd is a directory path, or None for the process cwd

    Ensures:
        - returns the sha string when `git rev-parse -q --verify MERGE_HEAD`
          exits 0 with output
        - returns None when it exits non-zero, when git is absent, when the
          directory does not exist, or when the read times out — every one of
          which ALLOWS the commit
        - never raises
    """
    try:
        done = subprocess.run(
            list( MERGE_HEAD_ARGV ),
            cwd            = cwd,
            capture_output = True,
            text           = True,
            timeout        = GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None

    if done.returncode != 0: return None

    return done.stdout.strip() or None


def _deny_reason_for( merge_sha: str ) -> str:
    """
    Compose the refusal: what is live, what committing would do, how to proceed.

    Requires:
        - merge_sha is the live MERGE_HEAD sha

    Ensures:
        - names the sha, so the committer can identify the merge before acting
        - names the machine-readable blindness, because the seat's next instinct
          is to check `git status --porcelain` and be reassured by nothing
        - gives the hatch verbatim, one line, copyable
        - NAMES ITS OWN RESIDUALS. A residual recorded only in a module docstring
          and a test is invisible to the person who actually meets the guard, who
          will reasonably assume it covers every way a merge gets concluded. The
          refusal is the only text a seat reads, so the scope belongs in it.
    """
    return (
        f"`git commit` is denied: A MERGE IS LIVE IN THIS TREE (MERGE_HEAD {merge_sha[ :12 ]}).\n"
        "Committing now CONCLUDES that merge under YOUR message. A merge is a two-step "
        "operation over tree-global state — staged by one command, written by the next — "
        "so between those steps it belongs to the tree, not to whoever started it. That "
        "happened on 2026-08-31 (row f3306404): parentage was lost, the lane landed with "
        "one parent, ten shas came out non-ancestors, and four seats spent an hour "
        "repairing it.\n"
        "DO NOT CHECK `git status --porcelain` — BOTH machine-readable forms show NOTHING "
        "once the conflicts are staged. Use the long `git status`, or "
        "`git rev-parse -q --verify MERGE_HEAD`.\n"
        "IF THE MERGE IS YOURS and you mean to conclude it, re-run with:\n"
        "  LUPIN_ALLOW_MERGE_COMMIT=1 git commit ...\n"
        "IF IT IS NOT YOURS, it belongs to another seat mid-operation. Do not abort it and "
        "do not commit around it — ask the owner to finish, or wait. Your own work is safe "
        "where it is; nothing here loses it.\n"
        "WHAT THIS GUARD DOES NOT COVER, so you do not read it as more than it is: "
        "`git merge --continue` also concludes a merge and is NOT checked, and a "
        "`git merge --squash` sets no MERGE_HEAD so it is invisible here. Seeing no "
        "refusal is not evidence that no merge is in flight."
    )


def merge_head_deny_reason(
    tool_name,
    tool_input,
    *,
    enabled      : Optional[ bool ] = None,
    env          = None,
    cwd          = None,
    merge_reader = None,
) -> Optional[ str ]:
    """
    Return a deny-reason string iff a Bash `git commit` would conclude a live merge.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict) whose "command" key
          carries the shell command, when present
        - enabled is None (resolved from env) or injected for testing
        - merge_reader is None (real git) or injected for testing

    Ensures:
        - None unless ALL hold: the guard is enabled, tool_name is Bash, the
          command invokes `git commit` in command position, the hatch prefix is
          absent, and MERGE_HEAD resolves in the target tree
        - the target tree honours BOTH `cd <path> &&` and `git -C <path>`, composed
          in that order; an unresolvable target falls back to cwd
        - FAIL-OPEN: any unexpected error → None
    """
    try:
        if enabled is None:
            enabled = not _guard_disabled( env )
        if not enabled: return None
        if tool_name not in BASH_TOOL_NAMES: return None
        if not isinstance( tool_input, dict ): return None

        command = tool_input.get( "command", "" )
        if not isinstance( command, str ) or not command: return None

        match = git_commit_match( command )
        if match is None: return None

        if _hatch_in_prefix( match.group( "prefix" ) ): return None

        target    = _target_directory( command, match, cwd )
        merge_sha = ( merge_reader or _live_merge_head )( target )
        if not merge_sha: return None

        return _deny_reason_for( merge_sha )

    except Exception:
        # FAIL-OPEN BACKSTOP, and it is EXERCISED rather than asserted: a test
        # injects a merge_reader that raises and asserts the commit is allowed.
        # stash_guard's equivalent carries `pragma: no cover` because nothing can
        # reach it; here the reader is a seam, so the branch is real and a pragma
        # would be a claim in place of a measurement.
        return None


def build_merge_head_deny_response( reason: str ) -> dict:
    """
    Build the PreToolUse deny envelope (mirrors build_stash_deny_response).

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
