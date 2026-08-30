"""
Fixture suite for cosa/rest/task_store_epic_keys.py — the epic-key drift detector.

WHY THESE CASES AND NOT OTHERS. The whole point of this detector is that the obvious
check — "is correlation_key blank?" — is not enforcement, because the field has THREE
tenants and only one is an epic key. So the load-bearing cases here are the ones a
blank-check would WAVE THROUGH:

    · a foreign key       ("cascade-quick-ask")   non-blank, ungroupable
    · a mirror key        ("cc-task:...")         non-blank, ungroupable, NOT re-stampable
    · an invented slug    ("epic:not-a-thing")    passes the PREFIX check, renders storyless

Delete one of those and the suite still passes while the detector loses the reason it
exists. A whitespace-only key gets its own case for the same reason: `" "` is truthy in
Python, so a naive presence test calls it keyed.
"""

import pytest

from cosa.rest.task_store_epic_keys import (
    BUCKET_BLANK,
    BUCKET_EPIC,
    BUCKET_FOREIGN,
    BUCKET_MIRROR,
    audit_rows,
    classify_key,
    reach_disclosure,
)


KNOWN = [ "epic:board-visibility", "epic:unassigned" ]


# ── classify_key ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "value,expected", [
    ( "epic:board-visibility",   BUCKET_EPIC ),
    ( "epic:",                   BUCKET_EPIC ),      # prefix alone still claims the tenant
    ( "cc-task:s1:g0:7",         BUCKET_MIRROR ),
    ( "cascade-quick-ask",       BUCKET_FOREIGN ),
    ( "EPIC:board-visibility",   BUCKET_FOREIGN ),   # case-SENSITIVE on purpose — the board matches exactly
    ( None,                      BUCKET_BLANK ),
    ( "",                        BUCKET_BLANK ),
    ( "   ",                     BUCKET_BLANK ),     # truthy in Python; absent to the board
    ( "\t\n",                    BUCKET_BLANK ),
    ( "  epic:x  ",              BUCKET_EPIC ),      # stripped before matching
] )
def test_classify_key_buckets( value, expected ):
    assert classify_key( value ) == expected


def test_classify_key_coerces_a_non_string():
    """A non-str key must bucket, not explode — the store column is nullable text but
    the caller hands us whatever the JSON carried."""
    assert classify_key( 12345 ) == BUCKET_FOREIGN


# ── audit_rows ────────────────────────────────────────────────────────────────────

def _row( row_id, key, **kwargs ):
    base = { "id": row_id, "correlation_key": key, "status": "queued",
             "title": f"row {row_id}", "project": "lupin" }
    base.update( kwargs )
    return base


def test_audit_flags_blank_foreign_and_unknown_but_never_mirror():
    rows = [
        _row( "a1", "epic:board-visibility" ),   # healthy
        _row( "a2", "epic:invented-slug" ),      # passes a PREFIX check, has no story
        _row( "a3", None ),                      # blank
        _row( "a4", "cascade-quick-ask" ),       # foreign — passes a BLANK check
        _row( "a5", "cc-task:s1:g0:7" ),         # mirror — counted, never flagged
        _row( "a6", "   " ),                     # whitespace-only
    ]
    report = audit_rows( rows, known_epic_keys=KNOWN )

    assert report[ "rows_seen" ] == 6
    assert report[ "counts" ] == {
        BUCKET_EPIC: 2, BUCKET_MIRROR: 1, BUCKET_FOREIGN: 1, BUCKET_BLANK: 2,
        "unknown_epic": 1,
    }

    flagged = { f[ "id" ]: f[ "reason" ] for f in report[ "findings" ] }
    assert flagged == { "a2": "unknown_epic", "a3": "blank", "a4": "foreign", "a6": "blank" }

    # The load-bearing negative: the mirror row is present in the counts and ABSENT from
    # the findings. Its key is load-bearing for the mirror's idempotency probe, so
    # flagging it would invite a re-stamp that breaks the probe.
    assert "a5" not in flagged
    assert report[ "counts" ][ BUCKET_MIRROR ] == 1


