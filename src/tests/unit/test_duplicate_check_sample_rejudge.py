#!/usr/bin/env python3
"""
duplicate_check_sample_rejudge: the sample, the corrected rate and the guarded live run.

Venue: :7999-eligible / local, pure. Files are built under tmp_path and the live step is replaced, so no model call is made.
"""
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

from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import duplicate_check_sample_rejudge as sr
from lupin_mcp import duplicate_check_status as dcs

OPUS, FABLE = "model-a", "model-b"
NOW         = datetime.datetime( 2026, 12, 14, 12, 0, tzinfo=datetime.timezone.utc )


def write_run( folder, name, pairs ):
    ( folder / name ).write_text( json.dumps( { "started_at": "2026-11-16T10:00:00-05:00", "pairs": pairs } ), encoding="utf-8" )


def manifest( folder, lines ):
    ( folder / daily.MANIFEST ).write_text( "".join( json.dumps( l ) + "\n" for l in lines ), encoding="utf-8" )


def line( i, run, model=OPUS, **extra ):
    return { "id": f"d-{i}", "file": "f.py", "run_file": run, "model_id": model, "time": "2026-11-16T10:00:00-05:00", **extra }


def verdict_rows( by_def ):
    return [ { "id": i, "candidate": f"c{k}", "verdict": "duplicate" if flag else "distinct" } for i, flags in by_def.items() for k, flag in enumerate( flags ) ]


def seeded_folder( tmp_path ):
    write_run( tmp_path, "2026-11-16-100000-cron.json", { OPUS: { "rows": 600, "flagged": 60 }, FABLE: { "rows": 9, "flagged": 9 } } )
    write_run( tmp_path, "2026-11-17-100000-cron.json", { OPUS: { "rows": 400, "flagged": 40 } } )
    write_run( tmp_path, "2026-11-10-100000-cron.json", None )
    manifest( tmp_path, [ line( 1, "2026-11-16-100000-cron.json" ), line( 2, "2026-11-16-100000-cron.json" ), line( 3, "2026-11-17-100000-cron.json" ), line( 4, "2026-11-17-100000-cron.json", reused_from_model=FABLE ),
                          line( 5, "2026-11-10-100000-cron.json" ), line( 6, "2026-11-17-100000-cron.json", model=FABLE ) ] )
    return tmp_path


def test_population_sums_only_the_models_own_pair_counts(tmp_path):
    folder = seeded_folder( tmp_path )
    assert sr.population_pairs( folder, OPUS, [] ) == ( 1000, 100, [ "2026-11-16-100000-cron.json", "2026-11-17-100000-cron.json" ] )
    assert sr.population_pairs( folder, "model-c", [] ) == ( 0, 0, [] )


def test_the_frame_holds_self_ruled_definitions_of_runs_with_pair_counts_and_the_draw_repeats(tmp_path):
    folder = seeded_folder( tmp_path )
    runs   = sr.population_pairs( folder, OPUS, [] )[ 2 ]
    frame  = sr.frame_ids( folder, OPUS, runs )
    assert frame == [ "d-1", "d-2", "d-3" ]
    assert sr.draw( frame, 2, 7 ) == sr.draw( frame[ ::-1 ], 2, 7 ) and len( sr.draw( frame, 2, 7 ) ) == 2
    assert sr.draw( frame, 50, 7 ) == frame


def test_matched_pairs_keep_the_pairs_both_passes_ruled_and_count_the_rest():
    first  = verdict_rows( { "d-1": [ 0, 1, 1 ], "d-2": [ 0 ] } )
    second = verdict_rows( { "d-1": [ 0, 1 ], "d-3": [ 1 ] } )
    by, unmatched = sr.matched_pairs( first, second )
    assert by == { "d-1": [ ( 0, 0 ), ( 1, 1 ) ] } and unmatched == 3


