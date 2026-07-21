"""
Unit tests for the SINGLE-SOURCED per-status field normalizer (row 86ce4c43 #2).

WHY THIS FILE EXISTS — the anti-divergence deliverable
------------------------------------------------------
Before this normalizer, `TaskRepository.create_item` and
`TaskRepository.apply_transition` each implemented the per-status field rules
INDEPENDENTLY. `create_item`'s own docstring admitted it: it "OWNS the per-status
field consistency, the same way apply_transition does". Two implementations of
one invariant by acknowledged parallel construction, with nothing enforcing that
they agree — so a divergence between them produces a store where a value
survives a create and dies on the next transition. That failure is SILENT and
lands GREEN, which is why the parity test below is the deliverable and not a
bonus.

THE BEHAVIOR CHANGE (Mr Radio GO 2026-07-21, row 86ce4c43 defect #2)
--------------------------------------------------------------------
`next_chase_ts` is no longer nulled outside `blocked`/`parked`. A chase is a
SCHEDULE, not a WAIT: "a queued row waits on nothing" is true about DEPENDENCIES
and says nothing about SCHEDULING. The DB never forbade this — both CHECK
constraints are one-directional implications that COMPEL a chase in two states
and forbid one nowhere (postgres_models.py) — so this deletes an
application-layer deletion rather than adding a schema capability.

`blocked_by` keeps its per-status clearing, and the asymmetry is deliberate: a
blocked_by ref is a DEPENDENCY whose meaning is defined by the blocked status, so
a non-blocked row genuinely holds none. A chase is independent of status. That
distinction IS the fix.

⚠️ WHAT THIS CHANGE DELIBERATELY DOES NOT DO — the owed fence (Mr Radio, RULED)
A queued row carrying a FUTURE chase still counts as OWED. The suppression shape
exists twenty lines away (`park_is_active`) and was NOT copied: `parked` earns its
exclusion because a HUMAN ruled the row not-now and the chase bounds that ruling,
with a quoted `park_reason` the next reader can refute. A chase on a queued row is
a schedule with nobody's ruling behind it — copying the clause would let any
caller silence a row from the liveness oracle with a timestamp and no human in
the loop. Scheduled-not-owed needs its own ratification with `stop.py` and the
arbiter named as consumers.

PART 3 — a normalizer that CANNOT silently drop (Rachel 71061fb4's framing,
adopted as crew doctrine): "a rule that says 'be loud' is a rule someone forgets;
a normalizer that cannot silently drop is a mechanism." Every value the
normalizer discards is REPORTED in its return, so callers cannot fail to know.
"""

import os
import sys
from datetime import datetime, timezone

import pytest

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from cosa.rest.task_store_rules import (
    normalize_status_fields,
    compose_drop_marker,
    DROPPED_MARKER_PREFIX,
)
from cosa.rest.task_store_owed import PARK_STATUS


CHASE = datetime( 2026, 7, 22, 14, 0, tzinfo=timezone.utc )
REFS  = [ { "kind": "persona", "id": "tiffany" } ]


# ---------------------------------------------------------------------------
# THE BEHAVIOR CHANGE — a chase SURVIVES outside blocked/parked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "status", [ "queued", "in_progress", "claimed", "review" ] )
def test_chase_survives_on_every_non_blocked_non_parked_status( status ):
    # THE DEFECT THIS PINS: before the fix these statuses fell into an `else:`
    # arm that set next_chase_ts = None, so a caller who scheduled a row got a
    # 200 and an unscheduled row. Silent, on the SUCCESS path.
    resolved, dropped = normalize_status_fields( status, blocked_by=None, next_chase_ts=CHASE )

    assert resolved[ "next_chase_ts" ] == CHASE
    assert "next_chase_ts" not in dropped


@pytest.mark.parametrize( "status", [ "blocked", PARK_STATUS ] )
def test_chase_still_honored_on_the_two_statuses_that_require_it( status ):
    # Unchanged behavior — the CHECK constraints COMPEL a chase here.
    resolved, dropped = normalize_status_fields( status, blocked_by=REFS, next_chase_ts=CHASE )

    assert resolved[ "next_chase_ts" ] == CHASE
    assert "next_chase_ts" not in dropped