def test_audit_skips_the_slug_check_when_no_key_list_is_supplied():
    """An unreadable key list must not manufacture findings — and the report must SAY it
    skipped, so a reader cannot mistake 'not checked' for 'checked and clean'."""
    rows   = [ _row( "b1", "epic:whatever-this-is" ) ]
    report = audit_rows( rows, known_epic_keys=None )

    assert report[ "known_keys_checked" ] is False
    assert report[ "findings" ] == [ ]
    assert report[ "counts" ][ "unknown_epic" ] == 0


def test_audit_reports_every_bucket_at_zero_on_a_clean_board():
    """A bucket missing from the report is indistinguishable from one never examined."""
    report = audit_rows( [ _row( "c1", "epic:unassigned" ) ], known_epic_keys=KNOWN )

    assert set( report[ "counts" ] ) == {
        BUCKET_EPIC, BUCKET_MIRROR, BUCKET_FOREIGN, BUCKET_BLANK, "unknown_epic"
    }
    assert report[ "counts" ][ BUCKET_FOREIGN ] == 0
    assert report[ "findings" ] == [ ]


def test_audit_handles_an_empty_board():
    report = audit_rows( [ ], known_epic_keys=KNOWN )
    assert report[ "rows_seen" ] == 0
    assert report[ "findings" ] == [ ]


def test_audit_survives_a_row_with_no_id_or_title():
    """A malformed row must still be classified — dropping it would silently shrink the
    denominator, which is the failure mode this whole family is made of."""
    report = audit_rows( [ { } ], known_epic_keys=KNOWN )

    assert report[ "rows_seen" ] == 1
    assert report[ "findings" ][ 0 ][ "id" ] is None
    assert report[ "findings" ][ 0 ][ "reason" ] == "blank"


def test_audit_finding_carries_the_fields_a_reader_needs_to_act():
    rows   = [ _row( "d1", None, status="in_progress", title="Fix the thing", project="lupin" ) ]
    report = audit_rows( rows, known_epic_keys=KNOWN )
    finding = report[ "findings" ][ 0 ]

    assert finding[ "id" ]              == "d1"
    assert finding[ "title" ]           == "Fix the thing"
    assert finding[ "status" ]          == "in_progress"
    assert finding[ "project" ]         == "lupin"
    assert finding[ "correlation_key" ] is None
    assert finding[ "bucket" ]          == BUCKET_BLANK


# ── reach_disclosure ──────────────────────────────────────────────────────────────

def test_reach_disclosure_names_the_mirror_tenant_and_the_prevention_gap():
    """The disclosure is a REQUIRED output, not a courtesy line: a clean verdict that
    does not name the mirror bucket reads as 'the board is fully grouped'."""
    report = audit_rows( [ _row( "e1", "cc-task:s1:g0:1" ) ], known_epic_keys=KNOWN )
    text   = reach_disclosure( report, KNOWN )

    assert "mirror keys        : 1" in text
    assert "NOT re-stampable"       in text
    assert "DOES NOT COVER"         in text
    assert "prevention"             in text
    assert "every creation path"    in text


def test_reach_disclosure_is_emitted_on_a_clean_run_too():
    report = audit_rows( [ _row( "f1", "epic:unassigned" ) ], known_epic_keys=KNOWN )
    text   = reach_disclosure( report, KNOWN )

    assert "REACH OF THIS SCAN" in text
    assert "2 known epic keys"  in text


def test_reach_disclosure_says_so_loudly_when_the_slug_check_was_skipped():
    report = audit_rows( [ _row( "g1", "epic:anything" ) ], known_epic_keys=None )
    text   = reach_disclosure( report, None )

    assert "SKIPPED" in text
    assert "was NOT checked" in text


def test_reach_disclosure_skips_when_keys_absent_even_if_audit_checked():
    """Defensive: known_keys_checked True but no list handed to the disclosure still
    reports SKIPPED rather than crashing on len(None)."""
    report = audit_rows( [ _row( "h1", "epic:board-visibility" ) ], known_epic_keys=KNOWN )
    text   = reach_disclosure( report, None )

    assert "SKIPPED" in text


