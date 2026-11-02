"""
The forced-shortlist judge, run on fakes: no model call, no search, no spend ledger.

A plan reads files only. A live run asks the judge about each missed plant in a pack of its own and writes its report.
"""
import json
import os
import types
from unittest import mock

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from cosa.repo.doc_lint import model_transport
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import forced_judge as fj
from lupin_mcp.reuse_needset import first_thousand, source_at
from lupin_mcp.reuse_seeded_miss_e2e import SavedAnswerMissing
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_needset_expansion_run import cli, old_run          # old_run is a fixture: the earlier run folder


@pytest.fixture( autouse=True )
def restore_environment():
    """Ensures: os.environ is restored after each test, since main writes into it."""
    with mock.patch.dict( os.environ ): yield

ENV = "export LUPIN_REUSE_JEV_PACK_SIZE=50\nexport LUPIN_REUSE_JEV_TOKEN_CEILING=60000000\nexport LUPIN_REUSE_JEV_RUN_NAME=needset-x\n"


def label( choice ): return { "choice": choice, "note": "", "ts": "t" }


def test_resolved_label_takes_the_two_raters_when_they_agree_and_the_third_when_they_differ():
    sym, none = label( "A" ), label( "NONE" )
    assert fj.resolved_label( sym, sym, None ) == fj.SAME_JOB and fj.resolved_label( none, none, None ) == fj.NOT_SAME
    assert fj.resolved_label( sym, none, none ) == fj.NOT_SAME and fj.resolved_label( none, sym, sym ) == fj.SAME_JOB
    assert fj.resolved_label( sym, none, None ) == fj.UNRESOLVED and fj.resolved_label( None, sym, sym ) == fj.UNRESOLVED and fj.resolved_label( sym, None, sym ) == fj.UNRESOLVED


def pair( n ):
    return { "original": { "id": f"d-o{n}", "file": f"src/o{n}.py", "name": f"o{n}", "lang": "py" }, "rewrite": { "id": f"d-r{n}", "file": f"src/r{n}.py", "name": f"r{n}", "lang": "ts" } }


def test_pair_labels_look_each_pair_up_in_the_key_and_leave_a_pair_with_no_item_unresolved():
    key = { "pair-1": { "a": "d-r1", "b": "d-o1" }, "pair-2": { "a": "d-o2", "b": "d-r2" } }
    sym, none = label( "A" ), label( "NONE" )
    out = fj.pair_labels( [ pair( 1 ), pair( 2 ), pair( 3 ) ], key, { "pair-1": sym, "pair-2": none }, { "pair-1": sym, "pair-2": none }, { } )
    assert out == { "d-r1": fj.SAME_JOB, "d-r2": fj.NOT_SAME, "d-r3": fj.UNRESOLVED }


def test_missed_ids_reads_the_control_stages_missed_list( tmp_path ):
    path = tmp_path / "r.json"; path.write_text( json.dumps( { "stages": { "control": { "report": { "missed": [ "d-r2", "d-r1" ] } } } } ), encoding="utf-8" )
    assert fj.missed_ids( path ) == [ "d-r2", "d-r1" ]


def test_frozen_needs_keeps_the_drafts_that_passed_and_drops_unsaved_and_failed_ones( monkeypatch ):
    outcome = { "d-r1": { "ok": True, "need": "need one" }, "d-r2": "missing", "d-r3": { "ok": False } }
    def draft_need( job, ask, ledger, max_tries=None ):
        if outcome[ job[ "keys" ][ 0 ][ "id" ] ] == "missing": raise SavedAnswerMissing( "no answer" )
        return outcome[ job[ "keys" ][ 0 ][ "id" ] ]
    monkeypatch.setattr( fj.draft, "draft_need", draft_need )
    monkeypatch.setattr( fj.first_thousand, "control_job", lambda p, strip_fn: { "keys": [ { "id": p[ "rewrite" ][ "id" ] } ] } )
    assert fj.frozen_needs( [ pair( 1 ), pair( 2 ), pair( 3 ) ], None, None ) == { "d-r1": "need one" }


