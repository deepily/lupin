"""
The flip-rate measure: repeats of one need, and how many needs change answer.

The plan asks for at least 30 needs, each asked at least 5 times, and passes at 5% or less.
Two things make a repeat real: its cache key holds the repeat number, and its receipt is not stored.
Without both, repeat two reads repeat one's answer and every flip rate is zero.
All answers come from a stand-in transport, so no test makes a live call.
"""
import json
import threading

import pytest

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_flip as rf
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_route import PAGE_TEXTS, PackedFake, env, no_jev_key, packed_ctx, probs_of  # noqa: F401  (env and no_jev_key are fixtures)
from tests.unit.test_reuse_page_first import HIT, write_wiki
from tests.unit.test_reuse_tools import FEEDS_TEXT, UNREL

NEED = "read an RSS feed [flip]"


class FlippingFake( PackedFake ):
    """Answers the feeds entry as a hit once, then as unrelated on every request after."""

    def __init__( self, need ):
        super().__init__( need, { FEEDS_TEXT: HIT } )
        self.calls = 0

    def post_with_meta( self, body ):
        with self.lock: self.calls += 1
        self.answers = { FEEDS_TEXT: HIT if self.calls == 1 else UNREL }
        return super().post_with_meta( body )


def result_of( verdict, shortlist=() ): return { "status": "ok", "verdict": verdict, "shortlist": [ { "id": i } for i in shortlist ] }


def steady( n_needs=30, repeats=5, verdict="NEW" ):
    return { f"need-{i}": [ result_of( verdict ) for _ in range( repeats ) ] for i in range( n_needs ) }


def test_a_repeat_is_asked_again_and_the_same_repeat_is_not( env ):
    fake = FlippingFake( NEED )
    ctx  = packed_ctx( env, fake )
    first  = rf.ask_repeat( ctx, NEED, "cosa.mathx.add", 1 )
    second = rf.ask_repeat( ctx, NEED, "cosa.mathx.add", 2 )
    again  = rf.ask_repeat( ctx, NEED, "cosa.mathx.add", 1 )
    assert ( first[ "verdict" ], second[ "verdict" ] ) == ( "REUSE", "NEW" )
    assert fake.calls == 2 and again[ "verdict" ] == first[ "verdict" ]                       # repeat 1 again is a cache hit and sends nothing


def test_a_repeat_stores_no_receipt_so_the_next_repeat_cannot_read_it( env ):
    ctx = packed_ctx( env, FlippingFake( NEED ) )
    rf.ask_repeat( ctx, NEED, "cosa.mathx.add", 1 )
    rf.ask_repeat( ctx, NEED, "cosa.mathx.add", 2 )
    assert not ( env[ 1 ] / "receipts" ).exists() or list( ( env[ 1 ] / "receipts" ).glob( "*.json" ) ) == []


def test_the_ordinary_ask_cannot_see_a_flip_which_is_why_repeats_are_keyed_apart( env ):
    fake = FlippingFake( NEED )
    ctx  = packed_ctx( env, fake )
    a, b = ( rt.sweep_need_impl( NEED, "cosa.mathx.add", ctx ) for _ in range( 2 ) )
    assert a[ "receipt_id" ] == b[ "receipt_id" ] and a[ "verdict" ] == b[ "verdict" ] and fake.calls == 1      # the control: one request, one receipt, no flip to find


def test_a_repeat_key_holds_the_repeat_number_and_never_meets_the_production_key():
    keys = { rp.stage1_key( NEED, FEEDS_TEXT, 10, i ) for i in range( 1, 6 ) }
    assert len( keys ) == 5 and rp.candidate_key( NEED, FEEDS_TEXT ) not in keys


def test_the_repeat_sweeper_refuses_a_repeat_number_below_one_before_anything_is_sent():
    for bad in ( 0, -1, None, 1.5, "1", True ):
        with pytest.raises( ValueError, match="run_index" ): rf.repeat_sweeper( 10, rp.WORKERS_DEFAULT, bad )


def test_the_repeat_sweeper_refuses_a_pack_size_or_worker_count_out_of_range():
    with pytest.raises( ValueError, match="size" ): rf.repeat_sweeper( 0, rp.WORKERS_DEFAULT, 1 )
    with pytest.raises( ValueError, match="workers" ): rf.repeat_sweeper( 10, 99, 1 )


def test_ask_repeat_needs_a_packed_context_and_a_known_member( env ):
    fake = PackedFake( NEED )
    plain = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake )
    with pytest.raises( ValueError, match="packed" ): rf.ask_repeat( plain, NEED, "cosa.mathx.add", 1 )
    assert rf.ask_repeat( packed_ctx( env, fake ), NEED, "cosa.nowhere.gone", 1 ) == { "status": "error", "error": "UNKNOWN_ENTRY", "entry": "cosa.nowhere.gone" }
    assert rf.ask_repeat( packed_ctx( env, fake ), "  ", "cosa.mathx.add", 1 ) == { "status": "error", "error": "EMPTY_NEED" } and fake.bodies == []


