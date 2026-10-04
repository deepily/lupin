"""
Unit tests for cosa.rest.task_store_change_notifier (row 8796333b, slice 1).

Every test runs through a REAL SQLAlchemy session and the REAL TaskRepository on an
in-memory SQLite copy of task_items / task_events: the notifier's whole job is to react
to a real commit or rollback, so a mock session would only echo what the test told it.
The sink is the one boundary faked, and it only records what it was handed.

SQLite fidelity limit: Postgres-only column types are swapped on a COPY of the tables
(the mapped classes are untouched), as test_the_for_update_read_refreshes_a_row_the_session_already_holds.py does.
"""

import os
import sys
import uuid

import pytest
from sqlalchemy import BigInteger, CheckConstraint, Integer, JSON, MetaData, String, create_engine
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Session

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_store_change_notifier as notifier
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest.postgres_models import TaskEvent, TaskItem


def _engine():
    """In-memory engine holding SQLite-renderable copies of task_items and task_events."""
    engine   = create_engine( "sqlite://" )
    metadata = MetaData()
    for model in ( TaskItem, TaskEvent ):
        table = model.__table__.to_metadata( metadata )
        for constraint in list( table.constraints ):
            if isinstance( constraint, CheckConstraint ): table.constraints.discard( constraint )
        for column in table.columns:
            if isinstance( column.type, JSONB ):      column.type = JSON()
            if isinstance( column.type, INET ):       column.type = String( 64 )
            if isinstance( column.type, BigInteger ): column.type = Integer()
            column.server_default = None if column.name == "id" else column.server_default
    metadata.create_all( engine )
    return engine


@pytest.fixture
def engine():
    engine = _engine()
    yield engine
    engine.dispose()


@pytest.fixture
def sink():
    """Install a recording sink; restore whatever was there afterwards."""
    previous = notifier.get_sink()
    seen     = []
    notifier.set_sink( seen.append )
    yield seen
    notifier.set_sink( previous )


def _create( session, title="a row" ):
    return TaskRepository( session ).create_item(
        item_class="task", title=title, project="lupin", created_by="chloe test", authority="standing" )


# ---------------------------------------------------------------------------
# Commit emits once
# ---------------------------------------------------------------------------

def test_a_commit_that_appended_one_event_emits_one_payload_naming_it( engine, sink ):
    with Session( engine ) as session:
        item = _create( session )
        assert sink == [], "nothing may be emitted before the commit"
        session.commit()
        event = session.query( TaskEvent ).one()
        item_id = str( item.id )
        event_id = event.id
        transition = event.transition

    assert len( sink ) == 1
    payload = sink[ 0 ]
    assert payload[ "event_id" ]   == event_id
    assert payload[ "item_id" ]    == item_id
    assert payload[ "transition" ] == transition == "->queued"
    assert payload[ "to_status" ]  == "queued"
    assert payload[ "count" ]      == 1
    assert payload[ "ts" ] is not None


def test_a_session_that_appended_several_events_emits_once_with_the_last_one_and_a_count( engine, sink ):
    with Session( engine ) as session:
        repo = TaskRepository( session )
        item = _create( session )
        repo.apply_transition( item, "in_progress", "chloe test", "standing" )
        last = repo.apply_transition( item, "queued", "chloe test", "standing" )
        session.commit()
        last_id         = last.id
        last_transition = last.transition

    assert len( sink ) == 1, "three events in one commit are ONE push"
    assert sink[ 0 ][ "count" ]      == 3
    assert sink[ 0 ][ "event_id" ]   == last_id
    assert sink[ 0 ][ "transition" ] == last_transition == "in_progress->queued"
    assert sink[ 0 ][ "to_status" ]  == "queued"


def test_two_commits_emit_two_pushes_and_the_second_does_not_re_count_the_first( engine, sink ):
    with Session( engine ) as session:
        repo = TaskRepository( session )
        item = _create( session )
        session.commit()
        repo.apply_transition( item, "in_progress", "chloe test", "standing" )
        session.commit()

    assert [ p[ "count" ] for p in sink ] == [ 1, 1 ]
    assert sink[ 1 ][ "transition" ] == "queued->in_progress"


