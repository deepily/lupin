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
    query.group_by.return_value        = query
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
        urgency             = "urgent",
        source_qid          = "fef1f7fa-0000-0000-0000-000000000000",
        correlation_key     = "harness-7",
    )
    assert item.owner_persona == "clayton" and item.accountable_manager == "tiberius"
    assert item.gate_class == "manager" and item.priority == "P1" and item.urgency == "urgent"
    assert item.source_qid.startswith( "fef1f7fa" ) and item.correlation_key == "harness-7"
    assert item.body == "details"


# create_item — one-call BLOCKED mint (Rick's ruling 2026-07-20, build 1b5483f4)

def test_create_item_blocked_mint_persists_fields_and_stamps_blocked_event( repo, session ):
    # A blocked mint sets status='blocked', persists blocked_by + next_chase_ts,
    # and the creation event's transition label is '->blocked' (not '->queued').
    refs  = [ { "kind": "persona", "id": "tiberius" } ]
    chase = datetime( 2026, 6, 12, 9, 0, tzinfo=timezone.utc )
    item  = repo.create_item(
        item_class    = "task",
        title         = "held on tiberius",
        project       = "lupin",
        created_by    = "mr radio 372f9dc9",
        authority     = "manager_relay",
        status        = "blocked",
        blocked_by    = refs,
        next_chase_ts = chase,
    )
    assert item.status == "blocked"
    assert item.blocked_by == refs and item.next_chase_ts == chase
    event = _added_instances( session, TaskEvent )[ 0 ]
    assert event.transition == "->blocked"                      # label follows the mint status


def test_create_item_blocked_mint_none_blocked_by_defaults_to_empty( repo ):
    # A blocked mint given blocked_by=None resolves to [] (the None→[] branch) —
    # the DB CHECK still holds (a []-blocked row has no persona ref → no chase req).
    item = repo.create_item(
        item_class    = "task",
        title         = "held, refs TBD",
        project       = "lupin",
        created_by    = "mr radio 372f9dc9",
        authority     = "standing",
        status        = "blocked",
        blocked_by    = None,
        next_chase_ts = None,
    )
    assert item.status == "blocked" and item.blocked_by == [ ] and item.next_chase_ts is None


def test_create_item_queued_mint_drops_stray_blocked_by_but_KEEPS_the_chase( repo ):
    # CHANGED 2026-07-21 (86ce4c43 #2, Mr Radio GO). This test previously asserted
    # that a queued mint nulled next_chase_ts too. That assertion encoded the
    # DEFECT: a caller who scheduled a row got a 200 and an unscheduled row,
    # silently, on the success path. Measured consequence — 47 of 51 operator
    # gates carry no chase, and ZERO queued gates have one fleet-wide, all-time.
    #
    # The asymmetry below is the fix: blocked_by is a DEPENDENCY whose meaning is
    # defined by the blocked status, so a queued row genuinely holds none. A chase
    # is a SCHEDULE and is independent of status. "A queued row waits on nothing"
    # is true about dependencies and says nothing about scheduling.
    #
    # Both paths now route through normalize_status_fields — see
    # test_task_store_field_normalizer.py for the anti-divergence parity test.
    chase = datetime( 2026, 6, 12, 9, 0, tzinfo=timezone.utc )
    item  = repo.create_item(
        item_class    = "task",
        title         = "just queued",
        project       = "lupin",
        created_by    = "krishna 38d15e3b",
        authority     = "standing",
        status        = "queued",
        blocked_by    = [ { "kind": "persona", "id": "tiberius" } ],   # stray — must be dropped
        next_chase_ts = chase,                                         # a SCHEDULE — must SURVIVE
    )
    assert item.status == "queued" and item.blocked_by == [ ]
    assert item.next_chase_ts == chase


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
    # unscoped_audit=True + include_terminal=True reproduces the PRE-guard "raw,
    # all-status" query_tasks() so this test isolates the filter-application
    # mechanics (no guard COUNT(*), no terminal-exclusion filter) — the guard and
    # terminal-default behaviors are covered by their own tests below.
    sentinel = [ _item() ]
    query    = session.query.return_value
    query.all.return_value = sentinel

    result = repo.query_tasks( unscoped_audit=True, include_terminal=True )

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
        gate_class          = "operator",
        urgency             = "urgent",
        accountable_manager = "tiberius",
        project             = "lupin",
        item_class          = "task",
        correlation_key     = "cc-task:sid:5",
        limit               = 7,
        offset              = 3,
    )

    assert query.filter.call_count == 8                       # one per provided filter, AND semantics
    query.limit.assert_called_once_with( 7 )
    query.offset.assert_called_once_with( 3 )


