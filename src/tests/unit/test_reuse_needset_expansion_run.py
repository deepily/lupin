"""
The need-expansion wiring, run on fakes: no model call, no embedding, no search server.

The plan reads files only. A live run asks the expansion replies through a counted transport and writes its report.
"""
import json
import stat
import types

import pytest

from cosa.repo.doc_lint import harness_runner, model_transport
from cosa.repo.symindex.candidates import candidate_stage, resident
from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import expansion_replay as ex
from lupin_mcp.reuse_needset import expansion_run as xr
from lupin_mcp.reuse_needset import first_thousand, source_at, yield_trace
from lupin_mcp.reuse_seeded_miss_e2e import SavedAnswerMissing

BINDING = "1.0 (Claude Code)|max-plan"
GOOD    = json.dumps( { "paraphrases": [ "one", "two", "three" ], "identifiers": [ "alpha", "beta" ] } )
FUSION  = { "k": 60, "depth": 512, "head": 5 }
CTX     = types.SimpleNamespace()                  # a reuse context with no transport yet
ENV     = "export LUPIN_REUSE_JEV_PACK_SIZE=50\nexport LUPIN_REUSE_JEV_TOKEN_CEILING=60000000\nexport LUPIN_REUSE_JEV_RUN_NAME=needset-x\n# a comment\nexport OTHER=1\n"


class Ledger:
    """A dict standing in for a saved-answer ledger."""
    def __init__( self ): self.rows = { }
    def get( self, key ): return self.rows.get( key )
    def put( self, key, value ): self.rows[ key ] = value


def seed_need( n, symbols=None ):
    return { "id": f"n-{n}", "need": f"need {n}", "write_lang": "py", "key": { "symbols": [ f"k{n}" ] if symbols is None else symbols } }


def test_read_env_file_returns_the_reuse_settings_and_ignores_other_lines( tmp_path ):
    path = tmp_path / "run-env.sh"; path.write_text( ENV, encoding="utf-8" )
    assert xr.read_env_file( path ) == { rt.PACK_SIZE_VARIABLE: "50", rt.CEILING_VARIABLE: "60000000", rt.RUN_NAME_VARIABLE: "needset-x" }


def test_read_env_file_names_the_settings_a_file_lacks( tmp_path ):
    path = tmp_path / "run-env.sh"; path.write_text( "export LUPIN_REUSE_JEV_PACK_SIZE=50\n", encoding="utf-8" )
    with pytest.raises( er.NeedsetError ) as caught: xr.read_env_file( path )
    assert caught.value.code == er.ENV_FILE_INCOMPLETE and rt.RUN_NAME_VARIABLE in caught.value.detail


def test_need_rows_take_the_seed_as_the_known_answer_and_refuse_another_key_shape():
    assert xr.need_rows( "yield", [ seed_need( 1 ) ] ) == [ { "id": "n-1", "group": "yield", "need": "need 1", "known_id": "k1" } ]
    for bad in ( [ ], [ "a", "b" ] ):
        with pytest.raises( er.NeedsetError ) as caught: xr.need_rows( "yield", [ seed_need( 2, bad ) ] )
        assert caught.value.code == er.BAD_NEED


def pair( n ):
    return { "original": { "id": f"d-o{n}", "file": f"src/o{n}.py", "name": f"o{n}", "lang": "py" }, "rewrite": { "id": f"d-r{n}", "file": f"src/r{n}.py", "name": f"r{n}", "lang": "py" } }


def fake_draft( monkeypatch, outcome ):
    """Replace the drafting of a control need with a table of outcomes by rewrite id."""
    def draft_need( job, ask, ledger, max_tries=None ):
        what = outcome[ job[ "keys" ][ 0 ][ "id" ] ]
        if what == "missing": raise SavedAnswerMissing( "no answer" )
        return what
    monkeypatch.setattr( xr.draft, "draft_need", draft_need )
    monkeypatch.setattr( xr.first_thousand, "control_job", lambda p, strip_fn: { "keys": [ { "id": p[ "rewrite" ][ "id" ] } ] } )