def test_build_rows_keeps_the_missed_drafted_pairs_in_file_order_and_lists_the_undrafted():
    rows, undrafted = fj.build_rows( [ pair( 1 ), pair( 2 ), pair( 3 ), pair( 4 ) ], { "d-r3", "d-r1", "d-r4" }, { "d-r1": "n1", "d-r2": "n2", "d-r3": "n3" },
                                     { "d-r1": fj.SAME_JOB, "d-r3": fj.NOT_SAME, "d-r4": fj.SAME_JOB } )
    assert [ r[ "id" ] for r in rows ] == [ "d-r1", "d-r3" ] and undrafted == [ "d-r4" ] and rows[ 1 ] == { "pair": pair( 3 ), "id": "d-r3", "lang": "ts", "label": fj.NOT_SAME, "need": "n3" }


def test_forced_ids_keep_the_first_127_real_places_and_say_whether_the_plant_was_already_in():
    ranking = [ f"i{n}" for n in range( 300 ) ]
    real, was_in = fj.forced_ids( ranking, "plant" )
    assert real == ranking[ :127 ] and was_in is False
    real, was_in = fj.forced_ids( ranking, "i5" )
    assert was_in is True and "i5" not in real and len( real ) == 127 and real[ 5 ] == "i6"
    assert fj.forced_ids( ranking, "i200" )[ 1 ] is False


def routed_with( *answers ): return { "sw": { "answers": list( answers ) } }


def answer( rid, reuse, extend, unrelated ): return { "id": rid, "probabilities": { "reuse": reuse, "extend": extend, "unrelated": unrelated } }


def test_plant_answer_reads_p_overlap_against_the_policy_threshold_and_names_a_missing_or_malformed_answer():
    policy = rt.vd.POLICY
    yes = fj.plant_answer( routed_with( answer( "p", 0.6, 0.2, 0.2 ) ), "p", policy )
    assert yes == { "answered": True, "p_overlap": 0.8, "confidence": 0.6, "choice": "reuse", "accepted": True }
    assert fj.plant_answer( routed_with( answer( "p", 0.1, 0.1, 0.8 ) ), "p", policy )[ "accepted" ] is False
    gone = { "answered": False, "p_overlap": None, "confidence": None, "choice": None, "accepted": False }
    assert fj.plant_answer( routed_with( answer( "q", 1, 0, 0 ) ), "p", policy ) == gone
    assert fj.plant_answer( routed_with( { "id": "p", "probabilities": { } } ), "p", policy ) == gone
    assert fj.plant_answer( routed_with( answer( "p", 1, 0, 0 ), answer( "p", 1, 0, 0 ) ), "p", policy ) == gone


class FakeStage:
    """A planted stage that answers a fixed fused order and remembers what it was asked."""
    def __init__( self, ranking ): self.ranking, self.asked = ranking, [ ]
    def shortlist( self, ranking_text, entries, sha, pages, exclude_id=None, index_manifest=None ):
        self.asked.append( ( ranking_text, exclude_id, index_manifest ) ); return { "ranking": self.ranking }


def entries_of_pool():
    """Entries in two languages, the seed among them, and a plant."""
    return [ { "id": f"py{n}", "lang": "py" } for n in range( 200 ) ] + [ { "id": "seed", "lang": "py" }, { "id": "ts0", "lang": "ts" } ]


