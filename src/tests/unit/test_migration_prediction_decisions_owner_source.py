"""
Migration f1c9a4d27b36: prediction_decisions owner_user_id and answer_source, backfilled.

Runs the real upgrade() and downgrade() against an in-memory SQLite database through a
minimal stand-in for alembic's `op`. Each test names what it would catch:
  - a column added to the wrong table or twice                      -> the column and idempotence tests
  - a backfill rule moved or dropped                                -> the per-class backfill test
  - a re-run that overwrites a value already filled                 -> the untouched-source test
  - a hint-vote case read as a missing notification                 -> the hint-vote row of the backfill test
  - a fresh database that already has the columns                   -> the columns-present test
  - a revision that does not follow a7c3e91b5d20                    -> the chain test
"""
import importlib.util
import json
from collections import Counter

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

from cosa.rest.db.auto_migrate import build_alembic_config

_REVISION = "f1c9a4d27b36"

_DDL_NO_COLUMNS = "CREATE TABLE prediction_decisions ( id TEXT PRIMARY KEY, ratification_state TEXT, question TEXT )"
_DDL_WITH_COLUMNS = ( "CREATE TABLE prediction_decisions ( id TEXT PRIMARY KEY, ratification_state TEXT, question TEXT, "
                      "owner_user_id TEXT, answer_source TEXT )" )
_DDL_NOTIFICATIONS = "CREATE TABLE notifications ( id TEXT PRIMARY KEY, response_value TEXT )"

OWNER = "11111111-1111-4111-8111-111111111111"

