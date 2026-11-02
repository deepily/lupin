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
from cosa.repo.symindex.candidates import candidate_stage as cs
from lupin_mcp.reuse_needset import call_cap, draft, first_thousand as ft, smoke, planted_pool, planted_purposes, positive_control as pc, stage_parts, stage_seeds, stages
from lupin_mcp.reuse_needset import control_report
from lupin_mcp.reuse_needset import errors as er
from tests.unit.test_reuse_needset_positive_control import pairs as bare_pairs, pool


class LiveStage( str ):
    """A stand-in for the live candidate stage: a string that also names its purpose store."""
    purposes_path = None


class PlantedStage( str ):
    """A stand-in for the planted stage that holds the whole lists of its last search."""
    last_answer = { "lists": { "code": [ "d-orig00" ], "prose": [ "d-orig00" ], "vector_concat": [ "d-rew00", "d-orig00" ] } }


PLANTED = PlantedStage( "planted stage" )


def live_pool():
    """Return the pool as the real index has it, with the originals under dotted ids."""
    return [ { **r, "id": f"idx.{r[ 'id' ]}" } for r in pool() ]


def live_ctx():
    """Return a context whose candidate stage is the live stand-in."""
    return types.SimpleNamespace( candidate_stage=LiveStage( "live stage" ) )


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
    Pair 3 has none from the first reviewer alone, pair 4 from the second alone, and pair 5 mentions unsure mid-note.
    """
    one, two = {}, {}
    for i in range( len( ps ) ):
        one[ f"pair-{i:02d}" ] = lab( f"pair-{i:02d}", "NONE" if i in ( 0, 1, 3 ) else "AS_PROPOSED", "UNSURE: a" if i == 1 else ( "not UNSURE here" if i == 5 else "" ) )
        two[ f"pair-{i:02d}" ] = lab( f"pair-{i:02d}", "NONE" if i in ( 0, 1, 4 ) else "AS_PROPOSED", "UNSURE: b" if i == 2 else "" )
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
    assert [ r[ "unsure_flagged" ] for r in rem[ :6 ] ] == [ False, True, True, False, False, False ]
    assert [ r[ "group" ] for r in rem[ 3:6 ] ] == [ "other", "other", "other" ]      # one reviewer's none is not drift; a note that merely mentions unsure is not a flag
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

    def draft_fn( job, ask, ledger, **kw ):
        order.append( job[ "id" ] )
        return { "ok": True, "need": f"sentence for {job[ 'id' ]}" }

    ps    = pairs()[ :4 ]
    needs = asyncio.run( ft.draft_control_needs( ps, lambda p: { "id": p[ "rewrite" ][ "id" ] }, "ask", "ledger", draft_fn ) )
    assert order == [ p[ "rewrite" ][ "id" ] for p in ps ] and needs == { p[ "rewrite" ][ "id" ]: f"sentence for {p[ 'rewrite' ][ 'id' ]}" for p in ps }


def test_a_need_that_did_not_pass_stops_the_drafting_by_name():
    calls = []

    def draft_fn( job, ask, ledger, **kw ):
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


def test_the_planted_check_gives_a_plant_its_line_as_attach_purposes_gives_a_real_entry_and_leaves_the_rest_alone():
    from cosa.repo.symindex import build as sx_build
    from lupin_mcp import reuse_tools as rt
    first, second = ( planted_pool.planted_entry( p[ "rewrite" ] ) for p in pairs()[ :2 ] )
    got  = {}
    base = ( set(), [ ], "shaX", "gen1" )
    need = { "kind": "work_alike", "write_lang": "py", "seed": "d-orig00", "need": "a need" }
    run  = lambda c, tool, query, need, **kw: got.update( kw ) or "receipt"
    ft.planted_check( need, fake_ctx(), "S", [ first, second ], prepare=lambda c: base, run_question=run, purposes={ first[ "pin" ]: "Does the first one's work." } )
    shown = { e[ "id" ]: e for e in got[ "prepared" ][ 1 ] }
    assert shown[ first[ "id" ] ][ "purpose" ] == "Does the first one's work." and "purpose" not in shown[ second[ "id" ] ]
    assert rt.entry_text( shown[ first[ "id" ] ] ).endswith( "| purpose: Does the first one's work." ) and shown[ first[ "id" ] ] == sx_build.attach_purposes( [ first ], { first[ "pin" ] : "Does the first one's work." } )[ 0 ]
    ft.planted_check( need, fake_ctx(), "S", [ first ], prepare=lambda c: base, run_question=run )
    assert "purpose" not in got[ "prepared" ][ 1 ][ 0 ]


def test_the_remainder_stage_adds_the_count_of_every_unsure_flagged_pair_drifted_ones_included():
    ps       = pairs()
    one, two = labelled( ps )
    rem      = ft.remainder_pairs( ps, key_of( ps ), one, two )
    routes   = { "pair-01": "reject", "pair-02": "person_check", "pair-00": "accept" }

    def run_remainder( given, seed ):
        return { "pairs": len( given ), "seed": seed, "per_pair": [ { "id": r[ "id" ], "group": r[ "group" ], "route": routes[ r[ "id" ] ] if r[ "id" ] in routes else "accept", "reason": "x" } for r in given ] }

    out = asyncio.run( ft.remainder_stage( rem, 7, run_remainder=run_remainder )() )
    assert out[ "unsure_flagged" ] == { "total": 2, "resolved": 1, "of": 20, "also_drifted": 1, "text": "2 of 20, with 1 also drifted" } and out[ "seed" ] == 7 and out[ "pairs" ] == 20


def test_a_full_run_charges_nothing_for_fakes_writes_the_report_and_a_resumed_cap_keeps_its_count( tmp_path ):
    def stage_returning( name, stop=False ):
        async def stage(): return { "name": name, "stop": stop }
        return stage

    rep = asyncio.run( ft.run_first_thousand( str( tmp_path ), stage_returning( "a" ), stage_returning( "b" ), stage_returning( "c" ), stage_returning( "d" ) ) )
    assert [ rep[ "stages" ][ n ][ "status" ] for n in stages.ORDER ] == [ "done" ] * 4 and rep[ "used" ] == 0 and rep[ "limit" ] == 1314
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


SENTENCE = "A function that releases everything a view holds when it goes away."


def strip_of( rec ):
    """Return a stripped original for the drafter, without reading a tree."""
    return { "kind": "function", "text": "def f(): pass", "forbidden": [ rec[ "name" ] ] }


def real_pair( i=0 ):
    """Return a pair with a language on each side, as the real planted file has."""
    p = pairs()[ i ]
    return { **p, "original": { **p[ "original" ], "lang": "py" }, "rewrite": { **p[ "rewrite" ], "lang": "py" } }


def test_the_drafter_job_makes_a_sentence_pass_the_real_drafter_with_a_fake_model( tmp_path ):
    job    = ft.control_job( real_pair(), strip_of )
    ledger = draft.make_ledger( str( tmp_path / "l.jsonl" ), None, "max-plan" )
    got    = draft.draft_need( job, lambda system, user: SENTENCE, ledger )
    assert job[ "seed" ][ "id" ] == "d-orig00" and [ k[ "id" ] for k in job[ "keys" ] ] == [ "d-rew00" ] and job[ "write_lang" ] == "py" and job[ "seed" ][ "lang" ] == "py"
    assert got[ "ok" ] is True and got[ "need" ] == SENTENCE


def test_the_planted_stage_shares_the_live_stage_settings_but_caches_in_the_run_folder( monkeypatch, tmp_path ):
    cache = tmp_path / "run" / "query-cache"
    live = types.SimpleNamespace( vectors_dir="/v", query_cache_dir="/q", embed_client="client", purposes_path="/p", K=9, arm="B1", fusion=None )
    seen = {}

    class FakeStage:
        def __init__( self, vectors_dir, query_cache_dir, embed_client, planted, **kw ): seen.update( vectors_dir=vectors_dir, cache=query_cache_dir, client=embed_client, planted=planted, kw=kw )

    monkeypatch.setattr( planted_pool, "PlantedCandidateStage", FakeStage )
    monkeypatch.setattr( planted_pool, "PlantedVectors", lambda base, ids, rows: ( base, ids, rows ) )
    ft.planted_stage_for( live, [ { "id": "d-rew00" } ], cache, embed_rows=lambda entries, client, purposes: ( "rows", client, purposes ), load_vectors=lambda folder: ( "base", folder ) )
    assert seen[ "planted" ] == ( ( "base", "/v" ), [ "d-rew00" ], ( "rows", "client", None ) ) and seen[ "vectors_dir" ] == "/v" and seen[ "cache" ] == str( cache ) and seen[ "client" ] == "client"
    assert cache.is_dir() and seen[ "cache" ] != "/q"
    assert seen[ "kw" ] == { "purposes_path": "/p", "K": 9, "arm": "B1", "fusion": None } and "refresher" not in seen[ "kw" ]
    ft.planted_stage_for( live, [ { "id": "d-rew00" } ], cache, embed_rows=lambda entries, client, purposes: ( "rows", client, purposes ), load_vectors=lambda folder: ( "base", folder ),
                          purposes={ "pin": "a line" }, purposes_file="/merged" )
    assert seen[ "planted" ][ 2 ] == ( "rows", "client", { "pin": "a line" } ) and seen[ "kw" ][ "purposes_path" ] == "/merged"      # the plant's line reaches the vectors and the word index


def test_the_live_control_drafts_first_then_plants_and_the_calls_are_the_drafters_only( monkeypatch, tmp_path ):
    ps      = [ real_pair( i ) for i in range( 20 ) ]
    log     = []
    ctx     = live_ctx()
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache, **kw: log.append( ( "stage", live, len( entries ), cache ) ) or PLANTED )

    def draft_fn( job, ask, ledger, **kw ):
        log.append( ( "draft", job[ "seed" ][ "id" ] ) )
        return { "ok": True, "need": SENTENCE }

    def check( need, c, planted, entries ):
        log.append( ( "check", need[ "seed" ], planted ) )
        return { "id": "r", "candidate_stage": { "ids": [ e[ "id" ] for e in entries ] + [ f"idx.{need[ 'seed' ]}" ], "widened_ids": [] }, "shortlist": [] }

    stage = ft.control_stage_live( ctx, ps, "ask", "ledger", strip_of, draft_fn, "CACHE", prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage )
    out   = asyncio.run( stage() )
    kinds = [ k[ 0 ] for k in log ]
    assert kinds == [ "draft" ] * 20 + [ "stage", "stage" ] + [ "check" ] * 40 and log[ 20 ] == ( "stage", "live stage", 20, "CACHE" ) and log[ 21 ] == ( "stage", "live stage", 20, "CACHE-bare" )
    assert out[ "found" ] == 20 and out[ "stop" ] is False
    assert all( k[ 2 ] == "planted stage" for k in log[ 22: ] ) and [ k[ 1 ] for k in log[ 22: ][ ::2 ] ] == [ p[ "original" ][ "id" ] for p in ps ], "each pair is checked live, then once over the bare plants"


def index_records():
    """Return 120 ts and 80 py index records."""
    return [ { "id": f"{lang}-{i}", "lang": lang, "file": f"src/{lang}/f{i}.{lang}", "name": f"fn{i}" } for lang in ( "ts", "py" ) for i in range( 120 if lang == "ts" else 80 ) ]


def test_the_seed_lists_are_drawn_from_tracked_files_without_the_planted_originals_and_written_once( tmp_path ):
    ps      = [ real_pair( i ) for i in range( 20 ) ]
    rows    = index_records()
    rows[ 0 ].update( file=ps[ 0 ][ "original" ][ "file" ], name=ps[ 0 ][ "original" ][ "name" ] )
    tracked = { r[ "file" ] for r in rows if r[ "id" ] != "ts-1" }
    built   = ( { r[ "id" ]: r for r in rows }, sorted( rows, key=lambda r: r[ "id" ] ), None, None, None )
    path    = ft.write_seed_lists( "/r", str( tmp_path ), ps, 7, "abc", built, tracked=lambda root: tracked )
    got  = json.loads( path.read_text( encoding="utf-8" ) )
    drawn = { i for stage in ( "attribution", "yield" ) for i in got[ stage ][ "order" ] }
    assert path.name == stage_seeds.LISTS_FILE and got[ "pool" ][ "excluded_planted" ] == 1
    assert "ts-0" not in drawn and "ts-1" not in drawn and len( got[ "attribution" ][ "order" ] ) == 50 and len( got[ "yield" ][ "order" ] ) == 100
    assert ft.write_seed_lists( "/r", str( tmp_path ), ps, 7, "abc", built, tracked=lambda root: tracked ) == path


def test_the_tracked_files_are_what_git_lists_for_the_tree_and_a_stub_shows_the_call( monkeypatch ):
    assert "CLAUDE.md" in ft.tracked_files( cu.get_project_root() )
    seen = {}
    monkeypatch.setattr( ft.subprocess, "run", lambda argv, **kw: seen.update( argv=argv ) or types.SimpleNamespace( stdout="a.py\0b/c.ts\0" ) )
    assert ft.tracked_files( "/x" ) == { "a.py", "b/c.ts" } and seen[ "argv" ] == [ "git", "-C", "/x", "ls-files", "-z" ]


LISTS_OF_TWO_AND_THREE = { "attribution": { "order": [ "a1", "a2" ] }, "yield": { "order": [ "y1", "y2", "y3" ] } }


def test_the_stage_factories_hand_the_lists_file_and_the_live_parts_to_pocholos_two_stages_and_add_the_counts( monkeypatch ):
    seen  = {}
    tally = stage_parts.Tally()
    parts = { "make_need": "MN", "trace_fn": "TF", "prepare_fn": "PF", "index": "IX", "tally": tally }

    def stage_of( report ):
        async def stage():
            tally[ "disputed" ] += 2
            tally.ids.append( "n-1" )
            return report
        return stage

    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: seen.update( a=( path, make_need, trace_fn ) ) or stage_of( { "needs": 1 } ) )
    monkeypatch.setattr( stage_seeds, "yield_stage", lambda path, prepare_fn, index: seen.update( y=( path, prepare_fn, index ) ) or stage_of( { "seeds": 1, "hard": 2 } ) )
    monkeypatch.setattr( stage_seeds, "load_lists", lambda path: LISTS_OF_TWO_AND_THREE )
    one, two = ft.stage_factories( "/lists.json", parts )
    counts   = { "not_pooled": 0, "no_partner": 0, "draft_failed": 0, "disputed": 2, "unreadable_reply": 0, "unstrippable_seed": 0, "disputed_ids": [ "n-1" ], "skipped": [] }
    assert asyncio.run( one( "env" )() ) == { "needs": 1, "no_final_need": counts } and asyncio.run( two( "env" )() ) == { "seeds": 1, "hard": 2, "no_final_need": { **counts, "disputed_ids": [ "n-1" ] } }
    assert seen == { "a": ( "/lists.json", "MN", "TF" ), "y": ( "/lists.json", "PF", "IX" ) }


def test_the_yield_report_counts_only_the_yield_seeds_and_not_the_attribution_ones( monkeypatch ):
    tally = stage_parts.Tally()
    parts = { "make_need": None, "trace_fn": None, "prepare_fn": None, "index": None, "tally": tally }

    def stage_that( reason, ids ):
        async def stage():
            tally[ reason ] += len( ids )
            tally.ids.extend( ids )
            return { "needs": 1, "seeds": 1 }
        return stage

    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: stage_that( "disputed", [ "n-a1", "n-a2" ] ) )
    monkeypatch.setattr( stage_seeds, "yield_stage", lambda path, prepare_fn, index: stage_that( "draft_failed", [] ) )
    monkeypatch.setattr( stage_seeds, "load_lists", lambda path: LISTS_OF_TWO_AND_THREE )
    one, two = ft.stage_factories( "/lists.json", parts )
    first    = asyncio.run( one( "env" )() )[ "no_final_need" ]
    second   = asyncio.run( two( "env" )() )[ "no_final_need" ]
    assert first == { "not_pooled": 0, "no_partner": 0, "draft_failed": 0, "disputed": 2, "unreadable_reply": 0, "unstrippable_seed": 0, "disputed_ids": [ "n-a1", "n-a2" ], "skipped": [] }
    assert second == { "not_pooled": 0, "no_partner": 0, "draft_failed": 0, "disputed": 0, "unreadable_reply": 0, "unstrippable_seed": 0, "disputed_ids": [], "skipped": [] }


def test_the_live_parts_use_their_own_ledgers_in_the_run_folder_and_the_arguments_models( tmp_path, monkeypatch ):
    seen = {}
    args = types.SimpleNamespace( run_dir=str( tmp_path ), cli_path=None, server="max-plan", second_model="M2", probe_model="MP", partners=False )
    env  = types.SimpleNamespace( ask="DRAFT-ASK" )
    monkeypatch.setattr( draft, "drafter_call", lambda model=draft.DRAFTER_MODEL: f"ask-{model}" )

    def build( env_, built, lists, models, drafter, second, ledgers, partners ):
        seen.update( env=env_, built=built, lists=lists, models=models, drafter=drafter, second=second, ledgers=ledgers, partners=partners )
        return "PARTS"

    assert ft.live_parts( args, env, "BUILT", "LISTS", build=build ) == "PARTS"
    assert seen[ "models" ] == { "second": "M2", "probe": "MP" } and seen[ "drafter" ] == "DRAFT-ASK" and seen[ "second" ] == "ask-M2" and seen[ "built" ] == "BUILT" and seen[ "lists" ] == "LISTS"
    paths = { k: pathlib.Path( v.ledger.path if hasattr( v, "ledger" ) else v.path ).name for k, v in seen[ "ledgers" ].items() }
    assert paths == { "draft": "ledger-stage-draft.jsonl", "second": "ledger-stage-second.jsonl", "trace": "ledger-trace.jsonl", "rejections": "ledger-rejections.jsonl" }
    assert seen[ "partners" ] is False and isinstance( seen[ "ledgers" ][ "rejections" ], stage_parts.RejectionLedger )
    assert isinstance( seen[ "ledgers" ][ "draft" ], draft.SharedLedger ) and isinstance( seen[ "ledgers" ][ "second" ], draft.SharedLedger )


def run_dir_files( tmp_path, cli=True ):
    """Write the proof's input files; return the command line, with a binary unless cli is false."""
    import hashlib
    ps       = pairs()
    one, two = labelled( ps )
    planted  = tmp_path / "planted.json"
    planted.write_text( json.dumps( { "failed": [], "planted": ps } ), encoding="utf-8" )
    key      = tmp_path / "answer-key.json"
    key.write_text( json.dumps( { "items": key_of( ps ) } ), encoding="utf-8" )
    labels   = tmp_path / "labels"
    labels.mkdir()
    for name, rows in ( ( "labels-rick.jsonl", one ), ( "labels-rick-redo.jsonl", { } ), ( "labels-reviewer-2.jsonl", two ) ):
        ( labels / name ).write_text( "".join( json.dumps( r ) + "\n" for r in rows.values() ), encoding="utf-8" )
    run = tmp_path / "run"
    run.mkdir()
    argv = [ "--root", "/r", "--run-dir", str( run ), "--planted", str( planted ), "--answer-key", str( key ), "--labels-dir", str( labels ), "--seed", "7", "--source-commit", "abc" ]
    if cli:
        binary = tmp_path / "claude-bin"
        binary.write_text( "#!/bin/sh\n" )
        binary.chmod( 0o755 )
        argv  += [ "--cli-path", str( binary ) ]
    return argv, hashlib.sha256( planted.read_bytes() ).hexdigest()


