"""
check_exists on the packed path: receipts, page asks, replay and the live spend limit.

Plan 10.3 a to e (as changed by 11.1) and 10.6. The stand-in Jev answers a question by the candidate text
it finds in the question's instructions, and refuses any text it was not given.
"""
import json
import threading

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_page_first import CHOSEN, FEEDS_PAGE, HIT, MATH_PAGE, write_wiki
from tests.unit.test_reuse_tools import ALL_TEXTS, FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT, UNREL

PAGE_TEXTS = ( FEEDS_PAGE, MATH_PAGE )


def probs_of( answer ): return answer[ "answers" ][ "fit" ][ "probabilities" ]


class PackedFake:
    """Answers each question of a packed body by the candidate text in its instructions."""

    def __init__( self, need, answers=None, omit=(), usage=( 100, 20 ) ):
        self.need, self.answers, self.omit, self.usage = need, answers or {}, set( omit ), usage
        self.bodies, self.unexpected, self.lock = [], [], threading.Lock()

    def post_with_meta( self, body ):
        with self.lock: self.bodies.append( body )
        assert body[ "state" ] == { "need": self.need }, "the need must sit in state once and nothing else"
        out = {}
        for key, q in body[ "questions" ].items():
            found = [ t for t in ALL_TEXTS + PAGE_TEXTS if t in q[ "instructions" ] ]
            if len( found ) != 1:
                with self.lock: self.unexpected.append( q )
                raise AssertionError( f"a question names {len( found )} known candidates" )
            if found[ 0 ] not in self.omit: out[ key ] = { "probabilities": probs_of( self.answers.get( found[ 0 ], UNREL ) ) }
        return { "answers": out, "model": body[ "model" ], "usage": { "input_tokens": self.usage[ 0 ], "output_tokens": self.usage[ 1 ] } }, \
               { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 2 }

    def sizes( self ): return [ len( b[ "questions" ] ) for b in self.bodies ]


@pytest.fixture( autouse=True )
def no_jev_key( monkeypatch ):
    """No test here may find a real key: a live call would be spend and a leak."""
    monkeypatch.delenv( jt.KEY_VARIABLE, raising=False )


@pytest.fixture
def env( tmp_path ):
    root = make_lupin_repo( tmp_path )
    return root, tmp_path / "data", tmp_path / "out"


def packed_ctx( env, fake, size=10, **kw ):
    root, data, out = env
    return rt.ReuseContext( root, data, out_dir=out, transport=fake, sweeper=rp.packed_sweeper( size ), request_shape=rp.SHAPE, pack_size=size, **kw )


def receipt_of( env, r ): return json.loads( next( ( env[ 1 ] / "receipts" ).glob( f"{r[ 'receipt_id' ]}*.json" ) ).read_text( encoding="utf-8" ) )


def test_a_full_sweep_goes_out_as_one_packed_request_and_decides_like_the_old_path( env ):
    need = "read an RSS feed [full]"
    fake = PackedFake( need, { FEEDS_TEXT: HIT } )
    r    = rt.check_exists_impl( need, packed_ctx( env, fake ) )
    assert ( r[ "status" ], r[ "verdict" ] ) == ( "ok", "REUSE" ) and fake.unexpected == []
    assert fake.sizes() == [ 3 ] and [ s[ "id" ] for s in r[ "shortlist" ] ] == [ "cosa.feeds.parse_feed" ]
    assert r[ "stats" ][ "requests" ] == 1 and r[ "stats" ][ "attempts" ] == 1 and r[ "stats" ][ "route" ] == "full"


def test_the_packed_receipt_names_its_shape_its_tool_version_its_pack_size_and_its_requests( env ):
    need = "read an RSS feed [receipt]"
    r    = rt.check_exists_impl( need, packed_ctx( env, PackedFake( need ), size=2 ) )
    rec  = receipt_of( env, r )
    assert rec[ "tool_version" ] == "2" and rec[ "request_shape" ] == "packed-choice-1" and rec[ "pack_size" ] == 2
    assert [ q[ "stage" ] for q in rec[ "requests" ] ] == [ "all", "all" ] and [ q[ "size" ] for q in rec[ "requests" ] ] == [ 2, 1 ]
    assert sum( q[ "attempts" ] for q in rec[ "requests" ] ) == rec[ "stats" ][ "attempts" ] == 2


