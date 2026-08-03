"""
Unit tests for the done-arm rejoin — store row 00a6bde2, item 3.

WHAT THESE TESTS ARE GUARDING, stated so a future reader does not weaken them by accident:

  1. THE done/dropped SPLIT IS THE WHOLE SAFETY PROPERTY.
     `test_dropped_blocker_never_rejoins_the_negative_control` is the control that must FAIL
     if the two arms are ever transposed. A transposition would make this code silently
     overturn decisions a human deliberately made — strictly worse than the defect it fixes.

  2. A REJOIN IS A WRITE, SO THE PREDICATE LIES TOWARD DOING NOTHING. Every ambiguous
     input — an unresolvable blocker, a persona edge, a blocker nobody looked up — must
     HOLD. `blocker_is_terminal` FLAGS an unresolvable canonical id; this must NOT rejoin on
     the same input, because flagging says "this edge is dead" while rejoining says "the
     precondition happened", and an absent row never happened.
     `test_unresolvable_canonical_blocker_holds_diverging_from_blocker_terminal` pins that
     asymmetry so a future reader cannot "harmonise" the two into a live-row unblock.

  3. THE HOLD REASON IS ORDER-INDEPENDENT. A reason that changes when nothing about the row
     changed is not a reason anyone can act on.

  4. THE STAMP MUST NOT CLAIM WHAT IT CANNOT KNOW. It reports dormancy and the blocker; it
     must say, in its own text, that what moved underneath the row is NOT computed.
"""

import pytest

from datetime import datetime, timedelta, timezone

from cosa.rest.task_store_rejoin import (
    HOLD_DROPPED_BLOCKER,
    HOLD_LIVE_BLOCKER,
    HOLD_NON_ITEM_BLOCKER,
    HOLD_NOT_BLOCKED,
    HOLD_NO_ITEM_BLOCKER,
    HOLD_UNRESOLVED_BLOCKER,
    REJOIN_BLOCKER_STATUS,
    VERDICT_REJOIN,
    _parse_ts,
    classify_blocked_row,
    dormancy_days,
    dormancy_stamp,
    quick_smoke_test,
    scope_disclosure,
)


DONE_ID    = "11111111-1111-4111-8111-111111111111"
DONE_ID_2  = "aaaaaaaa-1111-4111-8111-111111111111"
DROPPED_ID = "22222222-2222-4222-8222-222222222222"
LIVE_ID    = "33333333-3333-4333-8333-333333333333"
GONE_ID    = "44444444-4444-4444-8444-444444444444"

NOW = datetime( 2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc )

STATUSES = {
    DONE_ID    : "done",
    DONE_ID_2  : "done",
    DROPPED_ID : "dropped",
    LIVE_ID    : "queued",
    GONE_ID    : None,
}


def item( ref_id ): return { "kind": "item", "id": ref_id }


# ----------------------------------------------------------------------------------
# classify_blocked_row — the positive arm
# ----------------------------------------------------------------------------------

def test_single_done_blocker_rejoins():
    verdict = classify_blocked_row( "blocked", [ item( DONE_ID ) ], STATUSES )
    assert verdict[ "verdict" ] == VERDICT_REJOIN
    assert verdict[ "reason" ] is None
    assert verdict[ "closed_blocker_ids" ] == [ DONE_ID ]


def test_every_blocker_done_rejoins_and_lists_them_all():
    verdict = classify_blocked_row( "blocked", [ item( DONE_ID ), item( DONE_ID_2 ) ], STATUSES )
    assert verdict[ "verdict" ] == VERDICT_REJOIN
    assert verdict[ "closed_blocker_ids" ] == [ DONE_ID, DONE_ID_2 ]


# ----------------------------------------------------------------------------------
# classify_blocked_row — THE NEGATIVE CONTROL AND ITS NEIGHBOURS
# ----------------------------------------------------------------------------------

def test_dropped_blocker_never_rejoins_the_negative_control():
    """
    THE CONTROL FOR THE ENTIRE FEATURE. Dropping was a DECISION; a silent rejoin overturns
    it. If the done/dropped arms are ever transposed, this is what goes RED — and nothing
    else would, because every other test is about rows that legitimately move.
    """
    verdict = classify_blocked_row( "blocked", [ item( DROPPED_ID ) ], STATUSES )
    assert verdict[ "verdict" ] is None
    assert verdict[ "reason" ] == HOLD_DROPPED_BLOCKER


