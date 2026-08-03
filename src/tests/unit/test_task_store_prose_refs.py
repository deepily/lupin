"""
Unit tests for the (A)-arm prose-ref scanner — store row 00a6bde2, item 4.

WHAT THESE TESTS ARE GUARDING, stated so a future reader does not weaken them by accident:

  1. THE TIER IS A SAFETY PROPERTY, NOT AN OPTIMISATION. An 8-hex token must never be
     resolved, because commit shas, amendment session-ids and task ids are the same shape.
     `test_abbreviated_token_is_never_a_finding_even_when_it_prefixes_a_dead_id` is the
     negative control for that: it hands the scanner an 8-hex prefix OF A GENUINELY DEAD
     ROW and requires ZERO findings. It must FAIL if anyone adds a prefix resolve.

  2. THE SCOPE DISCLOSURE IS PART OF THE OUTPUT. `test_scope_disclosure_names_the_B_arm`
     asserts on the text because a scan that reports clean without naming the unscanned
     (B) half is the exact false-green the row exists to prevent.

  3. THE THREE BUCKETS ARE NEVER COLLAPSED. A count that silently rolls the unresolved
     bucket into "clean" turns this instrument into an instance of the class it detects.
"""

import pytest

from cosa.rest.task_store_prose_refs import (
    strip_amendment_stamps,
    extract_prose_refs,
    classify_prose_refs,
    aggregate_counts,
    scope_disclosure,
    scan_rows,
    candidate_ref_ids,
    quick_smoke_test,
)


LIVE_ID  = "11111111-1111-4111-8111-111111111111"
DEAD_ID  = "22222222-2222-4222-8222-222222222222"
GONE_ID  = "33333333-3333-4333-8333-333333333333"
NEVER_ID = "44444444-4444-4444-8444-444444444444"

STAMP    = "[amendment · mr radio 43ff094e · 2026-07-25T22:02:28.169063+00:00]"


# ----------------------------------------------------------------------------------
# strip_amendment_stamps
# ----------------------------------------------------------------------------------

def test_strip_amendment_stamps_removes_and_counts():
    text, n = strip_amendment_stamps( f"before {STAMP} after" )
    assert n == 1
    assert "43ff094e" not in text
    assert "before" in text and "after" in text


def test_strip_amendment_stamps_counts_stamps_not_distinct_seats():
    """Two amendments by ONE seat count 2 — the question is how much text was withheld."""
    _, n = strip_amendment_stamps( f"{STAMP}\nmiddle\n{STAMP}" )
    assert n == 2


def test_strip_amendment_stamps_on_non_string_is_empty_not_raise():
    assert strip_amendment_stamps( None ) == ( "", 0 )
    assert strip_amendment_stamps( 42 )   == ( "", 0 )


def test_strip_amendment_stamps_leaves_a_body_with_no_stamps_alone():
    body = "plain body, no headers"
    assert strip_amendment_stamps( body ) == ( body, 0 )


# ----------------------------------------------------------------------------------
# extract_prose_refs
# ----------------------------------------------------------------------------------

def test_extract_finds_canonical_uuid():
    refs = extract_prose_refs( f"blocked on {LIVE_ID} for now" )
    assert refs[ "canonical" ] == [ LIVE_ID ]


def test_extract_lowercases_and_dedupes_canonical():
    body = f"{LIVE_ID.upper()} and again {LIVE_ID}"
    assert extract_prose_refs( body )[ "canonical" ] == [ LIVE_ID ]


def test_extract_preserves_first_appearance_order():
    body = f"{DEAD_ID} then {LIVE_ID} then {DEAD_ID}"
    assert extract_prose_refs( body )[ "canonical" ] == [ DEAD_ID, LIVE_ID ]


def test_a_uuids_own_first_group_never_lands_in_the_abbreviated_bucket():
    """
    Canonicals are excised BEFORE the abbreviation pass. Without that, every full UUID
    would donate a phantom 8-hex citation of itself and inflate the unresolved bucket
    with tokens that were never separate references.
    """
    refs = extract_prose_refs( f"cites {DEAD_ID}" )
    assert refs[ "abbreviated" ] == [ ]


def test_extract_finds_abbreviated_tokens_and_dedupes():
    refs = extract_prose_refs( "see 97c12d68 and 97c12d68 and deadbeef" )
    assert refs[ "abbreviated" ] == [ "97c12d68", "deadbeef" ]


def test_amendment_stamp_session_ids_are_excluded_from_the_abbreviated_bucket():
    refs = extract_prose_refs( f"{STAMP}\ncites 97c12d68" )
    assert refs[ "abbreviated" ]     == [ "97c12d68" ]
    assert refs[ "stamps_excluded" ] == 1


