"""
Migration a9d4e7b2c615: six nullable evidence columns, up then down.

Runs the real upgrade() and downgrade() against in-memory SQLite through a minimal stand-in for alembic's op.
Each test names what it would catch:
  - a column added under another name, or left out              -> the column-set test
  - a column that is not the nullable type the model declares   -> the shape test
  - an upgrade that touches existing rows                       -> the untouched-rows test
  - up then down that does not restore the table                -> the round-trip test
  - a re-run that adds twice or loses data                      -> the idempotence test
  - a half-applied upgrade that is not finished                 -> the half-applied test
  - a table-absent database                                     -> the no-op test
  - a revision that is off the single linear chain              -> the chain test
"""
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import PreferenceEvidence

_REVISION = "a9d4e7b2c615"
_NAMES    = ( "source_key", "condition_key", "caveat", "decision_stage", "antecedent", "standing_quote" )


class _FakeOp:
    """Minimal alembic op over a live connection; added columns become text."""

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
    spec   = importlib.util.spec_from_file_location( "mig_evidence_keys", _script().get_revision( _REVISION ).path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _engine():
    return sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )


@pytest.fixture
def engine():
    eng = _engine()
    with eng.begin() as conn:
        conn.execute( sa.text( "CREATE TABLE preference_evidence ( id TEXT PRIMARY KEY, relation TEXT NOT NULL )" ) )
        conn.execute( sa.text( "INSERT INTO preference_evidence ( id, relation ) VALUES ( 'e1', 'supports' )" ) )
    yield eng
    eng.dispose()


def _columns( engine ):
    return [ c[ "name" ] for c in sa.inspect( engine ).get_columns( "preference_evidence" ) ]


def _run( engine, module, monkeypatch, verb ):
    with engine.begin() as conn:
        fake = _FakeOp( conn )
        monkeypatch.setattr( module, "op", fake, raising=True )
        getattr( module, verb )()
    return fake


def test_upgrade_adds_exactly_the_six_columns_and_leaves_rows_untouched( monkeypatch, engine ):
    """The six names land on the evidence table, and the existing row reads NULL in each."""
    module = _load_module()
    fake   = _run( engine, module, monkeypatch, "upgrade" )
    assert [ ( t, c.name ) for t, c in fake.columns ] == [ ( "preference_evidence", n ) for n in _NAMES ]
    with engine.begin() as conn:
        row = conn.execute( sa.text( f"SELECT id, relation, {', '.join( _NAMES )} FROM preference_evidence" ) ).one()
    assert tuple( row ) == ( "e1", "supports" ) + ( None, ) * 6


def test_the_columns_are_nullable_and_match_the_models( monkeypatch, engine ):
    """Each column has the model's nullability, type and string length."""
    module = _load_module()
    added  = { c.name: c for _, c in _run( engine, module, monkeypatch, "upgrade" ).columns }
    for name in _NAMES:
        modeled = PreferenceEvidence.__table__.columns[ name ]
        assert added[ name ].nullable is True and modeled.nullable is True
        assert type( added[ name ].type ) is type( modeled.type )
        assert getattr( added[ name ].type, "length", None ) == getattr( modeled.type, "length", None )
    assert added[ "source_key" ].type.length == 255 and added[ "decision_stage" ].type.length == 100


def test_up_then_down_restores_the_table_and_a_second_down_is_a_no_op( monkeypatch, engine ):
    """Up then down restores the columns and keeps the row; a second down changes nothing."""
    module = _load_module()
    before = _columns( engine )
    _run( engine, module, monkeypatch, "upgrade" )
    assert _columns( engine ) == before + list( _NAMES )
    _run( engine, module, monkeypatch, "downgrade" )
    assert _columns( engine ) == before
    _run( engine, module, monkeypatch, "downgrade" )
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT relation FROM preference_evidence" ) ).scalar_one() == "supports"


def test_upgrade_is_idempotent_and_keeps_existing_data( monkeypatch, engine ):
    """A re-run adds nothing, and a value already in a column survives."""
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    with engine.begin() as conn:
        conn.execute( sa.text( "UPDATE preference_evidence SET source_key = 'kept'" ) )
    assert _run( engine, module, monkeypatch, "upgrade" ).columns == []
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT source_key FROM preference_evidence" ) ).scalar_one() == "kept"


def test_a_half_applied_upgrade_is_finished( monkeypatch, engine ):
    """With two columns already present the upgrade adds only the other four."""
    module = _load_module()
    with engine.begin() as conn:
        conn.execute( sa.text( "ALTER TABLE preference_evidence ADD COLUMN source_key TEXT" ) )
        conn.execute( sa.text( "ALTER TABLE preference_evidence ADD COLUMN caveat TEXT" ) )
    fake = _run( engine, module, monkeypatch, "upgrade" )
    assert [ c.name for _, c in fake.columns ] == [ "condition_key", "decision_stage", "antecedent", "standing_quote" ]


def test_both_verbs_are_no_ops_when_the_table_is_absent( monkeypatch ):
    """A database without the evidence table is left empty by both verbs."""
    module = _load_module()
    eng    = _engine()
    try:
        assert _run( eng, module, monkeypatch, "upgrade" ).columns == []
        _run( eng, module, monkeypatch, "downgrade" )
        assert sa.inspect( eng ).get_table_names() == []
    finally:
        eng.dispose()


def test_the_revision_follows_the_answer_meaning_table_and_is_the_single_head():
    """The chain stays linear, with this revision on it right after e1b7c4a9d286."""
    script = _script()
    assert script.get_revision( _REVISION ).down_revision == "e1b7c4a9d286"
    heads = script.get_heads()
    assert len( heads ) == 1, f"the chain must stay linear, got heads {heads}"
    assert _REVISION in { r.revision for r in script.walk_revisions( base="base", head=heads[ 0 ] ) }
