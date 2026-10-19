#!/usr/bin/env python3
"""
Run the prose task-reference scan against the live task store.

Why a script and not just the module: `cosa/rest/task_store_prose_refs.py` is the pure
detector. A detector with no caller is still silence, because nothing runs it.
Shipping a scanner nobody invokes would repeat that failure. This script is the
caller.

What it does:
    1. Pages the whole board once (include_terminal + unscoped_audit + hide_parked=false)
       so one fetch yields both the bodies to scan and the id -> status map to resolve
       against. No second round-trip, no per-row lookup.
    2. Scans every non-terminal body for id-shaped citations.
    3. Prints findings, the three buckets, and the mandatory scope disclosure.

Truncation is reported, never swallowed. If the board exceeds `--max-rows`, the status
map is incomplete and every unresolvable citation lands in `unresolved_canonical`. That
is the safe direction (no false finding), but it silently narrows what the scan could
see. The script says so loudly and exits 3, because a partial scan reporting clean is
the false green this scan exists to prevent.

Exit codes:
    0  scanned, no findings
    1  findings present
    2  could not reach the store / auth failure
    3  scanned, but the board was truncated. The result is partial, so treat as unknown

Usage:
    PYTHONPATH=src python src/scripts/scan-prose-task-refs.py [--max-rows 2000] [--json]
"""

import argparse
import json
import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
from lupin_cli.claude_code.hooks.lib.task_store_client import read_api_key, _request, FETCH_BOARD_PAGE_SIZE
from lupin_cli.claude_code.hooks.lib.task_store_client import fetch_board as _shared_fetch_board

from cosa.rest.task_store_prose_refs import scan_rows
from cosa.rest.task_store_rules import TERMINAL_STATUSES

PAGE_SIZE = FETCH_BOARD_PAGE_SIZE


def fetch_board( settings, api_key, max_rows ):
    """
    Page the entire board, terminal rows included.

    Requires:
        - settings is load_task_store_settings()'s dict; api_key is a valid key
        - max_rows is a positive int

    Ensures:
        - returns ( rows, truncated ) where `truncated` is True iff the board has more
          rows than were fetched — the caller must surface that, never absorb it
        - never raises on an empty board
    """
    return _shared_fetch_board( settings, api_key, max_rows, include_terminal=True, request=_request )


def main( argv=None ):
    parser = argparse.ArgumentParser( description="Scan task-store bodies for dead id citations" )
    parser.add_argument( "--max-rows", type=int, default=2000 )
    parser.add_argument( "--json", action="store_true", help="emit the raw report as JSON" )
    args = parser.parse_args( argv )

    settings = load_task_store_settings()
    api_key  = read_api_key()

    try:
        rows, truncated = fetch_board( settings, api_key, args.max_rows )
    except Exception as error:
        print( f"✗ could not read the task store: {error}", file=sys.stderr )
        return 2

    status_by_id = { row[ "id" ]: row.get( "status" ) for row in rows if row.get( "id" ) }
    scannable    = [ row for row in rows if row.get( "status" ) not in TERMINAL_STATUSES ]
    report       = scan_rows( scannable, status_by_id )

    if args.json:
        print( json.dumps( { **report, "truncated": truncated }, indent=2 ) )
    else:
        print( f"\nPROSE-REF SCAN — {len( rows )} board rows fetched, "
               f"{report[ 'bodies_scanned' ]} non-terminal bodies scanned\n" )
        for finding in report[ "findings" ]:
            print( f"  ✗ {finding[ 'row_id' ][ :8 ]} [{finding[ 'row_status' ]}] "
                   f"{( finding[ 'row_title' ] or '' )[ :60 ]}" )
            print( f"      cites {finding[ 'cited_id' ][ :8 ]} — "
                   f"{finding[ 'reason' ].upper()} ({finding[ 'cited_state' ]}), no blocked_by edge" )
        if not report[ "findings" ]: print( "  (no dead id-citations found)" )
        print()
        print( report[ "scope" ] )

    if truncated:
        print( f"\n⚠️  BOARD TRUNCATED at {len( rows )} rows — the status map is INCOMPLETE "
               f"and this result is PARTIAL. Re-run with a larger --max-rows before believing "
               f"a clean verdict.", file=sys.stderr )
        return 3

    return 1 if report[ "findings" ] else 0


if __name__ == "__main__":
    sys.exit( main() )
