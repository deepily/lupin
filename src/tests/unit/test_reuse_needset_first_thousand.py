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
from lupin_mcp.reuse_needset import call_cap, draft, first_thousand as ft, smoke, planted_pool, positive_control as pc, stage_parts, stage_seeds, stages
from lupin_mcp.reuse_needset import errors as er
from tests.unit.test_reuse_needset_positive_control import pairs as bare_pairs, pool


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
    assert out[ "unsure_flagged" ] == { "total": 2, "resolved": 1, "of": 20, "also_drifted": 1, "text": "2 of 20, with 1 also drifted" } and out[ "seed" ] == 7 and out[ "pairs" ] == 20


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
    ft.planted_stage_for( live, [ { "id": "d-rew00" } ], cache, embed_rows=lambda entries, client: ( "rows", client ), load_vectors=lambda folder: ( "base", folder ) )
    assert seen[ "planted" ] == ( ( "base", "/v" ), [ "d-rew00" ], ( "rows", "client" ) ) and seen[ "vectors_dir" ] == "/v" and seen[ "cache" ] == str( cache ) and seen[ "client" ] == "client"
    assert cache.is_dir() and seen[ "cache" ] != "/q"
    assert seen[ "kw" ] == { "purposes_path": "/p", "K": 9, "arm": "B1", "fusion": None } and "refresher" not in seen[ "kw" ]


def test_the_live_control_drafts_first_then_plants_and_the_calls_are_the_drafters_only( monkeypatch, tmp_path ):
    ps      = [ real_pair( i ) for i in range( 20 ) ]
    log     = []
    ctx     = types.SimpleNamespace( candidate_stage="live stage" )
    monkeypatch.setattr( ft, "planted_stage_for", lambda live, entries, cache: log.append( ( "stage", live, len( entries ), cache ) ) or "planted stage" )

    def draft_fn( job, ask, ledger ):
        log.append( ( "draft", job[ "seed" ][ "id" ] ) )
        return { "ok": True, "need": SENTENCE }

    def check( need, c, planted, entries ):
        log.append( ( "check", need[ "seed" ], planted ) )
        return { "id": "r", "candidate_stage": { "ids": [ e[ "id" ] for e in entries ], "widened_ids": [] } }

    stage = ft.control_stage_live( ctx, ps, "ask", "ledger", strip_of, draft_fn, "CACHE", prepare=lambda c: ( set(), pool(), "sha", "gen" ), check=check, build_stage=cs.build_stage )
    out   = asyncio.run( stage() )
    kinds = [ k[ 0 ] for k in log ]
    assert kinds == [ "draft" ] * 20 + [ "stage" ] + [ "check" ] * 20 and log[ 20 ] == ( "stage", "live stage", 20, "CACHE" ) and out[ "found" ] == 20 and out[ "stop" ] is False
    assert all( k[ 2 ] == "planted stage" for k in log[ 21: ] ) and [ k[ 1 ] for k in log[ 21: ] ] == [ p[ "original" ][ "id" ] for p in ps ]


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

    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: seen.update( a=( path, make_need, trace_fn ) ) or stage_of( { "seeds": 1 } ) )
    monkeypatch.setattr( stage_seeds, "yield_stage", lambda path, prepare_fn, index: seen.update( y=( path, prepare_fn, index ) ) or stage_of( { "hard": 2 } ) )
    one, two = ft.stage_factories( "/lists.json", parts )
    counts   = { "not_pooled": 0, "no_partner": 0, "draft_failed": 0, "disputed": 2, "disputed_ids": [ "n-1" ] }
    assert asyncio.run( one( "env" )() ) == { "seeds": 1, "no_final_need": counts } and asyncio.run( two( "env" )() ) == { "hard": 2, "no_final_need": { **counts, "disputed_ids": [ "n-1" ] } }
    assert seen == { "a": ( "/lists.json", "MN", "TF" ), "y": ( "/lists.json", "PF", "IX" ) }


