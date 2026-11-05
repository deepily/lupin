"""
Both clean_test_db fixtures let a protected smoke admin survive.

The post-delete safety check used to demand a fixed number of protected rows.
Protecting the smoke admin would have reddened every test, so the check now counts
the companions and permits only protected admins beyond them.
These checks read the fixture source, because the fixtures need the live :8000 database.
"""

import ast
import os

import pytest

ROOT     = os.environ.get( "LUPIN_ROOT", os.getcwd() )
FIXTURES = { "integration": "src/tests/integration/conftest.py", "e2e": "src/tests/e2e_ui/conftest.py" }


def _fixture_source( rel ):
    path = os.path.join( ROOT, rel )
    with open( path, encoding="utf-8" ) as handle: text = handle.read()
    found = [ n for n in ast.walk( ast.parse( text ) ) if isinstance( n, ast.FunctionDef ) and n.name == "clean_test_db" ]
    assert len( found ) == 1, f"clean_test_db appears {len( found )} times in {rel}"
    return ast.get_source_segment( text, found[ 0 ] )


@pytest.mark.parametrize( "name", sorted( FIXTURES ) )
def test_the_check_counts_companions_not_every_protected_row( name ):
    source = _fixture_source( FIXTURES[ name ] )
    assert "WHERE is_protected AND email = ANY( :emails )" in source
    assert 'text( "SELECT count(*) FROM users WHERE is_protected" )' not in source


@pytest.mark.parametrize( "name", sorted( FIXTURES ) )
def test_only_protected_admins_are_allowed_beyond_the_companions( name ):
    source = _fixture_source( FIXTURES[ name ] )
    assert "NOT ( roles @> CAST( '[\\\"admin\\\"]' AS jsonb ) )" in source
    assert "unexpected protected non-admin users" in source
