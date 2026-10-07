"""
The token usage Jev reports for each live answer, summed on the receipt.

Live answered calls add their input and output tokens to `stats`. A cache hit adds nothing.
A failed call has no response to read. An answer with absent or malformed usage adds nothing and is counted apart.
Requests are answered by request-keyed fakes, so no case here can reach Jev.
"""
import json

import pytest

from cosa.repo.doc_lint import jev_transport
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_page_first import CHOSEN, FEEDS_PAGE, HIT, MATH_PAGE, PageFake, run, write_wiki
from tests.unit.test_reuse_tools import FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT, UNREL, FakeJev, N, ctx_for, key_of, literal_body, resp


def U( response, tokens_in, tokens_out ):
    """Ensures: returns the response with a usage mapping of the given counts."""
    return { **response, "usage": { "input_tokens": tokens_in, "output_tokens": tokens_out } }


@pytest.fixture( autouse=True )
def no_jev_key( monkeypatch ):
    """No test here may find a real key: a live call would be spend and a leak."""
    monkeypatch.delenv( jev_transport.KEY_VARIABLE, raising=False )


@pytest.fixture
def env( tmp_path ):
    root = make_lupin_repo( tmp_path )
    return root, tmp_path / "data", tmp_path / "out"


def tokens( stats ): return ( stats[ "tokens_in" ], stats[ "tokens_out" ], stats[ "usage_missing" ] )


@pytest.mark.parametrize( "response, expected", [
    ( { "usage": { "input_tokens": 448, "output_tokens": 42 } }, ( 448, 42 ) ),
    ( { "usage": { "input_tokens": 0, "output_tokens": 0 } }, ( 0, 0 ) ),
    ( { "usage": { "input_tokens": 10 ** 12, "output_tokens": 1 } }, ( 10 ** 12, 1 ) ),
    ( { "usage": { "input_tokens": 448, "output_tokens": 42, "extra": 1 } }, ( 448, 42 ) ),
    ( { "answers": {} }, None ),
    ( { "usage": None }, None ),
    ( { "usage": [ 448, 42 ] }, None ),
    ( { "usage": { "input_tokens": 448 } }, None ),
    ( { "usage": { "output_tokens": 42 } }, None ),
    ( { "usage": { "input_tokens": "448", "output_tokens": 42 } }, None ),
    ( { "usage": { "input_tokens": 448, "output_tokens": 4.5 } }, None ),
    ( { "usage": { "input_tokens": -1, "output_tokens": 42 } }, None ),
    ( { "usage": { "input_tokens": 448, "output_tokens": -1 } }, None ),
    ( { "usage": { "input_tokens": True, "output_tokens": 42 } }, None ),
    ( { "usage": { "input_tokens": 448, "output_tokens": False } }, None ),
    ( None, None ),
    ( "text", None ),
] )
def test_usage_of_reads_two_whole_numbers_and_nothing_else( response, expected ):
    assert rt.usage_of( response ) == expected


def test_live_answers_are_summed_input_and_output_separately( env ):
    need = N( "sum" )
    fake = FakeJev( { FEEDS_TEXT: U( UNREL, 448, 42 ), MATHX_TEXT: U( UNREL, 100, 10 ), SERVE_TEXT: U( UNREL, 7, 3 ) }, need=need )
    r    = rt.check_exists_impl( need, ctx_for( env, fake ) )
    assert r[ "stats" ][ "calls" ] == 3 and tokens( r[ "stats" ] ) == ( 555, 55, 0 )
    assert [ s[ "tokens_in" ] for s in r[ "stats" ][ "stages" ] ] == [ 555 ] and r[ "stats" ][ "stages" ][ 0 ][ "tokens_out" ] == 55


def test_a_cache_hit_counts_as_zero_and_is_not_a_missing_usage( env ):
    need = N( "hits" )
    fake = FakeJev( { FEEDS_TEXT: U( UNREL, 448, 42 ), MATHX_TEXT: U( UNREL, 100, 10 ), SERVE_TEXT: U( UNREL, 7, 3 ) }, need=need )
    ctx  = ctx_for( env, fake )
    first = rt.check_exists_impl( need, ctx )
    again = rt.run_question( ctx, "check_exists", need, need, write=False )                 # the same question, every answer cached
    assert first[ "stats" ][ "calls" ] == 3 and tokens( first[ "stats" ] ) == ( 555, 55, 0 )
    assert ( again[ "stats" ][ "calls" ], again[ "stats" ][ "cache_hits" ] ) == ( 0, 3 ) and tokens( again[ "stats" ] ) == ( 0, 0, 0 )
    assert len( fake.seen ) == 3                                                           # nothing was sent the second time


