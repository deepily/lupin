"""
What the Jev transport saw on each response, jitter and retry-after on the retry wait.

The first group drives jev_transport.send_with_meta with scripted doors, fixed randomness and a fake clock.
The second drives check_exists with the live transport over a scripted door, and reads the receipt.
No case reaches Jev.
"""
import json

import pytest

from cosa.repo.doc_lint import jev_transport
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_page_first import CHOSEN, FEEDS_PAGE, MATH_PAGE, PageFake, write_wiki
from tests.unit.test_reuse_tools import FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT, UNREL, FakeJev, N

ENV  = { jev_transport.KEY_VARIABLE: "k" }
BASE = jev_transport.BACKOFF_SECONDS


def with_usage( response, tokens_in=10, tokens_out=2, model="jev-1.13.0" ):
    """Ensures: returns the response with a usage mapping and a resolved model id."""
    return { **response, "usage": { "input_tokens": tokens_in, "output_tokens": tokens_out }, "model": model }


def door( replies ):
    """Ensures: returns a door that gives the scripted replies in order and repeats the last."""
    queue = list( replies )
    def post( url, headers, body, timeout ): return queue.pop( 0 ) if len( queue ) > 1 else queue[ 0 ]
    return post


def clock( *ticks ):
    """Ensures: returns a clock that reads the given values in order."""
    queue = list( ticks )
    return lambda: queue.pop( 0 )


def send( replies, sleeps, **kw ):
    kw.setdefault( "random_fn", lambda: 0.5 )                                    # jitter factor exactly 1
    return jev_transport.send_with_meta( b"{}", post_fn=door( replies ), sleep_fn=sleeps.append, environ=ENV, **kw )


@pytest.fixture( autouse=True )
def no_jev_key( monkeypatch ):
    """No test here may find a real key: a live call would be spend and a leak."""
    monkeypatch.delenv( jev_transport.KEY_VARIABLE, raising=False )


@pytest.fixture
def env( tmp_path ):
    root = make_lupin_repo( tmp_path )
    return root, tmp_path / "data", tmp_path / "out"


# ---- retry-after parsing --------------------------------------------------------------------

@pytest.mark.parametrize( "headers, expected", [
    ( { "Retry-After": "7" }, 7.0 ), ( { "retry-after": "2.5" }, 2.5 ), ( { "RETRY-AFTER": " 3 " }, 3.0 ), ( { "Retry-After": "0" }, 0.0 ),
    ( { "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT" }, None ), ( { "Retry-After": "soon" }, None ), ( { "Retry-After": "-3" }, None ),
    ( { "Retry-After": "inf" }, None ), ( { "Retry-After": "nan" }, None ), ( { "Retry-After": "" }, None ), ( { "Retry-After": None }, None ),
    ( { "Other": "7" }, None ), ( {}, None ), ( None, None ), ( "Retry-After: 7", None ), ( { 7: "7" }, None ),
] )
def test_retry_after_seconds_reads_a_non_negative_finite_number_and_nothing_else( headers, expected ):
    assert jev_transport.retry_after_seconds( headers ) == expected


# ---- the wait between attempts --------------------------------------------------------------

@pytest.mark.parametrize( "draw, factor", [ ( 0.0, 0.75 ), ( 0.5, 1.0 ), ( 1.0, 1.25 ) ] )
def test_the_backoff_wait_is_scaled_by_a_jitter_factor_between_three_quarters_and_five_quarters( draw, factor ):
    sleeps = []
    send( [ ( 429, "x" ), ( 429, "x" ), ( 429, "x" ), ( 200, "ok" ) ], sleeps, random_fn=lambda: draw )
    assert sleeps == pytest.approx( [ BASE * factor, BASE * 2 * factor, BASE * 4 * factor ] )              # doubling, each scaled


def test_the_default_jitter_is_random_and_stays_inside_its_band():
    waits = []
    for _ in range( 40 ):
        sleeps = []
        send( [ ( 429, "x" ), ( 200, "ok" ) ], sleeps, random_fn=None )                    # None keeps the module's own random
        waits += sleeps
    assert all( BASE * 0.75 <= w <= BASE * 1.25 for w in waits ) and len( set( waits ) ) > 1


