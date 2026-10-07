"""
The integration test of clean_test_db runs the real fixture and holds no copy of its SQL.

That test needs the live test server, so the unit tier cannot run it. These checks read its source.

The stray-user fixture comes before clean_test_db in the argument list. Pytest builds it first,
so the real cleanup runs over it. No cleanup statement is written out in the test body, where it
could drift from the fixture.
"""

import ast
import os

import pytest

ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
PATH = os.path.join( ROOT, "src", "tests", "integration", "test_conftest_clean_test_db.py" )
NAME = "test_clean_test_db_removes_prior_test_users"


def _function( name ):
    with open( PATH, encoding="utf-8" ) as handle: tree = ast.parse( handle.read() )
    found = [ node for node in ast.walk( tree ) if isinstance( node, ast.FunctionDef ) and node.name == name ]
    assert len( found ) == 1, f"{name} appears {len( found )} times in {PATH}"
    return found[ 0 ]


def test_the_stray_user_fixture_is_built_before_the_real_cleanup():
    arguments = [ argument.arg for argument in _function( NAME ).args.args ]
    assert "a_stray_user" in arguments and "clean_test_db" in arguments, arguments
    assert arguments.index( "a_stray_user" ) < arguments.index( "clean_test_db" ), \
        f"clean_test_db would run first and find nothing to clean: {arguments}"


@pytest.mark.parametrize( "statement", [ "TRUNCATE", "DELETE FROM", "drop_all", "create_all" ] )
def test_the_test_body_holds_no_copy_of_a_cleanup_statement( statement ):
    body = ast.get_source_segment( open( PATH, encoding="utf-8" ).read(), _function( NAME ) )
    assert statement.lower() not in body.lower(), f"{statement} is written out in {NAME}; call the fixture instead"
