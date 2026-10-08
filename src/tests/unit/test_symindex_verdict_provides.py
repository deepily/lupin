"""
Tests of the Noul-and-Score verdict rule `decide_provides`.

It is a new function beside `decide`, which this work does not change, so the first tests pin
`decide` on a stored case. Every boundary of the policy has a test on each side, so a mutated
comparison operator or constant is caught by a named test.
"""
import pytest

from cosa.repo.symindex import verdict as vd

LEVELS = ( "0", "1", "2", "3" )


def _cov( p2=0.0, p3=0.0 ):
    """Ensures: returns a valid Score probabilities mapping whose levels 2 and 3 hold p2 and p3."""
    return { "0": round( 1.0 - p2 - p3, 6 ), "1": 0.0, "2": p2, "3": p3 }


def _a( i, provides, p23=0.0 ):
    """Ensures: returns one answer with the Noul `provides` and a Score whose level 2 holds p23."""
    return { "id": i, "provides": provides, "coverage": _cov( p23 ) }


def _low( n ): return [ _a( f"u{k:04d}", 0.05 ) for k in range( n ) ]


def _decide( extra, failed=(), flags=(), n_low=20, expect_extra=True, policy=vd.POLICY_PROVIDES ):
    rows     = _low( n_low ) + extra
    expected = [ r[ "id" ] for r in rows ] if expect_extra else [ r[ "id" ] for r in _low( n_low ) ]
    return vd.decide_provides( rows, expected, failed, set( flags ), policy )


def _ids( rows ): return [ r[ "id" ] for r in rows ]


# --- decide is not changed, and the new function returns what decide returns ---------------------------------------------

def test_decide_is_pinned_on_a_stored_case():
    answers  = [ { "id": "a", "probabilities": { "reuse": 0.95, "extend": 0.03, "unrelated": 0.02 } },
                 { "id": "b", "probabilities": { "reuse": 0.02, "extend": 0.02, "unrelated": 0.96 } } ]
    got      = vd.decide( answers, [ "a", "b" ], [], set() )
    assert got == { "verdict": "REUSE", "cause": None, "causes": [], "shortlist": [ { "id": "a", "p_overlap": 0.98, "confidence": 0.95, "choice": "reuse" } ],
                    "shortlist_total": 1,
                    "nearest": [ { "id": "a", "p_overlap": 0.98, "confidence": 0.95, "choice": "reuse" }, { "id": "b", "p_overlap": 0.04, "confidence": 0.96, "choice": "unrelated" } ],
                    "doubtful": [], "malformed": [], "missing": [] }


def test_the_policy_is_the_one_in_the_design():
    assert vd.POLICY_PROVIDES == { "threshold": 0.5, "reuse": 0.7, "floor": 0.3, "coverage": 0.5, "shortlist": 10, "sum_tolerance": 0.02 }


def test_the_new_function_returns_exactly_the_keys_decide_returns():
    old = vd.decide( [], [], [], set() )
    new = vd.decide_provides( [ _a( "a", 0.9 ) ], [ "a" ], [], set() )
    assert set( new ) == set( old )


# --- the five steps ------------------------------------------------------------------------------------------------------

def test_many_confident_unrelated_entries_give_new_with_the_nearest_named():
    r = _decide( [], n_low=5000 )
    assert ( r[ "verdict" ], r[ "cause" ], r[ "causes" ], r[ "shortlist" ], r[ "shortlist_total" ] ) == ( "NEW", None, [], [], 0 )
    assert len( r[ "nearest" ] ) == 10 and r[ "nearest" ][ 0 ][ "id" ] == "u0000"
    assert r[ "malformed" ] == [] and r[ "missing" ] == [] and r[ "doubtful" ] == []


def test_reuse_boundary_is_provides_at_least_point_seven():
    at    = _decide( [ _a( "at", 0.7 ) ] )
    below = _decide( [ _a( "below", 0.69 ) ] )
    assert at[ "verdict" ] == "REUSE" and _ids( at[ "shortlist" ] ) == [ "at" ]
    assert below[ "verdict" ] != "REUSE"


