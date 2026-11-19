#!/usr/bin/env python3
r"""
Backfill every ask's question vector into `prediction_decisions` from the side file.

Dry run by default. It reads the database inside a read-only transaction and prints counts only.
`--rehearse` runs every apply step and the read-back, then rolls back. The real run is the same file with `--apply`.
Both need the three `--expect-*` counts, `--expect-insert-ids`, `--frozen-ids` and `--expect-database`.
The insert file lists the asks to insert. The frozen file lists every ask the run may touch.
The database name must match the connection.

What it does, in one transaction:
    1. Asserts the insert ids match the expected list and have no row, and the update ids have one.
    2. Inserts a case row for each ask in the side file that has none.
    3. Replaces the stored vector of each ask that already has a row.
    4. Sets `prediction_log.encoder_version` on every ask to `<model>@<revision>` from the file header.
    5. Reads the result back and rolls the whole transaction back if any count is off.

Side file contract (JSON lines, UTF-8):
    Line 1 is the header: `{"kind": "header", "model": ..., "revision": ..., "count": N, "engines": {...}}`.
    Every later line is a record: `{"id": <notification id>, "model": ..., "revision": ..., "vector": [768 floats]}`.
    A record's model and revision must equal the header's. Ids are unique and the count must match.

Fields of a new row:
    - question is the notification message, stripped; it is what the live store path embeds.
    - category and response_type come from the prediction log row.
    - decision_value is the logged answer: the value for yes/no, sorted JSON text for multiple choice.
    - owner_user_id is the notification recipient.
    - answer_source is human when the notification answer source is `ui`, otherwise unknown.
    - ratification_state is not_required, data_origin is organic.
    - created_at is the time the notification was answered, in UTC, as text.

Usage:
    python src/scripts/backfill_missing_question_vectors.py --side-file <path> --database-url <url> [--apply | --rehearse] [expect flags]

Exit codes:
    0 means the dry run printed its counts, or the apply committed and read back clean.
    2 means the side file or the database plan is not usable. Nothing was written.
    3 means an expected count did not match, or the read-back failed. The transaction was rolled back.
    4 means a required import failed: wrong interpreter or PYTHONPATH.

Design: src/docs/wiki/capabilities/rest-data-embedding-regeneration.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import timezone
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import sqlalchemy as sa
    from cosa.research.preference_replay.cohorts import answer_source_of
    from cosa.research.preference_replay.question_vectors import read_side_records
    from cosa.rest.db.embedding_regeneration import validate_fresh_vector
except ImportError as err:  # pragma: no cover -- run by a subprocess test, which coverage does not follow
    print( f"FATAL: import failed ({err!r}). Run with the repo's interpreter and PYTHONPATH=<tree>/src.", file=sys.stderr )
    sys.exit( 4 )

CHUNK              = 400
ENCODER_VERSION_MAX = 100   # the width of prediction_log.encoder_version
RATIFICATION_STATE = "not_required"
DATA_ORIGIN        = "organic"


class RefusedPlan( Exception ):
    """The side file or the database does not support a safe plan; nothing was written."""



class CountMismatch( Exception ):
    """An expected count or a read-back count is off; the transaction must roll back."""



@dataclass
class Plan:
    """What an apply would write, built from the side file and the database."""

    encoder_version : str
    inserts         : List[ Dict[ str, Any ] ] = field( default_factory=list )
    updates         : List[ Dict[ str, Any ] ] = field( default_factory=list )
    log_ids         : List[ str ]              = field( default_factory=list )
    log_rows        : int                      = 0
    question_drift  : int                      = 0

    def ids( self ) -> List[ str ]:
        """
        List every id the plan touches, inserts first.

        Ensures:
            - returns the insert ids followed by the update ids
        """
        return [ row[ "id" ] for row in self.inserts ] + [ row[ "id" ] for row in self.updates ]


def read_side_file( path: str ) -> Tuple[ Dict[ str, Any ], List[ Dict[ str, Any ] ] ]:
    """
    Read and validate the side file.

    Requires:
        - path names a readable UTF-8 JSON-lines file

    Ensures:
        - returns the header and the records, each record carrying the header's model and revision
        - every vector passes validate_fresh_vector, and every id is unique
        - the header's version is not checked here

    Raises:
        - RefusedPlan on a missing header, a count mismatch, a duplicate id, a model or revision
          that differs from the header, or a vector that fails validation
    """
    header, records = read_side_records( path, refuse=RefusedPlan, expected_version=None )
    for record in records:
        reason = validate_fresh_vector( record.get( "vector" ) )
        if reason is not None: raise RefusedPlan( f"record {record[ 'id' ]}: {reason}" )
    return header, records


def encoder_version_of( header: Dict[ str, Any ] ) -> str:
    """
    Name the encoder as the log column stores it.

    Requires:
        - header carries model and revision

    Ensures:
        - returns `<model>@<revision>`
    """
    return f"{header[ 'model' ]}@{header[ 'revision' ]}"


def decision_value_of( actual_value: Any ) -> str:
    """
    Turn a logged answer into the decision_value text the case store holds.

    Requires:
        - actual_value is a dict or a JSON string

    Ensures:
        - returns the value field when present, otherwise sorted JSON text of the whole answer
    """
    if isinstance( actual_value, str ): actual_value = json.loads( actual_value )
    if "value" in actual_value: return actual_value[ "value" ]
    return json.dumps( actual_value, sort_keys=True )


def vector_text( vector: List[ float ] ) -> str:
    """
    Render a vector in pgvector's text form.

    Requires:
        - vector is a list of finite floats

    Ensures:
        - returns `[a,b,...]` with each float in its shortest round-trip form
    """
    return "[" + ",".join( repr( float( value ) ) for value in vector ) + "]"


def _chunks( items: List[ str ] ):
    """Yield the items in slices of the chunk size."""
    for start in range( 0, len( items ), CHUNK ): yield items[ start:start + CHUNK ]


def _in_clause( sql: str ) -> Any:
    """Bind an expanding list named ids to the statement."""
    return sa.text( sql ).bindparams( sa.bindparam( "ids", expanding=True ) )


def fetch_asks( conn, ids: List[ str ] ) -> Dict[ str, Dict[ str, Any ] ]:
    """
    Read the ask behind each id from the notification and its prediction log row.

    Requires:
        - conn is an open connection to a database holding notifications and prediction_log

    Ensures:
        - returns a dict keyed by id with message, recipient_id, responded_at, response_value, response_options,
          category, response_type and actual_value
        - an id with no notification or no log row is absent from the dict
    """
    sql = ( "SELECT CAST( n.id AS TEXT ) AS id, n.message, CAST( n.recipient_id AS TEXT ) AS recipient_id, n.responded_at, "
            "n.response_value, n.response_options, l.category, l.response_type, l.actual_value "
            "FROM notifications n JOIN prediction_log l ON CAST( l.notification_id AS TEXT ) = CAST( n.id AS TEXT ) "
            "WHERE CAST( n.id AS TEXT ) IN :ids" )
    asks = {}
    for part in _chunks( ids ):
        for row in conn.execute( _in_clause( sql ), { "ids": part } ).mappings():
            asks[ row[ "id" ] ] = dict( row )
    return asks


def fetch_existing( conn, ids: List[ str ] ) -> Dict[ str, Optional[ str ] ]:
    """
    Read the stored question of each id that already has a case row.

    Requires:
        - conn is an open connection to a database holding prediction_decisions

    Ensures:
        - returns a dict from id to stored question, holding only ids that have a row
    """
    existing = {}
    for part in _chunks( ids ):
        rows = conn.execute( _in_clause( "SELECT id, question FROM prediction_decisions WHERE id IN :ids" ), { "ids": part } )
        for row_id, question in rows: existing[ row_id ] = question
    return existing


def _responded_text( responded_at: Any ) -> str:
    """Render the answer time in UTC as text, the form the live path stores."""
    if isinstance( responded_at, str ): return responded_at
    return responded_at.astimezone( timezone.utc ).isoformat()


def build_plan( conn, header: Dict[ str, Any ], records: List[ Dict[ str, Any ] ] ) -> Plan:
    """
    Decide which side-file asks are inserted and which are updated.

    Requires:
        - conn is an open connection; header and records come from read_side_file

    Ensures:
        - returns a Plan whose inserts are the asks with no case row and whose updates are the asks with one
        - every insert carries the fields listed in the module docstring and the vector text
        - question_drift counts the existing rows whose stored question differs from the stripped message
        - log_rows counts the prediction_log rows the encoder version will be written to

    Raises:
        - RefusedPlan if an id has no notification and log row, no recipient, an empty message, or an encoder version wider than its column
    """
    ids      = [ record[ "id" ] for record in records ]
    asks     = fetch_asks( conn, ids )
    existing = fetch_existing( conn, ids )
    missing  = [ row_id for row_id in ids if row_id not in asks ]
    if missing: raise RefusedPlan( f"{len( missing )} ids have no notification and log row, first {missing[ 0 ]}" )
    plan = Plan( encoder_version=encoder_version_of( header ), log_ids=ids )
    if len( plan.encoder_version ) > ENCODER_VERSION_MAX: raise RefusedPlan( f"encoder version is {len( plan.encoder_version )} characters, the column holds {ENCODER_VERSION_MAX}" )
    for record in records:
        ask  = asks[ record[ "id" ] ]
        text = ask[ "message" ].strip()
        if not text:                  raise RefusedPlan( f"{record[ 'id' ]} has an empty message" )
        if not ask[ "recipient_id" ]: raise RefusedPlan( f"{record[ 'id' ]} has no recipient" )
        vector = vector_text( record[ "vector" ] )
        if record[ "id" ] in existing:
            if existing[ record[ "id" ] ] != text: plan.question_drift += 1
            plan.updates.append( { "id": record[ "id" ], "vector": vector } )
            continue
        plan.inserts.append( {
            "id"                 : record[ "id" ],
            "question"           : text,
            "category"           : ask[ "category" ],
            "decision_value"     : decision_value_of( ask[ "actual_value" ] ),
            "ratification_state" : RATIFICATION_STATE,
            "data_origin"        : DATA_ORIGIN,
            "response_type"      : ask[ "response_type" ],
            "vector"             : vector,
            "created_at"         : _responded_text( ask[ "responded_at" ] ),
            "owner_user_id"      : ask[ "recipient_id" ],
            "answer_source"      : answer_source_of( ask[ "response_value" ], ask[ "response_options" ] ),
        } )
    plan.log_rows = _count_log_rows( conn, ids )
    return plan


def _count_log_rows( conn, ids: List[ str ] ) -> int:
    """Count the prediction_log rows that belong to the ids."""
    total = 0
    for part in _chunks( ids ):
        total += conn.execute( _in_clause( "SELECT count(*) FROM prediction_log WHERE CAST( notification_id AS TEXT ) IN :ids" ), { "ids": part } ).scalar()
    return total


def format_counts( plan: Plan ) -> str:
    """
    Summarise a plan as counts only.

    Requires:
        - plan comes from build_plan

    Ensures:
        - returns lines with the insert, update, log and drift counts and the insert split by answer source
    """
    split = {}
    for row in plan.inserts: split[ row[ "answer_source" ] ] = split.get( row[ "answer_source" ], 0 ) + 1
    lines = [ f"encoder_version    : {plan.encoder_version}",
              f"rows to insert     : {len( plan.inserts )}",
              f"  by answer_source : {json.dumps( split, sort_keys=True )}",
              f"vectors to replace : {len( plan.updates )}",
              f"log rows to stamp  : {plan.log_rows}",
              f"stored questions that differ from the stripped message : {plan.question_drift}" ]
    return "\n".join( lines )


def _vector_sql( conn, name: str ) -> str:
    """Return the SQL fragment that binds the named vector parameter."""
    return f"CAST( :{name} AS vector )" if conn.dialect.name == "postgresql" else f":{name}"


def apply_plan( conn, plan: Plan, expect_insert: int, expect_update: int, expect_log: int,
                expect_insert_ids: Optional[ Set[ str ] ] = None ) -> Dict[ str, int ]:
    """
    Write the plan inside the caller's open transaction and read it back.

    Requires:
        - conn has an open transaction the caller commits or rolls back
        - the three expect values are the counts the operator was told to expect
        - expect_insert_ids is the exact set of ids the operator expects to insert, from a source other than this plan

    Ensures:
        - the plan's insert ids equal expect_insert_ids exactly, and no insert id has a row, before any write
        - returns the read-back counts after all writes

    Raises:
        - CountMismatch before any write if the plan sizes or the pre-write counts differ from the expectations
        - CountMismatch after the writes if the read-back counts differ from the plan
    """
    insert_ids = [ row[ "id" ] for row in plan.inserts ]
    update_ids = [ row[ "id" ] for row in plan.updates ]
    if expect_insert_ids is None:              raise CountMismatch( "no expected insert id list was given" )
    extra      = sorted( set( insert_ids ) - expect_insert_ids )
    short      = sorted( expect_insert_ids - set( insert_ids ) )
    if extra or short:                         raise CountMismatch( f"insert ids differ from the expected list: {len( extra )} extra (first {extra[ :1 ]}), {len( short )} missing (first {short[ :1 ]})" )
    have_row   = set( fetch_existing( conn, insert_ids + update_ids ) )
    already    = sorted( have_row & set( insert_ids ) )
    absent     = sorted( set( update_ids ) - have_row )
    if already:                                raise CountMismatch( f"{len( already )} of the {len( insert_ids )} insert ids already have a row, first {already[ 0 ]}" )
    if absent:                                 raise CountMismatch( f"{len( absent )} of the {len( update_ids )} update ids have no row, first {absent[ 0 ]}" )
    if len( insert_ids ) != expect_insert:     raise CountMismatch( f"plan inserts {len( insert_ids )}, expected {expect_insert}" )
    if len( update_ids ) != expect_update:     raise CountMismatch( f"plan updates {len( update_ids )}, expected {expect_update}" )
    if plan.log_rows != expect_log:            raise CountMismatch( f"plan stamps {plan.log_rows} log rows, expected {expect_log}" )

    insert_sql = sa.text( "INSERT INTO prediction_decisions ( id, question, category, decision_value, ratification_state, data_origin, "
                          "response_type, question_embedding, created_at, owner_user_id, answer_source ) VALUES ( :id, :question, :category, "
                          f":decision_value, :ratification_state, :data_origin, :response_type, {_vector_sql( conn, 'vector' )}, :created_at, "
                          ":owner_user_id, :answer_source )" )
    update_sql = sa.text( f"UPDATE prediction_decisions SET question_embedding = {_vector_sql( conn, 'vector' )} WHERE id = :id" )
    stamp_sql  = sa.text( "UPDATE prediction_log SET encoder_version = :version WHERE CAST( notification_id AS TEXT ) = :id" )
    if plan.inserts: conn.execute( insert_sql, plan.inserts )
    if plan.updates: conn.execute( update_sql, plan.updates )
    conn.execute( stamp_sql, [ { "version": plan.encoder_version, "id": row_id } for row_id in plan.log_ids ] )
    return read_back( conn, plan, expect_insert + expect_update )


def read_back( conn, plan: Plan, expect_rows: int ) -> Dict[ str, int ]:
    """
    Count what the writes left behind and compare it with the plan.

    Requires:
        - conn is inside the transaction that wrote the plan

    Ensures:
        - returns the counts of case rows, rows with a vector, human-labelled inserts and stamped log rows

    Raises:
        - CountMismatch if a count differs from the plan
    """
    ids    = plan.ids()
    counts = { "rows": 0, "with_vector": 0, "inserted_human": 0, "stamped": 0 }
    insert_ids = [ row[ "id" ] for row in plan.inserts ]
    for part in _chunks( ids ):
        counts[ "rows" ]        += conn.execute( _in_clause( "SELECT count(*) FROM prediction_decisions WHERE id IN :ids" ), { "ids": part } ).scalar()
        counts[ "with_vector" ] += conn.execute( _in_clause( "SELECT count(*) FROM prediction_decisions WHERE id IN :ids AND question_embedding IS NOT NULL" ), { "ids": part } ).scalar()
    for part in _chunks( insert_ids ):
        counts[ "inserted_human" ] += conn.execute( _in_clause( "SELECT count(*) FROM prediction_decisions WHERE id IN :ids AND answer_source = 'human'" ), { "ids": part } ).scalar()
    for part in _chunks( plan.log_ids ):
        counts[ "stamped" ] += conn.execute( _in_clause( "SELECT count(*) FROM prediction_log WHERE CAST( notification_id AS TEXT ) IN :ids AND encoder_version = :version" ).bindparams( version=plan.encoder_version ), { "ids": part } ).scalar()
    want_human = sum( 1 for row in plan.inserts if row[ "answer_source" ] == "human" )
    wanted     = { "rows": expect_rows, "with_vector": expect_rows, "inserted_human": want_human, "stamped": plan.log_rows }
    if counts != wanted: raise CountMismatch( f"read-back {counts} differs from plan {wanted}" )
    return counts


def database_name( conn ) -> str:
    """
    Name the database the connection is really on.

    Requires:
        - conn is an open connection

    Ensures:
        - on Postgres returns current_database(); elsewhere returns the database part of the URL, or :memory:
    """
    if conn.dialect.name == "postgresql": return conn.execute( sa.text( "SELECT current_database()" ) ).scalar()
    return conn.engine.url.database or ":memory:"


def run( engine, side_file: str, apply: bool, expect_insert: int, expect_update: int, expect_log: int,
         out=print, rehearse: bool = False, expect_database: Optional[ str ] = None,
         expect_insert_ids: Optional[ Set[ str ] ] = None, frozen_ids: Optional[ Set[ str ] ] = None ) -> int:
    """
    Run the dry run, the rehearsal or the apply against an engine and return the exit code.

    Requires:
        - engine is a SQLAlchemy engine; side_file is a path
        - a rehearsal or an apply carries expect_database, the database name the operator intends
        - a rehearsal or an apply carries expect_insert_ids, the exact ids to insert
        - a rehearsal or an apply carries frozen_ids, the closed set of ask ids the run may touch

    Ensures:
        - the output names the database the connection is on
        - a dry run writes nothing and prints counts only; on Postgres it sets the transaction read only
        - a rehearsal runs every apply step and read-back, then rolls back, so nothing persists
        - an apply commits only when every check and the read-back pass, otherwise it rolls back
        - a rehearsal or apply on a database other than expect_database writes nothing and returns 2
        - a side file holding an id outside frozen_ids is refused before the database is opened
        - returns 0 on success, 2 when the plan is refused, 3 on a count mismatch

    Raises:
        - nothing for the refusals above; other exceptions propagate after a rollback
    """
    try:
        header, records = read_side_file( side_file )
    except ( RefusedPlan, KeyError, ValueError ) as err:
        out( f"REFUSED: {err}" )
        return 2
    if ( apply or rehearse ) and frozen_ids is None:
        out( "REFUSED: a rehearsal or apply needs the frozen id list" )
        return 2
    outside = sorted( record[ "id" ] for record in records if frozen_ids is not None and record[ "id" ] not in frozen_ids )
    if outside:
        out( f"REFUSED: {len( outside )} side-file ids are outside the frozen list, first {outside[ 0 ]}" )
        return 2
    writing = apply or rehearse
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            name = database_name( conn )
            out( f"database           : {name}" )
            if writing and name != expect_database: raise RefusedPlan( f"connected to {name!r}, expected {expect_database!r}" )
            if not writing and conn.dialect.name == "postgresql": conn.execute( sa.text( "SET TRANSACTION READ ONLY" ) )
            plan = build_plan( conn, header, records )
            out( format_counts( plan ) )
            if not writing:
                transaction.rollback()
                out( "dry run: nothing written" )
                return 0
            counts = apply_plan( conn, plan, expect_insert, expect_update, expect_log, expect_insert_ids )
            if rehearse:
                transaction.rollback()
                out( f"rehearsal read back, then rolled back: {json.dumps( counts, sort_keys=True )}" )
                return 0
            transaction.commit()
            out( f"applied and read back: {json.dumps( counts, sort_keys=True )}" )
            return 0
        except RefusedPlan as err:
            transaction.rollback()
            out( f"REFUSED: {err}" )
            return 2
        except CountMismatch as err:
            transaction.rollback()
            out( f"ROLLED BACK: {err}" )
            return 3


def _read_id_file( path: Optional[ str ] ) -> Optional[ Set[ str ] ]:
    """
    Read a file of ids, one per line.

    Requires:
        - path is None or a readable UTF-8 file

    Ensures:
        - returns None for None, otherwise the set of non-blank stripped lines
    """
    if path is None: return None
    with open( path, encoding="utf-8" ) as handle: return { line.strip() for line in handle if line.strip() }


def main( argv: Optional[ List[ str ] ] = None ) -> int:
    """
    Parse the command line and run.

    Requires:
        - argv is a list of arguments or None for sys.argv

    Ensures:
        - an apply without all three expect counts exits with a usage error before touching the database
        - returns the exit code of run
    """
    parser = argparse.ArgumentParser( description="Backfill question vectors into prediction_decisions from the side file." )
    parser.add_argument( "--side-file",     required=True )
    parser.add_argument( "--database-url",  required=True )
    parser.add_argument( "--apply",           action="store_true" )
    parser.add_argument( "--rehearse",        action="store_true" )
    parser.add_argument( "--expect-database" )
    parser.add_argument( "--frozen-ids", help="a file with one id per line: the closed set of asks the run may touch" )
    parser.add_argument( "--expect-insert-ids", help="a file with one id per line: exactly the asks that have no row today" )
    parser.add_argument( "--expect-insert", type=int )
    parser.add_argument( "--expect-update", type=int )
    parser.add_argument( "--expect-log",    type=int )
    args = parser.parse_args( argv )
    if args.apply and args.rehearse: parser.error( "--apply and --rehearse are exclusive" )
    if ( args.apply or args.rehearse ) and None in ( args.expect_insert, args.expect_update, args.expect_log, args.expect_database, args.expect_insert_ids, args.frozen_ids ):
        parser.error( "--apply and --rehearse need --expect-insert, --expect-update, --expect-log, --expect-database, --expect-insert-ids and --frozen-ids" )
    expected_ids = _read_id_file( args.expect_insert_ids )
    frozen_ids   = _read_id_file( args.frozen_ids )
    engine = sa.create_engine( args.database_url )
    return run( engine, args.side_file, args.apply, args.expect_insert, args.expect_update, args.expect_log,
                rehearse=args.rehearse, expect_database=args.expect_database, expect_insert_ids=expected_ids, frozen_ids=frozen_ids )


if __name__ == "__main__":
    sys.exit( main() )
