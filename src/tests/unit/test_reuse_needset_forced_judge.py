"""
The forced-shortlist judge, run on fakes: no model call, no search, no spend ledger.

A plan reads files only. A live run asks the judge about each missed plant in a pack of its own and writes its report.
The in_pack variant asks about every drafted pair's plant inside the 128 places, in one question.
"""
import json
import os
import threading
import types
from unittest import mock

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from cosa.repo.doc_lint import model_transport
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_pack as rp
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
    def draft_need( job, ask, ledger, model_id, max_tries=None ):
        assert model_id == "claude-sonnet-5-5"      # frozen_needs reads the drafter key once and passes it
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
    assert fj.plan_of( rows, [ "u" ], 100 ) == { "pairs": 3, "by_label": { "not_same": 1, "same_job": 2 }, "undrafted": [ "u" ], "requests_needed": 12, "stage_budget": 100, "variant": fj.ALONE }


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
    args = types.SimpleNamespace( planted = "p", answer_key = str( old / "key.json" ), labels_dir = str( old ), control_report = str( old / "report.json" ), run_dir = str( tmp_path ), cli_path = "c", server = "s", variant = fj.ALONE )
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


# ---- the in_pack variant: the plant asked among the 127 real places, never alone ----

def swept_with( ratings, calls ):
    """
    A sweeper that rates each place it is asked by its id and remembers what it was asked.

    It answers from the ids it receives, so a run that asks different places gets different answers.
    """
    def sweeper( ctx, need, asked, frozen=False, template=None, model=None, gaps=None ):
        calls.append( [ e[ "id" ] for e in asked ] )
        return { "answers": [ { "id": e[ "id" ], "probabilities": ratings.get( e[ "id" ], { "reuse": 0.0, "extend": 0.0, "unrelated": 1.0 } ) } for e in asked ], "failed": [ ], "not_reached": [ ],
                 "attempts_answered": 3, "attempts_failed": 0, "tokens_in": 0, "tokens_out": 0, "usage_missing": 0 }
    return sweeper


def in_pack_world( plant, ratings, policy=None ):
    """
    Build a row, a context, a stage, a pool and the calls list for one plant.

    The plant is asked through the real route and the real verdict.
    """
    calls = [ ]
    row   = { "pair": { **pair( 1 ), "original": { **pair( 1 )[ "original" ], "id": "seed" }, "rewrite": { **pair( 1 )[ "rewrite" ], "id": plant } }, "id": plant, "lang": "py", "label": fj.SAME_JOB, "need": "a need" }
    ctx   = types.SimpleNamespace( pages=[ ], pack_size=40, sweeper=swept_with( ratings, calls ) )
    stage = FakeStage( [ "ts0" ] + [ f"py{n}" for n in range( 200 ) ] )
    pool  = entries_of_pool()
    if plant not in { e[ "id" ] for e in pool }: pool.append( { "id": plant, "lang": "py" } )
    return row, ctx, stage, ( set(), pool, "sha", None ), calls


YES = { "reuse": 0.6, "extend": 0.2, "unrelated": 0.2 }
SURE = { "reuse": 0.9, "extend": 0.0, "unrelated": 0.1 }


def test_the_plant_is_asked_with_the_127_real_places_in_one_question_and_never_alone():
    row, ctx, stage, prepared, calls = in_pack_world( "pz", { "pz": YES } )
    out = fj.judge_row_in_pack( row, ctx, stage, prepared, rt.in_language )
    assert len( calls ) == 1, "one question: a second call would be the plant asked alone or a widened pack"
    assert calls[ 0 ] == sorted( [ f"py{n}" for n in range( 127 ) ] + [ "pz" ] ) and len( calls[ 0 ] ) == 128
    assert "seed" not in calls[ 0 ] and "ts0" not in calls[ 0 ] and "py127" not in calls[ 0 ]
    assert stage.asked[ 0 ][ 1 ] == "seed" and out[ "answered" ] is True and out[ "p_overlap" ] == 0.8 and out[ "accepted" ] is True


