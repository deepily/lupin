"""
The question vectors of the replay cohort, made fresh and kept in a side file.

Every scored ask in the cohort gets one new vector. It is made from the question text alone, ``message.strip()``,
which is the text the live store path embeds. All vectors come from one run of one model. The embedding
service answers over HTTP. Nothing here loads a model or touches a GPU. The model server's info block
holds the model, revision, dtype and dimensions. It is read after the first 20 texts, because the server may
load lazily. It is read again after the last call. If any field moved, the run writes nothing. Each vector carries the model and revision, and the file header holds the whole
block once.

The side file is JSON lines, the contract of the backfill script: a header line, then one record per ask.
It is the only place these vectors live. The database is read, never written.

Run it from the repository root, with the config and database the vectors should describe:

    python -m cosa.research.preference_replay.question_vectors --out io/question-vectors.json --probe-only
    python -m cosa.research.preference_replay.question_vectors --out io/question-vectors.json
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text

from cosa.memory.embedding_provider import get_embedding_provider
from cosa.research.preference_replay.cohorts import scored_rows
from cosa.research.preference_replay.retune import ELIGIBLE_TYPES
from cosa.rest.db.database import get_db
from cosa.rest.db.embedding_regeneration import EMBEDDING_DIM, validate_fresh_vector
from cosa.rest.postgres_models import Notification

SIDE_FILE_VERSION = 1
PROBE_SIZE        = 20
BATCH_SIZE        = 64
STAMP_KEYS        = ( "model", "revision", "dtype", "dimensions" )
FACTS_SQL         = "select current_database(), current_user, now()"


class EngineChanged( RuntimeError ):
    """The model server's info block differed between the first read and the last."""


def cohort_texts( session, response_types: Sequence[str] = ELIGIBLE_TYPES ) -> List[Tuple[str, str]]:
    """
    List the ( ask id, question text ) pairs of the cohort, in the cohort's own order.

    Requires:
        - session is an active SQLAlchemy session; response_types are names scored_rows accepts

    Ensures:
        - returns one pair per scored ask of each type in turn, the text being the notification's message stripped
        - a stripped text may be empty; the caller decides what to do with it
    """
    pairs = []
    for kind in response_types:
        for row in scored_rows( session, kind ):
            pairs.append( ( str( row.notification_id ), session.get( Notification, row.notification_id ).message.strip() ) )
    return pairs


def engine_stamp( provider ) -> Dict[str, Any]:
    """
    Read the prose engine's model, revision, dtype and dimensions, which decide a vector.

    Requires:
        - provider is an EmbeddingProvider whose describe_engines answers over HTTP in this process

    Ensures:
        - returns a dict holding only the STAMP_KEYS, read from the prose engine's block
        - loads no model

    Raises:
        - ValueError when the prose block lacks a key, is not loaded, or has no revision
    """
    block   = provider.describe_engines()[ "prose" ]
    missing = [ key for key in STAMP_KEYS if key not in block ]
    if missing: raise ValueError( f"the prose engine block lacks {missing}" )
    if block.get( "loaded" ) is False or block[ "revision" ] is None: raise ValueError( "the prose engine is not loaded, so it has no revision to record" )
    return { key: block[ key ] for key in STAMP_KEYS }


def _embed( provider, pairs: List[Tuple[str, str]], batch_size: int ) -> List[List[float]]:
    """Embed the texts of pairs in batches, role unset, and return the vectors in input order."""
    vectors = []
    for start in range( 0, len( pairs ), batch_size ):
        texts = [ question for _, question in pairs[ start : start + batch_size ] ]
        got   = provider.generate_embeddings_batch( texts, content_type="prose" )
        if len( got ) != len( texts ): raise ValueError( f"asked for {len( texts )} vectors and got {len( got )}" )
        vectors += got
    return vectors


