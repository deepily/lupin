#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Build a checkpoint cohort without the Stop-hook yes/no cards.

Rick ruled "new cohort, keep old" on 24 Nov 2026. The Stop hook stopped asking these cards on
6 Jun 2026 (commit 40c5491f4), so they no longer describe how Rick is asked. The current cohort
file is read and never written. The filtered cohort, its manifest and the dropped ids are new
files. The database is read in a read-only transaction.

A card is a Stop-hook card when its title is exactly "Stop hook: Anything else?".

Run from a seat tree, pinning all three:

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/filter_stop_hook_cards.py
"""

import argparse
import json
import sys

from sqlalchemy import text

import cosa.utils.util as cu
from cosa.research.phi4_flash_lite_study import freeze_corpus as fc
from cosa.research.preference_replay.retune_run import read_id_list

STOP_TITLE = "Stop hook: Anything else?"
STOP_SQL   = "SELECT id FROM notifications WHERE title = :title"
COHORT     = "/src/conf/prediction-checkpoint-cohort.jsonl"
FILTERED   = "/src/conf/prediction-checkpoint-cohort-no-stop-hook.jsonl"
MANIFEST   = "/src/conf/prediction-checkpoint-cohort-no-stop-hook-manifest.json"
DROPPED    = "/src/conf/prediction-checkpoint-cohort-stop-hook-ids.txt"


def stop_hook_ids( session ):
    """
    Read the ids of every Stop-hook card in a read-only transaction.

    Requires:
        - session is an active SQLAlchemy session on the database that holds the notifications

    Ensures:
        - the first statement makes the transaction read-only, and the transaction is rolled back
        - returns the set of ids as lower-case dashed strings, the form the cohort file uses
    """
    session.execute( text( "SET TRANSACTION READ ONLY" ) )
    try: return { str( row[ 0 ] ).lower() for row in session.execute( text( STOP_SQL ), { "title": STOP_TITLE } ) }
    finally: session.rollback()


def split_cohort( ids, stop_ids ):
    """
    Cut the Stop-hook cards out of a cohort, keeping its order.

    Requires:
        - ids is a list of ask ids; stop_ids is a set of ids

    Ensures:
        - returns ( kept, dropped ), both in the cohort's order, with kept + dropped equal to ids
    """
    return [ one for one in ids if one not in stop_ids ], [ one for one in ids if one in stop_ids ]


def build( cohort_path, out_path, manifest_path, dropped_path, stop_ids ):
    """
    Write the filtered cohort, its manifest and the dropped ids, then check the manifest.

    Requires:
        - cohort_path is the committed cohort file; the three output paths are new files
        - stop_ids is the set stop_hook_ids returned

    Ensures:
        - the cohort file is only read
        - the filtered file holds { "id": ... } lines in the cohort's order, written as the committed cohort is
        - the manifest has the committed manifest's three keys and verify_snapshot accepts it
        - returns { source_rows, kept, dropped, stop_hook_cards_not_in_cohort, filtered_sha256, source_sha256 }

    Raises:
        - RuntimeError when verify_snapshot refuses the new manifest, or when the cohort has no Stop-hook card to drop
    """
    ids           = read_id_list( cohort_path )
    kept, dropped = split_cohort( ids, stop_ids )
    if not dropped: raise RuntimeError( "no cohort id is a Stop-hook card: the filter would change nothing" )
    rows = [ { "id": one } for one in kept ]
    fc.write_snapshot( rows, out_path )
    manifest = { "minimum_rows": 1, "snapshot_row_count": len( rows ), "snapshot_sha256": fc.sha256_of_rows( rows ) }
    with open( manifest_path, "w", encoding="utf-8" ) as handle: json.dump( manifest, handle )
    with open( dropped_path, "w", encoding="utf-8" ) as handle: handle.write( "".join( one + "\n" for one in dropped ) )
    ok, detail = fc.verify_snapshot( out_path, manifest_path )
    if not ok: raise RuntimeError( f"the filtered cohort does not match its own manifest: {detail}" )
    return { "source_rows": len( ids ), "kept": len( kept ), "dropped": len( dropped ),
             "stop_hook_cards_not_in_cohort": len( stop_ids - set( ids ) ),
             "filtered_sha256": manifest[ "snapshot_sha256" ], "source_sha256": fc.sha256_of_rows( [ { "id": one } for one in ids ] ) }


def main( argv=None ):
    """
    Read the Stop-hook ids from the database and write the three new files.

    Requires:
        - the database named by the configuration is reachable

    Ensures:
        - prints the receipt as JSON and returns 0
    """
    parser = argparse.ArgumentParser( description="Build the checkpoint cohort without the Stop-hook cards (read only)." )
    root   = cu.get_project_root()
    parser.add_argument( "--cohort", default=root + COHORT )
    parser.add_argument( "--out", default=root + FILTERED )
    parser.add_argument( "--manifest", default=root + MANIFEST )
    parser.add_argument( "--dropped", default=root + DROPPED )
    args = parser.parse_args( argv )
    from cosa.rest.db.database import get_db
    with get_db() as session: stop_ids = stop_hook_ids( session )
    print( json.dumps( build( args.cohort, args.out, args.manifest, args.dropped, stop_ids ), indent=1, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit( main() )
