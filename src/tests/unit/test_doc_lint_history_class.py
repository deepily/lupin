"""
The history class of the claim check (row 9d40b2af): a dropped claim that is only history is excused,
a dropped reason or behaviour is still lost.

Every text here is written for this file from the rule's own examples (workflow/docstring-content.md
section 2). No model is called and no pilot data is read.
"""

import hashlib
import inspect

import pytest

from cosa.repo.doc_lint import claim_extractor as ce
from cosa.repo.doc_lint import harness_report as hr
from cosa.repo.doc_lint import harness_runner as hn
from cosa.repo.doc_lint import history_class as hc

CONFIG = hn.HarnessConfig( "ext-m", "judge-m", "esc-m", "writer-m" )

HISTORY_CLAIM = ( "Rick ruled on row 1e12cc08 on 2026-09-30 that the flag was added after the incident.", "Rick ruled on row 1e12cc08 on 2026-09-30." )
REASON_CLAIM  = ( "Both callers share one implementation, so they match the same rows.", "Both callers share one implementation, so they match the same rows." )


@pytest.mark.parametrize( "text, kind", [
    ( "Fixed 2026-09-30 after review.",                    "date" ),
    ( "Changed on Sept 3, 2026.",                          "date" ),
    ( "UPDATE: the loop was reworked.",                    "date" ),
    ( "The parser was added in 2026.",                     "date" ),
    ( "Tracked in row 1e12cc08.",                          "id" ),
    ( "See ticket 4812.",                                  "id" ),
    ( "Landed in commit 7fb35af.",                         "id" ),
    ( "Introduced by 394f6c9e9d.",                         "id" ),
    ( "Session 582a4885 found it.",                        "id" ),
    ( "Rick ruled that agents may be listed.",             "provenance" ),
    ( "This was found by the review crew.",                "provenance" ),
    ( "After the incident every parked row had the flag.", "incident" ),
    ( "The loop took 47 seconds.",                         "incident" ),
    ( "It was measured on the dev box.",                   "incident" ),
    ( "0 of 2 correct.",                                   "incident" ),
    ( "The queue was previously drained by hand.",         "narrative" ),
    ( "This used to be a separate call.",                  "narrative" ),
    ( "A copy would have been the obvious move.",          "narrative" ),
    ( "The first design was rejected.",                    "narrative" ),
] )
def test_each_history_kind_is_named( text, kind ):
    assert kind in hc.history_kinds( text, "" )


@pytest.mark.parametrize( "text", [
    "Both callers share one implementation, so they match the same rows.",
    "The flag is computed when the row is parked.",
    "The window is ten minutes long.",
    "Returns None when the row is parked.",
    "The gate opens below 1.5.",
    "The lock is no longer held after return.",
    "Returns the input unchanged.",
    "An API-key caller has no login account, so the router refuses the attestation key.",
    "Version 2 of the format is read.",
] )
def test_a_reason_or_behaviour_is_not_history( text ):
    assert hc.history_kinds( text, "" ) == []


@pytest.mark.parametrize( "text", [
    "Rick ruled on row 1e12cc08 that agents may not attest.",
    "After the incident on 2026-09-30 the flag is computed when the row is parked, because a stale flag misleads.",
    "The loop took 47 seconds because it re-reads the file; the code must cache it.",
    "Row 1e12cc08 added a check that raises ValueError when the id is blank.",
    "This used to be a separate call, but it now returns the cached row.",
] )
def test_a_claim_mixing_history_with_a_reason_is_not_excused( text ):
    assert hc.is_history( text, "" ) is False


def test_a_reason_in_the_quote_alone_keeps_the_claim_lost():
    assert hc.is_history( "Rick ruled on row 1e12cc08.", "Rick ruled on row 1e12cc08 that agents may not attest." ) is False


def test_a_history_marker_in_the_quote_alone_excuses_a_claim_with_no_reason():
    assert hc.is_history( "The flag was added.", "Added 2026-09-30." ) is True


def test_a_claim_with_no_marker_at_all_stays_lost():
    assert hc.is_history( "Two retries are made.", "Two retries are made." ) is False


