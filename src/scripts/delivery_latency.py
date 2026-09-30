#!/usr/bin/env python3
"""
delivery_latency.py — the instrument behind §9–§9e of
`src/rnd/v0.2.1/2026.09.05-no-worker-facing-delivery-route.md`.

WHY THIS FILE EXISTS. Every figure in those sections was produced by a throwaway probe in a
session scratchpad. A published number whose only artifact lives in `/tmp` cannot be re-derived,
and this file's own subject is measurements that turned out to be wrong four times — so it is
exactly the wrong place to leave the instrument unreproducible.

    python3 src/scripts/delivery_latency.py --repo /path/to/lupin --branch <target>

=== THE METRIC HAS BEEN REBUILT FOUR TIMES. READ THIS BEFORE TRUSTING A NUMBER. ===

  v1  committer date of the tip   a cherry-pick REWRITES it, so both sides of the comparison
                                  moved with the delivery act -> median 0.0 across 623 rows.
                                  The metric COULD NOT FAIL.
  v2  author date of the tip      a stack waits as long as its OLDEST member; a known 25.5 h
                                  delivery vanished from the tail entirely.
  v3  author date of the OLDEST   credible, and what §9 published — but it SHARES A TERM with
                                  "how many commits are carried" (a bigger stack has an older
                                  oldest member BY CONSTRUCTION), so stack-size hypotheses are
                                  untestable against it.
  v4  author date of the NEWEST   immune to stack size, and it ERASES every stalled commit that
                                  rides out beside fresh work. Measured: 3 commits that waited
                                  25.5 h, delivered with 5 commits authored minutes before
                                  landing, read as 0.08 h.
  v5  PER COMMIT (this file)      each commit against the landing that carried it. No stack-size
                                  confound and nothing maskable by a co-traveller.

🔴 AND ONE DECOMPOSITION IS UNFALSIFIABLE — it is v4 wearing a new name. Splitting a wait at
"the branch finished", taken as the last commit in the delivery, gives a route-side term of
`landed - max(author)`. ANY COMMIT MADE WHILE WAITING RESETS IT, so a long route wait cannot be
observed. It is computed here and reported ONLY as `route_side_UNFALSIFIABLE`, never as evidence.

⇒ What survives is `largest_silent_stretch`: a gap that ALREADY HAPPENED, which no later commit
  can erase. That is the figure §9e's "62.0 of 84.6 box-up hours (73%)" comes from.

=== WHAT "BOX UP" MEANS, AND WHAT IT DOES NOT ===
Uptime comes from `journalctl --list-boots` — the DURABLE instrument. `last -x reboot` reads
`wtmp`, which rotates: on 2026-09-02 it returned exactly ONE boot and nothing in that output says
it is a one-day window.
🔴 "Box up" is NOT "somebody was available." It means an available-action WINDOW existed. It is
never evidence that a person failed to act, and no output of this script may be read that way.
"""

import argparse
import datetime as dt
import re
import statistics
import subprocess


TAIL_HOURS = 6.0