def test_control_rows_carry_the_drafted_need_and_the_originals_index_id( monkeypatch ):
    fake_draft( monkeypatch, { "d-r1": { "ok": True, "need": "the control need" }, "d-r2": "missing", "d-r3": { "ok": False } } )
    rows, undrafted = xr.control_rows( [ pair( 1 ), pair( 2 ), pair( 3 ) ], None, Ledger(), None, lambda f, n: "idx." + n )
    assert rows == [ { "id": "d-o1", "group": "control", "need": "the control need", "known_id": "idx.o1" } ] and undrafted == [ "d-r2", "d-r3" ]


def test_control_rows_refuse_an_original_the_index_lacks( monkeypatch ):
    fake_draft( monkeypatch, { "d-r1": { "ok": True, "need": "n" } } )
    with pytest.raises( er.NeedsetError ) as caught: xr.control_rows( [ pair( 1 ) ], None, Ledger(), None, lambda f, n: None )
    assert caught.value.code == er.BAD_NEED and "d-o1" in caught.value.detail


def test_full_resident_returns_every_id_of_a_list_where_the_parent_cuts_at_twenty():
    entries = [ { "id": f"cosa.m{n:02d}.fn", "file": f"src/m{n}.py", "module": "m", "name": f"fn{n}", "sig": "", "doc": "alpha word", "pin": f"p{n}" } for n in range( 30 ) ]
    for cls, size in ( ( resident.ResidentSearch, resident.LIST_HEAD ), ( xr.FullResident, 30 ) ):
        held = cls( "/tmp" ); held.put_stage( "k", entries )
        got = held.search( { "stage_key": "k", "need": "alpha word", "K": 5 } )
        assert len( got[ "lists" ][ "prose" ] ) == size and got[ "list_sizes" ][ "prose" ] == 30
    with pytest.raises( CandidateError ) as caught: xr.FullResident( "/tmp" ).search( { "stage_key": "nope", "need": "x", "K": 5 } )
    assert caught.value.code == "STAGE_UNKNOWN"


def test_full_resident_confines_a_vectors_folder_to_its_root( tmp_path ):
    held = xr.FullResident( str( tmp_path ) ); held.put_stage( "k", [ { "id": "a.b", "file": "f", "module": "a", "name": "b", "sig": "", "doc": "x", "pin": "p" } ] )
    with pytest.raises( CandidateError ) as caught: held.search( { "stage_key": "k", "need": "x", "K": 5, "vectors_dir": "/etc", "query_vectors": { } } )
    assert caught.value.code == "PATH_REFUSED"


def test_full_stage_holds_a_full_resident_over_the_base_vectors( tmp_path ):
    stage = xr.FullStage( str( tmp_path ), str( tmp_path / "qc" ), object(), object() )
    assert isinstance( stage._resident, xr.FullResident )


def test_lists_for_returns_the_whole_ranked_list_of_each_source():
    class Stage:
        def shortlist( self, query, entries, index_sha, pages, K=None ):
            self.args = ( query, entries, index_sha, pages, K )
            return { "lists": { "code": { "size": 3, "head": [ "a", "b", "c" ] }, "vector_concat": { "size": 2, "head": [ "c", "a" ] } } }
    stage = Stage()
    assert xr.lists_for( stage, "E", "sha", "P" )( "a query" ) == { "code": [ "a", "b", "c" ], "vector_concat": [ "c", "a" ] }
    assert stage.args == ( "a query", "E", "sha", "P", ex.SHORTLIST )


def rows3():
    return [ { "id": "r1", "group": "attribution", "need": "n1", "known_id": "k1" }, { "id": "r2", "group": "yield", "need": "n2", "known_id": "k2" },
             { "id": "r3", "group": "yield", "need": "n3", "known_id": "k3" } ]