def test_judge_row_asks_the_127_real_places_then_the_plant_alone_and_reports_the_answer():
    row = { "pair": pair( 1 ), "id": "plant", "lang": "py", "label": fj.SAME_JOB, "need": "a need" }
    row[ "pair" ] = { **pair( 1 ), "original": { **pair( 1 )[ "original" ], "id": "seed" }, "rewrite": { **pair( 1 )[ "rewrite" ], "id": "plant" } }
    stage = FakeStage( [ "ts0" ] + [ f"py{n}" for n in range( 200 ) ] )
    calls = [ ]
    def route( ctx, sent, pool, flags, policy=None, candidate_ids=None ): calls.append( ( "route", sent, [ e[ "id" ] for e in pool ], candidate_ids ) ); return "first"
    def widen( ctx, first, sent, pool, flags, extra, policy=None ): calls.append( ( "widen", first, extra ) ); return routed_with( answer( "plant", 0.5, 0.3, 0.2 ) )
    prepared = ( set(), entries_of_pool() + [ { "id": "plant", "lang": "py" } ], "sha", None )
    out = fj.judge_row( row, types.SimpleNamespace( pages = [ ] ), stage, prepared, rt.in_language, route=route, widen=widen )
    assert out == { "id": "plant", "label": fj.SAME_JOB, "lang": "py", "was_in_shortlist": False, "answered": True, "p_overlap": 0.8, "confidence": 0.5, "choice": "reuse", "accepted": True }
    kind, sent, pool_ids, real = calls[ 0 ]
    assert sent == "a need" and real == [ f"py{n}" for n in range( 127 ) ] and "seed" not in pool_ids and "ts0" not in pool_ids and "plant" in pool_ids
    assert calls[ 1 ] == ( "widen", "first", [ "plant" ] ) and stage.asked[ 0 ][ 1 ] == "seed" and stage.asked[ 0 ][ 2 ] is None


def test_judge_row_asks_nothing_when_the_real_shortlist_already_held_the_plant():
    row = { "pair": { **pair( 1 ), "original": { **pair( 1 )[ "original" ], "id": "seed" } }, "id": "py3", "lang": "py", "label": fj.NOT_SAME, "need": "a need" }
    def never( *a, **k ): raise AssertionError( "nothing is asked for a plant the real shortlist held" )
    out = fj.judge_row( row, types.SimpleNamespace( pages = [ ] ), FakeStage( [ f"py{n}" for n in range( 10 ) ] ), ( set(), entries_of_pool(), "sha", None ), rt.in_language, route=never, widen=never )
    assert out[ "was_in_shortlist" ] is True and out[ "accepted" ] is None and out[ "answered" ] is None


def test_summarize_counts_accepts_by_label_and_keeps_already_in_pairs_apart():
    results = [ { "label": "same_job", "was_in_shortlist": False, "answered": True, "accepted": True }, { "label": "same_job", "was_in_shortlist": False, "answered": True, "accepted": False },
                { "label": "same_job", "was_in_shortlist": True, "answered": None, "accepted": None }, { "label": "not_same", "was_in_shortlist": False, "answered": False, "accepted": False } ]
    assert fj.summarize( results ) == { "not_same": { "pairs": 1, "already_in": 0, "answered": 0, "accepted": 0 }, "same_job": { "pairs": 3, "already_in": 1, "answered": 2, "accepted": 1 } }


def test_plan_of_counts_the_pairs_by_label_and_four_requests_for_each():
    rows = [ { "label": "same_job" }, { "label": "same_job" }, { "label": "not_same" } ]
    assert fj.plan_of( rows, [ "u" ], 100 ) == { "pairs": 3, "by_label": { "not_same": 1, "same_job": 2 }, "undrafted": [ "u" ], "requests_needed": 12, "stage_budget": 100 }


def row_of( n ): return { "id": f"r{n}", "label": fj.SAME_JOB }


def result_of( row ): model_transport.CHARGE_HOOK( "m" ); return { "label": row[ "label" ], "was_in_shortlist": False, "answered": True, "accepted": True, "id": row[ "id" ] }


def test_run_live_charges_each_request_to_the_forced_judge_stage_and_writes_the_report( tmp_path ):
    before = model_transport.CHARGE_HOOK
    out = fj.run_live( str( tmp_path ), [ row_of( 1 ), row_of( 2 ) ], result_of, 10, 5 )
    assert out[ "status" ] == fj.DONE and out[ "by_stage" ] == { fj.STAGE_NAME: 2 } and out[ "summary" ][ "same_job" ][ "accepted" ] == 2 and model_transport.CHARGE_HOOK is before
    assert json.loads( ( tmp_path / fj.REPORT_FILE ).read_text( encoding="utf-8" ) ) == out


