"""
Migration c4d8e1a6b392: proxy_decisions.rule_agreement.

Runs the real upgrade() and downgrade() against in-memory SQLite through a minimal stand-in for alembic's op.
Each test names what it would catch:
  - a column added under another name or to another table       -> the column test
  - a re-run that adds the column twice                          -> the idempotence test
  - an upgrade that touches existing rows                        -> the untouched-rows test
  - a table-absent database                                      -> the no-op test
  - a revision that is off the single linear chain               -> the chain test
  - a model column that disagrees with the migration             -> the model test
"""
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import ProxyDecision


_REVISION = "c4d8e1a6b392"
_PARENT   = "7a3e9c5d1b28"


class _FakeOp:
    def __init__( self, bind ): self._bind = bind
    def get_bind( self ):       return self._bind
    def add_column( self, table, column ):
        self._bind.execute( sa.text( f"ALTER TABLE {table} ADD COLUMN {column.name} BOOLEAN" ) )
    def drop_column( self, table, column_name ):
        self._bind.execute( sa.text( f"ALTER TABLE {table} DROP COLUMN {column_name}" ) )


def _script():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _load_module():
    spec   = importlib.util.spec_from_file_location( "mig_rule_agreement", _script().get_revision( _REVISION ).path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _engine():
    return sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )


@pytest.fixture
def engine():
    eng = _engine()
    with eng.begin() as conn:
        conn.execute( sa.text( "CREATE TABLE proxy_decisions ( id TEXT PRIMARY KEY, action TEXT NOT NULL )" ) )
        conn.execute( sa.text( "INSERT INTO proxy_decisions ( id, action ) VALUES ( 'r1', 'shadow' )" ) )
    yield eng
    eng.dispose()


def _columns( engine ):
    return [ c[ "name" ] for c in sa.inspect( engine ).get_columns( "proxy_decisions" ) ]


def _run( engine, module, monkeypatch, verb ):
    with engine.begin() as conn:
        monkeypatch.setattr( module, "op", _FakeOp( conn ), raising=True )
        getattr( module, verb )()


def test_upgrade_adds_the_column_and_leaves_rows_untouched( monkeypatch, engine ):
    module = _load_module()
    assert "rule_agreement" not in _columns( engine )
    _run( engine, module, monkeypatch, "upgrade" )
    assert "rule_agreement" in _columns( engine )
    with engine.begin() as conn:
        row = conn.execute( sa.text( "SELECT id, action, rule_agreement FROM proxy_decisions" ) ).one()
    assert tuple( row ) == ( "r1", "shadow", None )


def test_upgrade_checks_for_the_column_first_and_is_idempotent( monkeypatch, engine ):
    module = _load_module()
    with engine.begin() as conn:
        conn.execute( sa.text( "ALTER TABLE proxy_decisions ADD COLUMN rule_agreement BOOLEAN" ) )
    _run( engine, module, monkeypatch, "upgrade" )
    _run( engine, module, monkeypatch, "upgrade" )
    assert _columns( engine ).count( "rule_agreement" ) == 1


def test_downgrade_drops_the_column_and_is_safe_to_repeat( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _run( engine, module, monkeypatch, "downgrade" )
    assert "rule_agreement" not in _columns( engine )
    _run( engine, module, monkeypatch, "downgrade" )


def test_both_verbs_are_no_ops_when_the_table_is_absent( monkeypatch ):
    module = _load_module()
    eng    = _engine()
    try:
        _run( eng, module, monkeypatch, "upgrade" )
        _run( eng, module, monkeypatch, "downgrade" )
        assert sa.inspect( eng ).get_table_names() == []
    finally:
        eng.dispose()


def test_the_revision_follows_the_field_forecasts_revision_and_lies_on_the_single_head_chain():
    script = _script()
    assert script.get_revision( _REVISION ).down_revision == _PARENT
    heads = script.get_heads()
    assert len( heads ) == 1, f"the chain must stay linear, got heads {heads}"
    assert _REVISION in { r.revision for r in script.walk_revisions( base="base", head=heads[ 0 ] ) }


def test_the_model_column_is_a_nullable_boolean_with_no_default():
    column = ProxyDecision.__table__.c.rule_agreement
    assert isinstance( column.type, sa.Boolean )
    assert column.nullable is True
    assert column.default is None and column.server_default is None
