#!/usr/bin/env python3
"""
Rejoin blocked rows whose blockers are ALL `done` — store row 00a6bde2, item 3.

WHY THIS SCRIPT EXISTS AND NOT JUST THE MODULE
----------------------------------------------
`cosa/rest/task_store_rejoin.py` is the pure decision. A decision with no caller is still
silence — row `1dd41cde` ("Nothing RUNS verify") on this same board. This is the caller.

⚠️ IT IS A CALLER, NOT A SCHEDULE. Nothing runs this on a timer. That gap is named here
rather than left for the commit's existence to imply it was covered — the identical
disclosure item 4's scanner carries.

DRY-RUN BY DEFAULT. `--apply` is the only thing that writes. The pass moves rows into the
workable set where a seat will pick them up, so the default had to be the reversible one.

WRITE ORDER IS AMEND-THEN-TRANSITION, AND THAT ORDER IS LOAD-BEARING
--------------------------------------------------------------------
Transition first and the amend fails -> the row is QUEUED, workable, and READS AS FRESHLY
VETTED. That is precisely the defect item 3 exists to prevent, manufactured by the fix.
Amend first and the transition fails -> the row stays BLOCKED (nobody works a blocked row)
carrying a stamp that has not come true yet. Visible, harmless, retried next run. A
re-run then appends a second stamp, which is honest: it was attempted twice.

WHAT IT NEVER TOUCHES
    · a row with a `dropped` blocker — Rick's ruling, and only his
    · a row with an unresolvable blocker — a dead edge is not a satisfied precondition
    · a row with a persona/user blocker — no registry exists to resolve one

EXIT CODES
    0  examined, nothing eligible (or dry-run with nothing eligible)
    1  eligible rows found (dry-run), or rejoined successfully (--apply)
    2  could not reach the store / auth failure
    3  the board was truncated — the result is PARTIAL, treat as unknown
    4  --apply ran and at least one row failed mid-write (named in the output)

Usage:
    PYTHONPATH=src python src/scripts/rejoin-done-blocked-rows.py            # dry run
    PYTHONPATH=src python src/scripts/rejoin-done-blocked-rows.py --apply
"""

import argparse
import json
import os
import sys

from datetime import datetime, timezone

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
from lupin_cli.claude_code.hooks.lib.task_store_client import read_api_key, _request, transition_task

from cosa.rest.task_store_rejoin import (
    VERDICT_REJOIN,
    classify_blocked_row,
    dormancy_stamp,
    scope_disclosure,
)
from cosa.rest.task_store_rules import BLOCKED_STATUS

PAGE_SIZE = 500      # the router's hard `le=500` cap; not a tunable


def fetch_board( settings, api_key, max_rows ):
    """
    Page the entire board, terminal rows included.

    Terminal rows are REQUIRED here, not incidental: the blockers this pass resolves are
    `done` by definition, so a fetch that excluded them would resolve every blocker to
    None and the pass would rejoin NOTHING while reporting a clean run.

    Requires:
        - settings is load_task_store_settings()'s dict; api_key is a valid key
        - max_rows is a positive int

    Ensures:
        - returns ( rows, truncated ); `truncated` is True iff the board holds more rows
          than were fetched — the caller MUST surface that, never absorb it
        - raises on a non-2xx rather than returning an empty board (an unchecked 401
          scans CLEAN, which is the false-green this row family is made of)
    """
    rows      = [ ]
    offset    = 0
    truncated = False

    while True:
        # Ask for no more than the caller still has room for. A flat PAGE_SIZE here made
        # `--max-rows` a page-stop THRESHOLD rather than a cap (row 9124b70a): `--max-rows 100`
        # fetched 500 and then reported "truncated at 100 rows" — a figure the run never
        # honoured. `max( 1, … )` is reachable only via a direct non-positive max_rows; the
        # break below guarantees the subtraction is >= 1 on every later pass.
        limit = max( 1, min( PAGE_SIZE, max_rows - len( rows ) ) )
        query = ( f"include_terminal=true&unscoped_audit=true&hide_parked=false"
                  f"&limit={limit}&offset={offset}" )
        ok, status, page = _request( "GET", f"{settings[ 'api_base_url' ]}/api/tasks?{query}",
                                     api_key, settings[ "timeout_seconds" ] )
        if not ok:
            raise RuntimeError( f"HTTP {status}: {page.get( 'error' ) or page.get( 'detail' ) or page}" )
        batch = page.get( "tasks", [ ] )
        rows.extend( batch )
        offset += len( batch )

        if not page.get( "has_more" ) or not batch: break
        if len( rows ) >= max_rows:
            truncated = True
            break

    return ( rows, truncated )


def examine( rows, now ):
    """
    Classify every blocked row on the board.

    Requires:
        - rows is the full board (terminal rows INCLUDED — see fetch_board)
        - now is the comparison instant as a datetime

    Ensures:
        - returns ( eligible, counts ) where eligible is a list of
          { row, stamp, closed_blocker_ids } and counts tallies every verdict/hold bucket
        - `examined` counts only rows whose status is BLOCKED_STATUS
        - a row whose blocker is missing from the board (truncation) classifies as
          unresolved and is NOT rejoined
        - never raises
    """
    status_by_id = { row[ "id" ]: row.get( "status" )     for row in rows if row.get( "id" ) }
    closed_at    = { row[ "id" ]: row.get( "updated_ts" ) for row in rows if row.get( "id" ) }

    eligible = [ ]
    counts   = { "examined": 0 }

    for row in rows:
        if row.get( "status" ) != BLOCKED_STATUS: continue
        counts[ "examined" ] += 1

        verdict = classify_blocked_row( row.get( "status" ), row.get( "blocked_by" ), status_by_id )
        key     = verdict[ "verdict" ] or verdict[ "reason" ]
        counts[ key ] = counts.get( key, 0 ) + 1

        if verdict[ "verdict" ] != VERDICT_REJOIN: continue

        blockers = [ { "id": ref_id, "closed_at": closed_at.get( ref_id ) }
                     for ref_id in verdict[ "closed_blocker_ids" ] ]
        eligible.append( {
            "row"                : row,
            "stamp"              : dormancy_stamp( blockers, now ),
            "closed_blocker_ids" : verdict[ "closed_blocker_ids" ],
        } )

    return ( eligible, counts )