def test_run_live_keeps_the_finished_rows_when_the_budget_or_the_cap_ends_it_and_marks_a_named_failure( tmp_path ):
    for name, limit, budget, status in ( ( "a", 10, 1, fj.BUDGET_HIT ), ( "b", 1, 5, fj.CAP ) ):
        ( tmp_path / name ).mkdir()
        out = fj.run_live( str( tmp_path / name ), [ row_of( 1 ), row_of( 2 ) ], result_of, limit, budget )
        assert out[ "status" ] == status and len( out[ "results" ] ) == 1
    ( tmp_path / "c" ).mkdir()
    def odd( row ): raise er.NeedsetError( er.BAD_NEED, "odd" )
    assert fj.run_live( str( tmp_path / "c" ), [ row_of( 1 ) ], odd, 10, 5 )[ "status" ] == fj.FAILED


def test_run_live_writes_the_report_then_raises_an_error_that_is_not_a_named_one( tmp_path ):
    def boom( row ): raise KeyError( "x" )
    with pytest.raises( KeyError ): fj.run_live( str( tmp_path ), [ row_of( 1 ) ], boom, 10, 5 )
    assert json.loads( ( tmp_path / fj.REPORT_FILE ).read_text( encoding="utf-8" ) )[ "status" ] == fj.FAILED


def argv( tmp_path, *more ):
    names = ( "root", "run-dir", "from-run", "planted", "answer-key", "labels-dir", "control-report" )
    return [ x for n in names for x in ( "--" + n, str( tmp_path / ( "new" if n == "run-dir" else "old" if n == "from-run" else n ) ) ) ] + [ "--seed", "1", "--source-commit", "abc", *more ]


def test_the_command_line_defaults_are_a_plan_with_a_budget_of_100_and_a_ceiling_of_8_million( tmp_path ):
    args = fj.parse_args( argv( tmp_path ) )
    assert args.live is False and args.budget == args.limit == fj.BUDGET == 100 and args.ceiling == 8_000_000 and args.run_name is None
    assert fj.parse_args( argv( tmp_path, "--live", "--run-name", "r" ) ).run_name == "r"


def fake_rows( args, root ): return [ pair( 1 ) ], [ { "pair": pair( 1 ), "id": "d-r1", "lang": "ts", "label": fj.SAME_JOB, "need": "n" } ], [ "u1" ]


def deps_for( tmp_path, **more ):
    return { "source_root": lambda args: str( tmp_path ), "rows": fake_rows, "close_run": lambda ctx: None, **more }


def test_a_run_without_a_cli_path_or_a_live_run_without_a_run_name_is_refused_first( tmp_path, old_run ):
    with pytest.raises( er.NeedsetError ) as caught: fj.main( argv( tmp_path ), { } )
    assert caught.value.code == er.NO_CLI_PATH and not ( tmp_path / "new" ).exists()
    with pytest.raises( er.NeedsetError ) as caught: fj.main( argv( tmp_path, "--cli-path", old_run, "--live" ), { } )
    assert caught.value.code == er.BAD_NEED and not ( tmp_path / "new" ).exists()


def test_a_missing_saved_file_is_refused_before_any_rows_are_read( tmp_path, old_run ):
    ( tmp_path / "old" / "ledger-control-draft.jsonl" ).unlink()
    def no_rows( args, root ): raise AssertionError( "rows must not be read" )
    with pytest.raises( er.NeedsetError ) as caught: fj.main( argv( tmp_path, "--cli-path", old_run ), deps_for( tmp_path, rows=no_rows ) )
    assert caught.value.code == er.SAVED_FILE_MISSING


def test_without_live_main_plans_from_files_and_builds_no_context( tmp_path, old_run ):
    def no_context( root ): raise AssertionError( "a plan builds no context" )
    out = fj.main( argv( tmp_path, "--cli-path", old_run ), deps_for( tmp_path, context=no_context ) )
    assert out[ "live" ] is False and out[ "plan" ][ "pairs" ] == 1 and out[ "plan" ][ "requests_needed" ] == 4 and out[ "plan" ][ "undrafted" ] == [ "u1" ]
    assert not ( tmp_path / "new" / fj.REPORT_FILE ).exists() and fj.exit_status( out ) == 0