def test_a_retry_after_longer_than_the_backoff_sets_the_wait():
    sleeps = []
    send( [ ( 429, "x", { "Retry-After": "10" } ), ( 200, "ok" ) ], sleeps )
    assert sleeps == [ 10.0 ]


def test_a_retry_after_shorter_than_the_backoff_leaves_the_backoff():
    sleeps = []
    send( [ ( 429, "x", { "retry-after": "0.1" } ), ( 200, "ok" ) ], sleeps )
    assert sleeps == [ BASE ]


def test_a_retry_after_is_a_floor_that_jitter_never_goes_under():
    sleeps = []
    send( [ ( 529, "x", { "Retry-After": str( BASE * 1.1 ) } ), ( 200, "ok" ) ], sleeps, random_fn=lambda: 0.0 )       # jittered backoff is 0.75 base
    assert sleeps == [ BASE * 1.1 ]


def test_a_retry_after_beyond_the_cap_waits_the_cap_and_is_still_recorded():
    sleeps = []
    _, meta = send( [ ( 429, "x", { "Retry-After": "500" } ), ( 200, "ok" ) ], sleeps )
    assert sleeps == [ jev_transport.RETRY_AFTER_CAP ] and meta[ "retry_after" ] == 500.0


def test_a_door_that_returns_no_headers_still_works_and_sees_no_retry_after():
    sleeps = []
    text, meta = send( [ ( 429, "x" ), ( 200, "ok" ) ], sleeps )
    assert ( text, meta[ "retry_after" ], meta[ "attempts" ] ) == ( "ok", None, 2 ) and sleeps == [ BASE ]


def test_the_last_failed_attempt_does_not_sleep_and_other_statuses_are_not_retried():
    sleeps = []
    with pytest.raises( jev_transport.JevCallError ):
        send( [ ( 429, "x", { "Retry-After": "1" } ) ], sleeps )
    assert len( sleeps ) == jev_transport.MAX_ATTEMPTS - 1
    for status, error in ( ( 500, jev_transport.JevCallError ), ( 401, jev_transport.JevConfigError ) ):
        sleeps = []
        with pytest.raises( error ): send( [ ( status, "x", { "Retry-After": "9" } ) ], sleeps )
        assert sleeps == []


# ---- what the transport reports -------------------------------------------------------------

def test_a_first_try_success_reports_status_one_attempt_no_retry_after_and_its_latency():
    text, meta = send( [ ( 200, "ok" ) ], [], clock_fn=clock( 5.0, 5.0124 ) )
    assert text == "ok" and meta == { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 12 }


def test_a_retried_success_reports_the_attempts_the_largest_retry_after_and_the_last_attempts_latency():
    ticks = clock( 0.0, 9.0, 20.0, 20.5, 30.0, 30.0021 )                                 # three attempts: 9 s, 0.5 s, then 2.1 ms
    _, meta = send( [ ( 429, "x", { "Retry-After": "3" } ), ( 529, "x", { "Retry-After": "8" } ), ( 200, "ok" ) ], [], clock_fn=ticks )
    assert meta == { "status": 200, "attempts": 3, "retry_after": 8.0, "latency_ms": 2 }


def test_the_largest_retry_after_wins_in_either_order():
    _, meta = send( [ ( 429, "x", { "Retry-After": "8" } ), ( 429, "x", { "Retry-After": "3" } ), ( 200, "ok" ) ], [] )
    assert meta[ "retry_after" ] == 8.0


def test_latency_is_rounded_to_whole_milliseconds():
    assert send( [ ( 200, "ok" ) ], [], clock_fn=clock( 0.0, 0.0004 ) )[ 1 ][ "latency_ms" ] == 0
    assert send( [ ( 200, "ok" ) ], [], clock_fn=clock( 0.0, 0.0016 ) )[ 1 ][ "latency_ms" ] == 2


