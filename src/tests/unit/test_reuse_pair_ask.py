"""
The new question wired into the two drivers, over free text and over given candidates.

The transport is the PairFake. It answers from the need and each candidate's text.
Nothing here reaches Jev.
"""
import json

import pytest

from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_pair_fake as fake
from lupin_mcp import reuse_stage2_run as s2
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_route import env, no_jev_key, packed_ctx, receipt_of      # noqa: F401  (fixtures)
from tests.unit.test_reuse_pair_question import NEED, entries_of


def pair_ctx( env, **kw ): return packed_ctx( env, fake.PairFake( entries_of( env ), **kw ) )


def test_a_free_text_sweep_in_the_new_question_leaves_the_member_out_and_names_the_question( env ):
    ctx = pair_ctx( env )
    out = rt.sweep_need_impl( NEED, "cosa.mathx.add", ctx, question="provides" )
    rec = receipt_of( env, out )
    assert out[ "status" ] == "ok" and rec[ "question" ] == "provides" and rec[ "sweep_only" ] is True and rec[ "exclude_id" ] == "cosa.mathx.add"
    assert "cosa.mathx.add" not in [ i for r in rec[ "requests" ] for i in r[ "ids" ] ] and out[ "verdict" ] == "REUSE"


def test_the_old_free_text_sweep_is_unchanged_by_the_new_argument( env ):
    from tests.unit.test_reuse_pack_route import PackedFake
    out = rt.sweep_need_impl( NEED, "cosa.mathx.add", packed_ctx( env, PackedFake( NEED ) ) )
    assert "question" not in receipt_of( env, out )


def test_pair_ask_returns_each_answer_with_provides_coverage_and_score( env ):
    ctx, entries = pair_ctx( env ), entries_of( env )
    out = rp.pair_ask( ctx, NEED, entries )
    assert sorted( out[ "answered" ] ) == sorted( e[ "id" ] for e in entries ) and out[ "unasked" ] == [] and out[ "malformed" ] == []
    one = out[ "answered" ][ "cosa.feeds.parse_feed" ]
    assert set( one ) == { "provides", "coverage", "score" } and one[ "provides" ] > out[ "answered" ][ "cosa.mathx.add" ][ "provides" ]
    assert one[ "score" ] > out[ "answered" ][ "cosa.mathx.add" ][ "score" ] > 0 and one[ "coverage" ] > out[ "answered" ][ "cosa.mathx.add" ][ "coverage" ]
    assert set( out[ "stats" ] ) == { "failed", "not_checked", "stopped_by", "requests", "attempt_counts" } and out[ "stats" ][ "requests" ] == 1 and out[ "stats" ][ "stopped_by" ] is None


def test_pair_ask_separates_a_malformed_entry_from_an_unasked_one( env ):
    bad, gone = "cosa.mathx.add", "lupin_mcp.tool.serve"
    ctx = pair_ctx( env, wrong={ "coverage": { bad } }, omit={ "provides": { gone } } )
    out = rp.pair_ask( ctx, NEED, entries_of( env ) )
    assert [ m[ "id" ] for m in out[ "malformed" ] ] == [ bad ] and isinstance( out[ "malformed" ][ 0 ][ "reasons" ], list ) and out[ "malformed" ][ 0 ][ "reasons" ]
    assert out[ "unasked" ] == [ gone ] and bad not in out[ "answered" ] and gone not in out[ "answered" ] and out[ "stats" ][ "failed" ] == 2


def test_pair_ask_reports_the_http_attempts_it_made( env ):
    out = rp.pair_ask( pair_ctx( env ), NEED, entries_of( env ) )
    assert out[ "stats" ][ "attempt_counts" ] == rt.attempt_counts( [] ) and set( out[ "stats" ][ "attempt_counts" ] ) >= { "n429", "n529" }


def test_the_end_to_end_driver_asks_the_new_question_through_ask_new( env ):
    assert e2r.NEW_ASK is e2r.ask_new and set( e2r._asks( [ "old", "new" ] ) ) == { "old", "new" }
    out = e2r.ask_new( pair_ctx( env ), { "need": NEED, "member": "cosa.mathx.add" } )
    assert out[ "status" ] == "ok" and out[ "verdict" ] == "REUSE"


def test_ask_new_leaves_the_member_out_of_every_request_and_the_receipt_names_it( env ):
    member = "cosa.feeds.parse_feed"
    client = fake.PairFake( entries_of( env ) )
    out    = e2r.ask_new( packed_ctx( env, client ), { "need": NEED, "member": member } )
    rec    = receipt_of( env, out )
    asked  = [ i for r in rec[ "requests" ] for i in r[ "ids" ] ]
    assert rec[ "exclude_id" ] == member and rec[ "sweep_only" ] is True and member not in asked and len( asked ) == 2
    assert all( member not in q[ "instructions" ] for b in client.bodies for q in b[ "questions" ].values() ) and out[ "verdict" ] != "REUSE"


def test_the_stage_two_driver_turns_a_pair_sweep_into_rows( env ):
    assert s2.NEW_PAIR_ASK is rp.pair_ask
    entries = entries_of( env )
    out     = s2.ask_new_pairs( pair_ctx( env ), { "need": NEED, "entries": entries } )
    rows    = { r[ "candidate" ]: r for r in out[ "rows" ] }
    assert sorted( rows ) == sorted( e[ "id" ] for e in entries ) and rows[ "cosa.feeds.parse_feed" ][ "provides" ] > rows[ "cosa.mathx.add" ][ "provides" ]
    assert out[ "shortlist" ][ 0 ] == { "id": "cosa.feeds.parse_feed" } and all( r[ "unasked" ] is False for r in rows.values() )


def test_pair_ask_reports_why_the_sweep_stopped_when_the_model_named_is_not_the_model_served( env ):
    class Other( fake.PairFake ):
        def post_with_meta( self, body ):
            response, meta = super().post_with_meta( body )
            return dict( response, model="jev-other" ), meta
    entries = entries_of( env )
    out     = rp.pair_ask( packed_ctx( env, Other( entries ) ), NEED, entries )
    assert out[ "stats" ][ "stopped_by" ] == "model_mismatch" and out[ "answered" ] == {} and out[ "stats" ][ "failed" ] == len( entries )
    assert out[ "unasked" ] == [ e[ "id" ] for e in entries ]
