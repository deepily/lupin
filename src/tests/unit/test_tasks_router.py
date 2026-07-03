#!/usr/bin/env python3
"""
Unit tests for the task-store router — /api/tasks/* (cosa.rest.routers.tasks).

Minimal FastAPI app mounting ONLY the tasks router, with require_api_key_or_jwt
overridden and the get_db/TaskRepository seams monkeypatched — exercises HTTP
routing, structural-rule enforcement at the wire (422 with EVERY violation),
404s, and serialization without auth DB or Postgres (:7999-eligible).

100% lines/branches/functions of routers/tasks.py. All handlers are sync `def`
(C4 debt-clean) — TestClient drives them through the threadpool exactly as
production does.
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
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

NOW = datetime( 2026, 6, 12, 0, 0, tzinfo=timezone.utc )


def make_item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "build the store",
        body                = None,
        project             = "lupin",
        owner_persona       = "krishna",
        accountable_manager = "tiberius",
        created_by          = "krishna 38d15e3b",
        status              = "queued",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P2",
        source_qid          = None,
        correlation_key     = None,
        created_ts          = NOW,
        updated_ts          = NOW,
    )
    fields.update( overrides )
    return TaskItem( **fields )


def make_event( item_id, **overrides ):
    fields = dict(
        id           = 1,
        item_id      = item_id,
        ts           = NOW,
        actor        = "krishna 38d15e3b",
        transition   = "->queued",
        receipt_refs = None,
        authority    = "standing",
    )
    fields.update( overrides )
    return TaskEvent( **fields )


@pytest.fixture
def repo( monkeypatch ):
    """Patch the router's get_db + TaskRepository seams; return the fake repo."""
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
    # Override the credential (X-API-Key / JWT) so we test routing, not auth-DB.
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


_CREATE_BODY = {
    "item_class" : "task",
    "title"      : "build the store",
    "project"    : "lupin",
    "created_by" : "krishna 38d15e3b",
}


# ---------------------------------------------------------------------------
# POST /api/tasks
# ---------------------------------------------------------------------------

def test_create_returns_201_with_serialized_item( client, repo ):
    item = make_item()
    repo.create_item.return_value = item

    r = client.post( "/api/tasks", json=_CREATE_BODY )

    assert r.status_code == 201
    body = r.json()
    assert body[ "id" ] == str( item.id )
    assert body[ "status" ] == "queued" and body[ "item_class" ] == "task"
    assert body[ "created_ts" ] == NOW.isoformat() and body[ "next_chase_ts" ] is None
    repo.create_item.assert_called_once()


def test_create_defaults_flow_to_repository( client, repo ):
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=_CREATE_BODY )
    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "authority" ] == "standing" and kwargs[ "gate_class" ] == "none"
    assert kwargs[ "priority" ] == "P2" and kwargs[ "owner_persona" ] is None


def test_create_under_cap_title_guard_is_none( client, repo ):
    # Soft title guard (design 2026.06.29 §4.3): an under-cap title flows through
    # untouched and the response carries title_guard = None (the no-op advisory).
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=_CREATE_BODY )           # "build the store" — under cap
    assert r.status_code == 201
    assert r.json()[ "title_guard" ] is None
    assert repo.create_item.call_args.kwargs[ "title" ] == "build the store"


def test_create_over_cap_title_trimmed_overflow_to_empty_body( client, repo ):
    # Over-cap title + no body: the SERVER trims the stored title to the cap and
    # moves the overflow into body (non-destructive) BEFORE the repo write.
    long_title = "T" * 90
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, title=long_title ) )
    assert r.status_code == 201
    guard = r.json()[ "title_guard" ]
    assert guard[ "trimmed" ] is True and guard[ "overflow_moved_to_body" ] is True
    assert guard[ "original_length" ] == 90
    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "title" ] == "T" * 60 and kwargs[ "body" ] == "T" * 30   # overflow → body


def test_create_over_cap_title_with_body_trims_only( client, repo ):
    # Over-cap title + existing body: title trimmed, body left UNTOUCHED.
    repo.create_item.return_value = make_item()
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, title="W" * 80, body="keep me" ) )
    assert r.status_code == 201
    guard = r.json()[ "title_guard" ]
    assert guard[ "overflow_moved_to_body" ] is False
    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "title" ] == "W" * 60 and kwargs[ "body" ] == "keep me"   # body never clobbered


def test_create_rejects_bad_enums_with_all_violations( client, repo ):
    bad = dict( _CREATE_BODY, item_class="chore", gate_class="side-gate", priority="P9", authority="by-fiat" )
    r = client.post( "/api/tasks", json=bad )
    assert r.status_code == 422
    assert len( r.json()[ "detail" ][ "errors" ] ) == 4
    repo.create_item.assert_not_called()                       # rejected BEFORE any write


def test_create_rejects_empty_required_fields( client, repo ):
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, title="" ) )
    assert r.status_code == 422                                 # Pydantic min_length
    repo.create_item.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/tasks/{id}/transition