def test_send_still_returns_the_text_alone_and_the_budget_still_counts_each_attempt():
    budget = jev_transport.CallBudget( 10 )
    text = jev_transport.send( b"{}", post_fn=door( [ ( 429, "x" ), ( 200, "ok" ) ] ), sleep_fn=lambda s: None, environ=ENV, budget=budget, random_fn=lambda: 0.5 )
    assert text == "ok" and budget.used == 2


# ---- the summary ----------------------------------------------------------------------------

def call( ms, model="jev-1.13.0", status=200, attempts=1, retry_after=None ):
    return { "model": model, "status": status, "attempts": attempts, "retry_after": retry_after, "latency_ms": ms }


def test_the_summary_of_no_calls_is_empty_with_no_latency():
    assert rt.transport_summary( [] ) == { "responses": 0, "models": {}, "statuses": {}, "attempts": {}, "attempts_total": 0,
                                           "retry_after_seen": 0, "retry_after_max": None, "latency_ms": None }


def test_the_summary_counts_by_value_in_sorted_order_and_reports_nearest_rank_percentiles():
    calls = [ call( ms ) for ms in range( 1, 21 ) ] + [ call( 100, model="jev-9", status=200, attempts=3, retry_after=4.0 ), call( 200, model=None, attempts=2, retry_after=9.0 ) ]
    s = rt.transport_summary( calls )
    assert s[ "responses" ] == 22 and s[ "models" ] == { "None": 1, "jev-1.13.0": 20, "jev-9": 1 } and s[ "statuses" ] == { "200": 22 }
    assert s[ "attempts" ] == { "1": 20, "2": 1, "3": 1 } and s[ "attempts_total" ] == 25
    assert ( s[ "retry_after_seen" ], s[ "retry_after_max" ] ) == ( 2, 9.0 )
    assert s[ "latency_ms" ] == { "min": 1, "max": 200, "mean": 23, "p50": 11, "p95": 100 }                 # of 22 sorted values: rank 11 and rank 21; the mean is 510 / 22


def test_one_response_fills_every_percentile_with_its_own_latency():
    assert rt.transport_summary( [ call( 7 ) ] )[ "latency_ms" ] == { "min": 7, "max": 7, "mean": 7, "p50": 7, "p95": 7 }


# ---- on the receipt -------------------------------------------------------------------------

def live( fake, env_, **kw ):
    """Ensures: returns a context with a live transport that posts through the fake."""
    def post( url, headers, body, timeout ): return 200, json.dumps( fake.post( json.loads( body ) ) )
    root, data, out = env_
    transport = rt.LiveJevTransport( post_fn=kw.pop( "door", post ), sleep_fn=lambda s: None, environ=ENV, random_fn=lambda: 0.5, clock_fn=kw.pop( "clock_fn", None ) )
    return rt.ReuseContext( root, data, out_dir=out, transport=transport, **kw )


def test_the_receipt_summarises_every_live_response( env ):
    need = N( "receipt" )
    fake = FakeJev( { FEEDS_TEXT: with_usage( UNREL, 448, 42 ), MATHX_TEXT: with_usage( UNREL ), SERVE_TEXT: with_usage( UNREL, model="jev-1.14.0" ) }, need=need )
    t    = iter( range( 0, 1000 ) )
    r    = rt.check_exists_impl( need, live( fake, env, clock_fn=lambda: next( t ) / 1000 ) )               # every attempt reads 1 ms
    tr   = r[ "stats" ][ "transport" ]
    assert tr[ "responses" ] == 3 and tr[ "models" ] == { "jev-1.13.0": 2, "jev-1.14.0": 1 }
    assert tr[ "statuses" ] == { "200": 3 } and tr[ "attempts" ] == { "1": 3 } and tr[ "attempts_total" ] == 3
    assert ( tr[ "retry_after_seen" ], tr[ "retry_after_max" ] ) == ( 0, None ) and tr[ "latency_ms" ][ "p50" ] == 1


