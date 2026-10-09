"""
run_question with the new question: receipt, verdict rule and replay on the packed path.

This is unit 7 of the new question. The transport is the PairFake, which answers from the need
and each candidate's text. Nothing here reaches Jev.
"""
import json

import pytest

from cosa.repo.symindex import verdict as vd
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_pair_fake as fake
from lupin_mcp import reuse_pair_request as rpr
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_route import env, no_jev_key, packed_ctx      # noqa: F401  (fixtures)
from tests.unit.test_reuse_page_first import write_wiki

NEED = "Parse an RSS feed into Article objects."


def entries_of( env ):
    """Ensures: returns the sendable entries of the fixture repository."""
    probe = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake.PairFake( [] ) )
    return rt.prepare( probe )[ 1 ]


def pair_run( env, need=NEED, tool="check_exists", exclude_id=None, **fake_kw ):
    client = fake.PairFake( entries_of( env ), **fake_kw )
    ctx    = packed_ctx( env, client )
    return client, ctx, rt.run_question( ctx, tool, need, need, exclude_id=exclude_id, question="provides" )


def test_a_matching_entry_is_reused_on_the_new_question_and_the_receipt_says_which_question_it_was( env ):
    client, ctx, rec = pair_run( env )
    assert rec[ "verdict" ] == "REUSE" and rec[ "question" ] == "provides" and rec[ "route" ] == "full" and rec[ "pages" ] is None
    assert rec[ "policy" ] == vd.POLICY_PROVIDES and rec[ "request_shape" ] == rpr.SHAPE and rec[ "prompt_template" ] == rpr.PAIR_TEMPLATE
    assert rec[ "tool_version" ] == rt.PACKED_TOOL_VERSION and rec[ "prompt_template_hash" ] == rpr.template_hash()
    assert [ s[ "id" ] for s in rec[ "shortlist" ] ] == [ "cosa.feeds.parse_feed" ]
    assert { "provides", "coverage", "score", "file", "text" } <= set( rec[ "shortlist" ][ 0 ] ) and rec[ "stats" ][ "requests" ] == len( rec[ "requests" ] ) >= 1


def test_the_receipt_id_differs_from_the_three_way_receipt_of_the_same_question_text( env ):
    from tests.unit.test_reuse_pack_route import PackedFake
    _, _, pair = pair_run( env )
    ctx        = packed_ctx( env, PackedFake( NEED ) )
    choice     = rt.run_question( ctx, "check_exists", NEED, NEED )
    assert pair[ "id" ] != choice[ "id" ] and "question" not in choice


def test_the_new_question_asks_no_page_questions_even_when_the_context_has_pages( env ):
    write_wiki( env[ 0 ] )
    client, ctx, rec = pair_run( env )
    assert ctx.pages and rec[ "route" ] == "full" and rec[ "stats" ][ "stages" ][ 0 ][ "stage" ] == "all"
    assert rec[ "page_prompt_template" ] is None
    assert all( q[ "type" ] in ( "noul", "score" ) for b in client.bodies for q in b[ "questions" ].values() )


def test_fetch_similar_leaves_out_the_symbol_it_asked_about( env ):
    _, _, rec = pair_run( env, tool="fetch_similar", exclude_id="cosa.feeds.parse_feed" )
    assert "cosa.feeds.parse_feed" not in [ i for r in rec[ "requests" ] for i in r[ "ids" ] ] and rec[ "stats" ][ "entries" ] == 2


