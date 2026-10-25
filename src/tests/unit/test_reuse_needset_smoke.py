"""
The ten-need smoke: the live window, the measurements and the real index parts.
"""
import asyncio
import datetime
import json
import time

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from lupin_mcp.reuse_needset import draft, run, smoke
from lupin_mcp.reuse_needset import errors as er
from tests.unit.test_reuse_needset_keys import Vectors
from tests.unit.test_reuse_needset_pool import REPO_ROOT, write_tree
from tests.unit.test_reuse_needset_run import COMMIT, Model, make_env

UTC = datetime.timezone.utc


def at( hour, minute=0, tz=UTC, day=24 ):
    """Return a moment on a day of October 2026."""
    return datetime.datetime( 2026, 10, day, hour, minute, tzinfo=tz )


def argv( out, near=2, work=4, cross=2, extra=() ):
    """Return a command line for the smoke."""
    return [ "--root", "/r", "--out-dir", str( out ), "--source-commit", COMMIT, "--seed", "7", "--vectors-dir", "/v", "--query-cache-dir", "/q",
             "--near-copy", str( near ), "--work-alike", str( work ), "--cross-language", str( cross ), "--ts-share", "0.5", *extra ]


def tree( tmp_path ):
    """Write the pool tests' small tree under src/cosa/fx of a folder that has the lupin layout."""
    ( tmp_path / "tree" / "src" / "lupin_mcp" ).mkdir( parents=True )
    ( tmp_path / "tree" / "src" / "cosa" / "fx" ).mkdir( parents=True )
    write_tree( tmp_path / "tree" / "src" / "cosa" / "fx" )
    return tmp_path / "tree"


@pytest.fixture( autouse=True )
def _typescript_lookup( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )


@pytest.mark.parametrize( "moment, expected", [ ( at( 13, 59 ), False ), ( at( 14, 0 ), True ), ( at( 16, 59 ), True ), ( at( 17, 0 ), False ), ( at( 9, 59, smoke.EASTERN ), False ),
                                               ( at( 10, 0, smoke.EASTERN ), True ), ( at( 12, 59, smoke.EASTERN ), True ), ( at( 13, 0, smoke.EASTERN ), False ) ] )
def test_a_live_run_is_allowed_from_ten_to_one_eastern_whatever_the_zone_given( moment, expected ):
    assert smoke.in_window( moment ) is expected


def test_a_time_without_a_zone_is_refused():
    with pytest.raises( ValueError ): smoke.in_window( datetime.datetime( 2026, 10, 24, 11, 0 ) )


def test_the_command_line_names_the_split_and_has_no_default_for_it():
    a = smoke.parse_args( [ x for x in argv( "/o" ) if x not in ( "--ts-share", "0.5" ) ] )
    assert smoke.kind_split( a ) == { "near_copy": 2, "work_alike": 4, "cross_language": 2 } and a.parallel == 3 and a.second_model == "claude-opus-5-5" and a.server == "max-plan" and a.ts_share == 0.6
    for flag in ( "--near-copy", "--work-alike", "--cross-language", "--source-commit", "--seed" ):
        cut = argv( "/o" )
        i   = cut.index( flag )
        del cut[ i : i + 2 ]
        with pytest.raises( SystemExit ): smoke.parse_args( cut )


def test_timed_records_each_duration_and_each_failure_by_label_and_passes_the_error_on():
    ticks = iter( [ 0.0, 1.5, 2.0, 2.25, 3.0, 4.0 ] )

    def ask( system, prompt ):
        if prompt == "bad": raise RuntimeError( "boom" )
        return "reply"

    timed = smoke.Timed( lambda: next( ticks ) )
    one, two = timed.wrap( "draft", ask ), timed.wrap( "second", lambda prompt: "r" )
    assert one( "s", "ok" ) == "reply"
    with pytest.raises( RuntimeError ): one( "s", "bad" )
    assert two( "p" ) == "r"
    assert timed.calls == [ ( "draft", 1.5, False ), ( "draft", 0.25, True ), ( "second", 1.0, False ) ]
    assert timed.summary( "draft" ) == { "calls": 2, "errors": 1, "seconds": { "mean": 0.875, "min": 0.25, "max": 1.5 } }
    assert timed.summary( "second" )[ "calls" ] == 1 and timed.summary()[ "calls" ] == 3 and timed.summary()[ "errors" ] == 1
    assert smoke.Timed( None ).summary() == { "calls": 0, "errors": 0, "seconds": None }