def test_a_live_run_sets_the_run_name_and_ceiling_judges_each_row_and_closes_the_spend_run( tmp_path, old_run, monkeypatch ):
    import os
    seen, closed = [ ], [ ]
    ctx = types.SimpleNamespace()
    out = fj.main( argv( tmp_path, "--cli-path", old_run, "--live", "--run-name", "fresh-run", "--ceiling", "5000000" ),
                   deps_for( tmp_path, context=lambda root: ctx, judge=lambda c: lambda row: seen.append( row[ "id" ] ) or result_of( row ), close_run=lambda c: closed.append( c ) or "fresh-run" ) )
    assert seen == [ "d-r1" ] and out[ "report" ][ "status" ] == fj.DONE and out[ "closed_run" ] == "fresh-run" and closed == [ ctx ] and fj.exit_status( out ) == 0
    assert os.environ[ rt.RUN_NAME_VARIABLE ] == "fresh-run" and os.environ[ rt.CEILING_VARIABLE ] == "5000000" and os.environ[ rt.PACK_SIZE_VARIABLE ] == "50"


def test_a_failed_close_after_a_clean_live_run_is_reported_and_exits_one( tmp_path, old_run ):
    def bad_close( ctx ): raise RuntimeError( "ledger locked" )
    out = fj.main( argv( tmp_path, "--cli-path", old_run, "--live", "--run-name", "r2" ), deps_for( tmp_path, context=lambda root: None, judge=lambda c: result_of, close_run=bad_close ) )
    assert out[ "closed_run" ] is None and "ledger locked" in out[ "close_error" ] and fj.exit_status( out ) == 1


def test_an_error_in_a_live_run_closes_the_spend_run_and_never_replaces_the_error( tmp_path, old_run, capsys ):
    def boom( ctx ): raise RuntimeError( "close also failed" )
    def judge( c ): return lambda row: ( _ for _ in () ).throw( KeyError( "x" ) )
    with pytest.raises( KeyError ): fj.main( argv( tmp_path, "--cli-path", old_run, "--live", "--run-name", "r3" ), deps_for( tmp_path, context=lambda root: None, judge=judge, close_run=boom ) )
    assert "close_run failed while another error was raised" in capsys.readouterr().out


def test_without_deps_main_builds_the_planted_stage_the_pool_and_the_judge_from_the_real_parts( tmp_path, old_run, monkeypatch ):
    seen = { }
    class Ctx:
        candidate_stage = "live stage"; policy = None; pages = [ ]
    monkeypatch.setattr( source_at, "ensure_worktree", lambda repo, commit: str( tmp_path ) )
    monkeypatch.setattr( source_at, "unlock", lambda repo, dest: seen.setdefault( "unlocked", dest ) )
    monkeypatch.setattr( rt, "context_from_environment", lambda root: Ctx() )
    monkeypatch.setattr( rt, "close_run", lambda ctx: "run-z" )
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( set(), [ { "id": "py0", "lang": "py" } ], "sha", "gen" ) )
    monkeypatch.setattr( rt, "sendable_report", lambda entries: ( list( entries ), { } ) )
    monkeypatch.setattr( fj.planted_pool, "planted_entry", lambda rec: { "id": rec[ "id" ], "lang": rec[ "lang" ] } )
    monkeypatch.setattr( first_thousand, "planted_stage_for", lambda live, entries, cache: seen.setdefault( "stage", ( live, [ e[ "id" ] for e in entries ], cache ) ) and "stage" )
    def judge_row( row, at, stage, prepared, entries_of, policy ): seen.update( at=at, prepared=prepared, policy=policy ); return result_of( row )
    monkeypatch.setattr( fj, "judge_row", judge_row )
    out = fj.main( argv( tmp_path, "--cli-path", old_run, "--live", "--run-name", "r4" ), { "rows": fake_rows } )
    assert out[ "closed_run" ] == "run-z" and seen[ "unlocked" ] == str( tmp_path ) and seen[ "stage" ] == ( "live stage", [ "d-r1" ], str( tmp_path / "new" / fj.CACHE_DIR ) )
    flags, pool, planted_sha, gen = seen[ "prepared" ]
    assert [ e[ "id" ] for e in pool ] == [ "py0", "d-r1" ] and len( planted_sha ) == 32 and seen[ "at" ].candidate_stage == "stage" and seen[ "policy" ] is rt.vd.POLICY


