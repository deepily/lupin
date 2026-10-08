"""
Sweeping a catalogue in packs: chunks, workers, the per-entry cache, receipt counts.

Plan 10.3 a to d and 10.6. The stand-in transport is the one the send tests use.
"""
import threading

import pytest

from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_send import ENTRIES, NEED, PROBS, Fake

OLD_SWEEP_KEYS = { "answers", "failed", "not_reached", "calls", "cache_hits", "attempts_answered", "attempts_failed", "failed_attempts",
                   "tokens_in", "tokens_out", "usage_missing", "transport_calls" }


@pytest.fixture
def ctx_for( tmp_path ):
    def make( transport ): return rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=transport )
    return make


def sweep( ctx, entries=ENTRIES, size=3, **kw ): return rp.sweep_packed( ctx, NEED, entries, size, **kw )


def test_every_entry_is_answered_in_order_in_packs_of_the_given_size( ctx_for ):
    fake = Fake()
    out  = sweep( ctx_for( fake ) )
    assert [ len( b[ "questions" ] ) for b in sorted( fake.bodies, key=lambda b: -len( b[ "questions" ] ) ) ] == [ 3, 3, 2 ]
    assert [ a[ "id" ] for a in out[ "answers" ] ] == [ e[ "id" ] for e in ENTRIES ]
    assert out[ "calls" ] == 8 and out[ "cache_hits" ] == 0 and out[ "requests" ] == 3 and len( out[ "rows" ] ) == 3


def test_the_result_carries_every_key_the_old_sweep_returns( ctx_for ):
    out = sweep( ctx_for( Fake() ) )
    assert OLD_SWEEP_KEYS <= set( out ) and { "rows", "requests", "unasked" } <= set( out )


def test_a_second_sweep_of_the_same_need_is_all_cache_hits_whatever_the_pack_size( ctx_for ):
    fake = Fake()
    ctx  = ctx_for( fake )
    sweep( ctx, size=3 )
    before = len( fake.bodies )
    out    = sweep( ctx, size=5 )
    assert len( fake.bodies ) == before and out[ "cache_hits"] == 8 and out[ "calls" ] == 0 and out[ "requests" ] == 0


def test_a_new_entry_costs_one_request_and_the_old_entries_are_not_asked_again( ctx_for ):
    fake = Fake()
    ctx  = ctx_for( fake )
    sweep( ctx, ENTRIES[ :7 ] )
    fake.bodies.clear()
    out = sweep( ctx, ENTRIES )
    assert len( fake.bodies ) == 1 and list( fake.bodies[ 0 ][ "questions" ] ) == [ rp.question_key( ENTRIES[ 7 ][ "id" ] ) ]
    assert out[ "cache_hits" ] == 7 and out[ "calls" ] == 1 and [ a[ "id" ] for a in out[ "answers" ] ] == [ e[ "id" ] for e in ENTRIES ]


def test_the_cached_answer_of_one_entry_reads_like_the_old_single_answer_and_names_its_pack( ctx_for, tmp_path ):
    ctx = ctx_for( Fake() )
    sweep( ctx, ENTRIES[ :2 ], size=2 )
    cached = rt.JevCache( ctx.data ).get( rp.candidate_key( NEED, rt.entry_text( ENTRIES[ 0 ] ) ) )
    assert rt.parse_answer( cached ) == PROBS
    assert cached[ "pack" ][ "size" ] == 2 and len( cached[ "pack" ][ "request_hash" ] ) == 40


def test_measurement_arms_with_another_run_index_or_pack_size_ask_again_and_the_same_arm_does_not( ctx_for ):
    fake = Fake()
    ctx  = ctx_for( fake )
    sweep( ctx, size=3, key_mode="stage1", run_index=1 )
    n = len( fake.bodies )
    sweep( ctx, size=3, key_mode="stage1", run_index=1 )
    assert len( fake.bodies ) == n
    sweep( ctx, size=3, key_mode="stage1", run_index=2 )
    assert len( fake.bodies ) == 2 * n
    sweep( ctx, size=4, key_mode="stage1", run_index=1 )
    assert len( fake.bodies ) > 2 * n