def test_one_done_one_dropped_holds_because_dropped_dominates():
    verdict = classify_blocked_row( "blocked", [ item( DONE_ID ), item( DROPPED_ID ) ], STATUSES )
    assert verdict[ "verdict" ] is None
    assert verdict[ "reason" ] == HOLD_DROPPED_BLOCKER
    # the done sibling is still REPORTED — the row's partial progress is not erased
    assert verdict[ "closed_blocker_ids" ] == [ DONE_ID ]


def test_dropped_dominates_regardless_of_list_order():
    """Reversing the list must not change the verdict — order is not a fact about the row."""
    forward = classify_blocked_row( "blocked", [ item( DONE_ID ), item( DROPPED_ID ) ], STATUSES )
    reverse = classify_blocked_row( "blocked", [ item( DROPPED_ID ), item( DONE_ID ) ], STATUSES )
    assert forward[ "reason" ] == reverse[ "reason" ] == HOLD_DROPPED_BLOCKER


def test_live_blocker_holds():
    verdict = classify_blocked_row( "blocked", [ item( LIVE_ID ) ], STATUSES )
    assert verdict[ "verdict" ] is None
    assert verdict[ "reason" ] == HOLD_LIVE_BLOCKER


def test_one_done_one_live_holds_a_partial_wait_is_a_wait():
    verdict = classify_blocked_row( "blocked", [ item( DONE_ID ), item( LIVE_ID ) ], STATUSES )
    assert verdict[ "verdict" ] is None
    assert verdict[ "reason" ] == HOLD_LIVE_BLOCKER
    assert verdict[ "closed_blocker_ids" ] == [ DONE_ID ]


def test_unresolvable_canonical_blocker_holds_diverging_from_blocker_terminal():
    """
    THE DELIBERATE ASYMMETRY WITH ITEM 2, PINNED.

    `blocker_is_terminal` FLAGS a canonical id looked up and not found — on a typed edge it
    is unambiguously a dead reference. This must NOT rejoin on that same input: flagging
    says "this edge is dead, look at it"; rejoining says "the precondition HAPPENED". An
    absent row never happened, and only one of those licenses an automatic unblock.
    """
    verdict = classify_blocked_row( "blocked", [ item( GONE_ID ) ], STATUSES )
    assert verdict[ "verdict" ] is None
    assert verdict[ "reason" ] == HOLD_UNRESOLVED_BLOCKER


def test_blocker_never_looked_up_holds():
    """A key ABSENT from the map was never looked up — no evidence, and no evidence holds."""
    verdict = classify_blocked_row( "blocked", [ item( "unqueried-id" ) ], STATUSES )
    assert verdict[ "reason" ] == HOLD_UNRESOLVED_BLOCKER


def test_persona_blocker_disqualifies_rather_than_being_filtered_out():
    """
    `item_blocker_ids` DROPS persona refs for flagging. Here their presence must STOP the
    write: a persona edge is a real wait on a real seat, and rejoining past one unblocks
    work whose actual blocker was never examined.
    """
    verdict = classify_blocked_row( "blocked", [ item( DONE_ID ), { "kind": "persona", "id": "sam" } ], STATUSES )
    assert verdict[ "verdict" ] is None
    assert verdict[ "reason" ] == HOLD_NON_ITEM_BLOCKER


def test_user_blocker_disqualifies():
    verdict = classify_blocked_row( "blocked", [ { "kind": "user", "id": "rick" } ], STATUSES )
    assert verdict[ "reason" ] == HOLD_NON_ITEM_BLOCKER


@pytest.mark.parametrize( "malformed", [
    "not-a-dict",
    { "kind": "item" },                 # no id
    { "kind": "item", "id": "" },       # blank id
    { "kind": "item", "id": 12345 },    # non-str id
] )
def test_malformed_blocker_entry_holds_never_raises( malformed ):
    verdict = classify_blocked_row( "blocked", [ malformed ], STATUSES )
    assert verdict[ "verdict" ] is None
    assert verdict[ "reason" ] == HOLD_NON_ITEM_BLOCKER


