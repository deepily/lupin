#!/usr/bin/env python3
"""
duplicate_check_self_consistency: the sample, the comparison and the guarded live run.

Venue: :7999-eligible / local, pure. Every file is built under tmp_path, and the worktree, the judge and the lock are replaced, so no model call is made.
"""
import contextlib
import datetime
import io
import json
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.repo import code_health_settings as chs
from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import duplicate_check_history as history
from lupin_mcp import duplicate_check_self_consistency as sc
from lupin_mcp import duplicate_check_status as dcs

OPUS, FABLE = "model-a", "model-b"
NOW         = datetime.datetime( 2026, 11, 14, 12, 0, tzinfo=datetime.timezone.utc )


def manifest( folder, lines ):
    ( folder / daily.MANIFEST ).write_text( "".join( json.dumps( l ) + "\n" for l in lines ), encoding="utf-8" )


def line( i, model=OPUS, run="run-1.json", **extra ):
    return { "id": f"d-{i}", "file": "f.py", "run_file": run, "model_id": model, "config_sha": "x", "time": "2026-11-14T10:00:00-05:00", **extra }


def rows( slot_flags ):
    return [ { "id": i, "candidate": f"c-{i}-{k}", "verdict": v } for i, verdicts in slot_flags.items() for k, v in enumerate( verdicts ) ]


def test_own_lines_keep_the_last_self_ruled_line_of_each_definition(tmp_path):
    manifest( tmp_path, [ line( 1, run="a.json" ), line( 1, run="b.json" ), line( 2, model=FABLE ), line( 3, model=f"{OPUS}", reused_from_model=OPUS ), line( 4 ) ] )
    got = sc.own_lines( tmp_path, OPUS )
    assert sorted( got ) == [ "d-1", "d-4" ] and got[ "d-1" ][ "run_file" ] == "b.json"
    assert sc.own_lines( tmp_path / "nowhere", OPUS ) == {}


def test_the_sample_is_repeatable_bounded_by_what_exists_and_grouped_by_run(tmp_path):
    manifest( tmp_path, [ line( i, run="a.json" if i < 5 else "b.json" ) for i in range( 10 ) ] )
    one = sc.sample_ids( tmp_path, OPUS, 4, 7 )
    assert one == sc.sample_ids( tmp_path, OPUS, 4, 7 ) and len( one ) == 4 and one == sorted( one )
    assert len( sc.sample_ids( tmp_path, OPUS, 50, 1 ) ) == 10
    groups = sc.runs_of( tmp_path, OPUS, [ "d-7", "d-1", "d-3" ] )
    assert groups == { "a.json": [ "d-1", "d-3" ], "b.json": [ "d-7" ] } and list( groups ) == [ "a.json", "b.json" ]


def test_flags_by_definition_and_by_pair():
    r = rows( { "d-1": [ "distinct", "near_duplicate" ], "d-2": [ "related", "distinct" ], "d-3": [ "duplicate" ] } )
    assert sc.flagged_by_definition( r ) == { "d-1": True, "d-2": False, "d-3": True }
    assert sc.flagged_pairs( r ) == { ( "d-1", "c-d-1-1" ), ( "d-3", "c-d-3-0" ) }
    assert sc.flagged_by_definition( [] ) == {}


def test_compare_counts_the_four_cells_and_the_statistics():
    first  = { "d-1": True, "d-2": True, "d-3": False, "d-4": False, "d-5": True, "d-9": True }
    second = { "d-1": True, "d-2": False, "d-3": False, "d-4": True, "d-5": True }
    got = sc.compare( first, second )
    assert ( got[ "definitions" ], got[ "both" ], got[ "first_only" ], got[ "second_only" ], got[ "neither" ] ) == ( 5, 2, 1, 1, 1 )
    assert got[ "agreement" ] == pytest.approx( 0.6 )
    assert got[ "kappa" ] == pytest.approx( 0.1666667, abs=1e-6 )
    assert got[ "mcnemar_p" ] == 1.0


def test_compare_gives_none_when_nothing_overlaps_or_chance_is_certain():
    empty = sc.compare( { "d-1": True }, { "d-2": True } )
    assert empty[ "definitions" ] == 0 and empty[ "agreement" ] is None and empty[ "kappa" ] is None
    same = sc.compare( { "d-1": True, "d-2": True }, { "d-1": True, "d-2": True } )
    assert same[ "agreement" ] == 1.0 and same[ "kappa" ] is None


