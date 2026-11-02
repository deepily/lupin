"""
The yield replay, run on fakes with no model call.

It rebuilds the yield needs from saved answers, and with a live flag traces them under one stage of the call cap.
"""
import asyncio
import json
import stat
import types

import pytest

from cosa.repo.doc_lint import harness_runner, model_transport
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import call_cap, draft, loss_trace, source_at, stage_parts, stage_seeds, stages, yield_trace as yt
from lupin_mcp.reuse_seeded_miss_e2e import SavedAnswerMissing

BINDING = "1.0 (Claude Code)|max-plan"


def records( n_ts=130, n_py=90 ):
    """Return eligible records sorted by id, all tracked."""
    out = [ { "id": f"web.m{n:03d}.fn", "file": f"src/web/m{n:03d}.js", "lang": "ts" } for n in range( n_ts ) ]
    out += [ { "id": f"cosa.m{n:03d}.fn", "file": f"src/cosa/m{n:03d}.py", "lang": "py" } for n in range( n_py ) ]
    return sorted( out, key=lambda r: r[ "id" ] )


def saved_run( folder ):
    """Make an earlier run's folder with the seed lists and two ledgers; return the lists."""
    folder.mkdir()
    recs   = records()
    record = stage_seeds.draw_lists( recs, 7, set(), "abc123", { r[ "file" ] for r in recs } )
    stage_seeds.write_lists( folder, record )
    for name in yt.SAVED_FILES[ :2 ]: harness_runner.Ledger( str( folder / name ), binding=BINDING )
    return record


def need( n, lang="py" ): return { "id": f"n-{n}", "write_lang": lang, "kind": "work_alike", "seed": f"s{n}", "key": { "symbols": [ f"s{n}" ], "source": "seed_answer" } }


def cli( tmp_path ):
    """A stand-in for the Claude Code binary that reports a version."""
    path = tmp_path / "claude"
    path.write_text( "#!/bin/sh\necho '1.0 (Claude Code)'\n", encoding="utf-8" )
    path.chmod( path.stat().st_mode | stat.S_IXUSR )
    return str( path )


def test_saved_ask_refuses_every_question_so_no_model_is_contacted():
    with pytest.raises( SavedAnswerMissing ): yt.saved_ask( "system", "prompt" )


def test_copy_saved_copies_what_is_missing_and_keeps_what_is_there( tmp_path ):
    saved_run( tmp_path / "old" )
    run = tmp_path / "new"; run.mkdir()
    ( run / yt.SAVED_FILES[ 0 ] ).write_text( "mine\n", encoding="utf-8" )
    assert yt.copy_saved( tmp_path / "old", run ) == [ yt.SAVED_FILES[ 1 ], yt.SAVED_FILES[ 2 ] ]
    assert ( run / yt.SAVED_FILES[ 0 ] ).read_text( encoding="utf-8" ) == "mine\n"
    assert ( run / yt.SAVED_FILES[ 2 ] ).read_bytes() == ( tmp_path / "old" / yt.SAVED_FILES[ 2 ] ).read_bytes()
    assert yt.copy_saved( tmp_path / "old", run ) == []


def test_copy_saved_names_a_file_the_earlier_run_lacks_and_copies_nothing( tmp_path ):
    saved_run( tmp_path / "old" )
    ( tmp_path / "old" / yt.SAVED_FILES[ 1 ] ).unlink()
    run = tmp_path / "new"; run.mkdir()
    with pytest.raises( er.NeedsetError ) as caught: yt.copy_saved( tmp_path / "old", run )
    assert caught.value.code == er.SAVED_FILE_MISSING and yt.SAVED_FILES[ 1 ] in caught.value.detail
    assert list( run.iterdir() ) == []