@pytest.mark.parametrize( "kwargs, expected_filters", [
    ( { "owner_persona": "krishna" }, 1 ),
    ( { "status": "queued" }, 1 ),
    ( { "gate_class": "manager" }, 1 ),
    ( { "urgency": "low" }, 1 ),
    ( { "accountable_manager": "tiberius" }, 1 ),
    ( { "project": "lupin" }, 1 ),
    ( { "item_class": "bug" }, 1 ),
    ( { "correlation_key": "cc-task:sid:5" }, 1 ),
    ( { "owner_persona": "krishna", "status": "queued" }, 2 ),
] )
def test_query_tasks_filter_combinations( repo, session, kwargs, expected_filters ):
    query = session.query.return_value
    query.all.return_value = [ ]
    # include_terminal=True + unscoped_audit=True → the raw pre-guard path, so the
    # filter count equals exactly the provided-filter count (no terminal-exclusion
    # filter, no guard COUNT(*) that a urgency-only unscoped case would otherwise trip).
    repo.query_tasks( include_terminal=True, unscoped_audit=True, **kwargs )
    assert query.filter.call_count == expected_filters


# ---------------------------------------------------------------------------
# count_tasks (O2 / §G — true COUNT(*), no row materialization)
# ---------------------------------------------------------------------------

def test_count_tasks_no_filters_returns_scalar_no_pagination( repo, session ):
    query = session.query.return_value
    query.scalar.return_value = 273                            # >100: no page saturation
    # include_terminal=True → count every status (the pre-terminal-default count),
    # so this test stays about pagination/ordering, not terminal exclusion.
    result = repo.count_tasks( include_terminal=True )
    assert result == 273
    query.filter.assert_not_called()
    query.scalar.assert_called_once()
    # a count is order- and page-independent — never ordered/limited/offset
    query.order_by.assert_not_called()
    query.limit.assert_not_called()
    query.offset.assert_not_called()


def test_count_tasks_applies_every_provided_filter( repo, session ):
    query = session.query.return_value
    query.scalar.return_value = 0
    repo.count_tasks(
        owner_persona       = "krishna",
        status              = "in_progress",
        gate_class          = "operator",
        urgency             = "urgent",
        accountable_manager = "tiberius",
        project             = "lupin",
        item_class          = "task",
        correlation_key     = "cc-task:sid:5",
    )
    assert query.filter.call_count == 8                       # one per provided filter, AND semantics


@pytest.mark.parametrize( "kwargs, expected_filters", [
    ( { "owner_persona": "krishna" }, 1 ),
    ( { "status": "queued" }, 1 ),
    ( { "gate_class": "manager" }, 1 ),
    ( { "urgency": "low" }, 1 ),
    ( { "accountable_manager": "tiberius" }, 1 ),
    ( { "project": "lupin" }, 1 ),
    ( { "item_class": "bug" }, 1 ),
    ( { "correlation_key": "cc-task:sid:5" }, 1 ),
    ( { "owner_persona": "krishna", "status": "queued" }, 2 ),
] )
def test_count_tasks_filter_combinations( repo, session, kwargs, expected_filters ):
    query = session.query.return_value
    query.scalar.return_value = 0
    # include_terminal=True → no terminal-exclusion filter, so the filter count
    # equals exactly the provided-filter count regardless of whether status is set.
    repo.count_tasks( include_terminal=True, **kwargs )
    assert query.filter.call_count == expected_filters