def test_the_old_path_receipt_keeps_version_one_and_has_no_shape( env ):
    from tests.unit.test_reuse_tools import FakeJev
    need = "read an RSS feed [old]"
    r    = rt.check_exists_impl( need, rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=FakeJev( need=need ) ) )
    rec  = receipt_of( env, r )
    assert rec[ "tool_version" ] == "1" and "request_shape" not in rec and "requests" not in rec


def test_one_question_gets_a_different_receipt_id_on_each_path( env ):
    from tests.unit.test_reuse_tools import FakeJev
    need = "read an RSS feed [ids]"
    old  = rt.check_exists_impl( need, rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=FakeJev( need=need ) ) )
    new  = rt.check_exists_impl( need, packed_ctx( env, PackedFake( need ) ) )
    assert old[ "receipt_id" ] != new[ "receipt_id" ]


def test_the_receipt_id_of_an_old_question_is_unchanged():
    """The id is a literal measured before this change, so a hashed-field change shows here."""
    rid = rt.receipt_id( "check_exists", "need", "a" * 40, rt.JEV_MODEL, { "threshold": 0.5 }, "b" * 12, [] )
    assert rid == "53fcc3f891479602"


def test_page_asks_travel_in_one_packed_request_and_so_do_the_covered_entries( env ):
    write_wiki( env[ 0 ] )
    need = "read an RSS feed [pages]"
    fake = PackedFake( need, { FEEDS_PAGE: CHOSEN, FEEDS_TEXT: HIT } )
    r    = rt.check_exists_impl( need, packed_ctx( env, fake ) )
    assert ( r[ "status" ], r[ "verdict" ] ) == ( "ok", "REUSE" ) and fake.unexpected == []
    assert fake.sizes() == [ 2, 1 ]                                                       # both page asks in one request, then the one covered entry
    rec = receipt_of( env, r )
    assert rec[ "route" ] == "pages" and [ q[ "stage" ] for q in rec[ "requests" ] ] == [ "pages", "covered" ]
    assert rec[ "pages" ][ "chosen" ] == [ { "slug": "feeds-page", "p_overlap": 0.8 } ]


def test_the_page_questions_carry_the_page_template_and_the_entry_questions_the_entry_template( env ):
    write_wiki( env[ 0 ] )
    need = "read an RSS feed [templates]"
    fake = PackedFake( need, { FEEDS_PAGE: CHOSEN, FEEDS_TEXT: HIT } )
    rt.check_exists_impl( need, packed_ctx( env, fake ) )
    page_q  = next( iter( fake.bodies[ 0 ][ "questions" ].values() ) )
    entry_q = next( iter( fake.bodies[ 1 ][ "questions" ].values() ) )
    assert page_q[ "criteria" ] == rt.PAGE_TEMPLATE[ "criteria" ] and entry_q[ "criteria" ] == rt.PROMPT_TEMPLATE[ "criteria" ]


def test_replay_frozen_reproduces_a_packed_receipt_from_the_cache_with_no_transport( env ):
    write_wiki( env[ 0 ] )
    need = "read an RSS feed [replay]"
    ctx  = packed_ctx( env, PackedFake( need, { FEEDS_PAGE: CHOSEN, FEEDS_TEXT: HIT } ) )
    r    = rt.check_exists_impl( need, ctx )
    rep  = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert rep[ "status" ] == "ok" and rep[ "frozen" ][ "verdict" ] == r[ "verdict" ] == "REUSE" and rep[ "differences" ][ "frozen" ] == []