def test_the_command_line_needs_its_inputs_and_is_a_plan_unless_live_is_given():
    base = [ "--root", "/r", "--run-dir", "/d", "--planted", "p", "--answer-key", "k", "--labels-dir", "l", "--seed", "7", "--source-commit", "abc" ]
    a    = ft.parse_args( base )
    assert a.seed == 7 and a.limit == 1314 and a.live is False and a.cli_path is None and a.server == "max-plan" and a.second_model == a.probe_model == smoke.SECOND_MODEL and ft.parse_args( [ *base, "--live", "--limit", "5" ] ).live is True
    with pytest.raises( SystemExit ): ft.parse_args( base[ :-2 ] )


def test_without_live_main_plans_from_files_and_touches_nothing_else( tmp_path ):
    argv, sha = run_dir_files( tmp_path )
    boom      = lambda *a, **k: pytest.fail( "something live was touched" )
    out       = ft.main( argv, deps={ "planted_sha": sha, "context": boom, "factories": boom, "runner": boom, "ask": boom } )
    assert out[ "live" ] is False and out[ "plan" ][ "used" ] == 0 and out[ "plan" ][ "remaining" ] == 1314 and out[ "plan" ][ "pairs" ] == 20
    assert out[ "plan" ][ "groups" ] == { "drifted": 2, "other": 17, "unsure": 1 } and out[ "plan" ][ "unsure_flagged" ] == 2 and out[ "plan" ][ "ledger" ].endswith( "call-ledger.jsonl" )


