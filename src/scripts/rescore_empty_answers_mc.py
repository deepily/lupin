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

Rows it skips, each counted under its own reason:
    - not_json_answers: actual_value holds no JSON with an "answers" mapping, such as a bare label
    - no_prediction: predicted_value is empty, so there is nothing to compare
    - comparator_unscored: the comparator still answered match None, as for a cancelled card
The 60 open_ended_batch rows are out of scope (Rick's ruling) and are never selected.

Usage:
    PYTHONPATH=src python src/scripts/rescore_empty_answers_mc.py             # report only
    PYTHONPATH=src python src/scripts/rescore_empty_answers_mc.py --write     # rescore

Exit codes:
    0  ran; read the counts
    3  a required import failed: wrong interpreter or PYTHONPATH
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

try:
    from cosa.agents.prediction_engine.accuracy_comparators import get_comparator
    from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
    from cosa.rest.postgres_models import PredictionLog
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


def rescore( session, write=False ):
    """
    Classify every selected row and, with write, store the new score.

    Requires:
        - session is an open SQLAlchemy session

    Ensures:
        - returns a Counter with selected, would_score, match, miss and skipped:<reason> keys
        - writes only with write=True; then sets actual_value, accuracy_match and accuracy_detail and leaves responded_at alone
        - commits every COMMIT_EVERY rows and once at the end
    """
    rows, counts = select_rows( session ), Counter()
    counts[ "selected" ] = len( rows )
    for row in rows:
        outcome, decoded_or_reason, match, detail = classify( row.actual_value, row.predicted_value )
        if outcome == "skipped":
            counts[ f"skipped:{decoded_or_reason}" ] += 1
            continue
        counts[ "would_score" ] += 1
        counts[ "match" if match else "miss" ] += 1
        if write:
            row.actual_value    = { k: v for k, v in decoded_or_reason.items() if not k.startswith( "_" ) }
            row.accuracy_match  = match
            row.accuracy_detail = detail
            if counts[ "would_score" ] % COMMIT_EVERY == 0: session.commit()
    if write: session.commit()
    return counts


def main( argv=None, session_factory=None ):
    """
    Run the rescore from the command line and print the counts.

    Ensures:
        - report only unless --write is given
        - returns 0
    """
    parser = argparse.ArgumentParser( description="Rescore old multiple-choice rows left unscored as empty_answers." )
    parser.add_argument( "--write", action="store_true", help="store the new scores; without it nothing is written" )
    args = parser.parse_args( argv )
    if session_factory is None:
        from cosa.rest.db.database import get_db as session_factory
    with session_factory() as session:
        counts = rescore( session, write=args.write )
    print( f"mode: {'WRITE' if args.write else 'report only'}" )
    for key in sorted( counts ): print( f"{key:32} {counts[ key ]}" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
