"""
Migration b4d8f2a61c07: prediction_log forecast ledger columns, unique notification_id.

Runs the real upgrade() and downgrade() against in-memory SQLite through a minimal stand-in for
alembic's `op`. Each test names what it would catch:
  - a column missing, misnamed or added to the wrong table        -> the column-set test
  - a re-run that adds a column twice                              -> the idempotence tests
  - a database that already has some of the columns                -> the partial-columns test
  - duplicates present: a changed schema, a deleted row, no list   -> the refusal tests
  - a constraint added twice, or on the wrong column               -> the constraint tests
  - a table-absent database (fresh DB built from metadata)         -> the no-op test
  - a revision that is not the single head after f1c9a4d27b36      -> the chain test
  - the model and the migration disagreeing on the column set      -> the model-agreement test
"""
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import PredictionLog


_REVISION = "b4d8f2a61c07"

_NID_A = "11111111-1111-1111-1111-111111111111"
_NID_B = "22222222-2222-2222-2222-222222222222"

_DDL_PRE = """
CREATE TABLE prediction_log (
    id              TEXT PRIMARY KEY,
    notification_id TEXT NOT NULL,
    category        TEXT NOT NULL
)
"""


class _FakeOp:
    """Minimal alembic `op` over a live connection."""

    def __init__( self, bind ):
        self._bind = bind

    def get_bind( self ):
        return self._bind

    def add_column( self, table, column ):
        self._bind.execute( sa.text( f"ALTER TABLE {table} ADD COLUMN {column.name} TEXT" ) )

    def drop_column( self, table, column_name ):
        self._bind.execute( sa.text( f"ALTER TABLE {table} DROP COLUMN {column_name}" ) )

    def create_unique_constraint( self, name, table, columns ):
        self._bind.execute( sa.text( f"CREATE UNIQUE INDEX {name} ON {table} ( {', '.join( columns )} )" ) )

    def drop_constraint( self, name, table, type_=None ):
        self._bind.execute( sa.text( f"DROP INDEX {name}" ) )


def _script():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _load_module():
    path   = _script().get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "mig_forecast_ledger", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _new_engine():
    return sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )


def _insert( engine, row_id, notification_id ):
    with engine.begin() as conn:
        conn.execute( sa.text(
            "INSERT INTO prediction_log ( id, notification_id, category ) VALUES ( :i, :n, 'c' )" ),
            { "i": row_id, "n": notification_id } )


@pytest.fixture
def engine():
    eng = _new_engine()
    with eng.begin() as conn:
        conn.execute( sa.text( _DDL_PRE ) )
    _insert( eng, "r1", _NID_A )
    yield eng
    eng.dispose()


def _columns( engine ):
    return [ c[ "name" ] for c in sa.inspect( engine ).get_columns( "prediction_log" ) ]


def _unique_index_names( engine ):
    return [ i[ "name" ] for i in sa.inspect( engine ).get_indexes( "prediction_log" ) if i.get( "unique" ) ]


def _run( engine, module, monkeypatch, verb ):
    with engine.begin() as conn:
        monkeypatch.setattr( module, "op", _FakeOp( conn ), raising=True )
        getattr( module, verb )()


def test_upgrade_adds_every_ledger_column_and_the_constraint_and_leaves_rows_alone( monkeypatch, engine ):
    module = _load_module()
    before = set( _columns( engine ) )
    _run( engine, module, monkeypatch, "upgrade" )
    added = set( _columns( engine ) ) - before
    assert added == { name for name, _ in module.COLUMNS }
    assert len( module.COLUMNS ) == 18
    assert _unique_index_names( engine ) == [ "uq_prediction_log_notification_id" ]
    with engine.begin() as conn:
        row = conn.execute( sa.text( "SELECT id, notification_id, rendered_at, fold_opened_at FROM prediction_log" ) ).one()
    assert tuple( row ) == ( "r1", _NID_A, None, None ), "no backfill: existing rows keep NULL ledger values"