def test_extract_on_non_string_body_is_empty():
    refs = extract_prose_refs( None )
    assert refs == { "canonical": [ ], "abbreviated": [ ], "stamps_excluded": 0 }


# ----------------------------------------------------------------------------------
# classify_prose_refs — the finding logic
# ----------------------------------------------------------------------------------

def test_citing_a_dropped_id_with_no_edge_is_a_finding():
    result = classify_prose_refs( f"blocked on {DEAD_ID}", [ ], { DEAD_ID: "dropped" } )
    assert result[ "findings" ] == [ { "id": DEAD_ID, "status": "dropped", "reason": "terminal" } ]
    assert result[ "resolved_terminal" ] == 1


def test_citing_a_done_id_with_no_edge_is_a_finding():
    result = classify_prose_refs( f"waits on {DEAD_ID}", [ ], { DEAD_ID: "done" } )
    assert [ f[ "reason" ] for f in result[ "findings" ] ] == [ "terminal" ]


def test_citing_a_live_id_is_not_a_finding_the_negative_control():
    """If this ever produces a finding, the oracle is inverted."""
    result = classify_prose_refs( f"waits on {LIVE_ID}", [ ], { LIVE_ID: "queued" } )
    assert result[ "findings" ]      == [ ]
    assert result[ "resolved_live" ] == 1


def test_a_terminal_citation_already_carried_by_an_edge_is_suppressed():
    """
    blocker_terminal already reports this row. Counting it here too would double-report
    one strand under two instruments and inflate the board's finding count without the
    board having got worse.
    """
    blocked_by = [ { "kind": "item", "id": DEAD_ID } ]
    result     = classify_prose_refs( f"blocked on {DEAD_ID}", blocked_by, { DEAD_ID: "dropped" } )
    assert result[ "findings" ]          == [ ]
    assert result[ "edge_covered" ]      == 1
    assert result[ "resolved_terminal" ] == 1


def test_edge_match_is_case_insensitive():
    blocked_by = [ { "kind": "item", "id": DEAD_ID.upper() } ]
    result     = classify_prose_refs( f"on {DEAD_ID}", blocked_by, { DEAD_ID: "dropped" } )
    assert result[ "edge_covered" ] == 1


def test_a_persona_edge_does_not_suppress_a_prose_finding():
    """item_blocker_ids filters on kind — a persona edge is not an item edge."""
    blocked_by = [ { "kind": "persona", "id": DEAD_ID } ]
    result     = classify_prose_refs( f"on {DEAD_ID}", blocked_by, { DEAD_ID: "dropped" } )
    assert len( result[ "findings" ] ) == 1


def test_looked_up_and_absent_is_a_finding_marked_absent():
    result = classify_prose_refs( f"on {GONE_ID}", [ ], { GONE_ID: None } )
    assert result[ "findings" ] == [ { "id": GONE_ID, "status": None, "reason": "absent" } ]


def test_never_looked_up_is_unresolved_not_a_finding():
    """
    Absence from the map is a fact about the LOOKUP, not about the row. Promoting it to a
    finding would manufacture one for every id the caller forgot to batch.
    """
    result = classify_prose_refs( f"on {NEVER_ID}", [ ], { } )
    assert result[ "findings" ]             == [ ]
    assert result[ "unresolved_canonical" ] == 1


def test_abbreviated_token_is_never_a_finding_even_when_it_prefixes_a_dead_id():
    """
    🔴 THE TIER'S NEGATIVE CONTROL. `22222222` is the exact 8-hex prefix of DEAD_ID, which
    IS in the status map as `dropped`. A prefix resolve would report a finding here — and
    would report one identically for any commit sha or amendment session id sharing eight
    hex chars with a task. This test MUST fail if anyone adds prefix resolution.
    """
    result = classify_prose_refs( "blocked on 22222222", [ ], { DEAD_ID: "dropped" } )
    assert result[ "findings" ]               == [ ]
    assert result[ "resolved_terminal" ]      == 0
    assert result[ "unresolved_abbreviated" ] == 1


def test_multiple_citations_classify_independently():
    body   = f"{LIVE_ID} and {DEAD_ID} and {NEVER_ID} and 97c12d68\n{STAMP}"
    result = classify_prose_refs( body, [ ], { LIVE_ID: "queued", DEAD_ID: "done" } )
    assert result[ "resolved_live" ]           == 1
    assert result[ "resolved_terminal" ]       == 1
    assert result[ "unresolved_canonical" ]    == 1
    assert result[ "unresolved_abbreviated" ]  == 1
    assert result[ "stamps_excluded" ]         == 1
    assert len( result[ "findings" ] )         == 1


