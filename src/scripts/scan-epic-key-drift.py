#!/usr/bin/env python3
"""
Run the epic-key drift scan against the live task store — store row `5246bb67`.

WHY THIS SCRIPT EXISTS AND NOT JUST THE MODULE
----------------------------------------------
`cosa/rest/task_store_epic_keys.py` is the pure detector. A detector with no caller is
still silence — the lesson `scan-prose-task-refs.py` already carries on this same board.
This is the caller.

WHAT IT DOES
    1. Pages the LIVE board (non-terminal rows only, which is what the epic accordion
       renders) plus the known epic keys from GET /api/epic-stories, in two fetches.
    2. Buckets every row's `correlation_key` by tenant and reports the ungroupable ones.
    3. Prints the MANDATORY reach disclosure — on a clean run as well as a dirty one.

⚠️ REACH, STATED HERE AND AGAIN IN THE OUTPUT. This covers EVERY creation path — the MCP
verb, the hook lane, a raw POST, a future direct-repo call, hand-written SQL — because it
reads the ROWS rather than the doors. What it does NOT do is PREVENT drift: between two
runs the board can be wrong and nobody is told. And it cannot judge a `cc-task:*` mirror
row, whose key is load-bearing for the mirror's idempotency probe and therefore not
re-stampable; those are counted, never flagged. The module docstring has the full table.

⚠️ THE API KEY IS GITIGNORED (`src/conf/keys/**`) AND IS THEREFORE ABSENT FROM EVERY
WORKTREE. `read_api_key()` returns "" degrade-safe, the store answers 401, and a scan
that swallowed that would read an EMPTY BOARD as a CLEAN BOARD — a confident negative to
a question it never got to ask. So a bad fetch raises here and exits 2. Run from the main
checkout, or point `--key-root` at it.

EXIT CODES
    0  scanned, every row groupable
    1  findings present (blank / foreign / unknown-slug keys)
    2  could not reach the store / auth failure
    3  scanned, but the board was truncated — the result is PARTIAL, treat as unknown

Usage:
    PYTHONPATH=src python src/scripts/scan-epic-key-drift.py [--max-rows 2000]
                                                            [--include-terminal] [--json]
                                                            [--key-root /path/to/lupin]
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
from lupin_cli.claude_code.hooks.lib.task_store_client import read_api_key, _request

from cosa.rest.task_store_epic_keys import audit_rows, reach_disclosure

# The router caps `limit` at 500 (tasks.py:1131, `le=500`) but DEFAULTS to 100. So 500 is a
# CEILING, not a forced value, and this IS tunable anywhere in 0..500 — the old comment said
# "not a tunable", which was simply wrong (Tiberius, reviewing 2026-08-30). Kept at the
# ceiling to minimise round-trips; lower it freely, raise it above 500 and the router 422s.
PAGE_SIZE = 500


def fetch_board( settings, api_key, max_rows, include_terminal=False ):
    """
    Page the board and return ( rows, truncated ).

    Requires:
        - settings is load_task_store_settings()'s dict; api_key is a valid key
        - max_rows is a positive int

    Ensures:
        - returns ( rows, truncated ) where `truncated` is True iff the board has more
          rows than were fetched — the caller MUST surface that, never absorb it
        - RAISES on any non-ok response: a 401 that returned an empty list would scan
          CLEAN, which is the exact false-green this scan exists to prevent
        - never raises on a genuinely empty board
    """
    rows      = [ ]
    offset    = 0
    truncated = False

    while True:
        query = ( f"include_terminal={'true' if include_terminal else 'false'}"
                  f"&unscoped_audit=true&hide_parked=false"
                  f"&limit={PAGE_SIZE}&offset={offset}" )
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


def fetch_known_epic_keys( settings, api_key ):
    """
    Read the hand-maintained epic keys from GET /api/epic-stories.

    Requires:
        - settings / api_key as for fetch_board

    Ensures:
        - returns a list of `epic:<slug>` strings with the `_README` key excluded
        - returns None (NOT an empty list) when the endpoint cannot be read, so the
          caller SKIPS the unknown-slug check rather than reporting every epic key as
          unknown — an unreadable key list must not manufacture findings
        - never raises
    """
    try:
        ok, _status, body = _request( "GET", f"{settings[ 'api_base_url' ]}/api/epic-stories",
                                      api_key, settings[ "timeout_seconds" ] )
    except Exception:
        return None
    if not ok or not isinstance( body, dict ): return None

    stories = body.get( "stories" )
    if not isinstance( stories, dict ): return None
    return [ key for key in stories.keys() if not key.startswith( "_" ) ]


def render( report, rows, known_keys, truncated, include_terminal ):
    """
    Print the human-readable report. Returns nothing; the caller owns the exit code.

    Ensures:
        - every finding is printed with its reason
        - the reach disclosure is printed whether the run was clean or not
        - never raises
    """
    print( f"\nEPIC-KEY DRIFT SCAN — {len( rows )} board rows fetched\n" )
    for finding in report[ "findings" ]:
        row_id = ( finding[ "id" ] or "?" )[ :8 ]
        print( f"  ✗ {row_id} [{finding[ 'status' ]}] {( finding[ 'title' ] or '' )[ :58 ]}" )
        print( f"      {finding[ 'reason' ].upper()} — correlation_key="
               f"{finding[ 'correlation_key' ]!r}" )
    if not report[ "findings" ]: print( "  (every row carries a known epic key)" )
    print()
    print( reach_disclosure( report, known_keys, include_terminal, truncated ) )


def main( argv=None ):
    parser = argparse.ArgumentParser( description="Scan the task store for epic-key drift" )
    parser.add_argument( "--max-rows", type=int, default=2000 )
    parser.add_argument( "--include-terminal", action="store_true",
                         help="also scan done/dropped rows (history; the board does not render them)" )
    parser.add_argument( "--json", action="store_true", help="emit the raw report as JSON" )
    parser.add_argument( "--key-root", default=None,
                         help="read the API key from this checkout instead of LUPIN_ROOT "
                              "(the key file is gitignored and absent from worktrees)" )
    args = parser.parse_args( argv )

    settings = load_task_store_settings()
    api_key  = read_api_key( { "LUPIN_ROOT": args.key_root } ) if args.key_root else read_api_key()

    try:
        rows, truncated = fetch_board( settings, api_key, args.max_rows, args.include_terminal )
    except Exception as error:
        print( f"✗ could not read the task store: {error}", file=sys.stderr )
        print( "  (an empty board would scan CLEAN, so this is an exit 2, never a pass)",
               file=sys.stderr )
        return 2

    known_keys = fetch_known_epic_keys( settings, api_key )
    report     = audit_rows( rows, known_epic_keys=known_keys )

    if args.json:
        print( json.dumps( { **report, "truncated": truncated,
                             "reach": reach_disclosure( report, known_keys,
                                                        args.include_terminal, truncated ) },
                            indent=2 ) )
    else:
        render( report, rows, known_keys, truncated, args.include_terminal )

    if truncated:
        print( f"\n⚠️  BOARD TRUNCATED at {args.max_rows} rows — this result is PARTIAL. "
               f"Re-run with a larger --max-rows before believing a clean verdict.",
               file=sys.stderr )
        return 3

    return 1 if report[ "findings" ] else 0


if __name__ == "__main__":
    sys.exit( main() )
