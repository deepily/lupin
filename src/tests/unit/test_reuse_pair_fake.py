"""
The fake Jev client for the two-question request.

Design: John's Jev design, section 13.7, and the unit 3 row of 13.8.
The fake must answer from the need and each candidate's text. A fake that ignores its
input would make every assertion over it vacuous, so most tests here swap or change an input.
Nothing here reaches Jev.
"""
import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_pair as rpair
from lupin_mcp import reuse_pair_fake as fake
from lupin_mcp import reuse_pair_request as rpr
from lupin_mcp import reuse_tools as rt

NEED = "read an RSS feed and return its articles"
FEED = { "id": "cosa.feeds.parse_feed", "sig": "( url )", "doc": "Parse an RSS feed and return its articles." }
MATH = { "id": "cosa.mathx.add", "sig": "( a, b )", "doc": "Add two numbers." }


def ask( client, entries, need=NEED ):
    """Send one pack through the fake and read it; returns ( answered, unasked, malformed )."""
    body, qmap = rpr.pair_request( need, entries )
    response, _ = client.post_with_meta( body )
    return rpair.pair_answers( response, qmap )


def graded( n, doc ):
    """An entry with a neutral id, so that only its docstring shares words with the need."""
    return { "id": f"x.g{n}", "sig": "( )", "doc": doc }


def test_every_answer_round_trips_through_the_reader_as_answered():
    answered, unasked, malformed = ask( fake.PairFake( [ FEED, MATH ] ), [ FEED, MATH ] )
    assert sorted( answered ) == sorted( [ FEED[ "id" ], MATH[ "id" ] ]) and unasked == [] and malformed == []


def test_a_candidate_that_shares_the_needs_words_provides_more_than_one_that_does_not():
    answered, _, _ = ask( fake.PairFake( [ FEED, MATH ] ), [ FEED, MATH ] )
    assert answered[ FEED[ "id" ] ][ "provides" ] == pytest.approx( 0.8 )
    assert answered[ MATH[ "id" ] ][ "provides" ] == 0
    assert answered[ FEED[ "id" ] ][ "coverage" ] > answered[ MATH[ "id" ] ][ "coverage" ]


def test_swapping_two_candidates_text_swaps_their_answers():
    first, second = { "id": "x.a", "sig": "( url )", "doc": FEED[ "doc" ] }, { "id": "x.b", "sig": "( a, b )", "doc": MATH[ "doc" ] }
    swapped_first, swapped_second = dict( first, sig=second[ "sig" ], doc=second[ "doc" ] ), dict( second, sig=first[ "sig" ], doc=first[ "doc" ] )
    before, _, _ = ask( fake.PairFake( [ first, second ] ), [ first, second ] )
    after, _, _  = ask( fake.PairFake( [ swapped_first, swapped_second ] ), [ swapped_first, swapped_second ] )
    assert before[ "x.a" ][ "provides" ] == pytest.approx( 0.8 ) and before[ "x.b" ][ "provides" ] == 0
    assert after[ "x.a" ][ "provides" ] == 0 and after[ "x.b" ][ "provides" ] == pytest.approx( 0.8 )
    assert after[ "x.b" ][ "probabilities" ] == before[ "x.a" ][ "probabilities" ]
    assert after[ "x.a" ][ "probabilities" ] == before[ "x.b" ][ "probabilities" ]


def test_changing_the_need_changes_the_answer_about_the_same_candidate():
    one, _, _ = ask( fake.PairFake( [ FEED ] ), [ FEED ], need=NEED )
    two, _, _ = ask( fake.PairFake( [ FEED ] ), [ FEED ], need="add two numbers" )
    assert one[ FEED[ "id" ] ][ "provides" ] > 0.5 and two[ FEED[ "id" ] ][ "provides" ] == 0


def test_the_same_inputs_give_the_same_answers():
    entries = [ FEED, MATH ]
    assert ask( fake.PairFake( entries ), entries ) == ask( fake.PairFake( entries ), entries )


def test_coverage_levels_follow_provides_in_four_steps():
    four = [ graded( 0, "Nothing here." ), graded( 1, "Read it." ), graded( 2, "Return the feed." ), graded( 3, "Read the RSS feed and return its articles." ) ]
    answered, _, _ = ask( fake.PairFake( four ), four )
    levels = [ max( answered[ e[ "id" ] ][ "probabilities" ], key=answered[ e[ "id" ] ][ "probabilities" ].get ) for e in four ]
    assert levels == [ "0", "1", "2", "3" ]
    provides = [ answered[ e[ "id" ] ][ "provides" ] for e in four ]
    assert provides == sorted( provides ) and len( set( provides ) ) == 4


