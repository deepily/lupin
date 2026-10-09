"""
Sending one two-question pack: a 422 splits it and every entry is accounted for.

This is unit 5 of the new question. The transport is the PairFake. It answers from the need
and each candidate's text, so a pack that mixes up its entries shows in the values.
Nothing here reaches Jev.
"""
import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_pair_fake as fake
from lupin_mcp import reuse_pair_request as rpr

NEED    = "read an RSS feed and return its articles"
ENTRIES = [ { "id": "cosa.feeds.parse_feed", "sig": "( url )", "doc": "Parse an RSS feed and return its articles." },
            { "id": "cosa.mathx.add", "sig": "( a, b )", "doc": "Add two numbers." },
            { "id": "cosa.feeds.fetch_feed", "sig": "( url )", "doc": "Fetch an RSS feed." },
            { "id": "cosa.text.words", "sig": "( s )", "doc": "Split text into words." },
            { "id": "cosa.feeds.read_articles", "sig": "( feed )", "doc": "Return the articles of a feed." },
            { "id": "cosa.mathx.sub", "sig": "( a, b )", "doc": "Subtract two numbers." },
            { "id": "cosa.feeds.rss_items", "sig": "( xml )", "doc": "Read an RSS feed and return its articles." },
            { "id": "cosa.text.lines", "sig": "( s )", "doc": "Split text into lines." } ]


def send( client, entries=ENTRIES, **kw ): return rp.send_pack( client, NEED, entries, kind="pair", **kw )


def ids( out ): return [ a[ "id" ] for a in out[ "answers" ] ]


def test_a_fully_answered_pair_pack_returns_every_entry_in_order_with_both_answers_and_one_row():
    client = fake.PairFake( ENTRIES )
    out    = send( client, ENTRIES[ :4 ] )
    assert ids( out ) == [ e[ "id" ] for e in ENTRIES[ :4 ] ] and out[ "failed" ] == [] and out[ "not_reached" ] == []
    first = out[ "answers" ][ 0 ]
    assert first[ "provides" ] == pytest.approx( 0.8 ) and first[ "coverage" ] > 0.5 and set( first[ "probabilities" ] ) == { "0", "1", "2", "3" }
    assert out[ "answers" ][ 1 ][ "provides" ] == 0
    row, = out[ "rows" ]
    assert row[ "status" ] == "answered" and row[ "size" ] == 4 and row[ "ids" ] == ids( out ) and row[ "tokens_in" ] == 100 and row[ "malformed" ] == []


def test_the_body_sent_holds_a_noul_and_a_score_for_each_entry_and_the_need_alone_in_state():
    client = fake.PairFake( ENTRIES )
    send( client, ENTRIES[ :3 ] )
    body, = client.bodies
    assert sorted( q[ "type" ] for q in body[ "questions" ].values() ) == [ "noul" ] * 3 + [ "score" ] * 3
    assert body == rpr.pair_request( NEED, ENTRIES[ :3 ] )[ 0 ]


def test_an_entry_with_a_missing_half_is_failed_and_its_pack_mates_are_still_answered():
    out = send( fake.PairFake( ENTRIES, omit={ "coverage": { ENTRIES[ 1 ][ "id" ] } } ), ENTRIES[ :3 ] )
    assert ids( out ) == [ ENTRIES[ 0 ][ "id" ], ENTRIES[ 2 ][ "id" ] ] and out[ "failed" ] == [ ENTRIES[ 1 ][ "id" ] ]
    assert out[ "rows" ][ 0 ][ "unasked" ] == [ ENTRIES[ 1 ][ "id" ] ] and out[ "rows" ][ 0 ][ "status" ] == "answered"


def test_a_wrong_kind_of_answer_fails_the_entry_and_the_valid_half_is_not_used():
    out = send( fake.PairFake( ENTRIES, wrong={ "provides": { ENTRIES[ 0 ][ "id" ] } } ), ENTRIES[ :2 ] )
    assert ids( out ) == [ ENTRIES[ 1 ][ "id" ] ] and out[ "failed" ] == [ ENTRIES[ 0 ][ "id" ] ]
    bad, = out[ "rows" ][ 0 ][ "malformed" ]
    assert bad[ "id" ] == ENTRIES[ 0 ][ "id" ] and any( "not 'noul'" in r for r in bad[ "reasons" ] )
    assert out[ "rows" ][ 0 ][ "unasked" ] == []


def test_a_pack_nothing_of_which_is_answered_is_failed_with_no_answers():
    out = send( fake.PairFake( ENTRIES, omit={ "provides": { e[ "id" ] for e in ENTRIES[ :2 ] } } ), ENTRIES[ :2 ] )
    assert out[ "answers" ] == [] and out[ "failed" ] == [ e[ "id" ] for e in ENTRIES[ :2 ] ]
    assert out[ "rows" ][ 0 ][ "status" ] == "failed" and out[ "rows" ][ 0 ][ "error" ] == "NoAnswers"


def test_a_422_splits_the_pack_until_the_halves_fit_and_every_entry_is_answered_once():
    client = fake.PairFake( ENTRIES, refuse_over=6 )                       # 8 entries are 16 questions; 3 entries fit, 4 do not
    out    = send( client )
    assert sorted( ids( out ) ) == sorted( e[ "id" ] for e in ENTRIES ) and len( ids( out ) ) == 8 and out[ "failed" ] == []
    statuses = [ r[ "status" ] for r in out[ "rows" ] ]
    assert statuses.count( "refused" ) == 3 and statuses.count( "answered" ) == 4 and out[ "rows" ][ 1 ][ "split_from" ] == out[ "rows" ][ 0 ][ "request_hash" ]


def test_a_422_on_one_entry_fails_that_entry_alone():
    out = send( fake.PairFake( ENTRIES, refuse_over=1 ), ENTRIES[ :1 ] )
    assert out[ "answers" ] == [] and out[ "failed" ] == [ ENTRIES[ 0 ][ "id" ] ] and out[ "rows" ][ 0 ][ "status" ] == "refused"


def test_a_transport_error_fails_every_entry_of_the_pack_and_names_the_error():
    out = send( fake.PairFake( ENTRIES, fail=RuntimeError( "boom" ) ), ENTRIES[ :2 ] )
    assert out[ "failed" ] == [ e[ "id" ] for e in ENTRIES[ :2 ] ] and out[ "rows" ][ 0 ][ "error" ] == "RuntimeError"


def test_a_response_from_another_model_fails_the_pack_as_a_mismatch():
    class Other( fake.PairFake ):
        def post_with_meta( self, body ):
            response, meta = super().post_with_meta( body )
            return dict( response, model="jev-other" ), meta
    out = send( Other( ENTRIES ), ENTRIES[ :2 ] )
    assert out[ "answers" ] == [] and out[ "rows" ][ 0 ][ "error" ] == "ModelMismatch"


def test_an_unknown_kind_is_refused_before_anything_is_sent():
    client = fake.PairFake( ENTRIES )
    with pytest.raises( ValueError, match = "kind" ): rp.send_pack( client, NEED, ENTRIES[ :1 ], kind="other" )
    assert client.bodies == []