def test_the_plan_shows_the_calls_a_resumed_run_has_already_spent( tmp_path ):
    argv, sha = run_dir_files( tmp_path )
    cap       = call_cap.CallCap( str( tmp_path / "run" / ft.CALLS_FILE ) )
    for _ in range( 3 ): cap.charge( "m" )
    out = ft.main( [ *argv, "--limit", "10" ], deps={ "planted_sha": sha } )
    assert out[ "plan" ][ "used" ] == 3 and out[ "plan" ][ "remaining" ] == 7


def test_a_planted_file_with_the_wrong_hash_stops_before_anything_else( tmp_path ):
    argv, _ = run_dir_files( tmp_path )
    with pytest.raises( er.NeedsetError ) as e: ft.main( argv, deps={ "context": lambda root: pytest.fail( "a context was built" ) } )
    assert e.value.code == er.CONTROL_INPUT_CHANGED


def built_records():
    """Return what smoke.index_parts returns, over 120 ts and 80 py records."""
    rows = index_records()
    return ( { r[ "id" ]: r for r in rows }, sorted( rows, key=lambda r: r[ "id" ] ), None, None, None )


BUILT = built_records()


def seed_deps( skip=None ):
    """Return deps standing in for the index and git: every file tracked but the skipped id's."""
    gone = { BUILT[ 0 ][ skip ][ "file" ] } if skip else set()
    return { "built": lambda args: BUILT, "tracked": lambda root: { r[ "file" ] for r in BUILT[ 1 ] } - gone }


def test_a_live_run_assembles_the_env_for_the_two_stage_factories_and_runs_four_stages( tmp_path ):
    argv, sha = run_dir_files( tmp_path )
    seen      = {}
    ctx       = types.SimpleNamespace( candidate_stage="live" )

    def factory( name ):
        def make( env ):
            seen[ name ] = env
            async def stage(): return { "name": name }
            return stage
        return make

    async def runner( run_dir, one, two, control, rem, limit ):
        seen[ "args" ] = ( run_dir, limit, await one(), await two(), await control(), await rem() )
        return { "ran": True }

    deps = { "planted_sha": sha, "source_root": lambda args: "/s", "parts": lambda args, env, built, lists: seen.update( parts_args=( args.server, env.server, built, lists[ "seed" ], lists[ "sha" ] ) ) or "PARTS", **seed_deps(), "factories": ( factory( "a" ), factory( "y" ) ), "context": lambda root: ctx, "runner": runner, "ask": "ASK", "ledger": lambda args: "LEDGER",
             "strip_fn": strip_of, "source_root": lambda args: "/s", "draft_fn": "DRAFT", "close_run": lambda ctx: None, "remainder": lambda ps, seed: { "per_pair": [], "seed": seed },
             "control": lambda c, ps, ask, ledger, strip_fn, draft_fn, cache: ( seen.update( control_args=( c, len( ps ), ask, ledger, strip_fn, draft_fn, cache ) ) or ( lambda: asyncio.sleep( 0, { "control": True } ) ) ) }
    out  = ft.main( [ *argv, "--live", "--limit", "9" ], deps=deps )
    env  = seen[ "a" ]
    assert out[ "live" ] is True and out[ "report" ] == { "ran": True } and seen[ "y" ] is env
    assert ( env.root, env.seed, env.source_commit, env.ctx, env.ask, env.draft_ledger ) == ( "/s", 7, "abc", ctx, "ASK", "LEDGER" ) and env.run_dir.endswith( "run" )
    assert seen[ "args" ][ 1 ] == 9 and seen[ "args" ][ 2:4 ] == ( { "name": "a" }, { "name": "y" } ) and seen[ "args" ][ 4 ] == { "control": True }
    assert seen[ "args" ][ 5 ][ "unsure_flagged" ] == { "total": 0, "resolved": 0, "of": 20, "also_drifted": 1, "text": "0 of 20, with 1 also drifted" }
    assert seen[ "control_args" ] == ( ctx, 20, "ASK", "LEDGER", strip_of, "DRAFT", f"{env.run_dir}/query-cache" )
    assert seen[ "parts_args" ][ :4 ] == ( "max-plan", "max-plan", BUILT, 7 ) and len( seen[ "parts_args" ][ 4 ] ) == 64 and env.strip_fn is strip_of


def test_a_live_run_passes_the_written_lists_file_and_the_parts_to_the_stage_factories( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path )
    seen      = {}

    def fake_factories( path, parts ):
        seen.update( path=path, parts=parts )
        return ( lambda env: lambda: asyncio.sleep( 0, "one" ), lambda env: lambda: asyncio.sleep( 0, "two" ) )

    async def runner( run_dir, one, two, control, rem, limit ): return { "stages": [ await one(), await two() ] }

    monkeypatch.setattr( ft, "stage_factories", fake_factories )
    deps = { "planted_sha": sha, "parts": lambda args, env, built, lists: "PARTS", **seed_deps(), "context": lambda root: types.SimpleNamespace( candidate_stage="live" ), "runner": runner, "ask": "ASK", "ledger": lambda args: "L",
             "strip_fn": strip_of, "source_root": lambda args: "/s", "draft_fn": "D", "close_run": lambda ctx: None, "remainder": lambda ps, seed: { "per_pair": [], "seed": seed }, "control": lambda *a: ( lambda: asyncio.sleep( 0, {} ) ) }
    out  = ft.main( [ *argv, "--live" ], deps=deps )
    assert seen[ "parts" ] == "PARTS" and pathlib.Path( seen[ "path" ] ).name == stage_seeds.LISTS_FILE and pathlib.Path( seen[ "path" ] ).parent == tmp_path / "run"
    assert out[ "report" ] == { "stages": [ "one", "two" ] }


def test_a_live_run_over_other_seed_lists_stops_by_name_before_the_parts_are_built( tmp_path ):
    argv, sha = run_dir_files( tmp_path )
    base      = { "planted_sha": sha, "context": lambda root: types.SimpleNamespace( candidate_stage="live" ), "ask": "ASK", "ledger": lambda args: "L", "strip_fn": strip_of, "source_root": lambda args: "/s", "draft_fn": "D", "control": lambda *a: None,
                  "parts": lambda args, env, built, lists: "PARTS", "factories": ( lambda env: None, lambda env: None ), "runner": lambda *a: asyncio.sleep( 0, {} ), "close_run": lambda ctx: None, "remainder": lambda ps, seed: {} }
    ft.main( [ *argv, "--live" ], deps={ **base, **seed_deps() } )
    with pytest.raises( er.NeedsetError ) as e: ft.main( [ *argv, "--live" ], deps={ **base, **seed_deps( skip="ts-3" ), "parts": lambda *a: pytest.fail( "parts were built" ) } )
    assert e.value.code == er.PLAN_ALREADY_WRITTEN


def test_a_live_run_over_a_context_with_no_candidate_stage_stops_by_name_before_any_file_or_call( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path )
    monkeypatch.setattr( ft, "write_seed_lists", lambda *a, **k: pytest.fail( "a list was written" ) )
    deps = { "planted_sha": sha, "source_root": lambda args: "/s", "context": lambda root: types.SimpleNamespace( candidate_stage=None ), "ask": lambda *a: pytest.fail( "a model was called" ), "built": lambda args: pytest.fail( "the index was built" ) }
    with pytest.raises( er.NeedsetError ) as e: ft.main( [ *argv, "--live" ], deps=deps )
    assert e.value.code == er.NO_CANDIDATE_STAGE and all( v in str( e.value ) for v in ( "LUPIN_REUSE_JEV_PACK_SIZE", "LUPIN_REUSE_JEV_TOKEN_CEILING", "LUPIN_REUSE_JEV_RUN_NAME" ) )
    assert not ( tmp_path / "run" / "first-thousand-seeds.json" ).exists() and not ( tmp_path / "run" / ft.CALLS_FILE ).exists()


def live_deps( sha, runner ):
    """Return deps for a live run on stand-ins, ending in the given runner."""
    return { "planted_sha": sha, "context": lambda root: types.SimpleNamespace( candidate_stage="live" ), "ask": "ASK", "ledger": lambda args: "L", "strip_fn": strip_of, "source_root": lambda args: "/s", "draft_fn": "D",
             "control": lambda *a: None, "parts": lambda args, env, built, lists: "PARTS", "factories": ( lambda env: None, lambda env: None ), "runner": runner,
             "close_run": lambda ctx: None, "remainder": lambda ps, seed: {}, **seed_deps() }


def test_a_live_run_sends_every_call_through_the_binary_named_by_cli_path_and_a_plan_with_the_same_path_does_not( tmp_path, monkeypatch ):
    from cosa.repo.doc_lint import model_transport as mt
    argv, sha = run_dir_files( tmp_path )
    binary    = argv[ argv.index( "--cli-path" ) + 1 ]
    seen      = {}
    monkeypatch.setattr( mt, "CLI_PATH", None )

    async def runner( *a ):
        seen[ "live" ] = mt.CLI_PATH
        return {}

    ft.main( argv, deps=live_deps( sha, runner ) | { "factories": ( None, None ) } )
    assert mt.CLI_PATH is None and "live" not in seen
    ft.main( [ *argv, "--live" ], deps=live_deps( sha, runner ) )
    assert seen[ "live" ] == binary


def test_a_live_run_without_cli_path_stops_by_name_before_the_context_the_index_or_a_list( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path, cli=False )
    monkeypatch.setattr( ft, "write_seed_lists", lambda *a, **k: pytest.fail( "a list was written" ) )
    deps = live_deps( sha, None ) | { "context": lambda root: pytest.fail( "a context was built" ), "built": lambda args: pytest.fail( "the index was built" ) }
    with pytest.raises( er.NeedsetError ) as e: ft.main( [ *argv, "--live" ], deps=deps )
    assert e.value.code == er.NO_CLI_PATH and "--cli-path" in str( e.value )
    assert ft.main( argv, deps={ "planted_sha": sha } )[ "live" ] is False


def test_a_live_run_with_a_cli_path_that_is_no_executable_stops_by_name_before_the_index_or_a_list( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path )
    monkeypatch.setattr( ft, "write_seed_lists", lambda *a, **k: pytest.fail( "a list was written" ) )
    with pytest.raises( ValueError, match="not an executable file" ): ft.main( [ *argv, "--live", "--cli-path", str( tmp_path / "missing" ) ], deps=live_deps( sha, None ) | { "built": lambda args: pytest.fail( "the index was built" ) } )


