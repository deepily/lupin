"""
The history class of the claim check: a dropped claim that is only history is excused, a dropped reason
or behaviour is still lost.

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


# ---- what is history ---------------------------------------------------------------------------

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
] )
def test_a_claim_of_nothing_but_history_is_excused_and_its_kind_named( text, kind ):
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
    "This used to be a separate call.",
    "It was measured on the dev box.",
] )
def test_a_reason_or_behaviour_with_no_history_marker_is_lost( text ):
    assert hc.history_kinds( text, "" ) == []


# ---- finding 1: history is searched in the claim text only --------------------------------------

def test_a_history_marker_in_the_quote_alone_does_not_excuse_a_claim_that_states_behaviour():
    assert hc.is_history( "Skips empty rows.", "Skips empty rows (bug 4821, fixed 2026-09-01)." ) is False


def test_a_claim_with_no_history_of_its_own_stays_lost_whatever_its_quote_says():
    assert hc.is_history( "Added.", "Added 2026-09-30 in commit 7fb35af." ) is False


def test_a_reason_marker_in_the_quote_still_keeps_a_history_claim_lost():
    assert hc.is_history( "Rick ruled on row 1e12cc08.", "Rick ruled on row 1e12cc08 that agents may not attest." ) is False


# ---- finding 2: nothing but history may be left ----------------------------------------------------

@pytest.mark.parametrize( "text", [
    "The cache expires after 30 seconds, measured on 2026-09-01",
    "Skips empty rows (bug 4821 fixed this)",
    "keeps the lock; changed in 2026",
    "The cache expires after 30 seconds on 2026-09-01",
    "Rick ruled on row 1e12cc08 and the worker retries twice.",
] )
def test_a_behaviour_left_over_after_the_history_is_cut_out_keeps_the_claim_lost( text ):
    assert hc.is_history( text, "" ) is False


def test_a_bare_number_left_over_keeps_the_claim_lost():
    assert hc.is_history( "Changed 2026-09-01 and 2026.", "" ) is False


@pytest.mark.parametrize( "text", [
    "Rick ruled on row 1e12cc08 that agents may not attest.",
    "After the incident on 2026-09-30 the flag is computed when the row is parked, because a stale flag misleads.",
    "Row 1e12cc08 added a check that raises ValueError when the id is blank.",
    "This used to be a separate call, but it now returns the cached row.",
] )
def test_a_claim_mixing_history_with_a_reason_is_not_excused( text ):
    assert hc.is_history( text, "" ) is False


# ---- finding 3: ruling, ruled and according to excuse nothing alone ------------------------------

@pytest.mark.parametrize( "text", [
    "Returns the first match, by ruling.",
    "The first match wins, by ruling.",
    "Matches are ordered as ruled.",
    "Ties go to the older row, according to the spec.",
    "Provenance is found by the lookup.",
] )
def test_the_words_ruling_ruled_and_according_to_excuse_nothing_alone( text ):
    assert hc.is_history( text, "" ) is False


def test_provenance_with_an_id_attached_is_excused_only_when_nothing_else_is_left():
    assert hc.is_history( "A ruling on row 12ab34.", "" ) is True
    assert hc.is_history( "The first match wins, by ruling on row 12ab34.", "" ) is False


def test_provenance_with_a_named_person_is_excused_without_a_date_or_an_id():
    assert hc.is_history( "Maria found by Rick.", "" ) is False
    assert hc.is_history( "Rick ruled.", "" ) is True


# ---- the split -----------------------------------------------------------------------------------------

def test_only_the_reason_claim_counts_as_lost_when_both_are_absent():
    claims = [ ce.Claim( HISTORY_CLAIM[ 0 ], HISTORY_CLAIM[ 1 ], 0, 10 ), ce.Claim( REASON_CLAIM[ 0 ], REASON_CLAIM[ 1 ], 20, 30 ) ]
    lost, excused = hc.split_absent( claims, [ True, True ] )
    assert lost == [ 1 ]
    assert [ i for i, _ in excused ] == [ 0 ]
    assert excused[ 0 ][ 1 ] == [ "date", "id", "provenance" ]


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


# ---- the report ----------------------------------------------------------------------------------------

def run_list( verdicts ):
    """One extractor list holding the history claim and the reason claim, judged in 3 runs with the given verdicts."""
    row = lambda verdict: { "verdict": verdict, "escalated": False, "reason": None, "noul": None }
    return { "claims": [ { "text": HISTORY_CLAIM[ 0 ], "quote": HISTORY_CLAIM[ 1 ], "start": 0, "end": 10 },
                         { "text": REASON_CLAIM[ 0 ], "quote": REASON_CLAIM[ 1 ], "start": 20, "end": 30 } ],
             "discarded": 0, "discards": [], "flags": [], "flag_words": [], "reextract_calls": 0, "parse_failed": False,
             "retry_calls": 0, "uncovered": 0.0, "longest_quote": 0.25, "runs": [ [ row( v ) for v in verdicts ] ] * 3 }


def test_the_report_excuses_a_claim_by_its_text_and_lists_it_for_a_person_to_read():
    results = [ { "id": "u", "seed_span": None, "lists": [ run_list( [ "absent", "absent" ] ), run_list( [ "absent", "absent" ] ) ] } ]
    report  = hr.build_report( results, CONFIG )
    assert report[ "history_class" ][ "version" ] == hc.HISTORY_CLASS_VERSION
    assert report[ "history_class" ][ "lost" ] == [ 1, 1 ] and report[ "history_class" ][ "excused" ] == [ 1, 1 ]
    assert [ l[ "claims_lost" ] for l in report[ "lists" ] ] == [ 1, 1 ] and [ l[ "history_excused" ] for l in report[ "lists" ] ] == [ 1, 1 ]
    assert report[ "history_class" ][ "excused_claims" ] == [
        { "pair": "u", "list": slot, "claim": HISTORY_CLAIM[ 0 ], "quote": HISTORY_CLAIM[ 1 ], "kinds": [ "date", "id", "provenance" ] } for slot in ( 0, 1 ) ]


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