def test_a_premise_only_body_produces_nothing_at_all():
    """The (B) arm: no token, therefore no finding AND no count. Invisible by construction."""
    result = classify_prose_refs( "blocked until the demos ship", [ ], { } )
    assert result[ "findings" ] == [ ]
    assert all( result[ key ] == 0 for key in
                ( "resolved_live", "resolved_terminal", "unresolved_canonical",
                  "unresolved_abbreviated", "stamps_excluded", "edge_covered" ) )


# ----------------------------------------------------------------------------------
# aggregate_counts / scope_disclosure / scan_rows / candidate_ref_ids
# ----------------------------------------------------------------------------------

def test_aggregate_counts_on_empty_is_all_zero():
    totals = aggregate_counts( [ ] )
    assert set( totals ) == { "resolved_live", "resolved_terminal", "unresolved_canonical",
                              "unresolved_abbreviated", "stamps_excluded", "edge_covered" }
    assert all( value == 0 for value in totals.values() )


def test_aggregate_counts_sums_across_rows():
    a = classify_prose_refs( f"on {DEAD_ID}", [ ], { DEAD_ID: "done" } )
    b = classify_prose_refs( f"on {LIVE_ID}", [ ], { LIVE_ID: "queued" } )
    totals = aggregate_counts( [ a, b ] )
    assert totals[ "resolved_terminal" ] == 1
    assert totals[ "resolved_live" ]     == 1


def test_scope_disclosure_names_the_B_arm_and_the_low_confidence_tier():
    """
    The disclosure is REQUIRED output. A clean (A) result that does not name what it could
    not see reads as "no dangling preconditions" across a board whose larger half was
    never examined.
    """
    text = scope_disclosure( 7, aggregate_counts( [ ] ) )
    assert "NOT COVERED (B)" in text
    assert "NOT COVERED (A)" in text
    assert "UNRESOLVED"      in text
    assert "7 non-terminal bodies" in text


def test_scan_rows_names_the_citing_row_not_just_the_cited_id():
    rows = [ { "id": "r1", "title": "T", "status": "queued",
               "body": f"on {DEAD_ID}", "blocked_by": [ ] } ]
    report = scan_rows( rows, { DEAD_ID: "dropped" } )
    assert report[ "findings" ] == [ {
        "row_id": "r1", "row_title": "T", "row_status": "queued",
        "cited_id": DEAD_ID, "cited_state": "dropped", "reason": "terminal"
    } ]
    assert report[ "bodies_scanned" ] == 1


def test_scan_rows_always_carries_the_scope_even_when_clean():
    report = scan_rows( [ { "id": "r", "body": "nothing here", "blocked_by": [ ] } ], { } )
    assert report[ "findings" ] == [ ]
    assert "NOT COVERED (B)" in report[ "scope" ]


def test_scan_rows_on_an_empty_board():
    report = scan_rows( [ ], { } )
    assert report[ "bodies_scanned" ] == 0
    assert report[ "findings" ]       == [ ]


def test_candidate_ref_ids_returns_only_canonical_deduped():
    rows = [ { "body": f"{DEAD_ID} and 97c12d68" }, { "body": f"{DEAD_ID} and {LIVE_ID}" } ]
    assert candidate_ref_ids( rows ) == [ DEAD_ID, LIVE_ID ]


def test_candidate_ref_ids_cannot_surface_the_abbreviated_tier():
    """The tier expressed as an API: there is no seam through which a prefix reaches a resolve."""
    assert candidate_ref_ids( [ { "body": "97c12d68 deadbeef" } ] ) == [ ]


@pytest.mark.parametrize( "token", [
    "11111111-1111-1111-1111-111111111111",   # nil-ish variant field
    "ffffffff-ffff-ffff-ffff-ffffffffffff",   # all-f
    "00000000-0000-0000-0000-000000000000",   # all-zero
    "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",   # uppercase
] )
def test_the_canonical_regex_only_ever_yields_canonical_uuids( token ):
    """
    PINS THE INVARIANT THAT LET classify_prose_refs DROP ITS is_canonical_uuid RE-CHECK.
    Every CANONICAL_UUID_RE match must satisfy is_canonical_uuid after lowercasing — if a
    future loosening of the regex breaks that, this fails HERE, at the regex, rather than
    silently re-routing a low-confidence token into the HIGH tier downstream.
    """
    from cosa.rest.task_store_owed import is_canonical_uuid
    extracted = extract_prose_refs( f"cites {token} inline" )[ "canonical" ]
    assert extracted == [ token.lower() ]
    assert is_canonical_uuid( extracted[ 0 ] )


def test_quick_smoke_test_runs( capsys ):
    quick_smoke_test()
    out = capsys.readouterr().out
    assert "NOT COVERED (B)" in out
