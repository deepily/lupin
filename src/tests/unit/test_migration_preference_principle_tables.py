"""
Migration d3a6c1e8b5f2: the principle, evidence and arm-forecast tables.

Runs the real upgrade() and downgrade() against in-memory SQLite through a minimal stand-in for
alembic's `op` that rebuilds each create_table call with portable types. Each test names what it would catch:
  - a table missing, misnamed or carrying the wrong columns          -> the column-set test
  - a re-run that fails on tables that exist, or a database already
    holding one table                                                 -> the idempotence and partial tests
  - a second arm row for one notification, or the same evidence key
    twice                                                             -> the two refusal tests
  - the same notification under another arm, or the same evidence
    under another source                                              -> the two acceptance tests
  - the model and the migration disagreeing                           -> the model-agreement test
  - a revision that is not the single head after c9e3a7b1d542         -> the chain test
"""
import importlib.util

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import PredictionArmForecast, PreferenceEvidence, PreferencePrinciple


_REVISION = "d3a6c1e8b5f2"

_NID_A = "11111111-1111-1111-1111-111111111111"
_NID_B = "22222222-2222-2222-2222-222222222222"
_PID   = "33333333-3333-3333-3333-333333333333"
_NOW   = "2026-11-19T12:00:00"


class _FakeOp:
    """Minimal alembic `op` over a live connection; vector, uuid and jsonb columns become text."""

    def __init__( self, bind ):
        self._bind = bind

    def get_bind( self ):
        return self._bind

    def create_table( self, name, *items ):
        meta  = sa.MetaData()
        parts = []
        for item in items:
            if isinstance( item, sa.Column ):
                default = item.server_default if item.name == "displayed" else None
                parts.append( sa.Column( item.name, sa.Boolean() if item.name == "displayed" else sa.Text(),
                                         primary_key=item.primary_key, nullable=item.nullable, server_default=default ) )
            else:
                parts.append( sa.UniqueConstraint( *item._pending_colargs, name=item.name ) )
        sa.Table( name, meta, *parts ).create( self._bind )

    def create_index( self, name, table, columns, unique=False ):
        self._bind.execute( sa.text( f"CREATE INDEX {name} ON {table} ( {', '.join( columns )} )" ) )

    def drop_table( self, name ):
        self._bind.execute( sa.text( f"DROP TABLE {name}" ) )


def _script():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _load_module():
    path   = _script().get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "mig_preference_principle_tables", path )
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


def _tables( engine ):
    return set( sa.inspect( engine ).get_table_names() )


def _columns( engine, table ):
    return { c[ "name" ] for c in sa.inspect( engine ).get_columns( table ) }


def _arm( engine, nid, arm, displayed=False ):
    with engine.begin() as conn:
        conn.execute( sa.text(
            "INSERT INTO prediction_arm_forecast ( id, notification_id, arm, displayed ) VALUES ( :i, :n, :a, :d )" ),
            { "i": f"{nid}-{arm}", "n": nid, "a": arm, "d": displayed } )


def _evidence( engine, source, row_id ):
    with engine.begin() as conn:
        conn.execute( sa.text(
            "INSERT INTO preference_evidence ( id, principle_id, notification_id, field_key, relation, answered_at, "
            "extracted_at, extractor_version, source ) VALUES ( :i, :p, :n, 'f', 'supports', :t, :t, 'v1', :s )" ),
            { "i": row_id, "p": _PID, "n": _NID_A, "t": _NOW, "s": source } )