def test_a_retry_that_waited_is_visible_on_the_receipt( env ):
    need  = N( "retry" )
    fake  = FakeJev( { t: with_usage( UNREL ) for t in ( FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT ) }, need=need )
    state = { "first": True }
    def post( url, headers, body, timeout ):
        if state.pop( "first", False ): return 429, "slow", { "Retry-After": "4" }
        return 200, json.dumps( fake.post( json.loads( body ) ) )
    tr = rt.check_exists_impl( need, live( fake, env, door=post ) )[ "stats" ][ "transport" ]
    assert tr[ "responses" ] == 3 and tr[ "attempts" ] == { "1": 2, "2": 1 } and tr[ "attempts_total" ] == 4
    assert ( tr[ "retry_after_seen" ], tr[ "retry_after_max" ] ) == ( 1, 4.0 )


def test_a_cache_hit_adds_no_response_and_a_fake_transport_reports_none( env ):
    need = N( "hit" )
    fake = FakeJev( { FEEDS_TEXT: with_usage( UNREL ) }, need=need )
    ctx  = live( fake, env )
    rt.check_exists_impl( need, ctx )
    again = rt.run_question( ctx, "check_exists", need, need, write=False )["stats"]["transport"]
    assert again[ "responses" ] == 0 and again[ "latency_ms" ] is None
    plain = rt.check_exists_impl( N( "plain" ), rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=FakeJev( need=N( "plain" ) ) ) )
    assert plain[ "stats" ][ "transport" ][ "responses" ] == 0                                                   # a fake has no post_with_meta


def test_a_response_with_no_model_is_counted_under_none_and_a_non_object_too( env ):
    need = N( "nomodel" )
    fake = FakeJev( { FEEDS_TEXT: UNREL, MATHX_TEXT: with_usage( UNREL ) }, need=need )
    tr   = rt.check_exists_impl( need, live( fake, env ) )[ "stats" ][ "transport" ]
    assert tr[ "models" ] == { "None": 2, "jev-1.13.0": 1 }
    assert rt.transport_summary( [ call( 1, model=[ "x" ] ) ] )[ "models" ] == { "['x']": 1 }                 # counted by its text, never dropped


def test_page_first_summarises_every_stage( env ):
    write_wiki( env[ 0 ] )
    need = "read an RSS feed [stages-t]"
    fake = PageFake( need, { FEEDS_PAGE: with_usage( CHOSEN ), MATH_PAGE: with_usage( UNREL ) }, { FEEDS_TEXT: with_usage( UNREL ), MATHX_TEXT: with_usage( UNREL ), SERVE_TEXT: with_usage( UNREL ) } )
    def post( url, headers, body, timeout ): return 200, json.dumps( fake.answer( json.loads( body ) ) )
    root, data, out = env
    ctx = rt.ReuseContext( root, data, out_dir=out, transport=rt.LiveJevTransport( post_fn=post, sleep_fn=lambda s: None, environ=ENV, random_fn=lambda: 0.5 ) )
    r   = rt.check_exists_impl( need, ctx )
    assert [ s[ "stage" ] for s in r[ "stats" ][ "stages" ] ] == [ "pages", "covered", "all" ]
    assert r[ "stats" ][ "transport" ][ "responses" ] == 2 + 1 + 2                                          # the full sweep's feeds answer was cached


def test_a_response_lost_to_a_failed_cache_write_is_still_summarised( env, monkeypatch ):
    need = N( "lost" )
    fake = FakeJev( { t: with_usage( UNREL ) for t in ( FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT ) }, need=need )
    real, flaky = rt.JevCache.put, []
    def put( self, key, response ):
        if not flaky: flaky.append( key ); raise OSError( "disk full" )
        return real( self, key, response )
    monkeypatch.setattr( rt.JevCache, "put", put )
    assert rt.check_exists_impl( need, live( fake, env ) )[ "stats" ][ "transport" ][ "responses" ] == 4


def test_a_receipt_stored_before_the_summary_still_replays( env ):
    need = N( "old" )
    fake = FakeJev( { FEEDS_TEXT: with_usage( { "answers": { "fit": { "probabilities": { "reuse": 0.95, "extend": 0.03, "unrelated": 0.02 } } } } ) }, need=need )
    ctx  = live( fake, env )
    r    = rt.check_exists_impl( need, ctx )
    path = env[ 1 ] / "receipts" / f"{r[ 'receipt_id' ]}.json"
    old  = json.loads( path.read_text( encoding="utf-8" ) )
    del old[ "stats" ][ "transport" ]
    path.write_text( rt.canonical( old ) + "\n", encoding="utf-8" )                                       # the shape before this summary
    back = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert back[ "status" ] == "ok" and back[ "frozen" ][ "verdict" ] == "REUSE" and back[ "differences" ][ "frozen" ] == []
    assert "transport" not in back[ "stored" ][ "stats" ]