def generate( pairs: List[Tuple[str, str]], provider, probe_size: int = PROBE_SIZE, batch_size: int = BATCH_SIZE,
              clock: Callable[[], float] = time.monotonic, probe_only: bool = False ) -> Dict[str, Any]:
    """
    Embed the question texts, validate each vector and stamp the run with its engine.

    Requires:
        - pairs holds ( ask id, text ) with distinct ids; provider is an EmbeddingProvider
        - probe_size and batch_size are positive; clock is a seconds counter

    Ensures:
        - the first probe_size texts are embedded and timed on their own first, because the model server may load lazily
          and has no revision to report until it has answered once; with probe_only the run ends after them
        - the info block is read after the probe and again after the last call, and the run stops if the two differ,
          or if the first read shows the engine not loaded or without a revision
        - an empty text is rejected and never sent; a vector validate_fresh_vector refuses is rejected with its reason
        - returns { stamp, vectors, rejects, probe_seconds, total_seconds, texts }, vectors holding the accepted
          ones by ask id and rejects listing { id, reason } for each refused ask
        - a vector is never padded or replaced

    Raises:
        - EngineChanged when the two reads of the info block differ
        - ValueError when the service answers a different number of vectors than it was sent
    """
    ids = [ ask_id for ask_id, _ in pairs ]
    if len( set( ids ) ) != len( ids ): raise ValueError( "the ask ids are not distinct" )
    rejects      = [ { "id": ask_id, "reason": "empty question text" } for ask_id, question in pairs if question == "" ]
    sendable     = [ ( ask_id, question ) for ask_id, question in pairs if question != "" ]
    probe        = sendable[ :probe_size ]
    began        = clock()
    probe_vectors = _embed( provider, probe, batch_size )
    probe_seconds = clock() - began
    stamp_before = engine_stamp( provider )
    rest         = [] if probe_only else sendable[ probe_size: ]
    rest_vectors = _embed( provider, rest, batch_size )
    total        = clock() - began
    stamp_after  = engine_stamp( provider )
    if stamp_before != stamp_after: raise EngineChanged( f"the info block moved during the run: {stamp_before} then {stamp_after}" )
    vectors = {}
    for ( ask_id, _ ), vector in zip( probe + rest, probe_vectors + rest_vectors ):
        reason = validate_fresh_vector( vector )
        if reason is None: vectors[ ask_id ] = list( vector )
        else:              rejects.append( { "id": ask_id, "reason": reason } )
    return { "stamp": stamp_before, "vectors": vectors, "rejects": rejects, "probe_seconds": probe_seconds,
             "total_seconds": total, "texts": len( pairs ) }


def norm_band( vectors: Dict[str, List[float]] ) -> Optional[Dict[str, float]]:
    """
    Report the smallest and largest vector length.

    Requires:
        - vectors maps ask id to a list of floats

    Ensures:
        - returns { min, max } of the Euclidean norms, or None when there are no vectors
    """
    norms = [ sum( value * value for value in vector ) ** 0.5 for vector in vectors.values() ]
    return { "min": min( norms ), "max": max( norms ) } if norms else None


def write_side_file( path: str, result: Dict[str, Any], facts: Dict[str, Any] ) -> None:
    """
    Write the side file as JSON lines, in one move, so a reader never sees half of it.

    Requires:
        - result is what generate returns for a full run; facts names the database and read time
        - the directory of path exists

    Ensures:
        - line 1 is the header: kind, model, revision, count and engines (the stamp), plus the run's own facts
        - each later line is one record: id, model, revision and vector, in ask-id order
        - the data goes to a temporary name beside path and replaces path only when complete
    """
    stamp  = result[ "stamp" ]
    header = { "kind": "header", "model": stamp[ "model" ], "revision": stamp[ "revision" ], "count": len( result[ "vectors" ] ),
               "engines": stamp, "version": SIDE_FILE_VERSION, "texts": result[ "texts" ], "rejects": result[ "rejects" ],
               "norm_band": norm_band( result[ "vectors" ] ), "probe_seconds": result[ "probe_seconds" ],
               "total_seconds": result[ "total_seconds" ], "facts": facts, "text_rule": "message.strip()", "dimensions": EMBEDDING_DIM }
    scratch = path + ".part"
    with open( scratch, "w", encoding="utf-8" ) as handle:
        handle.write( json.dumps( header, sort_keys=True ) + "\n" )
        for ask_id in sorted( result[ "vectors" ] ):
            record = { "id": ask_id, "model": stamp[ "model" ], "revision": stamp[ "revision" ], "vector": result[ "vectors" ][ ask_id ] }
            handle.write( json.dumps( record, sort_keys=True ) + "\n" )
    os.replace( scratch, path )