def test_upgrade_creates_the_three_tables_with_the_columns_rick_named( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    assert _tables( engine ) == { "preference_principles", "preference_evidence", "prediction_arm_forecast" }
    assert _columns( engine, "prediction_arm_forecast" ) == {
        "id", "notification_id", "arm", "predictor_version", "forecast", "input_cutoff",
        "evidence_ids", "forecast_ready_at", "abstention_reason", "displayed" }
    assert _columns( engine, "preference_evidence" ) == {
        "id", "principle_id", "notification_id", "field_key", "relation", "condition", "answered_at",
        "extracted_at", "extractor_version", "retracted_at", "source" }
    assert _columns( engine, "preference_principles" ) == {
        "id", "owner_id", "kind", "dimension", "statement", "rationale", "scope", "embedding",
        "encoder_version", "extractor_version", "created_at" }


def test_upgrade_applies_twice_without_error( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _arm( engine, _NID_A, "A1" )
    _run( engine, module, monkeypatch, "upgrade" )          # a second create_table would raise "already exists"
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT COUNT(*) FROM prediction_arm_forecast" ) ).scalar() == 1, "a re-run keeps rows"


def test_a_database_that_already_has_one_table_gets_the_other_two( monkeypatch, engine ):
    module = _load_module()
    with engine.begin() as conn:
        conn.execute( sa.text( "CREATE TABLE preference_evidence ( id TEXT PRIMARY KEY, marker TEXT )" ) )
    _run( engine, module, monkeypatch, "upgrade" )
    assert _tables( engine ) == { "preference_principles", "preference_evidence", "prediction_arm_forecast" }
    assert _columns( engine, "preference_evidence" ) == { "id", "marker" }, "an existing table is left alone"


def test_a_second_row_for_the_same_notification_and_arm_is_refused( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _arm( engine, _NID_A, "B1", displayed=True )
    with pytest.raises( sa.exc.IntegrityError ):
        with engine.begin() as conn:
            conn.execute( sa.text(
                "INSERT INTO prediction_arm_forecast ( id, notification_id, arm, displayed ) VALUES ( 'dup', :n, 'B1', 0 )" ),
                { "n": _NID_A } )


def test_the_same_notification_under_another_arm_and_another_notification_under_the_same_arm_are_accepted( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _arm( engine, _NID_A, "B1" )
    _arm( engine, _NID_A, "C0" )
    _arm( engine, _NID_B, "B1" )
    with engine.begin() as conn:
        assert conn.execute( sa.text( "SELECT COUNT(*) FROM prediction_arm_forecast" ) ).scalar() == 3


def test_the_displayed_flag_defaults_to_false( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    with engine.begin() as conn:
        conn.execute( sa.text( "INSERT INTO prediction_arm_forecast ( id, notification_id, arm ) VALUES ( 'x', :n, 'A1' )" ),
                      { "n": _NID_A } )
        assert conn.execute( sa.text( "SELECT displayed FROM prediction_arm_forecast" ) ).scalar() in ( 0, False )


def test_the_evidence_key_refuses_a_repeat_and_allows_another_source( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _evidence( engine, "extractor", "e1" )
    _evidence( engine, "review_card", "e2" )                 # same key apart from source: accepted
    with pytest.raises( sa.exc.IntegrityError ):
        _evidence( engine, "extractor", "e3" )               # the full key repeats: refused


def test_downgrade_drops_all_three_and_is_safe_to_repeat( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _run( engine, module, monkeypatch, "downgrade" )
    assert _tables( engine ) == set()
    _run( engine, module, monkeypatch, "downgrade" )         # already gone: no error


def test_the_migration_and_the_models_name_the_same_tables_columns_and_keys( monkeypatch ):
    module  = _load_module()
    pairs   = ( ( PreferencePrinciple, module.PRINCIPLES_TABLE ), ( PreferenceEvidence, module.EVIDENCE_TABLE ),
                ( PredictionArmForecast, module.ARM_TABLE ) )
    created = {}

    class _Capture:
        def get_bind( self ):             return None
        def create_table( self, name, *items ): created[ name ] = items
        def create_index( self, *a, **k ): pass

    monkeypatch.setattr( module.sa, "inspect", lambda _bind: type( "I", (), { "get_table_names": lambda self: [] } )(), raising=True )
    monkeypatch.setattr( module, "op", _Capture(), raising=True )
    module.upgrade()
    assert set( created ) == { table for _, table in pairs }
    for model, table in pairs:
        migrated = { i.name for i in created[ table ] if isinstance( i, sa.Column ) }
        assert migrated == { c.name for c in model.__table__.columns }, table
    unique_names = { c.name for m, _ in pairs for c in m.__table__.constraints if isinstance( c, sa.UniqueConstraint ) }
    assert { module.EVIDENCE_UNIQUE, module.ARM_UNIQUE } <= unique_names


def test_the_revision_follows_c9e3a7b1d542_and_is_the_only_head():
    script = _script()
    assert script.get_revision( _REVISION ).down_revision == "c9e3a7b1d542"
    heads = script.get_heads()
    assert len( heads ) == 1, f"the chain must stay linear, got heads {heads}"
    assert _REVISION in { r.revision for r in script.walk_revisions( base="base", head=heads[ 0 ] ) }


def test_each_model_names_its_keys_in_its_repr():
    principle = PreferencePrinciple( id=_PID, kind="decision", dimension="ask.needs_link" )
    evidence  = PreferenceEvidence( principle_id=_PID, notification_id=_NID_A, relation="supports" )
    arm       = PredictionArmForecast( notification_id=_NID_A, arm="B1", displayed=True )
    assert f"id={_PID}, kind='decision', dimension='ask.needs_link'" in repr( principle )
    assert f"principle_id={_PID}, notification_id={_NID_A}, relation='supports'" in repr( evidence )
    assert f"notification_id={_NID_A}, arm='B1', displayed=True" in repr( arm )