def test_the_yield_report_counts_only_the_yield_seeds_and_not_the_attribution_ones( monkeypatch ):
    tally = stage_parts.Tally()
    parts = { "make_need": None, "trace_fn": None, "prepare_fn": None, "index": None, "tally": tally }

    def stage_that( reason, ids ):
        async def stage():
            tally[ reason ] += len( ids )
            tally.ids.extend( ids )
            return {}
        return stage

    monkeypatch.setattr( stage_seeds, "attribution_stage", lambda path, make_need, trace_fn: stage_that( "disputed", [ "n-a1", "n-a2" ] ) )
    monkeypatch.setattr( stage_seeds, "yield_stage", lambda path, prepare_fn, index: stage_that( "draft_failed", [] ) )
    one, two = ft.stage_factories( "/lists.json", parts )
    first    = asyncio.run( one( "env" )() )[ "no_final_need" ]
    second   = asyncio.run( two( "env" )() )[ "no_final_need" ]
    assert first == { "not_pooled": 0, "no_partner": 0, "draft_failed": 0, "disputed": 2, "disputed_ids": [ "n-a1", "n-a2" ] }
    assert second == { "not_pooled": 0, "no_partner": 0, "draft_failed": 0, "disputed": 0, "disputed_ids": [] }


def test_the_live_parts_use_their_own_ledgers_in_the_run_folder_and_the_arguments_models( tmp_path, monkeypatch ):
    seen = {}
    args = types.SimpleNamespace( run_dir=str( tmp_path ), cli_path=None, server="max-plan", second_model="M2", probe_model="MP" )
    env  = types.SimpleNamespace( ask="DRAFT-ASK" )
    monkeypatch.setattr( draft, "drafter_call", lambda model=draft.DRAFTER_MODEL: f"ask-{model}" )

    def build( env_, built, lists, models, drafter, second, ledgers ):
        seen.update( env=env_, built=built, lists=lists, models=models, drafter=drafter, second=second, ledgers=ledgers )
        return "PARTS"

    assert ft.live_parts( args, env, "BUILT", "LISTS", build=build ) == "PARTS"
    assert seen[ "models" ] == { "second": "M2", "probe": "MP" } and seen[ "drafter" ] == "DRAFT-ASK" and seen[ "second" ] == "ask-M2" and seen[ "built" ] == "BUILT" and seen[ "lists" ] == "LISTS"
    paths = { k: pathlib.Path( v.ledger.path if hasattr( v, "ledger" ) else v.path ).name for k, v in seen[ "ledgers" ].items() }
    assert paths == { "draft": "ledger-stage-draft.jsonl", "second": "ledger-stage-second.jsonl", "trace": "ledger-trace.jsonl" }
    assert isinstance( seen[ "ledgers" ][ "draft" ], draft.SharedLedger ) and isinstance( seen[ "ledgers" ][ "second" ], draft.SharedLedger )


def run_dir_files( tmp_path ):
    """Write the proof's input files; return the command line and the planted sha."""
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
    return argv, hashlib.sha256( planted.read_bytes() ).hexdigest()


def test_the_command_line_needs_its_inputs_and_is_a_plan_unless_live_is_given():
    base = [ "--root", "/r", "--run-dir", "/d", "--planted", "p", "--answer-key", "k", "--labels-dir", "l", "--seed", "7", "--source-commit", "abc" ]
    a    = ft.parse_args( base )
    assert a.seed == 7 and a.limit == 1000 and a.live is False and a.cli_path is None and a.server == "max-plan" and a.second_model == a.probe_model == smoke.SECOND_MODEL and ft.parse_args( [ *base, "--live", "--limit", "5" ] ).live is True
    with pytest.raises( SystemExit ): ft.parse_args( base[ :-2 ] )