def test_non_item_outranks_dropped_in_the_precedence():
    verdict = classify_blocked_row(
        "blocked", [ item( DROPPED_ID ), { "kind": "persona", "id": "sam" } ], STATUSES )
    assert verdict[ "reason" ] == HOLD_NON_ITEM_BLOCKER


def test_unresolved_outranks_live_in_the_precedence():
    verdict = classify_blocked_row( "blocked", [ item( LIVE_ID ), item( GONE_ID ) ], STATUSES )
    assert verdict[ "reason" ] == HOLD_UNRESOLVED_BLOCKER


def test_precedence_is_order_independent_across_every_hold_reason():
    blockers = [ item( LIVE_ID ), item( GONE_ID ), item( DROPPED_ID ), { "kind": "persona", "id": "s" } ]
    forward  = classify_blocked_row( "blocked", blockers, STATUSES )
    reverse  = classify_blocked_row( "blocked", list( reversed( blockers ) ), STATUSES )
    assert forward[ "reason" ] == reverse[ "reason" ] == HOLD_NON_ITEM_BLOCKER


# ----------------------------------------------------------------------------------
# classify_blocked_row — the guards
# ----------------------------------------------------------------------------------

@pytest.mark.parametrize( "status", [ "queued", "in_progress", "done", "dropped", "parked", "" ] )
def test_a_row_that_is_not_blocked_is_never_rejoined( status ):
    """Checked FIRST: a queued row carrying a leftover blocked_by is not waiting at all."""
    verdict = classify_blocked_row( status, [ item( DONE_ID ) ], STATUSES )
    assert verdict[ "verdict" ] is None
    assert verdict[ "reason" ] == HOLD_NOT_BLOCKED
    assert verdict[ "closed_blocker_ids" ] == [ ]


@pytest.mark.parametrize( "blocked_by", [ None, [ ], "nonsense", { "kind": "item" }, 42 ] )
def test_blocked_with_no_usable_blocker_list_holds( blocked_by ):
    verdict = classify_blocked_row( "blocked", blocked_by, STATUSES )
    assert verdict[ "verdict" ] is None
    assert verdict[ "reason" ] == HOLD_NO_ITEM_BLOCKER


def test_rejoin_blocker_status_is_done_not_merely_terminal():
    """The two arms differ by this constant alone — a transposition starts here."""
    assert REJOIN_BLOCKER_STATUS == "done"


# ----------------------------------------------------------------------------------
# _parse_ts
# ----------------------------------------------------------------------------------

def test_parse_ts_accepts_aware_datetime_unchanged():
    assert _parse_ts( NOW ) == NOW


def test_parse_ts_reads_a_naive_datetime_as_utc():
    assert _parse_ts( datetime( 2026, 7, 26, 12, 0, 0 ) ) == NOW


def test_parse_ts_accepts_iso_with_trailing_z():
    assert _parse_ts( "2026-07-26T12:00:00Z" ) == NOW


def test_parse_ts_reads_a_naive_iso_string_as_utc():
    assert _parse_ts( "2026-07-26T12:00:00" ) == NOW


@pytest.mark.parametrize( "junk", [ None, "", "not-a-timestamp", 12345, [ ] ] )
def test_parse_ts_on_junk_is_none_never_raises( junk ):
    assert _parse_ts( junk ) is None


# ----------------------------------------------------------------------------------
# dormancy_days
# ----------------------------------------------------------------------------------

def test_dormancy_days_counts_whole_days():
    assert dormancy_days( NOW - timedelta( days=7 ), NOW ) == 7


def test_dormancy_days_truncates_toward_zero():
    """47 hours is ONE day, not two — a rounded-up dormancy overstates the strand."""
    assert dormancy_days( NOW - timedelta( hours=47 ), NOW ) == 1


def test_dormancy_days_on_a_future_close_is_zero_never_negative():
    """Clock skew must not produce a negative strand, which would read as nonsense."""
    assert dormancy_days( NOW + timedelta( days=3 ), NOW ) == 0