def test_a_measurement_arm_never_reads_or_writes_the_production_keys( ctx_for ):
    fake = Fake()
    ctx  = ctx_for( fake )
    sweep( ctx, size=3, key_mode="stage1", run_index=1 )
    assert rt.JevCache( ctx.data ).get( rp.candidate_key( NEED, rt.entry_text( ENTRIES[ 0 ] ) ) ) is None
    fake.bodies.clear()
    sweep( ctx, size=3 )
    assert len( fake.bodies ) == 3


def test_a_stage_one_sweep_needs_a_run_index_and_an_unknown_key_mode_is_refused( ctx_for ):
    ctx = ctx_for( Fake() )
    with pytest.raises( ValueError, match="run_index" ):
        sweep( ctx, key_mode="stage1" )
    with pytest.raises( ValueError, match="key_mode" ):
        sweep( ctx, key_mode="nope" )


def test_a_422_on_one_pack_leaves_the_later_packs_running_and_fails_only_the_bad_entry( ctx_for ):
    bad  = ENTRIES[ 1 ][ "id" ]

    class Poisoned( Fake ):
        def post_with_meta( self, body ):
            if rp.question_key( bad ) in body[ "questions" ]:
                self.bodies.append( body )
                raise rp.jt.JevConfigError( "Jev refused the request with status 422", 422 )
            return super().post_with_meta( body )

    out = sweep( ctx_for( Poisoned() ), size=3 )
    assert out[ "failed" ] == [ bad ] and len( out[ "answers" ] ) == 7 and out[ "not_reached" ] == []
    assert out[ "failed_attempts" ] == [ { "request": out[ "failed_attempts" ][ 0 ][ "request" ], "ids": [ bad ], "attempts": 1 } ]


def test_the_counts_of_attempts_and_tokens_add_up_over_the_rows( ctx_for ):
    out = sweep( ctx_for( Fake( usage=( 100, 20 ) ) ) )
    assert out[ "attempts_answered" ] + out[ "attempts_failed" ] == sum( r[ "attempts" ] for r in out[ "rows" ] ) == 3
    assert out[ "tokens_in" ] == 300 and out[ "tokens_out" ] == 60 and out[ "usage_missing" ] == 0
    assert len( out[ "transport_calls" ] ) == 3 and out[ "transport_calls" ][ 0 ][ "model" ] == rt.JEV_MODEL


def test_a_response_without_usage_is_counted_in_usage_missing( ctx_for ):
    out = sweep( ctx_for( Fake( usage=None ) ) )
    assert out[ "usage_missing" ] == 3 and out[ "tokens_in" ] == 0


def test_an_entry_missing_from_an_answered_pack_is_failed_and_recorded_with_its_request( ctx_for ):
    gone = ENTRIES[ 4 ][ "id" ]
    out  = sweep( ctx_for( Fake( omit=[ gone ] ) ) )
    assert out[ "failed" ] == [ gone ] and out[ "unasked" ] == [ gone ]
    assert [ f[ "ids" ] for f in out[ "failed_attempts" ] ] == [ [ gone ] ]


def test_the_ceiling_stops_later_packs_with_no_http_and_counts_them_not_reached( ctx_for ):
    one    = rc.reserve_tokens( rp.pack_request( NEED, ENTRIES[ :3 ] )[ 0 ], 3 )
    budget = rc.TokenBudget( 50, int( one * 1.6 ) )
    fake   = Fake( usage=( 10_000, 10 ), budget=budget )               # the first answer spends far past the ceiling
    out    = sweep( ctx_for( fake ), budget=budget, workers=4 )
    assert len( fake.bodies ) == 1 and out[ "failed" ] == [] and budget.ceiling_refusals == 2
    assert len( out[ "answers" ] ) + len( out[ "not_reached" ] ) == 8 and 0 < len( out[ "not_reached" ] ) < 8


@pytest.mark.parametrize( "workers", [ 3, 9, 0, True, 4.0 ] )
def test_a_worker_count_outside_four_to_eight_is_refused( ctx_for, workers ):
    with pytest.raises( ValueError, match="workers" ):
        sweep( ctx_for( Fake() ), workers=workers )


