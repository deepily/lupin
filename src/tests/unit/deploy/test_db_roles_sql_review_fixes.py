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


def test_upgrade_issues_one_guarded_revoke_that_leaves_select_alone(monkeypatch):
    module = _migration()
    seen   = []
    monkeypatch.setattr( module.op, "execute", seen.append, raising=False )
    module.upgrade()
    assert len( seen ) == 1
    statement = seen[ 0 ]
    assert "pg_roles" in statement and "rolname = 'lupin_host'" in statement
    assert "to_regclass( 'public.approval_settings' ) IS NOT NULL" in statement
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.approval_settings FROM lupin_host" in statement
    assert "SELECT ON" not in statement


def test_downgrade_restores_nothing():
    assert _migration().downgrade() is None