def test_render_a_plan_makes_no_claim_of_calls_made():
    text = sc.render( OPUS, 30, 5, { "a.json": [ "d-1", "d-2" ] } )
    assert "Sample of 2 definitions (asked for 30, seed 5)" in text and "| a.json | 2 |" in text
    assert "Plan only: no model call was made. The second pass may make up to 2 calls" in text


def test_render_a_live_result_reports_the_comparison_the_calls_and_the_ids_left_out():
    first  = rows( { "d-1": [ "duplicate" ], "d-2": [ "distinct" ] } )
    second = rows( { "d-1": [ "duplicate" ], "d-2": [ "near_duplicate" ] } )
    text   = sc.render( OPUS, 30, 5, { "a.json": [ "d-1", "d-2", "d-3" ] }, ( first, second, [ "d-3" ], 4 ) )
    assert "| 2 | 1 | 0 | 1 | 0 | 0.500 |" in text
    assert "Flagged pairs: 1 both times, 0 first pass only, 1 second pass only." in text and "Model calls made: 4." in text
    assert "Left out, because a pass could not be replayed or judged: d-3" in text
    none = sc.render( OPUS, 30, 5, { "a.json": [ "d-1" ] }, ( [], [], [], 0 ) )
    assert "n/a" in none and "Left out" not in none


class Backend:
    server_label = "fake"


def patch_live( monkeypatch, judge_all, released, ensured=None, listed="c1 c2" ):
    monkeypatch.setattr( daily, "git", lambda root, *a: listed )
    monkeypatch.setattr( daily.source_at, "ensure_worktree", lambda root, end, target: ( ensured.append( ( end, target.name ) ) if ensured is not None else None ) or target )
    monkeypatch.setattr( daily, "new_definitions", lambda tree, root, window: { "defs": [ { "id": "d-1" }, { "id": "d-2" }, { "id": "d-other" } ] } )
    monkeypatch.setattr( daily, "pool_without_earlier_versions", lambda tree, fresh: [ { "id": "p-1" } ] )
    monkeypatch.setattr( daily, "release", lambda root, tree: released.append( tree ) )
    monkeypatch.setattr( sc.proof_cli, "daily_ledger", lambda *a: "ledger" )
    monkeypatch.setattr( sc.proof_cli, "base_wiring", lambda *a: { "wired": True } )
    monkeypatch.setattr( sc.pipeline, "judge_all", judge_all )


PARTS = { "verify": lambda: { "model_id": OPUS }, "backend": Backend(), "data_dir": "data", "structural": lambda tree, cfg: [], "client": object() }
DOC   = { "window": { "start": "aaa", "end": "bbbbbbbbbbbb", "commits": 2 } }


def test_rejudge_run_replays_slot_0_with_no_call_and_judges_slot_1(tmp_path, monkeypatch):
    seen, released, ensured = [], [], []
    def judge_all( wanted, everyone, cfg, wiring, slot, max_calls=None, skip_breaching=False ):
        seen.append( ( slot, max_calls, [ d[ "id" ] for d in wanted ], [ d[ "id" ] for d in everyone ], skip_breaching, wiring[ "redact_tools" ] ) )
        return { "verdicts": [ { "id": "d-1", "candidate": "x", "verdict": "related" } ], "unjudged": [ { "id": "d-2", "code": "JUDGE_CAP_REACHED" } ] if slot == 1 else [] }
    patch_live( monkeypatch, judge_all, released, ensured )
    first, second, missing, calls = sc.rejudge_run( str( tmp_path ), DOC, [ "d-1", "d-2", "d-gone" ], PARTS, "cli", 2, 4 )
    assert seen == [ ( 0, 0, [ "d-1", "d-2" ], [ "d-1", "d-2", "d-other", "p-1" ], True, True ), ( 1, 2, [ "d-1", "d-2" ], [ "d-1", "d-2", "d-other", "p-1" ], True, True ) ]
    assert missing == [ "d-2", "d-gone" ] and calls == 0 and len( first ) == len( second ) == 1
    assert ensured == [ ( "bbbbbbbbbbbb", "self-consistency-bbbbbbbbb" ) ] and len( released ) == 1


