"""
One side file of question vectors for one context arm, over the frozen cohort.

The arm's text is built for each frozen ask from the ask's notification and its rebuilt context, as of the
ask. The texts go through the same generator as the question-only side file, so the model, the stamp reads and
the file layout are the same. The database is read in a read-only transaction and never written.

    python -m cosa.research.preference_replay.arm_vectors --arm Q+A --frozen-ids src/conf/prediction-checkpoint-cohort.jsonl \
        --out io/question-vectors/2026.11.19-arm-q-a.jsonl --probe-only
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy import text

from cosa.agents.prediction_engine.history_context_rebuild import rebuild_context
from cosa.memory.embedding_provider import get_embedding_provider
from cosa.research.preference_replay.context_arms import ARMS, build_arm_texts, read_arm_inputs
from cosa.research.preference_replay.question_vectors import BATCH_SIZE, FACTS_SQL, PROBE_SIZE, generate, write_side_file
from cosa.rest.db.database import get_db
from cosa.utils.file_hash import file_sha256

ARM_TEXT_RULES = { "Q": "message.strip()", "Q+A": "message.strip() + abstract", "Q+O": "message.strip() + options and recommended flag",
                   "Q+P": "message.strip() + project and sender session",
                   "Q+H": "message.strip() + previous answered ask on the thread, else the sender session within two hours" }


def load_frozen_ids( path: str ) -> List[str]:
    """
    Read the frozen cohort's ask ids in file order.

    Requires:
        - path names a JSON-lines file with an id on each line

    Ensures:
        - returns the ids in the file's order

    Raises:
        - ValueError if the file holds no id or an id twice
    """
    with open( path, encoding="utf-8" ) as handle: ids = [ json.loads( line )[ "id" ] for line in handle if line.strip() ]
    if not ids: raise ValueError( f"{path} holds no ids" )
    if len( set( ids ) ) != len( ids ): raise ValueError( f"{path} holds an id twice" )
    return ids


def restamp_text_rule( path: str, rule: str ) -> None:
    """
    Name the arm's own text rule in a side file's header.

    Requires:
        - path names a side file write_side_file made

    Ensures:
        - the header's text_rule reads rule and nothing else changes
        - the file is replaced in one move
    """
    with open( path, encoding="utf-8" ) as handle: lines = handle.read().split( "\n" )
    header = json.loads( lines[ 0 ] )
    header[ "text_rule" ] = rule
    lines[ 0 ] = json.dumps( header, sort_keys=True )
    with open( path + ".part", "w", encoding="utf-8" ) as handle: handle.write( "\n".join( lines ) )
    os.replace( path + ".part", path )


def main( argv: Optional[Sequence[str]] = None, printer: Callable = print, session_factory: Optional[Callable] = None,
          provider_factory: Optional[Callable] = None, clock: Callable[[], float] = time.monotonic ) -> int:
    """
    Make one arm's side file from the command line.

    Requires:
        - argv holds --arm (one of the arm names), --frozen-ids and --out, and optionally --probe-only and --batch-size, a positive count

    Ensures:
        - the database is read in a read-only transaction and never written
        - prints the arm's counts of asks with and without its section, and the probe timing
        - with --probe-only writes nothing and returns 0
        - otherwise writes the side file, whose header names the arm, its counts, the frozen id file's sha256 and its own text rule,
          and returns 1 when any ask was rejected (the file is still written)

    Raises:
        - LookupError if a frozen ask has no notification row
        - EngineChanged and ValueError as generate raises them
    """
    parser = argparse.ArgumentParser( description="Embed one context arm's text for every frozen ask and write a side file." )
    parser.add_argument( "--arm", required=True, choices=ARMS )
    parser.add_argument( "--frozen-ids", required=True )
    parser.add_argument( "--out", required=True )
    parser.add_argument( "--probe-only", action="store_true" )
    parser.add_argument( "--batch-size", type=int, default=BATCH_SIZE, help="texts per embedding call; lower it when the model server runs out of memory" )
    args     = parser.parse_args( argv )
    ids      = load_frozen_ids( args.frozen_ids )
    provider = ( provider_factory or get_embedding_provider )()
    with ( session_factory or get_db )() as session:
        session.execute( text( "SET TRANSACTION READ ONLY" ) )
        row                  = session.execute( text( FACTS_SQL ) ).fetchall()[ 0 ]
        targets, notes_by_id = read_arm_inputs( session, [ { "id": ask_id } for ask_id in ids ] )
        session.rollback()
    pool     = list( notes_by_id.values() )
    contexts = { target[ "id" ]: rebuild_context( target, pool ) for target in targets }
    built    = build_arm_texts( args.arm, targets, contexts, notes_by_id )
    printer( f"arm {args.arm}: {built[ 'counts' ]}" )
    result   = generate( [ ( ask_id, built[ "texts" ][ ask_id ] ) for ask_id in ids ], provider, batch_size=args.batch_size, probe_only=args.probe_only, clock=clock )
    projected = result[ "probe_seconds" ] / min( PROBE_SIZE, len( ids ) ) * len( ids )
    printer( f"probe: {min( PROBE_SIZE, len( ids ) )} texts in {result[ 'probe_seconds' ]:.2f}s, projected {projected:.1f}s for {len( ids )}" )
    if args.probe_only: return 0
    facts = { "database": row[ 0 ], "db_role": row[ 1 ], "read_at": str( row[ 2 ] ), "arm": args.arm, "arm_counts": built[ "counts" ],
              "frozen_ids": len( ids ), "frozen_ids_sha256": file_sha256( args.frozen_ids ) }
    write_side_file( args.out, result, facts )
    restamp_text_rule( args.out, ARM_TEXT_RULES[ args.arm ] )
    printer( f"wrote {args.out}: {len( result[ 'vectors' ] )} vectors, {len( result[ 'rejects' ] )} rejects, model {result[ 'stamp' ][ 'model' ]}" )
    return 1 if result[ "rejects" ] else 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
