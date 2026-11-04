"""
The integration and e2e clean_test_db fixtures truncate the same tables.

The two fixtures were written apart and drifted.
The e2e one left the task tables and the push tokens alone.
Rows an e2e test made then stayed until the next integration test.
This reads the table list each fixture clears and requires the same set.

Venue: :7999 (unit, reads two conftest files).
"""

import ast
import os

import pytest

ROOT     = os.environ[ "LUPIN_ROOT" ]
FIXTURES = { "integration": "src/tests/integration/conftest.py", "e2e": "src/tests/e2e_ui/conftest.py" }


def _truncated( relative ):
    """The table names in the one clear-tables statement of a conftest."""
    with open( os.path.join( ROOT, relative ), encoding="utf-8" ) as handle: tree = ast.parse( handle.read() )
    texts = [ n.value for n in ast.walk( tree ) if isinstance( n, ast.Constant ) and isinstance( n.value, str )
              and n.value.startswith( "TRUNCATE TABLE" ) ]
    assert len( texts ) == 1, f"{relative}: expected one TRUNCATE TABLE statement, found {len( texts )}"
    return { name.strip() for name in texts[ 0 ][ len( "TRUNCATE TABLE" ): ].split( "," ) }


def test_both_fixtures_truncate_the_same_set_of_tables():
    integration, e2e = _truncated( FIXTURES[ "integration" ] ), _truncated( FIXTURES[ "e2e" ] )
    assert len( integration ) >= 9, "the scan found too few tables to trust a comparison"
    assert integration - e2e == set(), f"truncated in integration only: {sorted( integration - e2e )}"
    assert e2e - integration == set(), f"truncated in e2e only: {sorted( e2e - integration )}"


@pytest.mark.parametrize( "table", [ "task_items", "task_events", "task_promotion_tickets", "fcm_tokens" ] )
def test_the_e2e_fixture_truncates_the_task_tables_and_the_push_tokens( table ):
    assert table in _truncated( FIXTURES[ "e2e" ] )