def fake_result( accepted, failed ):
    """Return a run result with the given counts of accepted and failed seeds."""
    return { "needs": [ {} ] * accepted, "cells": [ { "accepted": [ {} ] * accepted, "failed": [ { "reason": r } for r in failed ] } ] }


def test_the_report_gives_the_rates_the_reasons_and_calls_it_a_measurement():
    timed = smoke.Timed( None )
    timed.calls = [ ( "draft", 1.0, False ), ( "draft", 3.0, True ), ( "second", 5.0, False ) ]
    args  = smoke.parse_args( argv( "/o" ) )
    rep   = smoke.smoke_report( args, timed, fake_result( 3, [ "NO_KEY", "NEED_LEAKS_KEY", "NO_KEY" ] ), at( 14, 0 ), at( 14, 5 ), "boxy", { "k": 1 } )
    assert rep[ "seeds_tried" ] == 6 and rep[ "seeds_failed" ] == 3 and rep[ "failure_rate" ] == 0.5 and rep[ "failed_by_reason" ] == { "NO_KEY": 2, "NEED_LEAKS_KEY": 1 }
    assert rep[ "seconds_per_call" ] == { "mean": 3.0, "min": 1.0, "max": 5.0 } and rep[ "model_calls" ] == 3 and rep[ "call_errors" ] == 1 and rep[ "elapsed_seconds" ] == 300.0
    assert rep[ "host" ] == "boxy" and rep[ "source_commit" ] == COMMIT and rep[ "smoke" ] is True and rep[ "note" ] == "a measurement, not a pass bar" and rep[ "needs" ] == 3 and rep[ "extras" ] == { "k": 1 }
    assert rep[ "by_model" ] == { "draft": timed.summary( "draft" ), "second": timed.summary( "second" ) } and rep[ "by_model" ][ "second" ][ "seconds" ][ "mean" ] == 5.0
    idle = smoke.smoke_report( args, smoke.Timed( None ), fake_result( 0, [] ), at( 14, 0 ), at( 14, 0 ), "boxy", {} )
    assert idle[ "seconds_per_call" ] is None and idle[ "failure_rate"] is None


def test_a_live_run_outside_the_window_is_refused_before_anything_is_built( tmp_path, monkeypatch ):
    monkeypatch.setattr( smoke, "live_build_env", lambda *a: pytest.fail( "the live env was built" ) )
    out = tmp_path / "out"
    with pytest.raises( er.NeedsetError ) as e: smoke.main( argv( out ), now=lambda: at( 3, 0 ) )
    assert e.value.code == er.OUTSIDE_WINDOW and not out.exists()


@pytest.mark.parametrize( "extra", [ (), ( "--window-lifted-by", "" ), ( "--window-lifted-by", "   " ) ] )
def test_a_blank_or_missing_lift_still_refuses_outside_the_window( tmp_path, monkeypatch, extra ):
    monkeypatch.setattr( smoke, "live_build_env", lambda *a: pytest.fail( "the live env was built" ) )
    with pytest.raises( er.NeedsetError ) as e: smoke.main( argv( tmp_path / "out", extra=extra ), now=lambda: at( 3, 0 ) )
    assert e.value.code == er.OUTSIDE_WINDOW


def test_a_named_lift_runs_outside_the_window_and_the_record_says_who( tmp_path, monkeypatch ):
    def live( args, set_at, timed ):
        ( tmp_path / "w" ).mkdir()
        return make_env( tmp_path / "w", ask=timed.wrap( "draft", Model() ), name="live.jsonl" )

    monkeypatch.setattr( smoke, "live_build_env", live )
    rep = smoke.main( argv( tmp_path / "out", extra=( "--window-lifted-by", " Rick, 23:55 " ) ), now=lambda: at( 3, 0 ), host="h" )
    assert rep[ "window_lifted_by" ] == "Rick, 23:55" and json.loads( ( tmp_path / "out" / smoke.SMOKE_FILE ).read_text() )[ "window_lifted_by" ] == "Rick, 23:55"
    ( tmp_path / "w2" ).mkdir()
    plain = smoke.main( argv( tmp_path / "out2" ), build_env=lambda a, s, t: make_env( tmp_path / "w2", ask=t.wrap( "draft", Model() ), name="x.jsonl" ), now=lambda: at( 3, 0 ), host="h" )
    assert plain[ "window_lifted_by" ] is None