# ---------------------------------------------------------------------------

def _transition_body( **overrides ):
    body = { "to_status": "claimed", "actor": "krishna 38d15e3b" }
    body.update( overrides )
    return body


def test_transition_404_when_item_missing( client, repo ):
    repo.get_by_id_for_update.return_value = None
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body() )
    assert r.status_code == 404 and "not found" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_transition_422_on_malformed_uuid( client, repo ):
    r = client.post( "/api/tasks/not-a-uuid/transition", json=_transition_body() )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


def test_transition_rejects_done_without_receipts( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="review" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body( to_status="done" ) )
    assert r.status_code == 422
    assert any( "receipt_refs" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_transition.assert_not_called()


def test_transition_rejects_leaving_terminal_state( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="done" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body() )
    assert r.status_code == 422
    assert any( "append-only" in e for e in r.json()[ "detail" ][ "errors" ] )


def test_transition_happy_path_returns_item_and_event( client, repo ):
    item  = make_item( status="queued", updated_ts=NOW )       # current status — body moves it to claimed
    event = make_event( item.id, transition="queued->claimed" )
    repo.get_by_id_for_update.return_value         = item
    repo.apply_transition.return_value  = event

    r = client.post( f"/api/tasks/{item.id}/transition", json=_transition_body() )

    assert r.status_code == 200
    body = r.json()
    assert body[ "item" ][ "id" ] == str( item.id )
    assert body[ "event" ][ "transition" ] == "queued->claimed"
    assert body[ "event" ][ "ts" ] == NOW.isoformat() and body[ "event" ][ "authority" ] == "standing"
    kwargs = repo.apply_transition.call_args.kwargs
    assert kwargs[ "to_status" ] == "claimed" and kwargs[ "actor" ] == "krishna 38d15e3b"


def test_transition_to_done_with_valid_receipts_passes_them_through( client, repo ):
    receipts = { "commit": "6be15f46" }
    item     = make_item( status="done" )
    repo.get_by_id_for_update.return_value        = make_item( status="review" )
    repo.apply_transition.return_value = make_event( item.id, transition="review->done", receipt_refs=receipts )

    r = client.post( f"/api/tasks/{item.id}/transition",
                     json=_transition_body( to_status="done", receipt_refs=receipts ) )

    assert r.status_code == 200
    assert r.json()[ "event" ][ "receipt_refs" ] == receipts
    assert repo.apply_transition.call_args.kwargs[ "receipt_refs" ] == receipts


def test_transition_to_blocked_serializes_chase_ts( client, repo ):
    chase = datetime( 2026, 6, 12, 9, 0, tzinfo=timezone.utc )
    refs  = [ { "kind": "user", "id": "rick" } ]
    item  = make_item( status="blocked", next_chase_ts=chase, blocked_by=refs )
    repo.get_by_id_for_update.return_value        = make_item( status="in_progress" )
    repo.apply_transition.return_value = make_event( item.id, transition="in_progress->blocked" )
    repo.get_by_id_for_update.return_value.next_chase_ts = None

    def _apply( **kwargs ):
        loaded               = repo.get_by_id_for_update.return_value
        loaded.status        = "blocked"
        loaded.next_chase_ts = kwargs[ "next_chase_ts" ]
        loaded.blocked_by    = kwargs[ "blocked_by" ]
        return make_event( loaded.id, transition="in_progress->blocked" )
    repo.apply_transition.side_effect = _apply

    r = client.post( f"/api/tasks/{item.id}/transition",
                     json=_transition_body( to_status="blocked",
                                            next_chase_ts=chase.isoformat(),
                                            blocked_by=refs ) )

    assert r.status_code == 200
    body = r.json()
    assert body[ "item" ][ "status" ] == "blocked"
    assert body[ "item" ][ "next_chase_ts" ] == chase.isoformat()   # the non-None serialize branch
    assert body[ "item" ][ "blocked_by" ] == refs


def test_transition_rejects_blocked_without_chase_or_refs( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="in_progress" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body( to_status="blocked" ) )
    assert r.status_code == 422
    assert len( r.json()[ "detail" ][ "errors" ] ) == 2             # chase_ts + blocked_by, all at once


def test_transition_rejects_junk_receipts_on_non_done( client, repo ):
    """N2 at the wire: junk receipts on ->review never reach the audit trail."""
    repo.get_by_id_for_update.return_value = make_item( status="in_progress" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition",
                     json=_transition_body( to_status="review", receipt_refs={ "vibes": "good" } ) )
    assert r.status_code == 422
    assert any( "unknown receipt key 'vibes'" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_transition.assert_not_called()


def test_transition_reads_through_row_lock_seam( client, repo ):
    """N3 code-path: the transition load uses get_by_id_for_update, never the
    plain unlocked get_by_id."""
    repo.get_by_id_for_update.return_value = make_item( status="queued" )
    repo.apply_transition.return_value     = make_event( uuid.uuid4(), transition="queued->claimed" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition", json=_transition_body() )
    assert r.status_code == 200
    repo.get_by_id_for_update.assert_called_once()
    repo.get_by_id.assert_not_called()


def test_transition_rejects_overlong_actor( client, repo ):
    """N5: actor backs VARCHAR(255) on the event — overlong is a 422, not a DB 500."""
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition",
                     json=_transition_body( actor="k" * 256 ) )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/tasks
# ---------------------------------------------------------------------------

def test_query_returns_tasks_and_count( client, repo ):
    repo.query_tasks.return_value = [ make_item(), make_item( status="claimed" ) ]
    r = client.get( "/api/tasks" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "count" ] == 2 and len( body[ "tasks" ] ) == 2


def test_query_count_only_returns_count_without_rows( client, repo ):
    # O2 / §G: count_only=true returns { count } (NO "tasks" key), via count_tasks
    # (the true COUNT(*)), and NEVER materializes rows through query_tasks.
    repo.count_tasks.return_value = 273
    r = client.get( "/api/tasks", params={ "count_only": "true" } )
    assert r.status_code == 200
    assert r.json() == { "count": 273 }                      # >100, no page saturation
    repo.count_tasks.assert_called_once()
    repo.query_tasks.assert_not_called()


def test_query_count_only_forwards_filters_not_pagination( client, repo ):
    repo.count_tasks.return_value = 0
    r = client.get( "/api/tasks", params={
        "owner_persona" : "krishna",
        "status"        : "queued",
        "project"       : "lupin",
        "count_only"    : "true",
        "limit"         : 7,                                  # ignored in count mode
        "offset"        : 3,                                  # ignored in count mode
    } )
    assert r.status_code == 200 and r.json() == { "count": 0 }
    kwargs = repo.count_tasks.call_args.kwargs
    assert kwargs[ "owner_persona" ] == "krishna" and kwargs[ "status" ] == "queued"
    assert kwargs[ "project" ] == "lupin"
    # a count is page-independent — limit/offset are NOT forwarded to count_tasks
    assert "limit" not in kwargs and "offset" not in kwargs


def test_query_count_only_still_validates_enums( client, repo ):
    # The enum gate fires BEFORE the count/list branch — a junk filter is still 422.
    r = client.get( "/api/tasks", params={ "status": "finished", "count_only": "true" } )
    assert r.status_code == 422
    repo.count_tasks.assert_not_called()
    repo.query_tasks.assert_not_called()


def test_query_terse_returns_glance_projection_only( client, repo ):
    # §G: terse=true serializes the at-a-glance projection — EXACTLY the six
    # glance keys, with `body` (and every other full-row field) dropped.
    repo.query_tasks.return_value = [
        make_item( body="a multi-paragraph body that must NOT ride the wire", priority="P1" ),
    ]
    r = client.get( "/api/tasks", params={ "terse": "true" } )
    assert r.status_code == 200
    body = r.json()
    assert body[ "count" ] == 1
    row = body[ "tasks" ][ 0 ]
    assert set( row.keys() ) == { "id", "title", "status", "blocked_by", "next_chase_ts", "priority" }
    assert "body" not in row                                  # the token win — body dropped
    assert row[ "priority" ] == "P1" and row[ "status" ] == "queued"
    repo.query_tasks.assert_called_once()                    # rows ARE materialized (not count mode)
    repo.count_tasks.assert_not_called()


def test_query_terse_serializes_nullable_next_chase_ts( client, repo ):
    # The terse projection's only conditional: next_chase_ts → None when unset.
    repo.query_tasks.return_value = [ make_item( next_chase_ts=NOW ), make_item( next_chase_ts=None ) ]
    r = client.get( "/api/tasks", params={ "terse": "true" } )
    rows = r.json()[ "tasks" ]
    assert rows[ 0 ][ "next_chase_ts" ] == NOW.isoformat()
    assert rows[ 1 ][ "next_chase_ts" ] is None


def test_query_terse_false_returns_full_rows( client, repo ):
    # Default (terse omitted) → the full wire shape, body included (unchanged).
    repo.query_tasks.return_value = [ make_item( body="full body here" ) ]
    r = client.get( "/api/tasks" )
    row = r.json()[ "tasks" ][ 0 ]
    assert row[ "body" ] == "full body here" and "created_ts" in row


def test_query_count_only_precedes_terse( client, repo ):
    # count_only wins over terse — a count needs no rows at all, so query_tasks
    # is never called even when terse is also requested.
    repo.count_tasks.return_value = 5
    r = client.get( "/api/tasks", params={ "count_only": "true", "terse": "true" } )
    assert r.status_code == 200 and r.json() == { "count": 5 }
    repo.count_tasks.assert_called_once()
    repo.query_tasks.assert_not_called()


def test_query_passes_all_filters_through( client, repo ):
    repo.query_tasks.return_value = [ ]
    r = client.get( "/api/tasks", params={
        "owner_persona"       : "krishna",
        "status"              : "in_progress",
        "gate_class"          : "operator",
        "urgency"             : "urgent",
        "accountable_manager" : "tiberius",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : "cc-task:sid:5",
        "limit"               : 7,
        "offset"              : 3,
    } )
    assert r.status_code == 200 and r.json() == { "tasks": [ ], "count": 0 }
    kwargs = repo.query_tasks.call_args.kwargs
    assert kwargs[ "owner_persona" ] == "krishna" and kwargs[ "gate_class" ] == "operator"
    assert kwargs[ "urgency" ] == "urgent"
    assert kwargs[ "correlation_key" ] == "cc-task:sid:5"
    assert kwargs[ "limit" ] == 7 and kwargs[ "offset" ] == 3


@pytest.mark.parametrize( "params, fragment", [
    ( { "status": "finished" }, "status filter" ),
    ( { "gate_class": "side-gate" }, "gate_class filter" ),
    ( { "urgency": "panic" }, "urgency filter" ),
    ( { "item_class": "chore" }, "item_class filter" ),
] )
def test_query_rejects_junk_enum_filters( client, repo, params, fragment ):
    """A typo'd filter is a caller bug surfaced as 422 — never an honest-looking empty result."""
    r = client.get( "/api/tasks", params=params )
    assert r.status_code == 422
    assert any( fragment in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.query_tasks.assert_not_called()


def test_query_reports_multiple_junk_filters_at_once( client, repo ):
    r = client.get( "/api/tasks", params={ "status": "finished", "gate_class": "side-gate", "item_class": "chore" } )
    assert r.status_code == 422 and len( r.json()[ "detail" ][ "errors" ] ) == 3


@pytest.mark.parametrize( "params", [
    { "limit": -1 },          # Postgres InvalidRowCountInLimitClause — was an authenticated 500
    { "limit": 501 },         # above the wire cap
    { "offset": -1 },
] )
def test_query_rejects_out_of_bounds_pagination( client, repo, params ):
    """N4: limit/offset bounds enforced at the wire (Query ge/le), never a DB 500."""
    r = client.get( "/api/tasks", params=params )
    assert r.status_code == 422
    repo.query_tasks.assert_not_called()


@pytest.mark.parametrize( "field, limit", [
    ( "project", 255 ),
    ( "created_by", 255 ),
    ( "owner_persona", 255 ),
    ( "accountable_manager", 255 ),
    ( "source_qid", 64 ),
    ( "correlation_key", 255 ),
] )
def test_create_rejects_overlong_varchar_backed_fields( client, repo, field, limit ):
    """N5: max_length mirrors the VARCHAR widths — overlong is a 422, not a DataError 500."""
    r = client.post( "/api/tasks", json=dict( _CREATE_BODY, **{ field: "x" * ( limit + 1 ) } ) )
    assert r.status_code == 422
    repo.create_item.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/tasks/{id} + /events
# ---------------------------------------------------------------------------

def test_get_task_404_when_missing( client, repo ):
    repo.get_by_id.return_value = None
    r = client.get( f"/api/tasks/{uuid.uuid4()}" )
    assert r.status_code == 404


def test_get_task_returns_serialized_item( client, repo ):
    item = make_item( body="framing payload", source_qid="c8c73fde-6ce4-4e8d-83d7-c55b5cce65a3" )
    repo.get_by_id.return_value = item
    r = client.get( f"/api/tasks/{item.id}" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "body" ] == "framing payload" and body[ "source_qid" ].startswith( "c8c73fde" )


def test_get_events_404_when_item_missing( client, repo ):
    repo.get_by_id.return_value = None
    r = client.get( f"/api/tasks/{uuid.uuid4()}/events" )
    assert r.status_code == 404
    repo.get_events.assert_not_called()


def test_get_events_returns_trail_in_order( client, repo ):
    item = make_item()
    repo.get_by_id.return_value = item
    repo.get_events.return_value = [
        make_event( item.id, id=1, transition="->queued" ),
        make_event( item.id, id=2, transition="queued->claimed",
                    receipt_refs=None, authority="manager_relay" ),
    ]
    r = client.get( f"/api/tasks/{item.id}/events" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "count" ] == 2
    assert [ e[ "transition" ] for e in body[ "events" ] ] == [ "->queued", "queued->claimed" ]
    assert body[ "events" ][ 1 ][ "authority" ] == "manager_relay"


# ---------------------------------------------------------------------------
# Phase 2 — reason on transitions (C12 pulled forward)
# ---------------------------------------------------------------------------

def test_transition_rejects_dropped_without_reason( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="queued" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition",
                     json={ "to_status": "dropped", "actor": "tiffany d03e6219" } )
    assert r.status_code == 422
    assert any( "reason is REQUIRED" in e for e in r.json()[ "detail" ][ "errors" ] )


def test_transition_to_dropped_with_reason_serializes_it( client, repo ):
    item = make_item( status="queued" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = make_event(
        item.id, transition="queued->dropped", reason="superseded-by-rewrite" )

    r = client.post( f"/api/tasks/{item.id}/transition",
                     json={ "to_status": "dropped", "actor": "tiffany d03e6219",
                            "reason": "superseded-by-rewrite" } )

    assert r.status_code == 200
    assert r.json()[ "event" ][ "reason" ] == "superseded-by-rewrite"
    assert repo.apply_transition.call_args.kwargs[ "reason" ] == "superseded-by-rewrite"


def test_transition_reason_defaults_to_none_in_serialization( client, repo ):
    item = make_item( status="queued" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = make_event( item.id, transition="queued->claimed" )
    r = client.post( f"/api/tasks/{item.id}/transition",
                     json={ "to_status": "claimed", "actor": "a b" } )
    assert r.status_code == 200 and r.json()[ "event" ][ "reason" ] is None


def test_transition_rejects_overlong_reason( client, repo ):
    r = client.post( f"/api/tasks/{uuid.uuid4()}/transition",
                     json={ "to_status": "dropped", "actor": "a b", "reason": "x" * 4001 } )
    assert r.status_code == 422   # Pydantic max_length — never a DB error


# ---------------------------------------------------------------------------
# Phase 2 — POST /api/tasks/{id}/correlate (respawn adoption)
# ---------------------------------------------------------------------------

_CORRELATE_BODY = { "correlation_key": "cc-task:new-sid:8", "actor": "tiffany d03e6219" }


def test_correlate_404_when_missing( client, repo ):
    repo.get_by_id_for_update.return_value = None
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate", json=_CORRELATE_BODY )
    assert r.status_code == 404


def test_correlate_422_on_malformed_uuid( client, repo ):
    r = client.post( "/api/tasks/not-a-uuid/correlate", json=_CORRELATE_BODY )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


@pytest.mark.parametrize( "terminal", [ "done", "dropped" ] )
def test_correlate_rejects_terminal_items( client, repo, terminal ):
    repo.get_by_id_for_update.return_value = make_item( status=terminal )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate", json=_CORRELATE_BODY )
    assert r.status_code == 422
    assert any( "immutable" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_correlation.assert_not_called()


def test_correlate_rejects_bad_authority( client, repo ):
    repo.get_by_id_for_update.return_value = make_item()
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate",
                     json={ **_CORRELATE_BODY, "authority": "divine_right" } )
    assert r.status_code == 422
    assert any( "authority" in e for e in r.json()[ "detail" ][ "errors" ] )


def test_correlate_reports_terminal_and_authority_together( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="done" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate",
                     json={ **_CORRELATE_BODY, "authority": "divine_right" } )
    assert r.status_code == 422 and len( r.json()[ "detail" ][ "errors" ] ) == 2


def test_correlate_happy_path_returns_item_and_event( client, repo ):
    item = make_item( correlation_key="cc-task:old-sid:3" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_correlation.return_value = make_event(
        item.id, transition="re-correlated",
        reason="correlation_key: cc-task:old-sid:3 -> cc-task:new-sid:8" )

    r = client.post( f"/api/tasks/{item.id}/correlate", json=_CORRELATE_BODY )

    assert r.status_code == 200
    body = r.json()
    assert body[ "event" ][ "transition" ] == "re-correlated"
    assert body[ "event" ][ "reason" ].endswith( "-> cc-task:new-sid:8" )
    kwargs = repo.apply_correlation.call_args.kwargs
    assert kwargs[ "correlation_key" ] == "cc-task:new-sid:8"
    assert kwargs[ "actor" ] == "tiffany d03e6219" and kwargs[ "authority" ] == "standing"
    # Row-locked read (N3 parity): the terminal check must not be raceable.
    repo.get_by_id_for_update.assert_called_once()
    repo.get_by_id.assert_not_called()


@pytest.mark.parametrize( "field,limit", [ ( "correlation_key", 255 ), ( "actor", 255 ) ] )
def test_correlate_rejects_overlong_fields( client, repo, field, limit ):
    r = client.post( f"/api/tasks/{uuid.uuid4()}/correlate",
                     json={ **_CORRELATE_BODY, field: "x" * ( limit + 1 ) } )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Phase 2.1 — PATCH /api/tasks/{id} (item-field edit)
# ---------------------------------------------------------------------------

_PATCH_BODY = { "title": "edited title", "actor": "krishna a38ee857" }


def test_patch_happy_path_returns_item_and_event( client, repo ):
    item = make_item( title="old title" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event(
        item.id, transition="patched", reason="title: 'old title' -> 'edited title'" )

    r = client.patch( f"/api/tasks/{item.id}", json=_PATCH_BODY )

    assert r.status_code == 200
    body = r.json()
    assert body[ "event" ][ "transition" ] == "patched"
    args, kwargs = repo.apply_patch.call_args.args, repo.apply_patch.call_args.kwargs
    assert args[ 1 ] == { "title": "edited title" }              # fields passed positionally; actor/authority excluded from it
    assert kwargs[ "actor" ] == "krishna a38ee857" and kwargs[ "authority" ] == "standing"
    repo.get_by_id_for_update.assert_called_once()               # N3 row-lock parity
    repo.get_by_id.assert_not_called()


def test_patch_empty_editable_set_rejected( client, repo ):
    # Only actor, no editable field → 422 before any DB touch.
    r = client.patch( f"/api/tasks/{uuid.uuid4()}", json={ "actor": "a b" } )
    assert r.status_code == 422
    assert any( "at least one editable field" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.get_by_id_for_update.assert_not_called()
    repo.apply_patch.assert_not_called()


@pytest.mark.parametrize( "forbidden", [
    { "status": "done" },
    { "correlation_key": "cc-task:x:1" },
    { "blocked_by": [ ] },
    { "next_chase_ts": "2026-06-15T00:00:00+00:00" },
    { "receipt_refs": { "commit": "abc1234" } },
] )
def test_patch_forbids_oracle_fields_at_the_wire( client, repo, forbidden ):
    # extra='forbid' — naming a transition-oracle field is a 422, never a silent
    # drop. The hard no-bypass invariant (reviewer ruling 2026-06-15).
    r = client.patch( f"/api/tasks/{uuid.uuid4()}", json={ **forbidden, "actor": "a b" } )
    assert r.status_code == 422
    repo.apply_patch.assert_not_called()


def test_patch_rejects_junk_enum_fields( client, repo ):
    r = client.patch( f"/api/tasks/{uuid.uuid4()}",
                      json={ "priority": "P9", "gate_class": "side-gate", "actor": "a b" } )
    assert r.status_code == 422
    errors = r.json()[ "detail" ][ "errors" ]
    assert any( "priority" in e for e in errors ) and any( "gate_class" in e for e in errors )
    repo.get_by_id_for_update.assert_not_called()


def test_patch_rejects_bad_authority( client, repo ):
    r = client.patch( f"/api/tasks/{uuid.uuid4()}",
                      json={ **_PATCH_BODY, "authority": "divine_right" } )
    assert r.status_code == 422
    assert any( "authority" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.get_by_id_for_update.assert_not_called()


def test_patch_404_when_missing( client, repo ):
    repo.get_by_id_for_update.return_value = None
    r = client.patch( f"/api/tasks/{uuid.uuid4()}", json=_PATCH_BODY )
    assert r.status_code == 404
    repo.apply_patch.assert_not_called()


@pytest.mark.parametrize( "terminal", [ "done", "dropped" ] )
def test_patch_rejects_terminal_items( client, repo, terminal ):
    repo.get_by_id_for_update.return_value = make_item( status=terminal )
    r = client.patch( f"/api/tasks/{uuid.uuid4()}", json=_PATCH_BODY )
    assert r.status_code == 422
    assert any( "terminal" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_patch.assert_not_called()


def test_patch_422_on_malformed_uuid( client, repo ):
    r = client.patch( "/api/tasks/not-a-uuid", json=_PATCH_BODY )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/tasks/events (cross-item stream)
# ---------------------------------------------------------------------------

def test_event_stream_returns_events_and_count( client, repo ):
    item_id = uuid.uuid4()
    repo.query_events.return_value = [
        make_event( item_id, id=2, transition="queued->in_progress" ),
        make_event( item_id, id=1, transition="->queued" ),
    ]
    r = client.get( "/api/tasks/events" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "count" ] == 2 and len( body[ "events" ] ) == 2
    assert body[ "events" ][ 0 ][ "transition" ] == "queued->in_progress"


def test_event_stream_static_path_wins_over_uuid_route( client, repo ):
    # /tasks/events must resolve to the stream handler, NOT /tasks/{task_id}
    # (which would 422 parsing "events" as a UUID). Declaration order is the
    # guarantee — pin it so a future reorder can't silently regress it.
    repo.query_events.return_value = [ ]
    r = client.get( "/api/tasks/events" )
    assert r.status_code == 200
    repo.query_events.assert_called_once()
    repo.get_by_id.assert_not_called()                       # the per-item route is never touched


def test_event_stream_passes_all_filters_through( client, repo ):
    repo.query_events.return_value = [ ]
    r = client.get( "/api/tasks/events", params={
        "actor"      : "krishna a38ee857",
        "transition" : "queued->done",
        "project"    : "lupin",
        "since"      : "2026-06-01T00:00:00+00:00",
        "until"      : "2026-06-30T00:00:00+00:00",
        "limit"      : 12,
        "offset"     : 6,
    } )
    assert r.status_code == 200 and r.json() == { "events": [ ], "count": 0 }
    kwargs = repo.query_events.call_args.kwargs
    assert kwargs[ "actor" ]      == "krishna a38ee857"
    assert kwargs[ "transition" ] == "queued->done"
    assert kwargs[ "project" ]    == "lupin"
    assert kwargs[ "since" ].isoformat() == "2026-06-01T00:00:00+00:00"
    assert kwargs[ "until" ].isoformat() == "2026-06-30T00:00:00+00:00"
    assert kwargs[ "limit" ] == 12 and kwargs[ "offset" ] == 6


@pytest.mark.parametrize( "params", [
    { "limit": -1 },
    { "offset": -1 },
    { "limit": 501 },
] )
def test_event_stream_rejects_out_of_bounds_pagination( client, repo, params ):
    r = client.get( "/api/tasks/events", params=params )
    assert r.status_code == 422
    repo.query_events.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 2 — persona-identity canonicalization at the /api/tasks choke point.
# Each test is a FLIP: it asserts the value REACHING the repo (write) or the
# repo query (read) is the canonical store key. Revert the router's _canon_*
# helpers to the raw payload value and the "maria"/"mr radio" assertions fail.
# ---------------------------------------------------------------------------

def test_create_canonicalizes_owner_and_manager_FLIP( client, repo ):
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY,
                 owner_persona="María", accountable_manager="Mr. Radio" ) )
    kwargs = repo.create_item.call_args.kwargs
    assert kwargs[ "owner_persona" ]       == "maria"        # was "María"
    assert kwargs[ "accountable_manager" ] == "mr radio"     # was "Mr. Radio"


def test_create_blank_persona_stays_none( client, repo ):
    # A blank owner canonicalizes to None (a falsy create field stays falsy —
    # never the "" sentinel) so it does not turn into an empty-string owner.
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY, owner_persona="  !!  " ) )
    assert repo.create_item.call_args.kwargs[ "owner_persona" ] is None


def test_query_canonicalizes_owner_filter_FLIP( client, repo ):
    # The READ seam — the direct fix for the 2026-06-18 false-idle: a "María"
    # filter must query the store's "maria" rows.
    repo.query_tasks.return_value = [ ]
    client.get( "/api/tasks", params={ "owner_persona": "María", "accountable_manager": "Mr. Radio" } )
    kwargs = repo.query_tasks.call_args.kwargs
    assert kwargs[ "owner_persona" ]       == "maria"
    assert kwargs[ "accountable_manager" ] == "mr radio"


def test_count_only_canonicalizes_owner_filter_FLIP( client, repo ):
    repo.count_tasks.return_value = 0
    client.get( "/api/tasks", params={ "owner_persona": "Mr. Radio", "count_only": "true" } )
    assert repo.count_tasks.call_args.kwargs[ "owner_persona" ] == "mr radio"


def test_transition_canonicalizes_persona_blocked_by_FLIP( client, repo ):
    # A persona-typed blocked_by ref ("Mr. Radio") is stored canonical so a
    # "blocked on Mr. Radio" item lines up with that persona's owner rows; a
    # user-typed ref is left untouched (only kind=="persona" is canonicalized).
    item  = make_item( status="claimed", updated_ts=NOW )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value     = make_event( item.id, transition="claimed->blocked" )
    blocked = [ { "kind": "persona", "id": "Mr. Radio" }, { "kind": "user", "id": "Rick" } ]
    client.post( f"/api/tasks/{item.id}/transition",
                 json=_transition_body( to_status="blocked",
                                        next_chase_ts="2026-06-30T00:00:00+00:00",
                                        blocked_by=blocked ) )
    sent = repo.apply_transition.call_args.kwargs[ "blocked_by" ]
    assert sent[ 0 ] == { "kind": "persona", "id": "mr radio" }   # was "Mr. Radio"
    assert sent[ 1 ] == { "kind": "user", "id": "Rick" }          # user ref untouched


def test_patch_canonicalizes_owner_persona_FLIP( client, repo ):
    # Re-owning an item via PATCH must store the canonical key, same as create.
    item = make_item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_patch.return_value = make_event( item.id, transition="patched" )
    client.patch( f"/api/tasks/{item.id}",
                  json={ "owner_persona": "María", "actor": "krishna a38ee857" } )
    fields = repo.apply_patch.call_args.args[ 1 ]
    assert fields[ "owner_persona" ] == "maria"                   # was "María"


# ---------------------------------------------------------------------------
# Bug de653086 — project-alias canonicalization at the /api/tasks choke point.
# The project-axis twin of the persona FLIPs above: each asserts the project
# value REACHING the repo (write) or the repo query (read) is the canonical
# alias form ("planning-is-prompting" -> "plan"). Revert the router's
# _canon_project helper to the raw payload value and the "plan" assertions
# fail. Closes the false-idle gap where a row written under the raw repo name
# splits out of the owed-oracle's alias-normalized project filter.
# ---------------------------------------------------------------------------

def test_create_canonicalizes_project_FLIP( client, repo ):
    # A new row must store the canonical alias form, so the owed-oracle (which
    # queries project="plan") finds it — symmetric with persona canonicalization.
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY, project="planning-is-prompting" ) )
    assert repo.create_item.call_args.kwargs[ "project" ] == "plan"   # was "planning-is-prompting"


def test_create_non_aliased_project_unchanged( client, repo ):
    # A non-aliased repo name is returned verbatim (idempotent / no false rewrite).
    repo.create_item.return_value = make_item()
    client.post( "/api/tasks", json=dict( _CREATE_BODY, project="lupin" ) )
    assert repo.create_item.call_args.kwargs[ "project" ] == "lupin"


def test_query_canonicalizes_project_filter_FLIP( client, repo ):
    # The READ seam: a query by the raw repo name must match rows stored under
    # the canonical alias — read and write agree on one form at the server.
    repo.query_tasks.return_value = [ ]
    client.get( "/api/tasks", params={ "project": "planning-is-prompting" } )
    assert repo.query_tasks.call_args.kwargs[ "project" ] == "plan"


def test_count_only_canonicalizes_project_filter_FLIP( client, repo ):
    repo.count_tasks.return_value = 0
    client.get( "/api/tasks", params={ "project": "planning-is-prompting", "count_only": "true" } )
    assert repo.count_tasks.call_args.kwargs[ "project" ] == "plan"


# ---------------------------------------------------------------------------
# Phase 2.2 — POST /api/tasks/{id}/amend (append-only body amendment)
# ---------------------------------------------------------------------------

_AMEND_BODY = { "note": "SCOPE REFRAME: subscriber path now.", "actor": "arnold 8b7225c4" }


def test_amend_404_when_missing( client, repo ):
    repo.get_by_id_for_update.return_value = None
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend", json=_AMEND_BODY )
    assert r.status_code == 404
    repo.apply_amendment.assert_not_called()


def test_amend_422_on_malformed_uuid( client, repo ):
    r = client.post( "/api/tasks/not-a-uuid/amend", json=_AMEND_BODY )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


@pytest.mark.parametrize( "terminal", [ "done", "dropped" ] )
def test_amend_rejects_terminal_items( client, repo, terminal ):
    repo.get_by_id_for_update.return_value = make_item( status=terminal )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend", json=_AMEND_BODY )
    assert r.status_code == 422
    assert any( "closed history" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_amendment.assert_not_called()


def test_amend_rejects_bad_authority( client, repo ):
    repo.get_by_id_for_update.return_value = make_item()
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "authority": "divine_right" } )
    assert r.status_code == 422
    assert any( "authority" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_amendment.assert_not_called()


def test_amend_rejects_blank_note( client, repo ):
    # min_length=1 lets a whitespace-only note THROUGH the wire; the handler's
    # strip-guard rejects it so no meaningless empty amendment block is written.
    repo.get_by_id_for_update.return_value = make_item()
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "note": "   " } )
    assert r.status_code == 422
    assert any( "note" in e for e in r.json()[ "detail" ][ "errors" ] )
    repo.apply_amendment.assert_not_called()


def test_amend_rejects_empty_note_at_wire( client, repo ):
    # An empty-string note is a Pydantic min_length 422 BEFORE the handler runs.
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "note": "" } )
    assert r.status_code == 422
    repo.get_by_id_for_update.assert_not_called()