def test_upgrade_is_idempotent( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _run( engine, module, monkeypatch, "upgrade" )          # a second add would raise "duplicate column"
    assert _columns( engine ).count( "rendered_at" ) == 1
    assert len( _unique_index_names( engine ) ) == 1


def test_each_column_is_checked_first_when_some_already_exist( monkeypatch, engine ):
    module = _load_module()
    with engine.begin() as conn:
        conn.execute( sa.text( "ALTER TABLE prediction_log ADD COLUMN rendered_at TEXT" ) )
        conn.execute( sa.text( "ALTER TABLE prediction_log ADD COLUMN code_identity TEXT" ) )
    _run( engine, module, monkeypatch, "upgrade" )
    assert _columns( engine ).count( "rendered_at" )   == 1
    assert _columns( engine ).count( "code_identity" ) == 1
    assert "fold_opened_at" in _columns( engine )


def test_an_existing_unique_constraint_is_not_added_again( monkeypatch, engine ):
    module = _load_module()
    with engine.begin() as conn:
        conn.execute( sa.text( "CREATE UNIQUE INDEX preexisting_unique ON prediction_log ( notification_id )" ) )
    _run( engine, module, monkeypatch, "upgrade" )
    assert _unique_index_names( engine ) == [ "preexisting_unique" ]


def test_duplicates_refuse_the_upgrade_list_them_and_change_nothing( monkeypatch, engine ):
    module = _load_module()
    _insert( engine, "r2", _NID_A )          # duplicate of r1
    _insert( engine, "r3", _NID_A )          # three rows for A
    _insert( engine, "r4", _NID_B )
    _insert( engine, "r5", _NID_B )
    before = _columns( engine )
    with pytest.raises( module.DuplicateNotificationIdsError ) as caught:
        _run( engine, module, monkeypatch, "upgrade" )
    message = str( caught.value )
    assert f"{_NID_A} x3" in message and f"{_NID_B} x2" in message
    assert "2 duplicate" in message
    assert _columns( engine ) == before, "a refused upgrade adds no column"
    assert _unique_index_names( engine ) == []
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT COUNT(*) FROM prediction_log" ) ).scalar() == 5, "never deletes a row"


def test_unique_ids_that_differ_only_in_the_other_columns_do_not_refuse( monkeypatch, engine ):
    module = _load_module()
    _insert( engine, "r2", _NID_B )
    _run( engine, module, monkeypatch, "upgrade" )
    assert _unique_index_names( engine ) == [ "uq_prediction_log_notification_id" ]


def test_the_constraint_rejects_a_second_row_for_one_notification( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    with pytest.raises( sa.exc.IntegrityError ):
        _insert( engine, "r2", _NID_A )


def test_downgrade_drops_columns_and_constraint_and_is_safe_to_repeat( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    # SQLite lists the index through get_indexes, not get_unique_constraints, so the downgrade's
    # constraint branch is exercised by the stand-in below; the column drops are real.
    _run( engine, module, monkeypatch, "downgrade" )
    assert _columns( engine ) == [ "id", "notification_id", "category" ]
    _run( engine, module, monkeypatch, "downgrade" )        # already gone: no error


def test_downgrade_drops_a_named_unique_constraint_when_the_inspector_reports_one( monkeypatch, engine ):
    module  = _load_module()
    dropped = []

    class _Op( _FakeOp ):
        def drop_constraint( self, name, table, type_=None ):
            dropped.append( ( name, table, type_ ) )

    class _Inspector:
        def get_table_names( self ):           return [ "prediction_log" ]
        def get_unique_constraints( self, t ): return [ { "name": module.CONSTRAINT_NAME, "column_names": [ "notification_id" ] } ]
        def get_columns( self, t ):            return []

    with engine.begin() as conn:
        monkeypatch.setattr( module, "op", _Op( conn ), raising=True )
        monkeypatch.setattr( module, "inspect", lambda _bind: _Inspector(), raising=True )
        module.downgrade()
    assert dropped == [ ( "uq_prediction_log_notification_id", "prediction_log", "unique" ) ]


def test_a_unique_constraint_reported_by_the_inspector_counts_as_present( monkeypatch ):
    module = _load_module()

    class _Inspector:
        def get_unique_constraints( self, t ): return [ { "name": "x", "column_names": [ "notification_id" ] } ]
        def get_indexes( self, t ):            return []

    assert module._has_unique_on_notification_id( _Inspector() ) is True


def test_other_constraints_and_indexes_do_not_count_as_a_unique_key_on_notification_id():
    module = _load_module()

    class _Inspector:
        def get_unique_constraints( self, t ):
            return [ { "name": "u1", "column_names": [ "category" ] } ]
        def get_indexes( self, t ):
            return [ { "name": "i1", "column_names": [ "notification_id" ], "unique": False },
                     { "name": "i2", "column_names": [ "category" ],        "unique": True },
                     { "name": "i3", "column_names": [ "notification_id", "category" ], "unique": True } ]

    assert module._has_unique_on_notification_id( _Inspector() ) is False


def test_both_verbs_are_no_ops_when_prediction_log_is_absent( monkeypatch ):
    module = _load_module()
    eng    = _new_engine()
    try:
        _run( eng, module, monkeypatch, "upgrade" )
        _run( eng, module, monkeypatch, "downgrade" )
        assert sa.inspect( eng ).get_table_names() == []
    finally:
        eng.dispose()


def test_the_migration_and_the_model_name_the_same_ledger_columns( ):
    module = _load_module()
    model_columns = { c.name for c in PredictionLog.__table__.columns }
    for name, _ in module.COLUMNS:
        assert name in model_columns, f"{name} is migrated but missing from PredictionLog"
    constraint_names = { c.name for c in PredictionLog.__table__.constraints }
    assert module.CONSTRAINT_NAME in constraint_names


def test_the_revision_follows_f1c9a4d27b36_and_is_the_only_head():
    script = _script()
    assert script.get_revision( _REVISION ).down_revision == "f1c9a4d27b36"
    heads = script.get_heads()
    assert len( heads ) == 1, f"the chain must stay linear, got heads {heads}"
    assert _REVISION in { r.revision for r in script.walk_revisions( base="base", head=heads[ 0 ] ) }, "this revision must lie on the chain that ends at the single head"
