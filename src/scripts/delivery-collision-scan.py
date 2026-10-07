#!/usr/bin/env python3
"""
delivery-collision-scan.py — the delivery step, made loud.

Finds files edited by two or more branches whose edits are not yet delivered to the target branch.

Notes:
    Why it exists:
    - A commit on a worktree branch moves nobody's tree but its author's.
    - So several engineers looked at a clean tree, saw no fix, and each wrote the same fix.
    - The work and receipts were real, but the delivery never happened.

    The trigger, at any age:
    - Two branches with undelivered edits to one file.
    - Age and risk are anti-correlated at the dangerous end.
    - Two seats editing one file on one morning is the collision case.
    - A lone commit that sits for a week on a file nobody else touches is the safe one.
    - So a filter for unmerged commits older than 24h excludes the pair that collided.

    Why not `merge-base --is-ancestor`:
    - Lupin delivers epics by squash, which destroys ancestry, patch-id and subject at once.
    - All three instruments then call delivered content unmerged.
    - Ancestry over-reported about 3x on the measured population.
    - A scan that cries wolf is a scan nobody reads.
    - So a commit is reported only once a line it added is confirmed absent from the target branch's tree.

    Filters must name what they excluded:
    - A falling count reads as progress, and a shrinking non-zero is the one number nobody re-checks.
    - Branches crossing the `--max-tip-age-days 7` boundary once dropped the count from 143 to 14 with nothing delivered.
    - Every filter must say what it excluded on every run, including clean ones.
    - `discover_branches` returns its exclusions and `_print_not_examined` states them.
    - A count is meaningless without its window, so quote the parameter with the figure.

    Exit codes, three because two failure modes that want opposite remedies must not share one code:
    - 0 means scanned with no collision, a real all-clear.
    - 1 means collision, more than one branch on a file.
    - 2 means refused, nothing scanned. It never reports clean.
    - A scan that discovered zero branches because a ref pattern went stale would otherwise print "no collisions".

    Worktree-safe:
    - The repo root comes from this file's location, never from $LUPIN_ROOT.
    - A script shipped inside the tree it inspects can be disagreed with by the environment, never informed by it.
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

    A population discovered from the artifact picks up branch number N+1 the day it is created.
    A hand-list silently stops watching everything added after it was written.

    Requires:
        - target is a branch name that exists
        - max_tip_age_days is a positive number

    Ensures:
        - returns ( inside, excluded ), each [ ( branch, tip_unixtime ), ... ]
        - target itself is in neither list
        - `inside` holds tips newer than max_tip_age_days; `excluded` holds the rest

    Notes:
        - It returns what it excluded, because a collision on an excluded branch is invisible, not absent.
        - The caller can only say so if it is handed the names.
        - Dropping aged-out branches silently once turned an unchanged backlog into an apparent drain.
        - The age filter is correct and stays, since an abandoned tree crying wolf is the failure it prevents.
    """
    cutoff = time.time() - max_tip_age_days * 86400
    out    = _git( "for-each-ref", "refs/heads", "--format=%(refname:short)\t%(committerdate:unix)" )

    inside   = []
    excluded = []
    for line in out.splitlines():
        if not line.strip(): continue
        name, tip = line.split( "\t" )
        if name == target: continue
        ( inside if int( tip ) >= cutoff else excluded ).append( ( name, int( tip ) ) )
    return inside, excluded


def commit_file_map( branch, target ):
    """
    Every non-ancestor commit on branch, with the code files it touched.

    Uses one git invocation per branch, not one per commit.
    `git log --name-only` answers the same question in a single pass.

    Requires:
        - branch and target are branch names that exist

    Ensures:
        - returns [ ( sha, [ path, ... ] ), ... ], merges excluded, code files only
        - a commit touching no code file is still returned, with an empty list

    Notes:
        - One subprocess per commit did not finish a 7-day window, with about 1,600 candidate commits.
        - Speed is not cosmetic, because a delivery check nobody waits for is a delivery check nobody runs.
        - Ancestry over-reports about 3x in this repo because of squash delivery.
        - So this is a pre-filter and never a verdict, and survivors go through `is_absent_from`.
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
    Is this commit's contribution to `path` missing from target's tree?

    This is the one instrument with controls in both directions.
    Known-undelivered commits read absent, and known ancestors of the target read present.

    Requires:
        - sha names a commit that exists
        - target is a branch name that exists
        - path is repo-relative and touched by sha

    Ensures:
        - returns True when a long line sha added to path is not in target's copy
        - returns False when that line is present (delivered by some other route)
        - returns False when no probe line can be found, because unprobeable is not evidence of absence.
          Silence is the safe direction for a check that must not cry wolf.

    Notes:
        - Ancestry, patch-id and subject-matching each failed one direction, because delivery here is by squash.
        - Results are memoised per ( sha, path ).
        - One commit touches many contested files, so the naive loop asked about 17x more questions than exist.
        - The `git grep` is scoped to the path, not run over the whole tree, and is about 30x faster per call.
        - That is also the more correct question: whether the content landed in that file, not somewhere in the repo.
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
          path -> [ ( branch, sha ), ... ] with at least two distinct branches
        - stats carries the denominators this scan actually covered

    Raises:
        - LookupError when discovery is vacuous, with zero branches or zero candidate commits.
          An empty scan passes every per-item check, so it must refuse.
        - TimeoutError when deadline_seconds elapses mid-probe. A partial scan is not a clean scan.
          It refuses and says how far it reached, since reporting partial findings as complete is the substitution this script stops.
    """
    started = time.time()
    branches, excluded_by_age = discover_branches( target, max_tip_age_days )
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
        # NOT a denominator of what was scanned — a denominator of what was NOT.
        # Carried so main() can say so on every run, clean ones included.
        "excluded_by_age"   : len( excluded_by_age ),
        "excluded_branches" : sorted( excluded_by_age, key=lambda bt: -bt[ 1 ] ),
    }
    return collisions, stats


def _print_not_examined( stats, max_tip_age_days, now=None, cap=20 ):
    """
    Say what the age filter did not look at, before anyone reads what it found.

    This prints on every run, clean ones included, and the branches are named, most recent tip first.

    Requires:
        - stats carries "excluded_by_age" and "excluded_branches"

    Ensures:
        - prints exactly one line when nothing was excluded, so silence never means
          "the filter did not run"
        - never prints more than `cap` names, and says how many it withheld

    Notes:
        - A count that falls from aging out looks like one that falls from delivery, and the delivery reading is the flattering one.
        - Naming the count alone is not enough, because an unnamed count is the easiest thing in a report to wave at.
        - A branch that aged out an hour ago is likelier to be live work than one that aged out in March.
    """
    n = stats[ "excluded_by_age" ]
    if not n:
        print( f"  0 branches excluded by age — every branch was examined at {max_tip_age_days}d" )
        return

    now = time.time() if now is None else now
    print( f"  ⚠️ {n} branches NOT EXAMINED (tip older than {max_tip_age_days}d). "
           "A collision on these is INVISIBLE, not absent:" )
    shown = stats[ "excluded_branches" ][ :cap ]
    for name, tip in shown:
        print( f"      {name}  ({( now - tip ) / 86400:.1f}d)" )
    if n > len( shown ):
        print( f"      … and {n - len( shown )} more — raise --max-tip-age-days to examine them" )


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
    _print_not_examined( stats, args.max_tip_age_days )

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