def test_rebuild_lists_the_unsaved_seeds_skips_a_seed_without_a_need_and_keeps_the_order():
    async def make( seed_id ):
        if seed_id == "b": raise SavedAnswerMissing( "no answer" )
        return None if seed_id == "c" else need( seed_id )
    needs, unsaved = asyncio.run( yt.rebuild( [ "a", "b", "c", "d" ], make ) )
    assert [ n[ "seed" ] for n in needs ] == [ "sa", "sd" ] and unsaved == [ "b" ]


def test_rebuild_head_counts_the_needs_by_language_and_only_this_calls_reasons( tmp_path ):
    record = saved_run( tmp_path / "old" )
    order  = record[ "yield" ][ "order" ]
    tally  = stage_parts.Tally(); tally[ stage_parts.DRAFT_FAILED ] += 5                 # an earlier stage's count must not show
    async def make( seed_id ):
        if seed_id == order[ 0 ]: tally[ stage_parts.NO_PARTNER ] += 1; return None
        if seed_id == order[ 1 ]: raise SavedAnswerMissing( "no answer" )
        return need( seed_id, "ts" if seed_id.startswith( "web." ) else "py" )
    needs, head = asyncio.run( yt.rebuild_head( str( tmp_path / "old" / stage_seeds.LISTS_FILE ), make, tally ) )
    assert head[ "seeds" ] == 100 and head[ "needs" ] == len( needs ) == 98 and head[ "unsaved" ] == [ order[ 1 ] ]
    assert head[ "no_final_need" ][ stage_parts.NO_PARTNER ] == 1 and head[ "no_final_need" ][ stage_parts.DRAFT_FAILED ] == 0
    assert sum( head[ "by_lang" ].values() ) == 98 and head[ "lists_sha" ] == record[ "sha" ] and list( head[ "by_lang" ] ) == sorted( head[ "by_lang" ] )


def test_found_intervals_give_each_languages_found_share_with_its_interval():
    out = yt.found_intervals( { "by_lang": { "py": { "FOUND": 7, "NOT_RETRIEVED": 3 }, "ts": { "NOT_READ": 2 } } } )
    assert out[ "py" ][ "found" ] == 7 and out[ "py" ][ "members" ] == 10 and 0.3 < out[ "py" ][ "interval" ][ 0 ] < 0.7 < out[ "py" ][ "interval" ][ 1 ] < 1.0
    assert out[ "ts" ][ "found" ] == 0 and out[ "ts" ][ "members" ] == 2


def trace_record( n, lost, lang="py" ): return { "id": f"n-{n}", "kind": "work_alike", "write_lang": lang, "members": { f"s{n}": lost } }


def test_trace_needs_reports_where_members_were_lost_and_the_found_share_by_language():
    async def trace( needs ): return [ trace_record( 1, loss_trace.FOUND ), trace_record( 2, loss_trace.NOT_RETRIEVED ), trace_record( 3, loss_trace.FOUND, "ts" ) ]
    out = asyncio.run( yt.trace_needs( [ need( 1 ), need( 2 ), need( 3 ) ], { "seeds": 3 }, trace ) )
    assert out[ "traced" ] is True and out[ "seeds" ] == 3 and out[ "found" ] == 2 and out[ "lost" ] == 1 and out[ "by_lost_at" ] == { "FOUND": 2, "NOT_RETRIEVED": 1 }
    assert out[ "found_by_lang" ][ "py" ][ "found" ] == 1 and out[ "found_by_lang" ][ "ts" ][ "found" ] == 1


def test_trace_needs_keeps_the_head_when_the_stage_budget_ends_it_and_raises_anything_else():
    async def over_budget( needs ): raise er.NeedsetError( er.STAGE_BUDGET_REACHED, "260 used" )
    out = asyncio.run( yt.trace_needs( [ need( 1 ) ], { "seeds": 1 }, over_budget ) )
    assert out == { "seeds": 1, "budget_reached": True, "budget_detail": "260 used", "traced": False }
    async def capped( needs ): raise er.NeedsetError( er.CALL_CAP_REACHED, "300 used" )
    with pytest.raises( er.NeedsetError ) as caught: asyncio.run( yt.trace_needs( [ need( 1 ) ], { }, capped ) )
    assert caught.value.code == er.CALL_CAP_REACHED


