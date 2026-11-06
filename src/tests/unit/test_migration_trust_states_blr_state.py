"""
Migration a7c3e91b5d20 — trust_states.blr_state.

Runs the real upgrade() and downgrade() against an in-memory SQLite database through a
minimal stand-in for alembic's `op`. Each test names what it would catch:
  - a column added to the wrong table or under another name        -> the column check
  - a re-run that adds the column twice                             -> the idempotence test
  - an upgrade that touches existing rows                           -> the untouched-rows test
  - a table-absent database (fresh DB built from metadata)          -> the no-op tests
  - a revision that is not the single head after 5efa1547bd37       -> the chain test
"""
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config


_REVISION = "a7c3e91b5d20"

_DDL_PRE = """
CREATE TABLE trust_states (
    id                    TEXT PRIMARY KEY,
    user_email            TEXT NOT NULL,
    category              TEXT NOT NULL,
    total_decisions       INTEGER NOT NULL DEFAULT 0,
    circuit_breaker_state TEXT
)
"""


class _FakeOp:
    """Minimal alembic `op` over a live connection: get_bind, add_column, drop_column."""

    def __init__( self, bind ):
        self._bind = bind

    def get_bind( self ):
        return self._bind

    def add_column( self, table, column ):
        self._bind.execute( sa.text( f"ALTER TABLE {table} ADD COLUMN {column.name} TEXT" ) )

    def drop_column( self, table, column_name ):
        self._bind.execute( sa.text( f"ALTER TABLE {table} DROP COLUMN {column_name}" ) )


def _script():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _load_module():
    path   = _script().get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "mig_blr_state", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def engine():
    eng = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    with eng.begin() as conn:
        conn.execute( sa.text( _DDL_PRE ) )
        conn.execute( sa.text( "INSERT INTO trust_states ( id, user_email, category, total_decisions ) VALUES ( 'a', 'u@x', 'testing', 7 )" ) )
    yield eng
    eng.dispose()


def _columns( engine ):
    return [ c[ "name" ] for c in sa.inspect( engine ).get_columns( "trust_states" ) ]


def _run( engine, module, monkeypatch, verb ):
    with engine.begin() as conn:
        monkeypatch.setattr( module, "op", _FakeOp( conn ), raising=True )
        getattr( module, verb )()


def test_upgrade_adds_the_column_to_trust_states_and_leaves_existing_rows_untouched( monkeypatch, engine ):
    module = _load_module()
    assert "blr_state" not in _columns( engine )
    _run( engine, module, monkeypatch, "upgrade" )
    assert "blr_state" in _columns( engine )
    with engine.begin() as conn:
        row = conn.execute( sa.text( "SELECT total_decisions, blr_state FROM trust_states" ) ).one()
    assert tuple( row ) == ( 7, None ), "no backfill: a row of unknown history stays NULL"


def test_upgrade_is_idempotent( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _run( engine, module, monkeypatch, "upgrade" )          # a second add would raise "duplicate column"
    assert _columns( engine ).count( "blr_state" ) == 1


def test_downgrade_drops_the_column_and_is_safe_to_repeat( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _run( engine, module, monkeypatch, "downgrade" )
    assert "blr_state" not in _columns( engine )
    _run( engine, module, monkeypatch, "downgrade" )        # column already gone: no error


def test_both_verbs_are_no_ops_when_trust_states_is_absent( monkeypatch ):
    module = _load_module()
    eng    = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    try:
        _run( eng, module, monkeypatch, "upgrade" )
        _run( eng, module, monkeypatch, "downgrade" )
        assert sa.inspect( eng ).get_table_names() == []
    finally:
        eng.dispose()


def test_the_revision_follows_5efa1547bd37_and_is_the_only_head():
    script = _script()
    assert script.get_revision( _REVISION ).down_revision == "5efa1547bd37"
    assert script.get_heads() == [ _REVISION ]