def test_plan_of_counts_the_rows_by_group_and_the_calls_a_live_run_still_needs():
    ledger = Ledger(); ledger.put( ex.expansion_key( "n1", "m" ), GOOD )
    plan = xr.plan_of( rows3(), [ "u1" ], [ "s1" ], ledger, "m", 140 )
    assert plan == { "rows": 3, "by_group": { "attribution": 1, "yield": 2 }, "undrafted": [ "u1" ], "unsaved": [ "s1" ], "saved_replies": 1,
                     "calls_needed": 2, "stage_budget": 140, "embeddings_needed": 15 }


def counted_ask( reply=GOOD ):
    """An ask that makes one counted call each time, as the real transport does."""
    def ask( system, prompt ): model_transport.CHARGE_HOOK( "claude-fable-5-1" ); return reply
    return ask


def search_fn( query ): return { "code": [ "k1", "k2", "k3", "z" ] }


def test_run_live_charges_each_reply_to_the_expansion_stage_and_writes_the_report( tmp_path ):
    before = model_transport.CHARGE_HOOK
    out = xr.run_live( str( tmp_path ), rows3(), counted_ask(), Ledger(), search_fn, FUSION, 10, 5, "m" )
    assert out[ "status" ] == xr.DONE and out[ "used" ] == 3 and out[ "by_stage" ] == { ex.STAGE_NAME: 3 } and len( out[ "results" ] ) == 3
    assert out[ "summary" ][ "yield" ][ "needs" ] == 2 and model_transport.CHARGE_HOOK is before
    assert json.loads( ( tmp_path / xr.REPORT_FILE ).read_text( encoding="utf-8" ) ) == out


def test_run_live_keeps_the_finished_rows_when_the_stage_budget_or_the_cap_ends_it( tmp_path ):
    ( tmp_path / "a" ).mkdir(); ( tmp_path / "b" ).mkdir()
    out = xr.run_live( str( tmp_path / "a" ), rows3(), counted_ask(), Ledger(), search_fn, FUSION, 10, 2, "m" )
    assert out[ "status" ] == xr.BUDGET and len( out[ "results" ] ) == 2 and out[ "used" ] == 2 and er.STAGE_BUDGET_REACHED in out[ "detail" ]
    out = xr.run_live( str( tmp_path / "b" ), rows3(), counted_ask(), Ledger(), search_fn, FUSION, 1, 5, "m" )
    assert out[ "status" ] == xr.CAP and len( out[ "results" ] ) == 1 and er.CALL_CAP_REACHED in out[ "detail" ]


def test_run_live_writes_the_report_then_raises_an_error_that_is_not_a_named_one( tmp_path ):
    def search( query ): raise CandidateError( "QUERY_VECTOR_MISSING", "no vector" )
    with pytest.raises( CandidateError ): xr.run_live( str( tmp_path ), rows3(), counted_ask(), Ledger(), search, FUSION, 10, 5, "m" )
    written = json.loads( ( tmp_path / xr.REPORT_FILE ).read_text( encoding="utf-8" ) )
    assert written[ "status" ] == xr.FAILED and "CandidateError" in written[ "detail" ] and written[ "results" ] == [ ]


def test_run_live_marks_a_failed_named_error_that_is_neither_the_cap_nor_the_budget( tmp_path ):
    def ask( system, prompt ): raise er.NeedsetError( er.BAD_NEED, "odd" )
    assert xr.run_live( str( tmp_path ), rows3(), ask, Ledger(), search_fn, FUSION, 10, 5, "m" )[ "status" ] == xr.FAILED


def argv( tmp_path, *more ):
    return [ "--root", str( tmp_path ), "--run-dir", str( tmp_path / "new" ), "--from-run", str( tmp_path / "old" ), "--planted", "p.json", "--seed", "1", "--source-commit", "abc", *more ]