def test_extend_needs_the_band_and_coverage_at_least_a_half():
    at     = _decide( [ _a( "at", 0.4, 0.5 ) ] )
    under  = _decide( [ _a( "under", 0.4, 0.49 ) ] )
    assert at[ "verdict" ] == "EXTEND" and at[ "cause" ] is None
    assert ( under[ "verdict" ], under[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE" )


def test_floor_boundary_is_provides_at_least_point_three():
    at    = _decide( [ _a( "at", 0.3 ) ] )
    below = _decide( [ _a( "below", 0.29 ) ] )
    assert ( at[ "verdict" ], at[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE" ) and _ids( at[ "doubtful" ] ) == [ "at" ]
    assert ( below[ "verdict" ], below[ "causes" ], below[ "doubtful" ] ) == ( "NEW", [], [] )


def test_an_extend_entry_below_the_floor_is_not_an_extend_it_contradicts_itself():
    r = _decide( [ _a( "odd", 0.1, 0.9 ) ] )                    # provides low, coverage high: Jev disagrees with itself
    assert ( r[ "verdict" ], r[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "LOW_CONFIDENCE" )
    assert r[ "doubtful" ] == []                                 # it is not in the provides band, so it is not "doubtful"


def test_coverage_below_a_half_with_low_provides_is_still_new():
    assert _decide( [ _a( "ok", 0.1, 0.49 ) ] )[ "verdict" ] == "NEW"


def test_coverage_is_the_sum_of_levels_two_and_three_not_the_score_float():
    both  = { "id": "both", "provides": 0.4, "coverage": { "0": 0.5, "1": 0.0, "2": 0.25, "3": 0.25 } }
    three = { "id": "three", "provides": 0.4, "coverage": { "0": 0.5, "1": 0.0, "2": 0.0, "3": 0.5 } }
    two   = { "id": "two", "provides": 0.4, "coverage": { "0": 0.45, "1": 0.0, "2": 0.55, "3": 0.0 } }     # score float 1.1, but 0.55 sits at level 2 or more
    big   = { "id": "big", "provides": 0.4, "coverage": { "0": 0.0, "1": 0.55, "2": 0.0, "3": 0.45 } }     # score float 1.9, but only 0.45 at level 2 or more
    for a, verdict in ( ( both, "EXTEND" ), ( three, "EXTEND" ), ( two, "EXTEND" ), ( big, "UNCERTAIN_READ_SOURCE" ) ):
        r = vd.decide_provides( [ a ], [ a[ "id" ] ], [], set() )
        assert r[ "verdict" ] == verdict, a[ "id" ]


def test_the_row_carries_provides_coverage_and_the_recomputed_score():
    a = { "id": "x", "provides": 0.9, "coverage": { "0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4 } }
    r = vd.decide_provides( [ a ], [ "x" ], [], set() )
    assert r[ "shortlist" ] == [ { "id": "x", "provides": 0.9, "coverage": 0.7, "score": 2.0 } ]


def test_reuse_wins_over_extend_and_the_shortlist_is_ordered_by_provides_then_id():
    r = _decide( [ _a( "e", 0.6, 0.9 ), _a( "r", 0.8 ), _a( "q", 0.8 ) ] )
    assert r[ "verdict" ] == "REUSE"
    assert _ids( r[ "shortlist" ] ) == [ "q", "r", "e" ]


# --- the shortlist -------------------------------------------------------------------------------------------------------

def test_threshold_is_provides_at_least_a_half_and_the_cut_is_ten():
    at    = _decide( [ _a( "at", 0.5 ) ] )
    below = _decide( [ _a( "below", 0.49 ) ] )
    assert _ids( at[ "shortlist" ] ) == [ "at" ] and below[ "shortlist" ] == []
    many  = _decide( [ _a( f"r{k:02d}", 0.9 ) for k in range( 12 ) ] )
    assert len( many[ "shortlist" ] ) == 10 and many[ "shortlist_total" ] == 12 and len( many[ "nearest" ] ) == 10


def test_an_extend_caused_by_an_entry_below_the_threshold_still_lists_that_entry():
    r = _decide( [ _a( "weak", 0.35, 0.8 ) ] )
    assert r[ "verdict" ] == "EXTEND"
    assert _ids( r[ "shortlist" ] ) == [ "weak" ] and r[ "shortlist_total" ] == 1


def test_a_cut_drops_a_non_causal_entry_before_a_causal_one():
    causal = [ _a( f"c{k}", 0.35 + k / 100, 0.8 ) for k in range( 3 ) ]                   # 0.35, 0.36, 0.37: they cause EXTEND
    other  = [ _a( f"n{k:02d}", 0.6 ) for k in range( 12 ) ]                               # at or above the threshold, no coverage: not causal
    r = _decide( causal + other )
    assert r[ "verdict" ] == "EXTEND" and r[ "shortlist_total" ] == 15 and len( r[ "shortlist" ] ) == 10
    assert { "c0", "c1", "c2" } <= set( _ids( r[ "shortlist" ] ) )                          # all three causal entries stay
    assert _ids( r[ "shortlist" ] )[ :7 ] == [ f"n{k:02d}" for k in range( 7 ) ]             # the best seven of the others fill the rest, ranked by provides then id


def test_when_causal_entries_outnumber_the_cap_the_cut_ranks_within_them():
    causal = [ _a( f"c{k:02d}", 0.31 + k / 100, 0.8 ) for k in range( 12 ) ]               # 0.31 to 0.42, all cause EXTEND
    other  = [ _a( "high", 0.65 ) ]
    r = _decide( causal + other )
    assert r[ "verdict" ] == "EXTEND" and r[ "shortlist_total" ] == 13
    assert _ids( r[ "shortlist" ] ) == [ f"c{k:02d}" for k in range( 11, 1, -1 ) ]           # the ten best causal entries, best first; "high" is not causal and is dropped
    assert "c11" in _ids( r[ "shortlist" ] )[ :1 ]                                          # the best causal entry stays


def test_equal_provides_break_by_id():
    r = _decide( [ _a( "b", 0.9 ), _a( "a", 0.9 ), _a( "c", 0.9 ) ] )
    assert _ids( r[ "shortlist" ] ) == [ "a", "b", "c" ]


# --- gaps: any one of unasked, malformed or failed gives UNCERTAIN and never NEW ------------------------------------------

def test_a_failed_entry_gives_call_failed_even_when_an_entry_says_reuse():
    r = vd.decide_provides( [ _a( "r", 0.95 ) ], [ "r", "gone" ], [ "gone" ], set() )
    assert ( r[ "verdict" ], r[ "cause" ], r[ "causes" ] ) == ( "UNCERTAIN_READ_SOURCE", "CALL_FAILED", [ "CALL_FAILED" ] )
    assert _ids( r[ "shortlist" ] ) == [ "r" ] and r[ "missing" ] == []


def test_an_expected_entry_neither_answered_nor_failed_is_missing_and_never_unrelated():
    r = vd.decide_provides( _low( 5 ), [ f"u{k:04d}" for k in range( 5 ) ] + [ "lost" ], [], set() )
    assert ( r[ "verdict" ], r[ "cause" ], r[ "missing" ] ) == ( "UNCERTAIN_READ_SOURCE", "CALL_FAILED", [ "lost" ] )


@pytest.mark.parametrize( "bad, reason", [
    ( True,         "not_a_number" ),
    ( "0.9",        "not_a_number" ),
    ( None,         "not_a_number" ),
    ( float( "nan" ), "not_finite" ),
    ( float( "inf" ), "not_finite" ),
    ( 1.01,         "out_of_range" ),
    ( -0.01,        "out_of_range" ),
] )
def test_a_bad_provides_is_malformed_with_its_reason_and_never_reaches_a_verdict(bad, reason):
    a = { "id": "x", "provides": bad, "coverage": _cov() }
    r = vd.decide_provides( [ a, _a( "ok", 0.1 ) ], [ "x", "ok" ], [], set() )
    assert r[ "malformed" ] == [ { "id": "x", "reason": reason } ]
    assert ( r[ "verdict" ], r[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "MALFORMED_ANSWER" )


@pytest.mark.parametrize( "bad, reason", [
    ( "not a mapping",                                                              "not_a_mapping" ),
    ( { "reuse": 0.9, "extend": 0.05, "unrelated": 0.05 },                          "missing_or_extra_keys" ),      # a Choice-shaped answer
    ( { "0": 0.5, "1": 0.5, "2": 0.0 },                                             "missing_or_extra_keys" ),
    ( { "0": 0.5, "1": 0.0, "2": 0.0, "3": 0.5, "4": 0.0 },                         "missing_or_extra_keys" ),
    ( { "0": "0.5", "1": 0.0, "2": 0.0, "3": 0.5 },                                 "not_a_number" ),
    ( { "0": True, "1": 0.0, "2": 0.0, "3": 0.0 },                                  "not_a_number" ),
    ( { "0": float( "nan" ), "1": 0.0, "2": 0.0, "3": 0.5 },                        "not_finite" ),
    ( { "0": 1.5, "1": -0.5, "2": 0.0, "3": 0.0 },                                  "out_of_range" ),
    ( { "0": 0.5, "1": 0.0, "2": 0.0, "3": 0.4 },                                   "sum_not_one" ),
] )
def test_a_bad_score_is_malformed_with_its_reason(bad, reason):
    a = { "id": "x", "provides": 0.9, "coverage": bad }
    r = vd.decide_provides( [ a ], [ "x" ], [], set() )
    assert r[ "malformed" ] == [ { "id": "x", "reason": reason } ]
    assert r[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and r[ "shortlist" ] == []


def test_a_valid_noul_beside_a_malformed_score_is_never_half_used():
    a = { "id": "x", "provides": 0.99, "coverage": { "reuse": 0.9, "extend": 0.05, "unrelated": 0.05 } }
    r = vd.decide_provides( [ a ], [ "x" ], [], set() )
    assert r[ "shortlist" ] == [] and r[ "nearest" ] == []                                  # the 0.99 is not read at all


def test_the_sum_tolerance_boundary_is_two_hundredths():
    inside  = { "id": "in", "provides": 0.1, "coverage": { "0": 0.5, "1": 0.0, "2": 0.0, "3": 0.52 } }       # sums to 1.02
    outside = { "id": "out", "provides": 0.1, "coverage": { "0": 0.5, "1": 0.0, "2": 0.0, "3": 0.53 } }      # sums to 1.03
    assert vd.decide_provides( [ inside ], [ "in" ], [], set() )[ "malformed" ] == []
    assert vd.decide_provides( [ outside ], [ "out" ], [], set() )[ "malformed" ] == [ { "id": "out", "reason": "sum_not_one" } ]


def test_a_repeated_or_unknown_id_is_malformed_and_every_copy_is_dropped():
    r = vd.decide_provides( [ _a( "d", 0.9 ), _a( "d", 0.1 ), _a( "stranger", 0.9 ) ], [ "d" ], [], set() )
    assert sorted( ( m[ "id" ], m[ "reason" ] ) for m in r[ "malformed" ] ) == [ ( "d", "duplicate_id" ), ( "d", "duplicate_id" ), ( "stranger", "unknown_id" ) ]
    assert r[ "shortlist" ] == [] and r[ "verdict" ] == "UNCERTAIN_READ_SOURCE"


def test_nothing_answered_is_never_new():
    for expected in ( [], [ "a", "b" ] ):
        r = vd.decide_provides( [], expected, [], set() )
        assert ( r[ "verdict" ], r[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "CALL_FAILED" ), expected
        assert r[ "missing" ] == sorted( expected )
    r = vd.decide_provides( [ _a( "x", 0.1 ) ], [ "a" ], [], set() )                       # an answer for none of the expected ids
    assert r[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and r[ "causes" ] == [ "CALL_FAILED", "MALFORMED_ANSWER" ]


def test_a_known_pipeline_flag_makes_the_verdict_uncertain_whatever_the_answers_say():
    r = vd.decide_provides( [ _a( "r", 0.99 ) ], [ "r" ], [], { "INDEX_STALE" } )
    assert ( r[ "verdict" ], r[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "INDEX_STALE" )


def test_every_cause_that_holds_is_listed_in_the_order_of_causes():
    bad = { "id": "m", "provides": True, "coverage": _cov() }
    r = vd.decide_provides( [ bad, _a( "band", 0.5 ) ], [ "m", "band", "lost" ], [ "failed" ], { "KEY_UNREADABLE" } )
    assert r[ "causes" ] == [ "KEY_UNREADABLE", "CALL_FAILED", "MALFORMED_ANSWER", "LOW_CONFIDENCE" ]
    assert r[ "cause" ] == "KEY_UNREADABLE"


def test_an_uncertain_verdict_always_carries_a_cause():
    for extra in ( [ _a( "band", 0.5 ) ], [ _a( "odd", 0.1, 0.9 ) ] ):
        r = _decide( extra )
        assert r[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and r[ "cause" ] is not None