def test_caller_supplied_none_still_clears_the_chase():
    # The caller ALWAYS determines the chase — supplying None means None. This is
    # what preserves every existing caller's behavior: the only case that changes
    # is the one where a caller supplied a value and it was thrown away.
    resolved, dropped = normalize_status_fields( "in_progress", blocked_by=None, next_chase_ts=None )

    assert resolved[ "next_chase_ts" ] is None
    assert "next_chase_ts" not in dropped   # nothing was DROPPED — nothing was given


# ---------------------------------------------------------------------------
# UNCHANGED — blocked_by keeps its per-status clearing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "status", [ "queued", "in_progress", "claimed", "review", PARK_STATUS ] )
def test_blocked_by_is_still_emptied_outside_blocked( status ):
    # DELIBERATE ASYMMETRY vs the chase: a blocked_by ref is a DEPENDENCY whose
    # meaning is defined by the blocked status. A non-blocked row holds none.
    resolved, dropped = normalize_status_fields( status, blocked_by=REFS, next_chase_ts=None )

    assert resolved[ "blocked_by" ] == [ ]


def test_blocked_by_passes_through_on_blocked():
    resolved, dropped = normalize_status_fields( "blocked", blocked_by=REFS, next_chase_ts=CHASE )

    assert resolved[ "blocked_by" ] == REFS
    assert dropped == [ ]


def test_none_blocked_by_defaults_to_empty_list_never_none():
    # A None blocked_by must land as [] — the column is a jsonb list, and a None
    # here would make "waits on nothing" unrepresentable.
    resolved, _ = normalize_status_fields( "blocked", blocked_by=None, next_chase_ts=CHASE )

    assert resolved[ "blocked_by" ] == [ ]


# ---------------------------------------------------------------------------
# PART 3 — the normalizer CANNOT silently drop
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "status", [ "queued", "in_progress", "claimed", "review", PARK_STATUS ] )
def test_a_discarded_blocked_by_is_REPORTED_not_silently_swallowed( status ):
    # The whole point of part 3: the caller supplied refs, the normalizer dropped
    # them, and that fact is in the RETURN VALUE — not in a docstring, not in a
    # convention someone remembers.
    resolved, dropped = normalize_status_fields( status, blocked_by=REFS, next_chase_ts=None )

    assert resolved[ "blocked_by" ] == [ ]
    assert dropped == [ "blocked_by" ]


def test_nothing_dropped_reports_an_empty_list_not_none():
    # A legitimate zero must be READABLE — an empty list, never None, so a caller
    # can branch on it without a truthiness trap.
    _, dropped = normalize_status_fields( "queued", blocked_by=None, next_chase_ts=CHASE )

    assert dropped == [ ]


def test_empty_blocked_by_is_not_reported_as_a_drop():
    # Dropping [] to [] discards NOTHING. Reporting it would train readers to
    # ignore the drop list, which is how a real signal becomes noise.
    _, dropped = normalize_status_fields( "queued", blocked_by=[ ], next_chase_ts=None )

    assert dropped == [ ]


# ---------------------------------------------------------------------------
# PART 3, SECOND HALF — the report must REACH the audit trail
#
# Rachel 71061fb4 caught this: a normalizer that reports a discard to a caller
# which binds it to `_dropped` and throws it away is THE SAME SILENCE one layer
# up. "Today it is still a convention, not a mechanism." These pin the listening
# end, without which the reporting end is decoration.
# ---------------------------------------------------------------------------

def test_drop_marker_names_the_discarded_field():
    marker = compose_drop_marker( [ "blocked_by" ], None )

    assert marker.startswith( DROPPED_MARKER_PREFIX )
    assert "blocked_by" in marker


def test_drop_marker_preserves_an_existing_reason_never_replaces_it():
    # The caller's justification and the machine's disclosure must BOTH survive —
    # a disclosure that overwrites the human's reason trades one silence for
    # another.
    marker = compose_drop_marker( [ "blocked_by" ], "parking this per Rick" )

    assert "parking this per Rick" in marker
    assert "blocked_by" in marker


def test_no_drop_produces_NO_marker_and_leaves_the_reason_untouched():
    # A no-op discard must not manufacture an audit reason. If every row grew a
    # marker, the marker would stop meaning anything — the same "real signal
    # trained into noise" this row's parent complains about.
    assert compose_drop_marker( [ ], "some reason" ) == "some reason"
    assert compose_drop_marker( [ ], None ) is None


