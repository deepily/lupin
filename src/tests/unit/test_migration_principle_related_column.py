"""
Migration f8c2d6a14e37: preference_principles.related_principle_id.

Runs the real upgrade() and downgrade() against in-memory SQLite through a minimal stand-in for alembic's op.
Each test names what it would catch:
  - a column added under another name or to another table       -> the column test
  - a column that is not a nullable key to preference_principles -> the shape test
  - the model and the revision disagreeing about the column      -> the model-agreement test
  - a re-run that adds the column twice                          -> the idempotence test
  - an upgrade that touches existing rows                        -> the untouched-rows test
  - a table-absent database                                      -> the no-op test
  - a revision that is off the single linear chain               -> the chain test
"""
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import PreferencePrinciple


_REVISION = "f8c2d6a14e37"
_TABLE    = "preference_principles"


class _FakeOp:
    """Minimal alembic op over a live connection; the added column becomes text."""

    def __init__( self, bind ):
        self._bind   = bind
        self.columns = []

    def get_bind( self ):
        return self._bind

    def add_column( self, table, column ):
        self.columns.append( column )
        self._bind.execute( sa.text( f"ALTER TABLE {table} ADD COLUMN {column.name} TEXT" ) )

    def drop_column( self, table, column_name ):
        self._bind.execute( sa.text( f"ALTER TABLE {table} DROP COLUMN {column_name}" ) )


def _script():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _load_module():
    spec   = importlib.util.spec_from_file_location( "mig_principle_related", _script().get_revision( _REVISION ).path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _engine():
    return sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )


@pytest.fixture
def engine():
    eng = _engine()
    with eng.begin() as conn:
        conn.execute( sa.text( f"CREATE TABLE {_TABLE} ( id TEXT PRIMARY KEY, statement TEXT NOT NULL )" ) )
        conn.execute( sa.text( f"INSERT INTO {_TABLE} ( id, statement ) VALUES ( 'p1', 's' )" ) )
    yield eng
    eng.dispose()


def _columns( engine ):
    return [ c[ "name" ] for c in sa.inspect( engine ).get_columns( _TABLE ) ]


def _run( engine, module, monkeypatch, verb ):
    with engine.begin() as conn:
        fake = _FakeOp( conn )
        monkeypatch.setattr( module, "op", fake, raising=True )
        getattr( module, verb )()
    return fake


def test_upgrade_adds_the_column_and_leaves_rows_untouched( monkeypatch, engine ):
    """The column appears on the principles table and the existing row reads NULL in it."""
    module = _load_module()
    assert "related_principle_id" not in _columns( engine )
    _run( engine, module, monkeypatch, "upgrade" )
    assert "related_principle_id" in _columns( engine )
    with engine.begin() as conn:
        assert tuple( conn.execute( sa.text( f"SELECT id, related_principle_id FROM {_TABLE}" ) ).one() ) == ( "p1", None )


def test_the_column_is_a_nullable_key_to_the_principles_table_and_matches_the_model( monkeypatch, engine ):
    """
    The revision's column is a nullable UUID key to the principles table.

    The model's column has the same name, type, nullability and target.
    """
    from sqlalchemy.dialects import postgresql
    module = _load_module()
    column = _run( engine, module, monkeypatch, "upgrade" ).columns[ 0 ]
    modeled = PreferencePrinciple.__table__.columns[ "related_principle_id" ]
    assert column.name == modeled.name == "related_principle_id"
    assert column.nullable is True and modeled.nullable is True
    assert isinstance( column.type, postgresql.UUID ) and isinstance( modeled.type, postgresql.UUID )
    assert { fk.target_fullname for fk in column.foreign_keys } == { fk.target_fullname for fk in modeled.foreign_keys } == { "preference_principles.id" }


def test_upgrade_is_idempotent_and_keeps_an_existing_column_and_its_data( monkeypatch, engine ):
    """A re-run adds nothing; a column that is already there keeps its values."""
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    with engine.begin() as conn:
        conn.execute( sa.text( f"UPDATE {_TABLE} SET related_principle_id = 'kept' WHERE id = 'p1'" ) )
    fake = _run( engine, module, monkeypatch, "upgrade" )
    assert fake.columns == [] and _columns( engine ).count( "related_principle_id" ) == 1
    with engine.begin() as conn:
        assert conn.execute( sa.text( f"SELECT related_principle_id FROM {_TABLE}" ) ).scalar_one() == "kept"


def test_downgrade_drops_the_column_and_is_safe_to_repeat( monkeypatch, engine ):
    """The downgrade removes the column, and a second downgrade is a no-op."""
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _run( engine, module, monkeypatch, "downgrade" )
    assert "related_principle_id" not in _columns( engine )
    _run( engine, module, monkeypatch, "downgrade" )


def test_both_verbs_are_no_ops_when_the_table_is_absent( monkeypatch ):
    """A database with no principles table is left empty by both verbs."""
    module = _load_module()
    eng    = _engine()
    try:
        _run( eng, module, monkeypatch, "upgrade" )
        _run( eng, module, monkeypatch, "downgrade" )
        assert sa.inspect( eng ).get_table_names() == []
    finally:
        eng.dispose()


def test_the_revision_follows_the_draft_at_reveal_revision_and_is_the_single_head():
    """The chain stays linear, with this revision right after e5b7d9a2c418."""
    script = _script()
    assert script.get_revision( _REVISION ).down_revision == "e5b7d9a2c418"
    heads = script.get_heads()
    assert len( heads ) == 1, f"the chain must stay linear, got heads {heads}"
    assert _REVISION in { r.revision for r in script.walk_revisions( base="base", head=heads[ 0 ] ) }