# ---------------------------------------------------------------------------
# count_tasks_by_status (c191be39 — the per-status breakdown, ONE GROUP BY)
# ---------------------------------------------------------------------------

def test_count_tasks_by_status_groups_once_no_pagination( repo, session ):
    query = session.query.return_value
    query.all.return_value = [ ( "in_progress", 2 ), ( "queued", 13 ), ( "parked", 1 ) ]

    result = repo.count_tasks_by_status( owed_only=True )

    assert result == { "in_progress": 2, "queued": 13, "parked": 1 }
    # ⛔ ONE GROUP BY — not one query per status. The forbidden shape (deleted
    # 2026-07-19) fired N queries and summed; it could not see a park-expiry rejoin
    # and double-counted expired-parked rows. A GROUP BY partitions ONE admitted
    # set, so every row lands in exactly one bucket by construction.
    query.group_by.assert_called_once()
    # a breakdown is order- and page-independent
    query.order_by.assert_not_called()
    query.limit.assert_not_called()
    query.offset.assert_not_called()


def test_count_tasks_by_status_empty_result_is_empty_dict( repo, session ):
    session.query.return_value.all.return_value = [ ]
    assert repo.count_tasks_by_status( owed_only=True ) == { }


def test_count_tasks_by_status_omits_absent_statuses_never_zero_fills( repo, session ):
    """
    A zero-filled key is a CLAIM about a status the query never saw. Only statuses
    actually present in the admitted set appear.
    """
    session.query.return_value.all.return_value = [ ( "queued", 4 ) ]
    result = repo.count_tasks_by_status( owed_only=True )
    assert result == { "queued": 4 }
    assert "in_progress" not in result and "parked" not in result


def test_count_tasks_by_status_applies_every_provided_filter( repo, session ):
    query = session.query.return_value
    query.all.return_value = [ ]
    repo.count_tasks_by_status(
        owner_persona       = "krishna",
        status              = "in_progress",
        gate_class          = "operator",
        urgency             = "urgent",
        accountable_manager = "tiberius",
        project             = "lupin",
        item_class          = "task",
        correlation_key     = "cc-task:sid:5",
    )
    assert query.filter.call_count == 8                        # one per provided filter, AND semantics


def test_count_tasks_by_status_filter_set_matches_count_tasks_exactly( repo, session ):
    """
    🔴 THE PARITY PRECONDITION. `count` and `breakdown` are two INDEPENDENT queries
    whose sum must agree — which is only meaningful if they select the SAME
    population. If one grows a filter the other lacks, the sum-parity gate silently
    starts comparing two different boards and its green stops meaning anything.

    Asserted on the filter COUNT for an identical kwargs set, which is what would
    diverge if a filter were added to one method and not the other.
    """
    kwargs = {
        "owner_persona"       : "krishna",
        "status"              : "queued",
        "gate_class"          : "operator",
        "urgency"             : "urgent",
        "accountable_manager" : "tiberius",
        "project"             : "lupin",
        "item_class"          : "task",
        "correlation_key"     : "cc-task:sid:5",
        "include_terminal"    : True,
    }
    query = session.query.return_value

    query.scalar.return_value = 0
    repo.count_tasks( **kwargs )
    count_filters = query.filter.call_count

    query.filter.reset_mock()
    query.all.return_value = [ ]
    repo.count_tasks_by_status( **kwargs )
    breakdown_filters = query.filter.call_count

    assert count_filters == breakdown_filters, (
        "count_tasks and count_tasks_by_status no longer select the same population — "
        "the sum-parity gate is comparing two different boards" )


# ---------------------------------------------------------------------------
# Unscoped-query guard + terminal-exclusion default (design 2026.07.07)
# ---------------------------------------------------------------------------

from cosa.rest.task_store_rules import UnscopedQueryError, UNSCOPED_QUERY_THRESHOLD