def result_of( *statuses ):
    """Return a live main result whose stages have the given statuses."""
    return { "live": True, "close_error": None, "report": { "stages": { f"s{i}": { "status": st } for i, st in enumerate( statuses ) } } }


@pytest.mark.parametrize( "statuses, code", [ ( ( "done", "done", "done", "done" ), 0 ), ( ( "done", "stopped", "not_run", "not_run" ), 0 ), ( ( "failed", "not_run", "not_run", "not_run" ), 1 ),
                                              ( ( "done", "cap_reached", "not_run", "not_run" ), 3 ), ( ( "cap_reached", "failed", "not_run", "not_run" ), 1 ) ] )
def test_a_failed_stage_exits_one_and_a_cap_stop_three_while_a_finding_stop_exits_zero( statuses, code ):
    assert ft.exit_status( result_of( *statuses ) ) == code and code != 2
    assert ft.exit_status( { "live": False, "plan": {} } ) == 0


def test_the_command_prints_the_report_of_a_failed_run_and_returns_one( tmp_path, capsys ):
    argv, sha = run_dir_files( tmp_path )
    shown     = []

    async def runner( run_dir, one, two, control, rem, limit ): return { "stages": { "attribution": { "status": "failed", "code": "UNREADABLE_REPLY" } } }

    code = ft.run_cli( [ *argv, "--live" ], deps=live_deps( sha, runner ), out=shown.append )
    assert code == 1 and "UNREADABLE_REPLY" in shown[ 0 ] and json.loads( shown[ 0 ] )[ "report" ][ "stages" ][ "attribution" ][ "status" ] == "failed"
    assert ft.run_cli( argv, deps={ "planted_sha": sha }, out=shown.append ) == 0 and json.loads( shown[ 1 ] )[ "live" ] is False


def skipping_stage( tally, count, report ):
    """Return a stage that skips count seeds as unreadable when it runs and then returns report."""
    async def stage():
        for i in range( count ):
            tally[ "unreadable_reply" ] += 1
            tally.skipped.append( { "seed": f"s{i}", "code": "UNREADABLE_REPLY", "detail": "k" } )
        return report
    return stage


def test_a_stage_whose_every_seed_was_skipped_as_unreadable_fails_by_name_and_does_not_read_as_a_stop( monkeypatch ):
    tally = stage_parts.Tally()
    parts = { "make_need": None, "trace_fn": None, "prepare_fn": None, "index": None, "tally": tally }
    monkeypatch.setattr( stage_seeds, "load_lists", lambda path: LISTS_OF_TWO_AND_THREE )
    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: skipping_stage( tally, 2, { "stop": True, "reason": "no seed gave a need" } ) )
    monkeypatch.setattr( stage_seeds, "yield_stage", lambda path, prepare_fn, index: skipping_stage( tally, 3, {} ) )
    one, two = ft.stage_factories( "/lists.json", parts )
    with pytest.raises( er.NeedsetError ) as e: asyncio.run( one( "env" )() )
    assert e.value.code == er.ALL_SEEDS_UNREADABLE and "attribution" in str( e.value ) and "2" in str( e.value )
    with pytest.raises( er.NeedsetError ) as e: asyncio.run( two( "env" )() )
    assert e.value.code == er.ALL_SEEDS_UNREADABLE and "yield" in str( e.value ) and "3" in str( e.value )


def test_a_stage_with_some_seeds_skipped_as_unreadable_still_reports_and_the_failed_stage_exits_one( monkeypatch ):
    tally = stage_parts.Tally()
    parts = { "make_need": None, "trace_fn": None, "prepare_fn": None, "index": None, "tally": tally }
    monkeypatch.setattr( stage_seeds, "load_lists", lambda path: LISTS_OF_TWO_AND_THREE )
    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: skipping_stage( tally, 1, { "needs": 1 } ) )
    one, _ = ft.stage_factories( "/lists.json", parts )
    got    = asyncio.run( one( "env" )() )
    assert got[ "needs" ] == 1 and got[ "no_final_need" ][ "unreadable_reply" ] == 1 and got[ "no_final_need" ][ "skipped" ][ 0 ][ "seed" ] == "s0"
    assert ft.exit_status( result_of( "failed", "not_run", "not_run", "not_run" ) ) == 1


def test_a_run_whose_attribution_seeds_were_all_skipped_ends_failed_through_run_stages_and_exits_one( tmp_path, monkeypatch ):
    cap   = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), 5 )
    tally = stage_parts.Tally()
    parts = { "make_need": None, "trace_fn": None, "prepare_fn": None, "index": None, "tally": tally }
    monkeypatch.setattr( stage_seeds, "load_lists", lambda path: LISTS_OF_TWO_AND_THREE )
    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: skipping_stage( tally, 2, { "stop": True } ) )
    one, two = ft.stage_factories( "/lists.json", parts )

    async def never(): return {}

    with cap.installed(): report = asyncio.run( stages.run_stages( cap, { stages.ATTRIBUTION: one( None ), stages.YIELD: never, stages.CONTROL: never, stages.REMAINDER: never } ) )
    assert report[ "stages" ][ "attribution" ][ "status" ] == "failed" and report[ "stages" ][ "attribution" ][ "code" ] == er.ALL_SEEDS_UNREADABLE and report[ "stages" ][ "yield" ][ "status" ] == "not_run"
    assert ft.exit_status( { "live": True, "close_error": None, "report": report } ) == 1


def test_a_stage_with_no_listed_seeds_and_no_skips_is_not_called_all_skipped( monkeypatch ):
    tally = stage_parts.Tally()
    parts = { "make_need": None, "trace_fn": None, "prepare_fn": None, "index": None, "tally": tally }
    monkeypatch.setattr( stage_seeds, "load_lists", lambda path: { "attribution": { "order": [] }, "yield": { "order": [] } } )
    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: skipping_stage( tally, 0, { "needs": 0 } ) )
    one, _ = ft.stage_factories( "/lists.json", parts )
    assert asyncio.run( one( "env" )() )[ "no_final_need" ][ "unreadable_reply" ] == 0


def factory_with( monkeypatch, skips, attribution_report, yield_report ):
    """Return the two factories over stages that skip the given counts and return the reports."""
    tally = stage_parts.Tally()
    parts = { "make_need": None, "trace_fn": None, "prepare_fn": None, "index": None, "tally": tally }
    monkeypatch.setattr( stage_seeds, "load_lists", lambda path: LISTS_OF_TWO_AND_THREE )
    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: skipping_stage( tally, skips[ 0 ], attribution_report ) )
    monkeypatch.setattr( stage_seeds, "yield_stage", lambda path, prepare_fn, index: skipping_stage( tally, skips[ 1 ], yield_report ) )
    return ft.stage_factories( "/lists.json", parts )


def test_a_stage_with_no_need_and_a_skipped_seed_fails_but_with_no_skipped_seed_it_stays_a_stop( monkeypatch ):
    one, two = factory_with( monkeypatch, ( 1, 1 ), { "needs": 0, "stop": True }, { "seeds": 0, "hard": 0 } )
    for factory, name in ( ( one, "attribution" ), ( two, "yield" ) ):
        with pytest.raises( er.NeedsetError ) as e: asyncio.run( factory( "env" )() )
        assert e.value.code == er.NO_NEEDS_WITH_SKIPS and name in str( e.value ) and "could have held" in str( e.value )
    one, two = factory_with( monkeypatch, ( 0, 0 ), { "needs": 0, "stop": True }, { "seeds": 0, "hard": 0 } )
    assert asyncio.run( one( "env" )() )[ "stop" ] is True and asyncio.run( two( "env" )() )[ "seeds" ] == 0


def test_a_stage_with_a_need_and_a_skipped_seed_is_not_failed_for_the_skip( monkeypatch ):
    one, two = factory_with( monkeypatch, ( 1, 2 ), { "needs": 1 }, { "seeds": 1, "hard": 0 } )
    assert asyncio.run( one( "env" )() )[ "needs" ] == 1 and asyncio.run( two( "env" )() )[ "seeds" ] == 1


def test_a_stage_with_no_need_and_only_disputed_or_no_partner_seeds_stays_a_stop_with_exit_zero( tmp_path, monkeypatch ):
    cap   = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), 5 )
    tally = stage_parts.Tally()
    parts = { "make_need": None, "trace_fn": None, "prepare_fn": None, "index": None, "tally": tally }
    monkeypatch.setattr( stage_seeds, "load_lists", lambda path: LISTS_OF_TWO_AND_THREE )

    async def stage():
        tally[ "disputed" ] += 1
        tally[ "no_partner" ] += 1
        return { "needs": 0, "stop": True, "reason": "no seed gave a need" }

    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: stage )
    one, _ = ft.stage_factories( "/lists.json", parts )

    async def never(): return {}

    with cap.installed(): report = asyncio.run( stages.run_stages( cap, { stages.ATTRIBUTION: one( None ), stages.YIELD: never, stages.CONTROL: never, stages.REMAINDER: never } ) )
    seen = report[ "stages" ][ "attribution" ]
    assert seen[ "status" ] == "stopped" and seen[ "report" ][ "no_final_need" ][ "disputed" ] == 1 and seen[ "report" ][ "no_final_need" ][ "no_partner" ] == 1 and seen[ "report" ][ "no_final_need" ][ "unreadable_reply" ] == 0
    assert ft.exit_status( { "live": True, "close_error": None, "report": report } ) == 0


def test_the_spend_ledger_run_is_closed_when_the_stages_end_and_also_when_they_raise( tmp_path ):
    argv, sha = run_dir_files( tmp_path )
    closed    = []

    async def ended( run_dir, one, two, control, rem, limit ): return { "stages": {} }

    async def crashed( run_dir, one, two, control, rem, limit ): raise RuntimeError( "boom" )

    out = ft.main( [ *argv, "--live" ], deps=live_deps( sha, ended ) | { "close_run": lambda ctx: closed.append( ctx ) or "needset-run" } )
    assert out[ "closed_run" ] == "needset-run" and len( closed ) == 1
    with pytest.raises( RuntimeError, match="boom" ): ft.main( [ *argv, "--live" ], deps=live_deps( sha, crashed ) | { "close_run": lambda ctx: closed.append( ctx ) } )
    assert len( closed ) == 2, "a run that dies on an error still closes its ledger run"