def test_the_command_line_defaults_are_a_plan_with_the_budget_as_the_cap( tmp_path ):
    args = xr.parse_args( argv( tmp_path ) )
    assert args.live is False and args.budget == args.limit == ex.BUDGET == 140 and args.cli_path is None
    assert xr.parse_args( argv( tmp_path, "--live", "--budget", "9", "--limit", "20" ) ).limit == 20


def cli( tmp_path ):
    path = tmp_path / "claude"
    path.write_text( "#!/bin/sh\necho '1.0 (Claude Code)'\n", encoding="utf-8" )
    path.chmod( path.stat().st_mode | stat.S_IXUSR )
    return str( path )


@pytest.fixture
def old_run( tmp_path, monkeypatch ):
    """An earlier run folder with every file the copy needs; the transport touches no binary."""
    monkeypatch.setattr( model_transport, "configure", lambda **kw: None )
    old = tmp_path / "old"; old.mkdir()
    for name in yield_trace.SAVED_FILES + xr.EXTRA_FILES: ( old / name ).write_text( ENV if name == "run-env.sh" else "", encoding="utf-8" )
    for name in ( yield_trace.SAVED_FILES[ 0 ], yield_trace.SAVED_FILES[ 1 ], xr.EXTRA_FILES[ 0 ] ): harness_runner.Ledger( str( old / name ), binding=BINDING )
    return cli( tmp_path )


def deps_for( tmp_path, **more ):
    """Stand-ins for the tree, context, rows and close; a test adds the stage and the ask."""
    return { "source_root": lambda args: str( tmp_path ), "context": lambda root: CTX, "close_run": lambda ctx: None,
             "rows": lambda args, root, ctx: ( rows3(), [ "u1" ], [ ] ), **more }


def test_a_run_without_a_cli_path_is_refused_before_anything_is_made( tmp_path ):
    with pytest.raises( er.NeedsetError ) as caught: xr.main( argv( tmp_path ), { } )
    assert caught.value.code == er.NO_CLI_PATH and not ( tmp_path / "new" ).exists()


def test_a_missing_saved_file_or_env_setting_is_refused_before_the_context_is_built( tmp_path, old_run ):
    def no_context( root ): raise AssertionError( "the context must not be built" )
    ( tmp_path / "old" / "run-env.sh" ).unlink()
    with pytest.raises( er.NeedsetError ) as caught: xr.main( argv( tmp_path, "--cli-path", old_run ), deps_for( tmp_path, context=no_context ) )
    assert caught.value.code == er.SAVED_FILE_MISSING
    ( tmp_path / "old" / "run-env.sh" ).write_text( "export LUPIN_REUSE_JEV_PACK_SIZE=50\n", encoding="utf-8" )
    with pytest.raises( er.NeedsetError ) as caught: xr.main( argv( tmp_path, "--cli-path", old_run ), deps_for( tmp_path, context=no_context ) )
    assert caught.value.code == er.ENV_FILE_INCOMPLETE


def test_without_live_main_plans_from_files_and_takes_the_run_name_from_the_env_file( tmp_path, old_run, monkeypatch ):
    monkeypatch.delenv( rt.RUN_NAME_VARIABLE, raising=False )
    def no_ask( system, prompt ): raise AssertionError( "a plan asks nothing" )
    out = xr.main( argv( tmp_path, "--cli-path", old_run ), deps_for( tmp_path, ask=no_ask, stage=lambda ctx: 1 / 0 ) )
    assert out[ "live" ] is False and out[ "plan" ][ "rows" ] == 3 and out[ "plan" ][ "calls_needed" ] == 3 and out[ "plan" ][ "undrafted" ] == [ "u1" ] and out[ "plan" ][ "run_name" ] == "needset-x"
    import os
    assert os.environ[ rt.RUN_NAME_VARIABLE ] == "needset-x" and not ( tmp_path / "new" / xr.REPORT_FILE ).exists() and xr.exit_status( out ) == 0


class FakeStage:
    fusion = None


