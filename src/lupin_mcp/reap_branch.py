"""
reap_branch.py — the branch half of the reap path.

THE DEFECT THIS CLOSES: **reviewed-and-merged is nobody's standing job.** Work finishes
on a worktree branch, the author is reaped, and the branch becomes the only thing that
remembers it. A reap writes a memento; it does not look at git at all, so the outcome is
structural — it recurs for every seat, every time, and the only thing that has ever
prevented it is somebody happening to remember. Measured by Cheech 2026-09-06: 72 local
branches carried commits absent from the working line, 18 of them held by no worktree at
all. One of those was his own predecessor's, 23 commits old, and he did not know it
existed until he ran the query.

Design: `src/rnd/2026.09.06-unmerged-branch-orphaning-mechanism.md` (Cheech 🌿), Half A.

=== 🔴 THIS SEAM DOES NOT WITHHOLD THE KILL, AND THAT IS THE WHOLE DESIGN ===

`reap_memento.py` withholds, and is right to. This must not copy it. The asymmetry
(design §3.2) is worth stating precisely because the shapes are otherwise identical:

    memento   what is at risk is DATA ONLY THIS SEAT CAN PRODUCE. Kill it and the work
              is gone.                                        => WITHHOLD — refuse the kill
    branch    what is at risk is ATTENTION. The commits are already in git, durable, and
              the janitor keeps them.                          => TRANSFER — name it, proceed

**Nothing is lost at the reap. What is lost is that anyone is looking.** Withholding here
would manufacture the immortal-seat class that `force_kill` exists to prevent, for a
condition that loses nothing. If you are reading this while adding a withhold, re-read
design section 3.2 first.

VERIFIED, not assumed (Clayton, 2026-09-06 ~17:00 EDT): the arbiter section 4b worktree
janitor really does preserve branches. Run against a real repo with `age_threshold_hours=0`,
it removed the worktree DIR, KEPT the branch, and committed the uncommitted work as
`WIP: auto-saved at reap <stamp>` — the branch came out one commit AHEAD, not deleted.
A census of every `_git(` call site in `worktree_reaper.py` names nine verbs and none of
them is `push`, `branch -d` or `branch -D`. So a branch named here is recoverable later.

=== WHY THIS DOES NOT CALL `orphaned_head_sweep.abandoned_branches` ===

It reuses that module's `_git` and its exact predicate — `rev-list --count <target>..<ref>`
— but NOT its classifier, and the reason is structural rather than stylistic.

`abandoned_branches` is defined as *branches with NO LIVE SEAT behind them*. It resolves
live seats from `tmux list-sessions` and drops every ref they hold. **At reap time the seat
is still alive** — the kill loop runs AFTER this seam, deliberately, for the same race
reason the memento coordinator runs first. So the branch this seam is asking about is in
that function's `held` set and is skipped by construction. It cannot answer this question;
it was never meant to.

=> The two PARTITION the space and must stay that way: this file reports on a seat that is
   about to die, `orphaned_head_sweep` on what the dead left behind. Neither is a substitute
   for the other, and merging them would leave a hole at exactly the join — the moment of
   the reap, which is the moment this defect is created.

PURITY: every side-effecting seam (git, the sweep module, the clock) is injected, so the
whole decision tree is unit-provable with fakes and no live git.
"""

import os

from typing import Any, Callable, Dict, Optional


# The working line a branch is measured against. A branch "ahead" of this carries commits
# the fleet's line does not have. Overridable at the call so a non-lupin repo, or a repo
# that renames its line, is not silently measured against a ref it does not own.
DEFAULT_TARGET_BRANCH = os.environ.get(
    "CONTEXT_TICK_TARGET_BRANCH", "wip-v0.2.1-2026.08.29-cjflow-v2-followup"
)

# Verdicts that mean COMMITS ARE LEAVING WITH THE SEAT. Everything else is quiet or is an
# honest "could not look", and the two are never merged — an unreadable probe must never
# render as "nothing to report" (CLAUDE.md, AN EMPTY RESULT IS TWO DIFFERENT FAILURES).
LOSING = ( "unmerged", "detached" )

