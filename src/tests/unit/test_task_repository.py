#!/usr/bin/env python3
"""
Unit tests for TaskRepository (cosa.rest.db.repositories.task_repository).

MagicMock-session tests (house norm for repositories — no live Postgres,
:7999-eligible): create_item's item+creation-event unit, apply_transition's
blocked/unblocked field handling + event labeling, query_tasks' filter
composition, and get_events' ordering chain.

100% lines/branches/functions of task_repository.py. Real id population +
constraint behavior is the integration suite's job (held behind Lane 1).
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.db.repositories.task_repository import TaskRepository


@pytest.fixture
def session():
    """A MagicMock session whose query() chain returns itself (any chain order)."""
    mock = MagicMock()
    query = mock.query.return_value
    query.filter.return_value          = query
    query.join.return_value            = query
    query.order_by.return_value        = query
    query.limit.return_value           = query
    query.offset.return_value          = query
    query.with_for_update.return_value = query
    return mock


@pytest.fixture
def repo( session ):
    return TaskRepository( session )


def _added_instances( session, model ):
    return [ call.args[ 0 ] for call in session.add.call_args_list
             if isinstance( call.args[ 0 ], model ) ]


# ---------------------------------------------------------------------------
# create_item
# ---------------------------------------------------------------------------

def test_create_item_writes_item_plus_creation_event( repo, session ):
    item = repo.create_item(
        item_class = "task",
        title      = "build the store",
        project    = "lupin",
        created_by = "krishna 38d15e3b",
        authority  = "standing",
    )

    items  = _added_instances( session, TaskItem )
    events = _added_instances( session, TaskEvent )
    assert len( items ) == 1 and items[ 0 ] is item
    assert len( events ) == 1

    event = events[ 0 ]
    assert event.transition   == "->queued"
    assert event.actor        == "krishna 38d15e3b"            # creator IS the creation actor
    assert event.authority    == "standing"
    assert event.receipt_refs is None
    assert session.flush.call_count == 2                       # item flush + event flush


def test_create_item_is_always_queued_with_empty_blocked_by( repo ):
    item = repo.create_item(
        item_class = "decision",
        title      = "pick a substrate",
        project    = "lupin",
        created_by = "maria dbe21f66",
        authority  = "user_direct",
    )
    assert item.status == "queued" and item.blocked_by == [ ]


def test_create_item_passes_optional_fields_through( repo ):
    item = repo.create_item(
        item_class          = "review_request",
        title               = "cold review",
        project             = "planning-is-prompting",
        created_by          = "tiberius f557aab9",
        authority           = "manager_relay",
        body                = "details",
        owner_persona       = "clayton",
        accountable_manager = "tiberius",
        gate_class          = "manager",
        priority            = "P1",
        source_qid          = "fef1f7fa-0000-0000-0000-000000000000",
        correlation_key     = "harness-7",
    )
    assert item.owner_persona == "clayton" and item.accountable_manager == "tiberius"
    assert item.gate_class == "manager" and item.priority == "P1"
    assert item.source_qid.startswith( "fef1f7fa" ) and item.correlation_key == "harness-7"
    assert item.body == "details"


# ---------------------------------------------------------------------------
# apply_transition
# ---------------------------------------------------------------------------

def _item( **overrides ):
    fields = dict(
        id            = uuid.uuid4(),
        item_class    = "task",
        title         = "t",
        project       = "lupin",
        created_by    = "krishna 38d15e3b",
        status        = "in_progress",
        blocked_by    = [ ],
        next_chase_ts = None,
    )
    fields.update( overrides )
    return TaskItem( **fields )


def test_transition_to_blocked_sets_chase_ts_and_refs( repo, session ):
    chase = datetime( 2026, 6, 12, 9, 0, tzinfo=timezone.utc )
    refs  = [ { "kind": "user", "id": "rick" } ]
    item  = _item()

    event = repo.apply_transition(
        item          = item,
        to_status     = "blocked",
        actor         = "krishna 38d15e3b",
        authority     = "standing",
        next_chase_ts = chase,
        blocked_by    = refs,
    )

    assert item.status == "blocked"
    assert item.next_chase_ts == chase and item.blocked_by == refs
    assert event.transition == "in_progress->blocked"
    assert event.item_id == item.id and event.receipt_refs is None


def test_transition_away_from_blocked_clears_block_state( repo ):
    item = _item( status="blocked",
                  next_chase_ts=datetime( 2026, 6, 12, 9, 0, tzinfo=timezone.utc ),
                  blocked_by=[ { "kind": "user", "id": "rick" } ] )

    event = repo.apply_transition(
        item      = item,
        to_status = "in_progress",
        actor     = "krishna 38d15e3b",
        authority = "standing",
    )

    assert item.status == "in_progress"
    assert item.next_chase_ts is None and item.blocked_by == [ ]   # unblocked = blocked on nothing
    assert event.transition == "blocked->in_progress"


def test_transition_to_done_carries_receipts_onto_event( repo, session ):
    receipts = { "commit": "6be15f46", "test_run": "ts-82ae2446" }
    item     = _item( status="review" )

    event = repo.apply_transition(
        item         = item,
        to_status    = "done",
        actor        = "krishna 38d15e3b",
        authority    = "standing",
        receipt_refs = receipts,
    )

    assert item.status == "done"
    assert event.transition == "review->done" and event.receipt_refs == receipts
    added_events = _added_instances( session, TaskEvent )
    assert len( added_events ) == 1 and added_events[ 0 ] is event


# ---------------------------------------------------------------------------
# query_tasks
# ---------------------------------------------------------------------------

def test_query_tasks_no_filters_skips_filter_calls( repo, session ):
    sentinel = [ _item() ]
    query    = session.query.return_value
    query.all.return_value = sentinel

    result = repo.query_tasks()

    assert result is sentinel
    query.filter.assert_not_called()
    query.limit.assert_called_once_with( 100 )
    query.offset.assert_called_once_with( 0 )
    query.order_by.assert_called_once()


def test_query_tasks_applies_every_provided_filter( repo, session ):
    query = session.query.return_value
    query.all.return_value = [ ]

    repo.query_tasks(
        owner_persona       = "krishna",
        status              = "in_progress",
        gate_class          = "ricks_court",
        accountable_manager = "tiberius",
        project             = "lupin",
        item_class          = "task",
        correlation_key     = "cc-task:sid:5",
        limit               = 7,
        offset              = 3,
    )

    assert query.filter.call_count == 7                       # one per provided filter, AND semantics
    query.limit.assert_called_once_with( 7 )
    query.offset.assert_called_once_with( 3 )


@pytest.mark.parametrize( "kwargs, expected_filters", [
    ( { "owner_persona": "krishna" }, 1 ),
    ( { "status": "queued" }, 1 ),
    ( { "gate_class": "manager" }, 1 ),
    ( { "accountable_manager": "tiberius" }, 1 ),
    ( { "project": "lupin" }, 1 ),
    ( { "item_class": "bug" }, 1 ),
    ( { "correlation_key": "cc-task:sid:5" }, 1 ),
    ( { "owner_persona": "krishna", "status": "queued" }, 2 ),
] )
def test_query_tasks_filter_combinations( repo, session, kwargs, expected_filters ):
    query = session.query.return_value
    query.all.return_value = [ ]
    repo.query_tasks( **kwargs )
    assert query.filter.call_count == expected_filters


# ---------------------------------------------------------------------------
# get_by_id_for_update (cold-review N3 — the transition row lock)
# ---------------------------------------------------------------------------

def test_get_by_id_for_update_takes_row_lock( repo, session ):
    """The transition read MUST go through with_for_update — terminal lockout
    is raceable without it (cold-review N3)."""
    sentinel = _item()
    query    = session.query.return_value
    query.first.return_value = sentinel

    result = repo.get_by_id_for_update( sentinel.id )

    assert result is sentinel
    query.with_for_update.assert_called_once_with()
    query.filter.assert_called_once()


def test_get_by_id_for_update_returns_none_when_missing( repo, session ):
    query = session.query.return_value
    query.first.return_value = None
    assert repo.get_by_id_for_update( uuid.uuid4() ) is None
    query.with_for_update.assert_called_once_with()


# ---------------------------------------------------------------------------
# Phase 2 — reason threading (C12 pulled forward)
# ---------------------------------------------------------------------------

def test_transition_to_dropped_carries_reason_onto_event( repo, session ):
    item  = _item( status="queued" )
    event = repo.apply_transition(
        item      = item,
        to_status = "dropped",
        actor     = "tiffany d03e6219",
        authority = "standing",
        reason    = "harness-deleted (TaskUpdate)",
    )
    assert item.status == "dropped"
    assert event.transition == "queued->dropped"
    assert event.reason == "harness-deleted (TaskUpdate)"


def test_transition_reason_defaults_to_none( repo, session ):
    event = repo.apply_transition(
        item      = _item(),
        to_status = "review",
        actor     = "tiffany d03e6219",
        authority = "standing",
    )
    assert event.reason is None


# ---------------------------------------------------------------------------
# Phase 2 — apply_correlation (respawn adoption seam)
# ---------------------------------------------------------------------------

def test_apply_correlation_restamps_key_and_audits( repo, session ):
    item  = _item( correlation_key="cc-task:old-sid:3" )
    event = repo.apply_correlation(
        item            = item,
        correlation_key = "cc-task:new-sid:8",
        actor           = "tiffany d03e6219",
        authority       = "standing",
    )

    assert item.correlation_key == "cc-task:new-sid:8"
    assert item.status == "in_progress"                       # status untouched
    assert event.transition   == "re-correlated"
    assert event.receipt_refs is None
    assert event.reason       == "correlation_key: cc-task:old-sid:3 -> cc-task:new-sid:8"
    assert event.actor        == "tiffany d03e6219"
    added_events = _added_instances( session, TaskEvent )
    assert len( added_events ) == 1 and added_events[ 0 ] is event


def test_apply_correlation_from_null_key_names_none_in_audit( repo, session ):
    item  = _item( correlation_key=None )
    event = repo.apply_correlation(
        item            = item,
        correlation_key = "cc-task:sid:1",
        actor           = "a b",
        authority       = "manager_relay",
    )
    assert event.reason == "correlation_key: None -> cc-task:sid:1"
    assert event.authority == "manager_relay"


# ---------------------------------------------------------------------------
# Phase 2.1 — apply_patch (item-field edit; never touches the oracle fields)
# ---------------------------------------------------------------------------

def test_apply_patch_writes_changed_fields_and_audits_delta( repo, session ):
    item  = _item( title="old title", priority="P2" )
    event = repo.apply_patch(
        item      = item,
        fields    = { "title": "new title", "priority": "P0" },
        actor     = "krishna a38ee857",
        authority = "standing",
    )
    assert item.title    == "new title"
    assert item.priority == "P0"
    assert item.status   == "in_progress"                     # status NEVER touched by a patch
    assert event.transition   == "patched"
    assert event.receipt_refs is None
    assert "title: 'old title' -> 'new title'" in event.reason
    assert "priority: 'P2' -> 'P0'" in event.reason
    added = _added_instances( session, TaskEvent )
    assert len( added ) == 1 and added[ 0 ] is event


def test_apply_patch_skips_unchanged_fields_in_delta( repo ):
    item  = _item( title="same", body="b0" )
    event = repo.apply_patch(
        item      = item,
        fields    = { "title": "same", "body": "b1" },         # title unchanged, body changed
        actor     = "a b",
        authority = "standing",
    )
    assert "title:" not in event.reason                       # unchanged field omitted from the delta
    assert "body: 'b0' -> 'b1'" in event.reason


def test_apply_patch_no_change_records_noop_marker( repo ):
    item  = _item( title="same" )
    event = repo.apply_patch(
        item      = item,
        fields    = { "title": "same" },
        actor     = "a b",
        authority = "standing",
    )
    assert event.reason     == "no-op patch (no field changed)"
    assert event.transition == "patched"


# ---------------------------------------------------------------------------
# Phase 2.1 — query_chase_due + apply_chase (chase consumer support)
# ---------------------------------------------------------------------------

def test_query_chase_due_filters_blocked_and_overdue( repo, session ):
    now      = datetime( 2026, 6, 15, 12, 0, tzinfo=timezone.utc )
    sentinel = [ _item( status="blocked" ) ]
    query    = session.query.return_value
    query.all.return_value = sentinel

    result = repo.query_chase_due( now )

    assert result is sentinel
    session.query.assert_called_once_with( TaskItem )
    query.filter.assert_called_once()                         # status + not-null + <= now in ONE filter
    query.order_by.assert_called_once()
    query.limit.assert_called_once_with( 100 )


def test_apply_chase_rearms_next_chase_and_audits( repo, session ):
    item   = _item( status="blocked", next_chase_ts=datetime( 2026, 6, 15, 9, 0, tzinfo=timezone.utc ) )
    re_arm = datetime( 2026, 6, 15, 12, 30, tzinfo=timezone.utc )

    event = repo.apply_chase( item, actor="task-chase-consumer", authority="standing", next_chase_ts=re_arm )

    assert item.next_chase_ts == re_arm
    assert item.status == "blocked"                           # status NEVER touched by a chase
    assert event.transition   == "chased"
    assert event.receipt_refs is None
    assert event.reason == f"chase re-armed -> {re_arm.isoformat()}"
    added = _added_instances( session, TaskEvent )
    assert len( added ) == 1 and added[ 0 ] is event


# ---------------------------------------------------------------------------
# get_events
# ---------------------------------------------------------------------------

def test_get_events_filters_by_item_and_orders_ascending( repo, session ):
    sentinel = [ TaskEvent( item_id=uuid.uuid4(), actor="a", transition="->queued" ) ]
    query    = session.query.return_value
    query.all.return_value = sentinel

    result = repo.get_events( uuid.uuid4() )

    assert result is sentinel
    session.query.assert_called_once_with( TaskEvent )
    query.filter.assert_called_once()
    query.order_by.assert_called_once()


# ---------------------------------------------------------------------------
# query_events (cross-item stream)
# ---------------------------------------------------------------------------

def test_query_events_no_filters_skips_filter_and_join( repo, session ):
    sentinel = [ TaskEvent( item_id=uuid.uuid4(), actor="a", transition="->queued" ) ]
    query    = session.query.return_value
    query.all.return_value = sentinel

    result = repo.query_events()

    assert result is sentinel
    session.query.assert_called_once_with( TaskEvent )
    query.filter.assert_not_called()
    query.join.assert_not_called()
    query.limit.assert_called_once_with( 100 )
    query.offset.assert_called_once_with( 0 )
    query.order_by.assert_called_once()


def test_query_events_project_filter_joins_task_item( repo, session ):
    query = session.query.return_value
    query.all.return_value = [ ]
    repo.query_events( project="lupin" )
    query.join.assert_called_once()                          # project rides a join to TaskItem
    assert query.filter.call_count == 1                      # the joined project == filter


def test_query_events_applies_every_provided_filter( repo, session ):
    query = session.query.return_value
    query.all.return_value = [ ]
    repo.query_events(
        actor      = "krishna a38ee857",
        transition = "queued->in_progress",
        project    = "lupin",
        since      = datetime( 2026, 6, 1, tzinfo=timezone.utc ),
        until      = datetime( 2026, 6, 30, tzinfo=timezone.utc ),
        limit      = 9,
        offset     = 4,
    )
    query.join.assert_called_once()
    assert query.filter.call_count == 5                      # project + actor + transition + since + until
    query.limit.assert_called_once_with( 9 )
    query.offset.assert_called_once_with( 4 )


@pytest.mark.parametrize( "kwargs, expected_filters, expect_join", [
    ( { "actor": "krishna a38ee857" }, 1, False ),
    ( { "transition": "queued->done" }, 1, False ),
    ( { "since": datetime( 2026, 6, 1, tzinfo=timezone.utc ) }, 1, False ),
    ( { "until": datetime( 2026, 6, 30, tzinfo=timezone.utc ) }, 1, False ),
    ( { "project": "lupin" }, 1, True ),
    ( { "actor": "a", "transition": "queued->done" }, 2, False ),
] )
def test_query_events_filter_combinations( repo, session, kwargs, expected_filters, expect_join ):
    query = session.query.return_value
    query.all.return_value = [ ]
    repo.query_events( **kwargs )
    assert query.filter.call_count == expected_filters
    assert query.join.called is expect_join


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
