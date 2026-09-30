#!/usr/bin/env python3
"""
stale-seat-scan.py — the sixth sighting, made loud.

WHY THIS EXISTS (row d2dd3ee3). The delivery chain is
`committed -> merged -> respawned -> cache-busted`, and this repo now watches
three of those links. **NOTHING watches the SEAT.**

`stale-process-scan.py` compares a running PROCESS against commits that landed —
"is this daemon executing superseded code?" That is a different question from the
one that keeps costing people days: **"is the tree I am editing in behind the
branch the fleet merges into?"** A seat can have a perfectly fresh process running
perfectly stale source, and neither the process scan nor the collision scan says a
word about it.

MEASURED, TWICE, ON THE SAME SEAT:
  · 2026-09-05 ~16:38 EDT — a census of worktrees with a LIVE PROCESS in them
    found **7 of 8 behind the working branch**, the author's own tree among them.
  · 2026-09-05 ~21:30 EDT — that same seat came back from a context clear
    **30 commits behind**, having written the census.

Neither time did anything warn. This is not a story about careless seats; on the
evidence it is the DEFAULT STATE of a live seat on this fleet.

🔴 NAME THE POPULATION OR THE NUMBER IS WORTHLESS. Across all 185 `lupin-wt-*`
worktrees, 183 are behind, the worst by 1,121 commits. That figure is TRUE AND
USELESS — almost every one is an abandoned tree nobody is sitting in, and quoting
it produces exactly the cry-wolf number this row already rejected for the ancestry
instrument. **The population is trees with a live process actually in them,
identified from `/proc/<pid>/cwd` and never from a name pattern.**

⇒ Two stages, and a seat is reported only when BOTH fire:

    STAGE 1  BEHIND    does the delivery target carry commits this tree lacks?
    STAGE 2  OVERLAP   do any of those commits touch a file THIS SEAT has also
                       touched — dirty in its tree, or committed and not yet
                       delivered?

Stage 1 alone reports 7 of 8 seats on an ordinary afternoon, which is a check
nobody reads by the second day. **BEHIND IS NOT HARMED.** A seat 200 commits
behind that touches none of them is behind and safe; a seat 3 commits behind where
one of the three moved the file under its cursor is the four-people-wrote-the-same-
gister-fix incident that opened this row.

EXIT CODES — three, so two failure modes wanting opposite remedies never share
one (`purge-pycache.sh` is the local precedent; both sibling scans use this
contract):

    0  scanned, no seat both behind AND overlapping   — a real all-clear
    1  a live seat is editing a file that moved under it
    2  REFUSED, nothing was scanned                   — say so, never report clean

⚠️ WHAT IT CANNOT SEE, STATED HERE RATHER THAN DISCOVERED LATER:
  · **It measures EXPOSURE, never damage.** An overlap says two parties touched
    one file, not that the result is wrong. That is the same caveat the collision
    scan carries and it is not a weakness to be engineered away — it is the honest
    limit of what a file-level probe can know.
  · **A seat that READS a stale file without editing it is invisible.** Stage 2
    keys on files the seat touched, and reading leaves no trace in git. So this
    UNDER-reports, in the opposite direction from stage 1 alone. The two errors do
    not cancel; they are simply the two edges of the instrument.
  · **`/proc/<pid>/cwd` finds a seat whose shell is IN the tree.** One reading a
    tree from elsewhere is missed. The occupied count is a FLOOR, not a ceiling.
  · It reports; it merges nothing. Fast-forwarding another seat's tree while it
    works is outside any standing authority, and a tree with local commits may not
    fast-forward at all.
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

    Longest-first matters: a cwd is matched to its tree by prefix, and an
    unsorted list would attribute a nested path to whichever tree happened to be
    checked first.

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

    🔴 THE POPULATION IS DECIDED BY `/proc/<pid>/cwd`, NEVER BY A NAME PATTERN.
    Matching `lupin-wt-*` counts 185 trees, 183 of them abandoned, and produces a
    number that is true and unusable. A cwd is a fact about a process that exists;
    a name is a fact about a string.

    ⚠️ Deliberately does NOT filter on `comm`. The sibling process scan does,
    because it asks "what is this process running?" — a question about the
    executable. This one asks "is anyone standing here?", and a shell, an editor, a
    pytest run and an agent seat are all equally an occupant.

    Ensures:
        - returns { worktree_root: [ pid, ... ] } for roots with >= 1 live process
        - a pid that exits mid-scan, or belongs to another user, is skipped rather
          than crashing the scan — a busy box must not make this fail more often
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

    STAGE 1.

    Requires:
        - target names a ref resolvable from inside `worktree`

    Ensures:
        - returns a list of full shas, newest first
        - returns None when the target does not resolve there, which is a refusal
          condition and NOT an empty result
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
    Everything this seat has its hands on: dirty in the tree, or committed and
    not yet delivered.

    STAGE 2's left-hand side. Three sources, because a seat's work lives in three
    places and leaving any of them out under-reports the overlap:

        · tracked files modified against its own HEAD
        · untracked files it has created (ignored files excluded by git itself)
        · files in commits it has made that the target does not carry

    ⚠️ A file the seat only READ is in none of these. Reading leaves no trace in
    git, so this set is a floor.

    Ensures:
        - returns a set of repo-relative paths
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
