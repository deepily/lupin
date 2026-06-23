"""
Unit coverage for the task_items.urgency add-column migration (revision
c9d0e1f2a3b4, Lane A2 of the proactive-manager mechanism).

The full-stack drift round-trip smoke test targets a FIXED earlier revision, so
it never exercises THIS migration's upgrade()/downgrade() DDL. These tests do —
against an in-memory SQLite bind driven through alembic's Operations context —
covering the add-column + index path, the idempotent re-run, the downgrade, AND
the table-absent guard, so the migration module reaches full line + branch
coverage without a live Postgres.

The migration is loaded by file path (alembic version files are not an importable
package) and its module-level `op` proxy is replaced with an Operations bound to
the test connection — the same seam alembic populates at real migration time.
"""
import importlib.util
import os

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


_MIGRATION_PATH = os.path.join(
    os.path.dirname( __file__ ), "..", "..",
    "migrations", "versions",
    "c9d0e1f2a3b4_add_task_urgency_column.py",
)


def _load_migration():
    spec   = importlib.util.spec_from_file_location( "_mig_add_urgency", _MIGRATION_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def conn():
    engine     = create_engine( "sqlite://" )
    connection = engine.connect()
    yield connection
    connection.close()


def _bind_ops( module, connection, monkeypatch ):
    """Install an alembic Operations bound to `connection` as the module's op proxy."""
    ctx = MigrationContext.configure( connection )
    monkeypatch.setattr( module, "op", Operations( ctx ) )


def _make_task_items( connection ):
    connection.execute( text( "CREATE TABLE task_items ( id TEXT PRIMARY KEY )" ) )
    connection.commit()


def _columns( connection ):
    return { c[ "name" ] for c in inspect( connection ).get_columns( "task_items" ) }


def _indexes( connection ):
    return { ix[ "name" ] for ix in inspect( connection ).get_indexes( "task_items" ) }


def test_upgrade_adds_urgency_column_and_index( conn, monkeypatch ):
    _make_task_items( conn )
    module = _load_migration()
    _bind_ops( module, conn, monkeypatch )

    module.upgrade()

    assert "urgency" in _columns( conn )
    assert "ix_task_items_urgency" in _indexes( conn )
    # server_default 'normal' backfills: a row inserted without urgency reads 'normal'
    conn.execute( text( "INSERT INTO task_items ( id ) VALUES ( 'a' )" ) )
    row = conn.execute( text( "SELECT urgency FROM task_items WHERE id='a'" ) ).scalar()
    assert row == "normal"


def test_upgrade_is_idempotent( conn, monkeypatch ):
    _make_task_items( conn )
    module = _load_migration()
    _bind_ops( module, conn, monkeypatch )

    module.upgrade()
    module.upgrade()   # column + index already exist → no-op, must not raise

    assert "urgency" in _columns( conn ) and "ix_task_items_urgency" in _indexes( conn )


def test_downgrade_drops_urgency_column_and_index( conn, monkeypatch ):
    _make_task_items( conn )
    module = _load_migration()
    _bind_ops( module, conn, monkeypatch )

    module.upgrade()
    module.downgrade()

    assert "urgency" not in _columns( conn )
    assert "ix_task_items_urgency" not in _indexes( conn )


def test_upgrade_noop_when_task_items_absent( conn, monkeypatch ):
    module = _load_migration()
    _bind_ops( module, conn, monkeypatch )

    assert not inspect( conn ).has_table( "task_items" )
    module.upgrade()   # guard branch — early return, no raise
    assert not inspect( conn ).has_table( "task_items" )


def test_downgrade_noop_when_task_items_absent( conn, monkeypatch ):
    module = _load_migration()
    _bind_ops( module, conn, monkeypatch )

    module.downgrade()   # guard branch twin — early return, no raise
    assert not inspect( conn ).has_table( "task_items" )
