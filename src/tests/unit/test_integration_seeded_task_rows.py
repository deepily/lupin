"""
The seeded-row fixture's guard and bookkeeping (tests/integration/seeded_task_rows.py).

The guard is the control: rows are only ever written to a database named exactly lupin_db_test.
Both outcomes are asserted for every kind of name that could slip past a substring check. The
seeder is driven through a recording stand-in for the session, since the real one needs the
test database; the live path runs when the park and staleness files are scheduled on :8000.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from cosa.rest.postgres_models import TaskEvent, TaskItem
from tests.integration.seeded_task_rows import TEST_DB_NAME, SeededRows, refuse_unless_test_db

TEST_URL = "postgresql://lupin:secret@lupin-postgres:5432/lupin_db_test"


def _url( database ):
    return f"postgresql://lupin:secret@lupin-postgres:5432/{database}"


class _Query:
    def __init__( self, session ): self.session = session
    def filter( self, clause ):
        self.session.filters.append( clause )
        return self
    def delete( self, synchronize_session ):
        self.session.deletes.append( synchronize_session )


class _Session:
    """Records what the seeder does; stamps the server-side defaults the real flush would."""
    def __init__( self ):
        self.added   = []
        self.filters = []
        self.deletes = []
        self.flushes = 0

    def add( self, obj ): self.added.append( obj )

    def flush( self ):
        self.flushes += 1
        for obj in self.added:
            if isinstance( obj, TaskItem ) and obj.id is None: obj.id = uuid.uuid4()

    def refresh( self, item ):
        item.updated_ts = datetime( 2026, 10, 2, 12, 0, tzinfo=timezone.utc )

    def query( self, model ):
        assert model is TaskItem
        return _Query( self )


@pytest.fixture
def session_log():
    return []


@pytest.fixture
def factory( session_log ):
    @contextmanager
    def make():
        session = _Session()
        session_log.append( session )
        yield session
    return make


# ── the guard ────────────────────────────────────────────────────────────────

def test_the_test_database_passes_as_a_string_and_as_a_url_object():
    assert refuse_unless_test_db( TEST_URL ) is None
    assert refuse_unless_test_db( make_url( TEST_URL ) ) is None


@pytest.mark.parametrize( "database", [
    "lupin_db_dev", "lupin_db_prod", "lupin_db",
    "lupin_db_test_copy", "not_lupin_db_test", "LUPIN_DB_TEST", "lupin_db_test ",
] )
def test_every_other_database_name_is_refused_including_lookalikes( database ):
    with pytest.raises( RuntimeError, match="SAFETY" ) as err:
        refuse_unless_test_db( _url( database ) )
    assert repr( database ) in str( err.value ), "the refusal did not name the database it found"


def test_a_url_with_no_database_is_refused():
    with pytest.raises( RuntimeError, match="None" ):
        refuse_unless_test_db( "postgresql://lupin:secret@lupin-postgres:5432" )


def test_a_string_that_is_not_a_url_is_an_error_not_a_pass():
    with pytest.raises( ArgumentError ):
        refuse_unless_test_db( "lupin_db_test" )


def test_a_dev_url_with_the_test_name_in_the_host_or_user_is_refused():
    with pytest.raises( RuntimeError ):
        refuse_unless_test_db( "postgresql://lupin_db_test:x@lupin_db_test:5432/lupin_db_dev" )


def test_the_name_the_guard_compares_against_is_pinned_to_a_literal():
    assert TEST_DB_NAME == "lupin_db_test"


# ── construction ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "database", [ "lupin_db_dev", "lupin_db_prod" ] )
def test_a_seeder_cannot_be_built_against_another_database( database, factory, session_log ):
    with pytest.raises( RuntimeError, match="SAFETY" ):
        SeededRows( _url( database ), factory )
    assert session_log == [], "a session was opened before the guard refused"


def test_a_seeder_built_against_the_test_database_starts_empty( factory ):
    assert SeededRows( TEST_URL, factory ).ids == []


# ── create ───────────────────────────────────────────────────────────────────

def test_create_inserts_one_queued_p5_row_and_its_creation_event( factory, session_log ):
    rows = SeededRows( TEST_URL, factory )
    row  = rows.create( "ac6-abc", "a title", created_by="rachel ac6" )

    item, event = session_log[ 0 ].added
    assert isinstance( item, TaskItem ) and isinstance( event, TaskEvent )
    assert ( item.item_class, item.title, item.project, item.status, item.priority ) == \
           ( "task", "a title", "lupin", "queued", "P5" )
    assert ( item.owner_persona, item.accountable_manager, item.created_by ) == \
           ( "ac6-abc", "ac6-abc", "rachel ac6" )
    assert item.correlation_key == "epic:unassigned"
    assert ( event.item_id, event.actor, event.transition, event.authority ) == \
           ( item.id, "rachel ac6", "->queued", "standing" )
    assert row == { "id": str( item.id ), "status": "queued", "updated_ts": "2026-10-02T12:00:00+00:00" }
    assert rows.ids == [ row[ "id" ] ]


def test_create_honours_a_status_and_the_default_creator( factory, session_log ):
    rows = SeededRows( TEST_URL, factory )
    row  = rows.create( "p", "t", status="in_progress" )
    item, event = session_log[ 0 ].added
    assert item.status == "in_progress" and row[ "status" ] == "in_progress"
    assert event.transition == "->in_progress" and item.created_by == "itest seed"


def test_two_creates_track_two_distinct_ids( factory ):
    rows = SeededRows( TEST_URL, factory )
    a, b = rows.create( "p", "one" ), rows.create( "p", "two" )
    assert a[ "id" ] != b[ "id" ] and rows.ids == [ a[ "id" ], b[ "id" ] ]


def test_create_refuses_when_the_database_changed_after_construction( factory, session_log ):
    rows = SeededRows( TEST_URL, factory )
    rows.db_url = _url( "lupin_db_dev" )
    with pytest.raises( RuntimeError, match="SAFETY" ):
        rows.create( "p", "t" )
    assert session_log == [] and rows.ids == []


# ── delete_all ───────────────────────────────────────────────────────────────

def test_delete_all_with_nothing_seeded_opens_no_session( factory, session_log ):
    SeededRows( TEST_URL, factory ).delete_all()
    assert session_log == []


def test_delete_all_removes_the_tracked_ids_once_and_clears_them( factory, session_log ):
    rows = SeededRows( TEST_URL, factory )
    rows.create( "p", "one" )
    rows.create( "p", "two" )
    opened = len( session_log )

    rows.delete_all()
    assert len( session_log ) == opened + 1
    deleter = session_log[ -1 ]
    assert deleter.deletes == [ False ], "a bulk delete must not try to synchronise the session"
    assert len( deleter.filters ) == 1
    assert rows.ids == []

    rows.delete_all()
    assert len( session_log ) == opened + 1, "a second delete_all opened another session"


def test_delete_all_refuses_when_the_database_changed_after_construction( factory, session_log ):
    rows = SeededRows( TEST_URL, factory )
    rows.create( "p", "one" )
    rows.db_url = _url( "lupin_db_prod" )
    opened = len( session_log )
    with pytest.raises( RuntimeError, match="SAFETY" ):
        rows.delete_all()
    assert len( session_log ) == opened and rows.ids != [], "rows were dropped from tracking unremoved"