def test_partners_are_off_unless_asked_for_and_a_budget_stop_exits_with_the_cap_code( tmp_path ):
    argv, sha = run_dir_files( tmp_path )
    assert ft.parse_args( argv ).partners is False and ft.parse_args( [ *argv, "--partners" ] ).partners is True
    live = lambda status: { "live": True, "close_error": None, "report": { "stages": { "attribution": { "status": status }, "yield": { "status": "done" } } } }
    assert ft.exit_status( live( "budget_reached" ) ) == ft.EXIT_CAP_REACHED and ft.exit_status( live( "failed" ) ) == ft.EXIT_FAILED and ft.exit_status( live( "done" ) ) == 0


def test_the_first_thousand_cap_gives_each_stage_its_own_budget_and_the_remainder_none( tmp_path ):
    async def stage(): return {}
    cap_seen = []
    real     = call_cap.CallCap

    class Spy( real ):
        def __init__( self, *a, **k ):
            super().__init__( *a, **k )
            cap_seen.append( self.stage_limits )

    call_cap.CallCap = Spy
    try: asyncio.run( ft.run_first_thousand( str( tmp_path ), stage, stage, stage, stage ) )
    finally: call_cap.CallCap = real
    assert cap_seen == [ stages.STAGE_BUDGETS ] and stages.STAGE_BUDGETS[ "remainder" ] == 0


def control_world( ledgers, miss_on_second=False ):
    """Return ( ctx, draft_fn, check ) for a multi-pass control on fakes."""
    ctx    = live_ctx()

    def draft_fn( job, ask, ledger, **kw ):
        ledgers.append( ledger )
        return { "ok": True, "need": SENTENCE }

    def check( need, c, planted, entries ):
        n    = len( ledgers ) // 20
        keep = [ e[ "id" ] for e in entries ] + [ f"idx.{need[ 'seed' ]}" ]
        if miss_on_second and n == 2: keep = keep[ 1: ]
        return { "id": "r", "candidate_stage": { "ids": keep, "widened_ids": [] }, "shortlist": [] }

    return ctx, draft_fn, check


def test_the_control_runs_twice_when_asked_each_pass_on_its_own_ledger_and_cache( monkeypatch ):
    ps, ledgers, caches = [ real_pair( i ) for i in range( 20 ) ], [], []
    ctx, draft_fn, check = control_world( ledgers )
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache, **kw: caches.append( cache ) or PLANTED )
    stage = ft.control_stage_live( ctx, ps, "ask", "L1", strip_of, draft_fn, "CACHE", prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage,
                                   passes=2, pass_resources=lambda n: ( f"L{n + 1}", f"CACHE-pass{n + 1}" ) )
    out = asyncio.run( stage() )
    assert ledgers == [ "L1" ] * 20 + [ "L2" ] * 20 and caches == [ "CACHE", "CACHE-bare", "CACHE-pass2", "CACHE-pass2-bare" ], "the second pass asks again, from its own cache"
    assert len( out[ "passes" ] ) == 2 and out[ "consistent" ] is True and out[ "stop" ] is False and out[ "found" ] == 20 and out[ "passes" ][ 1 ][ "found" ] == 20


def test_a_pair_missed_on_one_pass_only_makes_the_passes_inconsistent_and_a_plant_miss_alone_does_not_stop_the_run( monkeypatch ):
    ps, ledgers, caches = [ real_pair( i ) for i in range( 20 ) ], [], []
    ctx, draft_fn, check = control_world( ledgers, miss_on_second=True )
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache, **kw: PLANTED )
    stage = ft.control_stage_live( ctx, ps, "ask", "L1", strip_of, draft_fn, "CACHE", prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage,
                                   passes=2, pass_resources=lambda n: ( "L2", "C2" ) )
    out = asyncio.run( stage() )
    assert out[ "passes" ][ 0 ][ "missed" ] == [] and len( out[ "passes" ][ 1 ][ "missed" ] ) == 1 and out[ "consistent" ] is False
    assert out[ "stop" ] is False and out[ "pass_marks" ] == [ True, True ], "one missed plant is inside the pass mark and never sets stop"


def test_a_multi_pass_control_needs_its_pass_resources_and_at_least_one_pass():
    for passes, resources in ( ( 2, None ), ( 0, None ) ):
        with pytest.raises( ValueError, match="pass_resources" ): ft.control_stage_live( None, [], "a", "l", None, None, "c", passes=passes, pass_resources=resources )


def plant_store( tmp_path, ps ):
    """Write a purpose store with a line for the first two plants, in the run folder."""
    store = pathlib.Path( planted_purposes.lines_path( str( tmp_path ) ) )
    store.parent.mkdir( parents=True )
    pins = [ planted_pool.planted_entry( p[ "rewrite" ] )[ "pin" ] for p in ps[ :2 ] ]
    store.write_text( "".join( json.dumps( { "pin": pin, "purpose": f"Does thing {n}.", "prompt_hash": "h", "writer_version": "bounded-cc-1" } ) + "\n" for n, pin in enumerate( pins ) ), encoding="utf-8" )
    return store, pins


def test_the_live_control_is_two_passes_that_share_the_first_passs_drafts_and_each_has_its_own_cache_folder( monkeypatch, tmp_path ):
    seen = {}
    ps   = [ real_pair( i ) for i in range( 4 ) ]
    store, pins = plant_store( tmp_path, ps )
    monkeypatch.setattr( ft, "control_stage_live", lambda *a, **k: seen.update( args=a, kw=k ) or "STAGE" )
    args = types.SimpleNamespace( run_dir=str( tmp_path ), cli_path="/bin/claude", server="max-plan", plant_purposes=None )
    got  = ft.live_control( args, { "same_job": { "d-rew00": True }, "label_shas": { "labels-rick.jsonl": "aa" }, "answer_key_sha": "bb" } )( "ctx", ps, "ask", "L1", "strip", "draft", "CACHE" )
    assert ft.CONTROL_PASSES == 2 and got == "STAGE" and seen[ "args" ] == ( "ctx", ps, "ask", "L1", "strip", "draft", "CACHE" ) and seen[ "kw" ][ "passes" ] == 2
    assert seen[ "kw" ][ "pass_resources" ]( 1 ) == ( "L1", "CACHE-pass2" ), "a later pass is judged on the first pass's sentences and draws none again"
    assert seen[ "kw" ][ "plant_lines" ] == { pins[ 0 ]: "Does thing 0.", pins[ 1 ]: "Does thing 1." } and seen[ "kw" ][ "plant_without" ] == [ "d-rew02", "d-rew03" ]
    assert seen[ "kw" ][ "same_job" ] == { "d-rew00": True } and seen[ "kw" ][ "label_info" ] == { "label_shas": { "labels-rick.jsonl": "aa" }, "answer_key_sha": "bb" }
    ft.live_control( args )( "ctx", ps, "ask", "L1", "strip", "draft", "CACHE" )
    assert seen[ "kw" ][ "same_job" ] is None and seen[ "kw" ][ "label_info" ] is None


def test_the_live_control_refuses_by_name_when_the_plants_have_no_purpose_store_and_reads_a_named_one( monkeypatch, tmp_path ):
    seen = {}
    ps   = [ real_pair( i ) for i in range( 2 ) ]
    monkeypatch.setattr( ft, "control_stage_live", lambda *a, **k: seen.update( kw=k ) or "STAGE" )
    args = types.SimpleNamespace( run_dir=str( tmp_path ), plant_purposes=None )
    with pytest.raises( er.NeedsetError ) as caught: ft.live_control( args )( "ctx", ps, "ask", "L1", "strip", "draft", "CACHE" )
    assert caught.value.code == er.PLANT_LINES_MISSING and "planted_purposes" in caught.value.detail and seen == { }
    named = tmp_path / "elsewhere.jsonl"
    named.write_text( "", encoding="utf-8" )
    ft.live_control( types.SimpleNamespace( run_dir=str( tmp_path ), plant_purposes=str( named ) ) )( "ctx", ps, "ask", "L1", "strip", "draft", "CACHE" )
    assert seen[ "kw" ][ "plant_lines" ] == { } and seen[ "kw" ][ "plant_without" ] == [ "d-rew00", "d-rew01" ]


def test_an_error_after_the_context_is_built_but_before_the_runner_still_closes_the_spend_run_and_is_the_error_raised( tmp_path ):
    argv, sha = run_dir_files( tmp_path )
    closed    = []

    def broken_parts( args, env, built, lists ): raise RuntimeError( "parts failed after the run began" )

    deps = live_deps( sha, None ) | { "parts": broken_parts, "close_run": lambda ctx: closed.append( ctx ) }
    with pytest.raises( RuntimeError, match="parts failed" ): ft.main( [ *argv, "--live" ], deps=deps )
    assert len( closed ) == 1


def test_a_close_that_raises_while_another_error_is_on_its_way_never_replaces_it( tmp_path, capsys ):
    argv, sha = run_dir_files( tmp_path )

    def broken_parts( args, env, built, lists ): raise RuntimeError( "the real error" )

    def broken_close( ctx ): raise OSError( "ledger unreadable" )

    with pytest.raises( RuntimeError, match="the real error" ): ft.main( [ *argv, "--live" ], deps=live_deps( sha, None ) | { "parts": broken_parts, "close_run": broken_close } )
    assert "close_run failed while another error was raised" in capsys.readouterr().out


def test_a_close_that_raises_after_a_clean_finish_is_reported_and_exits_one_and_the_stage_report_survives( tmp_path ):
    argv, sha = run_dir_files( tmp_path )

    async def ended( run_dir, one, two, control, rem, limit ): return { "stages": { "attribution": { "status": "done" } } }

    def broken_close( ctx ): raise OSError( "ledger unreadable" )

    out = ft.main( [ *argv, "--live" ], deps=live_deps( sha, ended ) | { "close_run": broken_close } )
    assert out[ "closed_run" ] is None and "ledger unreadable" in out[ "close_error" ] and out[ "report" ][ "stages" ][ "attribution" ][ "status" ] == "done"
    assert ft.exit_status( out ) == ft.EXIT_FAILED


def budget_control( budget_on, ledgers, error_code=er.STAGE_BUDGET_REACHED ):
    """Return ( ctx, draft_fn, check ); a draft from the ledger budget_on raises."""
    ctx, draft_fn, check = control_world( ledgers )

    def drafting( job, ask, ledger, **kw ):
        if ledger == budget_on: raise er.NeedsetError( error_code, "the control stage used 250 of its 250 calls" )
        return draft_fn( job, ask, ledger )

    return ctx, drafting, check


