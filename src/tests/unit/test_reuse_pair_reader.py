"""
How the two-question answer (a Noul and a Score for each entry) is read.

Design: John's Jev design, section 13.3 and the unit 2 row of 13.8.
The fixtures are written by hand from the TypeSafe Noul and Score pages.
No real Score has come back yet, so this unit is not called done until one has.
Nothing here reaches Jev.
"""
import itertools

import pytest

from lupin_mcp import reuse_pair as rpair

QMAP  = { "a.one": { "provides": "p_1", "coverage": "c_1" },
          "a.two": { "provides": "p_2", "coverage": "c_2" } }
PROBS = { "0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4 }


def noul( x=0.99 ):
    """A Noul answer as the TypeSafe page shows it."""
    return { "type": "noul", "noul": x }


def score( probs=None, value=2.0 ):
    """A Score answer as the TypeSafe page shows it."""
    return { "type": "score", "score": value, "confidence": 0.8, "legend": "x", "probabilities": dict( PROBS if probs is None else probs ) }


def response( noul_answer, score_answer, entry="a.one" ):
    """A response that answers one entry's two questions; None leaves the question out."""
    answers = {}
    if noul_answer is not None: answers[ QMAP[ entry ][ "provides" ] ] = noul_answer
    if score_answer is not None: answers[ QMAP[ entry ][ "coverage" ] ] = score_answer
    return { "answers": answers }


def read_one( noul_answer, score_answer ):
    """Read a response about a.one; returns ( answered, unasked, malformed )."""
    return rpair.pair_answers( response( noul_answer, score_answer ), { "a.one": QMAP[ "a.one" ] } )


def test_a_plain_noul_with_a_valid_score_is_answered_not_unasked():
    """The Choice reader needs a probabilities mapping, so it would mark every Noul unasked."""
    answered, unasked, malformed = read_one( noul( 0.99 ), score() )
    assert list( answered ) == [ "a.one" ] and unasked == [] and malformed == []


def test_an_answered_entry_carries_provides_coverage_and_the_scores_own_float():
    answered, _, _ = read_one( noul( 0.6 ), score( value=1.9 ) )
    row = answered[ "a.one" ]
    assert row[ "provides" ] == 0.6
    assert row[ "coverage" ] == pytest.approx( 0.7 )                  # levels 2 and 3: 0.3 + 0.4, not the float
    assert row[ "score" ] == 1.9 and row[ "confidence" ] == 0.8 and row[ "probabilities" ] == PROBS


def test_coverage_is_the_sum_of_levels_two_and_three_not_the_float():
    answered, _, _ = read_one( noul(), score( { "0": 0.0, "1": 0.9, "2": 0.1, "3": 0.0 }, value=3.0 ) )
    assert answered[ "a.one" ][ "coverage" ] == pytest.approx( 0.1 )


OK, ABSENT, BAD = "ok", "absent", "bad"
NOULS  = { OK: noul(), ABSENT: None, BAD: noul( 1.5 ) }
SCORES = { OK: score(), ABSENT: None, BAD: score( { "0": 0.5, "1": 0.5, "2": 0.5, "3": 0.5 } ) }
TABLE  = { ( OK, OK ): "answered", ( OK, ABSENT ): "unasked", ( OK, BAD ): "malformed",
           ( ABSENT, OK ): "unasked", ( ABSENT, ABSENT ): "unasked", ( ABSENT, BAD ): "malformed",
           ( BAD, OK ): "malformed", ( BAD, ABSENT ): "malformed", ( BAD, BAD ): "malformed" }


@pytest.mark.parametrize( "n,s", list( itertools.product( ( OK, ABSENT, BAD ), repeat=2 ) ) )
def test_each_cell_of_the_noul_by_score_table( n, s ):
    answered, unasked, malformed = read_one( NOULS[ n ], SCORES[ s ] )
    got = "answered" if answered else "unasked" if unasked else "malformed"
    assert got == TABLE[ ( n, s ) ]
    assert len( answered ) + len( unasked ) + len( malformed ) == 1       # each entry lands in exactly one list


def test_the_table_has_nine_cells_and_the_loop_ran_over_them():
    assert len( TABLE ) == 9 == len( list( itertools.product( ( OK, ABSENT, BAD ), repeat=2 ) ) )


def test_malformed_wins_over_unasked_and_lists_both_reasons():
    _, unasked, malformed = read_one( None, SCORES[ BAD ] )
    assert unasked == [] and [ m[ "id" ] for m in malformed ] == [ "a.one" ]
    reasons = " | ".join( malformed[ 0 ][ "reasons" ] )
    assert "provides" in reasons and "coverage" in reasons


def test_a_valid_noul_beside_a_malformed_score_is_never_half_used():
    answered, _, malformed = read_one( noul( 0.9 ), SCORES[ BAD ] )
    assert answered == {} and len( malformed ) == 1


def test_a_valid_score_beside_a_malformed_noul_is_never_half_used():
    answered, _, malformed = read_one( NOULS[ BAD ], score() )
    assert answered == {} and len( malformed ) == 1


@pytest.mark.parametrize( "bad,why", [ ( { "type": "choice", "probabilities": { "reuse": 0.7, "extend": 0.2, "unrelated": 0.1 } }, "type" ),
                                       ( { "type": "score", "score": 1.0, "probabilities": dict( PROBS ) }, "type" ),
                                       ( { "probabilities": { "reuse": 0.7, "extend": 0.2, "unrelated": 0.1 } }, "type" ),
                                       ( { "type": "noul" }, "number" ),
                                       ( { "type": "noul", "noul": True }, "number" ),
                                       ( { "type": "noul", "noul": "0.9" }, "number" ),
                                       ( { "type": "noul", "noul": -0.1 }, "range" ),
                                       ( { "type": "noul", "noul": 1.1 }, "range" ),
                                       ( { "type": "noul", "noul": float( "nan" ) }, "range" ) ] )
def test_a_present_but_wrong_noul_is_malformed_with_its_reason( bad, why ):
    answered, unasked, malformed = read_one( bad, score() )
    assert answered == {} and unasked == [] and len( malformed ) == 1
    assert why in " ".join( malformed[ 0 ][ "reasons" ] )


@pytest.mark.parametrize( "bad,why", [ ( { "type": "noul", "noul": 0.9 }, "type" ),
                                       ( { "type": "choice", "probabilities": { "reuse": 0.7, "extend": 0.2, "unrelated": 0.1 } }, "type" ),
                                       ( { "type": "score", "probabilities": { "0": 0.5, "1": 0.5, "2": 0.0 } }, "levels" ),
                                       ( { "type": "score", "probabilities": { "0": 0.25, "1": 0.25, "2": 0.25, "3": 0.25, "4": 0.0 } }, "levels" ),
                                       ( { "type": "score", "probabilities": { "0": 0.25, "1": 0.25, "2": 0.25, "x": 0.25 } }, "levels" ),
                                       ( { "type": "score", "probabilities": { "0": True, "1": 0.0, "2": 0.0, "3": 0.0 } }, "number" ),
                                       ( { "type": "score", "probabilities": { "0": "a", "1": 0.0, "2": 0.0, "3": 1.0 } }, "number" ),
                                       ( { "type": "score", "probabilities": { "0": -0.5, "1": 0.5, "2": 0.5, "3": 0.5 } }, "range" ),
                                       ( { "type": "score", "probabilities": { "0": 1.5, "1": -0.5, "2": 0.0, "3": 0.0 } }, "range" ),
                                       ( { "type": "score", "probabilities": { "0": 0.5, "1": 0.5, "2": 0.5, "3": 0.5 } }, "sum" ),
                                       ( { "type": "score", "probabilities": { "0": 0.1, "1": 0.1, "2": 0.1, "3": 0.1 } }, "sum" ),
                                       ( { "type": "score", "probabilities": float( "nan" ) }, "levels" ),
                                       ( { "type": "score", "probabilities": { "0": float( "nan" ), "1": 0.5, "2": 0.5, "3": 0.0 } }, "range" ),
                                       ( { "type": "score" }, "levels" ) ] )
def test_a_present_but_wrong_score_is_malformed_with_its_reason( bad, why ):
    answered, unasked, malformed = read_one( noul(), bad )
    assert answered == {} and unasked == [] and len( malformed ) == 1
    assert why in " ".join( malformed[ 0 ][ "reasons" ] )


def test_probabilities_summing_to_one_within_the_tolerance_are_accepted_and_beyond_it_are_not():
    outside = { "0": 0.25, "1": 0.25, "2": 0.25, "3": 0.2 }         # sum 0.95, 0.05 off: outside
    near    = { "0": 0.25, "1": 0.25, "2": 0.25, "3": 0.24 }         # sum 0.99, 0.01 off: inside
    assert read_one( noul(), score( near ) )[ 0 ]
    assert read_one( noul(), score( outside ) )[ 2 ]


def test_the_score_float_is_kept_when_a_number_and_none_otherwise():
    assert read_one( noul(), score( value=0.5 ) )[ 0 ][ "a.one" ][ "score" ] == 0.5
    odd = score(); del odd[ "score" ]
    assert read_one( noul(), odd )[ 0 ][ "a.one" ][ "score" ] is None
    odd[ "score" ] = True
    assert read_one( noul(), odd )[ 0 ][ "a.one" ][ "score" ] is None


@pytest.mark.parametrize( "answer", [ "x", 3, [ 1 ], True, None ] )
def test_an_answer_that_is_not_a_mapping_is_absent_not_malformed( answer ):
    answers = { "p_1": answer, "c_1": score() }
    answered, unasked, malformed = rpair.pair_answers( { "answers": answers }, { "a.one": QMAP[ "a.one" ] } )
    assert answered == {} and unasked == [ "a.one" ] and malformed == []


@pytest.mark.parametrize( "resp", [ None, {}, { "answers": None }, { "answers": [] }, { "answers": "x" } ] )
def test_a_response_with_no_usable_answers_leaves_every_entry_unasked( resp ):
    answered, unasked, malformed = rpair.pair_answers( resp, QMAP )
    assert answered == {} and unasked == [ "a.one", "a.two" ] and malformed == []


def test_two_entries_are_read_apart_and_keep_the_order_of_the_map():
    resp = { "answers": { "p_1": noul( 0.2 ), "c_1": score(), "p_2": noul( 9 ), "c_2": score() } }
    answered, unasked, malformed = rpair.pair_answers( resp, QMAP )
    assert list( answered ) == [ "a.one" ] and answered[ "a.one" ][ "provides" ] == 0.2
    assert [ m[ "id" ] for m in malformed ] == [ "a.two" ] and unasked == []


def test_an_answer_for_a_question_nobody_asked_is_ignored():
    resp = response( noul(), score() )
    resp[ "answers" ][ "p_stranger" ] = noul( 99 )
    answered, unasked, malformed = rpair.pair_answers( resp, { "a.one": QMAP[ "a.one" ] } )
    assert list( answered ) == [ "a.one" ] and unasked == [] and malformed == []


def test_two_entries_that_share_a_question_key_are_malformed_because_one_answer_cannot_be_two():
    shared = { "a.one": { "provides": "p_1", "coverage": "c_1" }, "a.two": { "provides": "p_1", "coverage": "c_2" } }
    resp   = { "answers": { "p_1": noul(), "c_1": score(), "c_2": score() } }
    answered, unasked, malformed = rpair.pair_answers( resp, shared )
    assert answered == {} and sorted( m[ "id" ] for m in malformed ) == [ "a.one", "a.two" ]
    assert "repeated" in " ".join( malformed[ 0 ][ "reasons" ] )


def test_the_reader_does_not_change_the_response():
    resp = response( noul(), score() )
    before = repr( resp )
    rpair.pair_answers( resp, { "a.one": QMAP[ "a.one" ] } )
    assert repr( resp ) == before


def test_a_noul_of_exactly_one_and_of_exactly_zero_are_answered():
    assert read_one( noul( 1 ), score() )[ 0 ][ "a.one" ][ "provides" ] == 1
    assert read_one( noul( 0 ), score() )[ 0 ][ "a.one" ][ "provides" ] == 0


@pytest.mark.parametrize( "level", LEVEL_NAMES := ( "0", "1", "2", "3" ) )
def test_a_one_hot_score_is_answered_at_every_level( level ):
    one_hot = { k: ( 1 if k == level else 0 ) for k in LEVEL_NAMES }
    row     = read_one( noul(), score( one_hot ) )[ 0 ][ "a.one" ]
    assert row[ "coverage" ] == ( 1 if level in ( "2", "3" ) else 0 )


def test_the_probabilities_returned_are_a_copy_of_the_responses():
    resp   = response( noul(), score() )
    answer = rpair.pair_answers( resp, { "a.one": QMAP[ "a.one" ] } )[ 0 ][ "a.one" ]
    answer[ "probabilities" ][ "0" ] = 99
    assert resp[ "answers" ][ "c_1" ][ "probabilities" ][ "0" ] == PROBS[ "0" ]
