"""
The check of the template database the tests clone.

The template, lupin_template_vector, must exist, be marked as a template and refuse connections. The
check reads one catalog row, so it needs no connection to the template. A clean template adds no output
line, so the lines of a clean run stay as they were. A problem adds its own lines and turns the exit to 1.

Venue: :7999-eligible. No database; the psql answer is canned.
"""

import pytest

from cosa.utils import db_grants as g
from test_db_grants_check import CLEAN, Psql

NAME = "lupin_template_vector"


def _row( exists, is_template, allows ):
    return f"{NAME}|template|{exists}|{is_template}|{allows}\n"


def test_the_query_prints_one_row_and_reads_only_the_catalog():
    sql = g.build_template_sql()
    assert sql.count( "FROM pg_database" ) == 1 and f"WHERE datname = '{NAME}'" in sql
    assert sql.startswith( f"SELECT '{NAME}|template|'" ) and sql.endswith( ";\n" )
    assert "\\connect" not in sql, "the template refuses connections, so the query must not connect to it"


def test_the_script_of_a_check_ends_with_the_template_query_after_both_databases():
    run = Psql( CLEAN + _row( "true", "true", "false" ) )
    g.check_with_psql( "psql", run )
    script = run.calls[ 0 ][ 1 ]
    assert script.index( "\\connect lupin_db_test" ) < script.index( g.build_template_sql() )


@pytest.mark.parametrize( "flags,expected", [
    ( ( "true", "true", "false" ), [] ),
    ( ( "false", "false", "false" ), [ f"{NAME} does not exist, so a test that creates a database cannot clone it" ] ),
    ( ( "true", "false", "false" ), [ f"{NAME} is not marked as a template, so a plain login cannot clone it" ] ),
    ( ( "true", "true", "true" ),   [ f"{NAME} accepts connections, so a clone can fail while someone is connected to it" ] ),
    ( ( "true", "false", "true" ),  [ f"{NAME} is not marked as a template, so a plain login cannot clone it",
                                      f"{NAME} accepts connections, so a clone can fail while someone is connected to it" ] ),
] )
def test_each_flag_is_judged_on_its_own( flags, expected ):
    assert g.template_problems( g.parse_rows( _row( *flags ) ) ) == expected


def test_rows_that_hold_no_template_row_mean_it_was_not_asked_about():
    assert g.template_problems( g.parse_rows( CLEAN ) ) is None


def test_a_clean_template_leaves_the_lines_of_a_clean_run_as_they_were():
    clean = ( 0, [ "lupin_db_dev: 3 tables, 3 roles, 0 problems", "lupin_db_test: 2 tables, 3 roles, 0 problems" ] )
    assert g.check_with_psql( "psql", Psql( CLEAN ) ) == clean
    assert g.check_with_psql( "psql", Psql( CLEAN + _row( "true", "true", "false" ) ) ) == clean


def test_a_missing_template_exits_one_names_it_and_ends_with_the_one_repair_command():
    code, lines = g.check_with_psql( "psql", Psql( CLEAN + _row( "false", "false", "false" ) ) )
    assert code == 1
    assert lines[ 2 ] == f"{NAME}: 1 problems" and "does not exist" in lines[ 3 ]
    assert lines[ -1 ].startswith( "remedy:" ) and "--grants-only --apply" in lines[ -1 ]


def test_a_template_problem_beside_a_grant_gap_keeps_one_remedy_line_last():
    stdout      = CLEAN + "lupin_db_test|missing|lupin_test|widgets|DELETE\n" + _row( "true", "true", "true" )
    code, lines = g.check_with_psql( "psql", Psql( stdout ) )
    assert code == 1 and lines[ -1 ].startswith( "remedy:" ) and sum( l.startswith( "remedy:" ) for l in lines ) == 1
    assert lines.index( f"{NAME}: 1 problems" ) < len( lines ) - 1
    assert "  lupin_test cannot DELETE widgets" in lines


def test_the_template_is_asked_about_even_when_one_database_is_named():
    run = Psql( "lupin_db_test|tables||2|\n" + _row( "true", "true", "false" ) )
    code, _lines = g.check_with_psql( "psql", run, which=[ "lupin_db_test" ] )
    assert code == 0 and g.build_template_sql() in run.calls[ 0 ][ 1 ]
