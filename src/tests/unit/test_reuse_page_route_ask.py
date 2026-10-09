"""
The page-route ask: a need asked through the page route, one symbol left out.

Today's live runs used sweep_need_impl, which turns the page route off.
So the page route has unit tests and no live number.
page_route_need_impl is that same question with the page route left on.
The driver's "pages" question wraps it.
Every answer comes from the request-keyed fake in test_reuse_page_first, so no test makes a live call.
"""
import json

import pytest

from lupin_mcp import reuse_e2e_run as run
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_page_first import (  # noqa: F401  (env and no_jev_key are fixtures)
    CHOSEN, FEEDS_PAGE, HIT, MATH_PAGE, PageFake, env, no_jev_key, receipt_of, write_wiki )
from tests.unit.test_reuse_tools import FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT


def ctx_of( env, fake, **kw ): return rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake, **kw )


def test_the_page_route_ask_leaves_the_page_route_on_and_the_member_out( env ):
    write_wiki( env[ 0 ] )
    need = "read an RSS feed [route-on]"
    fake = PageFake( need, { FEEDS_PAGE: CHOSEN }, { FEEDS_TEXT: HIT } )
    r    = rt.page_route_need_impl( need, "cosa.mathx.add", ctx_of( env, fake ) )
    rec  = receipt_of( env, r )
    assert ( r[ "status" ], r[ "verdict" ] ) == ( "ok", "REUSE" ) and fake.unexpected == []
    assert rec[ "route" ] == "pages" and [ s[ "stage" ] for s in r[ "stats" ][ "stages" ] ] == [ "pages", "covered" ]
    assert rec[ "exclude_id" ] == "cosa.mathx.add" and "sweep_only" not in rec


def test_the_member_is_never_asked_even_when_the_route_falls_back_to_every_entry( env ):
    write_wiki( env[ 0 ] )
    need = "something unrelated [fallback]"
    fake = PageFake( need )
    r    = rt.page_route_need_impl( need, "cosa.mathx.add", ctx_of( env, fake ) )
    assert r[ "verdict" ] == "NEW" and receipt_of( env, r )[ "route" ] == "pages_then_full"
    assert MATHX_TEXT not in fake.seen and sorted( s for s in fake.seen if s in ( FEEDS_TEXT, SERVE_TEXT ) ) == sorted( [ FEEDS_TEXT, SERVE_TEXT ] )


def test_two_members_asked_the_same_need_get_two_receipts( env ):
    write_wiki( env[ 0 ] )
    need = "same words [two-members]"
    a = rt.page_route_need_impl( need, "cosa.mathx.add", ctx_of( env, PageFake( need ) ) )
    b = rt.page_route_need_impl( need, "cosa.feeds.parse_feed", ctx_of( env, PageFake( need ) ) )
    assert a[ "receipt_id" ] != b[ "receipt_id" ]


def test_replay_of_a_page_route_receipt_leaves_the_member_out_and_agrees( env ):
    write_wiki( env[ 0 ] )
    for tag, pages, entries, route in ( ( "hit", { FEEDS_PAGE: CHOSEN }, { FEEDS_TEXT: HIT }, "pages" ), ( "miss", {}, {}, "pages_then_full" ) ):
        need = f"replay the page route [{tag}]"
        ctx  = ctx_of( env, PageFake( need, pages, entries ) )
        r    = rt.page_route_need_impl( need, "cosa.mathx.add", ctx )
        assert receipt_of( env, r )[ "route" ] == route
        rep  = rt.replay_impl( r[ "receipt_id" ], ctx )                                   # the member was never cached: asking for it would be CACHE_MISSING
        assert rep[ "status" ] == "ok" and rep[ "frozen" ][ "verdict" ] == r[ "verdict" ] and rep[ "differences" ][ "frozen" ] == []
        assert rep[ "head" ][ "verdict" ] == r[ "verdict" ]