def test_estimate_adds_the_gap_to_the_interim_rate_with_a_cluster_ratio_interval():
    by  = { "d1": [ ( 0, 0 ), ( 1, 1 ), ( 0, 1 ) ], "d2": [ ( 0, 0 ), ( 0, 0 ) ], "d3": [ ( 1, 0 ) ], "d4": [ ( 0, 1 ), ( 0, 0 ), ( 0, 0 ) ] }
    got = sr.estimate( 1000, 100, by )
    assert ( got[ "definitions" ], got[ "pairs" ] ) == ( 4, 9 )
    assert got[ "interim_rate" ] == 0.1 and got[ "gap" ] == pytest.approx( 1 / 9 ) and got[ "rate" ] == pytest.approx( 0.1 + 1 / 9 )
    assert got[ "sample_interim_rate" ] == pytest.approx( 2 / 9 ) and got[ "reference_rate" ] == pytest.approx( 3 / 9 )
    assert got[ "low" ] == 0.0 and got[ "high" ] == pytest.approx( 0.5823, abs=1e-3 )


def test_estimate_interval_is_kept_inside_zero_and_one_and_narrows_with_more_agreement():
    agree = { f"d{i}": [ ( i % 2, i % 2 ) ] * 3 for i in range( 40 ) }
    got   = sr.estimate( 5000, 500, agree )
    assert got[ "gap" ] == 0 and got[ "rate" ] == pytest.approx( 0.1 ) and 0.0 <= got[ "low" ] <= 0.1 <= got[ "high" ] <= 1.0
    assert got[ "high" ] - got[ "low" ] == pytest.approx( 2 * 1.96 * ( 0.1 * 0.9 / 5000 ) ** 0.5, rel=1e-2 )
    high = sr.estimate( 100, 99, { "a": [ ( 1, 1 ), ( 1, 1 ) ], "b": [ ( 1, 1 ), ( 0, 1 ) ] } )
    assert high[ "high" ] == 1.0


def test_estimate_has_no_interval_from_one_definition_and_no_rate_from_none():
    one = sr.estimate( 100, 10, { "d1": [ ( 0, 1 ), ( 1, 1 ) ] } )
    assert one[ "rate" ] == pytest.approx( 0.1 + 0.5 ) and one[ "low" ] is None and one[ "high" ] is None
    none = sr.estimate( 100, 10, {} )
    assert none[ "rate" ] is None and none[ "gap" ] is None and none[ "definitions" ] == 0
    with pytest.raises( ValueError, match="no pair verdict" ): sr.estimate( 0, 0, {} )


def test_render_a_plan_and_a_live_result():
    plan = sr.render( OPUS, FABLE, 30, 5, 2, ( 1000, 100, [ "r.json" ] ), { "r.json": [ "d-1", "d-2" ] } )
    assert "Sample of 2 definitions (asked for 30, seed 5, slot 2), from 1 run file(s)" in plan and "100 flagged (10.0%)" in plan
    assert "Plan only: no model call was made. The re-judge may make up to 2 calls" in plan
    est  = sr.estimate( 1000, 100, { "d1": [ ( 0, 1 ), ( 0, 0 ) ], "d2": [ ( 1, 1 ) ], "d3": [ ( 0, 0 ) ] } )
    live = sr.render( OPUS, FABLE, 30, 5, 2, ( 1000, 100, [ "r.json" ] ), { "r.json": [ "d-1", "d-2" ] }, est, [ "d-9" ], 4, 2 )
    assert "| 3 | 4 |" in live and "Model calls made: 4." in live and "Pairs only one pass ruled, left out of the gap: 2." in live and "Left out, because" in live and "d-9" in live
    empty = sr.render( OPUS, FABLE, 30, 5, 2, ( 0, 0, [] ), {}, sr.estimate( 10, 1, {} ) )
    assert "n/a" in empty and "Left out" not in empty