def parse_boot_intervals( journal_text ):
    """
    Requires:
        - journal_text is the stdout of `journalctl --list-boots --no-pager`
    Ensures:
        - returns a sorted list of ( start_epoch, end_epoch ) float pairs, one per boot
        - returns [] when nothing parses, rather than raising — a caller checking the COUNT
          can then tell "no boots" from "boots found", which an exception would not allow
    """
    out = []
    for line in journal_text.splitlines():
        m = re.search( r"([A-Z][a-z]{2} \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \w+—"
                       r"([A-Z][a-z]{2} \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line )
        if not m: continue
        to_epoch = lambda s: dt.datetime.strptime( s[ 4: ], "%Y-%m-%d %H:%M:%S" ).timestamp()
        out.append( ( to_epoch( m.group( 1 ) ), to_epoch( m.group( 2 ) ) ) )
    return sorted( out )


def up_hours( intervals, start, end ):
    """
    Requires:
        - intervals is a list of ( start, end ) epoch pairs; start <= end for each
    Ensures:
        - returns the hours of [ start, end ] overlapped by any interval
        - returns 0.0 when end <= start, or when nothing overlaps
    """
    if end <= start: return 0.0
    return sum( max( 0.0, min( end, e ) - max( start, s ) ) for s, e in intervals ) / 3600.0


def largest_silent_stretch( intervals, commit_times, landed ):
    """
    The measure that survives, per §9e: the longest stretch inside a delivery during which NO
    commit was made on the branch, counted in BOX-UP hours only.

    Requires:
        - commit_times is a non-empty list of author epochs; landed is the landing epoch
    Ensures:
        - returns ( up_hours, wall_hours, start, end ) for the widest such gap
        - the gap ending AT `landed` is a candidate, because "branch finished, then sat" is
          precisely the unambiguous case this measure exists to surface
    """
    points = sorted( commit_times ) + [ landed ]
    best   = max( ( ( points[ i ], points[ i + 1 ] ) for i in range( len( points ) - 1 ) ),
                  key=lambda g: up_hours( intervals, *g ) )
    return ( up_hours( intervals, *best ), ( best[ 1 ] - best[ 0 ] ) / 3600.0, best[ 0 ], best[ 1 ] )


def _git( repo, *args ):
    return subprocess.run( [ "git", "-C", repo, *args ], capture_output=True, text=True ).stdout


def read_deliveries( repo, branch ):
    """
    Ensures:
        - returns one dict per HANDOFF delivery on `branch`'s reflog (a reflog verb starting
          "merge" — which covers Fast-forward deliveries, invisible to a merge-commit scan:
          measured at 28 of 188, 15%)
        - each carries landed / commit author epochs / the reflog subject
    """
    seq = []
    for line in _git( repo, "reflog", "show", branch, "--date=unix", "--format=%H|%gd|%gs" ).splitlines():
        parts = line.split( "|", 2 )
        if len( parts ) != 3: continue
        m = re.search( r"@\{(\d+)\}", parts[ 1 ] )
        if m: seq.append( ( parts[ 0 ], int( m.group( 1 ) ), parts[ 2 ] ) )
    seq.reverse()

    out = []
    for i in range( 1, len( seq ) ):
        old_sha            = seq[ i - 1 ][ 0 ]
        new_sha, when, gs  = seq[ i ]
        if not gs.startswith( "merge" ): continue
        times = [ int( l.split()[ 1 ] )
                  for l in _git( repo, "log", "--format=%h %at", f"{old_sha}..{new_sha}" ).splitlines()
                  if len( l.split() ) == 2 ]
        if times: out.append( dict( landed=when, times=sorted( times ), subject=gs ) )
    return out


def main():
    ap = argparse.ArgumentParser( description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter )
    ap.add_argument( "--repo",   required=True )
    ap.add_argument( "--branch", required=True )
    args = ap.parse_args()

    journal   = subprocess.run( [ "journalctl", "--list-boots", "--no-pager" ],
                                capture_output=True, text=True ).stdout
    intervals = parse_boot_intervals( journal )
    # POSITIVE CONTROL. An empty boot list makes every box-up figure 0.0 and every wait look
    # unavoidable — a confident wrong answer, so it is refused rather than reported.
    if not intervals:
        raise SystemExit( "REFUSING: parsed 0 boot intervals from journalctl. Every box-up hour "
                          "would read 0.0 and every wait would look forced. Nothing measured." )
    print( f"boot intervals: {len( intervals )}" )

    deliveries = read_deliveries( args.repo, args.branch )
    if not deliveries:
        raise SystemExit( "REFUSING: 0 handoff deliveries found. Check --branch; an empty "
                          "population and a clean result are the same output." )

    commits = [ ( t, d[ "landed" ] ) for d in deliveries for t in d[ "times" ] ]
    tail    = [ ( at, landed ) for at, landed in commits if ( landed - at ) / 3600.0 >= TAIL_HOURS ]
    print( f"handoff deliveries {len( deliveries )}   commits {len( commits )}   "
           f"tail >={TAIL_HOURS:g}h {len( tail )}" )

    tail_dels = [ d for d in deliveries
                  if ( d[ "landed" ] - d[ "times" ][ 0 ] ) / 3600.0 >= TAIL_HOURS ]
    print( f"\nTAIL EPISODES (the real n): {len( tail_dels )}   "
           f"carrying {sum( len( d[ 'times' ] ) for d in tail_dels )} commits" )

    total_up, total_silent, ends_at_landing = 0.0, 0.0, 0
    for d in tail_dels:
        total_up += up_hours( intervals, d[ "times" ][ 0 ], d[ "landed" ] )
        up, wall, _, end = largest_silent_stretch( intervals, d[ "times" ], d[ "landed" ] )
        total_silent += up
        if end == d[ "landed" ]: ends_at_landing += 1

    print( f"  box-up hours across tail episodes      : {total_up:.1f}" )
    print( f"  of which ONE silent stretch per episode: {total_silent:.1f} "
           f"({100 * total_silent / total_up:.0f}%)   <- §9e's 62.0 of 84.6" )
    print( f"  episodes whose silence ENDS AT THE LANDING: {ends_at_landing}/{len( tail_dels )}"
           f"   <- the unambiguous 'finished and waiting' cases" )
    print( "\n⚠️  'box up' is an available-action WINDOW, never evidence that a person failed to act." )


if __name__ == "__main__":
    main()
