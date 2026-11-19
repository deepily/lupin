#!/usr/bin/env python3
r"""
Backfill every ask's question vector into `prediction_decisions` from the side file.

Dry run by default. It reads the database inside a read-only transaction and prints counts only.
The real run is the same file with `--apply`, which needs the three `--expect-*` counts as well.

What it does, in one transaction:
    1. Asserts the ids it will insert still have no row, and the ids it will update still have one.
    2. Inserts a case row for each ask in the side file that has none.
    3. Replaces the stored vector of each ask that already has a row.
    4. Sets `prediction_log.encoder_version` on every ask to `<model>@<revision>` from the file header.
    5. Reads the result back and rolls the whole transaction back if any count is off.

Side file contract (JSON lines, UTF-8):
    Line 1 is the header: `{"kind": "header", "model": ..., "revision": ..., "count": N, "engines": {...}}`.
    Every later line is a record: `{"id": <notification id>, "model": ..., "revision": ..., "vector": [768 floats]}`.
    A record's model and revision must equal the header's. Ids are unique and the count must match.

Field rules for a new row:
    - question is the notification message, stripped; it is what the live store path embeds.
    - category and response_type come from the prediction log row.
    - decision_value is the logged answer: the value for yes/no, sorted JSON text for multiple choice.
    - owner_user_id is the notification recipient.
    - answer_source is human when the notification answer source is `ui`, otherwise unknown.
    - ratification_state is not_required, data_origin is organic.
    - created_at is the time the notification was answered, in UTC, as text.

Usage:
    python src/scripts/backfill_missing_question_vectors.py --side-file <path> --database-url <url>
    python src/scripts/backfill_missing_question_vectors.py --side-file <path> --database-url <url> \\
        --apply --expect-insert 2306 --expect-update 1304 --expect-log 3610

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
from typing import Any, Dict, List, Optional, Tuple

try:
    import sqlalchemy as sa
    from cosa.rest.db.embedding_regeneration import validate_fresh_vector
except ImportError as err:  # pragma: no cover -- run by a subprocess test, which coverage does not follow
    print( f"FATAL: import failed ({err!r}). Run with the repo's interpreter and PYTHONPATH=<tree>/src.", file=sys.stderr )
    sys.exit( 4 )

CHUNK              = 400
HUMAN_SOURCE       = "ui"
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

    Raises:
        - RefusedPlan on a missing header, a count mismatch, a duplicate id, a model or revision
          that differs from the header, or a vector that fails validation
    """
    with open( path, encoding="utf-8" ) as handle:
        lines = [ line for line in handle.read().splitlines() if line.strip() ]
    if not lines: raise RefusedPlan( "side file is empty" )
    header = json.loads( lines[ 0 ] )
    if header.get( "kind" ) != "header": raise RefusedPlan( "first line is not a header" )
    if not header.get( "model" ) or not header.get( "revision" ): raise RefusedPlan( "header lacks model or revision" )
    records = [ json.loads( line ) for line in lines[ 1: ] ]
    if header.get( "count" ) != len( records ): raise RefusedPlan( f"header count {header.get( 'count' )} but {len( records )} records" )
    seen = set()
    for record in records:
        if record[ "id" ] in seen: raise RefusedPlan( f"duplicate id {record[ 'id' ]}" )
        seen.add( record[ "id" ] )
        if record.get( "model" ) != header[ "model" ] or record.get( "revision" ) != header[ "revision" ]:
            raise RefusedPlan( f"record {record[ 'id' ]} names a different model or revision than the header" )
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