def test_a_live_answer_without_usable_usage_adds_nothing_and_is_counted( env ):
    need = N( "missing" )
    bad  = { **UNREL, "usage": { "input_tokens": "many", "output_tokens": 5 } }
    fake = FakeJev( { FEEDS_TEXT: U( UNREL, 448, 42 ), MATHX_TEXT: UNREL, SERVE_TEXT: bad }, need=need )
    r    = rt.check_exists_impl( need, ctx_for( env, fake ) )
    assert r[ "stats" ][ "calls" ] == 3 and tokens( r[ "stats" ] ) == ( 448, 42, 2 )


def test_a_failed_call_has_no_response_to_read_and_is_not_a_missing_usage( env ):
    need = N( "failed" )
    fake = FakeJev( { FEEDS_TEXT: U( UNREL, 448, 42 ), MATHX_TEXT: U( UNREL, 100, 10 ) }, need=need )
    fake.table.pop( key_of( literal_body( need, SERVE_TEXT ) ) )                              # the third text is never answered
    r    = rt.check_exists_impl( need, ctx_for( env, fake ) )
    assert r[ "stats" ][ "failed" ] == 1 and r[ "stats" ][ "calls" ] == 2
    assert tokens( r[ "stats" ] ) == ( 548, 52, 0 )


def test_page_first_sums_every_stage_and_a_cached_answer_is_not_counted_twice( env ):
    write_wiki( env[ 0 ] )
    need = "read an RSS feed [stages]"
    pages = { FEEDS_PAGE: U( CHOSEN, 50, 5 ), MATH_PAGE: U( resp( 0.1, 0.1, 0.8 ), 40, 4 ) }
    fake  = PageFake( need, pages, { FEEDS_TEXT: U( resp( 0.45, 0.0, 0.55 ), 300, 30 ), MATHX_TEXT: U( UNREL, 200, 20 ), SERVE_TEXT: U( UNREL, 100, 10 ) } )
    r     = run( env, need, fake )                                                          # the covered stage finds nothing at the threshold: the full sweep follows
    st    = r[ "stats" ]
    assert [ s[ "stage" ] for s in st[ "stages" ] ] == [ "pages", "covered", "all" ]
    assert [ ( s[ "tokens_in" ], s[ "tokens_out" ] ) for s in st[ "stages" ] ] == [ ( 90, 9 ), ( 300, 30 ), ( 300, 30 ) ]       # the full sweep's feeds answer was cached
    assert tokens( st ) == ( 690, 69, 0 )


def test_a_question_that_asks_nothing_reports_zero_tokens( env ):
    r = rt.check_exists_impl( N( "nokey" ), ctx_for( env, None ) )                         # no transport and no key: nothing is asked
    assert r[ "cause" ] == "KEY_UNREADABLE" and tokens( r[ "stats" ] ) == ( 0, 0, 0 )


def test_a_frozen_sweep_reports_zero_tokens( env ):
    need = N( "frozen" )
    fake = FakeJev( { FEEDS_TEXT: U( UNREL, 448, 42 ) }, need=need )
    ctx  = ctx_for( env, fake )
    rt.check_exists_impl( need, ctx )
    entries = [ { "id": "cosa.feeds.parse_feed", "sig": "(url)", "doc": "Parse an RSS feed into Article objects.", "file": "src/cosa/feeds.py", "lang": "py" } ]
    sw = rt.sweep( ctx, need, entries, frozen=True )
    assert ( sw[ "tokens_in" ], sw[ "tokens_out" ], sw[ "usage_missing" ], sw[ "cache_hits" ] ) == ( 0, 0, 0, 1 )