def test_dormancy_days_accepts_a_naive_now_as_utc():
    assert dormancy_days( "2026-07-19T12:00:00Z", datetime( 2026, 7, 26, 12, 0, 0 ) ) == 7


def test_dormancy_days_on_missing_close_time_is_none_not_zero():
    """None and 0 are different claims: 'unknown' must never render as 'closed today'."""
    assert dormancy_days( None, NOW ) is None


# ----------------------------------------------------------------------------------
# dormancy_stamp
# ----------------------------------------------------------------------------------

def test_stamp_headline_measures_from_the_LATEST_close():
    """
    The row became free when the LAST blocker closed; an earlier close did not release it.
    So the headline is the SHORTEST span, never the longest — reporting the longest would
    inflate the number on exactly the multi-blocker rows where it matters.
    """
    stamp = dormancy_stamp( [
        { "id": DONE_ID,   "closed_at": NOW - timedelta( days=10 ) },
        { "id": DONE_ID_2, "closed_at": NOW - timedelta( days=4 ) },
    ], NOW )
    assert "DORMANCY: 4d" in stamp
    assert "10d ago" in stamp and "4d ago" in stamp    # both spans still listed


def test_stamp_says_the_premise_is_not_computed():
    """
    §3's measured finding: two of the first three hand-rejoined rows had premises that had
    already gone false, and BOTH READ AS READY. The stamp exists to break that read, so it
    must state what it does NOT know.
    """
    stamp = dormancy_stamp( [ { "id": DONE_ID, "closed_at": NOW } ], NOW )
    assert "NOT FRESHLY VETTED" in stamp
    assert "NOT" in stamp and "computed" in stamp
    assert "closing receipts" in stamp


def test_stamp_names_an_unknown_close_time_rather_than_defaulting_it():
    stamp = dormancy_stamp( [ { "id": DONE_ID, "closed_at": None } ], NOW )
    assert "close time unknown" in stamp
    assert "DORMANCY: unknown" in stamp


def test_stamp_with_no_blockers_still_returns_usable_text():
    stamp = dormancy_stamp( [ ], NOW )
    assert "DORMANCY: unknown" in stamp
    assert stamp.strip()


def test_stamp_mixes_known_and_unknown_close_times():
    stamp = dormancy_stamp( [
        { "id": DONE_ID,   "closed_at": NOW - timedelta( days=3 ) },
        { "id": DONE_ID_2, "closed_at": "garbage" },
    ], NOW )
    assert "DORMANCY: 3d" in stamp
    assert "close time unknown" in stamp


def test_stamp_cites_the_row_so_a_reader_can_find_the_rule():
    assert "00a6bde2" in dormancy_stamp( [ ], NOW )


# ----------------------------------------------------------------------------------
# scope_disclosure — required output, not a courtesy
# ----------------------------------------------------------------------------------

def test_scope_disclosure_names_the_dropped_arm_as_ricks_alone():
    text = scope_disclosure( { "examined": 4, VERDICT_REJOIN: 0 } )
    assert "NEVER auto-rejoined" in text
    assert "Rick" in text


def test_scope_disclosure_names_both_arms_this_pass_cannot_see():
    text = scope_disclosure( { } )
    assert "PROSE" in text
    assert "persona edges" in text


def test_scope_disclosure_reads_missing_counts_as_zero_never_raises():
    text = scope_disclosure( { } )
    assert "examined                    : 0" in text


def test_scope_disclosure_reports_every_hold_bucket_separately():
    """A pass that rolls the hold buckets into one number hides WHY rows were left alone."""
    text = scope_disclosure( {
        "examined": 9, VERDICT_REJOIN: 1,
        HOLD_DROPPED_BLOCKER: 2, HOLD_LIVE_BLOCKER: 3,
        HOLD_UNRESOLVED_BLOCKER: 1, HOLD_NON_ITEM_BLOCKER: 1, HOLD_NO_ITEM_BLOCKER: 1,
    } )
    for expected in ( ": 9", ": 1", ": 2", ": 3" ):
        assert expected in text


# ----------------------------------------------------------------------------------
# smoke
# ----------------------------------------------------------------------------------

def test_quick_smoke_test_runs_clean( capsys ):
    quick_smoke_test()
    assert "✓" in capsys.readouterr().out
