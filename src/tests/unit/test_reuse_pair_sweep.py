"""
Sweeping a catalogue with two questions a pack: the key, the cache and the size split.

This is unit 6 of the new question. The transport is the PairFake, which answers from the need
and each candidate's text. Nothing here reaches Jev.
"""
import pytest

from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_pair_fake as fake
from lupin_mcp import reuse_pair_request as rpr
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pair_send import ENTRIES, NEED

PAIR_FIELDS = { "id", "provides", "coverage", "score", "confidence", "probabilities" }


@pytest.fixture
def ctx_for( tmp_path ):
    def make( transport ): return rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=transport )
    return make


def sweep( ctx, entries=ENTRIES, size=3, **kw ): return rp.sweep_packed( ctx, NEED, entries, size, kind="pair", **kw )


def test_the_pair_key_holds_the_need_the_text_and_the_model_and_no_pack():
    text = rt.entry_text( ENTRIES[ 0 ] )
    key  = rp.pair_key( NEED, text )
    assert key == rp.pair_key( NEED, text ) and len( key ) == 40
    assert key != rp.pair_key( NEED + " now", text ) and key != rp.pair_key( NEED, text + " x" ) and key != rp.pair_key( NEED, text, model="jev-other" )


def test_the_pair_key_is_not_the_choice_key_for_the_same_need_and_text():
    text = rt.entry_text( ENTRIES[ 0 ] )
    assert rp.pair_key( NEED, text ) != rp.candidate_key( NEED, text )


def test_every_entry_is_answered_in_order_with_both_answers_and_the_old_keys_are_present( ctx_for ):
    out = sweep( ctx_for( fake.PairFake( ENTRIES ) ) )
    assert [ a[ "id" ] for a in out[ "answers" ] ] == [ e[ "id" ] for e in ENTRIES ] and all( set( a ) == PAIR_FIELDS for a in out[ "answers" ] )
    assert out[ "calls" ] == 8 and out[ "cache_hits" ] == 0 and out[ "requests" ] == 3 and out[ "oversize" ] == [] and out[ "malformed" ] == []
    assert { "failed", "not_reached", "attempts_answered", "failed_attempts", "tokens_in", "rows", "unasked" } <= set( out )


def test_a_candidate_answered_in_one_pack_is_a_cache_hit_in_another_pack( ctx_for ):
    client = fake.PairFake( ENTRIES )
    first  = sweep( ctx_for( client ), ENTRIES[ :4 ], size=2 )
    second = sweep( ctx_for( client ), ENTRIES, size=3 )
    assert first[ "calls" ] == 4 and second[ "cache_hits" ] == 4 and second[ "calls" ] == 4
    assert [ a for a in second[ "answers" ] if a[ "id" ] == ENTRIES[ 0 ][ "id" ] ] == [ a for a in first[ "answers" ] if a[ "id" ] == ENTRIES[ 0 ][ "id" ] ]


def test_a_cached_pair_answer_reads_back_whole( ctx_for ):
    client = fake.PairFake( ENTRIES )
    live   = sweep( ctx_for( client ), ENTRIES[ :2 ] )
    cached = sweep( ctx_for( client ), ENTRIES[ :2 ] )
    assert cached[ "calls" ] == 0 and cached[ "cache_hits" ] == 2 and cached[ "answers" ] == live[ "answers" ] and len( client.bodies ) == 1


def test_a_choice_answer_never_serves_the_pair_question( ctx_for ):
    from tests.unit.test_reuse_pack_send import Fake
    choice = Fake()
    rp.sweep_packed( ctx_for( choice ), NEED, ENTRIES, 3 )
    client = fake.PairFake( ENTRIES )
    out    = sweep( ctx_for( client ) )
    assert out[ "cache_hits" ] == 0 and out[ "calls" ] == 8


def test_a_sweep_in_frozen_mode_reads_the_pair_answers_it_cached_and_sends_nothing( ctx_for ):
    live   = sweep( ctx_for( fake.PairFake( ENTRIES ) ) )
    frozen = sweep( ctx_for( None ), frozen=True )
    assert frozen[ "answers" ] == live[ "answers" ] and frozen[ "calls" ] == 0 and frozen[ "cache_hits" ] == 8


