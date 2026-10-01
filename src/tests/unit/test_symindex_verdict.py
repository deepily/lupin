"""
Row-by-row tests of the check_exists decision table (README-reuse-decision-table.md).

Every boundary of the policy constants has a test on each side, so a mutated comparison operator
or constant is caught by a named test.
"""
import math

import pytest

from cosa.repo.symindex import verdict as vd


def _p( reuse, extend, unrelated ): return { "reuse": reuse, "extend": extend, "unrelated": unrelated }


def _ans( i, probs ): return { "id": i, "probabilities": probs }


def _unrelated( n ): return [ _ans( f"u{i:04d}", _p( 0.05, 0.05, 0.9 ) ) for i in range( n ) ]


def _decide( extra, failed=(), flags=(), n_unrelated=50, expect_extra=True, policy=vd.POLICY ):
    rows     = _unrelated( n_unrelated ) + extra
    expected = [ r[ "id" ] for r in rows ] if expect_extra else [ r[ "id" ] for r in _unrelated( n_unrelated ) ]
    return vd.decide( rows, expected, failed, set( flags ), policy )


def test_thousands_of_confident_unrelated_entries_give_new_with_the_nearest_named():
    r = _decide( [], n_unrelated=5000 )
    assert ( r[ "verdict" ], r[ "cause" ], r[ "causes" ], r[ "shortlist" ], r[ "shortlist_total" ] ) == ( "NEW", None, [], [], 0 )
    assert len( r[ "nearest" ] ) == 10 and r[ "nearest" ][ 0 ][ "id" ] == "u0000"          # NEW still tells the reviewer what to read
    assert r[ "malformed" ] == [] and r[ "missing" ] == []


def test_relevance_boundary_is_p_overlap_at_least_threshold():
    at    = _decide( [ _ans( "at", _p( 0.25, 0.25, 0.5 ) ) ] )                                   # p_overlap exactly 0.5, confidence 0.5
    below = _decide( [ _ans( "below", _p( 0.24, 0.25, 0.51 ) ) ] )                                # p_overlap 0.49
    assert [ s[ "id" ] for s in at[ "shortlist" ] ] == [ "at" ] and below[ "shortlist" ] == []


def test_confidence_bar_boundary_is_strictly_below_point_nine():
    at   = _decide( [ _ans( "a", _p( 0.9, 0.05, 0.05 ) ) ] )                                      # confidence exactly 0.9: not doubtful
    under = _decide( [ _ans( "b", _p( 0.85, 0.1, 0.05 ) ) ] )                                     # 0.85 < 0.9 and relevant: doubtful
    assert at[ "verdict" ] == "REUSE" and under[ "cause" ] == "LOW_CONFIDENCE"


def test_floor_boundary_p_overlap_below_point_three_is_never_doubtful():
    at    = _decide( [ _ans( "at", _p( 0.3, 0.0, 0.7 ) ) ] )                                       # p_overlap exactly 0.3, confidence 0.7: doubtful
    below = _decide( [ _ans( "below", _p( 0.29, 0.0, 0.71 ) ) ] )                                 # p_overlap 0.29
    assert at[ "cause" ] == "LOW_CONFIDENCE" and ( below[ "verdict" ], below[ "causes" ] ) == ( "NEW", [] )


def test_reuse_and_extend_rows():
    assert _decide( [ _ans( "a", _p( 0.95, 0.03, 0.02 ) ) ] )[ "verdict" ] == "REUSE"
    r = _decide( [ _ans( "a", _p( 0.02, 0.92, 0.06 ) ) ] )
    assert r[ "verdict" ] == "EXTEND" and [ s[ "id" ] for s in r[ "shortlist" ] ] == [ "a" ]
    mixed = _decide( [ _ans( "e", _p( 0.02, 0.95, 0.03 ) ), _ans( "r", _p( 0.91, 0.05, 0.04 ) ) ] )
    assert mixed[ "verdict" ] == "REUSE"                                                          # REUSE wins when any relevant entry says reuse
    assert [ s[ "id" ] for s in mixed[ "shortlist" ] ] == [ "e", "r" ]                            # ordered by p_overlap, not by choice


