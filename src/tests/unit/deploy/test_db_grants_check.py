"""
The privilege matrix and the read-only check built on it.

The matrix in cosa.utils.db_grants and the grants in init-db-roles.sql describe one thing in two places.
The first test reads the SQL as psql would and fails when the two disagree. The real Postgres run
is in tests/smoke/test_db_grants_real_postgres.py.
Venue: :7999 (unit, no database).
"""

import io
import os
import re
import subprocess

import pytest

from cosa.utils import db_grants as g
from cosa.utils import db_roles
from test_db_roles_grants_only import active_lines

SQL_PATH = os.path.join( os.environ[ "LUPIN_ROOT" ], db_roles.SQL_RELATIVE_PATH )


def _statements():
    """Every active statement of the grants run, as ( database, text )."""
    with open( SQL_PATH ) as handle: lines = active_lines( handle.read(), { "grants_only" } )
    out, current, buffer = [], None, []
    for line in lines:
        if line.startswith( "\\connect " ): current = line.split()[ 1 ]; continue
        if line.strip().startswith( "--" ) or not line.strip(): continue
        buffer.append( line.strip() )
        if line.rstrip().endswith( ";" ):
            out.append( ( current, re.sub( r"\s+", " ", " ".join( buffer ) ) ) )
            buffer = []
    return out


def _privileges( text ):
    return g.ALL_PRIVILEGES if text.strip().upper() == "ALL" else tuple( p.strip().upper() for p in text.split( "," ) )


def _sequences_from_the_sql():
    found = set()
    for database, text in _statements():
        grant = re.match( r"GRANT (.+?) ON ALL SEQUENCES IN SCHEMA public TO (.+);$", text )
        if grant:
            privileges = g.SEQUENCE_PRIVILEGES if grant.group( 1 ) == "ALL" else tuple( p.strip() for p in grant.group( 1 ).split( "," ) )
            found.update( ( database, role.strip(), p ) for role in grant.group( 2 ).split( "," ) for p in privileges )
    return found


def test_the_sequence_rules_and_the_sql_describe_the_same_grants():
    sql = _sequences_from_the_sql()
    assert sql, "the instrument read no sequence grants from the SQL"
    assert sql == set( g.SEQUENCE_RULES )


def _matrix_from_the_sql():
    """( table grants, connect grants, host bars ) as the SQL states them."""
    tables, connects, barred = {}, set(), set()
    for database, text in _statements():
        grant = re.match( r"GRANT (.+?) ON ALL TABLES IN SCHEMA public TO (.+);$", text )
        if grant:
            for role in ( r.strip() for r in grant.group( 2 ).split( "," ) ):
                tables.setdefault( ( database, role ), set() ).update( _privileges( grant.group( 1 ) ) )
        connect = re.match( r"GRANT CONNECT ON DATABASE (\w+) TO (.+);$", text )
        if connect: connects.update( ( connect.group( 1 ), r.strip() ) for r in connect.group( 2 ).split( "," ) )
        revoke = re.search( r"REVOKE (.+?) ON approval_settings FROM (\w+)", text )
        if revoke: barred.update( ( database, revoke.group( 2 ), p ) for p in _privileges( revoke.group( 1 ) ) )
    return tables, connects, barred


def _matrix_from_python():
    tables, connects, barred = {}, set(), set()
    for database, role, privilege, scope, table, expected in g.TABLE_RULES:
        if expected and scope in ( "all", "except" ): tables.setdefault( ( database, role ), set() ).add( privilege )
        if not expected: barred.add( ( database, role, privilege ) )
    connects = { ( db, role ) for db, role, expected in g.CONNECT_RULES if expected }
    return tables, connects, barred


def test_the_matrix_and_the_sql_describe_the_same_grants():
    sql, python = _matrix_from_the_sql(), _matrix_from_python()
    assert sql[ 0 ], "the instrument read no table grants from the SQL"
    assert sql[ 0 ] == python[ 0 ], "table grants differ between the SQL and the matrix"
    assert sql[ 1 ] == python[ 1 ], "connect grants differ between the SQL and the matrix"
    assert sql[ 2 ] == python[ 2 ], "the approval_settings bars differ between the SQL and the matrix"


