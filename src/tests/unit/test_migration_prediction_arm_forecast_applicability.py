"""
Migration b3f7d1a94e62: the nullable applicability column, up then down.

Runs the real upgrade() and downgrade() against in-memory SQLite through a minimal stand-in for alembic's op.
Each test names what it would catch:
  - a column added under another name, or not nullable           -> the shape test
  - a column of another type than the model declares              -> the shape test
  - an upgrade that touches existing rows                         -> the untouched-rows test
  - up then down that does not restore the table                  -> the round-trip test
  - a re-run that adds twice or loses data                        -> the idempotence test
  - a table-absent database                                       -> the no-op test
  - a revision that is off the single linear chain                -> the chain test
"""
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import PredictionArmForecast

_REVISION = "b3f7d1a94e62"
_PARENT   = "a9d4e7b2c615"


class _FakeOp:
    """Minimal alembic op over a live connection; an added column becomes text."""

    def __init__( self, bind ):
        self._bind   = bind
        self.columns = []

    def get_bind( self ):
        return self._bind

    def add_column( self, table, column ):
        self.columns.append( ( table, column ) )
        self._bind.execute( sa.text( f"ALTER TABLE {table} ADD COLUMN {column.name} TEXT" ) )

    def drop_column( self, table, column_name ):
        self._bind.execute( sa.text( f"ALTER TABLE {table} DROP COLUMN {column_name}" ) )


def _script():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _load_module():
    spec   = importlib.util.spec_from_file_location( "mig_arm_applicability", _script().get_revision( _REVISION ).path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def engine():
    eng = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    with eng.begin() as conn:
        conn.execute( sa.text( "CREATE TABLE prediction_arm_forecast ( id TEXT PRIMARY KEY, arm TEXT NOT NULL )" ) )
        conn.execute( sa.text( "INSERT INTO prediction_arm_forecast ( id, arm ) VALUES ( 'r1', 'B1' )" ) )
    yield eng
    eng.dispose()


def _columns( engine ):
    return [ c[ "name" ] for c in sa.inspect( engine ).get_columns( "prediction_arm_forecast" ) ]


def _run( engine, module, monkeypatch, verb ):
    with engine.begin() as conn:
        fake = _FakeOp( conn )
        monkeypatch.setattr( module, "op", fake, raising=True )
        getattr( module, verb )()
    return fake


def test_upgrade_adds_one_nullable_column_of_the_models_type_and_leaves_rows_untouched( monkeypatch, engine ):
    """The column lands once, nullable, typed as the model's, with the old row reading NULL."""
    module  = _load_module()
    fake    = _run( engine, module, monkeypatch, "upgrade" )
    assert [ ( t, c.name ) for t, c in fake.columns ] == [ ( "prediction_arm_forecast", "applicability" ) ]
    added   = fake.columns[ 0 ][ 1 ]
    modeled = PredictionArmForecast.__table__.columns[ "applicability" ]
    assert added.nullable is True and modeled.nullable is True and type( added.type ) is type( modeled.type )
    with engine.begin() as conn:
        row = conn.execute( sa.text( "SELECT id, arm, applicability FROM prediction_arm_forecast" ) ).one()
    assert tuple( row ) == ( "r1", "B1", None )


def test_up_then_down_restores_the_table_and_a_second_down_is_a_no_op( monkeypatch, engine ):
    """Up then down restores the columns and keeps the row; a second down changes nothing."""
    module = _load_module()
    before = _columns( engine )
    _run( engine, module, monkeypatch, "upgrade" )
    assert _columns( engine ) == before + [ "applicability" ]
    _run( engine, module, monkeypatch, "downgrade" )
    assert _columns( engine ) == before
    _run( engine, module, monkeypatch, "downgrade" )
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT arm FROM prediction_arm_forecast" ) ).scalar_one() == "B1"


def test_upgrade_is_idempotent_and_keeps_existing_data( monkeypatch, engine ):
    """A re-run adds nothing, and a value already in the column survives."""
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    with engine.begin() as conn:
        conn.execute( sa.text( "UPDATE prediction_arm_forecast SET applicability = 'kept'" ) )
    assert _run( engine, module, monkeypatch, "upgrade" ).columns == []
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT applicability FROM prediction_arm_forecast" ) ).scalar_one() == "kept"


def test_both_verbs_are_no_ops_when_the_table_is_absent( monkeypatch ):
    """A database without the arm table is left empty by both verbs."""
    module = _load_module()
    eng    = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    try:
        assert _run( eng, module, monkeypatch, "upgrade" ).columns == []
        _run( eng, module, monkeypatch, "downgrade" )
        assert sa.inspect( eng ).get_table_names() == []
    finally:
        eng.dispose()


def test_the_revision_follows_the_evidence_columns_and_is_the_single_head():
    """The chain stays linear: this revision follows the evidence-columns one and is the head."""
    script = _script()
    assert script.get_revision( _REVISION ).down_revision == _PARENT
    assert script.get_heads() == [ _REVISION ]
