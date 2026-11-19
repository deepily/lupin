"""
Migration f8c2d6a14e37: the continues_principle_id and session_key columns.

Runs the real upgrade() and downgrade() against in-memory SQLite through a minimal stand-in for alembic's op.
Each test names what it would catch:
  - a column added under another name or to another table        -> the column test
  - a column that is not the nullable type the model declares     -> the shape test
  - one column added and the other forgotten                      -> the both-columns test
  - a re-run that adds a column twice, or loses its data           -> the idempotence test
  - a half-applied upgrade that is not finished                    -> the half-applied test
  - an upgrade that touches existing rows                          -> the untouched-rows test
  - a table-absent database                                        -> the no-op tests
  - a revision that is off the single linear chain                 -> the chain test
"""
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import PreferenceEvidence, PreferencePrinciple


_REVISION = "f8c2d6a14e37"
_ADDED    = { "preference_principles": "continues_principle_id", "preference_evidence": "session_key" }


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
    spec   = importlib.util.spec_from_file_location( "mig_principle_continues", _script().get_revision( _REVISION ).path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _engine():
    return sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )


@pytest.fixture
def engine():
    eng = _engine()
    with eng.begin() as conn:
        conn.execute( sa.text( "CREATE TABLE preference_principles ( id TEXT PRIMARY KEY, statement TEXT NOT NULL )" ) )
        conn.execute( sa.text( "CREATE TABLE preference_evidence ( id TEXT PRIMARY KEY, relation TEXT NOT NULL )" ) )
        conn.execute( sa.text( "INSERT INTO preference_principles ( id, statement ) VALUES ( 'p1', 's' )" ) )
        conn.execute( sa.text( "INSERT INTO preference_evidence ( id, relation ) VALUES ( 'e1', 'supports' )" ) )
    yield eng
    eng.dispose()


def _columns( engine, table ):
    return [ c[ "name" ] for c in sa.inspect( engine ).get_columns( table ) ]


def _run( engine, module, monkeypatch, verb ):
    with engine.begin() as conn:
        fake = _FakeOp( conn )
        monkeypatch.setattr( module, "op", fake, raising=True )
        getattr( module, verb )()
    return fake


def test_upgrade_adds_both_columns_to_their_own_tables_and_leaves_rows_untouched( monkeypatch, engine ):
    """Each column lands on its own table, and the existing rows read NULL in it."""
    module = _load_module()
    assert all( name not in _columns( engine, table ) for table, name in _ADDED.items() )
    fake = _run( engine, module, monkeypatch, "upgrade" )
    assert { ( table, column.name ) for table, column in fake.columns } == set( _ADDED.items() )
    with engine.begin() as conn:
        assert tuple( conn.execute( sa.text( "SELECT id, continues_principle_id FROM preference_principles" ) ).one() ) == ( "p1", None )
        assert tuple( conn.execute( sa.text( "SELECT id, session_key FROM preference_evidence" ) ).one() ) == ( "e1", None )


def test_the_columns_are_nullable_and_match_the_models( monkeypatch, engine ):
    """
    The continues column is a nullable UUID key to the principles table.

    The session key is a nullable string. Both are as the models declare them.
    """
    from sqlalchemy.dialects import postgresql
    module = _load_module()
    added  = { column.name: column for _, column in _run( engine, module, monkeypatch, "upgrade" ).columns }
    pairs  = ( ( PreferencePrinciple, "continues_principle_id" ), ( PreferenceEvidence, "session_key" ) )
    for model, name in pairs:
        modeled = model.__table__.columns[ name ]
        assert added[ name ].nullable is True and modeled.nullable is True
        assert type( added[ name ].type ) is type( modeled.type ) or isinstance( added[ name ].type, type( modeled.type ) )
    assert isinstance( added[ "continues_principle_id" ].type, postgresql.UUID )
    assert isinstance( added[ "session_key" ].type, sa.String ) and added[ "session_key" ].type.length == 255
    assert { fk.target_fullname for fk in added[ "continues_principle_id" ].foreign_keys } == { "preference_principles.id" }
    assert { fk.target_fullname for fk in PreferencePrinciple.__table__.columns[ "continues_principle_id" ].foreign_keys } == { "preference_principles.id" }
    assert not added[ "session_key" ].foreign_keys and not PreferenceEvidence.__table__.columns[ "session_key" ].foreign_keys


def test_upgrade_is_idempotent_and_keeps_existing_data( monkeypatch, engine ):
    """A re-run adds nothing, and a column that is already there keeps its values."""
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    with engine.begin() as conn:
        conn.execute( sa.text( "UPDATE preference_principles SET continues_principle_id = 'kept'" ) )
        conn.execute( sa.text( "UPDATE preference_evidence SET session_key = 'kept'" ) )
    assert _run( engine, module, monkeypatch, "upgrade" ).columns == []
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT continues_principle_id FROM preference_principles" ) ).scalar_one() == "kept"
        assert conn.execute( sa.text( "SELECT session_key FROM preference_evidence" ) ).scalar_one() == "kept"


def test_a_half_applied_upgrade_is_finished( monkeypatch, engine ):
    """With one column already present the upgrade adds only the other."""
    module = _load_module()
    with engine.begin() as conn:
        conn.execute( sa.text( "ALTER TABLE preference_principles ADD COLUMN continues_principle_id TEXT" ) )
    fake = _run( engine, module, monkeypatch, "upgrade" )
    assert [ ( table, column.name ) for table, column in fake.columns ] == [ ( "preference_evidence", "session_key" ) ]


def test_downgrade_drops_both_and_is_safe_to_repeat( monkeypatch, engine ):
    """The downgrade removes both columns, and a second downgrade is a no-op."""
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _run( engine, module, monkeypatch, "downgrade" )
    assert all( name not in _columns( engine, table ) for table, name in _ADDED.items() )
    _run( engine, module, monkeypatch, "downgrade" )


def test_both_verbs_are_no_ops_when_the_tables_are_absent( monkeypatch ):
    """A database with neither table is left empty by both verbs."""
    module = _load_module()
    eng    = _engine()
    try:
        _run( eng, module, monkeypatch, "upgrade" )
        _run( eng, module, monkeypatch, "downgrade" )
        assert sa.inspect( eng ).get_table_names() == []
    finally:
        eng.dispose()


def test_one_missing_table_skips_only_its_column( monkeypatch, engine ):
    """With the evidence table absent, the principles column is still added."""
    module = _load_module()
    with engine.begin() as conn:
        conn.execute( sa.text( "DROP TABLE preference_evidence" ) )
    fake = _run( engine, module, monkeypatch, "upgrade" )
    assert [ ( table, column.name ) for table, column in fake.columns ] == [ ( "preference_principles", "continues_principle_id" ) ]


def test_the_revision_follows_the_draft_at_reveal_revision_and_is_on_the_single_head_chain():
    """The chain stays linear, with this revision right after e5b7d9a2c418."""
    script = _script()
    assert script.get_revision( _REVISION ).down_revision == "e5b7d9a2c418"
    heads = script.get_heads()
    assert len( heads ) == 1, f"the chain must stay linear, got heads {heads}"
    assert _REVISION in { r.revision for r in script.walk_revisions( base="base", head=heads[ 0 ] ) }