def apply_rejoin( settings, api_key, actor, candidate ):
    """
    Amend then transition ONE row. Amend FIRST — see the module docstring.

    Requires:
        - candidate is one `examine()` eligible entry
        - actor is the persona + session id performing the write

    Ensures:
        - returns ( ok, stage, detail ); stage is "amend" or "transition" on failure and
          "done" on success
        - a failed amend NEVER proceeds to the transition — the stamp is the point, and a
          row rejoined without it is the defect wearing the fix's clothes
        - never raises
    """
    item_id = candidate[ "row" ][ "id" ]

    ok, status, body = _request(
        "POST", f"{settings[ 'api_base_url' ]}/api/tasks/{item_id}/amend", api_key,
        settings[ "timeout_seconds" ],
        body={ "note": candidate[ "stamp" ], "actor": actor, "authority": "standing",
               "reason": "00a6bde2 item 3 — done-arm auto-rejoin, dormancy stamp" },
    )
    if not ok:
        return ( False, "amend", f"HTTP {status}: {body.get( 'detail' ) or body}" )

    ok, status, body = transition_task(
        settings, api_key, item_id,
        { "to_status": "queued", "actor": actor, "authority": "standing",
          "reason": "00a6bde2 item 3 — every blocker is `done`; the wait was over. "
                    "Dormancy + unverified-premise warning stamped on the body." },
    )
    if not ok:
        return ( False, "transition", f"HTTP {status}: {body.get( 'detail' ) or body}" )

    return ( True, "done", None )


def main( argv=None ):
    parser = argparse.ArgumentParser( description="Rejoin blocked rows whose blockers are all done" )
    parser.add_argument( "--apply", action="store_true", help="WRITE. Default is a dry run." )
    parser.add_argument( "--actor", default=None, help="persona + session id stamped on the writes" )
    parser.add_argument( "--max-rows", type=int, default=2000 )
    parser.add_argument( "--json", action="store_true", help="emit the raw report as JSON" )
    args = parser.parse_args( argv )

    settings = load_task_store_settings()
    api_key  = read_api_key()
    now      = datetime.now( timezone.utc )

    try:
        rows, truncated = fetch_board( settings, api_key, args.max_rows )
    except Exception as error:
        print( f"✗ could not read the task store: {error}", file=sys.stderr )
        return 2

    eligible, counts = examine( rows, now )

    if args.json:
        print( json.dumps( { "counts": counts, "truncated": truncated,
                             "eligible": [ c[ "row" ][ "id" ] for c in eligible ] }, indent=2 ) )
    else:
        mode = "APPLY" if args.apply else "DRY RUN"
        print( f"\nDONE-ARM REJOIN [{mode}] — {len( rows )} board rows fetched, "
               f"{counts[ 'examined' ]} blocked rows examined\n" )
        for candidate in eligible:
            row = candidate[ "row" ]
            print( f"  ✓ {row[ 'id' ][ :8 ]} {( row.get( 'title' ) or '' )[ :60 ]}" )
            print( f"      every blocker done: {', '.join( b[ :8 ] for b in candidate[ 'closed_blocker_ids' ] )}" )
        if not eligible: print( "  (no blocked row has all-done blockers)" )
        print()
        print( scope_disclosure( counts ) )

    failures = [ ]
    if args.apply:
        actor = args.actor or os.environ.get( "LUPIN_TASK_ACTOR" )
        if not actor:
            print( "✗ --apply requires --actor (or LUPIN_TASK_ACTOR) — the write is audited "
                   "to a real seat, never anonymous", file=sys.stderr )
            return 4
        for candidate in eligible:
            ok, stage, detail = apply_rejoin( settings, api_key, actor, candidate )
            item_id = candidate[ "row" ][ "id" ]
            if ok:
                print( f"  → rejoined {item_id[ :8 ]}" )
            else:
                failures.append( ( item_id, stage, detail ) )
                print( f"  ✗ {item_id[ :8 ]} FAILED at {stage}: {detail}", file=sys.stderr )
                if stage == "transition":
                    print( f"      the row is STILL BLOCKED and now carries a stamp that has not "
                           f"come true — re-run to retry; the second stamp is honest.", file=sys.stderr )
    elif eligible and not args.json:
        # `and not args.json` (row 022d4232): --json exists so a caller can parse stdout, and
        # this line used to print after the JSON whenever the pass found something — making
        # the output parseable only when there was nothing to report. It stays coupled to
        # `if args.apply:` rather than moving into the human `else:` arm above, because it is
        # the else-branch of "did we write"; up there it would also print after an --apply run.
        print( f"DRY RUN — nothing was written. Re-run with --apply --actor '<persona> <sid8>' "
               f"to rejoin these {len( eligible )} row(s)." )

    if truncated:
        print( f"\n⚠️  BOARD TRUNCATED at {len( rows )} rows — blockers outside the fetched set "
               f"resolve as UNRESOLVED and were held, so this run under-reports. Re-run with a "
               f"larger --max-rows before believing it found everything.", file=sys.stderr )
        return 3

    if failures: return 4
    return 1 if eligible else 0


if __name__ == "__main__":
    sys.exit( main() )
