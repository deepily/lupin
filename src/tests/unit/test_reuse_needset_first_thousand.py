"""
The first-thousand driver on fakes, with no model contacted.
"""
import asyncio
import collections
import json
import pathlib
import types

import pytest

import cosa.utils.util as cu
from lupin_mcp.reuse_needset import call_cap, first_thousand as ft, planted_pool, positive_control as pc, stages
from lupin_mcp.reuse_needset import errors as er
from tests.unit.test_reuse_needset_positive_control import pairs as bare_pairs


def pairs():
    """Return the twenty pairs with a source text on each side, as the real planted file has."""
    return [ { **p, "original": { **p[ "original" ], "text": f"def orig{i}(): pass" }, "rewrite": { **p[ "rewrite" ], "text": f"def rew{i}(): pass" } } for i, p in enumerate( bare_pairs() ) ]


def lab( item, choice="AS_PROPOSED", note="", ts="2026-10-30T00:00:00" ):
    """Return one label row."""
    return { "item_id": item, "choice": choice, "note": note, "reviewer": "x", "symbols": [], "ts": ts }


def key_of( ps ):
    """Return the answer key's items: each pair holds the rewrite as a and the original as b."""
    return { f"pair-{i:02d}": { "a": p[ "rewrite" ][ "id" ], "b": p[ "original" ][ "id" ], "kind": "planted" } for i, p in enumerate( ps ) }


def labelled( ps ):
    """
    Return two label maps.

    Pairs 0 and 1 are drifted, 1 is also unsure, and 2 is unsure by the second reviewer only.
    """
    one, two = {}, {}
    for i in range( len( ps ) ):
        one[ f"pair-{i:02d}" ] = lab( f"pair-{i:02d}", "NONE" if i in ( 0, 1 ) else "AS_PROPOSED", "UNSURE: a" if i == 1 else "" )
        two[ f"pair-{i:02d}" ] = lab( f"pair-{i:02d}", "NONE" if i in ( 0, 1 ) else "AS_PROPOSED", "UNSURE: b" if i == 2 else "" )
    return one, two


def test_the_latest_label_of_an_item_wins_across_files_and_files_are_only_read( tmp_path ):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text( json.dumps( lab( "i1", "NONE", ts="2026-10-27" ) ) + "\n" + json.dumps( lab( "i2", ts="2026-10-27" ) ) + "\n", encoding="utf-8" )
    b.write_text( json.dumps( lab( "i1", "AS_PROPOSED", ts="2026-10-30" ) ) + "\n" + json.dumps( lab( "i2", "NONE", ts="2026-10-01" ) ) + "\n", encoding="utf-8" )
    got = ft.read_latest_labels( [ a, b ] )
    assert got[ "i1" ][ "choice" ] == "AS_PROPOSED" and got[ "i2" ][ "choice" ] == "AS_PROPOSED"
    assert a.read_text( encoding="utf-8" ).count( "\n" ) == 2


def test_the_groups_follow_the_two_reviewers_and_drifted_wins_over_unsure():
    ps        = pairs()
    one, two  = labelled( ps )
    rem       = ft.remainder_pairs( ps, key_of( ps ), one, two )
    groups    = [ r[ "group" ] for r in rem ]
    assert groups[ :4 ] == [ "drifted", "drifted", "unsure", "other" ] and groups.count( "drifted" ) == 2 and groups.count( "unsure" ) == 1
    assert [ r[ "unsure_flagged" ] for r in rem[ :4 ] ] == [ False, True, True, False ]
    assert rem[ 0 ][ "original" ] == ps[ 0 ][ "original" ][ "text" ] and rem[ 0 ][ "rewrite" ] == ps[ 0 ][ "rewrite" ][ "text" ] and rem[ 5 ][ "id" ] == "pair-05"


