"""
Unit tests for the bug-c6751cf8 data migration
(f6a7b8c9d0e1_canonicalize_task_project_aliases) — the one-time re-stamp of
task_items.project from raw alias keys to their canonical short names.

These execute the migration's upgrade()/downgrade() bodies against an in-memory
SQLite DB with a minimal `task_items` table, driving the alembic `op` proxy via
a tiny fake that returns the live connection from get_bind(). DB-light, no
Postgres — the migration's DML (`UPDATE ... WHERE project = :raw`) and the
inspector `has_table` guard are dialect-portable, so SQLite exercises both the
re-stamp loop and the no-table early-return branch at 100%.

The alias pairs are sourced from the SAME `_PROJECT_ALIASES` table the migration
imports — never duplicated here (single source of the map, bug c6751cf8).

Venue: :7999-eligible (pure unit, in-memory SQLite, no server, no Postgres).
"""

import importlib.util

import pytest
import sqlalchemy as sa

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.agents.utils.sender_id import _PROJECT_ALIASES
from alembic.script import ScriptDirectory


_REVISION = "f6a7b8c9d0e1"


def _load_migration_module():
    """Load the revision script as a module straight from its on-disk path."""
    script = ScriptDirectory.from_config( build_alembic_config( database_url=None ) )
    path   = script.get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "mig_canonicalize_project", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


class _FakeOp:
    """Minimal alembic-op stand-in: only get_bind() is exercised by the migration."""

    def __init__( self, bind ):
        self._bind = bind

    def get_bind( self ):
        return self._bind


@pytest.fixture
def sqlite_conn():
    """A live in-memory SQLite connection inside a transaction (rolled back at teardown)."""
    engine = sa.create_engine( "sqlite://" )
    conn   = engine.connect()
    trans  = conn.begin()
    try:
        yield conn
    finally:
        trans.rollback()
        conn.close()
        engine.dispose()


def _create_task_items( conn ):
    """Create a minimal task_items table (just the column the migration touches)."""
    conn.execute( sa.text( "CREATE TABLE task_items ( id INTEGER PRIMARY KEY, project TEXT )" ) )


def _projects( conn ):
    return [ row[ 0 ] for row in conn.execute( sa.text( "SELECT project FROM task_items ORDER BY id" ) ).fetchall() ]


def _run( module, conn, monkeypatch, fn ):
    """Run upgrade()/downgrade() with the alembic `op` proxy faked onto `conn`."""
    monkeypatch.setattr( module, "op", _FakeOp( conn ) )
    fn()


def test_upgrade_restamps_aliased_rows( sqlite_conn, monkeypatch ):
    module = _load_migration_module()
    _create_task_items( sqlite_conn )
    # One raw-alias row per alias key, plus a canonical row and a non-aliased row
    # that must BOTH survive untouched.
    raw_keys = list( _PROJECT_ALIASES.keys() )
    seed     = raw_keys + [ "plan", "lupin" ]
    for project in seed:
        sqlite_conn.execute( sa.text( "INSERT INTO task_items ( project ) VALUES ( :p )" ), { "p": project } )

    _run( module, sqlite_conn, monkeypatch, module.upgrade )

    after = _projects( sqlite_conn )
    # Every raw key is now its canonical value; "plan"/"lupin" unchanged.
    expected = [ _PROJECT_ALIASES[ k ] for k in raw_keys ] + [ "plan", "lupin" ]
    assert after == expected
    # No raw alias key survives.
    for raw in raw_keys:
        assert raw not in after


def test_upgrade_is_idempotent( sqlite_conn, monkeypatch ):
    module = _load_migration_module()
    _create_task_items( sqlite_conn )
    sqlite_conn.execute( sa.text( "INSERT INTO task_items ( project ) VALUES ( 'planning-is-prompting' )" ) )

    _run( module, sqlite_conn, monkeypatch, module.upgrade )
    first = _projects( sqlite_conn )
    _run( module, sqlite_conn, monkeypatch, module.upgrade )   # second run: 0 rows to change
    second = _projects( sqlite_conn )

    assert first == second == [ "plan" ]


def test_upgrade_no_table_is_noop( sqlite_conn, monkeypatch ):
    # No task_items table at all -> the has_table guard short-circuits, no raise.
    module = _load_migration_module()
    _run( module, sqlite_conn, monkeypatch, module.upgrade )   # must not raise
    assert not sa.inspect( sqlite_conn ).has_table( "task_items" )


def test_downgrade_is_noop( sqlite_conn, monkeypatch ):
    # Lossy reverse -> deliberate no-op: canonical rows are left exactly as-is.
    module = _load_migration_module()
    _create_task_items( sqlite_conn )
    sqlite_conn.execute( sa.text( "INSERT INTO task_items ( project ) VALUES ( 'plan' ), ( 'lupin' )" ) )

    _run( module, sqlite_conn, monkeypatch, module.downgrade )

    assert _projects( sqlite_conn ) == [ "plan", "lupin" ]