# ---------------------------------------------------------------------------
# Rollback control
# ---------------------------------------------------------------------------

def test_a_rolled_back_session_emits_nothing( engine, sink ):
    with Session( engine ) as session:
        _create( session )
        session.rollback()
        assert session.query( TaskEvent ).count() == 0, "control: the rollback really removed the row"

    assert sink == []


def test_a_rollback_does_not_leak_its_events_into_the_next_commit( engine, sink ):
    with Session( engine ) as session:
        _create( session, title="rolled back" )
        session.rollback()
        _create( session, title="kept" )
        session.commit()

    assert len( sink ) == 1
    assert sink[ 0 ][ "count" ] == 1, "the rolled-back event must not be counted"


def test_get_db_style_exception_path_emits_nothing( engine, sink ):
    """The shape get_db() has: yield, commit on success, rollback and re-raise on error."""
    with pytest.raises( RuntimeError ):
        session = Session( engine )
        try:
            _create( session )
            raise RuntimeError( "handler failed" )
            session.commit()                                  # pragma: no cover — unreachable by design
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    assert sink == []


# ---------------------------------------------------------------------------
# Commits that appended nothing, and no sink
# ---------------------------------------------------------------------------

def test_a_commit_that_appended_no_task_event_emits_nothing( engine, sink ):
    with Session( engine ) as session:
        session.add( TaskItem( id=uuid.uuid4(), item_class="task", title="direct", project="lupin",
                               created_by="chloe test", status="queued", priority="P5", urgency="normal",
                               gate_class="none" ) )
        session.commit()

    assert sink == []


def test_a_commit_with_no_sink_installed_is_a_silent_no_op( engine ):
    previous = notifier.get_sink()
    notifier.set_sink( None )
    try:
        with Session( engine ) as session:
            _create( session )
            session.commit()
            assert session.query( TaskEvent ).count() == 1
    finally:
        notifier.set_sink( previous )


def test_a_failing_sink_does_not_fail_the_commit( engine ):
    previous = notifier.get_sink()
    def boom( payload ): raise RuntimeError( "socket layer down" )
    notifier.set_sink( boom )
    try:
        with Session( engine ) as session:
            _create( session )
            session.commit()
            assert session.query( TaskEvent ).count() == 1, "the row is committed even though the push failed"
    finally:
        notifier.set_sink( previous )


# ---------------------------------------------------------------------------
# Pure helpers and the websocket sink
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "transition,expected", [
    ( "->queued",              "queued" ),
    ( "queued->in_progress",   "in_progress" ),
    ( "in_progress->done",     "done" ),
    ( "patched",               None ),
    ( "chased",                None ),
    ( "weird->",               None ),
] )
def test_to_status_of( transition, expected ):
    assert notifier.to_status_of( transition ) == expected


def test_record_appended_event_tolerates_an_event_without_a_timestamp():
    class _Event:
        id         = 7
        item_id    = uuid.uuid4()
        transition = "patched"
        ts         = None
    session = Session()
    notifier.record_appended_event( session, _Event )
    parked = session.info[ notifier._INFO_KEY ]
    assert parked[ 0 ][ "ts" ] is None
    assert parked[ 0 ][ "to_status" ] is None


def test_install_websocket_sink_emits_the_named_event_with_the_payload():
    class _Manager:
        def __init__( self ): self.calls = []
        def emit( self, event, data ): self.calls.append( ( event, data ) )

    previous = notifier.get_sink()
    manager  = _Manager()
    try:
        notifier.install_websocket_sink( manager )
        notifier.get_sink()( { "count": 1 } )
    finally:
        notifier.set_sink( previous )

    assert manager.calls == [ ( "task_store_changed", { "count": 1 } ) ]


def test_the_event_name_is_in_the_ini_list_the_server_validates_against():
    ini = open( os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "conf", "lupin-app.ini" ) ).read()
    line = [ l for l in ini.splitlines() if l.startswith( "websocket available events" ) ]
    assert len( line ) == 1
    assert notifier.TASK_STORE_CHANGED_EVENT in [ n.strip() for n in line[ 0 ].split( "=", 1 )[ 1 ].split( "," ) ]