def test_send_passes_its_randomness_to_the_wait():
    for draw, factor in ( ( 0.0, 0.75 ), ( 1.0, 1.25 ) ):
        sleeps = []
        jev_transport.send( b"{}", post_fn=door( [ ( 429, "x" ), ( 200, "ok" ) ] ), sleep_fn=sleeps.append, environ=ENV, random_fn=lambda draw=draw: draw )
        assert sleeps == [ BASE * factor ]


def test_the_summary_lists_values_in_sorted_order_whatever_order_they_arrived():
    s = rt.transport_summary( [ call( 1, model="jev-9", attempts=3 ), call( 1, model="jev-1", attempts=2 ), call( 1, model="jev-5", attempts=1 ) ] )
    assert list( s[ "models" ] ) == [ "jev-1", "jev-5", "jev-9" ] and list( s[ "attempts" ] ) == [ "1", "2", "3" ]


def test_the_mean_latency_is_rounded_and_not_cut_off():
    assert rt.transport_summary( [ call( 1 ), call( 2 ), call( 2 ) ] )[ "latency_ms" ][ "mean" ] == 2           # 5 / 3 = 1.67
    assert rt.transport_summary( [ call( 1 ), call( 1 ), call( 2 ) ] )[ "latency_ms" ][ "mean" ] == 1           # 4 / 3 = 1.33


@pytest.mark.parametrize( "status", [ 401, 403, 422 ] )
def test_a_refusal_carries_its_http_status_so_a_422_can_be_told_from_a_401( status ):
    with pytest.raises( jev_transport.JevConfigError ) as caught: send( [ ( status, "no" ) ], [] )
    assert caught.value.status == status


def test_a_missing_key_is_a_refusal_with_no_status():
    with pytest.raises( jev_transport.JevConfigError ) as caught:
        jev_transport.send_with_meta( b"{}", post_fn=door( [ ( 200, "ok" ) ] ), environ={} )
    assert caught.value.status is None


def test_a_422_refuses_one_request_and_the_next_post_is_still_sent():
    seen = []
    def post( url, headers, body, timeout ):
        seen.append( body )
        return ( 422, "bad pack" ) if len( seen ) == 1 else ( 200, json.dumps( with_usage( UNREL ) ) )
    t = rt.LiveJevTransport( post_fn=post, sleep_fn=lambda s: None, environ=ENV, random_fn=lambda: 0.5 )
    with pytest.raises( jev_transport.JevConfigError ) as caught: t.post_with_meta( {} )
    assert caught.value.status == 422 and t.refusal is None
    assert t.post_with_meta( {} )[ 0 ][ "model" ] == "jev-1.13.0" and len( seen ) == 2


@pytest.mark.parametrize( "status", [ 401, 403 ] )
def test_a_401_or_a_403_stays_sticky_and_later_posts_raise_without_http( status ):
    seen = []
    def post( url, headers, body, timeout ):
        seen.append( body )
        return status, "no"
    t = rt.LiveJevTransport( post_fn=post, sleep_fn=lambda s: None, environ=ENV, random_fn=lambda: 0.5 )
    for _ in range( 3 ):
        with pytest.raises( jev_transport.JevConfigError ) as caught: t.post_with_meta( {} )
        assert caught.value.status == status
    assert len( seen ) == 1                                                                            # only the first post made HTTP


def test_a_missing_key_stays_sticky_with_no_status():
    t = rt.LiveJevTransport( post_fn=door( [ ( 200, "ok" ) ] ), environ={} )
    for _ in range( 2 ):
        with pytest.raises( jev_transport.JevConfigError ) as caught: t.post_with_meta( {} )
        assert caught.value.status is None