def test_the_row_records_where_the_plant_fell_and_how_it_fared_against_the_real_places():
    ratings = { "pz": YES, "py0": SURE, "py1": SURE, "py2": { "reuse": 0.1, "extend": 0.1, "unrelated": 0.8 } }
    row, ctx, stage, prepared, calls = in_pack_world( "pz", ratings )
    out = fj.judge_row_in_pack( row, ctx, stage, prepared, rt.in_language )
    assert out == { "id": "pz", "label": fj.SAME_JOB, "lang": "py", "was_in_shortlist": False, "arm": "baseline", "answered": True, "p_overlap": 0.8, "confidence": 0.6, "choice": "reuse", "accepted": True,
                    "survives": True, "rank": 3, "wrong_at_threshold": 2, "pack_index": 3, "pack_position": 7, "position": 127, "asked": 128 }


def test_a_plant_that_ranks_below_the_cap_is_accepted_but_does_not_survive_it():
    ratings = { "pz": YES, "py0": SURE, "py1": SURE }
    row, ctx, stage, prepared, calls = in_pack_world( "pz", ratings )
    out = fj.judge_row_in_pack( row, ctx, stage, prepared, rt.in_language, policy={ **rt.vd.POLICY, "shortlist": 2 } )
    assert out[ "accepted" ] is True and out[ "survives" ] is False and out[ "rank" ] == 3


def test_a_plant_the_real_shortlist_already_held_is_still_asked_among_the_places():
    row, ctx, stage, prepared, calls = in_pack_world( "py3", { "py3": YES } )
    out = fj.judge_row_in_pack( row, ctx, stage, prepared, rt.in_language )
    assert out[ "was_in_shortlist" ] is True and out[ "answered" ] is True and out[ "accepted" ] is True
    assert len( calls ) == 1 and "py3" in calls[ 0 ] and len( calls[ 0 ] ) == 128 and "py128" not in calls[ 0 ]


def test_pack_place_counts_from_zero_over_the_ids_sorted_as_the_sweep_sorts_them():
    ids = [ f"a{n:03}" for n in range( 128 ) ]
    assert fj.pack_place( ids[ ::-1 ], "a000", 50 ) == { "pack_index": 0, "pack_position": 0, "position": 0, "asked": 128 }
    assert fj.pack_place( ids, "a049", 50 ) == { "pack_index": 0, "pack_position": 49, "position": 49, "asked": 128 }
    assert fj.pack_place( ids, "a050", 50 ) == { "pack_index": 1, "pack_position": 0, "position": 50, "asked": 128 }
    assert fj.pack_place( ids, "a127", 50 ) == { "pack_index": 2, "pack_position": 27, "position": 127, "asked": 128 }


def test_in_pack_figures_read_the_cut_shortlist_the_rank_and_the_wrong_places_at_the_threshold():
    policy = rt.vd.POLICY
    routed = { "sw": { "answers": [ answer( "p", 0.6, 0.2, 0.2 ), answer( "a", 0.9, 0, 0.1 ), answer( "b", 0.5, 0.5, 0 ), answer( "c", 0.1, 0.1, 0.8 ), { "id": "bad", "probabilities": { } } ] }, "d": { "shortlist": [ { "id": "a" }, { "id": "p" } ] } }
    assert fj.in_pack_figures( routed, "p", policy ) == { "survives": True, "rank": 3, "wrong_at_threshold": 2 }
    assert fj.in_pack_figures( { **routed, "d": { "shortlist": [ { "id": "a" } ] } }, "p", policy )[ "survives" ] is False
    assert fj.in_pack_figures( routed, "c", policy ) == { "survives": False, "rank": 4, "wrong_at_threshold": 3 }
    assert fj.in_pack_figures( routed, "bad", policy ) == { "survives": False, "rank": None, "wrong_at_threshold": 3 }
    edge = { "sw": { "answers": [ answer( "p", 0.6, 0.2, 0.2 ), answer( "at", 0.3, 0.0, 0.7 ), answer( "under", 0.29, 0.0, 0.71 ) ] }, "d": { "shortlist": [ ] } }
    assert fj.in_pack_figures( edge, "p", policy )[ "wrong_at_threshold" ] == 1, "0.30 counts, 0.29 does not"
    tie = { "sw": { "answers": [ answer( "z", 0.5, 0.5, 0 ), answer( "m", 0.5, 0.5, 0 ) ] }, "d": { "shortlist": [ ] } }
    assert fj.in_pack_figures( tie, "z", policy )[ "rank" ] == 2, "equal p_overlap goes by id, as the verdict orders it"


