#!/usr/bin/env python3
"""
delivery-collision-scan.py — the delivery step, made loud.

WHY THIS EXISTS (row d2dd3ee3, 2026-09-05). Four engineers wrote the same gister
fix inside twenty-four hours. Nobody was careless: a commit on a worktree branch
moves NOBODY'S TREE BUT ITS AUTHOR'S, so each of them looked at a clean tree, saw
no fix, and wrote one. The work was real, the receipts were real, and the delivery
never happened. Rick absorbed two days of a bug that had been solved twice before
breakfast on day one.

WHAT IT CHECKS, AND WHY IT IS NOT "COUNT THE OLD COMMITS". The row's first cut
asked for unmerged commits older than 24h. Measured, that filter EXCLUDES the one
pair known to have collided: `dd81cc7f` was 14 hours old and `755b821c` was 0
hours old, and together they reddened three tests. Age and risk are ANTI-CORRELATED
at the dangerous end — two seats editing one file on one morning IS the collision
case, while a commit sitting alone for a week on a file nobody else touches is the
safe one. So the trigger here is:

    TWO BRANCHES WITH UNDELIVERED EDITS TO ONE FILE, AT ANY AGE.

Both of this row's incidents are retro-detected by that predicate, which is the
only evidence offered for it:
  · src/cosa/memory/gister.py    — 4298f368, dd81cc7f, aefff8ae, 9c9e6f8c
  · src/cosa/rest/db/database.py — dd81cc7f + 755b821c, the pair proven to conflict

🔴 WHY IT DOES NOT USE `merge-base --is-ancestor`, AND THIS IS THE LOAD-BEARING
DECISION. Lupin delivers epics by SQUASH — `8bf71a64` is ONE commit carrying 1,546
files and 349,694 insertions. A squash destroys ancestry, patch-id AND subject
simultaneously, so all three of the obvious instruments call delivered content
"unmerged". Measured at a3f45e6d over the same population:

    ancestry (`merge-base --is-ancestor`)  3,976   over-reports 3.1x
    patch-id (`git cherry`)                1,494/1,495 on one branch
    subject match against the target's log over-reports
    CONTENT PROBE                          1,283   <- what this script uses

A scan built on ancestry cries wolf at three times the real number, and a check
that cries wolf is a check nobody reads. So a candidate commit is only reported
once a line it ADDED is confirmed ABSENT from the target branch's tree.

EXIT CODES — three, because two failure modes that want opposite remedies must not
share one code (`purge-pycache.sh`'s exit 2 is the local precedent):

    0  scanned, no collision            — a real all-clear
    1  COLLISION: >1 branch on a file   — the finding
    2  REFUSED, nothing was scanned     — say so, never report clean

🔴 EXIT 2 IS THE WHOLE POINT OF THE THIRD CODE. This repo's § A CLEAN EXIT IS NOT
EVIDENCE THE WORK HAPPENED collects five tools whose failure and success printed
the same thing. `disk-hygiene-report.sh` — the only other script in the tree that
computes merged-ness — dies on an unmatched glob and prints NOTHING, and its
silence is indistinguishable from a clean run. A scan that discovers zero branches
because a ref pattern went stale would print "no collisions" and be believed. It
refuses instead, and names what it did not do.

WORKTREE-SAFE BY CONSTRUCTION. The repo root is derived from THIS FILE'S location,
never from $LUPIN_ROOT — commit 5e7f74e8 removed exactly that steering from
`purge-pycache.sh` after it purged the main checkout from inside a worktree and
printed its success banner. A script shipped inside the tree it inspects can be
disagreed with by the environment, never informed by it.
"""

import argparse
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

# Derived from THIS FILE, never from $LUPIN_ROOT — see the module docstring.
REPO_ROOT = Path( __file__ ).resolve().parents[ 2 ]

CODE_SUFFIXES = ( ".py", ".js", ".ts", ".tsx", ".jsx", ".sh" )