def test_a_live_run_in_the_window_uses_the_live_env_and_writes_the_measurements( tmp_path, monkeypatch ):
    seen = []

    def live( args, set_at, timed ):
        seen.append( set_at )
        ( tmp_path / "w" ).mkdir()
        return make_env( tmp_path / "w", ask=timed.wrap( "draft", Model() ), name="live.jsonl" )

    monkeypatch.setattr( smoke, "live_build_env", live )
    rep = smoke.main( argv( tmp_path / "out" ), now=lambda: at( 15, 0 ), host="h" )
    assert seen == [ at( 15, 0 ).isoformat() ] and rep[ "needs" ] == 10


def test_a_smoke_run_over_a_fake_env_marks_every_need_and_writes_all_four_files( tmp_path ):
    model = Model()
    ticks = iter( range( 10000 ) )
    build = lambda a, t, timed: make_env( tmp_path, ask=timed.wrap( "draft", model ), name="x.jsonl", wrap_second=lambda f: timed.wrap( "second", f ) )
    rep   = smoke.main( argv( tmp_path / "out" ), build_env=build, now=lambda: at( 3, 0 ), clock=lambda: next( ticks ) * 0.5, host="h" )
    out   = tmp_path / "out"
    needs = [ json.loads( l ) for l in ( out / "needset-drafts.jsonl" ).read_text().splitlines() ]
    assert len( needs ) == 10 == rep[ "needs" ] and all( n[ "smoke" ] is True for n in needs )
    second = rep[ "by_model" ][ "second" ][ "calls" ]
    assert rep[ "by_model" ][ "draft" ][ "calls" ] == model.calls > 0 and second > 0, "the nothing needs call the second model, and the report counts those calls"
    assert rep[ "model_calls" ] == model.calls + second and rep[ "seconds_per_call" ][ "mean" ] == 0.5 and rep[ "failure_rate" ] == 0.0
    assert json.loads( ( out / smoke.SMOKE_FILE ).read_text() ) == rep and json.loads( ( out / "needset-draft-report.json" ).read_text() )[ "smoke" ] is True
    assert ( out / "needset-plan.json" ).is_file() and rep[ "host" ] == "h" and rep[ "kind_split" ] == { "near_copy": 2, "work_alike": 4, "cross_language": 2 }


def test_a_split_that_does_not_add_up_is_refused_before_the_env_is_built( tmp_path ):
    with pytest.raises( er.NeedsetError ) as e: smoke.main( argv( tmp_path / "out", near=1, work=1, cross=1 ), build_env=lambda a, t, timed: pytest.fail( "built" ), now=lambda: at( 3, 0 ) )
    assert e.value.code == er.QUOTA_INVALID


def test_the_real_index_the_finder_and_the_strip_feed_a_near_copy_job( tmp_path ):
    root = tree( tmp_path )
    by_id, kept, measures, twins, bodies = smoke.index_parts( root, tmp_path / "idx" )
    assert "cosa.fx.pkg.a.twin_a" in by_id and "cosa.fx.pkg.a.twin_a" in {r[ "id" ] for r in kept} and "cosa.fx.pkg.a.twin_b" in twins[ "cosa.fx.pkg.a.twin_a" ]
    assert "twin_a" in bodies[ "cosa.fx.pkg.a.twin_a" ] and set( bodies ) == { r[ "id" ] for r in kept } and set( measures ) >= set( bodies )


def test_the_candidate_parts_load_the_vector_set_embed_with_the_concat_vector_and_build_the_stage( monkeypatch ):
    calls = []
    loaded = Vectors( [ "a.f" ], [ [ 1.0, 0.0 ] ] )
    loaded.manifest = { "manifest_hash": "h" }
    monkeypatch.setattr( smoke.vector_store, "load_vectors", lambda d: ( calls.append( d ) or loaded ) )
    monkeypatch.setattr( smoke.vector_store, "query_vectors", lambda text, client, cache, manifest: ( calls.append( ( text, client, cache, manifest ) ) or { "concat": [ 0.5, 0.5 ] } ) )
    records = [ { "id": "a.f", "file": "a.py", "module": "a", "name": "f", "sig": "()", "doc": "Does f.", "pin": "p" } ]
    vectors, stage, embed = smoke.candidate_parts( "/v", "/q", "client", records )
    assert vectors is loaded and stage.ids == ( "a.f", ) and embed( "need" ) == [ 0.5, 0.5 ]
    assert calls == [ "/v", ( "need", "client", "/q", { "manifest_hash": "h" } ) ]