def test_a_packed_receipt_with_an_unanswered_entry_replays_to_the_same_uncertain_verdict_after_the_cache_fills( env ):
    need = "read an RSS feed [gap]"
    ctx  = packed_ctx( env, PackedFake( need, omit=[ MATHX_TEXT ] ) )
    r    = rt.check_exists_impl( need, ctx )
    assert r[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and r[ "cause" ] == "CALL_FAILED" and r[ "stats" ][ "failed" ] == 1
    assert receipt_of( env, r )[ "stats" ][ "failed_attempts" ][ 0 ][ "ids" ] == [ "cosa.mathx.add" ]
    rt.check_exists_impl( need, packed_ctx( env, PackedFake( need ) ) )                  # a later run answers the missing entry and fills the cache
    rep = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert rep[ "status" ] == "ok" and rep[ "frozen" ][ "verdict" ] == r[ "verdict" ] and rep[ "differences" ][ "frozen" ] == []


def test_replay_reads_a_failed_attempts_entry_in_the_old_shape_too( env ):
    from tests.unit.test_reuse_tools import FakeJev
    need = "read an RSS feed [old-gap]"
    ctx  = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=FakeJev( need=need ) )
    r    = rt.check_exists_impl( need, ctx )
    path = next( ( env[ 1 ] / "receipts" ).glob( f"{r[ 'receipt_id' ]}*.json" ) )
    rec  = json.loads( path.read_text( encoding="utf-8" ) )
    rec[ "stats" ][ "failed_attempts" ] = [ { "id": "cosa.mathx.add", "attempts": 3 } ]
    path.write_text( json.dumps( rec, sort_keys=True ), encoding="utf-8" )
    rep = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert rep[ "status" ] == "ok"


def test_load_receipt_accepts_versions_one_and_two_and_refuses_a_version_whose_id_does_not_recompute( env ):
    need = "read an RSS feed [versions]"
    ctx  = packed_ctx( env, PackedFake( need ) )
    r    = rt.check_exists_impl( need, ctx )
    assert rt.load_receipt( ctx, r[ "receipt_id" ] )[ "tool_version" ] == "2"
    path = next( ( env[ 1 ] / "receipts" ).glob( f"{r[ 'receipt_id' ]}*.json" ) )
    rec  = json.loads( path.read_text( encoding="utf-8" ) )
    rec[ "tool_version" ] = "1"
    path.write_text( json.dumps( rec, sort_keys=True ), encoding="utf-8" )
    with pytest.raises( rt.ReuseError, match="RECEIPT_ID_MISMATCH" ):
        rt.load_receipt( ctx, r[ "receipt_id" ] )
    rec[ "tool_version" ] = "3"
    path.write_text( json.dumps( rec, sort_keys=True ), encoding="utf-8" )
    with pytest.raises( rt.ReuseError, match="RECEIPT_ID_MISMATCH" ):
        rt.load_receipt( ctx, r[ "receipt_id" ] )


def test_the_environment_switches_the_packed_path_on_with_a_pack_size( monkeypatch, env ):
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( env[ 1 ] ) ); monkeypatch.setenv( "LUPIN_REUSE_OUT_DIR", str( env[ 2 ] ) )
    monkeypatch.delenv( "LUPIN_REUSE_JEV_PACK_SIZE", raising=False )
    assert rt.context_from_environment( env[ 0 ] ).sweeper is None
    monkeypatch.setenv( "LUPIN_REUSE_JEV_PACK_SIZE", "50" )
    monkeypatch.setenv( "LUPIN_REUSE_JEV_TOKEN_CEILING", "71000000" ); monkeypatch.setenv( "LUPIN_REUSE_JEV_RUN_NAME", "stage1-a" )
    ctx = rt.context_from_environment( env[ 0 ] )
    assert ctx.pack_size == 50 and ctx.sweeper is not None and ctx.request_shape == rp.SHAPE and ctx.token_ceiling == 71_000_000 and ctx.run_name == "stage1-a"


@pytest.mark.parametrize( "value", [ "0", "-3", "ten", "1.5", "10001" ] )
def test_a_bad_pack_size_is_refused_not_clamped( monkeypatch, env, value ):
    monkeypatch.setenv( "LUPIN_REUSE_JEV_PACK_SIZE", value )
    with pytest.raises( rt.ReuseError, match="BAD_PACK_SIZE" ):
        rt.context_from_environment( env[ 0 ] )


def test_a_packed_live_run_without_a_token_ceiling_or_a_run_name_is_refused_at_the_start( monkeypatch, env ):
    monkeypatch.setenv( "LUPIN_REUSE_JEV_PACK_SIZE", "50" )
    with pytest.raises( rt.ReuseError, match="BAD_SPEND_LIMIT" ):
        rt.context_from_environment( env[ 0 ] )
    monkeypatch.setenv( "LUPIN_REUSE_JEV_TOKEN_CEILING", "71000000" )
    with pytest.raises( rt.ReuseError, match="BAD_SPEND_LIMIT" ):
        rt.context_from_environment( env[ 0 ] )


