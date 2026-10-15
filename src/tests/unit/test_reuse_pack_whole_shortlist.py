"""
Whole-shortlist packing: the packs of the new shape do not move with the cache.

The stand-in transport is the one the send tests use. Eight entries and a pack size of three
give packs of three, three and two when the list is sorted by id.
"""
import json

import pytest

from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_send import ENTRIES, NEED, PROBS, Fake

SHIFTED = { "reuse": 0.1, "extend": 0.1, "unrelated": 0.8 }
BY_ID   = sorted( ENTRIES, key=lambda e: e[ "id" ] )
PACKS   = [ [ e[ "id" ] for e in BY_ID[ i:i + 3 ] ] for i in range( 0, 8, 3 ) ]


class Shifted( Fake ):
    """Answers every question with a shifted mapping, so its answers are recognisable."""

    def post_with_meta( self, body ):
        response, meta = super().post_with_meta( body )
        for answer in response[ "answers" ].values(): answer[ "probabilities" ] = dict( SHIFTED )
        return response, meta


@pytest.fixture
def ctx_for( tmp_path ):
    def make( transport, name="data" ): return rt.ReuseContext( tmp_path, tmp_path / name, out_dir=tmp_path / "out", transport=transport )
    return make


def whole( ctx, entries=ENTRIES, size=3, **kw ): return rp.sweep_packed( ctx, NEED, entries, size, shape=rp.SHAPE_WHOLE, **kw )
def sent_ids( fake ): return sorted( sorted( rp.question_key( i ) for i in pack ) for pack in PACKS )
def bodies_of( fake ): return sorted( json.dumps( b, sort_keys=True ) for b in fake.bodies )


def test_a_cold_sweep_cuts_packs_from_the_whole_list_sorted_by_id( ctx_for ):
    fake = Fake()
    out  = whole( ctx_for( fake ), list( reversed( ENTRIES ) ) )
    assert sorted( sorted( b[ "questions" ] ) for b in fake.bodies ) == sent_ids( fake )
    assert [ a[ "id" ] for a in out[ "answers" ] ] == [ e[ "id" ] for e in reversed( ENTRIES ) ]       # the answers keep the caller's order


def test_a_warm_cache_with_one_miss_in_a_pack_sends_that_pack_whole_with_the_cold_body( ctx_for, tmp_path ):
    cold = Fake()
    whole( ctx_for( cold, "cold" ) )
    ctx  = ctx_for( Fake() )
    whole( ctx, [ e for e in ENTRIES if e[ "id" ] != BY_ID[ 4 ][ "id" ] ] )                 # one entry of the middle pack is missing
    fake = Fake()
    ctx.transport = fake
    out  = whole( ctx )
    assert len( fake.bodies ) == 1 and sorted( fake.bodies[ 0 ][ "questions" ] ) == sorted( rp.question_key( i ) for i in PACKS[ 1 ] )
    middle = [ b for b in cold.bodies if sorted( b[ "questions" ] ) == sorted( rp.question_key( i ) for i in PACKS[ 1 ] ) ]
    assert len( middle ) == 1 and json.dumps( middle[ 0 ], sort_keys=True ) == json.dumps( fake.bodies[ 0 ], sort_keys=True )
    assert out[ "calls" ] == 1 and out[ "cache_hits" ] == 7 and len( out[ "answers" ] ) == 8


def test_the_old_shape_would_have_sent_only_the_missing_entry( ctx_for ):
    ctx = ctx_for( Fake() )
    rp.sweep_packed( ctx, NEED, [ e for e in ENTRIES if e[ "id" ] != BY_ID[ 4 ][ "id" ] ], 3 )
    fake = Fake()
    ctx.transport = fake
    rp.sweep_packed( ctx, NEED, ENTRIES, 3 )
    assert [ len( b[ "questions" ] ) for b in fake.bodies ] == [ 1 ]


def test_a_cached_entry_keeps_its_answer_when_its_pack_is_sent_again( ctx_for ):
    ctx = ctx_for( Fake() )
    whole( ctx, [ e for e in ENTRIES if e[ "id" ] != BY_ID[ 4 ][ "id" ] ] )
    ctx.transport = Shifted()
    out = whole( ctx )
    answers = { a[ "id" ]: a[ "probabilities" ] for a in out[ "answers" ] }
    assert answers[ BY_ID[ 4 ][ "id" ] ] == SHIFTED                                      # the new answer
    assert answers[ BY_ID[ 3 ][ "id" ] ] == PROBS and answers[ BY_ID[ 5 ][ "id" ] ] == PROBS      # the pack mates keep theirs
    assert out[ "calls" ] == 1 and out[ "cache_hits" ] == 7
    assert rt.parse_answer( rt.JevCache( ctx.data ).get( rp.candidate_key( NEED, rt.entry_text( BY_ID[ 3 ] ), shape=rp.SHAPE_WHOLE ) ) ) == PROBS