def charged( count ):
    """Return a work function that makes count counted model calls, as the trace does."""
    async def work():
        for _ in range( count ): model_transport.CHARGE_HOOK( "claude-opus-5-5" )
        return { "ok": True }
    return work


def test_run_traced_charges_the_trace_stage_writes_the_report_and_puts_the_hook_back( tmp_path ):
    before = model_transport.CHARGE_HOOK
    out = asyncio.run( yt.run_traced( str( tmp_path ), 10, 5, charged( 3 ) ) )
    assert out[ "status" ] == yt.DONE and out[ "used" ] == 3 and out[ "by_stage" ] == { yt.YIELD_TRACE: 3 } and out[ "limit" ] == 10
    assert json.loads( ( tmp_path / yt.REPORT_FILE ).read_text( encoding="utf-8" ) ) == out
    assert model_transport.CHARGE_HOOK is before


def test_run_traced_names_a_stop_a_stage_budget_the_cap_and_a_failure( tmp_path ):
    async def stop(): return { "stop": True }
    async def budget(): return { "budget_reached": True }
    for name, work, status in ( ( "a", stop, yt.STOPPED ), ( "d", budget, yt.BUDGET ) ):
        ( tmp_path / name ).mkdir()
        assert asyncio.run( yt.run_traced( str( tmp_path / name ), 5, 5, work ) )[ "status" ] == status
    run = tmp_path / "b"; run.mkdir()
    out = asyncio.run( yt.run_traced( str( run ), 10, 2, charged( 3 ) ) )                    # the third call is past the stage's budget of 2
    assert out[ "status" ] == yt.FAILED and out[ "report" ][ "code" ] == er.STAGE_BUDGET_REACHED and out[ "used" ] == 2
    run = tmp_path / "c"; run.mkdir()
    out = asyncio.run( yt.run_traced( str( run ), 2, 5, charged( 3 ) ) )                     # the third call is past the whole cap
    assert out[ "status" ] == yt.CAP and out[ "report" ][ "code" ] == er.CALL_CAP_REACHED and out[ "used" ] == 2


def argv( tmp_path, *more ):
    return [ "--root", str( tmp_path ), "--run-dir", str( tmp_path / "new" ), "--from-run", str( tmp_path / "old" ), "--seed", "20261101", "--source-commit", "abc123", *more ]


def test_the_command_line_defaults_are_a_plan_with_the_stage_budget_and_the_cap( tmp_path ):
    args = yt.parse_args( argv( tmp_path ) )
    assert args.live is False and args.limit == yt.RUN_LIMIT == 300 and args.budget == yt.TRACE_BUDGET == 260 and args.seed == 20261101 and args.cli_path is None
    assert yt.parse_args( argv( tmp_path, "--live", "--limit", "9", "--budget", "4" ) ).live is True


def fake_parts( needs_for, trace_fn=None, tally=None ):
    """Return a build_parts stand-in whose make_need answers from a dict of seed id to need."""
    async def make_need( seed_id ):
        if needs_for[ seed_id ] is SavedAnswerMissing: raise SavedAnswerMissing( "no answer" )
        return needs_for[ seed_id ]
    async def no_trace( needs ): raise AssertionError( "a plan never traces" )
    return lambda env, built, lists, models, drafter, second, ledgers, partners: { "make_need": make_need, "trace_fn": trace_fn or no_trace, "tally": tally or stage_parts.Tally() }


def deps_for( tmp_path, parts, **more ):
    return { "source_root": lambda args: str( tmp_path ), "context": lambda root: "ctx", "built": lambda args: "built", "build_parts": parts, "close_run": lambda ctx: None, **more }


@pytest.fixture
def quiet( monkeypatch, tmp_path ):
    """Keep the transport from touching a real binary, and give each test an earlier run to copy."""
    monkeypatch.setattr( model_transport, "configure", lambda **kw: None )
    record = saved_run( tmp_path / "old" )
    return record, cli( tmp_path )