@pytest.mark.parametrize( "ceiling", [ "0", "-1", "lots", "1.5" ] )
def test_a_bad_token_ceiling_is_refused( monkeypatch, env, ceiling ):
    monkeypatch.setenv( "LUPIN_REUSE_JEV_PACK_SIZE", "50" ); monkeypatch.setenv( "LUPIN_REUSE_JEV_RUN_NAME", "r" )
    monkeypatch.setenv( "LUPIN_REUSE_JEV_TOKEN_CEILING", ceiling )
    with pytest.raises( rt.ReuseError, match="BAD_SPEND_LIMIT" ):
        rt.context_from_environment( env[ 0 ] )


def test_a_live_packed_run_builds_its_budget_from_the_ceiling_and_the_ledger( monkeypatch, env, tmp_path ):
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    led = rl.AccountLedger.create( tmp_path / "ledger.jsonl", limit_tokens=100_000_000, by="t", why="fixture" )
    ctx = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], sweeper=rp.packed_sweeper( 10 ), request_shape=rp.SHAPE, pack_size=10,
                           token_ceiling=71_000_000, run_name="stage1-a", ledger=led )
    flags, entries, sha_, gen = rt.prepare( ctx )
    assert isinstance( ctx.transport, rt.LiveJevTransport ) and isinstance( ctx.transport.budget, rc.TokenBudget )
    assert ctx.transport.budget.ceiling_tokens == 71_000_000 and led.total() == 71_000_000


def test_a_run_the_account_cannot_afford_is_refused_before_any_http( monkeypatch, env, tmp_path ):
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    posts = []
    monkeypatch.setattr( jt, "_post", lambda *a: posts.append( a ) )
    led = rl.AccountLedger.create( tmp_path / "ledger.jsonl", limit_tokens=50_000_000, by="t", why="fixture" )
    ctx = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], sweeper=rp.packed_sweeper( 10 ), request_shape=rp.SHAPE, pack_size=10,
                           token_ceiling=71_000_000, run_name="stage1-a", ledger=led )
    r = rt.check_exists_impl( "read an RSS feed", ctx )
    assert r[ "status" ] == "error" and r[ "error" ] == "SPEND_LEDGER" and posts == []


def test_a_missing_ledger_refuses_the_run_before_any_http( monkeypatch, env, tmp_path ):
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    ctx = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], sweeper=rp.packed_sweeper( 10 ), request_shape=rp.SHAPE, pack_size=10,
                           token_ceiling=1_000_000, run_name="r", ledger=rl.AccountLedger( tmp_path / "none.jsonl" ) )
    with pytest.raises( rt.ReuseError, match="SPEND_LEDGER" ):
        rt.prepare( ctx )


def test_a_single_use_context_closes_its_run_in_the_ledger_when_the_question_ends( monkeypatch, env, tmp_path ):
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    need = "read an RSS feed [closing]"
    led  = rl.AccountLedger.create( tmp_path / "ledger.jsonl", limit_tokens=100_000_000, by="t", why="fixture" )
    ctx  = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], sweeper=rp.packed_sweeper( 10 ), request_shape=rp.SHAPE, pack_size=10,
                            token_ceiling=71_000_000, run_name="stage1-a", ledger=led, single_use=True )
    monkeypatch.setattr( jt, "_post", lambda url, headers, body, timeout: ( 200, json.dumps( PackedFake( need ).post_with_meta( json.loads( body ) )[ 0 ] ) ) )
    r = rt.check_exists_impl( need, ctx )
    assert r[ "status" ] == "ok" and led.total() == 120      # one request, 100 in and 20 out; the closed run counts at what it spent


def test_a_packed_context_built_by_hand_without_a_ceiling_or_ledger_is_refused_before_any_http( monkeypatch, env ):
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    posts = []
    monkeypatch.setattr( jt, "_post", lambda *a: posts.append( a ) )
    ctx = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], sweeper=rp.packed_sweeper( 10 ), request_shape=rp.SHAPE, pack_size=10 )
    r = rt.check_exists_impl( "read an RSS feed", ctx )
    assert r[ "status" ] == "error" and r[ "error" ] == "BAD_SPEND_LIMIT" and posts == []
