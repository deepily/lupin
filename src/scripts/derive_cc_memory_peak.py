#!/usr/bin/env python3
"""
Derive the concurrency + memory peak for row 117ed1b6 from the CC memory watcher log.

This REPLACES the snippet retired in that row's body on 2026-08-25. That snippet
had three defects, and this file exists to not repeat them:

  1. It read 3.7% of the log without saying so. Every peak here is printed beside
     `n_excluded` and the session denominator, so a reader can never mistake a
     window's property for the fleet's.
  2. It summed rss_gb, which is per-PROCESS VmRSS. A cgroup cap is enforced on the
     per-SCOPE tree. This groups on `scope_anon_gb` — the noun the cap acts on,
     added to the watcher in ab2a321c.
  3. Summing VmRSS does not recover the scope figure either (shared pages counted
     once per process vs once per cgroup), so no arithmetic over rss_gb is offered.

⚠️ A steady-state sample shows a cap is SAFE, never that it is UNNECESSARY, and it
cannot bound a peak it was not running for.
"""
import sys
import re
import collections

DEFAULT_LOG = "/home/rruiz/.claude/sessions/cc-memory-samples.log"

# Post-fix lines only: both a timestamp (to group passes) and the enforced noun.
USABLE_LINE = re.compile(
    r"ts=(\S+)\s+pid=(\d+)\s+rss_gb=\s*([\d.]+)(?:\s+scope_anon_gb=\s*([\d.]+))?.*?session=(\S+)"
)
# Counted over EVERY rss_gb line, matched or not. Using USABLE_LINE for the
# denominator would omit exactly the population the exclusion note discloses —
# that is the defect this file was written to avoid, and it was made once already.
ANY_SESSION = re.compile( r"session=(\S+)" )


def derive( lines ):
    """
    Reduce watcher report lines to a peak plus everything it could not see.

    Requires:
        - lines is an iterable of strings from the watcher's --report stream

    Ensures:
        - returns a dict carrying the peaks AND total/usable/excluded counts
        - counts sessions over ALL rss_gb lines, not only groupable ones
        - returns usable == 0 rather than raising when no line carries both fields

    Raises:
        - nothing
    """
    total        = 0
    no_timestamp = 0
    no_scope     = 0
    per_pass     = collections.defaultdict( dict )   # ts -> { session: anon_gb }
    all_sessions = set()
    win_sessions = set()

    for line in lines:
        if "rss_gb=" not in line: continue
        total += 1
        any_match = ANY_SESSION.search( line )
        if any_match: all_sessions.add( any_match.group( 1 ) )

        match = USABLE_LINE.search( line )
        if match is None:
            no_timestamp += 1
            continue
        timestamp, _pid, _rss, anon_gb, session = match.groups()
        if anon_gb is None:
            no_scope += 1
            continue
        win_sessions.add( session )
        # One line per seat per pass; keying on session makes a repeat idempotent.
        per_pass[ timestamp ][ session ] = float( anon_gb )

    usable = sum( len( seats ) for seats in per_pass.values() )
    result = {
        "total_lines"      : total,
        "usable_lines"     : usable,
        "excluded_no_ts"   : no_timestamp,
        "excluded_no_scope": no_scope,
        "sessions_all"     : len( all_sessions ),
        "sessions_window"  : len( win_sessions ),
        "passes"           : len( per_pass ),
    }
    if not per_pass:
        result.update( concurrency_peak=0, box_anon_peak_gb=0.0, worst_scope_gb=0.0 )
        return result

    concurrency = { ts: len( seats )          for ts, seats in per_pass.items() }
    box_total   = { ts: sum( seats.values() ) for ts, seats in per_pass.items() }
    worst       = max( ( gb, seat, ts ) for ts, seats in per_pass.items() for seat, gb in seats.items() )

    peak_conc_ts = max( concurrency, key=concurrency.get )
    peak_box_ts  = max( box_total,   key=box_total.get   )
    result.update(
        concurrency_peak    = concurrency[ peak_conc_ts ],
        concurrency_peak_ts = peak_conc_ts,
        box_anon_peak_gb    = box_total[ peak_box_ts ],
        box_anon_peak_ts    = peak_box_ts,
        worst_scope_gb      = worst[ 0 ],
        worst_scope_seat    = worst[ 1 ],
        worst_scope_ts      = worst[ 2 ],
        window_first        = min( per_pass ),
        window_last         = max( per_pass ),
    )
    return result


def render( r, log_path ):
    """
    Format a derive() result so no peak is printed without its exclusions.

    Requires:
        - r is a dict returned by derive()

    Ensures:
        - returns a multi-line string naming n_excluded beside every peak
    """
    if r[ "total_lines" ] == 0:
        return f"log {log_path}\nNO rss_gb LINES — nothing to derive."
    if r[ "usable_lines" ] == 0:
        return (
            f"log {log_path}\n"
            f"rss_gb lines total       {r[ 'total_lines' ]:>7,}\n"
            f"NO USABLE LINES — none carries both ts= and scope_anon_gb=.\n"
            f"The watcher predates ab2a321c, or has not been restarted since."
        )
    pct_usable   = 100.0 * r[ "usable_lines" ] / r[ "total_lines" ]
    excluded     = r[ "total_lines" ] - r[ "usable_lines" ]
    pct_excluded = 100.0 * excluded / r[ "total_lines" ]
    return "\n".join( [
        f"log                       {log_path}",
        f"rss_gb lines total        {r[ 'total_lines' ]:>7,}",
        f"  usable (ts+scope_anon)  {r[ 'usable_lines' ]:>7,}  ({pct_usable:.1f}%)",
        f"  EXCLUDED no ts=         {r[ 'excluded_no_ts' ]:>7,}",
        f"  EXCLUDED no scope_anon  {r[ 'excluded_no_scope' ]:>7,}",
        f"sessions in whole log     {r[ 'sessions_all' ]:>7}",
        f"sessions in usable window {r[ 'sessions_window' ]:>7}   <- the denominator the peaks are over",
        f"passes                    {r[ 'passes' ]:>7}",
        f"window                    {r[ 'window_first' ]} .. {r[ 'window_last' ]}",
        "",
        f"concurrency peak          {r[ 'concurrency_peak' ]:>7}   at {r[ 'concurrency_peak_ts' ]}",
        f"box-level anon peak       {r[ 'box_anon_peak_gb' ]:>7.2f} GiB at {r[ 'box_anon_peak_ts' ]}",
        f"worst single scope        {r[ 'worst_scope_gb' ]:>7.2f} GiB  seat {r[ 'worst_scope_seat' ]} at {r[ 'worst_scope_ts' ]}",
        "",
        f"⚠️  peaks are over {r[ 'sessions_window' ]} of {r[ 'sessions_all' ]} sessions this log has recorded;",
        f"    {excluded:,} of {r[ 'total_lines' ]:,} lines ({pct_excluded:.1f}%) predate the fields and are ungroupable.",
        "⚠️  worst-seat names a WINDOW, not a property of that seat — it moved seats "
        "inside ten minutes on 2026-08-25.",
    ] )


def main():
    log_path = sys.argv[ 1 ] if len( sys.argv ) > 1 else DEFAULT_LOG
    with open( log_path ) as handle:
        print( render( derive( handle ), log_path ) )


if __name__ == "__main__":
    main()
