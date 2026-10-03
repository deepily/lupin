"""
The history class of the claim check: a dropped claim that looks like history is tagged and listed apart;
no claim is excused, so the lost count is every dropped claim.

Every text here is made up for this file; no pilot text and no ledger is read. No model is called.
"""

import hashlib
import inspect

import pytest

from cosa.repo.doc_lint import claim_extractor as ce
from cosa.repo.doc_lint import harness_report as hr
from cosa.repo.doc_lint import harness_runner as hn
from cosa.repo.doc_lint import history_class as hc

CONFIG = hn.HarnessConfig( "ext-m", "judge-m", "esc-m", "writer-m" )

HISTORY_CLAIM = ( "Rick ruled on row 1e12cc08 on 2026-09-30.", "Rick ruled on row 1e12cc08 on 2026-09-30, before the cache change." )
REASON_CLAIM  = ( "Both callers share one implementation, so they match the same rows.", "Both callers share one implementation, so they match the same rows." )


# ---- what is tagged ---------------------------------------------------------------------------

@pytest.mark.parametrize( "text, kind", [
    ( "Fixed 2026-09-30.",                            "date" ),
    ( "Changed on Sept 3, 2026.",                     "date" ),
    ( "UPDATE: 2026-09-30",                           "date" ),
    ( "Added in 2026.",                               "date" ),
    ( "See ticket 4812.",                             "id" ),
    ( "Landed in commit 7fb35af.",                    "id" ),
    ( "Session 582a4885 and row 1e12cc08.",           "id" ),
    ( "Rick ruled on row 1e12cc08 on 2026-09-30.",    "provenance" ),
    ( "This was found by Maria on 2026-09-01.",       "provenance" ),
    ( "The loop took 47 seconds.",                    "incident" ),
    ( "0 of 2 correct.",                              "incident" ),
    ( "The incident of 2026-09-30.",                  "incident" ),
    ( "Changed 2026-09-01; it was rejected on 2026-09-02.", "narrative" ),
    ( "This used to be a separate call.",             "narrative" ),
    ( "It was measured on the dev box.",              "incident" ),
] )
def test_a_claim_of_nothing_but_history_is_tagged_and_its_kind_named( text, kind ):
    assert kind in hc.history_kinds( text, "" )


@pytest.mark.parametrize( "text", [
    "Both callers share one implementation, so they match the same rows.",
    "The flag is computed when the row is parked.",
    "The window is ten minutes long.",
    "Returns None when the row is parked.",
    "The gate opens below 1.5.",
    "The lock is no longer held after return.",
    "Returns the input unchanged.",
    "Version 2 of the format is read.",
    "Two retries are made.",
] )
def test_a_reason_or_behaviour_with_no_history_marker_is_not_tagged( text ):
    assert hc.history_kinds( text, "" ) == []


# ---- finding 1: history is searched in the claim text only --------------------------------------

def test_a_history_marker_in_the_quote_alone_does_not_tag_a_claim_that_states_behaviour():
    assert hc.is_history( "Skips empty rows.", "Skips empty rows (bug 4821, fixed 2026-09-01)." ) is False


def test_a_claim_with_no_history_of_its_own_is_not_tagged_whatever_its_quote_says():
    assert hc.is_history( "Added.", "Added 2026-09-30 in commit 7fb35af." ) is False


def test_a_reason_marker_in_the_quote_still_keeps_a_history_claim_untagged():
    assert hc.is_history( "Rick ruled on row 1e12cc08.", "Rick ruled on row 1e12cc08 that agents may not attest." ) is False


# ---- a history marker tags the claim whatever else the claim says ------------------------------------

@pytest.mark.parametrize( "text, kind", [
    ( "The cache expires after 30 seconds, measured on 2026-09-01",     "date" ),
    ( "Skips empty rows (bug 4821 fixed this)",                        "id" ),
    ( "keeps the lock; changed in 2026",                               "date" ),
    ( "The cache expires after 30 seconds on 2026-09-01",              "date" ),
    ( "Rick ruled on row 1e12cc08 and the worker retries twice.",      "provenance" ),
    ( "Changed 2026-09-01 and 2026.",                                  "date" ),
    ( "The first match wins, by ruling on row 12ab34.",                "id" ),
    ( "Maria found by Rick.",                                          "provenance" ),
] )
def test_a_history_marker_tags_the_claim_even_when_it_also_states_behaviour( text, kind ):
    assert kind in hc.history_kinds( text, "" )


@pytest.mark.parametrize( "text", [
    "Rick ruled on row 1e12cc08 that agents may not attest.",
    "After the incident on 2026-09-30 the flag is computed when the row is parked, because a stale flag misleads.",
    "Row 1e12cc08 added a check that raises ValueError when the id is blank.",
    "This used to be a separate call, but it now returns the cached row.",
] )
def test_a_claim_mixing_history_with_a_reason_is_not_tagged( text ):
    assert hc.is_history( text, "" ) is False


# ---- finding 3: ruling, ruled and according to tag nothing alone ------------------------------

@pytest.mark.parametrize( "text", [
    "Returns the first match, by ruling.",
    "The first match wins, by ruling.",
    "Matches are ordered as ruled.",
    "Ties go to the older row, according to the spec.",
] )
def test_the_words_ruling_ruled_and_according_to_tag_nothing_alone( text ):
    assert hc.is_history( text, "" ) is False