def test_the_scores_float_is_the_probability_weighted_level_and_the_sum_is_one():
    answered, _, _ = ask( fake.PairFake( [ FEED ] ), [ FEED ] )
    row = answered[ FEED[ "id" ] ]
    assert sum( row[ "probabilities" ].values() ) == pytest.approx( 1 )
    assert row[ "score" ] == pytest.approx( sum( int( k ) * v for k, v in row[ "probabilities" ].items() ) )


def test_a_candidate_text_with_quotes_and_a_newline_is_read_back_whole():
    odd = { "id": "q.odd", "sig": "( x )", "doc": "Read the 'RSS' feed\nand return its \"articles\"." }
    answered, unasked, malformed = ask( fake.PairFake( [ odd ] ), [ odd ] )
    assert list( answered ) == [ "q.odd" ] and answered[ "q.odd" ][ "provides" ] > 0.5 and unasked == [] and malformed == []


def test_omitting_a_question_leaves_the_entry_unasked():
    for kind in ( "provides", "coverage" ):
        answered, unasked, malformed = ask( fake.PairFake( [ FEED, MATH ], omit={ kind: { FEED[ "id" ] } } ), [ FEED, MATH ] )
        assert unasked == [ FEED[ "id" ] ] and list( answered ) == [ MATH[ "id" ] ] and malformed == []


def test_a_wrong_answer_makes_the_entry_malformed():
    for kind in ( "provides", "coverage" ):
        answered, unasked, malformed = ask( fake.PairFake( [ FEED, MATH ], wrong={ kind: { FEED[ "id" ] } } ), [ FEED, MATH ] )
        assert [ m[ "id" ] for m in malformed ] == [ FEED[ "id" ] ] and list( answered ) == [ MATH[ "id" ] ] and unasked == []


def test_a_pack_over_the_refusal_size_is_refused_with_a_422():
    body, _ = rpr.pair_request( NEED, [ FEED, MATH ] )
    with pytest.raises( jt.JevConfigError ) as caught:
        fake.PairFake( [ FEED, MATH ], refuse_over=3 ).post_with_meta( body )
    assert caught.value.status == 422
    assert fake.PairFake( [ FEED, MATH ], refuse_over=4 ).post_with_meta( body )[ 0 ][ "answers" ]       # 4 questions fit


def test_a_failing_client_raises_what_it_was_given():
    body, _ = rpr.pair_request( NEED, [ FEED ] )
    with pytest.raises( jt.JevCallError, match="down" ):
        fake.PairFake( [ FEED ], fail=jt.JevCallError( "down" ) ).post_with_meta( body )


def test_every_body_sent_is_recorded_and_usage_and_meta_are_reported():
    client = fake.PairFake( [ FEED ], usage=( 123, 45 ) )
    body, _ = rpr.pair_request( NEED, [ FEED ] )
    response, meta = client.post_with_meta( body )
    assert client.bodies == [ body ] and response[ "model" ] == rt.JEV_MODEL
    assert response[ "usage" ] == { "input_tokens": 123, "output_tokens": 45 }
    assert meta[ "status" ] == 200 and meta[ "attempts" ] == 1


def test_a_body_with_no_usage_reports_none():
    body, _ = rpr.pair_request( NEED, [ FEED ] )
    assert "usage" not in fake.PairFake( [ FEED ], usage=None ).post_with_meta( body )[ 0 ]


def test_the_need_must_be_the_only_thing_in_state():
    body, _ = rpr.pair_request( NEED, [ FEED ] )
    body[ "state" ][ "candidate" ] = "leaked"
    with pytest.raises( AssertionError, match="state" ):
        fake.PairFake( [ FEED ] ).post_with_meta( body )


def test_a_question_the_fake_cannot_place_is_an_error_not_a_quiet_answer():
    body, _ = rpr.pair_request( NEED, [ FEED ] )
    body[ "questions" ][ "p_stranger" ] = { "type": "noul", "instructions": "no candidate here" }
    with pytest.raises( AssertionError, match="holds no candidate" ):
        fake.PairFake( [ FEED ] ).post_with_meta( body )


def test_a_question_for_an_entry_the_fake_was_not_given_is_an_error():
    body, _ = rpr.pair_request( NEED, [ FEED, MATH ] )
    with pytest.raises( AssertionError, match="unknown" ):
        fake.PairFake( [ FEED ] ).post_with_meta( body )


def test_a_need_with_no_usable_words_provides_nothing():
    answered, _, _ = ask( fake.PairFake( [ FEED ] ), [ FEED ], need="a an it" )
    assert answered[ FEED[ "id" ] ][ "provides" ] == 0