# Verdicts that mean WE COULD NOT LOOK. Named separately and surfaced separately: a git
# hiccup and a clean branch produce the same silence otherwise.
UNREADABLE = ( "no_cwd", "not_a_worktree", "probe_failed", "sweep_unavailable" )


def default_sweep_git( planning_root=None ):
    """
    Load `orphaned_head_sweep._git` — the SAME git runner session-end's section 8 sweep uses.

    Reuse is deliberate (Cheech's instruction, 2026-09-06): two instruments answering one
    question by two routes coincide until the day they do not. This borrows the runner and
    the predicate rather than retyping either.

    Requires:
        - planning_root is None (-> $PLANNING_IS_PROMPTING_ROOT) or a path to that repo

    Ensures:
        - returns a callable( repo, *args ) -> CompletedProcess-like on success
        - returns None when the module cannot be located or imported — the caller renders
          that as `sweep_unavailable`, NEVER as a clean branch
        - never raises
    """
    root = planning_root or os.environ.get( "PLANNING_IS_PROMPTING_ROOT" )
    if not root:
        return None
    path = os.path.join( root, "workflow", "scripts", "orphaned_head_sweep.py" )
    if not os.path.isfile( path ):
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location( "orphaned_head_sweep", path )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec( spec )
        spec.loader.exec_module( module )
        return module._git
    except Exception:
        return None


def seat_branch( cwd, git_fn ):
    """
    The branch checked out in a seat's own worktree.

    Requires:
        - cwd is the seat's working directory (from its bridge), or None
        - git_fn is a callable( repo, *args ) -> CompletedProcess-like

    Ensures:
        - returns ( branch_name, None ) when a named branch is checked out
        - returns ( None, "no_cwd" ) when the identity carried no cwd
        - returns ( None, "not_a_worktree" ) when cwd is absent from disk or git refuses
        - returns ( None, "detached" ) for a detached HEAD — reported, never dropped:
          a detached seat's commits are anchored by the worktree alone, which is exactly
          `orphaned_head_sweep` category (i), the one that is LOST when the tree goes
        - never raises
    """
    if not cwd:
        return None, "no_cwd"
    if not os.path.isdir( cwd ):
        return None, "not_a_worktree"
    try:
        res = git_fn( cwd, "rev-parse", "--abbrev-ref", "HEAD" )
    except Exception:
        return None, "not_a_worktree"
    if getattr( res, "returncode", 1 ) != 0:
        return None, "not_a_worktree"
    branch = ( getattr( res, "stdout", "" ) or "" ).strip()
    if not branch:
        return None, "not_a_worktree"
    if branch == "HEAD":
        return None, "detached"
    return branch, None


def commits_ahead( repo, target_branch, branch, git_fn ):
    """
    How many commits `branch` carries that `target_branch` does not.

    THE PREDICATE IS `orphaned_head_sweep`'s, unchanged: `rev-list --count <target>..<ref>`.
    Same question, same answer, one definition.

    Requires:
        - repo is a directory git can be run in; branch and target_branch name refs
        - git_fn is a callable( repo, *args ) -> CompletedProcess-like

    Ensures:
        - returns a non-negative int on success
        - returns None when git failed or answered something that is not a count — an
          unparseable answer is "could not look", never zero
        - never raises
    """
    try:
        res = git_fn( repo, "rev-list", "--count", f"{target_branch}..{branch}" )
    except Exception:
        return None
    if getattr( res, "returncode", 1 ) != 0:
        return None
    raw = ( getattr( res, "stdout", "" ) or "" ).strip()
    return int( raw ) if raw.isdigit() else None