def test_the_default_worker_count_is_six_and_eight_workers_run_at_once( ctx_for ):
    assert rp.WORKERS_DEFAULT == 6 and ( rp.WORKERS_MIN, rp.WORKERS_MAX ) == ( 4, 8 )
    lock, now, peak, gate = threading.Lock(), [ 0 ], [ 0 ], threading.Barrier( 8, timeout=10 )
    many = [ { "id": f"pkg.mod.big{i}", "sig": "()", "doc": f"Thing {i}.", "file": "src/pkg/mod.py" } for i in range( 16 ) ]

    class Counting( Fake ):
        def post_with_meta( self, body ):
            with lock: now[ 0 ] += 1; peak[ 0 ] = max( peak[ 0 ], now[ 0 ] )
            try: gate.wait()
            finally:
                with lock: now[ 0 ] -= 1
            return {"answers": { k: { "probabilities": dict( PROBS ) } for k in body[ "questions" ] }, "model": body[ "model" ] }, None

    out = sweep( ctx_for( Counting() ), many, size=2, workers=8 )
    assert peak[ 0 ] == 8 and len( out[ "answers" ] ) == 16


def test_frozen_replay_reads_the_same_answers_from_the_cache_with_no_transport( ctx_for ):
    live = sweep( ctx_for( Fake() ) )
    ctx  = ctx_for( None )
    out  = sweep( ctx, frozen=True )
    assert out[ "answers" ] == live[ "answers" ] and out[ "cache_hits" ] == 8 and out[ "requests" ] == 0


def test_frozen_replay_with_an_empty_cache_raises_cache_missing( ctx_for ):
    with pytest.raises( rt.ReuseError, match="CACHE_MISSING" ):
        sweep( ctx_for( None ), frozen=True )


def test_frozen_replay_never_reads_the_cache_for_an_id_in_gaps( ctx_for ):
    sweep( ctx_for( Fake() ) )
    gap = ENTRIES[ 2 ][ "id" ]
    out = sweep( ctx_for( None ), frozen=True, gaps={ gap: "failed" } )
    assert out[ "failed" ] == [ gap ] and len( out[ "answers" ] ) == 7


def test_a_plain_call_budget_instead_of_a_token_budget_still_sweeps( ctx_for ):
    from cosa.repo.doc_lint import jev_transport as jt
    budget = jt.CallBudget( 50 )
    out    = sweep( ctx_for( Fake( budget=budget ) ), budget=budget )
    assert len( out[ "answers" ] ) == 8 and budget.used == 3


def test_a_cache_write_that_fails_keeps_the_answer_and_names_the_entry( ctx_for, monkeypatch ):
    ctx = ctx_for( Fake() )

    def broken( self, key, response ): raise OSError( "disk full" )

    monkeypatch.setattr( rt.JevCache, "put", broken )
    out = sweep( ctx, ENTRIES[ :2 ], size=2 )
    assert len( out[ "answers" ] ) == 2 and out[ "cache_write_failed" ] == [ e[ "id" ] for e in ENTRIES[ :2 ] ]


@pytest.mark.parametrize( "size", [ 0, -1, 1.5, True, None ] )
def test_a_pack_size_that_is_not_a_positive_integer_is_refused( ctx_for, size ):
    with pytest.raises( ValueError, match="size" ):
        sweep( ctx_for( Fake() ), size=size )


def test_a_live_transport_on_a_plain_call_budget_is_refused_before_any_http( ctx_for, monkeypatch ):
    from cosa.repo.doc_lint import jev_transport as jt
    posts = []
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    live = rt.LiveJevTransport( post_fn=lambda *a: posts.append( a ), budget=jt.CallBudget( 50 ) )
    with pytest.raises( rt.ReuseError, match="BAD_SPEND_LIMIT" ):
        sweep( ctx_for( live ) )
    assert posts == []


def test_a_live_transport_on_a_token_budget_is_allowed_and_a_frozen_sweep_needs_no_budget( ctx_for, monkeypatch ):
    from cosa.repo.doc_lint import jev_transport as jt
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    sweep( ctx_for( Fake() ) )                                                                           # fills the cache
    live = rt.LiveJevTransport( post_fn=lambda *a: ( _ for _ in () ).throw( AssertionError( "no HTTP when frozen" ) ), budget=jt.CallBudget( 50 ) )
    assert len( sweep( ctx_for( live ), frozen=True )[ "answers" ] ) == 8
    budget = rc.TokenBudget( 50, 10_000_000 )
    ok     = rt.LiveJevTransport( post_fn=lambda url, headers, body, timeout: ( 200, "{}" ), budget=budget )
    assert sweep( ctx_for( ok ) )[ "cache_hits" ] == 8                                                   # all hits: nothing is posted, nothing is refused