def test_the_env_is_assembled_from_the_real_index_with_two_ledgers_and_a_smoke_flag( tmp_path, monkeypatch ):
    root = tree( tmp_path )
    by_id, *_ = smoke.index_parts( root, tmp_path / "scan" )
    ids  = sorted( by_id )
    loaded = Vectors( ids, [ [ 1.0, 0.01 * n ] for n in range( len( ids ) ) ] )
    loaded.manifest = {}
    monkeypatch.setattr( smoke.vector_store, "load_vectors", lambda d: loaded )
    args = smoke.parse_args( argv( tmp_path / "out", extra=[ "--cli-path", "" ] ) )
    args.root = str( root )
    env  = smoke.assemble_env( args, Model(), Model(), None, "2026-10-24T14:00:00+00:00", smoke.Timed( time.monotonic ) )
    assert env.smoke is True and env.model_id == draft.DRAFTER_MODEL and env.source_commit == COMMIT and env.seed == 7 and env.set_at == "2026-10-24T14:00:00+00:00"
    assert env.kind_split == { "near_copy": 2, "work_alike": 4, "cross_language": 2 } and env.parallel == 3 and env.none_draft_fn is not None
    assert env.extras == { "vector_coverage": { "eligible": len( env.kept ), "with_a_vector_row": len( env.kept ), "vector_set_ids": len( ids ), "stage_ids": len( by_id ) } }
    assert ( tmp_path / "out" ).is_dir()
    seed = "cosa.fx.pkg.a.twin_a"
    job  = __import__( "lupin_mcp.reuse_needset.run", fromlist=[ "run" ] ).near_copy_job( env, seed, "py" )
    assert "cosa.fx.pkg.a.twin_b" in [ r[ "id" ] for r in job[ "keys" ] ] and "twin_a" not in job[ "stripped" ][ "text" ] and job[ "stripped" ][ "forbidden" ]


def test_the_live_env_uses_the_real_drafter_the_named_second_model_and_the_embeddings_client( monkeypatch ):
    made, got = [], []
    monkeypatch.setattr( smoke.draft, "drafter_call", lambda *a: ( made.append( a ) or f"call{len( made )}" ) )
    monkeypatch.setattr( smoke.vector_build, "EndpointClient", lambda: "client" )
    monkeypatch.setattr( smoke, "assemble_env", lambda *a: ( got.append( a ) or "env" ) )
    monkeypatch.setattr( smoke.model_transport, "configure", lambda **k: None )
    args = smoke.parse_args( argv( "/o", extra=[ "--second-model", "model-b" ] ) )
    assert smoke.live_build_env( args, "when", "timer" ) == "env"
    assert made == [ (), ( "model-b", ) ] and got == [ ( args, "call1", "call2", "client", "when", "timer" ) ]


def test_the_cli_path_argument_is_the_binary_the_next_model_call_invokes( tmp_path, monkeypatch ):
    cli = tmp_path / "claude-new"
    cli.write_text( "#!/bin/sh\n", encoding="utf-8" )
    cli.chmod( 0o755 )
    monkeypatch.setattr( smoke.model_transport, "CLI_PATH", None )
    monkeypatch.setattr( smoke.model_transport, "CWD", None )
    monkeypatch.setattr( smoke.draft, "drafter_call", lambda *a: "call" )
    monkeypatch.setattr( smoke.vector_build, "EndpointClient", lambda: "client" )
    monkeypatch.setattr( smoke, "assemble_env", lambda *a: "env" )
    args = smoke.parse_args( argv( tmp_path / "out", extra=[ "--cli-path", str( cli ) ] ) )
    assert smoke.live_build_env( args, "when", "timer" ) == "env"
    seen = []

    async def query_fn( prompt, options ):
        seen.append( options.cli_path )
        yield AssistantMessage( content=[ TextBlock( "ok" ) ], model=options.model )

    asyncio.run( smoke.model_transport.complete( "m", "s", "u", query_fn=query_fn ) )
    assert seen == [ str( cli ) ]                                      # the path the ledger is labelled with is the path invoked