# ( case id, ratification_state, notification answer or None for no notification, expected ( owner, source ) )
CASES = [
    ( "human-1",     "not_required", { "value": "yes", "source": "ui", "answered_by": { "user_id": OWNER } },            ( OWNER, "human" ) ),
    ( "approved-1",  "approved",     { "value": "yes", "source": "ui", "answered_by": { "user_id": OWNER } },            ( OWNER, "human" ) ),
    ( "rejected-1",  "rejected",     { "value": "no",  "source": "ui", "answered_by": { "user_id": OWNER } },            ( OWNER, "human" ) ),
    ( "timeout-1",   "not_required", { "value": "no", "source": "timeout_default", "answered_by": { "user_id": OWNER } }, ( OWNER, "timeout_default" ) ),
    ( "proxy-pend",  "pending",      { "value": "yes", "source": "ui", "answered_by": { "user_id": OWNER } },            ( OWNER, "proxy" ) ),
    ( "proxy-auto",  "autonomous",   { "value": "yes", "source": "ui" },                                                  ( None, "proxy" ) ),
    ( "proxy-shad",  "shadow",       { "value": "", "source": "ui" },                                                    ( None, "proxy" ) ),
    ( "no-user",     "not_required", { "value": "yes", "source": "ui" },                                                 ( None, "unknown" ) ),
    ( "odd-state",   "mystery",      { "value": "yes", "source": "ui", "answered_by": { "user_id": OWNER } },            ( OWNER, "unknown" ) ),
    ( "blank-state", None,           { "value": "yes", "source": "ui", "answered_by": { "user_id": OWNER } },            ( OWNER, "unknown" ) ),
    ( "no-notif",    "not_required", None,                                                                               ( None, "unknown" ) ),
    ( "hintvote-9",  "rejected",     None,                                                                               ( None, "hint_vote" ) ),
]


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
    spec   = importlib.util.spec_from_file_location( "mig_owner_source", _script().get_revision( _REVISION ).path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _seed( engine, with_columns=False ):
    with engine.begin() as conn:
        conn.execute( sa.text( _DDL_WITH_COLUMNS if with_columns else _DDL_NO_COLUMNS ) )
        conn.execute( sa.text( _DDL_NOTIFICATIONS ) )
        for case_id, state, answer, _ in CASES:
            conn.execute( sa.text( "INSERT INTO prediction_decisions ( id, ratification_state, question ) VALUES ( :i, :s, 'q' )" ),
                          { "i": case_id, "s": state } )
            if answer is not None:
                conn.execute( sa.text( "INSERT INTO notifications ( id, response_value ) VALUES ( :i, :v )" ),
                              { "i": case_id, "v": json.dumps( answer ) } )


@pytest.fixture
def engine():
    eng = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    _seed( eng )
    yield eng
    eng.dispose()


def _columns( engine ):
    return [ c[ "name" ] for c in sa.inspect( engine ).get_columns( "prediction_decisions" ) ]


def _run( engine, module, monkeypatch, verb ):
    with engine.begin() as conn:
        monkeypatch.setattr( module, "op", _FakeOp( conn ), raising=True )
        getattr( module, verb )()


def _filled( engine ):
    with engine.begin() as conn:
        return { row[ 0 ]: ( row[ 1 ], row[ 2 ] ) for row in conn.execute( sa.text( "SELECT id, owner_user_id, answer_source FROM prediction_decisions" ) ) }


def test_upgrade_adds_both_columns_and_fills_every_row_by_its_class( monkeypatch, engine ):
    module = _load_module()
    assert "answer_source" not in _columns( engine )
    _run( engine, module, monkeypatch, "upgrade" )
    assert { "owner_user_id", "answer_source" } <= set( _columns( engine ) )
    assert _filled( engine ) == { case_id: expected for case_id, _, _, expected in CASES }


def test_upgrade_prints_the_counts_per_state_and_per_derived_value( monkeypatch, engine, capsys ):
    _run( engine, _load_module(), monkeypatch, "upgrade" )
    printed = capsys.readouterr().out
    derived = Counter( expected[ 1 ] for _, _, _, expected in CASES )
    assert str( dict( derived ) ) in printed
    assert "'mystery': 1" in printed and "'not_required': 4" in printed


def test_a_second_upgrade_changes_nothing_and_keeps_a_value_already_filled( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    with engine.begin() as conn:
        conn.execute( sa.text( "UPDATE prediction_decisions SET answer_source = 'test' WHERE id = 'human-1'" ) )
    _run( engine, module, monkeypatch, "upgrade" )
    assert _columns( engine ).count( "answer_source" ) == 1
    assert _filled( engine )[ "human-1" ] == ( OWNER, "test" ), "a filled row is not derived again"


def test_a_database_that_already_has_the_columns_is_only_backfilled( monkeypatch ):
    eng = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    try:
        _seed( eng, with_columns=True )
        _run( eng, _load_module(), monkeypatch, "upgrade" )
        assert _columns( eng ).count( "owner_user_id" ) == 1
        assert _filled( eng )[ "human-1" ] == ( OWNER, "human" )
    finally:
        eng.dispose()


def test_the_backfill_copes_with_a_database_that_has_no_notifications_table( monkeypatch ):
    eng = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    try:
        with eng.begin() as conn:
            conn.execute( sa.text( _DDL_NO_COLUMNS ) )
            conn.execute( sa.text( "INSERT INTO prediction_decisions ( id, ratification_state ) VALUES ( 'a', 'not_required' ), ( 'hintvote-b', 'approved' )" ) )
        _run( eng, _load_module(), monkeypatch, "upgrade" )
        assert _filled( eng ) == { "a": ( None, "unknown" ), "hintvote-b": ( None, "hint_vote" ) }
    finally:
        eng.dispose()


def test_a_notification_answer_that_is_not_a_json_object_reads_as_no_answer():
    module = _load_module()
    assert module._as_dict( "[1, 2]" ) is None
    assert module._as_dict( { "a": 1 } ) == { "a": 1 }
    assert module._as_dict( None ) is None


def test_downgrade_drops_both_columns_and_is_safe_to_repeat( monkeypatch, engine ):
    module = _load_module()
    _run( engine, module, monkeypatch, "upgrade" )
    _run( engine, module, monkeypatch, "downgrade" )
    assert not { "owner_user_id", "answer_source" } & set( _columns( engine ) )
    _run( engine, module, monkeypatch, "downgrade" )


def test_both_verbs_are_no_ops_when_the_table_is_absent( monkeypatch ):
    module = _load_module()
    eng    = sa.create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    try:
        _run( eng, module, monkeypatch, "upgrade" )
        _run( eng, module, monkeypatch, "downgrade" )
        assert sa.inspect( eng ).get_table_names() == []
    finally:
        eng.dispose()


def test_the_revision_follows_a7c3e91b5d20_and_is_the_only_head():
    script = _script()
    assert script.get_revision( _REVISION ).down_revision == "a7c3e91b5d20"
    assert script.get_heads() == [ _REVISION ]