def run_budget_control( monkeypatch, budget_on, passes=2, error_code=er.STAGE_BUDGET_REACHED ):
    """Run a control whose drafting raises on one ledger; return its report."""
    ps, ledgers = [ real_pair( i ) for i in range( 20 ) ], []
    ctx, drafting, check = budget_control( budget_on, ledgers, error_code )
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache, **kw: PLANTED )
    stage = ft.control_stage_live( ctx, ps, "ask", "L1", strip_of, drafting, "CACHE", prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage,
                                   passes=passes, pass_resources=lambda n: ( "L2", "C2" ) )
    return asyncio.run( stage() )


def test_a_control_whose_second_pass_hits_the_budget_keeps_the_finished_first_pass_in_its_report( monkeypatch ):
    out = run_budget_control( monkeypatch, "L2" )
    assert out[ "budget_reached" ] is True and "250 of its 250" in out[ "budget_detail" ] and out[ "passes_done" ] == 1 and out[ "passes_wanted" ] == 2
    assert len( out[ "passes" ] ) == 1 and out[ "passes" ][ 0 ][ "found" ] == 20 and out[ "found" ] == 20 and out[ "stop" ] is False and out[ "consistent" ] is True


def test_a_control_that_hits_the_budget_before_any_pass_finishes_reports_an_empty_pass_list( monkeypatch ):
    out = run_budget_control( monkeypatch, "L1" )
    assert out[ "budget_reached" ] is True and out[ "passes" ] == [] and out[ "passes_done" ] == 0 and "found" not in out and out[ "stop" ] is False
    single = run_budget_control( monkeypatch, "L1", passes=1 )
    assert single[ "budget_reached" ] is True and single[ "passes" ] == [] and single[ "passes_wanted" ] == 1


def test_a_finished_multi_pass_control_says_it_was_not_stopped_by_the_budget_and_another_error_still_raises( monkeypatch ):
    ps, ledgers = [ real_pair( i ) for i in range( 20 ) ], []
    ctx, draft_fn, check = control_world( ledgers )
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache, **kw: PLANTED )
    stage = ft.control_stage_live( ctx, ps, "ask", "L1", strip_of, draft_fn, "CACHE", prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage,
                                   passes=2, pass_resources=lambda n: ( "L2", "C2" ) )
    done = asyncio.run( stage() )
    assert done[ "budget_reached" ] is False and done[ "budget_detail" ] is None and done[ "passes_done" ] == 2
    with pytest.raises( er.NeedsetError ) as caught: run_budget_control( monkeypatch, "L2", error_code=er.CALL_CAP_REACHED )
    assert caught.value.code == er.CALL_CAP_REACHED


def test_a_live_run_takes_the_source_commits_worktree_as_the_one_root_for_the_context_the_index_the_strips_and_the_trace( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path )
    seen      = { "strip": [], "context": [] }
    monkeypatch.setattr( ft.source_at, "ensure_worktree", lambda repo, commit: seen.update( tree=( repo, commit ) ) or "/WT" )
    monkeypatch.setattr( ft.source_at, "unlock", lambda repo, dest: None )
    monkeypatch.setattr( ft.smoke, "index_parts", lambda root, index_dir: seen.update( index=( root, index_dir ) ) or BUILT )
    monkeypatch.setattr( ft.strip, "strip_member", lambda rec, root: seen[ "strip" ].append( root ) or strip_of( rec ) )

    def parts( args, env, built, lists ):
        env.strip_fn( BUILT[ 1 ][ 0 ] )
        seen[ "env_root" ] = env.root
        return "PARTS"

    deps = { **live_deps( sha, lambda *a: asyncio.sleep( 0, {} ) ), "parts": parts, "control": lambda *a: None,
             "context": lambda root: seen[ "context" ].append( root ) or types.SimpleNamespace( candidate_stage="live" ) }
    for name in ( "strip_fn", "source_root", "built" ): del deps[ name ]
    ft.main( [ *argv, "--live" ], deps=deps )
    assert seen[ "tree" ] == ( "/r", "abc" ) and seen[ "context" ] == [ "/WT" ] and seen[ "index" ] == ( "/WT", f"{tmp_path / 'run'}/index" )
    assert seen[ "strip" ] == [ "/WT" ] and seen[ "env_root" ] == "/WT"


def test_a_plan_without_live_never_makes_a_worktree( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path )
    monkeypatch.setattr( ft.source_at, "ensure_worktree", lambda *a: pytest.fail( "a worktree was made for a plan" ) )
    assert ft.main( argv, deps={ "planted_sha": sha } )[ "live" ] is False


def test_a_stage_whose_every_seed_was_unstrippable_fails_by_name_and_a_stage_with_no_need_and_an_unstrippable_seed_fails_by_name( monkeypatch ):
    tally = stage_parts.Tally()
    parts = { "make_need": None, "trace_fn": None, "prepare_fn": None, "index": None, "tally": tally }

    def unstrippable( count, report ):
        async def stage():
            for i in range( count ):
                tally[ "unstrippable_seed" ] += 1
                tally.skipped.append( { "seed": f"s{i}", "code": "STRIP_FAILED", "detail": "gone" } )
            return report
        return stage

    monkeypatch.setattr( stage_seeds, "load_lists", lambda path: LISTS_OF_TWO_AND_THREE )
    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: unstrippable( 2, { "stop": True } ) )
    monkeypatch.setattr( stage_seeds, "yield_stage", lambda path, prepare_fn, index: unstrippable( 1, { "seeds": 0 } ) )
    one, two = ft.stage_factories( "/lists.json", parts )
    with pytest.raises( er.NeedsetError ) as e: asyncio.run( one( "env" )() )
    assert e.value.code == er.ALL_SEEDS_UNREADABLE and "attribution" in str( e.value )
    with pytest.raises( er.NeedsetError ) as e: asyncio.run( two( "env" )() )
    assert e.value.code == er.NO_NEEDS_WITH_SKIPS and "yield" in str( e.value )


def test_the_source_worktree_is_locked_for_the_run_and_unlocked_after_a_result_and_after_any_error( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path )
    events    = []
    monkeypatch.setattr( ft.source_at, "ensure_worktree", lambda repo, commit: events.append( "made+locked" ) or "/WT" )
    monkeypatch.setattr( ft.source_at, "unlock", lambda repo, dest: events.append( f"unlock {repo} {dest}" ) )
    deps = { **live_deps( sha, lambda *a: asyncio.sleep( 0, {} ) ) }
    del deps[ "source_root" ]
    ft.main( [ *argv, "--live" ], deps=deps )
    assert events == [ "made+locked", "unlock /r /WT" ]                                                         # unlocked by the repo it was made from, not by the worktree's own path

    async def failing( *a ): raise RuntimeError( "the stage runner died" )

    events.clear()
    with pytest.raises( RuntimeError ): ft.main( [ *argv, "--live" ], deps={ **deps, "runner": failing } )
    assert events == [ "made+locked", "unlock /r /WT" ]
    events.clear()

    def no_context( root ): raise RuntimeError( "the context failed" )

    with pytest.raises( RuntimeError ): ft.main( [ *argv, "--live" ], deps={ **deps, "context": no_context } )
    assert events == [ "made+locked", "unlock /r /WT" ]


def test_a_stand_in_root_is_neither_locked_nor_unlocked( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path )
    monkeypatch.setattr( ft.source_at, "ensure_worktree", lambda *a: pytest.fail( "a worktree was made" ) )
    monkeypatch.setattr( ft.source_at, "unlock", lambda *a: pytest.fail( "a stand-in root was unlocked" ) )
    ft.main( [ *argv, "--live" ], deps=live_deps( sha, lambda *a: asyncio.sleep( 0, {} ) ) )


class Replying:
    """A stand-in for sdk_query that answers the drafter with one sentence and counts the calls."""

    def __init__( self ): self.calls = 0

    async def __call__( self, prompt, options ):
        from claude_agent_sdk import AssistantMessage, TextBlock
        self.calls += 1
        yield AssistantMessage( content=[ TextBlock( SENTENCE ) ], model=options.model )


def test_the_control_drafts_with_the_real_drafter_call_inside_a_running_loop_and_the_cap_files_its_calls_under_the_stage( tmp_path ):
    from cosa.repo.doc_lint import model_transport as mt
    transport = Replying()
    ledger    = draft.make_ledger( str( tmp_path / "l.jsonl" ), None, "max-plan" )
    cap       = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), 100, { "control": 5 } )
    ps        = [ real_pair( i ) for i in range( 3 ) ]
    own_text  = lambda rec: { **strip_of( rec ), "text": f"def {rec[ 'id' ].replace( '-', '_' )}(): pass" }       # a text of its own per pair, so the ledger answers none from another's reply

    async def inside_a_loop():
        with call_cap.stage( "control" ): return await ft.draft_control_needs( ps, lambda p: ft.control_job( p, own_text ), draft.drafter_call( query_fn=transport ), ledger, draft.draft_need )

    try:
        with cap.installed(): needs = asyncio.run( inside_a_loop() )
    finally:
        mt.set_charge_hook( None )
    assert needs == { p[ "rewrite" ][ "id" ]: SENTENCE for p in ps } and transport.calls == 3
    assert cap.by_stage() == { "control": 3 }                                                                  # carried across the thread, not filed unstaged


def test_the_real_drafter_call_still_refuses_to_run_in_a_running_loop_so_the_thread_is_what_makes_the_control_work( tmp_path ):
    async def inline():
        return draft.drafter_call( query_fn=Replying() )( "s", "u" )

    with pytest.raises( RuntimeError, match="running event loop" ): asyncio.run( inline() )


def test_a_stage_that_crashes_leaves_stage_reports_json_with_the_finished_stages_and_the_crash( tmp_path ):
    async def done(): return { "found": 5 }

    async def crash(): raise RuntimeError( "asyncio.run() cannot be called from a running event loop" )

    async def never(): pytest.fail( "a stage after the crash ran" )

    with pytest.raises( RuntimeError, match="running event loop" ): asyncio.run( ft.run_first_thousand( str( tmp_path ), done, done, crash, never ) )
    report = json.loads( ( tmp_path / ft.REPORT_FILE ).read_text( encoding="utf-8" ) )
    assert report[ "stages" ][ "attribution" ] == { "status": "done", "report": { "found": 5 } } and report[ "stages" ][ "yield" ][ "status" ] == "done"
    assert report[ "stages" ][ "control" ] == { "status": "failed", "code": "RuntimeError", "detail": "asyncio.run() cannot be called from a running event loop" }
    assert report[ "stages" ][ "remainder" ] == { "status": "not_run" } and report[ "used" ] == 0 and report[ "limit" ] == call_cap.CALL_LIMIT