def load_side_file( path: str ) -> Tuple[Dict[str, Any], Dict[str, List[float]]]:
    """
    Read a side file back as its header and a vector for each ask id.

    Requires:
        - path names a JSON-lines file write_side_file made

    Ensures:
        - returns ( header, vectors ), vectors mapping ask id to its list of floats

    Raises:
        - ValueError when the first line is not a header, the version is not SIDE_FILE_VERSION, the count differs
          from the header's, an id repeats, or a record's model or revision differs from the header's
    """
    with open( path, encoding="utf-8" ) as handle: lines = [ line for line in handle.read().splitlines() if line.strip() ]
    if not lines: raise ValueError( "the side file is empty" )
    header = json.loads( lines[ 0 ] )
    if header.get( "kind" ) != "header": raise ValueError( "the first line is not a header" )
    if header[ "version" ] != SIDE_FILE_VERSION: raise ValueError( f"side file version {header[ 'version' ]} is not {SIDE_FILE_VERSION}" )
    records = [ json.loads( line ) for line in lines[ 1: ] ]
    if len( records ) != header[ "count" ]: raise ValueError( f"the header says {header[ 'count' ]} vectors and the file holds {len( records )}" )
    vectors = {}
    for record in records:
        if ( record[ "model" ], record[ "revision" ] ) != ( header[ "model" ], header[ "revision" ] ):
            raise ValueError( f"the vector of {record[ 'id' ]} names a different model or revision than the header" )
        if record[ "id" ] in vectors: raise ValueError( f"the id {record[ 'id' ]} appears twice" )
        vectors[ record[ "id" ] ] = record[ "vector" ]
    return header, vectors


def main( argv: Optional[Sequence[str]] = None, printer: Callable = print, session_factory: Optional[Callable] = None,
          provider_factory: Optional[Callable] = None, clock: Callable[[], float] = time.monotonic ) -> int:
    """
    Make the side file from the command line.

    Requires:
        - argv holds --out, and optionally --probe-only; the factories default to the real database and provider

    Ensures:
        - the database is read in a read-only transaction and never written
        - prints the probe's seconds and the projected seconds for the whole cohort
        - with --probe-only writes nothing and returns 0
        - otherwise writes the side file, prints the counts and returns 0, or returns 1 when any ask was rejected
          (the file is still written, so the rejects can be read)

    Raises:
        - EngineChanged and ValueError as generate raises them
    """
    parser = argparse.ArgumentParser( description="Embed every cohort question and write the vectors to a side file." )
    parser.add_argument( "--out", required=True )
    parser.add_argument( "--probe-only", action="store_true" )
    args     = parser.parse_args( argv )
    provider = ( provider_factory or get_embedding_provider )()
    with ( session_factory or get_db )() as session:
        session.execute( text( "SET TRANSACTION READ ONLY" ) )
        row   = session.execute( text( FACTS_SQL ) ).fetchall()[ 0 ]
        facts = { "database": row[ 0 ], "db_role": row[ 1 ], "read_at": str( row[ 2 ] ) }
        pairs = cohort_texts( session )
        session.rollback()
    result    = generate( pairs, provider, probe_only=args.probe_only, clock=clock )
    projected = result[ "probe_seconds" ] / min( PROBE_SIZE, max( 1, len( pairs ) ) ) * len( pairs )
    printer( f"probe: {min( PROBE_SIZE, len( pairs ) )} texts in {result[ 'probe_seconds' ]:.2f}s, projected {projected:.1f}s for {len( pairs )}" )
    if args.probe_only: return 0
    write_side_file( args.out, result, facts )
    printer( f"wrote {args.out}: {len( result[ 'vectors' ] )} vectors, {len( result[ 'rejects' ] )} rejects, model {result[ 'stamp' ][ 'model' ]}" )
    return 1 if result[ "rejects" ] else 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