# ── the FRAME: terminal rows and truncation (Tiberius, reviewing 2026-08-30) ─────────
#
# The defect: reach_disclosure printed a clean four-bucket table and never said the fetch
# excludes TERMINAL rows by default. The script's module docstring said so — but nobody
# reports a module docstring, they report this string. These hold the frame stated.
#
# The function CANNOT discover either fact: `report` comes from audit_rows, which sees
# rows and nothing else. Both arrive as arguments, and an unpassed argument must read as
# an ADMISSION, never as silence. That is what the first test below pins.

def test_the_default_call_admits_it_was_not_told_the_frame():
    """
    THE ONE THAT MATTERS, and the one Tiberius asked for by name. Every other test here
    passes the frame explicitly, so all of them would still pass if the default silently
    meant "terminal excluded, not truncated" — which is the original omission wearing a
    parameter. This calls it the way the old code did and demands an admission.
    """
    report = audit_rows( [ _row( "t0", "epic:board-visibility" ) ], known_epic_keys=KNOWN )
    text   = reach_disclosure( report, KNOWN )

    assert "row-status frame" in text and "fetch truncated" in text, (
        "the frame must be named even when nobody passed it" )
    assert text.count( "NOT STATED BY THE CALLER" ) == 2, (
        "an unpassed frame must read as an explicit admission on BOTH lines; silence here "
        "is the exact omission this parameter was added to end" )


def test_excluding_terminal_rows_is_stated_as_a_blind_spot():
    report = audit_rows( [ _row( "t1", "epic:board-visibility" ) ], known_epic_keys=KNOWN )
    text   = reach_disclosure( report, KNOWN, include_terminal=False, truncated=False )

    assert "EXCLUDED" in text
    assert "done/dropped rows were never fetched" in text, (
        "the line must say WHAT was excluded, not merely that something was — a bare "
        "'EXCLUDED' survived a mutation that deleted this clause" )
    assert "since closed is invisible here" in text, (
        "naming the exclusion is not enough — it must say what the reader therefore cannot see" )
    assert "NOT STATED BY THE CALLER" not in text


def test_including_terminal_rows_is_stated_too():
    report = audit_rows( [ _row( "t2", "epic:board-visibility" ) ], known_epic_keys=KNOWN )
    text   = reach_disclosure( report, KNOWN, include_terminal=True, truncated=False )

    assert "included — done/dropped rows were in frame" in text
    assert "EXCLUDED" not in text


def test_a_truncated_fetch_says_the_verdict_covers_a_subset():
    report = audit_rows( [ _row( "t3", "epic:board-visibility" ) ], known_epic_keys=KNOWN )
    text   = reach_disclosure( report, KNOWN, include_terminal=False, truncated=True )

    assert "SUBSET" in text
    assert "unseen rows may carry drift" in text


def test_the_disclosure_no_longer_outsources_truncation_to_the_caller():
    """
    It used to end 'the caller must say so' — a mandatory discloser handing half its
    disclosure to somebody else. That is how the terminal-row omission survived review.
    """
    report = audit_rows( [ _row( "t4", "epic:board-visibility" ) ], known_epic_keys=KNOWN )
    text   = reach_disclosure( report, KNOWN, include_terminal=False, truncated=False )

    assert "the caller must say so" not in text


def test_the_frame_lines_survive_a_clean_and_a_dirty_board_alike():
    for rows in ( [ _row( "t5", "epic:board-visibility" ) ], [ _row( "t6", "" ) ] ):
        text = reach_disclosure( audit_rows( rows, known_epic_keys=KNOWN ), KNOWN,
                                 include_terminal=False, truncated=False )
        assert "row-status frame" in text and "fetch truncated" in text


def test_quick_smoke_test_passes():
    """The module's own CLI smoke block is excluded from coverage BY POLICY, not because
    it is unreachable — so it gets a pytest wrapper like the rest of the house."""
    from cosa.rest.task_store_epic_keys import quick_smoke_test
    quick_smoke_test()