def test_summarize_in_pack_counts_accepts_and_survivors_by_arm_repeat_and_label_and_never_pools_cells():
    cell = lambda arm, repeat, label, answered, accepted, survives: { "arm": arm, "repeat": repeat, "label": label, "answered": answered, "accepted": accepted, "survives": survives }
    results = [ cell( "baseline", 1, "same_job", True, True, True ), cell( "baseline", 1, "same_job", True, True, False ), cell( "baseline", 1, "not_same", False, False, False ),
                cell( "baseline", 1, "same_job", True, False, False ), cell( "plant_line", 2, "same_job", True, True, True ) ]
    assert fj.summarize_in_pack( results ) == { "baseline/1": { "not_same": { "pairs": 1, "answered": 0, "accepted": 0, "survived": 0 }, "same_job": { "pairs": 3, "answered": 3, "accepted": 2, "survived": 1 } },
                                                "plant_line/2": { "same_job": { "pairs": 1, "answered": 1, "accepted": 1, "survived": 1 } } }


def test_the_in_pack_plan_needs_three_requests_for_each_pair_and_names_its_variant():
    rows = [ { "label": "same_job" }, { "label": "not_same" } ]
    assert fj.plan_of( rows, [ ], 100, fj.IN_PACK ) == { "pairs": 2, "by_label": { "not_same": 1, "same_job": 1 }, "undrafted": [ ], "requests_needed": 6, "stage_budget": 100, "variant": "in_pack" }
    assert fj.plan_of( rows, [ ], 100, fj.IN_PACK, jobs=[ 1 ] * 8 )[ "requests_needed" ] == 24, "with jobs the count is over the jobs, three requests each"
    assert fj.plan_of( rows, [ ], 100, fj.ALONE, jobs=[ 1 ] * 8 )[ "requests_needed" ] == 8, "the alone variant counts pairs, four requests each"


def test_run_live_counts_the_report_with_the_summary_it_is_given( tmp_path ):
    out = fj.run_live( str( tmp_path ), [ row_of( 1 ) ], result_of, 10, 5, lambda results: { "counted": len( results ) } )
    assert out[ "summary" ] == { "counted": 1 }


def test_the_variant_is_alone_unless_in_pack_is_asked_for( tmp_path ):
    assert fj.parse_args( argv( tmp_path ) ).variant == fj.ALONE and fj.parse_args( argv( tmp_path, "--variant", "in_pack" ) ).variant == fj.IN_PACK
    with pytest.raises( SystemExit ): fj.parse_args( argv( tmp_path, "--variant", "other" ) )


def test_the_in_pack_variant_keeps_every_drafted_pair_and_gives_each_its_plant_line( tmp_path, monkeypatch ):
    old = tmp_path / "old"; old.mkdir()
    ( old / "key.json" ).write_text( json.dumps( { "items": { "pair-1": { "a": "d-r1", "b": "d-o1" }, "pair-2": { "a": "d-r2", "b": "d-o2" } } } ), encoding="utf-8" )
    ( old / "report.json" ).write_text( json.dumps( { "stages": { "control": { "report": { "missed": [ "d-r2" ], "rows": [ { "rewrite": "d-r1", "purpose_line": "Reads a feed." }, { "rewrite": "d-r2", "purpose_line": "" }, { "rewrite": "d-r3" } ] } } } } ), encoding="utf-8" )
    for name in ( "labels-rick.jsonl", "labels-rick-redo.jsonl", "labels-reviewer-2.jsonl", "labels-jason.jsonl" ):
        ( old / name ).write_text( "".join( json.dumps( { "item_id": i, "choice": "A", "note": "", "ts": "t" } ) + "\n" for i in ( "pair-1", "pair-2" ) ), encoding="utf-8" )
    monkeypatch.setattr( fj.positive_control, "load_pairs", lambda path, sha: [ pair( 1 ), pair( 2 ), pair( 3 ) ] )
    monkeypatch.setattr( fj.draft, "make_ledger", lambda path, cli, server: None )
    monkeypatch.setattr( fj, "frozen_needs", lambda pairs, ledger, strip_fn: { "d-r1": "n1", "d-r2": "n2" } )
    args = types.SimpleNamespace( planted = "p", answer_key = str( old / "key.json" ), labels_dir = str( old ), control_report = str( old / "report.json" ), run_dir = str( tmp_path ), cli_path = "c", server = "s", variant = fj.IN_PACK )
    _pairs, got, undrafted = fj.collect_rows( args, str( tmp_path ), { "planted_sha": "x" } )
    assert [ ( r[ "id" ], r[ "plant_line" ] ) for r in got ] == [ ( "d-r1", "Reads a feed." ), ( "d-r2", None ) ] and undrafted == [ "d-r3" ]
    args.variant = fj.ALONE
    alone = fj.collect_rows( args, str( tmp_path ), { "planted_sha": "x" } )[ 1 ]
    assert [ r[ "id" ] for r in alone ] == [ "d-r2" ] and "plant_line" not in alone[ 0 ]


