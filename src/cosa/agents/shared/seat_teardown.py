"""
Seat teardown — a seat removes its OWN worktree and its merged branch (row 129cc96b, P3).

Rick ruled 2026-09-18: workers must not leave trees behind. Two doors call this:

    1. session_spawner.dismiss_sessions — right after the manager's reap kills the seat
    2. the SessionEnd hook — a detached waiter, launched when a seat exits on its own

The arbiter's worktree janitor stays the backstop for seats that get hard-killed.

This is STRICTER than the janitor, on purpose. The janitor auto-commits WIP and removes
the tree anyway, because it is the last line and a tree left forever is its own failure.
Teardown runs while somebody is still around to look, so it keeps and REPORTS instead:

    uncommitted edits             → tree kept, "uncommitted_work"
    ignored files that are data   → tree kept, "ignored_files_present"
    commits the WIP line lacks    → tree AND branch kept, "unmerged"
    clean, and merged             → `git worktree remove` (no --force), then
                                    `git branch -d` via worktree_reaper.delete_merged_branch

It touches only a tree locked `lupin-seat:<this seat's tmux name>`, and only once that seat
is provably gone (worktree_reaper.seat_is_alive: tmux absent AND no process standing in
the tree). Every uncertainty keeps the tree.

See: planning-is-prompting -> src/rnd/2026.09.18-worktree-and-branch-cleanup-proposal.md §4
"""

import argparse
import json
import os
import sys
import time
from typing import Callable, Optional

from cosa.agents.shared.worktree_reaper import (
    SEAT_LOCK_PREFIX, _default_run, _git, delete_merged_branch, find_ignored_blockers,
    list_worktrees, main_worktree_branch, merge_verdict, seat_is_alive,
)


# Kept reasons that mean "this was never a seat tree to tear down" rather than "work is
# being kept". teardown_notice stays quiet about these — a seat that ran in the main
# checkout has nothing to report.
NOT_A_SEAT_TREE = ( "no_tree", "not_a_worktree", "not_registered", "main_worktree",
                    "not_a_seat_tree", "not_this_seats_tree" )

DEFAULT_WAIT_SECONDS = 10.0
POLL_SECONDS         = 0.5


def _main_root( top: str, run: Callable ) -> Optional[ str ]:
    """
    The main checkout that owns the worktree at `top`.

    Ensures:
        - returns the directory holding the shared .git, as an absolute path
        - returns None when git cannot say; never raises
    """
    res = _git( run, top, "rev-parse", "--path-format=absolute", "--git-common-dir" )
    if not res[ "success" ] or not res[ "stdout" ]:
        return None
    return os.path.dirname( res[ "stdout" ].rstrip( os.sep ) )


def _wait_until_gone( seat_name: str, path: str, alive_fn: Callable, wait_seconds: float,
                      sleep_fn: Callable, clock: Callable ) -> bool:
    """
    Poll the seat's liveness until it is gone or the wait runs out.

    Ensures:
        - returns True as soon as alive_fn( seat_name, path ) is False
        - returns False once wait_seconds have passed with the seat still alive
        - checks at least once, even with wait_seconds == 0
    """
    deadline = clock() + wait_seconds
    while True:
        if not alive_fn( seat_name, path ):
            return True
        if clock() >= deadline:
            return False
        sleep_fn( POLL_SECONDS )