def test_the_matrix_holds_no_connect_for_lupin_test_on_dev_and_none_for_lupin_host_on_test():
    allowed = { ( db, role ) for db, role, expected in g.CONNECT_RULES if expected }
    assert ( g.DEV_DB, g.TEST_ROLE ) not in allowed and ( g.TEST_DB, g.HOST_ROLE ) not in allowed
    assert len( g.CONNECT_RULES ) == 6


# ── the query ────────────────────────────────────────────────────────────────

def test_the_check_query_only_reads():
    text = re.sub( r"'[^']*'", "''", g.build_check_sql( g.DEV_DB ) )
    assert not re.search( r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|GRANT|REVOKE|CREATE|TRUNCATE)\b", text, re.IGNORECASE )
    assert "has_table_privilege" in text and "has_database_privilege" in text


def test_the_check_query_names_the_roles_and_the_guarded_table_of_its_database():
    dev, test = g.build_check_sql( g.DEV_DB ), g.build_check_sql( g.TEST_DB )
    assert "'lupin_host', 'SELECT', 'only', 'approval_settings', true" in dev
    assert "lupin_host" in test and "'lupin_host', 'SELECT'" not in test, "the host role has no table rule in the test database"


def test_the_check_query_asks_about_sequences_as_well_as_tables():
    text = g.build_check_sql( g.TEST_DB )
    assert "has_sequence_privilege" in text and "relkind = 'S'" in text
    assert "( 'lupin_test', 'usage' )" in text


def test_a_database_outside_the_matrix_is_refused():
    with pytest.raises( AssertionError, match="no privilege matrix for lupin_db_other" ): g.build_check_sql( "lupin_db_other" )


# ── reading the answer ───────────────────────────────────────────────────────

def _rows( *lines ): return g.parse_rows( "\n".join( lines ) + "\n" )


def test_a_clean_database_is_ok_with_its_table_and_role_counts():
    report = g.evaluate( g.TEST_DB, _rows( "lupin_db_test|tables||27|" ) )
    assert report == { "database": "lupin_db_test", "tables": 27, "roles": 3, "problems": [], "ok": True }


def test_each_problem_row_is_kept_in_order_with_its_kind():
    rows = _rows( "lupin_db_dev|tables||3|", "lupin_db_dev|missing|lupin_host|widgets|INSERT", "lupin_db_dev|unexpected|lupin_host|approval_settings|UPDATE" )
    report = g.evaluate( g.DEV_DB, rows )
    assert report[ "problems" ] == [ ( "missing", "lupin_host", "widgets", "INSERT" ), ( "unexpected", "lupin_host", "approval_settings", "UPDATE" ) ]
    assert report[ "ok" ] is False


def test_zero_tables_is_a_failure_and_not_a_pass():
    report = g.evaluate( g.DEV_DB, _rows( "lupin_db_dev|tables||0|" ) )
    assert report[ "ok" ] is False and report[ "problems" ][ 0 ][ 0 ] == "empty"


def test_an_answer_with_no_table_count_raises_because_nothing_was_checked():
    with pytest.raises( ValueError, match="no table count" ): g.evaluate( g.DEV_DB, _rows( "lupin_db_test|tables||5|" ) )


def test_a_line_that_is_not_a_result_row_raises_naming_it():
    with pytest.raises( ValueError, match="not a result row" ): g.parse_rows( "ERROR: boom\n" )


def test_blank_lines_between_rows_are_skipped():
    assert g.parse_rows( "d|tables||1|\n\n  \nd|missing|r|t|SELECT\n" ) == [ ( "d", "tables", "", "1", "" ), ( "d", "missing", "r", "t", "SELECT" ) ]


def test_the_report_has_a_summary_line_per_database_the_problems_and_the_remedy():
    reports = [ g.evaluate( g.DEV_DB, _rows( "lupin_db_dev|tables||3|", "lupin_db_dev|missing|lupin_host|widgets|INSERT" ) ),
                g.evaluate( g.TEST_DB, _rows( "lupin_db_test|tables||2|" ) ) ]
    lines = g.format_report( reports, "remedy: X" )
    assert lines == [ "lupin_db_dev: 3 tables, 3 roles, 1 problems", "  lupin_host cannot INSERT widgets",
                      "lupin_db_test: 2 tables, 3 roles, 0 problems", "remedy: X" ]