def test_a_live_run_asks_the_replies_searches_five_ways_and_closes_the_spend_run( tmp_path, old_run ):
    closed = [ ]
    searched = [ ]
    def search( query ): searched.append( query ); return { "code": [ "k1", "k2", "k3" ] }
    out = xr.main( argv( tmp_path, "--cli-path", old_run, "--live" ),
                   deps_for( tmp_path, ask=counted_ask(), stage=lambda ctx: ( FakeStage(), search ), close_run=lambda ctx: closed.append( ctx ) or "run-x" ) )
    assert out[ "live" ] is True and out[ "report" ][ "status" ] == xr.DONE and out[ "report" ][ "used" ] == 3 and len( searched ) == 15
    assert out[ "closed_run" ] == "run-x" and closed == [ CTX ] and out[ "close_error" ] is None and xr.exit_status( out ) == 0


def test_a_failed_close_after_a_clean_live_run_is_reported_and_exits_one( tmp_path, old_run ):
    def bad_close( ctx ): raise RuntimeError( "ledger locked" )
    out = xr.main( argv( tmp_path, "--cli-path", old_run, "--live" ),
                   deps_for( tmp_path, ask=counted_ask(), stage=lambda ctx: ( FakeStage(), search_fn ), close_run=bad_close ) )
    assert out[ "closed_run" ] is None and "ledger locked" in out[ "close_error" ] and xr.exit_status( out ) == 1


def test_an_error_in_a_live_run_closes_the_spend_run_and_never_replaces_the_error( tmp_path, old_run, capsys ):
    def boom( ctx ): raise RuntimeError( "close also failed" )
    def search( query ): raise CandidateError( "QUERY_VECTOR_MISSING", "no vector" )
    with pytest.raises( CandidateError ):
        xr.main( argv( tmp_path, "--cli-path", old_run, "--live" ), deps_for( tmp_path, ask=counted_ask(), stage=lambda ctx: ( FakeStage(), search ), close_run=boom ) )
    assert "close_run failed while another error was raised" in capsys.readouterr().out


def test_without_deps_main_builds_the_real_stage_rows_ask_and_closer( tmp_path, old_run, monkeypatch ):
    seen = { }
    class Live:
        vectors_dir = "/v"; purposes_path = None; K = 128; arm = "B1"; fusion = None; embed_client = "embed"
    class Ctx:
        candidate_stage = Live(); pages = "pages"; transport = None
    monkeypatch.setattr( source_at, "ensure_worktree", lambda repo, commit: str( tmp_path ) )
    monkeypatch.setattr( source_at, "unlock", lambda repo, dest: seen.setdefault( "unlocked", dest ) )
    monkeypatch.setattr( rt, "context_from_environment", lambda root: Ctx() )
    monkeypatch.setattr( rt, "close_run", lambda ctx: "run-z" )
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( None, [ "E" ], "sha", None ) )
    monkeypatch.setattr( xr, "collect_rows", lambda args, root, ctx, deps: ( rows3()[ :1 ], [ ], [ ] ) )
    monkeypatch.setattr( xr.vs, "load_vectors", lambda folder: seen.setdefault( "vectors", folder ) )
    monkeypatch.setattr( xr, "FullStage", lambda *a, **k: seen.setdefault( "stage", FakeStage() ) )
    monkeypatch.setattr( xr, "lists_for", lambda stage, entries, sha, pages: seen.setdefault( "search_args", ( entries, sha, pages ) ) and search_fn )
    monkeypatch.setattr( xr.draft, "drafter_call", lambda: counted_ask() )
    out = xr.main( argv( tmp_path, "--cli-path", old_run, "--live" ), None )
    assert out[ "closed_run" ] == "run-z" and seen[ "unlocked" ] == str( tmp_path ) and seen[ "vectors" ] == "/v" and seen[ "search_args" ] == ( [ "E" ], "sha", "pages" )
    assert out[ "report" ][ "used" ] == 1