def test_amend_reports_all_violations_together( client, repo ):
    repo.get_by_id_for_update.return_value = make_item( status="done" )
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, "authority": "divine_right", "note": "   " } )
    # bad authority + blank note + terminal item -> all three at once.
    assert r.status_code == 422 and len( r.json()[ "detail" ][ "errors" ] ) == 3


def test_amend_happy_path_returns_item_and_event( client, repo ):
    item = make_item( body="ORIGINAL." )
    repo.get_by_id_for_update.return_value = item
    repo.apply_amendment.return_value = make_event(
        item.id, transition="amended", reason="manager ruling" )

    r = client.post( f"/api/tasks/{item.id}/amend",
                     json={ **_AMEND_BODY, "reason": "manager ruling" } )

    assert r.status_code == 200
    body = r.json()
    assert body[ "event" ][ "transition" ] == "amended"
    kwargs = repo.apply_amendment.call_args.kwargs
    assert kwargs[ "note" ]      == "SCOPE REFRAME: subscriber path now."
    assert kwargs[ "actor" ]     == "arnold 8b7225c4"
    assert kwargs[ "authority" ] == "standing"
    assert kwargs[ "reason" ]    == "manager ruling"
    # The router owns the clock -> passes a tz-aware datetime the repo stamps.
    assert kwargs[ "now" ].tzinfo is not None
    # Row-locked read (N3 parity): the terminal check must not be raceable.
    repo.get_by_id_for_update.assert_called_once()
    repo.get_by_id.assert_not_called()


@pytest.mark.parametrize( "field,limit", [ ( "note", 4000 ), ( "actor", 255 ), ( "reason", 4000 ) ] )
def test_amend_rejects_overlong_fields( client, repo, field, limit ):
    r = client.post( f"/api/tasks/{uuid.uuid4()}/amend",
                     json={ **_AMEND_BODY, field: "x" * ( limit + 1 ) } )
    assert r.status_code == 422   # Pydantic max_length — never a DB error


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
