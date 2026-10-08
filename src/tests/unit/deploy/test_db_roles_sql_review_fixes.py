"""
Review fixes to 793eb070f, part 2 (row 80513825): the role SQL and the revoke migration.

The behaviour itself (no password in the server log under log_statement='ddl'; the host role
keeps no write right after approval_settings is re-created) was measured against a throwaway
Postgres 16 and is quoted in the commit message. A unit test cannot run Postgres, so these
pin the text the measurement depended on, and run the migration's upgrade() against a recorder.
"""
import importlib.util
import os

import pytest

ROOT     = os.environ[ "LUPIN_ROOT" ]
SQL_PATH = os.path.join( ROOT, "src/scripts/sql/init-db-roles.sql" )
MIG_PATH = os.path.join( ROOT, "src/migrations/versions/b80513825c02_revoke_host_writes_on_approval_settings.py" )

QUIET = ( "SET log_statement = 'none';", "SET log_min_error_statement = 'panic';", "SET log_min_duration_statement = -1;" )


def _sql():
    with open( SQL_PATH ) as handle: return handle.read()


def _migration():
    spec   = importlib.util.spec_from_file_location( "_mig_b80513825c02", MIG_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def test_the_log_quieting_statements_come_before_the_first_password_is_used():
    sql   = _sql()
    first = sql.index( ":'app_pw'" )
    for statement in QUIET:
        assert sql.index( statement ) < first, statement


@pytest.mark.parametrize( "database", [ "lupin_db_dev", "lupin_db_test" ] )
def test_every_connect_is_followed_by_the_quieting_statements(database):
    sql  = _sql()
    tail = sql[ sql.index( f"\\connect {database}\n" ) + len( f"\\connect {database}\n" ): ]
    head = tail[ :len( "".join( QUIET ) ) + 10 ]
    for statement in QUIET:
        assert statement in head, f"{statement} missing right after \\connect {database}"


def test_the_test_database_is_checked_before_any_role_is_created():
    sql = _sql()
    assert 0 < sql.index( "datname = 'lupin_db_test'" ) < sql.index( "format( 'CREATE ROLE" )
    assert "database lupin_db_test does not exist" in sql


def test_the_migration_chains_after_the_approval_settings_revision():
    module = _migration()
    assert module.down_revision == "a80513825b01"
    assert module.revision == "b80513825c02"


class _Result:
    def __init__( self, value ): self._value = value
    def scalar( self ): return self._value


class _Connection:
    """Answers the two queries upgrade() makes: still-writable, then current_user."""
    def __init__( self, writable ): self.writable, self.asked = writable, []
    def execute( self, statement ):
        self.asked.append( str( statement ) )
        return _Result( self.writable if "has_table_privilege" in str( statement ) else "lupin_app" )


def _run( monkeypatch, writable ):
    module, executed, connection = _migration(), [], _Connection( writable )
    monkeypatch.setattr( module.op, "execute", executed.append, raising=False )
    monkeypatch.setattr( module.op, "get_bind", lambda: connection, raising=False )
    return module, executed, connection


def test_upgrade_issues_one_guarded_revoke_that_leaves_select_alone_and_swallows_no_privilege(monkeypatch):
    module, executed, _ = _run( monkeypatch, False )
    module.upgrade()
    assert len( executed ) == 1
    statement = executed[ 0 ]
    assert "rolname = 'lupin_host'" in statement
    assert "to_regclass( 'public.approval_settings' ) IS NOT NULL" in statement
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.approval_settings FROM lupin_host" in statement
    assert "EXCEPTION WHEN insufficient_privilege" in statement
    assert "SELECT ON" not in statement and "RAISE" not in statement


def test_no_warning_when_the_host_role_cannot_write_afterwards(monkeypatch, caplog):
    module, _, connection = _run( monkeypatch, False )
    with caplog.at_level( "WARNING", logger="alembic.runtime.migration" ):
        module.upgrade()
    assert caplog.records == []
    assert len( connection.asked ) == 1


def test_one_warning_through_alembics_logger_when_the_host_role_can_still_write(monkeypatch, caplog):
    module, _, _ = _run( monkeypatch, True )
    with caplog.at_level( "WARNING", logger="alembic.runtime.migration" ):
        module.upgrade()
    assert len( caplog.records ) == 1
    record = caplog.records[ 0 ]
    assert record.name == "alembic.runtime.migration" and record.levelname == "WARNING"
    message = record.getMessage()
    assert "lupin_host" in message and "approval_settings" in message
    assert "lupin_app" in message and "Remedy" in message


def test_the_still_writable_check_is_false_without_the_role_or_the_table():
    module = _migration()
    check  = module._STILL_WRITABLE_SQL
    assert check.index( "pg_roles" ) < check.index( "to_regclass" ) < check.index( "has_table_privilege" )
    for right in ( "INSERT", "UPDATE", "DELETE" ):
        assert f"'{right}' )" in check


def test_downgrade_restores_nothing():
    assert _migration().downgrade() is None


# ---- CREATEDB: lupin_test only (row 80513825, the .env step) --------------------------------------
def _code_lines():
    """The SQL's non-comment lines, stripped; lines because psql meta-commands have no semicolon."""
    return [ line.strip() for line in _sql().splitlines() if line.strip() and not line.strip().startswith( "--" ) ]


def _grants_createdb( line ):
    return "CREATEDB" in line.replace( "NOCREATEDB", "" )


def test_lupin_test_alone_is_given_createdb():
    lines = _code_lines()
    assert lines.count( "ALTER ROLE lupin_test CREATEDB;" ) == 1
    assert [ line for line in lines if _grants_createdb( line ) ] == [ "ALTER ROLE lupin_test CREATEDB;" ]


def test_every_role_is_still_created_without_createdb_so_only_the_alter_grants_it():
    create = [ line for line in _code_lines() if "CREATE ROLE" in line ]
    assert len( create ) == 1 and "NOCREATEDB" in create[ 0 ]


@pytest.mark.parametrize( "role", [ "lupin_app", "lupin_host" ] )
def test_the_app_and_host_roles_are_never_given_createdb(role):
    assert not [ line for line in _code_lines() if role in line and _grants_createdb( line ) ]


def test_the_createdb_alter_comes_after_the_statement_that_creates_the_role():
    lines = _code_lines()
    assert lines.index( "ALTER ROLE lupin_test CREATEDB;" ) > next( i for i, line in enumerate( lines ) if "CREATE ROLE" in line )