def test_no_cli_path_leaves_the_sdk_binary_and_a_bad_one_is_refused_before_any_call( tmp_path, monkeypatch ):
    monkeypatch.setattr( smoke.model_transport, "CLI_PATH", "/stale" )
    monkeypatch.setattr( smoke.model_transport, "CWD", None )
    monkeypatch.setattr( smoke, "assemble_env", lambda *a: "env" )
    monkeypatch.setattr( smoke.draft, "drafter_call", lambda *a: "call" )
    monkeypatch.setattr( smoke.vector_build, "EndpointClient", lambda: "client" )
    assert smoke.live_build_env( smoke.parse_args( argv( tmp_path ) ), "w", "t" ) == "env" and smoke.model_transport.CLI_PATH is None
    bad = smoke.parse_args( argv( tmp_path, extra=[ "--cli-path", str( tmp_path / "missing" ) ] ) )
    with pytest.raises( ValueError, match="not an executable file" ): smoke.live_build_env( bad, "w", "t" )


def test_a_symbol_newer_than_the_vector_set_is_left_out_of_the_pool_and_counted( tmp_path, monkeypatch ):
    root = tree( tmp_path )
    by_id, kept, *_ = smoke.index_parts( root, tmp_path / "scan" )
    old  = sorted( r[ "id" ] for r in kept )[ 1: ]
    loaded = Vectors( old, [ [ 1.0, 0.01 * n ] for n in range( len( old ) ) ] )
    loaded.manifest = {}
    monkeypatch.setattr( smoke.vector_store, "load_vectors", lambda d: loaded )
    args = smoke.parse_args( argv( tmp_path / "out", extra=[ "--cli-path", "" ] ) )
    args.root = str( root )
    env  = smoke.assemble_env( args, Model(), Model(), None, "2026-10-24T14:00:00+00:00", smoke.Timed( time.monotonic ) )
    assert sorted( r[ "id" ] for r in env.kept ) == old and env.ctx.by_id.keys() == set( old )
    assert env.extras[ "vector_coverage" ] == { "eligible": len( kept ), "with_a_vector_row": len( old ), "vector_set_ids": len( old ), "stage_ids": len( by_id ) }


def test_a_tree_without_the_lupin_layout_is_refused_by_name( tmp_path ):
    ( tmp_path / "plain" ).mkdir()
    with pytest.raises( er.NeedsetError ) as e: smoke.index_parts( tmp_path / "plain", tmp_path / "idx" )
    assert e.value.code == er.NOT_LUPIN_TREE


def test_the_assembled_env_sends_the_drafter_and_the_second_model_through_the_timer( tmp_path, monkeypatch ):
    root = tree( tmp_path )
    by_id, *_ = smoke.index_parts( root, tmp_path / "scan" )
    ids  = sorted( by_id )
    loaded = Vectors( ids, [ [ 1.0, 0.01 * n ] for n in range( len( ids ) ) ] )
    loaded.manifest = {}
    monkeypatch.setattr( smoke.vector_store, "load_vectors", lambda d: loaded )
    monkeypatch.setattr( smoke.vector_store, "query_vectors", lambda text, client, cache, manifest: { "concat": [ 1.0, 0.0 ] } )
    args = smoke.parse_args( argv( tmp_path / "out", extra=[ "--cli-path", "" ] ) )
    args.root = str( root )
    timed  = smoke.Timed( time.monotonic )
    second = []
    env    = smoke.assemble_env( args, Model(), lambda system, prompt: ( second.append( system ) or '{"any_does_it": "no"}' ), None, "when", timed )
    got    = env.none_draft_fn( run.nothing_job( env, "src/cosa/fx/pkg/a.py", "py" ), env.ask, env.ledger )
    assert got[ "ok" ] is True and got[ "absence" ][ "rejected" ] is False
    assert timed.summary( "draft" )[ "calls" ] == 1 and timed.summary( "second" )[ "calls" ] == len( second ) >= 1 and set( second ) == { smoke.SECOND_SYSTEM }