def test_a_repeat_runs_the_full_sweep_and_never_asks_a_page( env ):
    write_wiki( env[ 0 ] )                                                                   # two pages the page route could ask about
    fake = PackedFake( NEED )
    r    = rf.ask_repeat( packed_ctx( env, fake ), NEED, "cosa.mathx.add", 1 )
    asked = [ q[ "instructions" ] for body in fake.bodies for q in body[ "questions" ].values() ]
    assert r[ "stats" ][ "route" ] == "full" and fake.unexpected == []
    assert asked and not any( page in text for page in PAGE_TEXTS for text in asked )          # page questions may not carry the repeat number, so none may be sent


def test_asking_a_repeat_leaves_the_callers_context_as_it_was( env ):
    ctx    = packed_ctx( env, FlippingFake( NEED ) )
    before = ( ctx.sweeper, ctx.pack_size )
    rf.ask_repeat( ctx, NEED, "cosa.mathx.add", 2 )
    assert ( ctx.sweeper, ctx.pack_size ) == before                                           # the repeat's sweeper lives on a copy only


def test_steady_answers_have_a_zero_flip_rate_with_an_upper_bound_and_pass():
    r = rf.flip_rate( steady() )
    assert ( r[ "needs" ], r[ "flips" ], r[ "rate" ], r[ "flipped" ], r[ "state" ] ) == ( 30, 0, 0.0, [], "pass" )
    assert r[ "interval" ] == e2e.wilson( 0, 30 ) and r[ "upper" ] == r[ "interval" ][ 1 ] and 0.11 < r[ "upper" ] < 0.12


def test_one_need_whose_verdict_differs_on_one_repeat_is_one_flip_of_thirty_and_still_passes():
    runs = steady()
    runs[ "need-7" ][ 3 ] = result_of( "REUSE" )
    r = rf.flip_rate( runs )
    assert ( r[ "flips" ], r[ "flipped" ], r[ "state" ] ) == ( 1, [ "need-7" ], "pass" ) and r[ "rate" ] == pytest.approx( 1 / 30 )
    assert r[ "interval" ] == e2e.wilson( 1, 30 )


def test_two_flips_of_thirty_is_over_five_percent_and_fails():
    runs = steady()
    runs[ "need-1" ][ 0 ], runs[ "need-2" ][ 4 ] = result_of( "REUSE" ), result_of( "EXTEND" )
    r = rf.flip_rate( runs )
    assert ( r[ "flips" ], r[ "flipped" ], r[ "state" ] ) == ( 2, [ "need-1", "need-2" ], "fail" ) and r[ "rate" ] == pytest.approx( 2 / 30 )


def test_a_need_that_changes_and_changes_back_counts_once_not_twice():
    runs = steady()
    runs[ "need-3" ] = [ result_of( "NEW" ), result_of( "REUSE" ), result_of( "NEW" ), result_of( "REUSE" ), result_of( "NEW" ) ]
    assert rf.flip_rate( runs )[ "flips" ] == 1


def test_the_same_verdict_with_a_different_shortlist_is_a_flip_and_a_different_order_is_not():
    runs = { f"n{i}": [ result_of( "REUSE", [ "a", "b" ] ) for _ in range( 5 ) ] for i in range( 30 ) }
    runs[ "n0" ][ 2 ] = result_of( "REUSE", [ "a", "c" ] )
    runs[ "n1" ][ 2 ] = result_of( "REUSE", [ "b", "a" ] )
    r = rf.flip_rate( runs )
    assert r[ "flipped" ] == [ "n0" ] and r[ "flips" ] == 1


def test_the_signature_is_the_verdict_and_the_sorted_shortlist_ids():
    assert rf.signature( result_of( "REUSE", [ "b", "a" ] ) ) == ( "REUSE", ( "a", "b" ) )
    assert rf.signature( result_of( "NEW" ) ) == ( "NEW", () )


def test_fewer_than_thirty_needs_or_five_repeats_is_inconclusive_not_a_pass():
    assert rf.flip_rate( steady( n_needs=29 ) )[ "state" ] == "inconclusive"
    assert rf.flip_rate( steady( repeats=4 ) )[ "state" ] == "inconclusive"
    assert rf.flip_rate( steady( n_needs=29 ) )[ "rate" ] == 0.0
    runs = steady()
    runs[ "need-9" ] = runs[ "need-9" ][ :4 ]
    assert rf.flip_rate( runs )[ "state" ] == "inconclusive" and rf.flip_rate( runs )[ "repeats_min" ] == 4


def test_the_limit_is_five_percent_and_a_bad_input_is_refused():
    assert ( rf.MIN_NEEDS, rf.MIN_REPEATS, rf.PASS_LIMIT ) == ( 30, 5, 0.05 )
    with pytest.raises( ValueError, match="no needs" ): rf.flip_rate( {} )
    with pytest.raises( ValueError, match="at least two" ): rf.flip_rate( { "n": [ result_of( "NEW" ) ] } )
    with pytest.raises( ValueError, match="complete" ): rf.flip_rate( { "n": [ result_of( "NEW" ), { "status": "error", "error": "X" } ] } )


def test_the_report_names_a_flip_exactly_at_the_limit_as_a_pass():
    runs = steady( n_needs=40 )
    runs[ "need-1" ][ 0 ], runs[ "need-2" ][ 0 ] = result_of( "REUSE" ), result_of( "EXTEND" )
    r = rf.flip_rate( runs )
    assert r[ "rate" ] == 0.05 and r[ "state" ] == "pass"