def test_a_control_pair_is_tried_control_tries_times_and_the_drafter_is_told_so( tmp_path ):
    seen = []

    def draft_fn( job, ask, ledger, **kw ):
        seen.append( kw )
        return { "ok": True, "need": "n" }

    asyncio.run( ft.draft_control_needs( pairs()[ :2 ], lambda p: { "id": p[ "rewrite" ][ "id" ] }, None, None, draft_fn ) )
    assert ft.CONTROL_TRIES == 4 and ft.CONTROL_TRIES > draft.MAX_TRIES == 2
    assert seen == [ { "max_tries": 4 } ] * 2


def test_a_pair_that_never_drafts_is_handed_to_on_undrafted_and_left_out_while_the_others_go_on():
    def draft_fn( job, ask, ledger, **kw ): return { "ok": job[ "id" ] != "d-rew01", "need": f"n-{job[ 'id' ]}", "reason": "NEED_LEAKS_KEY", "tries": 4, "history": [ { "try": 0 } ] }

    gone  = []
    needs = asyncio.run( ft.draft_control_needs( pairs()[ :4 ], lambda p: { "id": p[ "rewrite" ][ "id" ] }, None, None, draft_fn, on_undrafted=lambda p, record: gone.append( ( p[ "rewrite" ][ "id" ], record[ "reason" ] ) ) ) )
    assert needs == { "d-rew00": "n-d-rew00", "d-rew02": "n-d-rew02", "d-rew03": "n-d-rew03" } and gone == [ ( "d-rew01", "NEED_LEAKS_KEY" ) ]


def test_the_control_runs_over_the_pairs_that_drafted_and_the_report_names_the_pair_left_out_and_why( monkeypatch ):
    ps, log = [ real_pair( i ) for i in range( 20 ) ], []
    ctx     = live_ctx()
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache, **kw: log.append( ( "planted", [ e[ "id" ] for e in entries ] ) ) or PLANTED )

    def draft_fn( job, ask, ledger, **kw ):
        if job[ "seed" ][ "id" ] == "d-orig01": return { "ok": False, "reason": "NEED_LEAKS_KEY", "tries": 4, "history": [ { "try": 0, "failures": [ "identifier" ], "words": [ "toolbar" ] } ] }
        return { "ok": True, "need": SENTENCE }

    def check( need, c, planted, entries ): return { "id": "r", "candidate_stage": { "ids": [ e[ "id" ] for e in entries ] + [ f"idx.{need[ 'seed' ]}" ], "widened_ids": [] }, "shortlist": [] }

    out = asyncio.run( ft.control_stage_live( ctx, ps, "ask", "L", strip_of, draft_fn, "CACHE", prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage )() )
    assert out[ "pairs" ] == 19 and out[ "found" ] == 19 and out[ "stop" ] is False and "d-rew01" not in log[ 0 ][ 1 ] and len( log[ 0 ][ 1 ] ) == 19
    assert out[ "undrafted" ] == [ { "pair": "d-rew01", "seed": "d-orig01", "reason": "NEED_LEAKS_KEY", "tries": 4, "history": [ { "try": 0, "failures": [ "identifier" ], "words": [ "toolbar" ] } ] } ]


def test_a_control_where_no_pair_drafts_still_fails_by_name_and_a_clean_one_reports_nothing_left_out( monkeypatch ):
    ps  = [ real_pair( i ) for i in range( 3 ) ]
    ctx = live_ctx()
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache, **kw: PLANTED )

    def leaking( job, ask, ledger, **kw ): return { "ok": False, "reason": "NEED_LEAKS_KEY", "tries": 4, "history": [] }

    def clean( job, ask, ledger, **kw ): return { "ok": True, "need": SENTENCE }

    def check( need, c, planted, entries ): return { "id": "r", "candidate_stage": { "ids": [ e[ "id" ] for e in entries ] + [ f"idx.{need[ 'seed' ]}" ], "widened_ids": [] }, "shortlist": [] }

    with pytest.raises( er.NeedsetError ) as e: asyncio.run( ft.control_stage_live( ctx, ps, "ask", "L", strip_of, leaking, "CACHE", prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage )() )
    assert e.value.code == er.CONTROL_NEED_UNDRAFTED and "none of the 3 pairs" in e.value.detail and "d-rew00" in e.value.detail
    out = asyncio.run( ft.control_stage_live( ctx, ps, "ask", "L", strip_of, clean, "CACHE", prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage )() )
    assert out[ "undrafted" ] == [] and out[ "pairs" ] == 3


def two_pass_control( monkeypatch, leaves_out ):
    """Run a two-pass control on fakes; leaves_out names the seeds each pass never drafts."""
    ps  = [ real_pair( i ) for i in range( 20 ) ]
    ctx = live_ctx()
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache, **kw: PLANTED )

    def draft_fn( job, ask, ledger, **kw ):
        if job[ "seed" ][ "id" ] in leaves_out[ ledger ]: return { "ok": False, "reason": "NEED_LEAKS_KEY", "tries": 4, "history": [] }
        return { "ok": True, "need": SENTENCE }

    def check( need, c, planted, entries ): return { "id": "r", "candidate_stage": { "ids": [ e[ "id" ] for e in entries ] + [ f"idx.{need[ 'seed' ]}" ], "widened_ids": [] }, "shortlist": [] }

    stage = ft.control_stage_live( ctx, ps, "ask", "L1", strip_of, draft_fn, "CACHE", prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage,
                                   passes=2, pass_resources=lambda n: ( "L2", "C2" ) )
    return asyncio.run( stage() )


def test_the_report_says_how_many_pairs_were_wanted_in_each_pass_and_at_the_top_so_a_short_run_cannot_read_as_complete( monkeypatch ):
    out = two_pass_control( monkeypatch, { "L1": { "d-orig01" }, "L2": { "d-orig01" } } )
    assert out[ "pairs_wanted" ] == 20 and [ p[ "pairs_wanted" ] for p in out[ "passes" ] ] == [ 20, 20 ]
    assert out[ "pairs" ] == 19 and out[ "found" ] == 19 and out[ "missed" ] == []                                  # the undrafted pair is neither found nor missed
    assert out[ "pairs" ] + len( out[ "undrafted" ] ) == out[ "pairs_wanted" ]


def test_pairs_wanted_is_in_the_report_of_a_control_the_budget_stopped_before_any_pass_finished( monkeypatch ):
    out = run_budget_control( monkeypatch, "L1" )
    assert out[ "passes" ] == [] and out[ "pairs_wanted" ] == 20


def test_consistent_compares_the_pairs_left_out_as_well_as_the_pairs_missed( monkeypatch ):
    same = two_pass_control( monkeypatch, { "L1": { "d-orig01" }, "L2": { "d-orig01" } } )
    assert same[ "consistent" ] is True
    differs = two_pass_control( monkeypatch, { "L1": { "d-orig01" }, "L2": { "d-orig02" } } )
    assert differs[ "consistent" ] is False and differs[ "passes" ][ 0 ][ "missed" ] == differs[ "passes" ][ 1 ][ "missed" ] == []
    one_less = two_pass_control( monkeypatch, { "L1": { "d-orig01" }, "L2": set() } )
    assert one_less[ "consistent" ] is False