def test_query_tasks_guard_fires_on_bare_unscoped_over_threshold( repo, session ):
    # A BARE unscoped pull whose non-terminal COUNT(*) exceeds the threshold, with
    # no unscoped_audit escape, HARD-FAILS before a single row is materialized.
    query = session.query.return_value
    query.scalar.return_value = UNSCOPED_QUERY_THRESHOLD + 10   # the guard's COUNT(*)
    with pytest.raises( UnscopedQueryError ) as exc:
        repo.query_tasks()
    assert exc.value.count == UNSCOPED_QUERY_THRESHOLD + 10
    assert exc.value.threshold == UNSCOPED_QUERY_THRESHOLD
    query.all.assert_not_called()                              # rejected before row fetch


def test_query_tasks_guard_boundary_at_threshold_does_not_fire( repo, session ):
    # EXACTLY the threshold is allowed (strictly-greater fails) — no raise, rows fetched.
    sentinel = [ _item() ]
    query    = session.query.return_value
    query.scalar.return_value = UNSCOPED_QUERY_THRESHOLD        # == threshold, not >
    query.all.return_value = sentinel
    assert repo.query_tasks() is sentinel                       # no UnscopedQueryError raised
    query.all.assert_called_once()


def test_query_tasks_unscoped_audit_escape_bypasses_guard( repo, session ):
    # unscoped_audit=True is the deliberate-full-sweep escape: even a huge count
    # does NOT raise, and the guard's COUNT(*) is never consulted.
    query = session.query.return_value
    query.scalar.return_value = UNSCOPED_QUERY_THRESHOLD + 999
    query.all.return_value = [ _item(), _item() ]
    result = repo.query_tasks( unscoped_audit=True )
    assert result == query.all.return_value
    query.scalar.assert_not_called()                           # guard COUNT(*) skipped entirely


@pytest.mark.parametrize( "scoping", [
    { "owner_persona": "krishna" },
    { "status": "in_progress" },
    { "gate_class": "operator" },
    { "accountable_manager": "tiberius" },
    { "project": "lupin" },
    { "item_class": "task" },
    { "correlation_key": "cc-task:sid:5" },
] )
def test_query_tasks_scoped_query_skips_guard_even_when_large( repo, session, scoping ):
    # A SCOPED query (any narrowing filter) never trips the guard, however large —
    # the exact false-positive to avoid (owner=me with 60 rows must NOT fail).
    sentinel = [ _item() ]
    query    = session.query.return_value
    query.scalar.return_value = UNSCOPED_QUERY_THRESHOLD + 500  # would trip IF consulted
    query.all.return_value = sentinel
    result = repo.query_tasks( **scoping )                      # no raise
    assert result is sentinel
    query.scalar.assert_not_called()                           # scoped → guard COUNT(*) never run


def test_query_tasks_urgency_only_is_unscoped_and_guarded( repo, session ):
    # urgency is deliberately NOT a scoping filter — a urgency-only query is still
    # unscoped and still guarded (a bare urgency pull can't narrow the store enough).
    query = session.query.return_value
    query.scalar.return_value = UNSCOPED_QUERY_THRESHOLD + 1
    with pytest.raises( UnscopedQueryError ):
        repo.query_tasks( urgency="urgent" )


def test_query_tasks_excludes_terminal_by_default_on_unstatused_scoped_query( repo, session ):
    # status=None + include_terminal=False → the terminal-exclusion filter is added
    # ON TOP of the scoping filter (owner). Scoped, so the guard never runs.
    query = session.query.return_value
    query.all.return_value = [ ]
    repo.query_tasks( owner_persona="krishna" )
    assert query.filter.call_count == 2                        # owner filter + terminal-exclusion


def test_query_tasks_include_terminal_suppresses_terminal_filter( repo, session ):
    # include_terminal=True on an un-status'd scoped query → NO terminal filter.
    query = session.query.return_value
    query.all.return_value = [ ]
    repo.query_tasks( owner_persona="krishna", include_terminal=True )
    assert query.filter.call_count == 1                        # owner filter only