def test_rejudge_run_removes_its_worktree_when_the_judge_raises_and_reads_an_empty_commit_list(tmp_path, monkeypatch):
    released = []
    def judge_all( *a, **k ): raise RuntimeError( "judge down" )
    patch_live( monkeypatch, judge_all, released, listed="" )
    with pytest.raises( RuntimeError, match="judge down" ): sc.rejudge_run( str( tmp_path ), DOC, [ "d-1" ], PARTS, "cli", 1, 1 )
    assert len( released ) == 1


@contextlib.contextmanager
def lock( held ):
    yield held


def test_live_run_bounds_each_run_by_the_calls_left_and_writes_a_history_line(tmp_path, monkeypatch):
    for name in ( "a.json", "b.json" ): ( tmp_path / name ).write_text( json.dumps( DOC ), encoding="utf-8" )
    caps = []
    def fake( root, doc, ids, parts, cli, cap, parallel ):
        caps.append( ( ids, cap ) )
        return [ { "id": ids[ 0 ] } ], [ { "id": ids[ 0 ] } ], [ "gone" ], cap
    monkeypatch.setattr( sc, "rejudge_run", fake )
    monkeypatch.setattr( daily, "run_lock", lambda data: lock( True ) )
    monkeypatch.setattr( daily, "calls_left", lambda folder, parts, model, now: 5 )
    total = sc.live_run( "root", tmp_path, OPUS, { "a.json": [ "d-1", "d-2", "d-3" ], "b.json": [ "d-4", "d-5" ] }, { "data_dir": "d" }, "cli", 2, NOW )
    assert caps == [ ( [ "d-1", "d-2", "d-3" ], 3 ), ( [ "d-4", "d-5" ], 2 ) ]
    assert len( total[ 0 ] ) == 2 and total[ 2 ] == [ "gone", "gone" ] and total[ 3 ] == 5
    lines = history.read_lines( tmp_path )
    assert lines[ -1 ][ "mode" ] == sc.MODE and lines[ -1 ][ "judge_calls" ] == 5 and lines[ -1 ][ "judge_model" ] == OPUS
    assert history.calls_on( lines, NOW.date().isoformat(), OPUS ) == 5


def test_live_run_refuses_when_the_lock_is_held_and_makes_no_call(tmp_path, monkeypatch):
    monkeypatch.setattr( daily, "run_lock", lambda data: lock( False ) )
    monkeypatch.setattr( sc, "rejudge_run", lambda *a: pytest.fail( "no call may be made" ) )
    with pytest.raises( RuntimeError, match="run lock" ): sc.live_run( "root", tmp_path, OPUS, { "a.json": [ "d-1" ] }, { "data_dir": "d" }, "cli", 1, NOW )
    assert history.read_lines( tmp_path ) == []


def run_main( argv, **kw ):
    out = io.StringIO()
    return sc.main( argv, out=out, now=NOW, **kw ), out.getvalue()


def test_main_without_go_prints_the_plan_and_makes_no_call(tmp_path):
    manifest( tmp_path, [ line( i ) for i in range( 4 ) ] )
    code, text = run_main( [ "--model", OPUS, "--check-dir", str( tmp_path ), "--size", "3", "--seed", "1" ], run=lambda *a: pytest.fail( "no call" ) )
    assert code == 0 and "Plan only" in text and "seed 1" in text


def test_main_takes_the_week_seed_the_model_and_the_folder_from_the_date_the_ini_and_the_root(tmp_path, monkeypatch):
    manifest( tmp_path, [ line( 1 ) ] )
    class Config:
        def get_required( self, key, silent=False ):
            assert key == chs.JUDGE_MODEL_KEY
            return OPUS
    monkeypatch.setattr( dcs, "folder_of", lambda root: tmp_path )
    code, text = run_main( [], config=Config() )
    assert code == 0 and "seed 20261114" in text and f"self-consistency: {OPUS}" in text


def test_main_with_go_runs_the_live_step_and_prints_the_comparison(tmp_path):
    manifest( tmp_path, [ line( 1 ), line( 2 ) ] )
    seen = {}
    def run( root, folder, model, groups, parts, cli, parallel, when ):
        seen.update( groups=groups, cli=cli, parts=parts, when=when )
        return rows( { "d-1": [ "duplicate" ] } ), rows( { "d-1": [ "duplicate" ] } ), [], 2
    code, text = run_main( [ "--model", OPUS, "--check-dir", str( tmp_path ), "--go", "--claude-cli-path", "/bin/claude" ], run=run, parts={ "p": 1 } )
    assert code == 0 and "Model calls made: 2." in text and "Plan only" not in text
    assert seen[ "groups" ] == { "run-1.json": [ "d-1", "d-2" ] } and seen[ "cli" ] == "/bin/claude" and seen[ "parts" ] == { "p": 1 } and seen[ "when" ] == NOW