def test_a_stored_page_route_receipt_with_no_exclusion_replays_as_before( env ):
    write_wiki( env[ 0 ] )
    need = "no exclusion [plain]"
    ctx  = ctx_of( env, PageFake( need ) )
    r    = rt.check_exists_impl( need, ctx )
    assert "exclude_id" not in receipt_of( env, r ) and rt.replay_impl( r[ "receipt_id" ], ctx )[ "differences" ][ "frozen" ] == []


def test_the_ask_refuses_an_empty_need_and_an_unknown_member_before_any_request( env ):
    write_wiki( env[ 0 ] )
    fake = PageFake( "x" )
    assert rt.page_route_need_impl( "  ", None, ctx_of( env, fake ) ) == { "status": "error", "error": "EMPTY_NEED" }
    assert rt.page_route_need_impl( 5, None, ctx_of( env, fake ) ) == { "status": "error", "error": "EMPTY_NEED" }
    r = rt.page_route_need_impl( "a need", "cosa.nowhere.gone", ctx_of( env, fake ) )
    assert r == { "status": "error", "error": "UNKNOWN_ENTRY", "entry": "cosa.nowhere.gone" } and fake.seen == []


def test_the_ask_with_no_member_to_leave_out_asks_every_candidate( env ):
    write_wiki( env[ 0 ] )
    need = "no member [none]"
    fake = PageFake( need )
    r    = rt.page_route_need_impl( need, None, ctx_of( env, fake ) )
    assert r[ "verdict" ] == "NEW" and "exclude_id" not in receipt_of( env, r ) and FEEDS_TEXT in fake.seen and MATHX_TEXT in fake.seen


def test_a_missing_index_returns_the_flag_error_not_an_unknown_entry( env, tmp_path ):
    bare = ( tmp_path / "not-a-repo", tmp_path / "data2", tmp_path / "out2" )
    bare[ 0 ].mkdir()
    r = rt.page_route_need_impl( "a need", "cosa.mathx.add", rt.ReuseContext( bare[ 0 ], bare[ 1 ], out_dir=bare[ 2 ], transport=PageFake( "a need" ) ) )
    assert r[ "status" ] == "ok" and r[ "verdict" ] == "UNCERTAIN" and "NOT_LUPIN_TREE" in r[ "flags" ]


def test_receipt_ids_of_other_questions_do_not_move():
    base = dict( tool="fetch_similar", query="q", index_sha="i", model="m", policy={}, template_hash="t" )
    a = rt.receipt_id( base[ "tool" ], base[ "query" ], base[ "index_sha" ], base[ "model" ], base[ "policy" ], base[ "template_hash" ] )
    b = rt.receipt_id( base[ "tool" ], base[ "query" ], base[ "index_sha" ], base[ "model" ], base[ "policy" ], base[ "template_hash" ], exclude_id="q" )
    assert a == b                                                                         # fetch_similar passes its own id as exclude_id; its id has never carried it
    c = rt.receipt_id( "check_exists", "q", "i", "m", {}, "t" )
    d = rt.receipt_id( "check_exists", "q", "i", "m", {}, "t", exclude_id="x" )
    e = rt.receipt_id( "check_exists", "q", "i", "m", {}, "t", sweep_only=True, exclude_id="x" )
    assert len( { c, d, e } ) == 3


def test_the_driver_asks_the_page_route_for_the_member_and_registers_the_pages_question( env ):
    write_wiki( env[ 0 ] )
    need = "read an RSS feed [driver]"
    fake = PageFake( need, { FEEDS_PAGE: CHOSEN }, { FEEDS_TEXT: HIT } )
    r    = run.ask_pages( ctx_of( env, fake ), { "need": need, "member": "cosa.mathx.add" } )
    assert r[ "verdict" ] == "REUSE" and receipt_of( env, r )[ "exclude_id" ] == "cosa.mathx.add"
    assert run._asks( [ "old", "pages" ] ) == { "old": run.ask_old, "pages": run.ask_pages }
    assert run.QUESTION_NAMES == ( "old", "new" )                                          # the stage-two driver shares this tuple and keeps refusing "pages"
    with pytest.raises( s1.DriverRefused, match="not one of" ): run._asks( [ "bogus" ] )