def retire_seat_worktree(
    path         : Optional[ str ],
    seat_name    : Optional[ str ]      = None,
    run          : Optional[ Callable ] = None,
    alive_fn     : Optional[ Callable ] = None,
    wait_seconds : float                = DEFAULT_WAIT_SECONDS,
    sleep_fn     : Callable             = time.sleep,
    clock        : Callable             = time.monotonic,
    debug        : bool                 = False,
) -> dict:
    """
    Remove a dead seat's own worktree and its merged branch — or keep both and say why.

    Requires:
        - path is the seat's cwd (its worktree or anything inside it), or None
        - seat_name is the seat's tmux session name, or None to take it from the tree's
          `lupin-seat:` lock (the SessionEnd door, which does not know its tmux name)
        - run / alive_fn are None (real git, worktree_reaper.seat_is_alive) or injected

    Ensures:
        - returns { seat, path, removed, kept_reason, branch, branch_outcome,
          ignored_blockers, errors }
        - removed=True only when ALL hold: the tree is a linked worktree (not the main
          checkout), it is locked `lupin-seat:<seat_name>`, the seat is gone within
          wait_seconds, `git status --porcelain` is empty, no ignored file is data
          (find_ignored_blockers), and HEAD is an ancestor of the main tree's branch
        - then: unlock, `git worktree remove` WITHOUT --force, and
          delete_merged_branch — which runs `git branch -d` only, never -D. A failed
          removal re-locks the tree with its original reason
        - every other case keeps the tree, sets kept_reason, and changes nothing
        - never auto-commits, never pushes, never raises
    """
    run      = run      if run      is not None else _default_run
    alive_fn = alive_fn if alive_fn is not None else seat_is_alive
    out = { "seat": seat_name, "path": path, "removed": False, "kept_reason": None,
            "branch": None, "branch_outcome": None, "ignored_blockers": [], "errors": [] }

    def keep( reason, error=None ):
        out[ "kept_reason" ] = reason
        if error: out[ "errors" ].append( error )
        if debug: print( f"[seat_teardown] kept {out[ 'path' ]}: {reason}" )
        return out

    if not path or not os.path.isdir( path ):
        return keep( "no_tree" )
    top = _git( run, path, "rev-parse", "--show-toplevel" )
    if not top[ "success" ] or not top[ "stdout" ]:
        return keep( "not_a_worktree", top[ "stderr" ] or None )
    tree = top[ "stdout" ]
    out[ "path" ] = tree
    main_root = _main_root( tree, run )
    if main_root is None:
        return keep( "not_a_worktree", "git could not name the main checkout" )

    records = list_worktrees( main_root, run=run )
    rec     = next( ( r for r in records if os.path.realpath( r[ "path" ] ) == os.path.realpath( tree ) ), None )
    if rec is None:
        return keep( "not_registered" )
    if rec[ "is_main" ]:
        return keep( "main_worktree" )
    reason = rec.get( "lock_reason" ) or ""
    if not ( rec.get( "locked" ) and reason.startswith( SEAT_LOCK_PREFIX ) ):
        return keep( "not_a_seat_tree" )
    owner = reason[ len( SEAT_LOCK_PREFIX ): ]
    if seat_name is None:
        seat_name = owner
        out[ "seat" ] = owner
    if owner != seat_name:
        return keep( "not_this_seats_tree" )

    if not _wait_until_gone( seat_name, tree, alive_fn, wait_seconds, sleep_fn, clock ):
        return keep( "seat_alive" )

    status = _git( run, tree, "status", "--porcelain" )
    if not status[ "success" ]:
        return keep( "status_failed", status[ "stderr" ] )
    if status[ "stdout" ]:
        return keep( "uncommitted_work" )

    ignored = find_ignored_blockers( tree, main_root, run )
    if not ignored[ "ok" ]:
        return keep( "ignored_check_failed", ignored[ "error" ] )
    if ignored[ "blockers" ]:
        out[ "ignored_blockers" ] = ignored[ "blockers" ]
        return keep( "ignored_files_present" )

    out[ "branch" ] = rec.get( "branch" )
    target = main_worktree_branch( records )
    if not target:
        return keep( "no_target_branch" )
    if out[ "branch" ]:
        verdict = merge_verdict( main_root, out[ "branch" ], target, run )
    else:
        verdict = _detached_verdict( tree, main_root, target, run )
    if verdict[ "verdict" ] != "merged":
        out[ "branch_outcome" ] = { "branch": out[ "branch" ], "target": target, "deleted": False,
                                    "kept_reason": verdict[ "verdict" ], "commits_ahead": verdict[ "commits_ahead" ],
                                    "error": verdict[ "error" ] }
        return keep( "unmerged" if verdict[ "verdict" ] == "unmerged" else "merge_check_failed", verdict[ "error" ] )

    unlock = _git( run, main_root, "worktree", "unlock", tree )
    if not unlock[ "success" ]:
        return keep( "unlock_failed", unlock[ "stderr" ] )
    remove = _git( run, main_root, "worktree", "remove", tree )
    if not remove[ "success" ]:
        relock = _git( run, main_root, "worktree", "lock", "--reason", reason, tree )
        if not relock[ "success" ]:
            out[ "errors" ].append( f"re-lock failed, the seat tree is now unprotected: {relock[ 'stderr' ]}" )
        return keep( "remove_failed", remove[ "stderr" ] )

    out[ "removed" ] = True
    if out[ "branch" ]:
        out[ "branch_outcome" ] = delete_merged_branch( main_root, out[ "branch" ], target, run=run )
    if debug: print( f"[seat_teardown] removed {tree}; branch {out[ 'branch_outcome' ]}" )
    return out