def test_a_pack_that_failed_does_not_overwrite_a_cached_mate_with_a_failure( ctx_for ):
    ctx = ctx_for( Fake() )
    whole( ctx, [ e for e in ENTRIES if e[ "id" ] != BY_ID[ 4 ][ "id" ] ] )
    ctx.transport = Fake( omit=[ BY_ID[ 4 ][ "id" ], BY_ID[ 3 ][ "id" ] ] )              # the response leaves out the missing entry and a cached one
    out = whole( ctx )
    assert out[ "failed" ] == [ BY_ID[ 4 ][ "id" ] ] and len( out[ "answers" ] ) == 7
    assert BY_ID[ 3 ][ "id" ] in [ a[ "id" ] for a in out[ "answers" ] ]


def test_the_two_shapes_key_their_answers_apart( ctx_for ):
    text = rt.entry_text( ENTRIES[ 0 ] )
    assert rp.candidate_key( NEED, text, shape=rp.SHAPE_WHOLE ) != rp.candidate_key( NEED, text )
    assert rp.candidate_key( NEED, text ) == rp.candidate_key( NEED, text, shape=rp.SHAPE )
    assert rp.stage1_key( NEED, text, 3, 1, shape=rp.SHAPE_WHOLE ) != rp.stage1_key( NEED, text, 3, 1 )
    assert rp.replay_key( NEED, text, 1, shape=rp.SHAPE_WHOLE ) != rp.replay_key( NEED, text, 1 )
    ctx  = ctx_for( Fake() )
    whole( ctx )
    fake = Fake()
    ctx.transport = fake
    rp.sweep_packed( ctx, NEED, ENTRIES, 3 )
    assert sum( len( b[ "questions" ] ) for b in fake.bodies ) == 8                      # the old shape finds none of the new shape's answers


def test_a_frozen_sweep_of_the_new_shape_reads_only_its_cache( ctx_for ):
    ctx = ctx_for( Fake() )
    whole( ctx )
    fake = Fake()
    ctx.transport = fake
    out = whole( ctx, frozen=True )
    assert fake.bodies == [] and out[ "cache_hits" ] == 8 and out[ "calls" ] == 0
    with pytest.raises( rt.ReuseError ) as e:
        rp.sweep_packed( ctx_for( Fake(), "empty" ), NEED, ENTRIES, 3, shape=rp.SHAPE_WHOLE, frozen=True )
    assert e.value.name == "CACHE_MISSING"


def test_an_unknown_shape_and_the_pair_question_on_the_new_shape_are_refused( ctx_for ):
    ctx = ctx_for( Fake() )
    with pytest.raises( ValueError, match="shape must be one of" ):
        rp.sweep_packed( ctx, NEED, ENTRIES, 3, shape="packed-choice-9" )
    with pytest.raises( ValueError, match="choice question" ):
        rp.sweep_packed( ctx, NEED, ENTRIES, 3, shape=rp.SHAPE_WHOLE, kind="pair" )
    with pytest.raises( ValueError, match="shape must be one of" ):
        rp.packed_sweeper( 3, shape="packed-choice-9" )


def test_the_packed_sweeper_of_the_new_shape_cuts_the_same_packs( ctx_for ):
    fake = Fake()
    rp.packed_sweeper( 3, shape=rp.SHAPE_WHOLE )( ctx_for( fake ), NEED, list( reversed( ENTRIES ) ) )
    assert sorted( sorted( b[ "questions" ] ) for b in fake.bodies ) == sent_ids( fake )


def test_a_measurement_arm_of_the_new_shape_has_its_own_keys_and_asks_once( ctx_for ):
    fake = Fake()
    ctx  = ctx_for( fake )
    whole( ctx, key_mode="stage1", run_index=1 )
    n = len( fake.bodies )
    whole( ctx, key_mode="stage1", run_index=1 )
    assert len( fake.bodies ) == n
    assert rt.JevCache( ctx.data ).get( rp.candidate_key( NEED, rt.entry_text( ENTRIES[ 0 ] ), shape=rp.SHAPE_WHOLE ) ) is None


def test_a_cached_entry_the_response_leaves_out_stays_answered_and_is_not_a_gap_for_replay( ctx_for ):
    """Pocholo's probe: the live run keeps the cached answer, so a frozen replay reads it too."""
    ctx = ctx_for( Fake() )
    whole( ctx, [ e for e in ENTRIES if e[ "id" ] != BY_ID[ 4 ][ "id" ] ] )                       # warm: every entry but fn4
    ctx.transport = Fake( omit={ BY_ID[ 3 ][ "id" ] } )                                          # the resent middle pack: fn4 is new, Jev omits the cached fn3
    live = whole( ctx )
    gap_ids = [ i for f in live[ "failed_attempts" ] for i in f[ "ids" ] ]
    assert BY_ID[ 3 ][ "id" ] in [ a[ "id" ] for a in live[ "answers" ] ]
    assert BY_ID[ 3 ][ "id" ] not in gap_ids and BY_ID[ 3 ][ "id" ] not in live[ "unasked" ] and live[ "failed" ] == []
    gaps   = { i: "failed" for i in gap_ids }                                                    # what replay_impl builds from stats.failed_attempts
    frozen = whole( ctx, frozen=True, gaps=gaps )
    assert sorted( a[ "id" ] for a in frozen[ "answers" ] ) == sorted( a[ "id" ] for a in live[ "answers" ] ) and frozen[ "failed" ] == []