# A probe line must be long enough to be distinctive. A short added line ("import os",
# "return None") appears in hundreds of files and would report delivered content as
# present no matter which commit it came from.
MIN_PROBE_LINE = 45


def _git( *args, check=False ):
    """
    Run a git command in REPO_ROOT and return its stdout.

    Requires:
        - args form a valid git invocation

    Ensures:
        - returns stdout as str (empty string when git fails and check is False)

    Raises:
        - subprocess.CalledProcessError when check is True and git exits non-zero
    """
    result = subprocess.run(
        [ "git", "-C", str( REPO_ROOT ), *args ],
        capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError( result.returncode, args, result.stdout, result.stderr )
    return result.stdout


def discover_branches( target, max_tip_age_days ):
    """
    Discover candidate branches from git — never from a hand-maintained list.

    This mirrors the cache-bust guard's first property: a population discovered
    from the artifact picks up branch number N+1 the day it is created, while a
    hand-list silently stops watching everything added after it was written.

    Requires:
        - target is a branch name that exists
        - max_tip_age_days is a positive number

    Ensures:
        - returns [ ( branch, tip_unixtime ), ... ] excluding target itself
        - excludes branches whose tip is older than max_tip_age_days
    """
    cutoff = time.time() - max_tip_age_days * 86400
    out    = _git( "for-each-ref", "refs/heads", "--format=%(refname:short)\t%(committerdate:unix)" )

    branches = []
    for line in out.splitlines():
        if not line.strip(): continue
        name, tip = line.split( "\t" )
        if name == target: continue
        if int( tip ) < cutoff: continue
        branches.append( ( name, int( tip ) ) )
    return branches


def commit_file_map( branch, target ):
    """
    Every non-ancestor commit on branch, with the code files it touched.

    ONE git invocation per BRANCH, not one per COMMIT. The first cut of this
    function asked git for each commit's file list separately and did not finish a
    7-day window in nine minutes — 1,600 candidate commits is 1,600 subprocesses.
    `git log --name-only` answers the same question in a single pass. Speed is not
    cosmetic here: a delivery check nobody waits for is a delivery check nobody
    runs, which is the same not-installed failure this script exists to close.

    Ancestry over-reports ~3x in this repo (squash delivery), so this is a
    PRE-FILTER and never a verdict — survivors go through `is_absent_from`.

    Requires:
        - branch and target are branch names that exist

    Ensures:
        - returns [ ( sha, [ path, ... ] ), ... ], merges excluded, code files only
        - a commit touching no code file is still returned, with an empty list
    """
    out = _git(
        "log", "--no-merges", "--format=%x00%H", "--name-only", branch, "--not", target
    )

    commits = []
    sha     = None
    files   = []
    for line in out.splitlines():
        if line.startswith( "\x00" ):
            if sha is not None: commits.append( ( sha, sorted( set( files ) ) ) )
            sha, files = line[ 1: ].strip(), []
        elif line.strip().endswith( CODE_SUFFIXES ):
            files.append( line.strip() )
    if sha is not None: commits.append( ( sha, sorted( set( files ) ) ) )
    return commits


def code_files_of( sha ):
    """
    The code files a commit touched.

    Requires:
        - sha names a commit that exists

    Ensures:
        - returns a sorted list of repo-relative paths ending in a CODE_SUFFIXES entry
    """
    out = _git( "show", "--name-only", "--format=", sha )
    return sorted( {
        line.strip() for line in out.splitlines()
        if line.strip().endswith( CODE_SUFFIXES )
    } )


_ABSENCE_CACHE = {}


def is_absent_from( sha, target, path ):
    """
    Is this commit's contribution to `path` genuinely missing from target's tree?

    THE INSTRUMENT THAT SURVIVED, and the only one here with controls in BOTH
    directions (measured 2026-09-05 at a3f45e6d): the four commits known to be
    undelivered read ABSENT, and four commits known to be ancestors of the target
    read PRESENT. Ancestry, patch-id and subject-matching each failed one of those
    directions, because delivery in this repo is by squash.

    TWO OPTIMISATIONS, BOTH MEASURED RATHER THAN ASSUMED, because the first cut of
    this scan ran for over nine minutes and a check nobody waits for is a check
    nobody runs:
      · MEMOISED per ( sha, path ). One commit touches many contested files, so the
        naive loop asked 15,936 questions where 940 distinct ones exist — a 17x
        multiplier straight out of the loop nesting.
      · The `git grep` is SCOPED TO THE PATH, not run over the whole tree: 0.003s
        against 0.086s per call. It is also the more correct question — whether the
        content landed in THAT file, not merely somewhere in the repo.

    Requires:
        - sha names a commit that exists
        - target is a branch name that exists
        - path is repo-relative and touched by sha

    Ensures:
        - returns True  when a long line sha ADDED to path is not in target's copy
        - returns False when that line IS present (delivered by some other route)
        - returns False when no probe line can be found — UNPROBEABLE is not
          evidence of absence, and silence is the safe direction for a check that
          must not cry wolf
    """
    key = ( sha, path )
    if key in _ABSENCE_CACHE: return _ABSENCE_CACHE[ key ]

    verdict = False
    diff    = _git( "show", sha, "--", path )
    for line in diff.splitlines():
        if not line.startswith( "+" ) or line.startswith( "+++" ): continue
        probe = line[ 1: ]
        if len( probe ) <= MIN_PROBE_LINE: continue
        # `git grep -q` answers in its EXIT CODE, which _git discards, so this call
        # is made directly rather than through the helper.
        hit = subprocess.run(
            [ "git", "-C", str( REPO_ROOT ), "grep", "-qF", "--", probe, target, "--", path ],
            capture_output=True, text=True
        )
        verdict = hit.returncode != 0
        break

    _ABSENCE_CACHE[ key ] = verdict
    return verdict


def scan( target, max_tip_age_days, deadline_seconds=None, progress=None ):
    """
    Find files carrying undelivered edits from more than one branch.

    Requires:
        - target is a branch name that exists

    Ensures:
        - returns ( collisions, stats ) where collisions maps
          path -> [ ( branch, sha ), ... ] with at least two DISTINCT branches
        - stats carries the denominators this scan actually covered

    Raises:
        - LookupError when discovery is vacuous — zero branches or zero candidate
          commits. An empty scan passes every per-item check, so it must refuse.
        - TimeoutError when deadline_seconds elapses mid-probe. A PARTIAL scan is
          not a clean scan: it has looked at some of the corpus and none of the
          rest, and reporting its findings as complete is the same substitution
          this script exists to stop. It refuses and says how far it reached.
    """
    started = time.time()
    branches = discover_branches( target, max_tip_age_days )
    if not branches:
        raise LookupError(
            f"discovered ZERO branches with a tip inside {max_tip_age_days} days. "
            "Nothing was scanned; this is not an all-clear."
        )

    # file -> { branch -> [ sha, ... ] }, built from the ancestry pre-filter
    touch    = defaultdict( lambda: defaultdict( list ) )
    n_cands  = 0
    for branch, _tip in branches:
        for sha, paths in commit_file_map( branch, target ):
            n_cands += 1
            for path in paths:
                touch[ path ][ branch ].append( sha )

    if n_cands == 0:
        raise LookupError(
            f"{len( branches )} branches discovered but ZERO candidate commits. "
            "Nothing was scanned; this is not an all-clear."
        )

    # Contested by the cheap instrument. Only these get the expensive content probe —
    # filter first, probe the survivors.
    contested = { p: b for p, b in touch.items() if len( b ) > 1 }

    collisions = {}
    probed     = 0
    for n_done, ( path, by_branch ) in enumerate( sorted( contested.items() ), start=1 ):
        if deadline_seconds is not None and time.time() - started > deadline_seconds:
            raise TimeoutError(
                f"deadline of {deadline_seconds}s reached after {n_done - 1} of "
                f"{len( contested )} contested files. A PARTIAL scan is not a clean scan."
            )
        if progress is not None and n_done % 25 == 0:
            progress( f"  ... {n_done}/{len( contested )} contested files probed "
                      f"({probed} probes, {len( collisions )} confirmed)" )

        surviving = []
        for branch, shas in by_branch.items():
            for sha in shas:
                probed += 1
                if is_absent_from( sha, target, path ):
                    surviving.append( ( branch, sha ) )
        if len( { b for b, _ in surviving } ) > 1:
            collisions[ path ] = sorted( surviving )

    stats = {
        "branches"          : len( branches ),
        "candidate_commits" : n_cands,
        "files_touched"     : len( touch ),
        "contested_cheap"   : len( contested ),
        "content_probed"    : probed,
        "collisions"        : len( collisions ),
    }
    return collisions, stats


def main( argv=None ):
    """
    Report delivery collisions and exit 0 / 1 / 2.

    Ensures:
        - prints its own denominators on every run, clean or not
        - exit 0 no collision, 1 collision, 2 refused (nothing scanned)
    """
    parser = argparse.ArgumentParser( description=__doc__.splitlines()[ 1 ] )
    parser.add_argument( "--target", default="wip-v0.2.1-2026.08.29-cjflow-v2-followup",
                         help="the branch work is delivered INTO" )
    parser.add_argument( "--max-tip-age-days", type=float, default=7.0,
                         help="ignore branches whose tip is older than this" )
    parser.add_argument( "--mine", default=None,
                         help="only fail when THIS branch is one of the colliding parties" )
    parser.add_argument( "--deadline-seconds", type=float, default=300.0,
                         help="refuse (exit 2) rather than return a PARTIAL scan" )
    parser.add_argument( "--quiet", action="store_true", help="suppress progress lines" )
    args = parser.parse_args( argv )

    progress = None if args.quiet else ( lambda m: print( m, file=sys.stderr, flush=True ) )

    try:
        collisions, stats = scan(
            args.target, args.max_tip_age_days,
            deadline_seconds=args.deadline_seconds, progress=progress
        )
    except LookupError as refusal:
        print( f"REFUSED: {refusal}", file=sys.stderr )
        print( "exit 2 — nothing was scanned. Do not read this as a clean run.", file=sys.stderr )
        return 2
    except TimeoutError as refusal:
        print( f"REFUSED: {refusal}", file=sys.stderr )
        print( "exit 2 — the scan is INCOMPLETE. Raise --deadline-seconds or narrow "
               "--max-tip-age-days; do not read this as a clean run.", file=sys.stderr )
        return 2

    # A scan that cannot state its own denominator is telling you about its corpus,
    # not about your code — so print it whether or not anything was found.
    print( f"delivery collision scan — target {args.target}" )
    print( "  branches {branches} · candidate commits {candidate_commits} · "
           "code files {files_touched}".format( **stats ) )
    print( "  contested (cheap) {contested_cheap} · content-probed {content_probed} · "
           "CONFIRMED {collisions}".format( **stats ) )

    reportable = collisions
    if args.mine is not None:
        reportable = {
            p: v for p, v in collisions.items()
            if any( b == args.mine for b, _ in v )
        }
        print( f"  filtered to collisions involving {args.mine}: {len( reportable )}" )

    if not reportable:
        return 0

    print()
    print( "🔴 UNDELIVERED EDITS FROM MORE THAN ONE BRANCH ON ONE FILE:" )
    for path in sorted( reportable ):
        print( f"  {path}" )
        for branch, sha in reportable[ path ]:
            print( f"      {sha[ :8 ]}  {branch}" )
    print()
    print( "Each of these is somebody's finished work that has not reached anyone's tree." )
    print( "Deliver them, or read the other branch's commit before you write the same fix again." )
    return 1


if __name__ == "__main__":
    sys.exit( main() )