def test_a_pair_with_no_key_item_or_no_label_is_refused_by_name():
    ps       = pairs()
    one, two = labelled( ps )
    for bad_key, bad_one, bad_two in ( ( { k: v for k, v in key_of( ps ).items() if k != "pair-03" }, one, two ), ( key_of( ps ), { k: v for k, v in one.items() if k != "pair-03" }, two ),
                                      ( key_of( ps ), one, { k: v for k, v in two.items() if k != "pair-03" } ) ):
        with pytest.raises( er.NeedsetError ) as e: ft.remainder_pairs( ps, bad_key, bad_one, bad_two )
        assert e.value.code == er.CONTROL_INPUT_CHANGED


def test_needs_are_drafted_one_pair_at_a_time_in_file_order_through_the_drafter_given():
    order = []

    def draft_fn( job, ask, ledger ):
        order.append( job[ "id" ] )
        return { "ok": True, "need": f"sentence for {job[ 'id' ]}" }

    ps    = pairs()[ :4 ]
    needs = asyncio.run( ft.draft_control_needs( ps, lambda p: { "id": p[ "rewrite" ][ "id" ] }, "ask", "ledger", draft_fn ) )
    assert order == [ p[ "rewrite" ][ "id" ] for p in ps ] and needs == { p[ "rewrite" ][ "id" ]: f"sentence for {p[ 'rewrite' ][ 'id' ]}" for p in ps }


def test_a_need_that_did_not_pass_stops_the_drafting_by_name():
    calls = []

    def draft_fn( job, ask, ledger ):
        calls.append( job[ "id" ] )
        return { "ok": job[ "id" ] != "d-rew01", "need": "n", "reason": "NEED_LEAKS_KEY" }

    with pytest.raises( er.NeedsetError ) as e: asyncio.run( ft.draft_control_needs( pairs()[ :4 ], lambda p: { "id": p[ "rewrite" ][ "id" ] }, None, None, draft_fn ) )
    assert e.value.code == er.CONTROL_NEED_UNDRAFTED and "d-rew01" in e.value.detail and calls == [ "d-rew00", "d-rew01" ]


def test_the_ask_hands_the_checker_the_drafted_need_with_the_original_as_the_seed():
    seen = []
    p    = { **pairs()[ 3 ], "original": { **pairs()[ 3 ][ "original" ], "lang": "ts" } }

    def check( need, planted ):
        seen.append( ( need, planted ) )
        return { "receipt": need[ "need" ] }

    ask = ft.control_ask( { p[ "rewrite" ][ "id" ]: "a sentence" }, check, lambda receipt: [ receipt[ "receipt" ].upper() ] )
    assert asyncio.run( ask( "POOL", p ) ) == [ "A SENTENCE" ] and seen == [ ( { "kind": "work_alike", "write_lang": "ts", "seed": "d-orig03", "need": "a sentence" }, "POOL" ) ]


def fake_ctx():
    """Return a context with a candidate stage of its own."""
    return types.SimpleNamespace( candidate_stage="real stage" )


def test_the_planted_check_adds_the_planted_entries_swaps_the_stage_on_a_copy_and_leaves_the_seed_out():
    ctx     = fake_ctx()
    planted = [ planted_pool.planted_entry( pairs()[ 0 ][ "rewrite" ] ) ]
    got     = {}

    def run_question( c, tool, query, need, **kw ):
        got.update( ctx=c, tool=tool, query=query, need=need, **kw )
        return "receipt"

    base = ( { "F" }, [ { "id": "e1", "sig": "()" } ], "shaX", "gen1" )
    need = { "kind": "work_alike", "write_lang": "py", "seed": "d-orig00", "need": "  a need  " }
    assert ft.planted_check( need, ctx, "PLANTED STAGE", planted, prepare=lambda c: base, run_question=run_question ) == "receipt"
    flags, entries, sha, gen = got[ "prepared" ]
    assert [ e[ "id" ] for e in entries ] == [ "e1", "d-rew00" ] and flags == { "F" } and gen == "gen1" and sha != "shaX" and len( sha ) == 32
    assert got[ "ctx" ].candidate_stage == "PLANTED STAGE" and ctx.candidate_stage == "real stage" and got[ "ctx" ] is not ctx
    assert got[ "tool" ] == "check_exists" and got[ "query" ] == got[ "need" ] == "a need" and got[ "exclude_id" ] == "d-orig00" and got[ "write" ] is False and got[ "language" ] == "py"
    ft.planted_check( { **need, "kind": "cross_language" }, ctx, "S", planted, prepare=lambda c: base, run_question=run_question )
    assert got[ "language" ] == "all"
    ft.planted_check( need, ctx, "S", [ ], prepare=lambda c: base, run_question=run_question )
    assert got[ "prepared" ][ 2 ] != sha


