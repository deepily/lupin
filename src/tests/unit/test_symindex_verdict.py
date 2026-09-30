"""
Row-by-row tests of the check_exists decision table (README-reuse-decision-table.md).
"""
import pytest

from cosa.repo.symindex import verdict as vd


def _p( reuse, extend, unrelated ): return { "reuse": reuse, "extend": extend, "unrelated": unrelated }


def _unrelated( n ): return [ { "id": f"u{i}", "probabilities": _p( 0.05, 0.05, 0.9 ) } for i in range( n ) ]


def _sweep( extra, n_unrelated=50 ):
    rows = _unrelated( n_unrelated ) + extra
    return rows, len( rows )


def _decide( extra, failed=0, flags=(), n_unrelated=50 ):
    rows, total = _sweep( extra, n_unrelated )
    return vd.decide( rows, total, failed, set( flags ) )


def test_thousands_of_confident_unrelated_entries_give_new():
    r = _decide( [], n_unrelated=5000 )
    assert ( r[ "verdict" ], r[ "cause" ], r[ "causes" ], r[ "shortlist" ], r[ "shortlist_total" ] ) == ( "NEW", None, [], [], 0 )


def test_weakly_unrelated_entries_below_the_floor_do_not_cause_uncertainty():
    r = _decide( [ { "id": "w", "probabilities": _p( 0.2, 0.05, 0.75 ) } ] )       # p_overlap 0.25 < F, confidence 0.75 < C
    assert r[ "verdict" ] == "NEW" and r[ "causes" ] == []


def test_reuse_and_extend_rows():
    assert _decide( [ { "id": "a", "probabilities": _p( 0.95, 0.03, 0.02 ) } ] )[ "verdict" ] == "REUSE"
    r = _decide( [ { "id": "a", "probabilities": _p( 0.02, 0.92, 0.06 ) } ] )
    assert r[ "verdict" ] == "EXTEND" and [ s[ "id" ] for s in r[ "shortlist" ] ] == [ "a" ]
    mixed = _decide( [ { "id": "e", "probabilities": _p( 0.02, 0.95, 0.03 ) }, { "id": "r", "probabilities": _p( 0.91, 0.05, 0.04 ) } ] )
    assert mixed[ "verdict" ] == "REUSE"                                              # REUSE wins when any relevant entry says reuse
    assert [ s[ "id" ] for s in mixed[ "shortlist" ] ] == [ "e", "r" ]                # ordered by p_overlap, not by choice


def test_low_confidence_relevant_and_band_calls_are_uncertain():
    for probs in ( _p( 0.6, 0.0, 0.4 ), _p( 0.3, 0.1, 0.6 ), _p( 0.4, 0.4, 0.2 ) ):
        r = _decide( [ { "id": "x", "probabilities": probs } ] )
        assert ( r[ "verdict" ], r[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE" ), probs


def test_failed_calls_and_short_sweeps_are_call_failed_never_new():
    r = _decide( [], failed=1 )
    assert ( r[ "verdict" ], r[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "CALL_FAILED" )
    rows = _unrelated( 10 )
    short = vd.decide( rows, 12, 0, set() )                                           # 2 entries never answered
    assert short[ "cause" ] == "CALL_FAILED"


def test_each_pipeline_flag_becomes_its_own_cause():
    for flag in ( "NOT_LUPIN_TREE", "DEPENDENCY_MISSING", "INDEX_STALE", "KEY_UNREADABLE" ):
        r = _decide( [], flags={ flag } )
        assert ( r[ "verdict" ], r[ "cause" ], r[ "causes" ] ) == ( "UNCERTAIN_READ_SOURCE", flag, [ flag ] )


def test_precedence_is_pipeline_order_and_every_holding_cause_is_listed():
    r = _decide( [ { "id": "d", "probabilities": _p( 0.6, 0.0, 0.4 ) } ], failed=1 )
    assert ( r[ "cause" ], r[ "causes" ] ) == ( "CALL_FAILED", [ "CALL_FAILED", "LOW_CONFIDENCE" ] )
    r = _decide( [], flags={ "KEY_UNREADABLE", "INDEX_STALE" } )
    assert ( r[ "cause" ], r[ "causes" ] ) == ( "INDEX_STALE", [ "INDEX_STALE", "KEY_UNREADABLE" ] )
    r = _decide( [], failed=2, flags=set( vd.CAUSES ) )
    assert r[ "causes" ] == list( vd.CAUSES ) and r[ "cause" ] == "NOT_LUPIN_TREE"


def test_shortlist_is_cut_at_k_with_the_total_recorded_and_ties_broken_by_id():
    extra = [ { "id": f"r{i:02d}", "probabilities": _p( 0.9, 0.05, 0.05 ) } for i in range( 14 ) ]
    r = _decide( extra )
    assert r[ "shortlist_total" ] == 14 and len( r[ "shortlist" ] ) == 10
    assert [ s[ "id" ] for s in r[ "shortlist" ] ] == [ f"r{i:02d}" for i in range( 10 ) ]


def test_call_facts_and_ties():
    assert vd.call_facts( _p( 0.5, 0.5, 0.0 ) ) == ( 1.0, 0.5, "reuse" )
    assert vd.call_facts( _p( 0.0, 0.5, 0.5 ) ) == ( 0.5, 0.5, "extend" )
    assert vd.call_facts( _p( 0.1, 0.1, 0.8 ) )[ 2 ] == "unrelated"