def test_a_run_without_a_cli_path_is_refused_before_anything_is_made( tmp_path ):
    with pytest.raises( er.NeedsetError ) as caught: yt.main( argv( tmp_path ), { } )
    assert caught.value.code == er.NO_CLI_PATH and not ( tmp_path / "new" ).exists()


def test_a_missing_saved_file_is_refused_before_the_context_is_built( tmp_path, quiet ):
    ( tmp_path / "old" / yt.SAVED_FILES[ 0 ] ).unlink()
    def no_context( root ): raise AssertionError( "the context must not be built" )
    with pytest.raises( er.NeedsetError ) as caught: yt.main( argv( tmp_path, "--cli-path", quiet[ 1 ] ), deps_for( tmp_path, fake_parts( { } ), context=no_context ) )
    assert caught.value.code == er.SAVED_FILE_MISSING


def test_without_live_main_rebuilds_the_needs_and_reports_the_plan_with_no_call( tmp_path, quiet ):
    record, binary = quiet
    answers = { s: ( SavedAnswerMissing if i == 0 else None if i == 1 else need( i ) ) for i, s in enumerate( record[ "yield" ][ "order" ] ) }
    out = yt.main( argv( tmp_path, "--cli-path", binary ), deps_for( tmp_path, fake_parts( answers ) ) )
    assert out[ "live" ] is False and out[ "plan" ][ "needs" ] == 98 and out[ "plan" ][ "unsaved" ] == [ record[ "yield" ][ "order" ][ 0 ] ]
    assert not ( tmp_path / "new" / yt.REPORT_FILE ).exists() and not ( tmp_path / "new" / yt.CALLS_FILE ).exists()
    assert yt.exit_status( out ) == 0


def test_a_live_run_with_an_unsaved_seed_stops_before_it_spends_anything( tmp_path, quiet ):
    record, binary = quiet
    answers = { s: ( SavedAnswerMissing if i == 0 else need( i ) ) for i, s in enumerate( record[ "yield" ][ "order" ] ) }
    closed = []
    out = yt.main( argv( tmp_path, "--cli-path", binary, "--live" ), deps_for( tmp_path, fake_parts( answers ), close_run=lambda ctx: closed.append( ctx ) or "run-x" ) )
    assert out[ "live" ] is True and out[ "report" ][ "status" ] == yt.STOPPED and out[ "report" ][ "used" ] == 0 and "1 seeds have no saved answer" in out[ "report" ][ "report" ][ "reason" ]
    assert closed == [ "ctx" ] and out[ "closed_run" ] == "run-x" and out[ "close_error" ] is None and yt.exit_status( out ) == 0


def test_a_live_run_with_no_needs_at_all_stops_and_says_so( tmp_path, quiet ):
    record, binary = quiet
    out = yt.main( argv( tmp_path, "--cli-path", binary, "--live" ), deps_for( tmp_path, fake_parts( { s: None for s in record[ "yield" ][ "order" ] } ) ) )
    assert out[ "report" ][ "status" ] == yt.STOPPED and out[ "report" ][ "report" ][ "reason" ] == "no seed gave a need"


def test_a_live_run_traces_the_needs_under_the_cap_and_closes_the_spend_run( tmp_path, quiet ):
    record, binary = quiet
    answers = { s: need( i ) for i, s in enumerate( record[ "yield" ][ "order" ] ) }
    async def trace( needs ):
        for _ in needs[ :2 ]: model_transport.CHARGE_HOOK( "claude-opus-5-5" )
        return [ trace_record( i, loss_trace.FOUND if i % 2 else loss_trace.NOT_RETRIEVED ) for i in range( len( needs ) ) ]
    out = yt.main( argv( tmp_path, "--cli-path", binary, "--live" ), deps_for( tmp_path, fake_parts( answers, trace ), close_run=lambda ctx: "run-y" ) )
    report = out[ "report" ]
    assert report[ "status" ] == yt.DONE and report[ "used" ] == 2 and report[ "by_stage" ] == { yt.YIELD_TRACE: 2 } and report[ "report" ][ "members" ] == 100
    assert out[ "closed_run" ] == "run-y" and yt.exit_status( out ) == 0 and ( tmp_path / "new" / yt.REPORT_FILE ).is_file()


