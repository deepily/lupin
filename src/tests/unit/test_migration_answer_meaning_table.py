"""
Migration e1b7c4a9d286: the answer_meaning table.

Runs the real upgrade() and downgrade() against in-memory SQLite through a minimal stand-in for alembic's `op`.
Each test names what it would catch:
  - a table missing, misnamed or carrying the wrong columns     -> the column-set test
  - an upgrade then a downgrade that leaves something behind    -> the up-then-down test
  - a re-run that fails on a table that exists                  -> the idempotence test
  - a downgrade on a database that never had the table          -> the absent-table test
  - a second reading under one key, or a second version         -> the unique-key tests
  - the model and the migration disagreeing                     -> the model-agreement test
  - a revision that is not on the single linear chain           -> the chain test
"""
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import AnswerMeaning


_REVISION = "e1b7c4a9d286"
_NID      = "11111111-1111-1111-1111-111111111111"


class _FakeOp:
    """Minimal alembic `op` over a live connection; uuid, jsonb and float columns become text."""

    def __init__( self, bind ):
        self._bind = bind

    def get_bind( self ):
        return self._bind

    def create_table( self, name, *items ):
        parts = []
        for item in items:
            if isinstance( item, sa.Column ): parts.append( sa.Column( item.name, sa.Text(), primary_key=item.primary_key, nullable=item.nullable ) )
            else: parts.append( sa.UniqueConstraint( *item._pending_colargs, name=item.name ) )
        sa.Table( name, sa.MetaData(), *parts ).create( self._bind )

    def create_index( self, name, table, columns, unique=False ):
        self._bind.execute( sa.text( f"CREATE INDEX {name} ON {table} ( {', '.join( columns )} )" ) )

    def drop_table( self, name ):
        self._bind.execute( sa.text( f"DROP TABLE {name}" ) )


def _script():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _load_module():
    spec   = importlib.util.spec_from_file_location( "mig_answer_meaning", _script().get_revision( _REVISION ).path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def engine():
    eng = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    yield eng
    eng.dispose()


def _run( engine, module, monkeypatch, verb ):
    with engine.begin() as conn:
        monkeypatch.setattr( module, "op", _FakeOp( conn ), raising=True )
        getattr( module, verb )()


def _row( engine, row_id, version="v1", annotator="a" ):
    with engine.begin() as conn:
        conn.execute( sa.text(
            "INSERT INTO answer_meaning ( id, notification_id, schema_version, annotator, source, native_answer, acts, conditions, "
            "alignment, unknowns, annotated_at ) VALUES ( :i, :n, :v, :a, 'human', '{}', '[]', '[]', 'unknown', '[]', '2026-11-23' )" ),
            { "i": row_id, "n": _NID, "v": version, "a": annotator } )


def test_upgrade_creates_the_table_with_the_columns_of_the_plan( monkeypatch, engine ):
    _run( engine, _load_module(), monkeypatch, "upgrade" )
    assert set( sa.inspect( engine ).get_table_names() ) == { "answer_meaning" }
    assert { c[ "name" ] for c in sa.inspect( engine ).get_columns( "answer_meaning" ) } == {
        "id", "notification_id", "schema_version", "annotator", "source", "native_answer", "acts", "conditions", "alignment",
        "unknowns", "supporting_spans", "uncertainty", "answered_at", "annotated_at", "session_key" }
    assert [ i[ "name" ] for i in sa.inspect( engine ).get_indexes( "answer_meaning" ) ] == [ "ix_answer_meaning_notification_id" ]


def test_upgrade_then_downgrade_leaves_the_schema_as_it_was( monkeypatch, engine ):
    module = _load_module()
    before = set( sa.inspect( engine ).get_table_names() )
    _run( engine, module, monkeypatch, "upgrade" )
    assert set( sa.inspect( engine ).get_table_names() ) != before, "the upgrade must have added the table"
    _run( engine, module, monkeypatch, "downgrade" )
    assert set( sa.inspect( engine ).get_table_names() ) == before


def test_upgrade_applies_twice_and_keeps_rows( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _row( engine, "r1" )
    _run( engine, module, monkeypatch, "upgrade" )          # a second create_table would raise "already exists"
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT COUNT(*) FROM answer_meaning" ) ).scalar() == 1


def test_downgrade_on_a_database_without_the_table_does_nothing( monkeypatch, engine ):
    _run( engine, _load_module(), monkeypatch, "downgrade" )
    assert sa.inspect( engine ).get_table_names() == []


def test_the_same_key_twice_is_refused_and_a_new_version_or_annotator_is_accepted( monkeypatch, engine ):
    _run( engine, _load_module(), monkeypatch, "upgrade" )
    _row( engine, "r1" )
    with pytest.raises( sa.exc.IntegrityError ): _row( engine, "r2" )
    _row( engine, "r3", version="v2" )
    _row( engine, "r4", annotator="b" )
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT COUNT(*) FROM answer_meaning" ) ).scalar() == 3


def test_the_model_and_the_migration_name_the_same_columns_and_key( monkeypatch, engine ):
    _run( engine, _load_module(), monkeypatch, "upgrade" )
    assert { c[ "name" ] for c in sa.inspect( engine ).get_columns( "answer_meaning" ) } == { c.name for c in AnswerMeaning.__table__.columns }
    unique = [ c for c in sa.inspect( engine ).get_unique_constraints( "answer_meaning" ) ]
    assert [ ( u[ "name" ], u[ "column_names" ] ) for u in unique ] == [ ( "uq_answer_meaning_key", [ "notification_id", "schema_version", "annotator" ] ) ]
    assert not AnswerMeaning.__table__.c.notification_id.foreign_keys, "no foreign key, so pruning notifications never removes a reading"


def test_the_revision_lies_on_the_single_head_chain():
    script = _script()
    heads  = script.get_heads()
    assert len( heads ) == 1, f"the chain must stay linear, got heads {heads}"
    assert _REVISION in { r.revision for r in script.walk_revisions( base="base", head=heads[ 0 ] ) }
    assert script.get_revision( _REVISION ).down_revision == "d5e9f2b7c413"