def row_with_line( n, line ): return { "pair": pair( n ), "id": f"d-r{n}", "lang": "ts", "label": fj.SAME_JOB, "need": "n", "plant_line": line }


def test_expand_jobs_makes_a_job_for_each_pair_arm_and_repeat_in_pair_arm_repeat_order_and_skips_a_missing_line():
    jobs, skipped = fj.expand_jobs( [ row_with_line( 1, "A line." ), row_with_line( 2, None ) ] )
    assert [ ( j[ "id" ], j[ "arm" ], j[ "repeat" ] ) for j in jobs ] == [ ( "d-r1", "baseline", 1 ), ( "d-r1", "baseline", 2 ), ( "d-r1", "plant_line", 1 ), ( "d-r1", "plant_line", 2 ),
                                                                              ( "d-r2", "baseline", 1 ), ( "d-r2", "baseline", 2 ) ]
    assert skipped == [ { "pair": "d-r2", "arm": "plant_line", "reason": "plant_has_no_line" } ] and jobs[ 0 ][ "plant_line" ] == "A line." and jobs[ 0 ][ "need" ] == "n"
    one, none = fj.expand_jobs( [ row_with_line( 1, "A line." ) ], arms=( fj.ARM_BASELINE, ), repeats=( 3, ) )
    assert [ ( j[ "arm" ], j[ "repeat" ] ) for j in one ] == [ ( "baseline", 3 ) ] and none == [ ]


def test_sixteen_pairs_with_lines_make_192_requests_of_three_packs_each_two_arms_two_repeats():
    jobs, _ = fj.expand_jobs( [ row_with_line( n, "L." ) for n in range( 16 ) ] )
    assert len( jobs ) == 64 and fj.plan_of( [ ], [ ], fj.IN_PACK_BUDGET, fj.IN_PACK, jobs )[ "requests_needed" ] == fj.IN_PACK_BUDGET == 192


def test_each_arm_and_repeat_has_a_run_index_of_its_own_and_one_or_more():
    assert [ fj.in_pack_run_index( a, r ) for a in fj.IN_PACK_ARMS for r in fj.IN_PACK_REPEATS ] == [ 1, 2, 101, 102 ]


def test_with_plant_line_changes_only_the_plant_and_leaves_the_pool_it_was_given_alone():
    pool  = [ { "id": "a", "pin": "pa" }, { "id": "pz", "pin": "pz-pin", "doc": "d" }, { "id": "b", "pin": "pb" } ]
    after = fj.with_plant_line( pool, { "id": "pz", "plant_line": "Does the thing." } )
    assert after[ 1 ] == { "id": "pz", "pin": "pz-pin", "doc": "d", "purpose": "Does the thing." } and after[ 0 ] is pool[ 0 ] and after[ 2 ] is pool[ 2 ] and "purpose" not in pool[ 1 ]


# ---- arms and repeats through the real sweep: a stand-in transport that answers every question it is sent ----

class Echo:
    """A transport that answers every question in a body, and records the body."""
    def __init__( self ): self.bodies, self.lock = [ ], threading.Lock()
    def post_with_meta( self, body ):
        with self.lock: self.bodies.append( body )
        return { "answers": { key: { "probabilities": dict( YES ) } for key in body[ "questions" ] }, "model": body[ "model" ], "usage": { "input_tokens": 100, "output_tokens": 20 } }, { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 3 }