def test_a_clean_report_prints_no_remedy():
    lines = g.format_report( [ g.evaluate( g.TEST_DB, _rows( "lupin_db_test|tables||2|" ) ) ], "remedy: X" )
    assert lines == [ "lupin_db_test: 2 tables, 3 roles, 0 problems" ]


def test_the_remedy_is_grants_only_unless_a_role_is_missing():
    gap = [ g.evaluate( g.DEV_DB, _rows( "lupin_db_dev|tables||3|", "lupin_db_dev|missing|lupin_host|widgets|INSERT" ) ) ]
    assert g.remedy_for( "docker exec -i box psql -U u -d lupin_db_dev", gap ) == \
        "remedy: python -m cosa.utils.db_roles --psql 'docker exec -i box psql -U u -d lupin_db_dev' --grants-only --apply"
    nobody = [ g.evaluate( g.DEV_DB, _rows( "lupin_db_dev|tables||3|", "lupin_db_dev|norole|lupin_app||" ) ) ]
    assert "full provisioning" in g.remedy_for( "psql", nobody ) and "--grants-only" not in g.remedy_for( "psql", nobody )


@pytest.mark.parametrize( "kind, text", [ ( "unexpected", "can UPDATE approval_settings and must not" ), ( "norole", "role lupin_app does not exist" ),
                                          ( "empty", "has no public tables" ) ] )
def test_each_kind_of_problem_has_its_own_sentence( kind, text ):
    report = { "database": "d", "tables": 1, "roles": 1, "ok": False, "problems": [ ( kind, "lupin_app" if kind == "norole" else "lupin_host", "approval_settings" if kind != "norole" else "", "UPDATE" ) ] }
    assert any( text in line for line in g.format_report( [ report ], "r" ) )


# ── running it through psql ──────────────────────────────────────────────────

class Psql:
    def __init__( self, stdout="", returncode=0, stderr="" ): self.calls, self.stdout, self.returncode, self.stderr = [], stdout, returncode, stderr
    def __call__( self, command, input, text, capture_output ):
        self.calls.append( ( command, input ) )
        return type( "Done", (), { "returncode": self.returncode, "stdout": self.stdout, "stderr": self.stderr } )()


CLEAN = "lupin_db_dev|tables||3|\nlupin_db_test|tables||2|\n"


def test_a_clean_run_exits_zero_and_asks_both_databases_read_only():
    run = Psql( CLEAN )
    code, lines = g.check_with_psql( "docker exec -i box psql -U u -d lupin_db_dev", run )
    assert code == 0 and len( lines ) == 2
    command, script = run.calls[ 0 ]
    assert "-tA" in command and "ON_ERROR_STOP=1" in command
    assert script.index( "\\connect lupin_db_dev" ) < script.index( "\\connect lupin_db_test" )


def test_a_gap_exits_one_and_names_it():
    run = Psql( CLEAN + "lupin_db_test|missing|lupin_test|widgets|DELETE\n" )
    code, lines = g.check_with_psql( "psql", run )
    assert code == 1 and "  lupin_test cannot DELETE widgets" in lines and lines[ -1 ].startswith( "remedy:" )


def test_a_psql_failure_exits_two_and_is_not_a_pass():
    code, lines = g.check_with_psql( "psql", Psql( returncode=3, stderr="connection refused" ) )
    assert code == 2 and "psql exited 3" in lines[ 0 ] and "connection refused" in lines[ 0 ]


def test_an_unreadable_answer_exits_two():
    code, lines = g.check_with_psql( "psql", Psql( "garbage\n" ) )
    assert code == 2 and "could not read" in lines[ 0 ]


def test_an_answer_missing_one_database_exits_two():
    code, lines = g.check_with_psql( "psql", Psql( "lupin_db_dev|tables||3|\n" ) )
    assert code == 2 and "lupin_db_test" in lines[ 0 ]


# ── the command line ─────────────────────────────────────────────────────────

