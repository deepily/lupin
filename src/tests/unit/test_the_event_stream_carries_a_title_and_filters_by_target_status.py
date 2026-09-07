#!/usr/bin/env python3
"""
D1 for the completed-work accordion — row 2c6a87f3.

Run:  .venv/bin/pytest src/tests/unit/test_the_event_stream_carries_a_title_and_filters_by_target_status.py -q

WHAT THIS DOOR IS FOR. The accordion needs "which rows became terminal in the last 24 hours,
and what are they called". `/api/tasks` cannot answer it — no time window, ordered by
created_ts rather than by when a row finished, and no terminal-timestamp column anywhere. The
event stream can: it windows on event ts and sorts newest-finished-first. Two things stood in
the way, and this file guards both.

  1. `_serialize_event` returned no TITLE, so the most important at-a-glance column was not on
     the wire and a client needed one extra fetch PER EVENT to recover it.
  2. `transition` is EXACT match on a "from->to" string, so "anything -> done" needed 21 calls
     (7 non-terminal sources x 3 terminal targets), and the unfiltered fallback needs 584 rows
     against a cap of 500 — a SILENT truncation.

⚠️ WHAT THE EAGER-LOAD GUARD DOES AND DOES NOT ESTABLISH, said here rather than left implied.
It asserts the readers ATTACH `joinedload( TaskEvent.item )` — so deleting the eager load
reddens a named test. It does NOT count emitted SQL, because these are MagicMock-session tests
(the house norm for this repository) and a mock issues no queries. A real query-count needs
Postgres: `JSONB` will not compile on SQLite, so an in-memory DB here could only test a
hand-mirrored copy of the models rather than the models. The runtime N+1 measurement was taken
separately, read-only against the live dev database, and is recorded on the row.
"""
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest.routers import tasks
from cosa.rest.routers.tasks import require_api_key_or_jwt
from cosa.rest import task_store_rules as rules

NOW = datetime( 2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc )


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def session():
    """A MagicMock session whose query() chain returns itself, `options` included."""
    mock  = MagicMock()
    query = mock.query.return_value
    for attr in ( "filter", "join", "order_by", "limit", "offset", "options" ):
        getattr( query, attr ).return_value = query
    return mock


@pytest.fixture
def query( session ):
    return session.query.return_value


@pytest.fixture
def repo_direct( session ):
    return TaskRepository( session )


def make_event( item_id, item_title="ship the accordion", **overrides ):
    fields = dict(
        id           = 1,
        item_id      = item_id,
        ts           = NOW,
        actor        = "rachel 9948946c",
        transition   = "in_progress->done",
        receipt_refs = None,
        authority    = "standing",
        reason       = None,
    )
    fields.update( overrides )
    event      = TaskEvent( **fields )
    # Attached because production guarantees it — both readers eager-load the relationship.
    event.item = TaskItem( id=item_id, title=item_title )
    return event


@pytest.fixture
def repo( monkeypatch ):
    fake = MagicMock()
    @contextmanager
    def _fake_get_db():
        yield MagicMock()
    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def client( repo ):
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "rachel"
    return TestClient( app )


def _filter_values( query ):
    """Every bound value the repository handed to filter(), as strings."""
    out = [ ]
    for call in query.filter.call_args_list:
        expr = call.args[ 0 ]
        right = getattr( expr, "right", None )
        if right is not None and hasattr( right, "value" ):
            out.append( ( str( expr ), right.value ) )
    return out


# ---------------------------------------------------------------- ① the title on the wire

def test_the_wire_shape_carries_the_owning_items_title( client, repo ):
    """
    The column the accordion cannot be built without. Drop `title` from the serializer and
    this is the test that says so.
    """
    repo.query_events.return_value = [ make_event( uuid.uuid4(), item_title="ship the accordion" ) ]
    r = client.get( "/api/tasks/events" )
    assert r.status_code == 200
    assert r.json()[ "events" ][ 0 ][ "title" ] == "ship the accordion"


def test_the_title_is_the_items_and_not_a_placeholder( client, repo ):
    """
    A second item, a different title. A serializer emitting a constant — or the wrong row's
    title — passes the test above and fails this one.
    """
    a, b = uuid.uuid4(), uuid.uuid4()
    repo.query_events.return_value = [
        make_event( a, id=2, item_title="close the gate" ),
        make_event( b, id=1, item_title="open the door" ),
    ]
    titles = [ e[ "title" ] for e in client.get( "/api/tasks/events" ).json()[ "events" ] ]
    assert titles == [ "close the gate", "open the door" ]


def test_the_existing_wire_keys_are_untouched( client, repo ):
    """
    Adding a key must not quietly remove one — the accordion is not the only reader.
    """
    repo.query_events.return_value = [ make_event( uuid.uuid4() ) ]
    event = client.get( "/api/tasks/events" ).json()[ "events" ][ 0 ]
    for key in ( "id", "item_id", "ts", "actor", "transition", "receipt_refs", "authority", "reason" ):
        assert key in event, f"{key} disappeared from the wire shape"


# ---------------------------------------------------------------- ② the eager load

