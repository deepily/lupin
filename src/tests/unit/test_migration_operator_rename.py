"""
Unit coverage for the gate_class `ricks_court` -> `operator` data migration
(revision b8c9d0e1f2a3, Lane A0 of the proactive-manager mechanism).

The full-stack drift round-trip smoke test targets a FIXED earlier revision
(_DRIFT_REVISION), so it never exercises THIS migration's upgrade()/downgrade()
DDL. These tests do — against an in-memory SQLite bind — covering both the
table-present execute path AND the table-absent early-return guard, so the
migration module reaches 100% line + branch coverage without a live Postgres.

The migration is loaded by file path (alembic version files are not an
importable package) and its module-level `op` proxy's `get_bind` is patched to
return the test connection — the same seam alembic populates at real upgrade
time.
"""
import importlib.util
import os

import pytest
from sqlalchemy import create_engine, inspect, text


_MIGRATION_PATH = os.path.join(
    os.path.dirname( __file__ ), "..", "..",
    "migrations", "versions",
    "b8c9d0e1f2a3_rename_gate_class_ricks_court_to_operator.py",
)


def _load_migration():
    """Import the migration module by file path (versions/ is not a package)."""
    spec   = importlib.util.spec_from_file_location( "_mig_operator_rename", _MIGRATION_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def conn():
    """A single in-memory SQLite connection (one connection == one DB)."""
    engine     = create_engine( "sqlite://" )
    connection = engine.connect()
    yield connection
    connection.close()


def _make_task_items( connection ):
    """Create a minimal task_items table with the gate_class column + seed rows."""
    connection.execute( text(
        "CREATE TABLE task_items ( id TEXT PRIMARY KEY, gate_class TEXT NOT NULL )"
    ) )
    connection.execute( text(
        "INSERT INTO task_items ( id, gate_class ) VALUES "
        "( 'a', 'ricks_court' ), ( 'b', 'ricks_court' ), "
        "( 'c', 'none' ), ( 'd', 'manager' )"
    ) )
    connection.commit()


def _gate_classes( connection ):
    rows = connection.execute( text( "SELECT id, gate_class FROM task_items ORDER BY id" ) ).all()
    return { r[ 0 ]: r[ 1 ] for r in rows }


def test_upgrade_renames_ricks_court_rows_only( conn, monkeypatch ):
    # AC-A0.2 back-catalogue heal: only the retired value flips; siblings untouched.
    _make_task_items( conn )
    module = _load_migration()
    monkeypatch.setattr( module.op, "get_bind", lambda: conn )

    module.upgrade()
    conn.commit()

    assert _gate_classes( conn ) == { "a": "operator", "b": "operator", "c": "none", "d": "manager" }


def test_upgrade_is_idempotent( conn, monkeypatch ):
    # A re-run updates zero rows (no remaining ricks_court) — safe to re-apply.
    _make_task_items( conn )
    module = _load_migration()
    monkeypatch.setattr( module.op, "get_bind", lambda: conn )

    module.upgrade()
    conn.commit()
    module.upgrade()
    conn.commit()

    assert _gate_classes( conn ) == { "a": "operator", "b": "operator", "c": "none", "d": "manager" }


def test_downgrade_reverses_operator_rows_only( conn, monkeypatch ):
    # Faithful inverse: every operator gate restored to ricks_court; siblings untouched.
    _make_task_items( conn )
    module = _load_migration()
    monkeypatch.setattr( module.op, "get_bind", lambda: conn )

    module.upgrade()
    conn.commit()
    module.downgrade()
    conn.commit()

    assert _gate_classes( conn ) == { "a": "ricks_court", "b": "ricks_court", "c": "none", "d": "manager" }


def test_upgrade_noop_when_task_items_absent( conn, monkeypatch ):
    # Guard branch: a DB without task_items (stamp-before-task-store) → early return.
    module = _load_migration()
    monkeypatch.setattr( module.op, "get_bind", lambda: conn )

    assert not inspect( conn ).has_table( "task_items" )
    module.upgrade()    # must not raise
    assert not inspect( conn ).has_table( "task_items" )


def test_downgrade_noop_when_task_items_absent( conn, monkeypatch ):
    # Guard branch (downgrade twin): no table → early return, no raise.
    module = _load_migration()
    monkeypatch.setattr( module.op, "get_bind", lambda: conn )

    module.downgrade()  # must not raise
    assert not inspect( conn ).has_table( "task_items" )