def test_check_runs_with_no_password_file_no_sql_file_and_no_apply():
    run, out = Psql( CLEAN ), io.StringIO()
    code = db_roles.main( [ "--psql", "psql -U u -d lupin_db_dev", "--sql", "/nonexistent/init.sql", "--check" ], run_fn=run, out=out )
    assert code == 0 and len( run.calls ) == 1 and "lupin_db_dev: 3 tables" in out.getvalue()


def test_check_returns_the_exit_code_of_the_check():
    run = Psql( CLEAN + "lupin_db_dev|missing|lupin_app|widgets|SELECT\n" )
    assert db_roles.main( [ "--psql", "psql", "--check" ], run_fn=run, out=io.StringIO() ) == 1


def test_check_with_a_database_option_asks_only_that_database():
    run = Psql( "lupin_db_test|tables||2|\n" )
    code = db_roles.main( [ "--psql", "psql -U lupin_test -d lupin_db_test", "--check", "--database", "lupin_db_test" ], run_fn=run, out=io.StringIO() )
    script = run.calls[ 0 ][ 1 ]
    assert code == 0 and "\\connect lupin_db_test" in script and "\\connect lupin_db_dev" not in script


def test_a_database_option_may_be_given_twice_and_keeps_its_order():
    run = Psql( CLEAN )
    db_roles.main( [ "--psql", "psql", "--check", "--database", "lupin_db_test", "--database", "lupin_db_dev" ], run_fn=run, out=io.StringIO() )
    script = run.calls[ 0 ][ 1 ]
    assert script.index( "\\connect lupin_db_test" ) < script.index( "\\connect lupin_db_dev" )


def test_a_database_option_outside_the_matrix_or_without_check_is_refused():
    run = Psql( CLEAN )
    with pytest.raises( SystemExit ): db_roles.main( [ "--psql", "psql", "--check", "--database", "lupin_db_other" ], run_fn=run, out=io.StringIO() )
    with pytest.raises( SystemExit ): db_roles.main( [ "--psql", "psql", "--grants-only", "--database", "lupin_db_test" ], run_fn=run, out=io.StringIO() )
    assert run.calls == []


@pytest.mark.parametrize( "other", [ "--reassign", "--rollback", "--grants-only" ] )
def test_check_with_another_direction_is_refused_before_anything_runs( other ):
    run = Psql( CLEAN )
    with pytest.raises( SystemExit ): db_roles.main( [ "--psql", "psql", "--check", other ], run_fn=run, out=io.StringIO() )
    assert run.calls == []


def _flood():
    rows = [ ( "lupin_db_test", "tables", "", "27", "" ) ]
    rows += [ ( "lupin_db_test", "missing", "lupin_app", f"t{i:02d}", p ) for i in range( 40 ) for p in g.ALL_PRIVILEGES ]
    return g.evaluate( "lupin_db_test", rows )


def test_the_full_report_lists_every_problem_and_the_log_form_groups_and_cuts_it():
    report = _flood()
    assert len( report[ "problems" ] ) == 280
    full = g.format_report( [ report ], "r" )
    assert len( full ) == 282 and "  lupin_app cannot SELECT t00" in full
    cut = g.report_lines( report )
    assert len( cut ) == 1 + g.LOG_LINE_LIMIT + 1 + 1, "summary, the limit, the more line, the remedy"
    assert cut[ 0 ] == "lupin_db_test: 27 tables, 3 roles, 280 problems"
    assert cut[ 1 ] == "  lupin_app cannot SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER t00"
    assert cut[ -2 ] == "  ... and 10 more; run db_roles --check for the full list" and cut[ -1 ].startswith( "remedy:" )


def test_a_report_within_the_limit_has_no_more_line_and_keeps_its_groups():
    report = g.evaluate( "lupin_db_test", [ ( "lupin_db_test", "tables", "", "2", "" ), ( "lupin_db_test", "missing", "lupin_app", "t", "DELETE" ),
                                              ( "lupin_db_test", "missing", "lupin_app", "t", "INSERT" ), ( "lupin_db_test", "norole", "lupin_x", "", "" ) ] )
    lines = g.report_lines( report )
    assert lines[ 1: 3 ] == [ "  lupin_app cannot DELETE, INSERT t", "  role lupin_x does not exist" ]
    assert not any( "more;" in l for l in lines )