def test_low_confidence_rows():
    for probs in ( _p( 0.6, 0.0, 0.4 ), _p( 0.3, 0.1, 0.6 ), _p( 0.4, 0.4, 0.2 ) ):
        r = _decide( [ _ans( "x", probs ) ] )
        assert ( r[ "verdict" ], r[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE" ), probs


def test_failed_calls_are_call_failed_never_new():
    r = _decide( [ _ans( "f", _p( 0.05, 0.05, 0.9 ) ) ], failed=[ "f" ], expect_extra=True )
    assert ( r[ "verdict" ], r[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "CALL_FAILED" )
    assert _decide( [], failed=[ "u0001" ] )[ "cause" ] == "CALL_FAILED"


def test_a_failed_id_is_accounted_for_and_not_reported_missing():
    r = vd.decide( [ _ans( "a", _p( 0.05, 0.05, 0.9 ) ), _ans( "b", _p( 0.05, 0.05, 0.9 ) ) ], [ "a", "b", "c" ], [ "c" ], set() )
    assert r[ "missing" ] == [] and r[ "causes" ] == [ "CALL_FAILED" ]
    r = vd.decide( [ _ans( "a", _p( 0.05, 0.05, 0.9 ) ) ], [ "a", "c" ], [], set() )
    assert r[ "missing" ] == [ "c" ]


def test_an_integer_too_large_for_a_float_is_not_finite():
    assert vd.malformed_reason( _p( 10 ** 400, 0, 0 ) ) == "not_finite"


def test_coverage_is_set_equality_not_a_count():
    """Two expected ids never answered, two answered ids nobody asked for: the counts match, the sets do not."""
    expected = [ "a", "b", "c", "d" ]
    answers  = [ _ans( "a", _p( 0.05, 0.05, 0.9 ) ), _ans( "b", _p( 0.05, 0.05, 0.9 ) ), _ans( "x", _p( 0.05, 0.05, 0.9 ) ), _ans( "y", _p( 0.05, 0.05, 0.9 ) ) ]
    r = vd.decide( answers, expected, [], set() )
    assert r[ "verdict" ] == "UNCERTAIN_READ_SOURCE"
    assert r[ "missing" ] == [ "c", "d" ] and r[ "causes" ] == [ "CALL_FAILED", "MALFORMED_ANSWER" ]
    assert [ m[ "reason" ] for m in r[ "malformed" ] ] == [ "unknown_id", "unknown_id" ]


def test_a_duplicate_answer_drops_every_copy():
    twice = [ _ans( "a", _p( 0.05, 0.05, 0.9 ) ), _ans( "a", _p( 0.95, 0.03, 0.02 ) ) ]
    r = vd.decide( twice, [ "a" ], [], set() )
    assert r[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and r[ "cause" ] == "MALFORMED_ANSWER"
    assert [ m[ "reason" ] for m in r[ "malformed" ] ] == [ "duplicate_id", "duplicate_id" ] and r[ "missing" ] == []


@pytest.mark.parametrize( "probs, reason", [
    ( None, "not_a_mapping" ), ( [ 0.2, 0.3, 0.5 ], "not_a_mapping" ),
    ( { "reuse": 0.5, "extend": 0.5 }, "missing_or_extra_keys" ), ( { **_p( 0.3, 0.3, 0.4 ), "x": 0.0 }, "missing_or_extra_keys" ),
    ( _p( "0.3", 0.3, 0.4 ), "not_a_number" ), ( _p( True, 0.0, 0.0 ), "not_a_number" ), ( _p( None, 0.3, 0.7 ), "not_a_number" ),
    ( _p( float( "nan" ), 0.5, 0.5 ), "not_finite" ), ( _p( float( "inf" ), 0.0, 0.0 ), "not_finite" ),
    ( _p( 1.2, -0.1, -0.1 ), "out_of_range" ), ( _p( 1.01, 0.0, 0.0 ), "out_of_range" ), ( _p( -0.01, 0.5, 0.51 ), "out_of_range" ),
    ( _p( 0.3, 0.3, 0.3 ), "sum_not_one" ), ( _p( 0.5, 0.5, 0.03 ), "sum_not_one" ),
] )
def test_a_malformed_answer_never_becomes_a_verdict_and_names_its_reason( probs, reason ):
    assert vd.malformed_reason( probs ) == reason
    r = _decide( [ _ans( "m", probs ) ] )
    assert ( r[ "verdict" ], r[ "cause" ], r[ "malformed" ] ) == ( "UNCERTAIN_READ_SOURCE", "MALFORMED_ANSWER", [ { "id": "m", "reason": reason } ] )
    assert r[ "missing" ] == [] and r[ "shortlist" ] == []


def test_sum_tolerance_boundary_and_integer_probabilities():
    assert vd.malformed_reason( _p( 0.49, 0.49, 0.0 ) ) is None                                 # sum 0.98: exactly on the tolerance
    assert vd.malformed_reason( _p( 0.49, 0.48, 0.0 ) ) == "sum_not_one"                        # sum 0.97
    assert vd.malformed_reason( _p( 1, 0, 0 ) ) is None and vd.malformed_reason( _p( 0, 0, 1 ) ) is None
    assert vd.malformed_reason( _p( 0.51, 0.51, 0.0 ) ) is None and vd.malformed_reason( _p( 0.52, 0.51, 0.0 ) ) == "sum_not_one"


def test_each_pipeline_flag_becomes_its_own_cause():
    for flag in ( "NOT_LUPIN_TREE", "DEPENDENCY_MISSING", "INDEX_STALE", "KEY_UNREADABLE" ):
        r = _decide( [], flags={ flag } )
        assert ( r[ "verdict" ], r[ "cause" ], r[ "causes" ] ) == ( "UNCERTAIN_READ_SOURCE", flag, [ flag ] )


def test_precedence_is_pipeline_order_and_every_holding_cause_is_listed():
    r = _decide( [ _ans( "d", _p( 0.6, 0.0, 0.4 ) ) ], failed=[ "u0001" ] )
    assert ( r[ "cause" ], r[ "causes" ] ) == ( "CALL_FAILED", [ "CALL_FAILED", "LOW_CONFIDENCE" ] )
    r = _decide( [], flags={ "KEY_UNREADABLE", "INDEX_STALE" } )
    assert ( r[ "cause" ], r[ "causes" ] ) == ( "INDEX_STALE", [ "INDEX_STALE", "KEY_UNREADABLE" ] )
    r = _decide( [ _ans( "m", None ), _ans( "d", _p( 0.6, 0.0, 0.4 ) ) ], failed=[ "u0001" ], flags=set( vd.CAUSES ) )
    assert r[ "causes" ] == list( vd.CAUSES ) and r[ "cause" ] == "NOT_LUPIN_TREE"
    r = _decide( [ _ans( "m", None ), _ans( "d", _p( 0.6, 0.0, 0.4 ) ) ] )
    assert r[ "causes" ] == [ "MALFORMED_ANSWER", "LOW_CONFIDENCE" ]                          # malformed ranks before low confidence


def test_shortlist_and_nearest_are_cut_at_k_with_the_total_recorded_and_ties_broken_by_id():
    extra = [ _ans( f"r{i:02d}", _p( 0.9, 0.05, 0.05 ) ) for i in range( 14 ) ]
    r = _decide( list( reversed( extra ) ) )                                                       # input order must not decide ties
    assert r[ "shortlist_total" ] == 14 and len( r[ "shortlist" ] ) == 10 and len( r[ "nearest" ] ) == 10
    assert [ s[ "id" ] for s in r[ "shortlist" ] ] == [ f"r{i:02d}" for i in range( 10 ) ]
    exact = _decide( extra[ :10 ] )
    assert len( exact[ "shortlist" ] ) == 10 and exact[ "shortlist_total" ] == 10
    one_more = _decide( extra[ :11 ] )
    assert len( one_more[ "shortlist" ] ) == 10 and one_more[ "shortlist_total" ] == 11
    tiny = _decide( extra[ :3 ], policy={ **vd.POLICY, "shortlist": 2 } )
    assert len( tiny[ "shortlist" ] ) == 2 and len( tiny[ "nearest" ] ) == 2


def test_nearest_orders_by_p_overlap_even_below_threshold():
    r = _decide( [ _ans( "n1", _p( 0.2, 0.2, 0.6 ) ), _ans( "n2", _p( 0.1, 0.05, 0.85 ) ) ], n_unrelated=3 )
    assert [ n[ "id" ] for n in r[ "nearest" ][ :2 ] ] == [ "n1", "n2" ]
    assert r[ "nearest" ][ 0 ][ "p_overlap" ] == 0.4


def test_reported_numbers_keep_six_decimals():
    r = _decide( [ _ans( "fine", _p( 0.123456, 0.0, 0.876544 ) ) ], n_unrelated=3 )
    assert r[ "nearest" ][ 0 ] == { "id": "fine", "p_overlap": 0.123456, "confidence": 0.876544, "choice": "unrelated" }


def test_call_facts_and_ties():
    assert vd.call_facts( _p( 0.5, 0.5, 0.0 ) ) == ( 1.0, 0.5, "reuse" )
    assert vd.call_facts( _p( 0.0, 0.5, 0.5 ) ) == ( 0.5, 0.5, "extend" )
    p, c, ch = vd.call_facts( _p( 0.1, 0.1, 0.8 ) )
    assert ( math.isclose( p, 0.2 ), c, ch ) == ( True, 0.8, "unrelated" )