def _detached_verdict( tree: str, main_root: str, target: str, run: Callable ) -> dict:
    """
    merge_verdict for a detached HEAD: resolve the sha in the tree, measure it in main.

    A seat tree is provisioned detached, and a seat that never made a branch still has
    commits only the tree anchors if it committed on the detached HEAD.

    Ensures:
        - returns merge_verdict's shape; "failed" when the sha cannot be read
    """
    sha = _git( run, tree, "rev-parse", "HEAD" )
    if not sha[ "success" ] or not sha[ "stdout" ]:
        return { "verdict": "failed", "commits_ahead": None, "error": f"rev-parse HEAD failed: {sha[ 'stderr' ]}" }
    return merge_verdict( main_root, sha[ "stdout" ], target, run )


def teardown_notice( outcomes: dict ) -> Optional[ str ]:
    """
    One sentence naming every seat whose tree teardown KEPT because of work in it.

    Requires:
        - outcomes maps seat name -> a retire_seat_worktree result; a non-dict value is
          a teardown that raised and is reported as such

    Ensures:
        - returns None when every tree was removed or was never a seat tree
          (NOT_A_SEAT_TREE) — the quiet case stays quiet
        - otherwise names each kept seat with its reason and path, sorted by seat
    """
    kept = []
    for name in sorted( outcomes ):
        outcome = outcomes[ name ]
        if not isinstance( outcome, dict ):
            kept.append( f"{name}: teardown raised ({outcome})" )
            continue
        if outcome.get( "removed" ) or outcome.get( "kept_reason" ) in NOT_A_SEAT_TREE:
            continue
        kept.append( f"{name}: {outcome.get( 'kept_reason' )} at {outcome.get( 'path' )}" )
    if not kept:
        return None
    return ( f"SEAT TREE KEPT for {len( kept )} seat(s): " + "; ".join( kept )
             + ". Nothing was deleted; the janitor sweeps it once it is idle." )


def main( argv=None, retire_fn=None ) -> int:
    """
    CLI for the SessionEnd door: `python -m cosa.agents.shared.seat_teardown --path <cwd>`.

    Ensures:
        - prints the retire_seat_worktree result as one JSON line on stdout
        - exits 0 whatever the verdict; a kept tree is a report, not a failure
    """
    parser = argparse.ArgumentParser( description="Remove a dead seat's own worktree and merged branch." )
    parser.add_argument( "--path", required=True )
    parser.add_argument( "--seat", default=None )
    parser.add_argument( "--wait-seconds", type=float, default=DEFAULT_WAIT_SECONDS )
    args   = parser.parse_args( argv )
    retire = retire_fn if retire_fn is not None else retire_seat_worktree
    result = retire( args.path, seat_name=args.seat, wait_seconds=args.wait_seconds )
    print( json.dumps( { "ts": time.strftime( "%Y-%m-%dT%H:%M:%S%z" ), **result } ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