def test_a_context_policy_is_used_for_the_judge_when_it_has_one( tmp_path, old_run, monkeypatch ):
    seen = { }
    class Ctx:
        candidate_stage = "live"; policy = { "threshold": 0.9 }; pages = [ ]
    monkeypatch.setattr( rt, "context_from_environment", lambda root: Ctx() )
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( set(), [ ], "sha", None ) )
    monkeypatch.setattr( rt, "sendable_report", lambda entries: ( [ ], { } ) )
    monkeypatch.setattr( fj.planted_pool, "planted_entry", lambda rec: { "id": rec[ "id" ] } )
    def judge_row( row, at, stage, prepared, entries_of, policy ): seen[ "policy" ] = policy; return result_of( row )
    monkeypatch.setattr( fj, "judge_row", judge_row )
    fj.main( argv( tmp_path, "--cli-path", old_run, "--live", "--run-name", "r5" ), deps_for( tmp_path, stage=lambda live, entries, cache: "stage", close_run=lambda c: None ) | { "rows": fake_rows } )
    assert seen[ "policy" ] == { "threshold": 0.9 }


def test_collect_rows_reads_the_missed_pairs_their_frozen_drafts_and_their_resolved_labels( tmp_path, monkeypatch ):
    old = tmp_path / "old"; old.mkdir()
    ( old / "key.json" ).write_text( json.dumps( { "items": { "pair-1": { "a": "d-r1", "b": "d-o1" }, "pair-2": { "a": "d-r2", "b": "d-o2" } } } ), encoding="utf-8" )
    ( old / "report.json" ).write_text( json.dumps( { "stages": { "control": { "report": { "missed": [ "d-r2" ] } } } } ), encoding="utf-8" )
    rows = lambda name, choice: ( old / name ).write_text( "".join( json.dumps( { "item_id": i, "choice": choice, "note": "", "ts": "t" } ) + "\n" for i in ( "pair-1", "pair-2" ) ), encoding="utf-8" )
    rows( "labels-rick.jsonl", "A" ); rows( "labels-rick-redo.jsonl", "A" ); rows( "labels-reviewer-2.jsonl", "A" ); rows( "labels-jason.jsonl", "NONE" )
    monkeypatch.setattr( fj.positive_control, "load_pairs", lambda path, sha: [ pair( 1 ), pair( 2 ) ] )
    monkeypatch.setattr( fj.draft, "make_ledger", lambda path, cli, server: None )
    monkeypatch.setattr( fj, "frozen_needs", lambda pairs, ledger, strip_fn: { "d-r1": "n1", "d-r2": "n2" } )
    args = types.SimpleNamespace( planted = "p", answer_key = str( old / "key.json" ), labels_dir = str( old ), control_report = str( old / "report.json" ), run_dir = str( tmp_path ), cli_path = "c", server = "s" )
    pairs, got, undrafted = fj.collect_rows( args, str( tmp_path ), { "planted_sha": "x" } )
    assert len( pairs ) == 2 and [ r[ "id" ] for r in got ] == [ "d-r2" ] and got[ 0 ][ "label" ] == fj.SAME_JOB and undrafted == [ ]
    fj.collect_rows( args, str( tmp_path ), { } )


def test_run_cli_prints_the_result_as_json_and_returns_the_status( tmp_path, old_run ):
    lines = [ ]
    assert fj.run_cli( argv( tmp_path, "--cli-path", old_run ), deps_for( tmp_path ), out=lines.append ) == 0 and json.loads( lines[ 0 ] )[ "plan" ][ "pairs" ] == 1


def test_a_plan_leaves_a_real_spend_ledger_byte_identical_and_builds_no_context( tmp_path, old_run, monkeypatch ):
    root = make_lupin_repo( tmp_path )
    led  = rl.AccountLedger.create( tmp_path / "ledger.jsonl", limit_tokens=100_000_000, by="t", why="fixture" )
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" ); monkeypatch.setenv( "LUPIN_REUSE_LEDGER_PATH", str( led.path ) )
    before = led.path.read_bytes()
    fj.main( argv( tmp_path, "--cli-path", old_run ), deps_for( tmp_path, context=lambda r: rt.context_from_environment( root ) ) )
    assert led.path.read_bytes() == before