def test_main_builds_the_live_parts_only_when_it_has_to(tmp_path, monkeypatch):
    manifest( tmp_path, [ line( 1 ) ] )
    monkeypatch.setattr( daily, "live_parts", lambda: { "built": True } )
    got = []
    run_main( [ "--model", OPUS, "--check-dir", str( tmp_path ), "--go", "--claude-cli-path", "c" ], run=lambda *a: got.append( a[ 4 ] ) or ( [], [], [], 0 ) )
    assert got == [ { "built": True } ]


@pytest.mark.parametrize( "argv, reason", [
    ( [ "--go" ], "--go needs --claude-cli-path" ),
    ( [ "--check-dir", "EMPTY" ], "names no definition" ),
] )
def test_main_refuses_with_exit_3_and_names_the_reason( tmp_path, argv, reason ):
    argv = [ str( tmp_path ) if a == "EMPTY" else a for a in argv ]
    code, text = run_main( [ "--model", OPUS, *( [ "--check-dir", str( tmp_path ) ] if "--check-dir" not in argv else [] ), *argv ] )
    assert code == sc.EXIT_NOT_MADE and "REFUSING:" in text and reason in text and "Nothing was made." in text


def test_main_refuses_when_the_budget_is_spent_or_the_lock_is_held(tmp_path):
    manifest( tmp_path, [ line( 1 ) ] )
    def spent( *a ): raise daily.SpendRefused( "the daily call budget is spent" )
    code, text = run_main( [ "--model", OPUS, "--check-dir", str( tmp_path ), "--go", "--claude-cli-path", "c" ], run=spent, parts={} )
    assert code == sc.EXIT_NOT_MADE and "SpendRefused" in text


def test_rejudge_run_takes_every_definition_of_the_tree_for_a_baseline_run(tmp_path, monkeypatch):
    released, seen = [], []
    patch_live( monkeypatch, lambda wanted, everyone, cfg, wiring, slot, max_calls=None, skip_breaching=False: seen.append( [ d[ "id" ] for d in wanted ] ) or { "verdicts": [], "unjudged": [] }, released )
    monkeypatch.setattr( daily, "git", lambda *a: pytest.fail( "a baseline run has no commit list to read" ) )
    monkeypatch.setattr( daily, "new_definitions", lambda *a: pytest.fail( "a baseline run does not ask for the window's new definitions" ) )
    monkeypatch.setattr( daily, "baseline_definitions", lambda tree, window: { "defs": [ { "id": "d-1" }, { "id": "d-9" } ] } )
    _first, _second, missing, _calls = sc.rejudge_run( str( tmp_path ), { **DOC, "mode": "baseline" }, [ "d-1", "d-2" ], PARTS, "cli", 2, 1 )
    assert seen == [ [ "d-1" ], [ "d-1" ] ] and missing == [ "d-2" ] and len( released ) == 1


def test_second_pass_writes_its_history_line_even_when_a_later_run_file_raises(tmp_path, monkeypatch):
    for name in ( "a.json", "b.json" ): ( tmp_path / name ).write_text( json.dumps( DOC ), encoding="utf-8" )
    def fake( root, doc, ids, parts, cli, cap, parallel ):
        if ids == [ "d-2" ]: raise RuntimeError( "the second run file broke" )
        return [], [], [], 3
    monkeypatch.setattr( sc, "rejudge_run", fake )
    monkeypatch.setattr( daily, "calls_left", lambda folder, parts, model, now: 10 )
    with pytest.raises( RuntimeError, match="second run file broke" ): sc.second_pass( "root", tmp_path, OPUS, { "a.json": [ "d-1" ], "b.json": [ "d-2" ] }, {}, "cli", 1, NOW )
    last = history.read_lines( tmp_path )[ -1 ]
    assert last[ "mode" ] == sc.MODE and last[ "status" ] == "failed" and last[ "judge_calls" ] == 3
    assert history.calls_on( history.read_lines( tmp_path ), NOW.date().isoformat(), OPUS ) == 3