def test_provenance_with_a_named_person_is_tagged_without_a_date_or_an_id():
    assert hc.is_history( "Rick ruled.", "" ) is True
    assert hc.is_history( "A ruling on row 12ab34.", "" ) is True


# ---- the tag ----------------------------------------------------------------------------------------------

def test_a_bare_ruling_alone_does_not_tag():
    assert hc.is_history( "ruling", "" ) is False
    assert hc.is_history( "A ruling.", "" ) is False
    assert hc.history_kinds( "Returns the first match, by ruling.", "" ) == []


def test_every_dropped_claim_stays_dropped_and_the_history_one_is_tagged_as_well():
    claims = [ ce.Claim( HISTORY_CLAIM[ 0 ], HISTORY_CLAIM[ 1 ], 0, 10 ), ce.Claim( REASON_CLAIM[ 0 ], REASON_CLAIM[ 1 ], 20, 30 ) ]
    dropped, tagged = hc.tag_absent( claims, [ True, True ] )
    assert dropped == [ 0, 1 ]
    assert tagged == [ ( 0, [ "date", "id", "provenance" ] ) ]


def test_a_claim_judged_present_is_in_neither_list():
    claims = [ ce.Claim( HISTORY_CLAIM[ 0 ], HISTORY_CLAIM[ 1 ], 0, 10 ), ce.Claim( REASON_CLAIM[ 0 ], REASON_CLAIM[ 1 ], 20, 30 ) ]
    assert hc.tag_absent( claims, [ False, False ] ) == ( [], [] )


def test_ledger_dicts_are_tagged_the_same_way_as_claims():
    claims = [ { "text": HISTORY_CLAIM[ 0 ], "quote": HISTORY_CLAIM[ 1 ], "start": 0, "end": 10 },
               { "text": REASON_CLAIM[ 0 ], "quote": REASON_CLAIM[ 1 ], "start": 20, "end": 30 } ]
    dropped, tagged = hc.tag_absent( claims, [ True, True ] )
    assert dropped == [ 0, 1 ] and [ i for i, _ in tagged ] == [ 0 ]


def test_a_flag_list_of_the_wrong_length_is_refused():
    with pytest.raises( ValueError, match="2 claims but 1 flags" ):
        hc.tag_absent( [ ce.Claim( "a", "a", 0, 1 ), ce.Claim( "b", "b", 0, 1 ) ], [ True ] )


# ---- the report ----------------------------------------------------------------------------------------

def run_list( verdicts ):
    """One extractor list holding the history claim and the reason claim, judged in 3 runs with the given verdicts."""
    row = lambda verdict: { "verdict": verdict, "escalated": False, "reason": None, "noul": None }
    return { "claims": [ { "text": HISTORY_CLAIM[ 0 ], "quote": HISTORY_CLAIM[ 1 ], "start": 0, "end": 10 },
                         { "text": REASON_CLAIM[ 0 ], "quote": REASON_CLAIM[ 1 ], "start": 20, "end": 30 } ],
             "discarded": 0, "discards": [], "flags": [], "flag_words": [], "reextract_calls": 0, "parse_failed": False,
             "retry_calls": 0, "uncovered": 0.0, "longest_quote": 0.25, "runs": [ [ row( v ) for v in verdicts ] ] * 3 }


def test_the_report_counts_every_dropped_claim_as_lost_and_lists_the_history_ones_apart():
    results = [ { "id": "u", "seed_span": None, "lists": [ run_list( [ "absent", "absent" ] ), run_list( [ "absent", "absent" ] ) ] } ]
    report  = hr.build_report( results, CONFIG )
    assert report[ "history_class" ][ "version" ] == hc.HISTORY_CLASS_VERSION
    assert report[ "history_class" ][ "lost" ] == [ 2, 2 ] and report[ "history_class" ][ "tagged" ] == [ 1, 1 ]
    assert [ l[ "claims_lost" ] for l in report[ "lists" ] ] == [ 2, 2 ] and [ l[ "history_tagged" ] for l in report[ "lists" ] ] == [ 1, 1 ]
    assert report[ "history_class" ][ "tagged_claims" ] == [
        { "pair": "u", "list": slot, "claim": HISTORY_CLAIM[ 0 ], "quote": HISTORY_CLAIM[ 1 ], "kinds": [ "date", "id", "provenance" ] } for slot in ( 0, 1 ) ]


def test_the_gate_figures_and_the_lost_count_both_see_a_history_claim_as_dropped():
    only_history = run_list( [ "absent", "present" ] )
    results      = [ { "id": "u", "seed_span": None, "lists": [ only_history, only_history ] } ]
    report       = hr.build_report( results, CONFIG )
    assert report[ "lists" ][ 0 ][ "false_alarms" ] == 1
    assert report[ "history_class" ][ "lost" ] == [ 1, 1 ] and report[ "history_class" ][ "tagged" ] == [ 1, 1 ]


def test_a_list_with_no_claims_has_nothing_dropped_or_tagged():
    assert hr.drop_tags( { "claims": [], "runs": [] } ) == ( [], [] )


def test_the_version_is_the_hash_of_this_modules_source():
    assert hc.HISTORY_CLASS_VERSION == "history-" + hashlib.sha256( inspect.getsource( hc ).encode( "utf-8" ) ).hexdigest()[ :10 ]