def test_collect_rows_rebuilds_attribution_and_yield_needs_then_the_control_rows( tmp_path, monkeypatch ):
    from lupin_mcp.reuse_needset import stage_seeds
    recs   = [ { "id": f"web.m{n:03d}.fn", "file": f"src/web/m{n:03d}.js", "lang": "ts" } for n in range( 130 ) ] + [ { "id": f"cosa.m{n:03d}.fn", "file": f"src/cosa/m{n:03d}.py", "lang": "py" } for n in range( 90 ) ]
    recs.sort( key=lambda r: r[ "id" ] )
    record = stage_seeds.draw_lists( recs, 7, set(), "abc", { r[ "file" ] for r in recs } )
    run = tmp_path / "new"; run.mkdir(); stage_seeds.write_lists( run, record )
    async def make_need( seed_id ): return None if seed_id == record[ "yield" ][ "order" ][ 0 ] else { **seed_need( 1 ), "id": f"n-{seed_id}", "key": { "symbols": [ seed_id ] } }
    monkeypatch.setattr( yield_trace, "live_parts", lambda args, root, ctx, deps: { "make_need": make_need } )
    monkeypatch.setattr( xr.draft, "make_ledger", lambda path, cli, server: Ledger() )
    monkeypatch.setattr( xr.positive_control, "load_pairs", lambda path, sha: [ pair( 1 ) ] )
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( None, [ { "file": "src/o1.py", "name": "o1", "id": "idx.o1" } ], "sha", None ) )
    fake_draft( monkeypatch, { "d-r1": { "ok": True, "need": "control need" } } )
    args = xr.parse_args( argv( tmp_path, "--cli-path", "c" ) )
    args.run_dir = str( run )
    rows, undrafted, unsaved = xr.collect_rows( args, str( tmp_path ), "ctx", { "planted_sha": "x" } )
    groups = [ r[ "group" ] for r in rows ]
    assert groups.count( "attribution" ) == 50 and groups.count( "yield" ) == 99 and groups[ -1 ] == "control" and rows[ -1 ][ "known_id" ] == "idx.o1" and undrafted == [ ] and unsaved == [ ]
    rows2, _, _ = xr.collect_rows( args, str( tmp_path ), "ctx", { } )
    assert rows2[ -1 ][ "group" ] == "control"


def test_the_exit_status_is_zero_for_a_plan_and_a_finish_one_for_a_failure_and_three_for_the_cap_or_the_budget():
    run = lambda status, close_error=None: { "live": True, "close_error": close_error, "report": { "status": status } }
    assert xr.exit_status( { "live": False } ) == 0 and xr.exit_status( run( xr.DONE ) ) == 0
    assert xr.exit_status( run( xr.FAILED ) ) == 1 and xr.exit_status( run( xr.DONE, "boom" ) ) == 1
    assert xr.exit_status( run( xr.CAP ) ) == 3 and xr.exit_status( run( xr.BUDGET ) ) == 3


def test_run_cli_prints_the_result_as_json_and_returns_the_status( tmp_path, old_run ):
    lines = [ ]
    status = xr.run_cli( argv( tmp_path, "--cli-path", old_run ), deps_for( tmp_path ), out=lines.append )
    assert status == 0 and json.loads( lines[ 0 ] )[ "plan" ][ "rows" ] == 3


def test_the_context_gets_a_refusing_transport_in_a_plan_and_in_a_live_run_so_no_spend_run_begins( tmp_path, old_run ):
    from lupin_mcp.reuse_seeded_miss_e2e import NoCallTransport
    for extra in ( [ ], [ "--live" ] ):
        ctx = types.SimpleNamespace()
        xr.main( argv( tmp_path, "--cli-path", old_run, *extra ), deps_for( tmp_path, context=lambda root: ctx, ask=counted_ask(), stage=lambda c: ( FakeStage(), search_fn ) ) )
        assert isinstance( ctx.transport, NoCallTransport )