def probe_seat_branches(
    identities    : Dict[ str, Any ],
    *,
    target_branch : Optional[ str ] = None,
    git_fn        : Optional[ Callable ] = None
) -> Dict[ str, Any ]:
    """
    For every seat about to be reaped, decide whether it is leaving commits behind.

    Requires:
        - identities maps tmux session name -> the `_capture_reap_identity` dict (or None);
          the dict's `cwd` is the seat's OWN worktree, already captured pre-unlink
        - git_fn is None (-> the session-end sweep's runner) or an injected runner

    Ensures:
        - returns { seat_name: { status, persona, branch, commits, resume } } for every seat
        - `unmerged` carries the commit count and the exact `git log` line a successor runs
        - a seat with no bridge, no cwd, or a git failure gets an EXPLICIT unreadable status
          — never a silent pass, which is the defect this whole mechanism exists for
        - when the sweep module cannot be loaded EVERY seat reads `sweep_unavailable`; the
          probe says it could not look rather than reporting a quiet fleet
        - never raises: a reap must never fail because git hiccupped
    """
    target   = target_branch or DEFAULT_TARGET_BRANCH
    runner   = git_fn if git_fn is not None else default_sweep_git()
    outcomes : Dict[ str, Any ] = {}

    for name in sorted( identities ):
        identity = identities[ name ] or {}
        persona  = identity.get( "persona" )
        cwd      = identity.get( "cwd" )

        if runner is None:
            outcomes[ name ] = { "status": "sweep_unavailable", "persona": persona,
                                 "branch": None, "commits": None, "resume": None }
            continue

        branch, failure = seat_branch( cwd, runner )
        if failure is not None:
            outcomes[ name ] = { "status": failure, "persona": persona,
                                 "branch": None, "commits": None, "resume": None }
            continue

        ahead = commits_ahead( cwd, target, branch, runner )
        if ahead is None:
            outcomes[ name ] = { "status": "probe_failed", "persona": persona,
                                 "branch": branch, "commits": None, "resume": None }
            continue

        outcomes[ name ] = {
            "status"  : "unmerged" if ahead > 0 else "merged",
            "persona" : persona,
            "branch"  : branch,
            "commits" : ahead,
            # The successor's next command, spelled out. A branch NAME plus the line that
            # reads it beats a claim about the branch — the merge-claim check's own
            # docstring names that gap and calls closing it a template rule, and a rule
            # that depends on remembering is not installed. git answers it here instead.
            "resume"  : f"git log --oneline {target}..{branch}" if ahead > 0 else None
        }

    return outcomes


def branch_alarm( outcomes ):
    """
    One sentence, for the TOP of the reap result, naming every seat leaving commits behind.

    WHY TOP-LEVEL (row 3b0c5f90, inherited from `memento_alarm`). Per-seat verdicts in a
    nested dict were already honest and already ignored: a manager reads the top of a
    result, and the reap reports success around them either way. A verdict nobody reads is
    the same as no verdict.

    Requires:
        - outcomes maps seat name -> a probe_seat_branches outcome dict; the reserved
          `_error` key (a probe failure, not a seat) is tolerated

    Ensures:
        - returns None when every seat is merged — the quiet case stays quiet, so the line
          means something when it appears
        - names UNREADABLE seats too, in their own clause: "could not look" and "nothing
          to report" are different facts and must never share a silence
        - sorted by seat name, so the same reap reads the same way twice
        - never raises
    """
    losers, blind = [], []
    for name in sorted( outcomes ):
        if name == "_error":
            continue
        outcome = outcomes[ name ]
        if not isinstance( outcome, dict ):
            continue
        status  = outcome.get( "status" )
        persona = outcome.get( "persona" ) or "unknown persona"
        if status == "unmerged":
            losers.append( f"{name} ({persona}): {outcome.get( 'commits' )} commit(s) on "
                           f"{outcome.get( 'branch' )}" )
        elif status == "detached":
            losers.append( f"{name} ({persona}): detached HEAD — no branch anchors its commits" )
        elif status in UNREADABLE:
            blind.append( f"{name} ({persona}): {status}" )

    if not losers and not blind:
        return None

    parts = []
    if losers:
        parts.append( f"REAPED LEAVING UNMERGED WORK — {len( losers )} seat(s): "
                      + "; ".join( losers )
                      + ". The commits are safe in git and NOBODY IS LOOKING AT THEM; "
                        "see branch_outcomes for the git log line that reads each one." )
    if blind:
        parts.append( f"BRANCH STATE UNREADABLE for {len( blind )} seat(s): "
                      + "; ".join( blind )
                      + ". This is 'could not look', NOT 'nothing to report'." )
    return " ".join( parts )