def real_world( tmp_path, echo ):
    """
    Build a job row, a context, a stage and a pool for the real sweep.

    The pool holds 127 real places and a plant with a pin, and echo answers them.
    """
    place = lambda i, lang="py": { "id": i, "lang": lang, "sig": "()", "doc": f"Does {i}.", "pin": f"pin-{i}" }
    pool  = [ place( f"py{n}" ) for n in range( 200 ) ] + [ place( "seed" ), place( "ts0", "ts" ), place( "pz" ) ]
    row   = { "pair": { **pair( 1 ), "original": { **pair( 1 )[ "original" ], "id": "seed" }, "rewrite": { **pair( 1 )[ "rewrite" ], "id": "pz" } }, "id": "pz", "lang": "py", "label": fj.SAME_JOB, "need": "a need", "plant_line": "Reads a feed." }
    ctx   = rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=echo, pack_size=40 )
    return row, ctx, FakeStage( [ "ts0" ] + [ f"py{n}" for n in range( 200 ) ] ), ( set(), pool, "sha", None )


def test_a_repeat_really_posts_its_packs_even_when_the_production_answers_are_cached( tmp_path ):
    echo = Echo()
    row, ctx, stage, prepared = real_world( tmp_path, echo )
    production = rp.packed_sweeper( 40, shape=rp.SHAPE_WHOLE )
    ctx.sweeper = production
    fj.judge_row_in_pack( row, ctx, stage, prepared, rt.in_language )
    warm = len( echo.bodies )
    assert warm == 4, "128 places in packs of 40 are 4 posts"
    fj.judge_row_in_pack( row, ctx, stage, prepared, rt.in_language )
    assert len( echo.bodies ) == warm, "control: the same question asked the production way again is served from the cache and posts nothing"
    cells = [ ( "baseline", 1 ), ( "baseline", 2 ), ( "plant_line", 1 ), ( "plant_line", 2 ) ]
    for n, ( arm, repeat ) in enumerate( cells, start=1 ):
        out = fj.judge_job( { **row, "arm": arm, "repeat": repeat }, ctx, stage, prepared, rt.in_language )
        assert len( echo.bodies ) == warm + 4 * n, f"{arm} repeat {repeat} must post its 4 packs"
        assert out[ "arm" ] == arm and out[ "repeat" ] == repeat and out[ "answered" ] is True and out[ "asked" ] == 128
    assert ctx.sweeper is production, "the context it was given is not changed"
    hashes = [ rp.pack_key( b ) for b in echo.bodies[ warm: ] ]
    assert len( hashes ) == 16 and len( set( hashes ) ) == 16, "no two cells post the same body"


def test_the_plant_line_arm_sends_the_plant_with_its_line_and_the_baseline_arm_does_not( tmp_path ):
    echo = Echo()
    row, ctx, stage, prepared = real_world( tmp_path, echo )
    fj.judge_job( { **row, "arm": "baseline", "repeat": 1 }, ctx, stage, prepared, rt.in_language )
    plain = len( echo.bodies )
    fj.judge_job( { **row, "arm": "plant_line", "repeat": 1 }, ctx, stage, prepared, rt.in_language )
    sent = lambda bodies: json.dumps( bodies, sort_keys=True )
    assert "Reads a feed." not in sent( echo.bodies[ :plain ] ) and "Reads a feed." in sent( echo.bodies[ plain: ] )
    assert "purpose: Reads a feed." in sent( echo.bodies[ plain: ] )


def test_a_cell_is_asked_with_a_pack_template_that_ends_in_its_run_index_and_the_reading_is_in_the_row( tmp_path ):
    echo = Echo()
    row, ctx, stage, prepared = real_world( tmp_path, echo )
    out = fj.judge_job( { **row, "arm": "plant_line", "repeat": 2 }, ctx, stage, prepared, rt.in_language )
    assert all( "(repeat 102)" in json.dumps( b ) for b in echo.bodies ) and out[ "pack_index" ] == 3 and out[ "pack_position" ] == 7 and out[ "position" ] == 127
    assert out[ "accepted" ] is True and out[ "survives" ] is False and out[ "wrong_at_threshold" ] == 127


