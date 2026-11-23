"""
Capture the organic proxy_decisions rows of one day as a fixture, read-only.

The neither-fix replay needs the 43 organic rows of one day. A unit test cannot reach the database from a worktree.
So this script reads the rows once from the dev database and prints them as JSON on standard output.
It writes nothing to the database. The transaction is read-only before the first query.

Usage:
    python src/scripts/capture_proxy_decisions_fixture.py --day <day> > <fixture path>
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

QUERY = (
    "select category, action, decision_value, rule_agreement, metadata_json, question, created_at "
    "from proxy_decisions where data_origin = 'organic' "
    "and date( created_at at time zone 'UTC' ) = :day order by created_at, id"
)


def capture( day ):
    """
    Read one day's organic proxy_decisions rows, read-only.

    Requires:
        - day is an ISO date string, such as "2026-11-05"
        - the dev database is reachable through cosa.rest.db.database.get_db

    Ensures:
        - returns a list of dicts with category, action, decision_value, rule_agreement, user_answer, question and created_at, oldest first
        - the transaction is read-only, so nothing is written
        - the notification id is left out: the fixture needs no join key
    """
    from sqlalchemy import text
    from cosa.rest.db.database import get_db

    with get_db() as session:
        session.execute( text( "SET TRANSACTION READ ONLY" ) )
        rows = session.execute( text( QUERY ), { "day": day } ).fetchall()

    return [
        {
            "category"       : row.category,
            "action"         : row.action,
            "decision_value" : row.decision_value,
            "rule_agreement" : row.rule_agreement,
            "user_answer"    : ( row.metadata_json or {} ).get( "user_answer" ),
            "question"       : row.question,
            "created_at"     : row.created_at.isoformat(),
        }
        for row in rows
    ]


def main( argv=None ):
    """Print the captured rows as JSON on standard output and return 0."""
    parser = argparse.ArgumentParser( description="Capture one day's organic proxy_decisions rows, read-only." )
    parser.add_argument( "--day", required=True )
    args = parser.parse_args( argv )
    print( json.dumps( capture( args.day ), indent=2 ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