def scored_world( tmp_path, monkeypatch, ids_of=None, shortlist_of=None, lines=None, without=( ), same_job=None, label_info=None, passes=1, bare_ids_of=None ):
    """
    Run the live control on fakes; return ( report, what planted_stage_for was given ).

    The live purpose store holds a line for the first original only, so the leak for the others is None.
    """
    ps        = [ real_pair( i ) for i in range( 20 ) ]
    live      = LiveStage( "live stage" )
    live.purposes_path = str( tmp_path / "live-purposes.jsonl" )
    ( tmp_path / "live-purposes.jsonl" ).write_text( json.dumps( { "pin": "pin00", "purpose": "Original line that tears down." } ) + "\n", encoding="utf-8" )
    ctx       = types.SimpleNamespace( candidate_stage=live, transport=None )
    given     = { "calls": [ ], "transports": [ ] }
    monkeypatch.setattr( ft, "planted_stage_for", lambda live_stage, entries, cache, **kw: given[ "calls" ].append( { "entries": entries, "cache": cache, "kw": kw } ) or PLANTED )

    def draft_fn( job, ask, ledger, **kw ): return { "ok": True, "need": SENTENCE }

    def check( need, c, planted, entries, **kw ):
        given[ "transports" ].append( type( c.transport ).__name__ )
        given.setdefault( "purposes", [ ] ).append( ( type( c.transport ).__name__, kw ) )
        arm = bare_ids_of if isinstance( c.transport, ft.RefusingTransport ) and bare_ids_of is not None else ids_of
        ids = [ e[ "id" ] for e in entries ] + [ f"idx.{need[ 'seed' ]}" ] if arm is None else arm( need, entries )
        return { "id": "r", "candidate_stage": { "ids": ids, "widened_ids": [] }, "shortlist": [ { "id": i } for i in ( ids if shortlist_of is None else shortlist_of( need, ids ) ) ] }

    stage = ft.control_stage_live( ctx, ps, "ask", "L1", strip_of, draft_fn, str( tmp_path / "cache" ), prepare=lambda c: ( set(), live_pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage,
                                   passes=passes, pass_resources=lambda n: ( "L2", str( tmp_path / f"cache-pass{n + 1}" ) ), plant_lines=lines, plant_without=without, same_job=same_job, label_info=label_info )
    return asyncio.run( stage() ), given


def test_the_scored_control_gives_each_plant_its_line_through_a_merged_store_and_a_row_per_pair_with_the_leak_beside_the_original( monkeypatch, tmp_path ):
    pin   = planted_pool.planted_entry( real_pair( 0 )[ "rewrite" ] )[ "pin" ]
    out, given = scored_world( tmp_path, monkeypatch, lines={ pin: "Does the plant's work." }, without=[ "d-rew01" ], label_info={ "answer_key_sha": "k" } )
    live_call, bare_call = given[ "calls" ]
    assert live_call[ "kw" ][ "purposes" ] == { pin: "Does the plant's work." } and live_call[ "kw" ][ "purposes_file" ] == f"{tmp_path}/cache-purposes.jsonl"
    assert bare_call[ "cache" ] == f"{tmp_path}/cache-bare" and bare_call[ "kw" ] == { }, "the bare stage is built with no purpose line at all"
    merged = [ json.loads( line ) for line in pathlib.Path( live_call[ "kw" ][ "purposes_file" ] ).read_text( encoding="utf-8" ).splitlines() ]
    assert merged == [ { "pin": "pin00", "purpose": "Original line that tears down." }, { "pin": pin, "purpose": "Does the plant's work." } ], "the live lines first, then the plants', and the live store is only read"
    assert out[ "purpose_lines_used" ] == 1 and out[ "plants_without_line" ] == [ "d-rew01" ] and out[ "labels" ] == { "answer_key_sha": "k" }
    assert all( kw == { "purposes": { pin: "Does the plant's work." } } for name, kw in given[ "purposes" ] if name != "RefusingTransport" ) and len( given[ "purposes" ] ) > 20, "the live check judges the plant with its line"
    assert all( kw == { } for name, kw in given[ "purposes" ] if name == "RefusingTransport" ), "the bare check judges the plant with no line at all"
    first = out[ "rows" ][ 0 ]
    assert len( out[ "rows" ] ) == 20 and first[ "purpose_line" ] == "Does the plant's work." and first[ "original" ][ "id" ] == "idx.d-orig00" and first[ "leak" ][ "original" ] == control_report.word_overlap( SENTENCE, "Original line that tears down." )
    assert out[ "rows" ][ 1 ][ "purpose_line" ] is None and out[ "rows" ][ 1 ][ "leak" ] == { "plant": None, "original": None }
    assert out[ "primary" ][ "drafted" ] == 20 and out[ "primary" ][ "retrieval" ][ "k" ] == 20 and out[ "stop" ] is False and out[ "found" ] == 20


def test_the_scored_control_without_lines_plants_bare_and_treats_every_pair_as_the_same_job_unless_labelled( monkeypatch, tmp_path ):
    out, given = scored_world( tmp_path, monkeypatch )
    assert given[ "calls" ][ 0 ][ "kw" ] == { "purposes": None, "purposes_file": None } and out[ "purpose_lines_used" ] == 0 and out[ "primary" ][ "drafted" ] == 20 and out[ "secondary" ][ "drafted" ] == 0
    labelled, _ = scored_world( tmp_path, monkeypatch, same_job={ f"d-rew{i:02d}": i >= 5 for i in range( 20 ) } )
    assert labelled[ "primary" ][ "drafted" ] == 15 and labelled[ "secondary" ][ "drafted" ] == 5 and labelled[ "false_positives" ] == 5, "the five not-the-same-job plants the fake judge accepted are false positives"


def test_a_plant_the_checker_misses_is_scored_and_listed_but_never_stops_the_run_while_the_originals_are_found( monkeypatch, tmp_path ):
    blind = lambda need, entries: [ f"idx.{need[ 'seed' ]}" ]
    out, _ = scored_world( tmp_path, monkeypatch, ids_of=blind )
    assert out[ "found" ] == 0 and len( out[ "missed" ] ) == 20 and out[ "primary" ][ "retrieval" ][ "k" ] == 0 and out[ "primary" ][ "pass_mark" ] == { "a": 20, "b": 0, "n": 20, "slack": 2, "passed": False }
    assert out[ "stop" ] is False and out[ "originals" ] == control_report.count( 20, 20 )


def test_a_control_whose_originals_are_all_missed_still_does_not_stop_and_reports_their_rate_beside_the_attribution_figure( monkeypatch, tmp_path ):
    out, _ = scored_world( tmp_path, monkeypatch, ids_of=lambda need, entries: [ e[ "id" ] for e in entries ] )
    assert out[ "found" ] == 20 and out[ "stop" ] is False and out[ "originals" ] == control_report.count( 0, 20 ) and out[ "attribution" ] == control_report.count( 27, 37 )
    assert out[ "primary" ][ "pass_mark" ][ "b" ] == 20 and out[ "primary" ][ "pass_mark" ][ "passed" ] is True, "the plants beat the originals, so the paired mark holds"


def test_the_bare_arm_is_checked_on_a_transport_that_refuses_every_model_request_and_its_figure_sits_beside_the_lines( monkeypatch, tmp_path ):
    only_originals = lambda need, entries: [ f"idx.{need[ 'seed' ]}" ]
    out, given = scored_world( tmp_path, monkeypatch, bare_ids_of=only_originals )
    assert given[ "transports" ] == [ "NoneType", "RefusingTransport" ] * 20, "the live check keeps the context's own transport and the bare one is refused"
    assert out[ "primary" ][ "retrieval" ] == control_report.count( 20, 20 ) and out[ "primary" ][ "retrieval_bare" ] == control_report.count( 0, 20 )
    assert all( r[ "plant" ][ "retrieved" ] and not r[ "plant_bare" ][ "retrieved" ] for r in out[ "rows" ] ) and out[ "stop" ] is False


def test_the_refusing_transport_raises_on_every_post_counts_the_refusals_and_sends_nothing():
    transport = ft.RefusingTransport()
    for n in range( 2 ):
        with pytest.raises( ft.NoModelCall, match="no model call" ): transport.post_with_meta( { "state": { "need": f"n{n}" } } )
    assert len( transport.refused ) == 2 and transport.calls == 0


def test_the_original_is_found_by_file_and_name_and_the_pair_is_refused_before_any_check_when_its_id_is_an_index_id_or_it_is_not_there():
    ps    = [ real_pair( i ) for i in range( 3 ) ]
    found = ft.original_entries( ps, live_pool(), { "pin01": "A stored line." } )
    assert found == { "d-rew00": { "id": "idx.d-orig00", "line": None }, "d-rew01": { "id": "idx.d-orig01", "line": "A stored line." }, "d-rew02": { "id": "idx.d-orig02", "line": None } }
    with pytest.raises( er.NeedsetError ) as excluded: ft.original_entries( ps, pool(), { } )
    assert excluded.value.code == er.CONTROL_ORIGINAL_EXCLUDED and "d-orig00" in excluded.value.detail and "leave it out" in excluded.value.detail
    gone = [ r for r in live_pool() if r[ "name" ] != ps[ 1 ][ "original" ][ "name" ] ]
    with pytest.raises( er.NeedsetError ) as missing: ft.original_entries( ps, gone, { } )
    assert missing.value.code == er.CONTROL_ORIGINAL_UNRESOLVED and "d-orig01" in missing.value.detail


def test_a_control_with_an_original_the_index_would_leave_out_stops_by_name_before_the_first_plant_is_checked( monkeypatch, tmp_path ):
    checked = [ ]
    monkeypatch.setattr( ft, "planted_stage_for", lambda live_stage, entries, cache, **kw: PLANTED )
    ps = [ real_pair( i ) for i in range( 3 ) ]

    def check( need, c, planted, entries ):
        checked.append( need[ "seed" ] )
        return { "id": "r", "candidate_stage": { "ids": [ ], "widened_ids": [ ] }, "shortlist": [ ] }

    stage = ft.control_stage_live( live_ctx(), ps, "ask", "L", strip_of, lambda job, ask, ledger, **kw: { "ok": True, "need": SENTENCE }, "CACHE", prepare=lambda c: ( set(), pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage )
    with pytest.raises( er.NeedsetError ) as caught: asyncio.run( stage() )
    assert caught.value.code == er.CONTROL_ORIGINAL_EXCLUDED and checked == [ ], "no plant was checked, so no judge call could be spent on a control that cannot read the originals"


def test_the_judge_figure_counts_a_plant_only_when_the_judge_rated_it_relevant_and_two_passes_each_carry_a_pass_mark( monkeypatch, tmp_path ):
    only_orig = lambda need, ids: [ f"idx.{need[ 'seed' ]}" ]
    out, _ = scored_world( tmp_path, monkeypatch, shortlist_of=only_orig, passes=2 )
    assert out[ "passes" ][ 0 ][ "primary" ][ "retrieval" ][ "k" ] == 20 and out[ "passes" ][ 0 ][ "primary" ][ "judge" ] == control_report.count( 0, 20 ) and out[ "pass_marks" ] == [ True, True ]
    assert out[ "passes" ][ 0 ][ "primary" ][ "originals_retrieved" ][ "k" ] == 20 and out[ "stop" ] is False


def test_the_ask_tells_an_observer_about_each_pair_after_the_check_and_before_the_ids_are_read():
    seen = []
    ask  = ft.control_ask( { "d-rew00": SENTENCE }, lambda need, planted: { "id": "r", "candidate_stage": { "ids": [ "d-rew00" ], "widened_ids": [] } }, loss_trace_ids, observe=lambda pair, need, receipt: seen.append( ( pair[ "rewrite" ][ "id" ], need[ "need" ], receipt[ "id" ] ) ) )
    assert asyncio.run( ask( "planted", real_pair( 0 ) ) ) == [ "d-rew00" ] and seen == [ ( "d-rew00", SENTENCE, "r" ) ]


def loss_trace_ids( receipt ):
    """Return the ids the stand-in candidate stage sent to the judge."""
    return receipt[ "candidate_stage" ][ "ids" ]


def test_the_command_line_takes_an_optional_purpose_store_for_the_plants( tmp_path ):
    argv, _ = run_dir_files( tmp_path )
    assert ft.parse_args( argv ).plant_purposes is None and ft.parse_args( [ *argv, "--plant-purposes", "/p/purpose.jsonl" ] ).plant_purposes == "/p/purpose.jsonl"


def test_a_live_run_settles_the_labels_from_the_label_files_and_builds_the_live_control_from_them( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path )
    seen      = {}
    monkeypatch.setattr( ft.control_report, "same_job_labels", lambda pairs, labels_dir, key: seen.update( labels=( len( pairs ), labels_dir, key ) ) or "LABELLED" )

    def live_control( args, labelled ):
        seen[ "labelled" ] = labelled
        return lambda c, ps, ask, ledger, strip_fn, draft_fn, cache: lambda: asyncio.sleep( 0, { "control": True } )

    async def runner( run_dir, one, two, control, rem, limit ): return { "control": await control() }

    monkeypatch.setattr( ft, "live_control", live_control )
    deps = live_deps( sha, runner )
    del deps[ "control" ]
    out  = ft.main( [ *argv, "--live" ], deps=deps )
    args = ft.parse_args( argv )
    assert out[ "report" ] == { "control": { "control": True } } and seen[ "labelled" ] == "LABELLED" and seen[ "labels" ] == ( 20, args.labels_dir, args.answer_key )