def run_main( argv, **kw ):
    out  = io.StringIO()
    code = sr.main( argv, out=out, now=NOW, **kw )
    return code, out.getvalue()


def base( folder, *extra ):
    return [ "--ruled-by", OPUS, "--rejudge-with", FABLE, "--size", "2", "--seed", "3", "--check-dir", str( folder ), *extra ]


def test_main_without_go_prints_the_plan_and_makes_no_call(tmp_path):
    folder = seeded_folder( tmp_path )
    code, text = run_main( base( folder ), run=lambda *a: pytest.fail( "no call" ) )
    assert code == 0 and "Plan only" in text and "slot 2" in text and "Sample re-judge of model-a with model-b" in text


def test_main_takes_the_seed_from_the_date_and_the_folder_from_the_project_root(tmp_path, monkeypatch):
    folder = seeded_folder( tmp_path )
    monkeypatch.setattr( dcs, "folder_of", lambda root: folder )
    code, text = run_main( [ "--ruled-by", OPUS, "--rejudge-with", FABLE, "--size", "2" ] )
    assert code == 0 and "seed 20261214" in text


def test_main_with_go_judges_the_sample_and_prints_the_estimate(tmp_path):
    folder = seeded_folder( tmp_path )
    seen   = {}
    def run( root, fold, model, groups, parts, cli, parallel, when, second_model, slot ):
        seen.update( model=model, second=second_model, slot=slot, cli=cli, parts=parts )
        ids = [ i for g in groups.values() for i in g ]
        return verdict_rows( { i: [ 0, 1 ] for i in ids } ), verdict_rows( { i: [ 0, 1 ] for i in ids[ :-1 ] } ), [ "gone" ], 3
    code, text = run_main( base( folder, "--go", "--claude-cli-path", "/bin/claude", "--slot", "5" ), run=run, parts={ "p": 1 } )
    assert code == 0 and "Model calls made: 3." in text and "estimated flag rate" in text and "Pairs only one pass ruled, left out of the gap: 2." in text
    assert seen == { "model": OPUS, "second": FABLE, "slot": 5, "cli": "/bin/claude", "parts": { "p": 1 } }


def test_main_builds_the_live_parts_only_when_it_has_to(tmp_path, monkeypatch):
    folder = seeded_folder( tmp_path )
    monkeypatch.setattr( daily, "live_parts", lambda: { "built": True } )
    got = []
    run_main( base( folder, "--go", "--claude-cli-path", "c" ), run=lambda root, fold, model, groups, parts, *r: got.append( parts ) or ( [], [], [], 0 ) )
    assert got == [ { "built": True } ]


@pytest.mark.parametrize( "extra, reason", [
    ( [ "--slot", "1" ], "below 2" ),
    ( [ "--go" ], "--go needs --claude-cli-path" ),
    ( [ "--size", "0" ], "--size must be at least 1" ),
] )
def test_main_refuses_with_exit_3_and_names_the_reason( tmp_path, extra, reason ):
    code, text = run_main( [ *base( seeded_folder( tmp_path ) ), *extra ] )
    assert code == sr.EXIT_NOT_MADE and "REFUSING:" in text and reason in text and "Nothing was made." in text


def test_main_refuses_when_nothing_can_be_sampled_the_folder_is_missing_or_the_budget_is_spent(tmp_path):
    code, text = run_main( base( tmp_path ) )
    assert code == sr.EXIT_NOT_MADE and "no definition that model-a judged itself" in text
    code, text = run_main( base( tmp_path / "missing" ) )
    assert code == sr.EXIT_NOT_MADE and "FileNotFoundError" in text
    folder = seeded_folder( tmp_path / ".." / tmp_path.name )
    def spent( *a ): raise daily.SpendRefused( "the daily call budget is spent" )
    code, text = run_main( base( folder, "--go", "--claude-cli-path", "c" ), run=spent, parts={} )
    assert code == sr.EXIT_NOT_MADE and "SpendRefused" in text
