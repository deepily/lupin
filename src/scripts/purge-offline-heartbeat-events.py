#!/usr/bin/env python3
"""
Purge OFFLINE-marked heartbeat-event files from the live arbiter roster source.

The standalone arbiter (:8001) rebuilds its fleet table every poll from one
JSONL file per session under ~/.claude/heartbeat-events/. There is no aging on
that directory, so every session that ever emitted an event lingers forever and
shows as "offline" days later. This tool archives the event files for sessions
the live arbiter currently marks `liveness.verdict == "offline"`, leaving the
LIVE/quiet sessions untouched — giving a fresh, accurate roster on the next poll.

SAFE BY DEFAULT: dry-run unless --apply is passed. Files are MOVED to a timestamped
archive dir (recoverable), never hard-deleted. Deleting while :8001 runs is safe —
the event tailer skips missing files (offset preserved); no arbiter restart needed.

Run (dry-run first):
    python3 src/scripts/purge-offline-heartbeat-events.py
Then apply:
    python3 src/scripts/purge-offline-heartbeat-events.py --apply
"""
import argparse
import datetime
import json
import os
import shutil
import urllib.request


def fetch_offline_and_live( state_url, timeout ):
    """
    Fetch the arbiter snapshot and partition its sessions by liveness verdict.

    Requires:
        - state_url points at the arbiter /state endpoint
        - timeout is a positive number of seconds

    Ensures:
        - returns ( offline, live ) — two lists of session dicts; a session is
          OFFLINE iff liveness.verdict == "offline", else LIVE (kept)
        - raises urllib.error.URLError / json.JSONDecodeError on a bad fetch
    """
    raw      = urllib.request.urlopen( state_url, timeout=timeout ).read()
    state    = json.loads( raw )
    sessions = ( state.get( "fleet_arbiter" ) or { } ).get( "sessions" ) or [ ]
    offline  = [ s for s in sessions if ( s.get( "liveness" ) or { } ).get( "verdict" ) == "offline" ]
    live     = [ s for s in sessions if ( s.get( "liveness" ) or { } ).get( "verdict" ) != "offline" ]
    return offline, live


def main():
    parser = argparse.ArgumentParser( description="Archive offline-marked heartbeat-event files." )
    parser.add_argument( "--apply", action="store_true", help="Actually move files (default: dry-run)." )
    parser.add_argument( "--state-url", default="http://localhost:8001/state" )
    parser.add_argument( "--events-dir", default=os.path.expanduser( "~/.claude/heartbeat-events" ) )
    parser.add_argument( "--timeout", type=int, default=5 )
    # INJECTABLE ON PURPOSE (Mr Radio's ruling, 2026-08-30). This used to be built
    # inline as /tmp/lupin-heartbeat-purge-<ts> with nothing able to redirect it, so
    # an end-to-end --apply test could only be written by writing into /tmp — the one
    # directory this fleet's doctrine tells every seat to stay out of. The default is
    # unchanged, so no caller has to do anything differently.
    parser.add_argument( "--archive-dir", default=None,
                         help="Where to archive event files (default: a timestamped dir under /tmp)." )
    args = parser.parse_args()

    offline, live = fetch_offline_and_live( args.state_url, args.timeout )
    mode = "APPLY" if args.apply else "DRY-RUN"
    print( f"[{mode}] snapshot: offline={len( offline )} | keep(live/quiet)={len( live )}" )

    print( "\nKEEP (untouched):" )
    for s in live:
        verdict = ( s.get( "liveness" ) or { } ).get( "verdict" )
        print( f"  {str( s.get( 'persona' ) ):14} {s.get( 'session_id' )}  [{verdict}]" )

    ts      = datetime.datetime.now().strftime( "%Y.%m.%d-at-%H%M%S" )
    archive = args.archive_dir or f"/tmp/lupin-heartbeat-purge-{ts}"

    moved, nofile = [ ], [ ]
    for s in offline:
        sid = s.get( "session_id" )
        src = os.path.join( args.events_dir, f"{sid}.jsonl" )
        if sid and os.path.isfile( src ):
            if args.apply:
                os.makedirs( archive, exist_ok=True )
                shutil.move( src, os.path.join( archive, f"{sid}.jsonl" ) )
            moved.append( ( s.get( "persona" ), sid ) )
        else:
            nofile.append( ( s.get( "persona" ), sid ) )

    verb = "ARCHIVED" if args.apply else "WOULD ARCHIVE"
    print( f"\n{verb} {len( moved )} offline event files" + ( f" -> {archive}" if args.apply else "" ) + ":" )
    for p, sid in moved:
        print( f"  {str( p ):14} {sid}" )

    if nofile:
        print( f"\nOFFLINE but NO event file on disk ({len( nofile )}) — commons-only (24h self-expiry), not purged here:" )
        for p, sid in nofile:
            print( f"  {str( p ):14} {sid}" )

    if not args.apply:
        print( "\n(DRY-RUN — nothing moved. Re-run with --apply to archive.)" )


if __name__ == "__main__":
    main()