def test_only_the_reason_claim_counts_as_lost_when_both_are_absent():
    claims = [ ce.Claim( HISTORY_CLAIM[ 0 ], HISTORY_CLAIM[ 1 ], 0, 10 ), ce.Claim( REASON_CLAIM[ 0 ], REASON_CLAIM[ 1 ], 20, 30 ) ]
    lost, excused = hc.split_absent( claims, [ True, True ] )
    assert lost == [ 1 ]
    assert [ i for i, _ in excused ] == [ 0 ]
    assert "provenance" in excused[ 0 ][ 1 ] and "id" in excused[ 0 ][ 1 ]


def test_a_claim_judged_present_is_in_neither_list():
    claims = [ ce.Claim( HISTORY_CLAIM[ 0 ], HISTORY_CLAIM[ 1 ], 0, 10 ), ce.Claim( REASON_CLAIM[ 0 ], REASON_CLAIM[ 1 ], 20, 30 ) ]
    assert hc.split_absent( claims, [ False, False ] ) == ( [], [] )


def test_ledger_dicts_are_split_the_same_way_as_claims():
    claims = [ { "text": HISTORY_CLAIM[ 0 ], "quote": HISTORY_CLAIM[ 1 ], "start": 0, "end": 10 },
               { "text": REASON_CLAIM[ 0 ], "quote": REASON_CLAIM[ 1 ], "start": 20, "end": 30 } ]
    lost, excused = hc.split_absent( claims, [ True, True ] )
    assert lost == [ 1 ] and [ i for i, _ in excused ] == [ 0 ]


def test_a_flag_list_of_the_wrong_length_is_refused():
    with pytest.raises( ValueError, match="2 claims but 1 flags" ):
        hc.split_absent( [ ce.Claim( "a", "a", 0, 1 ), ce.Claim( "b", "b", 0, 1 ) ], [ True ] )


def run_list( verdicts ):
    """One extractor list holding the history claim and the reason claim, judged in 3 runs with the given verdicts."""
    row = lambda verdict: { "verdict": verdict, "escalated": False, "reason": None, "noul": None }
    return { "claims": [ { "text": HISTORY_CLAIM[ 0 ], "quote": HISTORY_CLAIM[ 1 ], "start": 0, "end": 10 },
                         { "text": REASON_CLAIM[ 0 ], "quote": REASON_CLAIM[ 1 ], "start": 20, "end": 30 } ],
             "discarded": 0, "discards": [], "flags": [], "flag_words": [], "reextract_calls": 0, "parse_failed": False,
             "retry_calls": 0, "uncovered": 0.0, "longest_quote": 0.25, "runs": [ [ row( v ) for v in verdicts ] ] * 3 }


def test_the_report_counts_excused_history_apart_from_lost_claims():
    results = [ { "id": "u", "seed_span": None, "lists": [ run_list( [ "absent", "absent" ] ), run_list( [ "absent", "absent" ] ) ] } ]
    report  = hr.build_report( results, CONFIG )
    assert report[ "history_class" ] == { "version": hc.HISTORY_CLASS_VERSION, "lost": [ 1, 1 ], "excused": [ 1, 1 ] }
    assert [ l[ "claims_lost" ] for l in report[ "lists" ] ] == [ 1, 1 ]
    assert [ l[ "history_excused" ] for l in report[ "lists" ] ] == [ 1, 1 ]


def test_the_gate_figures_still_see_a_history_claim_as_dropped():
    only_history = run_list( [ "absent", "present" ] )
    results      = [ { "id": "u", "seed_span": None, "lists": [ only_history, only_history ] } ]
    report       = hr.build_report( results, CONFIG )
    assert report[ "lists" ][ 0 ][ "false_alarms" ] == 1
    assert report[ "history_class" ][ "lost" ] == [ 0, 0 ] and report[ "history_class" ][ "excused" ] == [ 1, 1 ]


def test_a_list_with_no_claims_has_nothing_lost_or_excused():
    assert hr.loss_split( { "claims": [], "runs": [] } ) == ( [], [] )


def test_the_version_is_the_hash_of_this_modules_source():
    assert hc.HISTORY_CLASS_VERSION == "history-" + hashlib.sha256( inspect.getsource( hc ).encode( "utf-8" ) ).hexdigest()[ :10 ]
