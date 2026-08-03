"""
Unit tests for the bug-11cda843 migration
(f2a3b4c5d6e7_notif_response_requested_not_null) — the follow-on drift fix that
tightens notifications.response_requested to NOT NULL so a pure
`alembic upgrade head` DB matches the ORM (and every create_all-built deploy).

The migration's executable body is exercised against an in-memory SQLite DB
with a minimal `notifications` table, driving the alembic `op` proxy via a tiny
fake: `get_bind()` returns the live connection (so the backfill UPDATE really
runs and is asserted), and `alter_column()` is RECORDED (SQLite cannot
`ALTER COLUMN ... SET NOT NULL`, and the real DDL is proven empirically against
Postgres in src/tests/smoke/test_migration_notif_response_requested_not_null_roundtrip.py).
This split mirrors the e5f6a7b8c9d0 pattern (DB-free structural/exec guards here;
live-Postgres round-trip in the smoke bucket).

Venue: :7999-eligible (pure unit, in-memory SQLite, no server, no Postgres).
"""
import importlib.util

import pytest
import sqlalchemy as sa

from alembic.script import ScriptDirectory

from cosa.rest.db.auto_migrate import build_alembic_config


_REVISION       = "f2a3b4c5d6e7"
_DOWN_REVISION  = "e1f2a3b4c5d6"   # chains onto the drop-HNSW-exact-scan head


def _load_migration_module():
    """Load the revision script as a module straight from its on-disk path."""
    script = ScriptDirectory.from_config( build_alembic_config( database_url=None ) )
    path   = script.get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "mig_notif_response_requested_nn", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


class _FakeOp:
    """alembic-op stand-in: get_bind() drives the live conn; alter_column() is recorded."""

    def __init__( self, bind ):
        self._bind       = bind
        self.alter_calls = []

    def get_bind( self ):
        return self._bind

    def alter_column( self, table, column, **kwargs ):
        self.alter_calls.append( { "table": table, "column": column, **kwargs } )


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


def _create_notifications( conn ):
    """Create a minimal notifications table with a NULLABLE response_requested."""
    conn.execute( sa.text(
        "CREATE TABLE notifications ( id INTEGER PRIMARY KEY, response_requested BOOLEAN )"
    ) )


def _response_values( conn ):
    return [ row[ 0 ] for row in conn.execute(
        sa.text( "SELECT response_requested FROM notifications ORDER BY id" )
    ).fetchall() ]


def _run( module, conn, monkeypatch, fn ):
    """Run upgrade()/downgrade() with the alembic `op` proxy faked onto `conn`; returns the fake."""
    fake = _FakeOp( conn )
    monkeypatch.setattr( module, "op", fake )
    fn()
    return fake


# ---- structural contract ---------------------------------------------------

def test_revision_and_down_revision():
    """The migration declares the expected revision id and chains onto the alias head."""
    module = _load_migration_module()
    assert module.revision == _REVISION
    assert module.down_revision == _DOWN_REVISION


# ---- upgrade() -------------------------------------------------------------

def test_upgrade_backfills_nulls_and_tightens_to_not_null( sqlite_conn, monkeypatch ):
    module = _load_migration_module()
    _create_notifications( sqlite_conn )
    # A NULL row (legacy), a true row, and a false row — only the NULL must change.
    sqlite_conn.execute( sa.text( "INSERT INTO notifications ( id, response_requested ) VALUES ( 1, NULL )" ) )
    sqlite_conn.execute( sa.text( "INSERT INTO notifications ( id, response_requested ) VALUES ( 2, 1 )" ) )
    sqlite_conn.execute( sa.text( "INSERT INTO notifications ( id, response_requested ) VALUES ( 3, 0 )" ) )

    fake = _run( module, sqlite_conn, monkeypatch, module.upgrade )

    # Backfill ran: the NULL is now false(0); true/false rows untouched; no NULLs remain.
    assert _response_values( sqlite_conn ) == [ 0, 1, 0 ]
    null_count = sqlite_conn.execute(
        sa.text( "SELECT COUNT(*) FROM notifications WHERE response_requested IS NULL" )
    ).scalar()
    assert null_count == 0
    # The NOT NULL tighten was issued for exactly the right column.
    assert len( fake.alter_calls ) == 1
    call = fake.alter_calls[ 0 ]
    assert call[ "table" ]    == "notifications"
    assert call[ "column" ]   == "response_requested"
    assert call[ "nullable" ] is False


def test_upgrade_no_table_is_noop( sqlite_conn, monkeypatch ):
    """No notifications table -> inspector guard short-circuits: no raise, no alter."""
    module = _load_migration_module()
    fake   = _run( module, sqlite_conn, monkeypatch, module.upgrade )   # must not raise
    assert not sa.inspect( sqlite_conn ).has_table( "notifications" )
    assert fake.alter_calls == []   # guard returned BEFORE alter_column


def test_upgrade_is_idempotent_when_no_nulls( sqlite_conn, monkeypatch ):
    """A second upgrade over an already-tightened table changes no data."""
    module = _load_migration_module()
    _create_notifications( sqlite_conn )
    sqlite_conn.execute( sa.text( "INSERT INTO notifications ( id, response_requested ) VALUES ( 1, 0 ), ( 2, 1 )" ) )

    _run( module, sqlite_conn, monkeypatch, module.upgrade )
    first = _response_values( sqlite_conn )
    _run( module, sqlite_conn, monkeypatch, module.upgrade )   # zero NULLs -> no-op backfill
    second = _response_values( sqlite_conn )

    assert first == second == [ 0, 1 ]


# ---- downgrade() -----------------------------------------------------------

def test_downgrade_relaxes_back_to_nullable( sqlite_conn, monkeypatch ):
    """downgrade() issues a single alter_column relaxing the column to nullable=True."""
    module = _load_migration_module()
    fake   = _run( module, sqlite_conn, monkeypatch, module.downgrade )
    assert len( fake.alter_calls ) == 1
    call = fake.alter_calls[ 0 ]
    assert call[ "table" ]    == "notifications"
    assert call[ "column" ]   == "response_requested"
    assert call[ "nullable" ] is True
