"""
replay_impl with a repeat index: each repeat is a new draw; repeat 0 is the old replay.
"""
import pytest

from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_page_first import CHOSEN, FEEDS_PAGE, HIT, write_wiki
from tests.unit.test_reuse_pack_route import PackedFake, env, no_jev_key, packed_ctx   # noqa: F401  fixtures
from tests.unit.test_reuse_tools import FEEDS_TEXT


def made( env, need ):
    """A packed context whose first question has been asked and answered as a reuse."""
    write_wiki( env[ 0 ] )
    fake = PackedFake( need, { FEEDS_PAGE: CHOSEN, FEEDS_TEXT: HIT } )
    ctx  = packed_ctx( env, fake )
    return fake, ctx, rt.check_exists_impl( need, ctx )


def test_repeat_zero_is_the_old_replay_and_sends_nothing( env ):
    fake, ctx, r = made( env, "read an RSS feed [repeat0]" )
    sent = len( fake.bodies )
    rep  = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert rep[ "head" ][ "verdict" ] == "REUSE" and len( fake.bodies ) == sent
    assert rt.replay_impl( r[ "receipt_id" ], ctx, repeat=0 )[ "head" ] == rep[ "head" ]


def test_a_repeat_is_a_new_draw_that_can_differ_from_the_cached_answer( env ):
    fake, ctx, r = made( env, "read an RSS feed [draw]" )
    sent = len( fake.bodies )
    fake.answers.clear()                                                  # the stand-in now answers every candidate as unrelated
    again = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert again[ "head" ][ "verdict" ] == "REUSE" and len( fake.bodies ) == sent                # repeat 0 still reads the cache
    one   = rt.replay_impl( r[ "receipt_id" ], ctx, repeat=1 )
    assert one[ "head" ][ "verdict" ] == "NEW" and len( fake.bodies ) > sent                     # repeat 1 asked again


def test_the_same_repeat_asked_twice_is_a_cache_hit_and_another_repeat_is_not( env ):
    fake, ctx, r = made( env, "read an RSS feed [keys]" )
    fake.answers.clear()
    rt.replay_impl( r[ "receipt_id" ], ctx, repeat=1 )
    after_one = len( fake.bodies )
    rt.replay_impl( r[ "receipt_id" ], ctx, repeat=1 )
    assert len( fake.bodies ) == after_one
    rt.replay_impl( r[ "receipt_id" ], ctx, repeat=2 )
    assert len( fake.bodies ) > after_one


def test_a_repeat_writes_no_receipt_and_leaves_the_stored_one_unchanged( env ):
    fake, ctx, r = made( env, "read an RSS feed [nowrite]" )
    before = sorted( p.name for p in ( env[ 1 ] / "receipts" ).glob( "*" ) )
    rep    = rt.replay_impl( r[ "receipt_id" ], ctx, repeat=3 )
    assert rep[ "status" ] == "ok" and sorted( p.name for p in ( env[ 1 ] / "receipts" ).glob( "*" ) ) == before


def test_a_repeat_needs_a_packed_context( env ):
    from tests.unit.test_reuse_tools import FakeJev
    need = "read an RSS feed [unpacked]"
    ctx  = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=FakeJev( need=need ) )
    r    = rt.check_exists_impl( need, ctx )
    got  = rt.replay_impl( r[ "receipt_id" ], ctx, repeat=1 )
    assert got[ "status" ] == "error" and got[ "error" ] == "REPEAT_NEEDS_PACKED_CONTEXT"


@pytest.mark.parametrize( "bad", [ -1, 1.5, True, "1", None ] )
def test_a_repeat_must_be_a_whole_number_of_zero_or_more( env, bad ):
    fake, ctx, r = made( env, "read an RSS feed [badrepeat]" )
    got = rt.replay_impl( r[ "receipt_id" ], ctx, repeat=bad )
    assert got[ "status" ] == "error" and got[ "error" ] == "REPEAT_OUT_OF_RANGE"


def test_a_repeat_of_a_pair_receipt_asks_again_under_its_own_pair_key( env ):
    from tests.unit.test_reuse_pair_question import pair_run
    client, ctx, rec = pair_run( env )
    sent = len( client.bodies )
    assert rt.replay_impl( rec[ "id" ], ctx )[ "head" ][ "verdict" ] == "REUSE" and len( client.bodies ) == sent
    one = rt.replay_impl( rec[ "id" ], ctx, repeat=1 )
    assert one[ "status" ] == "ok" and one[ "head" ][ "verdict" ] == "REUSE" and len( client.bodies ) == sent + 1
    rt.replay_impl( rec[ "id" ], ctx, repeat=1 )
    assert len( client.bodies ) == sent + 1