def test_create_path_stamps_the_drop_marker_onto_the_creation_event():
    """
    END-TO-END through the repository: a stray blocked_by on a queued mint is
    dropped AND the drop is named in the event the store keeps forever.
    """
    from unittest.mock import MagicMock
    from cosa.rest.db.repositories.task_repository import TaskRepository
    from cosa.rest.postgres_models import TaskEvent

    session = MagicMock()
    repo    = TaskRepository( session )
    repo.create_item(
        item_class = "task",
        title      = "queued with a stray blocker",
        project    = "lupin",
        created_by = "arnold 5bcd3ad6",
        authority  = "standing",
        status     = "queued",
        blocked_by = REFS,          # stray — dropped, and MUST be disclosed
    )

    events = [ c.args[ 0 ] for c in session.add.call_args_list
               if isinstance( c.args[ 0 ], TaskEvent ) ]
    assert len( events ) == 1
    assert DROPPED_MARKER_PREFIX in events[ 0 ].reason
    assert "blocked_by" in events[ 0 ].reason


def test_transition_path_stamps_the_drop_marker_onto_the_transition_event():
    from unittest.mock import MagicMock
    from cosa.rest.db.repositories.task_repository import TaskRepository
    from cosa.rest.postgres_models import TaskItem, TaskEvent

    session = MagicMock()
    repo    = TaskRepository( session )
    item    = TaskItem( item_class="task", title="t", project="lupin",
                        created_by="arnold 5bcd3ad6", status="queued",
                        blocked_by=[ ], next_chase_ts=None )

    event = repo.apply_transition(
        item       = item,
        to_status  = "in_progress",
        actor      = "arnold 5bcd3ad6",
        authority  = "standing",
        blocked_by = REFS,          # stray on a non-blocked target — disclosed
    )

    assert DROPPED_MARKER_PREFIX in event.reason
    assert "blocked_by" in event.reason


# ---------------------------------------------------------------------------
# THE ANTI-DIVERGENCE PARITY TEST — the deliverable
# ---------------------------------------------------------------------------

def test_both_repository_write_paths_route_through_this_one_normalizer():
    """
    The create path and the transition path must not re-implement the invariant.

    This asserts the SOURCE calls it — a behavioral parity test can pass while
    two implementations agree TODAY and drift tomorrow, which is exactly the
    failure mode ("silent, and green") this file exists to prevent.
    """
    import inspect
    from cosa.rest.db.repositories import task_repository

    create_src     = inspect.getsource( task_repository.TaskRepository.create_item )
    transition_src = inspect.getsource( task_repository.TaskRepository.apply_transition )

    assert "normalize_status_fields" in create_src, \
        "create_item must route per-status field consistency through the shared normalizer"
    assert "normalize_status_fields" in transition_src, \
        "apply_transition must route per-status field consistency through the shared normalizer"


# ---------------------------------------------------------------------------
# REGRESSION — the CHECK constraints must stay ONE-DIRECTIONAL
# ---------------------------------------------------------------------------

def test_check_constraints_never_forbid_a_chase_outside_blocked_or_parked():
    """
    The finding that made this fix cheap: the DB ALREADY permits a chase on any
    status. Both CHECKs are one-directional implications — they COMPEL a chase in
    two states and FORBID one nowhere.

    Pinned because a future migration that "tightens" either predicate into a
    biconditional would silently re-break defect #2 at the storage layer, below
    every application-layer test in this file.
    """
    from cosa.rest.postgres_models import TaskItem

    checks = { c.name: str( c.sqltext )
               for c in TaskItem.__table__.constraints
               if hasattr( c, "sqltext" ) }

    blocked = checks[ "ck_task_items_blocked_requires_chase_ts" ]
    parked  = checks[ "ck_task_items_parked_requires_chase_ts" ]

    # Each guards ONLY its own status: the predicate is vacuously true elsewhere.
    assert "status != 'blocked'" in blocked
    assert "status != 'parked'"  in parked
    # And neither mentions a non-blocked/non-parked status, so neither can forbid
    # a chase on one.
    assert "queued"      not in blocked and "queued"      not in parked
    assert "in_progress" not in blocked and "in_progress" not in parked
