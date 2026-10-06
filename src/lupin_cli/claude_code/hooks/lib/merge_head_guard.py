"""
Denies a Bash `git commit` while a merge or squash is staged and unconcluded in the tree.

The mechanism: `git merge` stages the result and leaves MERGE_HEAD set, and a later `git commit` writes the merge commit. Between those steps the merge belongs to the tree, not to the session that started it. Any seat committing meanwhile concludes someone else's merge under its own message, with parentage lost.

No existing habit catches it. `git status` says a merge is in progress, but `--porcelain` and `--porcelain=v2` say nothing once conflicts are staged. Scripts built on machine-readable status are blind to the dangerous state, in the safe-looking direction. The reliable check is plumbing: `git rev-parse -q --verify MERGE_HEAD` exits 0 with a sha when a merge is live, and it is worktree-aware. Never use `test -f .git/MERGE_HEAD`: in a linked worktree `.git` is a file, so it reports no merge while one is live. Never quote a count of linked trees; re-derive it with `git worktree list --porcelain`. `test_merge_head_guard.py` measures these behaviours against real git rather than asserting them.

Scope: on a Bash `git commit` with a merge live in the target tree, the guard denies. For a live MERGE_HEAD the message names the merge sha; for a squash there is no sha to name. Either way it says what committing would do. It denies rather than advises, because a warning in a busy log is not a control. The guard is global, not conditional on the branch, since fewer conditions are fewer ways to be wrong. It has an escape hatch for the seat that started the merge, and it fails open when the check errors.

There are two probes because MERGE_HEAD alone would have been silent through the founding incident. A commit made while MERGE_HEAD is live always records the merge parent, yet the real commit had one parent. So either `git merge --squash` staged it, which sets no MERGE_HEAD, or a merge was live earlier and cleared. The SQUASH_MSG probe covers the squash route. The other route cannot be detected, since nothing is left in the tree. Claiming the guard would have prevented the incident overstates it; it covers the squash route.

Residuals:
  1. Closed: a squash merge was invisible to the MERGE_HEAD check. Kept so nobody simplifies back to one probe.
  2. A partial commit (`git commit -m x -- <paths>`) cannot consume a merge, since git refuses it. The guard still refuses that shape, because carving it out adds a way to be wrong.
  3. A line beginning `git commit` inside a heredoc is refused, as a choice. Mid-line prose does not match. `commit_scope_guard` strips heredoc bodies because its false denies block honest commits at any time. Here a false deny fires only while a merge is live, when being stopped is nearly always right. Not stripping also stops an unclosed heredoc hiding a commit. The cost is one hatch prefix for a seat writing prose about `git commit` mid-merge. A test pins the behaviour so it stays a decision rather than a surprise.
  4. `git merge --continue` also concludes a merge and is not seen, because it is not a `git commit`. It writes git's own merge message, not the running seat's, so it is thinner. Under an accident threat model the gap is thin, since a seat types it only when it believes it owns a merge, whereas `git commit` is typed all day.

The threat model is accident, not evasion. The matcher is the one `commit_scope_guard` uses, so the tree has one answer to "is this a git commit". A seat determined to route around it can.

Safety: this runs in the hot-path PreToolUse hook, so any error allows (return None). The `git rev-parse` read has a timeout, and git absent, not a repo or a slow disk also allow. The escape hatch is `LUPIN_ALLOW_MERGE_COMMIT=1 git commit ...`, honoured by a prefix carve-out. A hook is a separate process with its own environment. An inline `VAR=1 cmd` prefix belongs to a command that has not run yet, so an env read alone cannot honour it. The process environment is also honoured, for a session exported into merge work.

Landing note: a clean `--no-ff` merge auto-commits inside one `git merge`, so it opens no window and never reaches this guard. The window is a merge that does not auto-commit: a conflict, or `--no-commit`. Prefer a landing that cannot leave a merge staged but uncommitted in a tree others work in. One safe order: merge the working branch into the lane branch in your own worktree and verify green there. Then fast-forward, so the shared tree never holds a merge in flight. A conflicting merge leaves MERGE_HEAD live, so the guard refuses until the hatch is used. That friction is the ratified trade, since a tree records no owner.
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

# THE SECOND PROBE. `git merge --squash` stages the whole merge and sets NO
# MERGE_HEAD, so the first probe is blind to it — and the resulting commit has ONE
# parent and loses the lane's ancestry, which is the shape the founding incident
# ended in. Rick ruled the widening by voice, 2026-08-31 ~21:05 EDT, after being
# shown that the MERGE_HEAD-only guard would not have caught its own incident.
#
# `--git-path` resolves through the worktree's own git dir, so this is worktree-
# aware for the same reason `rev-parse --verify` is; never build the path by hand.
#
# ⚠️ MEASURED BEFORE SHIPPING, because a file that LINGERS would be a permanent
# false refusal for every seat that ever abandoned a squash:
#     after `git merge --squash`   PRESENT   <- the state to catch
#     after the commit             absent    <- git clears it
#     after `git reset --hard`     absent    <- the normal abandon path clears it
#     after an ordinary merge      absent    <- cannot be confused with MERGE_HEAD
# Both real ways out of a squash clear it, so it cannot strand a seat.
SQUASH_MSG_ARGV = ( "git", "rev-parse", "--git-path", "SQUASH_MSG" )

# Which in-flight state was found. They need different words: one names a sha the
# committer can look up, the other has none to name.
KIND_MERGE  = "merge"
KIND_SQUASH = "squash"

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
    True iff this invocation's own env-assignment prefix carries the hatch, truthy.

    Requires:
        - prefix is the matched env-assignment / wrapper span, or None

    Ensures:
        - reads the flag from the command, never from os.environ — see the module
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

    Both `cd <path> && git commit` and `git -C <path> commit` move a commit into another tree.
    The Bash tool resets its working directory every call, so the hook's cwd is rarely that tree.
    They compose in that order, each relative to the last, as os.path.join does: a later absolute path wins.

    Requires:
        - command is the raw Bash command
        - match is the git_commit_match result for it
        - cwd is the directory the hook is standing in, or None for the process cwd

    Ensures:
        - returns cwd when the command names neither a cd nor a -C
        - otherwise returns the composed target, resolved against cwd, with ~ expanded
        - falls back to cwd when the composed path is not an existing directory, so a
          `cd` misread out of a quoted literal checks the session's own tree rather
          than checking nowhere — the fallback is what makes the loose scan safe
        - only a `cd` before the commit counts; one after it has not run yet
        - never raises

    It follows the last `cd` before the commit and does not model subshells or
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
          which allows the commit
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


def _squash_in_flight( cwd=None ) -> bool:
    """
    True iff a `git merge --squash` is staged and unconcluded in <cwd>.

    Requires:
        - cwd is a directory path, or None for the process cwd

    Ensures:
        - asks git for the SQUASH_MSG path rather than building one, so it is
          worktree-aware exactly as the MERGE_HEAD probe is
        - returns False on any failure — git absent, not a repo, a timeout, a
          missing directory — every one of which allows the commit
        - never raises
    """
    try:
        done = subprocess.run(
            list( SQUASH_MSG_ARGV ),
            cwd            = cwd,
            capture_output = True,
            text           = True,
            timeout        = GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return False

    if done.returncode != 0: return False

    path = done.stdout.strip()
    if not path: return False

    # --git-path answers relative to the repo when cwd is inside it.
    if not os.path.isabs( path ):
        path = os.path.join( cwd or os.getcwd(), path )

    try:
        return os.path.isfile( path )
    except Exception:
        return False


def _deny_reason_for( kind: str, merge_sha=None ) -> str:
    """
    Compose the refusal: what is live, what committing would do, how to proceed.

    Requires:
        - kind is KIND_MERGE or KIND_SQUASH
        - merge_sha is the live MERGE_HEAD sha for KIND_MERGE, None for KIND_SQUASH

    Ensures:
        - names the sha, so the committer can identify the merge before acting
        - names the machine-readable blindness, because the seat's next instinct
          is to check `git status --porcelain` and be reassured by nothing
        - gives a remedy that matches the state. The hatch is right for a merge you
          mean to conclude and wrong for a squash that is not yours — using it there
          lands the squash, which is the damage. A refusal whose instruction causes
          the harm is worse than none, because it carries authority
        - names its own residuals. A residual recorded only in a module docstring
          and a test is invisible to the person who actually meets the guard, who
          will reasonably assume it covers every way a merge gets concluded. The
          refusal is the only text a seat reads, so the scope belongs in it.
    """
    # 🔴 THE REMEDY DIFFERS BY STATE, AND OFFERING THE WRONG ONE CAUSES THE HARM.
    # Found by Rachel 🕊️ on review, 2026-08-31: the squash refusal pointed at the
    # hatch, and the hatch is exactly what a seat must NOT reach for when the staged
    # squash is not theirs — using it LANDS the squash under their message, which is
    # the damage this guard exists to prevent. A refusal whose instruction produces
    # the harm is worse than no refusal, because it carries authority.
    #
    # MEASURED — a plain `git reset` (not --hard) is the safe way out of a squash:
    #     SQUASH_MSG           PRESENT -> absent
    #     the seat's own untracked file      kept
    #     the seat's own tracked edit        kept
    #     the lane's files       left in the worktree, UNSTAGED
    # Nothing is lost, which is why it can be recommended without a warning attached.
    #
    # ⚠️ The unstaged leftovers matter and the message says so: a later `git add -A`
    # or `git commit -a` re-captures the lane's files and lands them without ancestry
    # anyway — the original harm reached by a second route.
    if kind == KIND_SQUASH:
        remedy = (
            "IF YOU MEAN TO LAND THIS SQUASH, re-run with:\n"
            "  LUPIN_ALLOW_MERGE_COMMIT=1 git commit ...\n"
            "IF IT IS NOT YOURS, OR IS LEFT OVER — you are almost certainly here because you "
            "wanted to commit your OWN unrelated work — DO NOT use the hatch: it would land "
            "the squash under your message. Clear it instead:\n"
            "  git reset            # unstages the squash, keeps every file, drops SQUASH_MSG\n"
            "Your own changes survive that untouched, staged or not. ⚠️ It leaves the merged "
            "files in the worktree UNSTAGED, so commit your paths BY NAME afterwards — a later "
            "`git add -A` or `git commit -a` would sweep them back in and land them without "
            "ancestry, which is the same damage by another route.\n"
        )
        headline = (
            "`git commit` is denied: A SQUASH MERGE IS STAGED AND UNCONCLUDED IN THIS TREE "
            "(SQUASH_MSG is present, and there is no MERGE_HEAD to name).\n"
            "Committing now LANDS that merge under YOUR message, with ONE parent and none of "
            "the lane's ancestry — which is exactly the shape the 2026-08-31 incident ended in "
            "(row f3306404: `b26d31a1`, one parent, ten shas non-ancestors, repaired at "
            "`f3e9b41a`).\n"
        )
    else:
        remedy = (
            "IF THE MERGE IS YOURS and you mean to conclude it, re-run with:\n"
            "  LUPIN_ALLOW_MERGE_COMMIT=1 git commit ...\n"
            "IF IT IS NOT YOURS, it belongs to another seat mid-operation. Do NOT abort it and "
            "do NOT commit around it — ask the owner to finish, or wait. Unlike a staged squash "
            "this one is not yours to clear: `git merge --abort` would destroy their conflict "
            "resolution. Your own work is safe where it is; nothing here loses it.\n"
        )
        headline = (
            f"`git commit` is denied: A MERGE IS LIVE IN THIS TREE (MERGE_HEAD {merge_sha[ :12 ]}).\n"
            "Committing now CONCLUDES that merge under YOUR message.\n"
        )

    return (
        headline +
        "A merge is a two-step "
        "operation over tree-global state — staged by one command, written by the next — "
        "so between those steps it belongs to the tree, not to whoever started it. That "
        "happened on 2026-08-31 (row f3306404): parentage was lost, the lane landed with "
        "one parent, ten shas came out non-ancestors, and four seats spent an hour "
        "repairing it.\n"
        "DO NOT CHECK `git status --porcelain` — BOTH machine-readable forms show NOTHING "
        "once the conflicts are staged. Use the long `git status`, or "
        "`git rev-parse -q --verify MERGE_HEAD`, or look for SQUASH_MSG.\n"
        + remedy +
        "WHAT THIS GUARD DOES NOT COVER, so you do not read it as more than it is: "
        "`git merge --continue` also concludes a merge and is NOT checked. Seeing no "
        "refusal is not evidence that no merge is in flight."
    )


def merge_head_deny_reason(
    tool_name,
    tool_input,
    *,
    enabled       : Optional[ bool ] = None,
    env           = None,
    cwd           = None,
    merge_reader  = None,
    squash_reader = None,
) -> Optional[ str ]:
    """
    Return a deny-reason string iff a Bash `git commit` would conclude a live merge.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict) whose "command" key
          carries the shell command, when present
        - enabled is None (resolved from env) or injected for testing
        - merge_reader / squash_reader are None (real git) or injected for testing

    Ensures:
        - None unless all hold: the guard is enabled, tool_name is Bash, the
          command invokes `git commit` in command position, the hatch prefix is
          absent, and either MERGE_HEAD resolves in the target tree or a squash
          merge is staged there
        - MERGE_HEAD is checked first: when it resolves, the refusal can name a sha,
          which is more use to the committer than the squash wording
        - the target tree honours both `cd <path> &&` and `git -C <path>`, composed
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
        if merge_sha:
            return _deny_reason_for( KIND_MERGE, merge_sha )

        if ( squash_reader or _squash_in_flight )( target ):
            return _deny_reason_for( KIND_SQUASH )

        return None

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