def test_a_close_that_fails_after_a_clean_run_is_reported_and_exits_one( tmp_path, quiet ):
    record, binary = quiet
    def bad_close( ctx ): raise RuntimeError( "ledger locked" )
    out = yt.main( argv( tmp_path, "--cli-path", binary, "--live" ), deps_for( tmp_path, fake_parts( { s: None for s in record[ "yield" ][ "order" ] } ), close_run=bad_close ) )
    assert out[ "closed_run" ] is None and "ledger locked" in out[ "close_error" ] and yt.exit_status( out ) == 1


def test_an_error_while_rebuilding_closes_the_run_and_never_replaces_the_error( tmp_path, quiet, capsys ):
    record, binary = quiet
    def boom( ctx ): raise RuntimeError( "close also failed" )
    async def make( seed_id ): raise ValueError( "index unreadable" )
    parts = lambda *a: { "make_need": make, "trace_fn": None, "tally": stage_parts.Tally() }
    with pytest.raises( ValueError, match = "index unreadable" ): yt.main( argv( tmp_path, "--cli-path", binary, "--live" ), deps_for( tmp_path, parts, close_run=boom ) )
    assert "close_run failed while another error was raised" in capsys.readouterr().out


def test_without_deps_main_uses_the_real_worktree_context_index_parts_and_closer( tmp_path, quiet, monkeypatch ):
    record, binary = quiet
    seen = { }
    monkeypatch.setattr( source_at, "ensure_worktree", lambda repo, commit: seen.setdefault( "made", str( tmp_path ) ) )
    monkeypatch.setattr( source_at, "unlock", lambda repo, dest: seen.setdefault( "unlocked", dest ) )
    monkeypatch.setattr( rt, "context_from_environment", lambda root: "ctx" )
    monkeypatch.setattr( rt, "close_run", lambda ctx: "run-z" )
    monkeypatch.setattr( yt.smoke, "index_parts", lambda root, folder: seen.setdefault( "index", folder ) )
    monkeypatch.setattr( stage_parts, "build_parts", fake_parts( { s: None for s in record[ "yield" ][ "order" ] } ) )
    out = yt.main( argv( tmp_path, "--cli-path", binary, "--live" ), None )
    assert out[ "closed_run" ] == "run-z" and seen[ "unlocked" ] == str( tmp_path ) and seen[ "index" ] == str( tmp_path / "new" / "index" )


def test_the_exit_status_is_zero_for_a_plan_and_a_stop_one_for_a_failure_and_three_for_the_cap_or_the_budget():
    run = lambda status, close_error=None: { "live": True, "close_error": close_error, "report": { "status": status } }
    assert yt.exit_status( { "live": False } ) == 0 and yt.exit_status( run( yt.DONE ) ) == 0 and yt.exit_status( run( yt.STOPPED ) ) == 0
    assert yt.exit_status( run( yt.FAILED ) ) == 1 and yt.exit_status( run( yt.DONE, "boom" ) ) == 1
    assert yt.exit_status( run( yt.CAP ) ) == 3 and yt.exit_status( run( yt.BUDGET ) ) == 3


def test_run_cli_prints_the_result_as_json_and_returns_the_status( tmp_path, quiet ):
    record, binary = quiet
    lines = []
    status = yt.run_cli( argv( tmp_path, "--cli-path", binary ), deps_for( tmp_path, fake_parts( { s: None for s in record[ "yield" ][ "order" ] } ) ), out=lines.append )
    assert status == 0 and json.loads( lines[ 0 ] )[ "live" ] is False
