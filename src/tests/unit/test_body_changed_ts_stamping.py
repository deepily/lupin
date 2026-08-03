#!/usr/bin/env python3
"""
THE WRITER SIDE of park-reason staleness — bug `54924128`'s actual fix.

María 🌸 (56a24527), 2026-07-26, on Rick's ruling (option a; the live-store schema
migration authorized). Column: `38e025169a73`. Predicate: `task_store_owed`.

WHY THIS FILE EXISTS SEPARATELY FROM `test_park_reason_staleness.py`
--------------------------------------------------------------------
That file proves the PREDICATE's arithmetic — that `captured < changed` reads
STALE — across a 64-row boundary matrix, against a genuinely independent SQL
twin. **It cannot see this bug at all.** The predicate was never wrong; it was
reading the wrong column, and the columns it compares are written somewhere else
entirely.

⇒ A writer that stamps `body_changed_ts` on EVERY write (the old `updated_ts`
  behaviour) and a writer that never stamps it at all leave every assertion in
  that file green. The defect and its fix both live in `TaskRepository`.

WHAT WENT WRONG, MEASURED
--------------------------
`park_reason_is_stale` compared `park_reason_captured_at` against `updated_ts`,
and `updated_ts` moves on EVERY write. `task_edit`'s five free-edit fields are
title / body / priority / gate_class / urgency, and **only `body` can make a park
quote untrue.** Two priority-only edits during a routine board recut on
2026-07-26 produced two false STALEs in three minutes — at that moment every
parked row in production carried the flag and every one was wrong, **0 of 2**.

⚠️ BOTH ARMS, IN ONE RUN — THE ROW SAID SO AND IT IS THE WHOLE POINT
---------------------------------------------------------------------
    "A fix asserted only on the first arm is indistinguishable from a predicate
    that returns False always — which is indistinguishable from deleting the
    feature."

So every run asserts BOTH:

    ARM 1 (the fix)              a priority-only edit after park -> FRESH
    ARM 2 (the negative control) a real body amendment after park -> STALE

Neither is meaningful without the other. `test_the_two_arms_disagree` exists to
make that structural rather than aspirational: it fails if the two scenarios ever
produce the same verdict, which is what both degenerate implementations look like.

⚠️ WHAT THIS FILE DOES NOT PROVE
---------------------------------
The CLOCK. `_db_clock_now` is stubbed here to a controlled sequence, so these
tests would stay green against a writer that used `datetime.now()` instead of the
database clock. That substitution is a real hazard — it makes the comparison
cross-clock and surfaces skew as a false FRESH, i.e. in the direction nobody
notices — and it is a live-Postgres claim, not a unit one. It is asserted
structurally instead, by `test_both_writers_take_the_ONE_clock`, which pins that
both stamps come from the same method rather than from `datetime.now()`.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.postgres_models import TaskItem
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest.task_store_owed import PARK_STATUS, park_reason_is_stale


PARKED_AT   = datetime( 2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc )
LATER       = PARKED_AT + timedelta( hours=3 )
THE_QUOTE   = "Not right now — keep shipping, revisit when something forces it."


@pytest.fixture
def session():
    """A MagicMock session whose query() chain returns itself (house norm)."""
    mock  = MagicMock()
    query = mock.query.return_value
    for chain in ( "filter", "join", "order_by", "limit", "offset", "with_for_update", "group_by" ):
        getattr( query, chain ).return_value = query
    return mock


@pytest.fixture
def repo( session ):
    """
    A repository whose DB clock is FROZEN at `LATER`.

    Stubbing `_db_clock_now` rather than the session's `execute` keeps the test
    about the STAMPING DECISION — which writes move the marker — instead of about
    SQLAlchemy plumbing. The clock's own correctness is a separate claim; see the
    module docstring.
    """
    repository              = TaskRepository( session )
    repository._db_clock_now = MagicMock( return_value=LATER )
    return repository


def _a_parked_row():
    """
    A row parked at PARKED_AT, exactly as the write path leaves it: the capture
    time EQUALS the park write's `updated_ts`, and the body has not changed since
    (so `body_changed_ts` is at-or-before the park — here, None, which is the real
    state of every row the day migration 38e025169a73 lands, since it deliberately
    writes no backfill).
    """
    item                         = TaskItem()
    item.status                  = PARK_STATUS
    item.title                   = "a parked row"
    item.body                    = f"The decisive sentence: {THE_QUOTE}"
    item.priority                = "P1"
    item.gate_class              = "none"
    item.urgency                 = "normal"
    item.park_reason             = THE_QUOTE
    item.park_reason_captured_at = PARKED_AT
    item.updated_ts              = PARKED_AT
    item.body_changed_ts         = None
    return item


def _verdict( item ):
    """The flag exactly as both router projections compute it."""
    return park_reason_is_stale( item.status, item.park_reason_captured_at, item.body_changed_ts )


# ===========================================================================
# ARM 1 — the fix. The four fields that cannot invalidate a quote must not move
#         the marker.
# ===========================================================================

@pytest.mark.parametrize( "field,new_value", [
    ( "priority",   "P3" ),
    ( "gate_class", "operator" ),
    ( "urgency",    "high" ),
    ( "title",      "a re-titled parked row" ),
] )
def test_a_non_body_edit_after_park_leaves_the_quote_FRESH( repo, field, new_value ):
    """
    THE BUG, ROW BY ROW. `priority` is the one that actually fired — a board recut
    is the single most common maintenance write there is — but all four
    free-edit-but-not-body fields belong here, because the defect was never about
    priority specifically: it was about `updated_ts` moving for reasons unrelated
    to the row's content.
    """
    item = _a_parked_row()
    repo.apply_patch( item, { field: new_value }, actor="maria", authority="standing" )

    assert getattr( item, field ) == new_value,  "sanity: the edit must actually have applied"
    assert item.body_changed_ts is None,         f"a {field}-only edit must not stamp the content marker"
    assert _verdict( item ) is False,            f"a {field}-only edit defamed a correct quote — 54924128"


def test_a_patch_naming_body_but_not_CHANGING_it_leaves_the_quote_FRESH( repo ):
    """
    A no-op body write. The quote cannot have been invalidated by text that did
    not change, and stamping here would re-import the false-positive class through
    a narrower door — an idempotent re-PUT of the same body would start defaming
    quotes.

    Keyed off the SAME equality the audit delta uses, so the marker and the
    `patched` event can never disagree about whether the body changed.
    """
    item = _a_parked_row()
    repo.apply_patch( item, { "body": item.body }, actor="maria", authority="standing" )

    assert item.body_changed_ts is None
    assert _verdict( item ) is False


# ===========================================================================
# ARM 2 — the negative control. Without this, ARM 1 is satisfied by never
#         stamping at all, which is deleting the feature.
# ===========================================================================

def test_an_amendment_after_park_turns_the_quote_STALE( repo ):
    """
    An amend only ever APPENDS to the body, so it always changed — this stamp is
    unconditional. This is the arm that fails if someone "fixes" the false
    positive by simply never stamping.
    """
    item = _a_parked_row()
    repo.apply_amendment(
        item, note="the situation changed; the quoted sentence no longer holds",
        actor="maria", authority="standing", now=LATER,
    )

    assert item.body_changed_ts == LATER
    assert THE_QUOTE in item.body, "sanity: an amend appends, it never rewrites"
    assert _verdict( item ) is True, "a real body change after park MUST still report stale"


def test_a_body_PATCH_after_park_turns_the_quote_STALE( repo ):
    """The other body-writing door. A destructive body overwrite is a content change too."""
    item = _a_parked_row()
    repo.apply_patch( item, { "body": "an entirely different body" },
                      actor="maria", authority="standing" )

    assert item.body_changed_ts == LATER
    assert _verdict( item ) is True


def test_a_MIXED_patch_stamps_because_of_the_body_not_despite_it( repo ):
    """
    body + priority in one call. The presence of a non-body field must not suppress
    the stamp — the discriminator is "did the body change", not "was the body the
    only thing that changed."
    """
    item = _a_parked_row()
    repo.apply_patch( item, { "body": "new text", "priority": "P3" },
                      actor="maria", authority="standing" )

    assert item.priority        == "P3"
    assert item.body_changed_ts == LATER
    assert _verdict( item ) is True


# ===========================================================================
# The structural guards — these are what make the two arms above a GATE rather
# than two agreeable assertions
# ===========================================================================

def test_the_two_arms_disagree( repo ):
    """
    ⚠️ THE LOAD-BEARING TEST IN THIS FILE.

    Both degenerate implementations — "never stamp" and "always stamp" — make the
    two scenarios AGREE. A suite that asserts each arm separately can be satisfied
    by a constant; a suite that asserts they DIFFER cannot.

    Same fixture, same repo, same run: one priority edit, one amendment, opposite
    verdicts.
    """
    quiet = _a_parked_row()
    repo.apply_patch( quiet, { "priority": "P3" }, actor="maria", authority="standing" )

    loud = _a_parked_row()
    repo.apply_amendment( loud, note="this invalidates the quote", actor="maria",
                          authority="standing", now=LATER )

    assert _verdict( quiet ) != _verdict( loud ), (
        "the marker no longer discriminates — a predicate that cannot disagree with "
        "itself is a deleted feature wearing a green"
    )
    assert _verdict( quiet ) is False and _verdict( loud ) is True, "and in this direction, not the other"


def test_both_writers_take_the_ONE_clock( session ):
    """
    Both stamps come from `_db_clock_now`, never from `datetime.now()`.

    This value is COMPARED against `park_reason_captured_at`, which the park write
    takes from the database clock. An application-clock stamp on either side makes
    the comparison cross-clock, and skew surfaces as a **false FRESH** — a parked
    row silently failing to report an expired quote, which is this feature's own
    defect arriving in the direction nobody notices.

    Asserted by counting calls to the ONE method rather than by inspecting the
    value, because a frozen stub cannot tell two clocks apart — that is exactly
    what makes the substitution easy to ship unnoticed.
    """
    repo                     = TaskRepository( session )
    repo._db_clock_now       = MagicMock( return_value=LATER )

    repo.apply_amendment( _a_parked_row(), note="x", actor="m", authority="standing", now=LATER )
    assert repo._db_clock_now.call_count == 1, "the amend path must take the DB clock"

    repo.apply_patch( _a_parked_row(), { "body": "changed" }, actor="m", authority="standing" )
    assert repo._db_clock_now.call_count == 2, "the body-patch path must take the DB clock"

    repo.apply_patch( _a_parked_row(), { "priority": "P3" }, actor="m", authority="standing" )
    assert repo._db_clock_now.call_count == 2, "and a non-body patch must not read a clock at all"


@pytest.mark.parametrize( "serializer_name", [ "_serialize_item", "_serialize_item_terse" ] )
def test_BOTH_router_projections_read_the_content_marker( repo, serializer_name ):
    """
    Touch point 5 — the one a predicate test cannot reach.

    The flag ships from two places: the full row and the terse projection. Fix one
    and miss the other and `park_reason_stale` **means a different thing depending
    on how the caller queried**, which is worse than the original bug: it is the
    original bug, intermittently, keyed on a parameter nobody associates with it.

    Both are exercised against the SAME row through the real serializers, so
    reverting either call site to `item.updated_ts` goes red here — and nowhere
    else in the suite, because every other test calls the predicate directly.
    """
    from cosa.rest.routers import tasks as tasks_router

    serialize = getattr( tasks_router, serializer_name )

    quiet = _a_parked_row()
    quiet.id = None
    repo.apply_patch( quiet, { "priority": "P3" }, actor="maria", authority="standing" )
    # updated_ts is bumped by the ORM's onupdate in production; set it explicitly
    # so the row carries the exact shape the bug needed — a moved updated_ts with
    # an unmoved body. A serializer still reading updated_ts reports STALE here.
    quiet.updated_ts = LATER
    quiet.created_ts = PARKED_AT

    assert serialize( quiet )[ "park_reason_stale" ] is False, (
        f"{serializer_name} is still reading updated_ts — 54924128 in one projection only"
    )

    loud = _a_parked_row()
    loud.id = None
    repo.apply_amendment( loud, note="invalidates the quote", actor="maria",
                          authority="standing", now=LATER )
    loud.updated_ts = LATER
    loud.created_ts = PARKED_AT

    assert serialize( loud )[ "park_reason_stale" ] is True, (
        f"{serializer_name} stopped reporting a genuinely stale quote"
    )


def test_a_body_change_BEFORE_the_park_leaves_the_quote_FRESH( repo ):
    """
    Ordering, the other way round: the quote was taken FROM the current text, so a
    body change that predates the park cannot have invalidated it.

    Not a hypothetical — it is the normal shape of a park. Whoever parks the row
    reads the body, quotes its decisive sentence, and parks; the body's last change
    is necessarily earlier.
    """
    item                 = _a_parked_row()
    item.body_changed_ts = PARKED_AT - timedelta( hours=6 )

    assert _verdict( item ) is False