def test_the_cross_item_stream_eager_loads_the_item_it_serializes( repo_direct, query ):
    """
    Remove the joinedload and the serializer's `event.item.title` becomes one SELECT per event,
    across a page capped at 500. See the module docstring for what this does NOT prove.
    """
    repo_direct.query_events()
    assert query.options.called, "the stream did not eager-load anything"
    path = [ str( element ) for element in query.options.call_args.args[ 0 ].path ]
    assert "TaskEvent.item" in path, f"eager load does not target the item relationship: {path}"


def test_the_per_item_trail_eager_loads_it_too( repo_direct, query ):
    """
    The saving here is one query rather than N — but the serializer's requirement must hold at
    EVERY call site, not only the one where the saving is large.
    """
    repo_direct.get_events( uuid.uuid4() )
    assert query.options.called, "the per-item trail did not eager-load anything"
    path = [ str( element ) for element in query.options.call_args.args[ 0 ].path ]
    assert "TaskEvent.item" in path


# ---------------------------------------------------------------- ③ to_status

def test_to_status_matches_every_source_that_reached_that_target( repo_direct, query ):
    """
    THE POINT OF THE FILTER. `to_status=done` must match `in_progress->done`, `queued->done`
    and every other source — which is what the exact-match `transition` filter cannot do.
    """
    repo_direct.query_events( to_status="done" )
    values = _filter_values( query )
    assert any( "LIKE" in expr and value == "%->done" for expr, value in values ), values


def test_to_status_is_anchored_so_it_cannot_match_a_source( repo_direct, query ):
    """
    The pattern carries the arrow. Without it, `%done` would also match a transition whose
    SOURCE ended in the word — matching the wrong end of the arrow is the whole hazard.
    """
    repo_direct.query_events( to_status="done" )
    values = [ value for _, value in _filter_values( query ) ]
    assert "%->done" in values
    assert "%done" not in values


def test_to_status_and_transition_are_independent_filters( repo_direct, query ):
    """
    Adding a filter must not disturb the one that was already there. Both applied, both bound.
    """
    repo_direct.query_events( transition="queued->done", to_status="done" )
    values = [ value for _, value in _filter_values( query ) ]
    assert "queued->done" in values, "the exact-match transition filter was dropped"
    assert "%->done"      in values, "the to_status filter was dropped"


def test_no_to_status_means_no_extra_filter( repo_direct, query ):
    """
    NEGATIVE CONTROL. An absent to_status must add nothing — an always-on filter would
    silently narrow every existing caller's result.
    """
    repo_direct.query_events()
    values = [ value for _, value in _filter_values( query ) ]
    assert not any( isinstance( v, str ) and v.startswith( "%->" ) for v in values ), values


def test_to_status_composes_with_since_and_project( repo_direct, query ):
    """The accordion asks all three at once: this window, this project, this target status."""
    repo_direct.query_events( to_status="done", project="lupin", since=NOW )
    assert query.join.called, "the project filter stopped joining the item"
    values = [ value for _, value in _filter_values( query ) ]
    assert "%->done" in values and "lupin" in values


def test_the_router_passes_to_status_through( client, repo ):
    repo.query_events.return_value = [ ]
    r = client.get( "/api/tasks/events", params={ "to_status": "done" } )
    assert r.status_code == 200
    assert repo.query_events.call_args.kwargs[ "to_status" ] == "done"


# ---------------------------------------------------------------- ④ junk is refused, not empty

@pytest.mark.parametrize( "bad", [ "Done", "finished", "done ", "%", "wontfix" ] )
def test_an_unknown_to_status_is_refused_rather_than_silently_empty( client, repo, bad ):
    """
    🔴 AN EMPTY RESULT AND A TYPO PRINT THE SAME THING. A caller asking for `finished` must be
    told the value is unknown, never handed `{events: [], count: 0}` to read as "nothing
    reached that status".

    ⚠️ AND `%` IS NOT A COSMETIC CASE. The repository matches with LIKE, so an unvalidated `%`
    would silently widen the query to every event rather than erroring — the refusal is
    load-bearing, not tidiness.
    """
    r = client.get( "/api/tasks/events", params={ "to_status": bad } )
    assert r.status_code == 422
    assert "to_status" in str( r.json() )
    repo.query_events.assert_not_called()


@pytest.mark.parametrize( "good", list( rules.VALID_STATUSES ) )
def test_every_valid_status_is_accepted( client, repo, good ):
    """
    POSITIVE CONTROL for the test above — without it, a handler that 422'd EVERYTHING would
    satisfy the refusal test perfectly. Parametrized over the store's own tuple, so a new
    status joins this guard automatically instead of quietly falling outside it.
    """
    repo.query_events.return_value = [ ]
    r = client.get( "/api/tasks/events", params={ "to_status": good } )
    assert r.status_code == 200, r.text


def test_the_three_terminal_statuses_the_accordion_needs_are_all_valid():
    """
    The pane's three filters are the store's own TERMINAL_STATUSES. If this ever fails, the
    accordion's design has drifted from the store rather than the other way round.
    """
    for status in rules.TERMINAL_STATUSES:
        assert status in rules.VALID_STATUSES