def test_query_tasks_explicit_terminal_status_overrides_exclusion( repo, session ):
    # An explicit status=done governs alone — no terminal-exclusion double-filter.
    query = session.query.return_value
    query.all.return_value = [ ]
    repo.query_tasks( status="done" )                          # scoped by status → guard skipped
    assert query.filter.call_count == 1                        # status filter only, terminal returned


def test_count_tasks_excludes_terminal_by_default_on_unstatused_query( repo, session ):
    # count_tasks parity: status=None + include_terminal=False → terminal-exclusion
    # filter applied, so the guard's non-terminal count matches the payload it guards.
    query = session.query.return_value
    query.scalar.return_value = 0
    repo.count_tasks( owner_persona="krishna" )
    assert query.filter.call_count == 2                        # owner + terminal-exclusion


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


def test_apply_patch_caller_reason_wins_over_field_delta( repo ):
    """
    ITEM A (Tiffany's Phase-1 finding) — the caller-reason-WINS branch of
    apply_patch's `event_reason = reason if reason else <auto-delta>` ternary is
    COVERAGE-INVISIBLE: coverage.py reports the line 100% covered whether or not
    its truthy arm ever runs (intra-line ternary branches are not tracked). The
    caller-supplied reason IS the headline of task_reassign — recording the
    manager's WHY — so the truthy arm must be proven directly.

    WITH a reason: the caller's "why" is recorded verbatim and the auto-delta is
    NOT used, even though the field genuinely changed (a delta string would
    otherwise have been generated). WITHOUT a reason: the SAME field change falls
    back to the field-delta string — proving the ternary's else-arm is the only
    thing that flipped the outcome.
    """
    # Truthy-arm: caller reason wins, auto-delta suppressed (the headline path).
    item  = _item( title="old title" )
    event = repo.apply_patch(
        item      = item,
        fields    = { "title": "new title" },
        actor     = "mr_radio a1b2c3",
        authority = "standing",
        reason    = "reassigned to balance the queue",
    )
    assert item.title       == "new title"                        # the edit still lands
    assert event.reason     == "reassigned to balance the queue"  # caller reason WINS
    assert "title:"     not in event.reason                       # the auto-delta is NOT used
    assert event.transition == "patched"

    # Else-arm parity: an absent reason on the SAME change falls back to the delta.
    item2  = _item( title="old title" )
    event2 = repo.apply_patch(
        item      = item2,
        fields    = { "title": "new title" },
        actor     = "mr_radio a1b2c3",
        authority = "standing",
    )
    assert event2.reason == "title: 'old title' -> 'new title'"   # absent-reason falls back to the delta

    # Else-arm also covers an EMPTY-STRING reason — `reason if reason` gates on
    # truthiness, not `is not None`, so "" must behave like absent, not win.
    item3  = _item( title="old title" )
    event3 = repo.apply_patch(
        item      = item3,
        fields    = { "title": "new title" },
        actor     = "mr_radio a1b2c3",
        authority = "standing",
        reason    = "",
    )
    assert event3.reason == "title: 'old title' -> 'new title'"   # "" is falsy -> delta, not the empty reason


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


# ---------------------------------------------------------------------------
# Phase 2.2 — apply_amendment (append-only body-amend seam; never rewrites)
# ---------------------------------------------------------------------------

_AMEND_NOW = datetime( 2026, 7, 2, 21, 55, 0, tzinfo=timezone.utc )


def test_apply_amendment_appends_block_preserving_original_body( repo, session ):
    item  = _item( body="ORIGINAL SPEC verbatim." )
    event = repo.apply_amendment(
        item      = item,
        note      = "SCOPE REFRAME: now the subscriber path.",
        actor     = "arnold 8b7225c4",
        authority = "standing",
        now       = _AMEND_NOW,
        reason    = "manager ruling on cited evidence",
    )
    # Original preserved verbatim; the note lands below a persona+UTC divider.
    assert item.body.startswith(
        "ORIGINAL SPEC verbatim.\n\n[amendment · arnold 8b7225c4 · 2026-07-02T21:55:00+00:00]\n"
    )
    assert item.body.endswith( "SCOPE REFRAME: now the subscriber path." )
    assert item.status        == "in_progress"                # status untouched (an amend is not a transition)
    assert event.transition   == "amended"
    assert event.receipt_refs is None
    assert event.reason       == "manager ruling on cited evidence"
    assert event.actor        == "arnold 8b7225c4"
    added_events = _added_instances( session, TaskEvent )
    assert len( added_events ) == 1 and added_events[ 0 ] is event


