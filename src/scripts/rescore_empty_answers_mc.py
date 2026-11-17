#!/usr/bin/env python3
"""
Rescore the old multiple-choice rows that were left unscored with reason `empty_answers`.

One-off, by Rick's ruling of 6 Nov and Rio's design. Report only by default.
It writes nothing unless you pass `--write`.

Why this exists:
    Before commit 6c41a7346 the router stored a multiple-choice answer as {"value": "<json string>"}.
    The comparators looked for an "answers" key, found none, and recorded accuracy_match NULL with
    accuracy_detail.reason "empty_answers". New rows score. These old rows never did.

What it does to each multiple_choice row whose accuracy_detail.reason is "empty_answers":
    - decodes actual_value["value"] with PredictionEngine._parse_mc_decision_value, the same
      decoder record_outcome uses
    - reruns get_comparator against the stored predicted_value
    - with --write, sets actual_value to the decoded dict, plus accuracy_match and accuracy_detail
    - never touches responded_at, which is when the user answered
    - with --write, first dumps every row it will change to a JSON-lines file and flushes it to disk
    - the dump holds id, notification_id, old actual_value, old accuracy_match and old accuracy_detail
    - it does this because the write cannot be undone from the database, and it writes nothing if the dump fails

Rows it skips, each counted under its own reason:
    - not_json_answers: actual_value holds no JSON with an "answers" mapping, such as a bare label
    - no_prediction: predicted_value is empty, so there is nothing to compare
    - comparator_unscored: the comparator still answered match None, as for a cancelled card
The 60 open_ended_batch rows are out of scope (Rick's ruling) and are never selected.

Usage:
    PYTHONPATH=src python src/scripts/rescore_empty_answers_mc.py             # report only
    PYTHONPATH=src python src/scripts/rescore_empty_answers_mc.py --write     # dump, then rescore
    ... --write --dump-path /some/file.jsonl                                  # choose the dump file

Exit codes:
    0  ran; read the counts
    3  a required import failed: wrong interpreter or PYTHONPATH
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

try:
    from cosa.agents.prediction_engine.accuracy_comparators import get_comparator
    from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
    from cosa.rest.postgres_models import PredictionLog
    import cosa.utils.util as cu
except ImportError as err:
    print( f"FATAL: import failed ({err!r}). Run with the repo's interpreter and PYTHONPATH=<tree>/src.", file=sys.stderr )
    sys.exit( 3 )

RESPONSE_TYPE   = "multiple_choice"
UNSCORED_REASON = "empty_answers"
COMMIT_EVERY    = 200


def classify( actual_value, predicted_value ):
    """
    Decide what rescoring one row would do.

    Requires:
        - actual_value and predicted_value are the row's stored JSONB values, any type

    Ensures:
        - returns ( "would_score", decoded_actual, match, detail ) when the comparator scores the decoded answer
        - returns ( "skipped", reason, None, None ) otherwise, with reason one of not_json_answers,
          no_prediction or comparator_unscored
        - never raises on a malformed stored value
    """
    value = actual_value.get( "value" ) if isinstance( actual_value, dict ) else None
    decoded = PredictionEngine._parse_mc_decision_value( value ) if isinstance( value, str ) else None
    if decoded is None: return "skipped", "not_json_answers", None, None
    if not isinstance( predicted_value, dict ) or not predicted_value: return "skipped", "no_prediction", None, None
    match, detail = get_comparator( RESPONSE_TYPE, actual_value=decoded )( predicted_value, decoded )
    if match is None: return "skipped", "comparator_unscored", None, None
    return "would_score", decoded, match, detail


def select_rows( session ):
    """
    Return the multiple_choice rows still marked empty_answers.

    Ensures:
        - returns a list of PredictionLog rows; open_ended_batch and every other type is excluded
    """
    return session.query( PredictionLog ).filter(
        PredictionLog.response_type == RESPONSE_TYPE,
        PredictionLog.accuracy_detail[ "reason" ].astext == UNSCORED_REASON
    ).all()


def default_dump_path():
    """
    Return the default dump file path, stamped with the UTC time.

    Ensures:
        - returns a path under the project root's io/ directory, unique to the second
    """
    stamp = datetime.now( timezone.utc ).strftime( "%Y%m%dT%H%M%SZ" )
    return os.path.join( cu.get_project_root(), "io", f"rescore-empty-answers-mc-{stamp}.jsonl" )


def dump_old_values( planned, dump_path ):
    """
    Write the old stored values of every row about to change, then flush them to disk.

    Requires:
        - planned is a list of ( row, decoded, match, detail ) tuples

    Ensures:
        - dump_path holds one JSON line per row: id, notification_id, actual_value, accuracy_match, accuracy_detail
        - the file is closed and fsynced before this returns, so a later write never runs ahead of it
        - returns the number of lines written

    Raises:
        - OSError when the file cannot be written; the caller then writes nothing
    """
    os.makedirs( os.path.dirname( os.path.abspath( dump_path ) ), exist_ok=True )
    with open( dump_path, "w", encoding="utf-8" ) as out:
        for row, _decoded, _match, _detail in planned:
            out.write( json.dumps( { "id": str( row.id ), "notification_id": str( row.notification_id ), "actual_value": row.actual_value,
                                     "accuracy_match": row.accuracy_match, "accuracy_detail": row.accuracy_detail } ) + "\n" )
        out.flush()
        os.fsync( out.fileno() )
    return len( planned )


def rescore( session, write=False, dump_path=None ):
    """
    Classify every selected row; with write, dump the old values, then store the scores.

    Requires:
        - session is an open SQLAlchemy session
        - dump_path is the dump file for a write run, or None for the default path

    Ensures:
        - returns a Counter with selected, would_score, match, miss and skipped:<reason> keys, plus dumped on a write run
        - writes only with write=True; then dumps first, sets actual_value, accuracy_match and accuracy_detail, and leaves responded_at alone
        - a failed dump raises before any row changes
        - commits every COMMIT_EVERY rows and once at the end
    """
    rows, counts, planned = select_rows( session ), Counter(), []
    counts[ "selected" ] = len( rows )
    for row in rows:
        outcome, decoded_or_reason, match, detail = classify( row.actual_value, row.predicted_value )
        if outcome == "skipped":
            counts[ f"skipped:{decoded_or_reason}" ] += 1
            continue
        counts[ "would_score" ] += 1
        counts[ "match" if match else "miss" ] += 1
        planned.append( ( row, decoded_or_reason, match, detail ) )
    if not write: return counts
    counts[ "dumped" ] = dump_old_values( planned, dump_path if dump_path is not None else default_dump_path() )
    for done, ( row, decoded, match, detail ) in enumerate( planned, start=1 ):
        row.actual_value    = { k: v for k, v in decoded.items() if not k.startswith( "_" ) }
        row.accuracy_match  = match
        row.accuracy_detail = detail
        if done % COMMIT_EVERY == 0: session.commit()
    session.commit()
    return counts


def main( argv=None, session_factory=None ):
    """
    Run the rescore from the command line and print the counts.

    Ensures:
        - report only unless --write is given
        - returns 0
    """
    parser = argparse.ArgumentParser( description="Rescore old multiple-choice rows left unscored as empty_answers." )
    parser.add_argument( "--write", action="store_true", help="dump the old values, then store the new scores; without it nothing is written" )
    parser.add_argument( "--dump-path", default=None, help="the dump file for --write; default io/rescore-empty-answers-mc-<UTC stamp>.jsonl" )
    args = parser.parse_args( argv )
    if session_factory is None:
        from cosa.rest.db.database import get_db as session_factory
    dump_path = ( args.dump_path if args.dump_path is not None else default_dump_path() ) if args.write else None
    with session_factory() as session:
        counts = rescore( session, write=args.write, dump_path=dump_path )
    print( f"mode: {'WRITE' if args.write else 'report only'}" )
    for key in sorted( counts ): print( f"{key:32} {counts[ key ]}" )
    if args.write: print( f"dump file: {dump_path}" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
