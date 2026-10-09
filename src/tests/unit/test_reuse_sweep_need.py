"""
The free-text full sweep: a need as text, the page route off, one entry left out.

Built on the page-first fixture, so a page ask that wrongly happens shows in what the fake saw.
Nothing here sends a live request.
"""
import pytest

from cosa.repo.doc_lint import jev_transport
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_page_first import FEEDS_PAGE, FEEDS_TEXT, MATH_PAGE, MATHX_TEXT, SERVE_TEXT, PageFake, env, receipt_of, write_wiki   # noqa: F401  (env is a fixture)

MEMBER = "cosa.mathx.add"


@pytest.fixture( autouse=True )
def no_jev_key( monkeypatch ):
    """No test here may find a real key: a live call would be spend and a leak."""
    monkeypatch.delenv( jev_transport.KEY_VARIABLE, raising=False )


def ctx_of( env, fake ): return rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake )


def test_a_free_text_need_sweeps_every_entry_and_asks_no_page( env ):
    write_wiki( env[ 0 ] )
    need = "read an RSS feed [sweep]"
    fake = PageFake( need )
    r    = rt.sweep_need_impl( need, None, ctx_of( env, fake ) )
    rec  = receipt_of( env, r )
    assert r[ "status" ] == "ok" and fake.unexpected == []
    assert sorted( fake.seen ) == sorted( [ FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT ] ) and FEEDS_PAGE not in fake.seen and MATH_PAGE not in fake.seen
    assert rec[ "route" ] == "full" and rec[ "pages" ] is None and rec[ "sweep_only" ] is True and rec[ "tool" ] == "check_exists"


def test_check_exists_still_asks_the_pages_first_on_the_same_wiki( env ):
    write_wiki( env[ 0 ] )
    need = "read an RSS feed [default]"
    fake = PageFake( need )
    r    = rt.check_exists_impl( need, ctx_of( env, fake ) )
    assert FEEDS_PAGE in fake.seen and MATH_PAGE in fake.seen                                    # the guard: the default path did not change
    assert "sweep_only" not in receipt_of( env, r ) and "exclude_id" not in receipt_of( env, r )


def test_the_excluded_entry_is_never_asked_and_the_receipt_names_it( env ):
    write_wiki( env[ 0 ] )
    need = "add two numbers [exclude]"
    fake = PageFake( need )
    r    = rt.sweep_need_impl( need, MEMBER, ctx_of( env, fake ) )
    rec  = receipt_of( env, r )
    assert sorted( fake.seen ) == sorted( [ FEEDS_TEXT, SERVE_TEXT ] ) and MATHX_TEXT not in fake.seen
    assert rec[ "exclude_id" ] == MEMBER and rec[ "stats" ][ "entries" ] == 2


def test_an_excluded_id_that_is_not_in_the_index_is_refused_before_any_request( env ):
    write_wiki( env[ 0 ] )
    fake = PageFake( "x" )
    r    = rt.sweep_need_impl( "add two numbers", "cosa.nowhere.gone", ctx_of( env, fake ) )
    assert r == { "status": "error", "error": "UNKNOWN_ENTRY", "entry": "cosa.nowhere.gone" } and fake.seen == []


def test_an_empty_need_is_refused( env ):
    assert rt.sweep_need_impl( "  ", None, ctx_of( env, PageFake( "x" ) ) ) == { "status": "error", "error": "EMPTY_NEED" }


def test_the_receipt_id_carries_the_flag_the_exclusion_and_the_need( env ):
    write_wiki( env[ 0 ] )
    need = "add two numbers [ids]"
    ctx  = ctx_of( env, PageFake( need ) )
    ids  = { "plain"   : rt.check_exists_impl( need, ctx )[ "receipt_id" ],
             "sweep"   : rt.sweep_need_impl( need, None, ctx )[ "receipt_id" ],
             "member"  : rt.sweep_need_impl( need, MEMBER, ctx )[ "receipt_id" ],
             "again"   : rt.sweep_need_impl( need, MEMBER, ctx )[ "receipt_id" ] }
    assert len( { ids[ "plain" ], ids[ "sweep" ], ids[ "member" ] } ) == 3
    assert ids[ "again" ] == ids[ "member" ]
    other = rt.sweep_need_impl( "add two numbers [ids-2]", MEMBER, ctx_of( env, PageFake( "add two numbers [ids-2]" ) ) )[ "receipt_id" ]
    assert other != ids[ "member" ]


def test_the_cache_key_carries_the_need_so_a_new_need_is_asked_again_and_the_same_need_is_not( env ):
    write_wiki( env[ 0 ] )
    need_a, need_b = "add two numbers [cache-a]", "add two numbers [cache-b]"
    fake = PageFake( need_a )
    fake.table.update( PageFake( need_b ).table )
    rt.sweep_need_impl( need_a, None, ctx_of( env, fake ) )
    assert len( fake.seen ) == 3
    rt.sweep_need_impl( need_a, None, ctx_of( env, fake ) )
    assert len( fake.seen ) == 3                                                                 # the same need: served from the cache
    rt.sweep_need_impl( need_b, None, ctx_of( env, fake ) )
    assert len( fake.seen ) == 6                                                                 # a new need: asked again


def test_a_sweep_need_receipt_replays_frozen_and_at_head_with_the_same_exclusion( env ):
    write_wiki( env[ 0 ] )
    need = "add two numbers [replay]"
    fake = PageFake( need )
    ctx  = ctx_of( env, fake )
    r    = rt.sweep_need_impl( need, MEMBER, ctx )
    rep  = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert rep[ "status" ] == "ok" and rep[ "differences" ] == { "frozen": [], "head": [] } and fake.unexpected == []
    assert MATHX_TEXT not in fake.seen and FEEDS_PAGE not in fake.seen                           # neither re-run asked the member or a page


def test_a_reuse_error_while_sweeping_comes_back_as_an_error_result( env, monkeypatch ):
    def refuse( ctx ): raise rt.ReuseError( "SNAPSHOT_CORRUPT", "scratch" )
    monkeypatch.setattr( rt, "prepare", refuse )
    assert rt.sweep_need_impl( "add two numbers", None, ctx_of( env, PageFake( "x" ) ) ) == { "status": "error", "error": "SNAPSHOT_CORRUPT", "detail": "scratch" }