def test_the_remainder_stage_adds_the_count_of_every_unsure_flagged_pair_drifted_ones_included():
    ps       = pairs()
    one, two = labelled( ps )
    rem      = ft.remainder_pairs( ps, key_of( ps ), one, two )
    routes   = { "pair-01": "reject", "pair-02": "person_check", "pair-00": "accept" }

    def run_remainder( given, seed ):
        return { "pairs": len( given ), "seed": seed, "per_pair": [ { "id": r[ "id" ], "group": r[ "group" ], "route": routes[ r[ "id" ] ] if r[ "id" ] in routes else "accept", "reason": "x" } for r in given ] }

    out = asyncio.run( ft.remainder_stage( rem, 7, run_remainder=run_remainder )() )
    assert out[ "unsure_flagged" ] == { "total": 2, "resolved": 1 } and out[ "seed" ] == 7 and out[ "pairs" ] == 20


def test_a_full_run_charges_nothing_for_fakes_writes_the_report_and_a_resumed_cap_keeps_its_count( tmp_path ):
    def stage_returning( name, stop=False ):
        async def stage(): return { "name": name, "stop": stop }
        return stage

    rep = asyncio.run( ft.run_first_thousand( str( tmp_path ), stage_returning( "a" ), stage_returning( "b" ), stage_returning( "c" ), stage_returning( "d" ) ) )
    assert [ rep[ "stages" ][ n ][ "status" ] for n in stages.ORDER ] == [ "done" ] * 4 and rep[ "used" ] == 0 and rep[ "limit" ] == 1000
    assert json.loads( ( tmp_path / ft.REPORT_FILE ).read_text( encoding="utf-8" ) ) == rep
    cap = call_cap.CallCap( str( tmp_path / ft.CALLS_FILE ), 3 )
    for _ in range( 2 ): cap.charge( "m" )
    stopped = asyncio.run( ft.run_first_thousand( str( tmp_path ), stage_returning( "a", stop=True ), stage_returning( "b" ), stage_returning( "c" ), stage_returning( "d" ), limit=3 ) )
    assert stopped[ "used" ] == 2 and stopped[ "limit" ] == 3 and stopped[ "stages" ][ "yield" ] == { "status": "not_run" }


REAL_RUN = pathlib.Path( cu.get_project_root() + "/io/semdup-labelling/2026.10.25-run5" )


@pytest.mark.skipif( not REAL_RUN.exists(), reason="io/ is not tracked, so a worktree has no copy of the proof's evidence" )
def test_the_real_labels_give_three_drifted_and_twelve_unsure_pairs_of_twenty():
    real = pc.load_pairs( REAL_RUN / "key" / "planted.json" )
    key  = json.loads( ( REAL_RUN / "key" / "answer-key.json" ).read_text( encoding="utf-8" ) )[ "items" ]
    one  = ft.read_latest_labels( [ REAL_RUN / "packets" / "labels-rick.jsonl", REAL_RUN / "packets" / "labels-rick-redo.jsonl" ] )
    two  = ft.read_latest_labels( [ REAL_RUN / "packets" / "labels-reviewer-2.jsonl" ] )
    got  = collections.Counter( r[ "group" ] for r in ft.remainder_pairs( real, key, one, two ) )
    assert got == { "drifted": 3, "unsure": 10, "other": 7 }
    assert sum( 1 for r in ft.remainder_pairs( real, key, one, two ) if r[ "unsure_flagged" ] ) == 12