def test_a_frozen_sweep_with_an_entry_never_cached_is_refused( ctx_for ):
    sweep( ctx_for( fake.PairFake( ENTRIES ) ), ENTRIES[ :4 ] )
    with pytest.raises( rt.ReuseError ) as e: sweep( ctx_for( None ), ENTRIES, frozen=True )
    assert e.value.name == "CACHE_MISSING"


def test_a_cached_pair_entry_of_the_wrong_shape_is_corrupt( ctx_for ):
    ctx  = ctx_for( fake.PairFake( ENTRIES ) )
    cache = rt.JevCache( ctx.data )
    cache.put( rp.pair_key( NEED, rt.entry_text( ENTRIES[ 0 ] ) ), { "answers": { "fit": { "probabilities": { "reuse": 1 } } } } )
    with pytest.raises( rt.ReuseError ) as e: sweep( ctx, ENTRIES[ :1 ] )
    assert e.value.name == "CACHE_CORRUPT"


def test_a_pack_over_the_size_limit_is_split_before_anything_is_sent( ctx_for ):
    client = fake.PairFake( ENTRIES )
    limit  = rpr.estimate_tokens( rpr.pair_request( NEED, ENTRIES[ :2 ] )[ 0 ] ) + 5
    out    = sweep( ctx_for( client ), ENTRIES[ :6 ], size=6, size_limit=limit )
    assert len( client.bodies ) >= 3 and all( len( b[ "questions" ] ) <= 4 for b in client.bodies ) and out[ "failed" ] == []
    assert [ a[ "id" ] for a in out[ "answers" ] ] == [ e[ "id" ] for e in ENTRIES[ :6 ] ]


def test_an_entry_too_large_to_send_alone_is_failed_and_named_with_no_request_for_it( ctx_for ):
    client = fake.PairFake( ENTRIES )
    big    = dict( ENTRIES[ 1 ], doc="word " * 400 )
    out    = sweep( ctx_for( client ), [ ENTRIES[ 0 ], big ], size=2, size_limit=rpr.estimate_tokens( rpr.pair_request( NEED, [ ENTRIES[ 0 ] ] )[ 0 ] ) + 5 )
    assert out[ "oversize" ] == [ big[ "id" ] ] and out[ "failed" ] == [ big[ "id" ] ] and [ a[ "id" ] for a in out[ "answers" ] ] == [ ENTRIES[ 0 ][ "id" ] ]
    assert len( client.bodies ) == 1


def test_a_malformed_entry_is_failed_listed_and_counted_in_failed_attempts( ctx_for ):
    bad = ENTRIES[ 1 ][ "id" ]
    out = sweep( ctx_for( fake.PairFake( ENTRIES, wrong={ "coverage": { bad } } ) ), ENTRIES[ :3 ], size=3 )
    assert out[ "failed" ] == [ bad ] and [ m[ "id" ] for m in out[ "malformed" ] ] == [ bad ] and len( out[ "answers" ] ) == 2
    assert out[ "failed_attempts" ] == [ { "request": out[ "rows" ][ 0 ][ "request_hash" ], "ids": [ bad ], "attempts": 1 } ]


def test_the_pair_kind_has_no_measurement_key_mode_and_an_unknown_kind_is_refused( ctx_for ):
    ctx = ctx_for( fake.PairFake( ENTRIES ) )
    with pytest.raises( ValueError, match = "key_mode" ): sweep( ctx, key_mode="stage1", run_index=1 )
    with pytest.raises( ValueError, match = "kind" ): rp.sweep_packed( ctx, NEED, ENTRIES, 3, kind="other" )
    with pytest.raises( ValueError, match = "kind" ): rp.packed_sweeper( 3, kind="other" )


def test_the_choice_sweep_reports_no_oversize_and_no_malformed_entries( ctx_for ):
    from tests.unit.test_reuse_pack_send import Fake
    out = rp.sweep_packed( ctx_for( Fake() ), NEED, ENTRIES, 3 )
    assert out[ "oversize" ] == [] and out[ "malformed" ] == []


def test_the_pair_sweeper_made_for_a_context_sweeps_in_the_pair_kind( ctx_for ):
    out = rp.packed_sweeper( 4, kind="pair" )( ctx_for( fake.PairFake( ENTRIES ) ), NEED, ENTRIES )
    assert len( out[ "answers" ] ) == 8 and all( set( a ) == PAIR_FIELDS for a in out[ "answers" ] ) and out[ "requests" ] == 2