def test_a_job_builds_its_sweeper_for_the_contexts_pack_size_its_run_index_and_the_whole_shape( tmp_path ):
    made = [ ]
    def sweeper_for( size, workers, index, shape=None ):
        made.append( ( size, workers, index, shape ) )
        return swept_with( { }, [ ] )
    row, ctx, stage, prepared = real_world( tmp_path, Echo() )
    fj.judge_job( { **row, "arm": "plant_line", "repeat": 2 }, ctx, stage, prepared, rt.in_language, sweeper_for=sweeper_for )
    assert made == [ ( 40, rp.WORKERS_DEFAULT, 102, rp.SHAPE_WHOLE ) ]


def fake_in_pack_rows( args, root ): return [ pair( 1 ) ], [ row_with_line( 1, "A line." ), row_with_line( 2, None ) ], [ "u1" ]


def test_the_in_pack_defaults_are_a_budget_and_cap_of_192_and_a_named_value_wins( tmp_path ):
    assert fj.parse_args( argv( tmp_path, "--variant", "in_pack" ) ).budget == fj.parse_args( argv( tmp_path, "--variant", "in_pack" ) ).limit == 192
    named = fj.parse_args( argv( tmp_path, "--variant", "in_pack", "--budget", "50", "--limit", "60" ) )
    assert ( named.budget, named.limit ) == ( 50, 60 )
    assert fj.parse_args( argv( tmp_path, "--budget", "7" ) ).budget == 7 and fj.parse_args( argv( tmp_path ) ).limit == 100


def test_an_in_pack_plan_lists_the_arms_repeats_jobs_and_what_it_skipped_and_counts_192_style_requests( tmp_path, old_run ):
    plan = fj.main( argv( tmp_path, "--cli-path", old_run, "--variant", "in_pack" ), deps_for( tmp_path, rows=fake_in_pack_rows ) )[ "plan" ]
    assert plan[ "variant" ] == "in_pack" and plan[ "arms" ] == [ "baseline", "plant_line" ] and plan[ "repeats" ] == [ 1, 2 ]
    assert plan[ "jobs" ] == 6 and plan[ "requests_needed" ] == 18 and plan[ "stage_budget" ] == 192 and plan[ "pairs" ] == 2
    assert plan[ "skipped" ] == [ { "pair": "d-r2", "arm": "plant_line", "reason": "plant_has_no_line" } ]
    alone = fj.main( argv( tmp_path, "--cli-path", old_run ), deps_for( tmp_path ) )[ "plan" ]
    assert "arms" not in alone and "jobs" not in alone


def test_a_live_in_pack_run_judges_each_job_with_the_job_judge_and_reports_by_arm_and_repeat( tmp_path, old_run, monkeypatch ):
    seen = [ ]
    class Ctx:
        candidate_stage = "live"; policy = None; pages = [ ]
    monkeypatch.setattr( rt, "context_from_environment", lambda root: Ctx() )
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( set(), [ ], "sha", None ) )
    monkeypatch.setattr( rt, "sendable_report", lambda entries: ( [ ], { } ) )
    monkeypatch.setattr( fj.planted_pool, "planted_entry", lambda rec: { "id": rec[ "id" ] } )
    def job_judge( job, at, stage, prepared, entries_of, policy ): seen.append( ( job[ "id" ], job[ "arm" ], job[ "repeat" ] ) ); return { "label": job[ "label" ], "id": job[ "id" ], "arm": job[ "arm" ], "repeat": job[ "repeat" ], "answered": True, "accepted": True, "survives": True }
    def alone( *a, **k ): raise AssertionError( "the alone judge must not run for the in_pack variant" )
    monkeypatch.setattr( fj, "judge_job", job_judge )
    monkeypatch.setattr( fj, "judge_row", alone )
    out = fj.main( argv( tmp_path, "--cli-path", old_run, "--live", "--run-name", "r6", "--variant", "in_pack" ), deps_for( tmp_path, rows=fake_in_pack_rows, stage=lambda live, entries, cache: "stage", close_run=lambda c: None ) )
    assert seen == [ ( "d-r1", "baseline", 1 ), ( "d-r1", "baseline", 2 ), ( "d-r1", "plant_line", 1 ), ( "d-r1", "plant_line", 2 ), ( "d-r2", "baseline", 1 ), ( "d-r2", "baseline", 2 ) ]
    assert sorted( out[ "report" ][ "summary" ] ) == [ "baseline/1", "baseline/2", "plant_line/1", "plant_line/2" ] and out[ "report" ][ "summary" ][ "baseline/1" ][ "same_job" ][ "pairs" ] == 2
