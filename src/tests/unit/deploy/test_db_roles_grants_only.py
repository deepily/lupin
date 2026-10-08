"""
db_roles --grants-only: grants and default privileges, with no role or password statement.

The SQL is read as psql reads it: the \\if lines are followed with grants_only set, and only the
lines that would run are kept. The real run against Postgres is in tests/smoke/test_db_grants_real_postgres.py.
Venue: :7999 (unit, no database).
"""

import io
import os
import re

import pytest

from cosa.utils import db_roles

SQL_PATH = os.path.join( os.environ[ "LUPIN_ROOT" ], db_roles.SQL_RELATIVE_PATH )
PASSWORD_WORDS = re.compile( r"CREATE ROLE|ALTER ROLE|PASSWORD|:'(app|host|test)_pw'|\bapp_pw\b|\bhost_pw\b|\btest_pw\b", re.IGNORECASE )


def active_lines( text, variables, truthy=( "has_test_db", ) ):
    """
    The lines psql would run, following \\if / \\else / \\endif.

    Requires:
        - variables is the set of psql variables that are set
        - truthy names the boolean variables that read true (the precheck's has_test_db)
    """
    stack, kept = [], []
    for line in text.splitlines():
        word = line.strip()
        if word.startswith( "\\if " ):
            condition = word[ 4: ].strip()
            if condition.startswith( ":{?" ): value = condition[ 3:-1 ] in variables
            else:                             value = condition.lstrip( ":" ) in truthy
            stack.append( ( value, value ) )
        elif word == "\\else":
            taken, _ = stack.pop()
            stack.append( ( not taken, True ) )
        elif word == "\\endif": stack.pop()
        elif all( state for state, _ in stack ): kept.append( line )
    assert not stack, "unbalanced \\if in init-db-roles.sql"
    return kept


def _sql():
    with open( SQL_PATH ) as handle: return handle.read()


def test_the_walker_finds_the_password_statements_when_it_is_not_grants_only():
    lines = "\n".join( active_lines( _sql(), { "app_pw", "host_pw", "test_pw" } ) )
    assert "CREATE ROLE" in lines and "ALTER ROLE lupin_test CREATEDB" in lines, "the instrument cannot see a role statement"


def test_grants_only_runs_no_role_or_password_statement():
    lines = [ l for l in active_lines( _sql(), { "grants_only" } ) if not l.strip().startswith( "--" ) ]
    hits  = [ l for l in lines if PASSWORD_WORDS.search( l ) ]
    assert hits == [ ], f"a role or password statement runs under grants_only: {hits}"


def test_grants_only_still_runs_the_grants_the_revoke_and_the_default_privileges():
    lines = "\n".join( active_lines( _sql(), { "grants_only" } ) )
    assert lines.count( "GRANT ALL ON ALL TABLES" ) == 2
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO lupin_host" in lines
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON approval_settings FROM lupin_host" in lines
    assert "ALTER DEFAULT PRIVILEGES" in lines


def test_grants_only_stops_with_a_named_error_when_a_role_is_missing():
    lines = "\n".join( active_lines( _sql(), { "grants_only", "missing_any" }, truthy=( "has_test_db", "missing_any" ) ) )
    assert "grants_only does not create roles" in lines and "missing roles :missing_names" in lines


# ── the Python side ──────────────────────────────────────────────────────────

class Recorder:
    def __init__( self ): self.calls = []
    def __call__( self, command, input, text ):
        self.calls.append( ( command, input ) )
        return type( "Done", (), { "returncode": 0 } )()


@pytest.fixture
def sql_file( tmp_path ):
    path = tmp_path / "init-db-roles.sql"
    path.write_text( "SELECT 1;\n" )
    return str( path )


def test_the_stdin_for_grants_only_is_one_flag_and_the_sql_with_no_password_line():
    text = db_roles.build_psql_stdin( "AAAA", "HHHH", "TTTT", "SELECT 1;\n", grants_only=True )
    assert text.splitlines() == [ "\\set grants_only 1", "SELECT 1;" ]


def test_grants_only_runs_with_no_password_file_option_and_sends_no_password( sql_file ):
    run  = Recorder()
    argv = [ "--psql", "psql -U admin -d lupin_db_dev", "--sql", sql_file, "--grants-only", "--apply" ]
    assert db_roles.main( argv, run_fn=run, out=io.StringIO() ) == 0
    assert len( run.calls ) == 1 and run.calls[ 0 ][ 1 ].splitlines()[ 0 ] == "\\set grants_only 1"


def test_a_grants_only_dry_run_runs_nothing( sql_file ):
    run, out = Recorder(), io.StringIO()
    assert db_roles.main( [ "--psql", "psql", "--sql", sql_file, "--grants-only" ], run_fn=run, out=out ) == 0
    assert run.calls == [] and "DRY RUN" in out.getvalue() and "\\set grants_only 1" in out.getvalue()


@pytest.mark.parametrize( "other", [ "--reassign", "--rollback" ] )
def test_grants_only_with_another_direction_is_refused_before_anything_runs( sql_file, other ):
    run = Recorder()
    with pytest.raises( SystemExit ):
        db_roles.main( [ "--psql", "psql", "--sql", sql_file, "--grants-only", other, "--apply" ], run_fn=run, out=io.StringIO() )
    assert run.calls == []
