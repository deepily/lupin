#!/usr/bin/env python3
"""
stale-seat-scan.py: finds live seats editing files that moved on the delivery target.

The delivery chain is committed, merged, respawned, cache-busted, and three of those
links are watched. Nothing watched the seat. `stale-process-scan.py` asks whether a
running daemon executes superseded code. This scan asks a different question that keeps
costing people days: is the tree I am editing in behind the branch the fleet merges into?
A seat can have a fresh process running stale source. Neither the process scan nor the
collision scan says a word about it. Being behind is the default state of a live seat here.

The population must be named or the number is worthless. Most `lupin-wt-*` worktrees are
behind, but almost all are abandoned, so that count is true and useless. The population is
trees with a live process in them, found from `/proc/<pid>/cwd`, never from a name pattern.

So there are two stages, and a seat is reported only when both fire:

    Behind   does the delivery target carry commits this tree lacks?
    Overlap  do any of those commits touch a file this seat has also touched, dirty in
             its tree or committed and not yet delivered?

Behind alone reports most seats on an ordinary afternoon, a check nobody reads by the
second day. Behind is not harmed. A seat 200 commits behind that touches none of them is
safe. A seat 3 commits behind, where one moved its file, is the incident where four
people wrote the same gister fix.

Exit codes are three, so failure modes wanting opposite remedies never share one.
`purge-pycache.sh` is the precedent and both sibling scans use this contract:

    0  scanned, no seat both behind and overlapping: a real all-clear.
    1  a live seat is editing a file that moved under it.
    2  refused, nothing was scanned: say so, never report clean.

What it cannot see:
  - It measures exposure, never damage. An overlap says two parties touched one file,
    not that the result is wrong. That is the honest limit of a file-level probe.
  - A seat that reads a stale file without editing it is invisible, because reading
    leaves no trace in git. The overlap stage under-reports; the two errors do not cancel.
  - `/proc/<pid>/cwd` finds a seat whose shell is in the tree, so one reading a tree
    from elsewhere is missed. The occupied count is a floor, not a ceiling.
  - It reports and merges nothing. Fast-forwarding another seat's tree while it works is
    outside any standing authority, and a tree with local commits may not fast-forward.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Derived from THIS FILE, never from $LUPIN_ROOT — commit 5e7f74e8 removed exactly
# that steering from purge-pycache.sh after it cleaned the main checkout from inside
# a worktree and printed its success banner.
REPO_ROOT = Path( __file__ ).resolve().parents[ 2 ]


def _git( repo, *args ):
    """
    Run git in `repo` and return ( returncode, stdout ).

    Ensures:
        - never raises for a failing git command; the caller decides what a
          failure means, because "this ref does not exist" and "this worktree is
          gone" want different answers
    """
    done = subprocess.run(
        [ "git", "-C", str( repo ), *args ], capture_output=True, text=True
    )
    return done.returncode, done.stdout


def worktree_roots( repo=None ):
    """
    Every worktree of this repository, longest path first.

    Longest first matters because a cwd is matched to its tree by prefix. An unsorted list
    would attribute a nested path to whichever tree happened to be checked first.

    Ensures:
        - returns a list of absolute worktree paths, longest string first
        - returns [] when git cannot enumerate them, so the caller refuses rather
          than reporting an empty fleet as a clean one
    """
    code, out = _git( repo or REPO_ROOT, "worktree", "list", "--porcelain" )
    if code != 0: return []
    roots = [ line.split( " ", 1 )[ 1 ].strip()
              for line in out.splitlines() if line.startswith( "worktree " ) ]
    return sorted( roots, key=len, reverse=True )


def occupied_worktrees( roots ):
    """
    Which of `roots` have a live process standing in them.

    The population is decided by `/proc/<pid>/cwd`, never by a name pattern. This does not
    filter on `comm`, because it asks whether anyone is standing here, not what is running.

    Ensures:
        - returns { worktree_root: [ pid, ... ] } for roots with >= 1 live process
        - a pid that exits mid-scan, or belongs to another user, is skipped rather
          than crashing the scan; a busy box must not make this fail more often
        - matching `lupin-wt-*` would count 185 trees, 183 of them abandoned, a number
          that is true and unusable; a cwd is a fact about a live process, a name only a string
        - a shell, an editor, a pytest run and an agent seat all count equally as occupants
          here, whereas the sibling process scan filters on `comm` to ask what is executing
    """
    occupants = {}
    for entry in os.listdir( "/proc" ):
        if not entry.isdigit(): continue
        try:
            cwd = os.readlink( f"/proc/{entry}/cwd" )
        except ( OSError, PermissionError ):
            continue
        for root in roots:
            if cwd == root or cwd.startswith( root + os.sep ):
                occupants.setdefault( root, [] ).append( entry )
                break
    return occupants


def behind_commits( worktree, target ):
    """
    Commits the delivery target carries that this worktree's HEAD lacks.

    This is the behind stage.

    Requires:
        - target names a ref resolvable from inside `worktree`

    Ensures:
        - returns a list of full shas, newest first
        - returns None when the target does not resolve there, which is a refusal
          condition and not an empty result
    """
    code, out = _git( worktree, "rev-list", f"HEAD..{target}" )
    if code != 0: return None
    return [ line.strip() for line in out.splitlines() if line.strip() ]


def files_touched_by( worktree, shas ):
    """
    Every path touched by `shas`.

    Ensures:
        - returns a set of repo-relative paths, empty when shas is empty
    """
    if not shas: return set()
    # One `show` over every sha, rather than N processes. The %x00 format makes the
    # commit header lines identifiable so they can be dropped from the path set.
    code, out = _git( worktree, "show", "--name-only", "--format=%x00", *shas )
    if code != 0: return set()
    return { line.strip() for line in out.splitlines()
             if line.strip() and not line.startswith( "\x00" ) }


def files_this_seat_touched( worktree, target ):
    """
    Files this seat has touched: dirty, untracked, or committed but not yet delivered.

    This is the seat side of the overlap stage. A seat's work lives in three places, and
    leaving any of them out under-reports the overlap.

    Ensures:
        - returns a set of repo-relative paths
        - includes tracked files modified against its own HEAD
        - includes untracked files it has created, with ignored files excluded by git itself
        - includes files in commits it has made that the target does not carry
        - a file the seat only read is in none of these, because reading leaves no trace in
          git, so this set is a floor
    """
    touched = set()

    code, out = _git( worktree, "diff", "--name-only", "HEAD" )
    if code == 0:
        touched |= { line.strip() for line in out.splitlines() if line.strip() }

    code, out = _git( worktree, "ls-files", "--others", "--exclude-standard" )
    if code == 0:
        touched |= { line.strip() for line in out.splitlines() if line.strip() }

    code, out = _git( worktree, "rev-list", f"{target}..HEAD" )
    if code == 0:
        ahead = [ line.strip() for line in out.splitlines() if line.strip() ]
        touched |= files_touched_by( worktree, ahead )

    return touched


def scan( target, roots=None ):
    """
    Find live seats standing on a tree that moved under them.

    Ensures:
        - returns ( stale, stats ); stale maps worktree -> details for BOTH-stage
          hits only

    Raises:
        - LookupError when zero worktrees are enumerable, or zero of them are
          occupied. An empty scan satisfies every per-item assertion in the loop,
          so it must refuse rather than report clean — the same defect that let
          `disk-hygiene-report.sh` print nothing for weeks and be read as healthy.
    """
    roots = worktree_roots() if roots is None else roots
    if not roots:
        raise LookupError(
            "git enumerated ZERO worktrees. Nothing was scanned; this is not an all-clear."
        )

    occupants = occupied_worktrees( roots )
    if not occupants:
        raise LookupError(
            f"{len( roots )} worktrees exist and NONE has a live process in it. "
            "Nothing was scanned; this is not an all-clear."
        )

    stale       = {}
    n_behind    = 0
    n_unresolved = 0
    for root, pids in sorted( occupants.items() ):
        missing = behind_commits( root, target )
        if missing is None:
            # The target does not resolve in this tree. Counted and named rather
            # than silently treated as up-to-date, which is the flattering reading.
            n_unresolved += 1
            continue
        if not missing: continue
        n_behind += 1

        moved_under = files_touched_by( root, missing )
        seat_has    = files_this_seat_touched( root, target )
        overlap     = moved_under & seat_has
        if not overlap: continue

        stale[ root ] = {
            "pids"    : pids,
            "behind"  : len( missing ),
            "moved"   : len( moved_under ),
            "touched" : len( seat_has ),
            "overlap" : sorted( overlap ),
        }

    stats = {
        "worktrees"  : len( roots ),
        "occupied"   : len( occupants ),
        "behind"     : n_behind,
        "unresolved" : n_unresolved,
        "overlapping": len( stale ),
    }
    return stale, stats


def main( argv=None ):
    """
    Report live seats standing on stale trees and exit 0 / 1 / 2.

    Ensures:
        - prints its denominators on every run, clean or not
    """
    parser = argparse.ArgumentParser( description="find live seats whose tree moved under them" )
    parser.add_argument( "--target", default="wip-v0.2.1-2026.08.29-cjflow-v2-followup",
                         help="the branch work is delivered INTO" )
    parser.add_argument( "--mine", default=None,
                         help="only exit 1 when THIS worktree path is one of the hits" )
    args = parser.parse_args( argv )

    try:
        stale, stats = scan( args.target )
    except LookupError as refusal:
        print( f"REFUSED: {refusal}", file=sys.stderr )
        print( "exit 2 — nothing was scanned. Do not read this as a clean run.", file=sys.stderr )
        return 2

    # A scan that cannot state its own denominator is telling you about its corpus,
    # not about your fleet — so this prints on a clean run too.
    print( "stale-seat scan" )
    print( "  worktrees {worktrees} · LIVE-OCCUPIED {occupied} · behind {behind} · "
           "AND overlapping {overlapping}".format( **stats ) )
    if stats[ "unresolved" ]:
        print( f"  ⚠️ {stats[ 'unresolved' ]} occupied trees could not resolve '{args.target}' "
               "and were NOT judged — not counted clean" )

    if not stale: return 0

    print()
    print( "🔴 LIVE SEATS EDITING FILES THAT MOVED UNDER THEM:" )
    for root, info in sorted( stale.items(), key=lambda kv: -len( kv[ 1 ][ "overlap" ] ) ):
        print( f"  {root}" )
        print( f"      {info[ 'behind' ]} commits behind · {len( info[ 'pids' ] )} live processes · "
               f"{info[ 'moved' ]} files moved on the target · {info[ 'touched' ]} touched here" )
        for path in info[ "overlap" ]:
            print( f"      ⚡ {path}" )
    print()
    print( "Each ⚡ is one file two parties have their hands on. That is EXPOSURE, not damage —" )
    print( "go and read the other party's version before you finish yours." )

    if args.mine is not None:
        mine = str( Path( args.mine ).resolve() )
        return 1 if mine in stale else 0
    return 1


if __name__ == "__main__":
    sys.exit( main() )