def test_a_receipt_stored_before_the_tally_still_replays( env ):
    need = N( "old" )
    fake = FakeJev( { FEEDS_TEXT: U( resp( 0.95, 0.03, 0.02 ), 448, 42 ) }, need=need )
    ctx  = ctx_for( env, fake )
    r    = rt.check_exists_impl( need, ctx )
    path = env[ 1 ] / "receipts" / f"{r[ 'receipt_id' ]}.json"
    old  = json.loads( path.read_text( encoding="utf-8" ) )
    for key in ( "tokens_in", "tokens_out", "usage_missing" ):
        del old[ "stats" ][ key ]
        for stage in old[ "stats" ][ "stages" ]: stage.pop( key, None )
    path.write_text( rt.canonical( old ) + "\n", encoding="utf-8" )                          # the shape a receipt had before this tally
    back = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert back[ "status" ] == "ok" and back[ "frozen" ][ "verdict" ] == "REUSE" and back[ "differences" ][ "frozen" ] == []
    assert "tokens_in" not in back[ "stored" ][ "stats" ]                                    # replay reads the old shape and adds nothing to it


def test_the_caller_facing_result_carries_the_tokens( env ):
    need = N( "public" )
    r    = rt.check_exists_impl( need, ctx_for( env, FakeJev( { FEEDS_TEXT: U( UNREL, 448, 42 ) }, need=need ) ) )
    assert set( r[ "stats" ] ) >= { "tokens_in", "tokens_out", "usage_missing" }


def test_a_response_whose_cache_write_failed_still_counts_its_tokens_when_the_call_is_retried( env, monkeypatch ):
    need = N( "put-once" )
    fake = FakeJev( { FEEDS_TEXT: U( UNREL, 448, 42 ), MATHX_TEXT: U( UNREL, 100, 10 ), SERVE_TEXT: U( UNREL, 7, 3 ) }, need=need )
    real, failed_once = rt.JevCache.put, []

    def flaky( self, key, response ):
        if not failed_once: failed_once.append( key ); raise OSError( "disk full" )
        return real( self, key, response )

    monkeypatch.setattr( rt.JevCache, "put", flaky )
    r = rt.check_exists_impl( need, ctx_for( env, fake ) )
    assert len( fake.seen ) == 4 and r[ "stats" ][ "calls" ] == 3 and r[ "stats" ][ "failed" ] == 0       # one entry was asked twice
    first = next( t for t in ( FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT ) if key_of( literal_body( need, t ) ) == failed_once[ 0 ] )
    extra = { FEEDS_TEXT: ( 448, 42 ), MATHX_TEXT: ( 100, 10 ), SERVE_TEXT: ( 7, 3 ) }[ first ]
    assert ( r[ "stats" ][ "tokens_in" ], r[ "stats" ][ "tokens_out" ] ) == ( 555 + extra[ 0 ], 55 + extra[ 1 ] )      # the answer lost to the failed write was paid for


def test_responses_that_never_reached_the_cache_count_their_tokens_when_the_entry_fails( env, monkeypatch ):
    need = N( "put-always" )
    fake = FakeJev( { FEEDS_TEXT: U( UNREL, 448, 42 ), MATHX_TEXT: U( UNREL, 100, 10 ), SERVE_TEXT: U( UNREL, 7, 3 ) }, need=need )

    def broken( self, key, response ): raise OSError( "disk full" )

    monkeypatch.setattr( rt.JevCache, "put", broken )
    r = rt.check_exists_impl( need, ctx_for( env, fake ) )
    assert r[ "stats" ][ "failed" ] == 3 and len( fake.seen ) == 3 * ( rt.RETRIES + 1 )
    assert tokens( r[ "stats" ] ) == ( 555 * ( rt.RETRIES + 1 ), 55 * ( rt.RETRIES + 1 ), 0 )              # Jev answered every attempt


def test_missing_usage_in_a_later_stage_is_counted_in_the_total( env ):
    write_wiki( env[ 0 ] )
    need  = "read an RSS feed [late-missing]"
    pages = { FEEDS_PAGE: U( CHOSEN, 50, 5 ), MATH_PAGE: U( resp( 0.1, 0.1, 0.8 ), 40, 4 ) }
    fake  = PageFake( need, pages, { FEEDS_TEXT: U( resp( 0.45, 0.0, 0.55 ), 300, 30 ), MATHX_TEXT: UNREL, SERVE_TEXT: U( UNREL, 100, 10 ) } )
    st    = run( env, need, fake )[ "stats" ]                                                       # the full sweep's math answer has no usage
    assert [ s[ "usage_missing" ] for s in st[ "stages" ] ] == [ 0, 0, 1 ] and st[ "usage_missing" ] == 1
    assert ( st[ "tokens_in" ], st[ "tokens_out" ] ) == ( 490, 49 )