def test_without_live_main_plans_from_files_and_touches_nothing_else( tmp_path ):
    argv, sha = run_dir_files( tmp_path )
    boom      = lambda *a, **k: pytest.fail( "something live was touched" )
    out       = ft.main( argv, deps={ "planted_sha": sha, "context": boom, "factories": boom, "runner": boom, "ask": boom } )
    assert out[ "live" ] is False and out[ "plan" ][ "used" ] == 0 and out[ "plan" ][ "remaining" ] == 1000 and out[ "plan" ][ "pairs" ] == 20
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

    deps = { "planted_sha": sha, "parts": lambda args, env, built, lists: seen.update( parts_args=( args.server, env.server, built, lists[ "seed" ], lists[ "sha" ] ) ) or "PARTS", **seed_deps(), "factories": ( factory( "a" ), factory( "y" ) ), "context": lambda root: ctx, "runner": runner, "ask": "ASK", "ledger": lambda args: "LEDGER",
             "strip_fn": strip_of, "draft_fn": "DRAFT", "remainder": lambda ps, seed: { "per_pair": [], "seed": seed },
             "control": lambda c, ps, ask, ledger, strip_fn, draft_fn, cache: ( seen.update( control_args=( c, len( ps ), ask, ledger, strip_fn, draft_fn, cache ) ) or ( lambda: asyncio.sleep( 0, { "control": True } ) ) ) }
    out  = ft.main( [ *argv, "--live", "--limit", "9" ], deps=deps )
    env  = seen[ "a" ]
    assert out[ "live" ] is True and out[ "report" ] == { "ran": True } and seen[ "y" ] is env
    assert ( env.root, env.seed, env.source_commit, env.ctx, env.ask, env.draft_ledger ) == ( "/r", 7, "abc", ctx, "ASK", "LEDGER" ) and env.run_dir.endswith( "run" )
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
             "strip_fn": strip_of, "draft_fn": "D", "remainder": lambda ps, seed: { "per_pair": [], "seed": seed }, "control": lambda *a: ( lambda: asyncio.sleep( 0, {} ) ) }
    out  = ft.main( [ *argv, "--live" ], deps=deps )
    assert seen[ "parts" ] == "PARTS" and pathlib.Path( seen[ "path" ] ).name == stage_seeds.LISTS_FILE and pathlib.Path( seen[ "path" ] ).parent == tmp_path / "run"
    assert out[ "report" ] == { "stages": [ "one", "two" ] }


def test_a_live_run_over_other_seed_lists_stops_by_name_before_the_parts_are_built( tmp_path ):
    argv, sha = run_dir_files( tmp_path )
    base      = { "planted_sha": sha, "context": lambda root: types.SimpleNamespace( candidate_stage="live" ), "ask": "ASK", "ledger": lambda args: "L", "strip_fn": strip_of, "draft_fn": "D", "control": lambda *a: None,
                  "parts": lambda args, env, built, lists: "PARTS", "factories": ( lambda env: None, lambda env: None ), "runner": lambda *a: asyncio.sleep( 0, {} ), "remainder": lambda ps, seed: {} }
    ft.main( [ *argv, "--live" ], deps={ **base, **seed_deps() } )
    with pytest.raises( er.NeedsetError ) as e: ft.main( [ *argv, "--live" ], deps={ **base, **seed_deps( skip="ts-3" ), "parts": lambda *a: pytest.fail( "parts were built" ) } )
    assert e.value.code == er.PLAN_ALREADY_WRITTEN


def test_a_live_run_over_a_context_with_no_candidate_stage_stops_by_name_before_any_file_or_call( tmp_path, monkeypatch ):
    argv, sha = run_dir_files( tmp_path )
    monkeypatch.setattr( ft, "write_seed_lists", lambda *a, **k: pytest.fail( "a list was written" ) )
    deps = { "planted_sha": sha, "context": lambda root: types.SimpleNamespace( candidate_stage=None ), "ask": lambda *a: pytest.fail( "a model was called" ), "built": lambda args: pytest.fail( "the index was built" ) }
    with pytest.raises( er.NeedsetError ) as e: ft.main( [ *argv, "--live" ], deps=deps )
    assert e.value.code == er.NO_CANDIDATE_STAGE and all( v in str( e.value ) for v in ( "LUPIN_REUSE_JEV_PACK_SIZE", "LUPIN_REUSE_JEV_TOKEN_CEILING", "LUPIN_REUSE_JEV_RUN_NAME" ) )
    assert not ( tmp_path / "run" / "first-thousand-seeds.json" ).exists() and not ( tmp_path / "run" / ft.CALLS_FILE ).exists()