def test_apply_amendment_on_empty_body_writes_block_alone( repo, session ):
    # No original body -> the stamped block stands alone (no leading blank lines).
    item = _item( body=None )
    repo.apply_amendment(
        item      = item, note="first note", actor="a b",
        authority = "standing", now=_AMEND_NOW, reason=None,
    )
    assert item.body == "[amendment · a b · 2026-07-02T21:55:00+00:00]\nfirst note"


def test_apply_amendment_auto_marker_reason_when_absent( repo, session ):
    # reason falsy -> the audit event auto-describes the appended length.
    item  = _item( body="x" )
    event = repo.apply_amendment(
        item      = item, note="abcde", actor="a b",
        authority = "manager_relay", now=_AMEND_NOW, reason=None,
    )
    assert event.reason    == "body amended (+5 chars)"
    assert event.authority == "manager_relay"


# ---------------------------------------------------------------------------
# Persona-key follow-on policy (2026-07-11, task c03d1870) — flag_suffix folds
# the off-roster persona marker into the EXISTING creation / patched event reason
# (zero schema, zero new events). Design:
# src/rnd/v0.1.9/2026.07.11-persona-key-followon-policy.md
# ---------------------------------------------------------------------------

def test_create_item_folds_flag_suffix_into_queued_event_reason( repo, session ):
    repo.create_item(
        item_class  = "task",
        title       = "t",
        project     = "lupin",
        created_by  = "ziggy 5a1f17f8",
        authority   = "standing",
        flag_suffix = "[persona_flag: owner 'ziggy' off-roster]",
    )
    event = _added_instances( session, TaskEvent )[ 0 ]
    assert event.transition == "->queued"
    assert event.reason     == "[persona_flag: owner 'ziggy' off-roster]"


def test_create_item_no_flag_suffix_leaves_reason_none( repo, session ):
    repo.create_item(
        item_class = "task",
        title      = "t",
        project    = "lupin",
        created_by = "krishna 38d15e3b",
        authority  = "standing",
    )
    event = _added_instances( session, TaskEvent )[ 0 ]
    assert event.reason is None                                # unchanged default — no marker


def test_apply_patch_appends_flag_suffix_to_field_delta( repo ):
    item  = _item( owner_persona="krishna" )
    event = repo.apply_patch(
        item        = item,
        fields      = { "owner_persona": "ziggy stardust" },
        actor       = "mr radio 372f9dc9",
        authority   = "standing",
        flag_suffix = "[persona_flag: owner 'ziggy stardust' off-roster]",
    )
    # field-delta PRESERVED, marker appended after it (both survive on one event)
    assert "owner_persona: 'krishna' -> 'ziggy stardust'" in event.reason
    assert event.reason.endswith( "[persona_flag: owner 'ziggy stardust' off-roster]" )


def test_apply_patch_appends_flag_suffix_to_caller_reason( repo ):
    item  = _item( owner_persona="krishna" )
    event = repo.apply_patch(
        item        = item,
        fields      = { "owner_persona": "ziggy" },
        actor       = "a b",
        authority   = "standing",
        reason      = "manager handoff",
        flag_suffix = "[persona_flag: owner 'ziggy' off-roster]",
    )
    assert event.reason == "manager handoff [persona_flag: owner 'ziggy' off-roster]"


def test_apply_patch_none_flag_suffix_is_noop( repo ):
    item  = _item( title="old", priority="P2" )
    event = repo.apply_patch(
        item      = item,
        fields    = { "priority": "P0" },
        actor     = "a b",
        authority = "standing",
    )
    assert "[persona_flag" not in event.reason
    assert "priority: 'P2' -> 'P0'" in event.reason


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