def answer_source_of( response_value: Any ) -> str:
    """
    Label an answer human when the notification says it came from the UI, otherwise unknown.

    Requires:
        - response_value is a dict, a JSON string, or None

    Ensures:
        - returns human only when the source field equals ui
    """
    if isinstance( response_value, str ): response_value = json.loads( response_value )
    if isinstance( response_value, dict ) and response_value.get( "source" ) == HUMAN_SOURCE: return "human"
    return "unknown"


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
        - returns a dict keyed by id with message, recipient_id, responded_at, response_value,
          category, response_type and actual_value
        - an id with no notification or no log row is absent from the dict
    """
    sql = ( "SELECT CAST( n.id AS TEXT ) AS id, n.message, CAST( n.recipient_id AS TEXT ) AS recipient_id, n.responded_at, "
            "n.response_value, l.category, l.response_type, l.actual_value "
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
        - RefusedPlan if an id has no notification and log row, no recipient, or an empty message
    """
    ids      = [ record[ "id" ] for record in records ]
    asks     = fetch_asks( conn, ids )
    existing = fetch_existing( conn, ids )
    missing  = [ row_id for row_id in ids if row_id not in asks ]
    if missing: raise RefusedPlan( f"{len( missing )} ids have no notification and log row, first {missing[ 0 ]}" )
    plan = Plan( encoder_version=encoder_version_of( header ), log_ids=ids )
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
            "answer_source"      : answer_source_of( ask[ "response_value" ] ),
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


def apply_plan( conn, plan: Plan, expect_insert: int, expect_update: int, expect_log: int ) -> Dict[ str, int ]:
    """
    Write the plan inside the caller's open transaction and read it back.

    Requires:
        - conn has an open transaction the caller commits or rolls back
        - the three expect values are the counts the operator was told to expect

    Ensures:
        - the first statement counts the insert ids and the update ids that already have a row
        - returns the read-back counts after all writes

    Raises:
        - CountMismatch before any write if the plan sizes or the pre-write counts differ from the expectations
        - CountMismatch after the writes if the read-back counts differ from the plan
    """
    insert_ids = [ row[ "id" ] for row in plan.inserts ]
    update_ids = [ row[ "id" ] for row in plan.updates ]
    already    = sum( conn.execute( _in_clause( "SELECT count(*) FROM prediction_decisions WHERE id IN :ids" ), { "ids": part } ).scalar() for part in _chunks( insert_ids ) )
    present    = sum( conn.execute( _in_clause( "SELECT count(*) FROM prediction_decisions WHERE id IN :ids" ), { "ids": part } ).scalar() for part in _chunks( update_ids ) )
    if already:                                raise CountMismatch( f"{already} of the {len( insert_ids )} insert ids already have a row" )
    if present != len( update_ids ):           raise CountMismatch( f"only {present} of the {len( update_ids )} update ids have a row" )
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


def run( engine, side_file: str, apply: bool, expect_insert: int, expect_update: int, expect_log: int, out=print ) -> int:
    """
    Run the dry run or the apply against an engine and return the exit code.

    Requires:
        - engine is a SQLAlchemy engine; side_file is a path

    Ensures:
        - a dry run writes nothing and prints counts only; on Postgres it sets the transaction read only
        - an apply commits only when every check and the read-back pass, otherwise it rolls back
        - returns 0 on success, 2 when the plan is refused, 3 on a count mismatch

    Raises:
        - nothing for the refusals above; other exceptions propagate after a rollback
    """
    try:
        header, records = read_side_file( side_file )
    except ( RefusedPlan, KeyError, ValueError ) as err:
        out( f"REFUSED: {err}" )
        return 2
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            if not apply and conn.dialect.name == "postgresql": conn.execute( sa.text( "SET TRANSACTION READ ONLY" ) )
            plan = build_plan( conn, header, records )
            out( format_counts( plan ) )
            if not apply:
                transaction.rollback()
                out( "dry run: nothing written" )
                return 0
            counts = apply_plan( conn, plan, expect_insert, expect_update, expect_log )
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
    parser.add_argument( "--apply",         action="store_true" )
    parser.add_argument( "--expect-insert", type=int )
    parser.add_argument( "--expect-update", type=int )
    parser.add_argument( "--expect-log",    type=int )
    args = parser.parse_args( argv )
    if args.apply and None in ( args.expect_insert, args.expect_update, args.expect_log ):
        parser.error( "--apply needs --expect-insert, --expect-update and --expect-log" )
    engine = sa.create_engine( args.database_url )
    return run( engine, args.side_file, args.apply, args.expect_insert, args.expect_update, args.expect_log )


if __name__ == "__main__":
    sys.exit( main() )