def test_an_entry_with_a_wrong_answer_is_a_gap_so_the_verdict_is_uncertain_and_never_new( env ):
    bad = "cosa.mathx.add"
    _, _, rec = pair_run( env, wrong={ "coverage": { bad } } )
    assert rec[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and "CALL_FAILED" in rec[ "causes" ] and rec[ "stats" ][ "failed" ] == 1
    assert rec[ "stats" ][ "failed_attempts" ][ 0 ][ "ids" ] == [ bad ]


def test_a_question_with_no_entry_to_ask_about_is_uncertain_on_its_pipeline_flag( env, tmp_path ):
    bare = tmp_path / "bare"; bare.mkdir()
    ctx  = rt.ReuseContext( bare, tmp_path / "d2", transport=fake.PairFake( [] ), sweeper=rp.packed_sweeper( 10 ), request_shape=rp.SHAPE, pack_size=10 )
    rec  = rt.run_question( ctx, "check_exists", NEED, NEED, question="provides" )
    assert rec[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and rec[ "cause" ] == "NOT_LUPIN_TREE" and rec[ "route" ] == "none" and rec[ "stats" ][ "calls" ] == 0


def test_the_new_question_needs_the_packed_path_and_sends_nothing_without_it( env ):
    client = fake.PairFake( entries_of( env ) )
    ctx    = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=client )
    with pytest.raises( rt.ReuseError ) as e: rt.run_question( ctx, "check_exists", NEED, NEED, question="provides" )
    assert e.value.name == "PAIR_NEEDS_PACKED" and client.bodies == []


def test_an_unknown_question_is_refused( env ):
    with pytest.raises( rt.ReuseError ) as e: pair_run_unknown( env )
    assert e.value.name == "BAD_QUESTION"


def pair_run_unknown( env ):
    ctx = packed_ctx( env, fake.PairFake( entries_of( env ) ) )
    return rt.run_question( ctx, "check_exists", NEED, NEED, question="other" )


def test_replay_of_a_pair_receipt_reproduces_its_verdict_from_the_cache_and_at_head( env ):
    client, ctx, rec = pair_run( env )
    out = rt.replay_impl( rec[ "id" ], ctx )
    assert out[ "status" ] == "ok" and out[ "frozen" ][ "verdict" ] == "REUSE" and out[ "differences" ] == { "frozen": [], "head": [] }
    assert out[ "head" ][ "verdict" ] == "REUSE" and len( client.bodies ) == 1


def test_replay_of_a_pair_receipt_with_a_gap_does_not_ask_for_the_missing_entry( env ):
    _, ctx, rec = pair_run( env, wrong={ "coverage": { "cosa.mathx.add" } } )
    out = rt.replay_impl( rec[ "id" ], ctx )
    assert out[ "status" ] == "ok" and out[ "frozen" ][ "verdict" ] == "UNCERTAIN_READ_SOURCE" and out[ "differences" ][ "frozen" ] == []


def test_replay_of_a_pair_receipt_whose_cache_is_gone_names_the_missing_entry( env, tmp_path ):
    _, ctx, rec = pair_run( env )
    for p in ( env[ 1 ] / "jev-cache" ).rglob( "*.json" ): p.unlink()
    out = rt.replay_impl( rec[ "id" ], ctx )
    assert out[ "status" ] == "error" and out[ "error" ] == "CACHE_MISSING"


def test_the_receipts_malformed_list_names_every_entry_of_a_pack_in_which_all_are_malformed( env ):
    ids = { e[ "id" ] for e in entries_of( env ) }
    _, _, rec = pair_run( env, wrong={ "provides": ids } )
    assert sorted( m[ "id" ] for m in rec[ "malformed" ] ) == sorted( ids ) and all( m[ "reason" ] for m in rec[ "malformed" ] )
    assert rec[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and rec[ "cause" ] == "CALL_FAILED" and "MALFORMED_ANSWER" not in rec[ "causes" ]


def test_the_receipts_malformed_list_names_an_entry_that_was_malformed_alone_after_a_422_split( env ):
    bad = "cosa.mathx.add"
    _, _, rec = pair_run( env, refuse_over=2, wrong={ "coverage": { bad } } )
    assert [ m[ "id" ] for m in rec[ "malformed" ] ] == [ bad ] and rec[ "stats" ][ "failed" ] == 1 and rec[ "cause" ] == "CALL_FAILED"
    assert any( r[ "status" ] == "refused" for r in rec[ "requests" ] ) and any( r[ "size" ] == 1 and r[ "status" ] == "answered" for r in rec[ "requests" ] )


def test_a_pair_receipt_replays_on_a_context_with_another_pack_size( env ):
    _, _, rec = pair_run( env )
    other     = packed_ctx( env, fake.PairFake( entries_of( env ) ), size=7 )
    out       = rt.replay_impl( rec[ "id" ], other )
    assert out[ "status" ] == "ok" and out[ "frozen" ][ "verdict" ] == rec[ "verdict" ] and out[ "differences" ] == { "frozen": [], "head": [] }


def test_replaying_a_pair_receipt_on_a_context_without_the_packed_path_is_a_named_error_not_a_crash( env ):
    _, _, rec = pair_run( env )
    plain     = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=None )
    out       = rt.replay_impl( rec[ "id" ], plain )
    assert out[ "status" ] == "error" and out[ "error" ] == "PAIR_NEEDS_PACKED"


def test_the_receipt_shows_the_first_reason_of_an_entry_with_two( env ):
    bad = "cosa.mathx.add"
    _, _, rec = pair_run( env, wrong={ "provides": { bad } }, omit={ "coverage": { bad } } )
    one, = rec[ "malformed" ]
    assert one[ "id" ] == bad and one[ "reason" ].startswith( "provides:" ) and "not 'noul'" in one[ "reason" ]
