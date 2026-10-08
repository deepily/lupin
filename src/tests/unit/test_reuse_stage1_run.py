"""
The packing runner: one command for each step of the run sheet, on a stand-in by default.

Design: the run sheet, sections 7 and 8, and the rehearsal findings file.
Every transport here is a stand-in. Nothing reaches Jev and no real ledger or cache is touched.
"""
import json
import types

import pytest

from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_tools as rt

KEY     = "JEV_API_TOASTER"
ENTRIES = [ { "id": f"pkg.mod.fn{i:03d}", "sig": "()", "doc": f"Does thing {i}.", "file": "src/pkg/mod.py" } for i in range( 260 ) ]
PAGES   = [ { "id": f"page.{i}", "sig": "", "doc": f"Page {i} describes a capability." } for i in range( 3 ) ]


def loader( root ): return ENTRIES, PAGES


@pytest.fixture
def scratch( tmp_path, monkeypatch ):
    """Scratch paths, with the real data folder and ledger pointed elsewhere."""
    monkeypatch.setattr( rt, "data_dir", lambda root: tmp_path / "real-data" )
    monkeypatch.setattr( rl, "ledger_path", lambda root: tmp_path / "real" / "ledger.jsonl" )
    monkeypatch.delenv( KEY, raising=False )
    return types.SimpleNamespace( root=tmp_path / "root", data=tmp_path / "data", ledger=tmp_path / "ledger.jsonl", real_data=tmp_path / "real-data", real_ledger=tmp_path / "real" / "ledger.jsonl" )


def run( paths, *args, live=False, data=True, ledger=True ):
    """Run the command line as a person would, with a small catalogue for the index."""
    argv  = [ "--root", str( paths.root ) ]
    argv += [ "--data", str( paths.data ) ] if data else []
    argv += [ "--ledger", str( paths.ledger ) ] if ledger else []
    argv += [ "--live" ] if live else []
    return rr.main( argv + list( args ), loader=loader )


def read( paths, name ): return json.loads( ( paths.data / "stage1-results" / f"{name}.json" ).read_text() )


def ledger_rows( path ): return path.read_text().splitlines()


def test_the_four_questions_are_the_pre_registered_texts():
    assert rr.NEEDS == { 1: "A function that sends a notification to the user and waits for a yes/no answer, returning the answer.",
                         2: "A function that checks that a database table's actual schema matches the expected columns, and reports any mismatch.",
                         3: "A function that marks a one-time token record as used, so it cannot be redeemed twice.",
                         4: "A function that takes an LLM reply containing a fenced JSON block and returns the metadata fields from it." }


def test_the_stand_in_answers_the_same_text_the_same_way_and_other_text_differently():
    class Budget:
        def take( self ): pass
    body = lambda text: { "model": "m", "questions": { "q1": { "instructions": text } } }
    first, second, other = rr.StandIn( Budget() ), rr.StandIn( Budget() ), rr.StandIn( Budget() )
    a, meta = first.post_with_meta( body( "the candidate 'x'" ) )
    assert a == second.post_with_meta( body( "the candidate 'x'" ) )[ 0 ] and a != other.post_with_meta( body( "the candidate 'y'" ) )[ 0 ]
    probs = a[ "answers" ][ "q1" ][ "probabilities" ]
    assert sum( probs.values() ) == pytest.approx( 1 ) and a[ "model" ] == "m" and a[ "usage" ][ "output_tokens" ] == 40 and meta[ "status" ] == 200


def test_the_stand_in_spends_one_attempt_of_the_budget_per_post():
    taken = []
    budget = types.SimpleNamespace( take=lambda: taken.append( 1 ) )
    rr.StandIn( budget ).post_with_meta( { "model": "m", "questions": { "q": { "instructions": "x" } } } )
    assert taken == [ 1 ]


def test_a_stand_in_run_needs_its_own_data_folder_and_ledger( scratch ):
    with pytest.raises( rr.RunnerRefused, match="--data" ): run( scratch, "status", data=False )
    scratch.data.mkdir()
    with pytest.raises( rr.RunnerRefused, match="--ledger" ): run( scratch, "status", ledger=False )


def test_a_stand_in_run_refuses_the_real_data_folder_and_the_real_ledger( scratch ):
    with pytest.raises( rr.RunnerRefused, match="real data folder" ): rr.main( [ "--root", str( scratch.root ), "--data", str( scratch.real_data ), "--ledger", str( scratch.ledger ), "status" ], loader=loader )
    with pytest.raises( rr.RunnerRefused, match="real ledger" ): rr.main( [ "--root", str( scratch.root ), "--data", str( scratch.data ), "--ledger", str( scratch.real_ledger ), "status" ], loader=loader )
    assert not scratch.real_data.exists() and not scratch.real_ledger.exists() and not scratch.data.exists()          # a refusal creates nothing


def test_the_default_is_the_stand_in_and_it_marks_its_data_folder( scratch ):
    run( scratch, "ledger-init" )
    assert run( scratch, "arm", "--question", "1", "--arm", "single1", "--ceiling", "5000000" ) == 0
    assert ( scratch.data / rr.STAND_IN_MARKER ).exists() and read( scratch, "s1-q1-single1" )[ "state" ] == "complete"
    env = rr.open_env( scratch.root, scratch.data, scratch.ledger, False, 5 )
    assert env.live is False


def test_a_live_run_refuses_a_data_folder_a_stand_in_wrote( scratch ):
    scratch.real_ledger.parent.mkdir(); rl.AccountLedger.create( scratch.real_ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "scratch" )
    scratch.real_data.mkdir(); ( scratch.real_data / rr.STAND_IN_MARKER ).write_text( "marked\n" )
    with pytest.raises( rr.RunnerRefused, match="stand-in" ): run( scratch, "status", live=True, data=False, ledger=False )


def test_a_live_run_refuses_a_data_folder_or_ledger_that_is_not_the_real_one( scratch ):
    scratch.real_ledger.parent.mkdir(); rl.AccountLedger.create( scratch.real_ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "scratch" )
    rl.AccountLedger.create( scratch.ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "a scratch ledger" )
    with pytest.raises( rr.RunnerRefused, match="real ledger" ): run( scratch, "status", live=True, data=False )              # spend on it would escape the account limit
    with pytest.raises( rr.RunnerRefused, match="real data folder" ): run( scratch, "status", live=True, ledger=False )
    assert run( scratch, "status", live=False ) == 0                                                                           # the same scratch paths are fine for a stand-in
    argv = [ "--root", str( scratch.root ), "--data", str( scratch.real_data ), "--ledger", str( scratch.real_ledger ), "--live", "status" ]
    assert rr.main( argv, loader=loader ) == 0                                                                                  # naming the real ones is allowed


def test_a_live_run_uses_the_real_paths_by_default_and_needs_the_ledger_to_exist( scratch ):
    with pytest.raises( rr.RunnerRefused, match="create the ledger first" ): rr.main( [ "--root", str( scratch.root ), "--live", "status" ], loader=loader )
    scratch.real_ledger.parent.mkdir(); rl.AccountLedger.create( scratch.real_ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "scratch" )
    assert rr.main( [ "--root", str( scratch.root ), "--live", "status" ], loader=loader ) == 0
    assert not ( scratch.real_data / rr.STAND_IN_MARKER ).exists()


def test_a_live_run_with_no_key_is_refused_by_the_driver_and_spends_nothing( scratch ):
    scratch.real_ledger.parent.mkdir(); rl.AccountLedger.create( scratch.real_ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "scratch" )
    before = ledger_rows( scratch.real_ledger )
    with pytest.raises( s1.KeyMissing, match=KEY ): run( scratch, "canary", "--question", "1", "--ceiling", "2000000", live=True, data=False, ledger=False )
    assert ledger_rows( scratch.real_ledger ) == before and not ( scratch.real_data / "stage1-results" ).exists()


def test_ledger_init_makes_a_scratch_ledger_once_and_never_the_real_one( scratch ):
    assert run( scratch, "ledger-init" ) == 0
    assert rl.AccountLedger( scratch.ledger ).snapshot() == ( rl.ACCOUNT_LIMIT_TOKENS, 0 )
    with pytest.raises( FileExistsError ): run( scratch, "ledger-init" )
    with pytest.raises( rr.RunnerRefused, match="stand-in" ): run( scratch, "ledger-init", live=True )


def test_status_prints_the_ledger_and_what_the_stage_has_left( scratch, capsys ):
    run( scratch, "ledger-init" ); capsys.readouterr()
    assert run( scratch, "status" ) == 0
    out = capsys.readouterr().out
    assert f"ledger ({rl.ACCOUNT_LIMIT_TOKENS}, 0)" in out and f"stage remaining {s1.STAGE_TOKENS}" in out and "entries 260" in out and "pages 3" in out


def test_a_whole_question_runs_in_the_sheets_order_and_the_report_reads_it( scratch, capsys ):
    run( scratch, "ledger-init" )
    q, big = [ "--question", "1" ], [ "--ceiling", "14000000" ]
    assert run( scratch, "arm", *q, "--arm", "single1", *big ) == 0
    assert run( scratch, "canary", *q, "--ceiling", "2000000" ) == 0
    assert "tripped []" in capsys.readouterr().out
    with pytest.raises( s1.CanaryNotApproved ): run( scratch, "arm", *q, "--arm", "single2", *big )          # the canary gate holds through the runner
    assert run( scratch, "approve", *q, "--by", "rachel", "--why", "stand-in numbers read" ) == 0
    for arm in ( "single2", "pack10", "pack50", "pack200" ): assert run( scratch, "arm", *q, "--arm", arm, "--ceiling", "6000000" ) == 0
    assert run( scratch, "probe-plan", *q ) == 0
    for arm in sorted( a for a in s1.ARMS if a.startswith( "probe-" ) ): assert run( scratch, "arm", *q, "--arm", arm, "--ceiling", "2000000" ) == 0
    for arm in ( "page-single1", "page-single2", "page-pack" ): assert run( scratch, "arm", *q, "--arm", arm, "--ceiling", "1000000" ) == 0
    assert run( scratch, "old-shape", *q ) == 0
    capsys.readouterr()
    assert run( scratch, "report" ) == 0
    out = capsys.readouterr().out
    assert "Live packing measurement: analysis" in out and "question 1 old:" in out and "s1-q1-page-pack: lost 0" in out
    names = sorted( p.name for p in ( scratch.data / "stage1-results" ).iterdir() )
    assert "s1-q1-old-shape.json" in names and "s1-q1-probe-plan.json" in names and len( names ) == 18          # 15 arms, canary file, plan, old shape


def test_each_arm_gets_the_entries_it_is_about( scratch ):
    run( scratch, "ledger-init" )
    q = [ "--question", "1" ]
    run( scratch, "arm", *q, "--arm", "single1", "--ceiling", "14000000" ); run( scratch, "canary", *q, "--ceiling", "2000000" ); run( scratch, "approve", *q, "--by", "r", "--why", "ok" )
    run( scratch, "arm", *q, "--arm", "page-single1", "--ceiling", "1000000" )
    assert read( scratch, "s1-q1-single1" )[ "entry_ids" ] == [ e[ "id" ] for e in ENTRIES ] and read( scratch, "s1-q1-page-single1" )[ "entry_ids" ] == [ p[ "id" ] for p in PAGES ]
    assert read( scratch, "s1-q1-single1" )[ "entries_in_index" ] == 260


def test_the_canary_is_run_by_its_own_command_not_the_arm_command( scratch ):
    with pytest.raises( SystemExit ): run( scratch, "arm", "--question", "1", "--arm", "canary", "--ceiling", "1" )
    with pytest.raises( SystemExit ): run( scratch, "arm", "--question", "1", "--arm", "nonsense", "--ceiling", "1" )


def test_a_ceiling_is_always_asked_for( scratch ):
    with pytest.raises( SystemExit ): run( scratch, "arm", "--question", "1", "--arm", "single1" )
    with pytest.raises( SystemExit ): run( scratch, "canary", "--question", "1" )


def test_the_probe_arms_need_the_single_run_and_a_plan_that_still_matches( scratch ):
    run( scratch, "ledger-init" )
    q = [ "--question", "1" ]
    with pytest.raises( rr.RunnerRefused, match="single run 1" ): run( scratch, "probe-plan", *q )
    run( scratch, "arm", *q, "--arm", "single1", "--ceiling", "14000000" ); run( scratch, "canary", *q, "--ceiling", "2000000" ); run( scratch, "approve", *q, "--by", "r", "--why", "ok" )
    with pytest.raises( rr.RunnerRefused, match="probe plan first" ): run( scratch, "arm", *q, "--arm", "probe-first-random", "--ceiling", "2000000" )
    run( scratch, "probe-plan", *q )
    with pytest.raises( FileExistsError ): run( scratch, "probe-plan", *q )                                       # written once
    plan_file = scratch.data / "stage1-results" / "s1-q1-probe-plan.json"
    plan = json.loads( plan_file.read_text() ); plan[ "seed" ] += 1; plan_file.write_text( json.dumps( plan ) )
    with pytest.raises( rr.RunnerRefused, match="no longer matches" ): run( scratch, "arm", *q, "--arm", "probe-first-random", "--ceiling", "2000000" )


def test_the_old_shape_record_is_written_under_a_name_no_arm_can_take( scratch ):
    run( scratch, "ledger-init" )
    assert run( scratch, "old-shape", "--question", "2" ) == 0
    record = read( scratch, "s1-q2-old-shape" )
    assert record[ "arm" ] == "old" and record[ "question" ] == 2 and record[ "need" ] == rr.NEEDS[ 2 ] and record[ "state" ] == "incomplete"
    assert "s1-q2-old-shape" not in { s1.run_name( 2, arm ) for arm in s1.ARMS }


def test_a_missing_environment_root_is_refused( scratch, monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( rr.RunnerRefused, match="LUPIN_ROOT" ): rr.main( [ "--data", str( scratch.data ), "--ledger", str( scratch.ledger ), "status" ], loader=loader )


def test_the_root_comes_from_the_environment_when_not_given( scratch, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( scratch.root ) )
    run( scratch, "ledger-init" )
    assert rr.main( [ "--data", str( scratch.data ), "--ledger", str( scratch.ledger ), "status" ], loader=loader ) == 0


def fake_index( monkeypatch, flags, pages ):
    """A tool-path context whose index holds three entries, with the given causes and pages."""
    monkeypatch.setattr( rt, "context_from_environment", lambda root: types.SimpleNamespace( pages=pages ) )
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( flags, ENTRIES[ :3 ], "sha", None ) )


def test_the_inputs_are_the_prepared_entries_and_the_pages_in_the_drivers_shape( monkeypatch ):
    fake_index( monkeypatch, { "KEY_UNREADABLE" }, [ { "slug": "a", "text": "About a.", "scope": "x" }, { "slug": "b", "text": "About b.", "scope": "y" } ] )
    entries, pages = rr.load_inputs( "." )
    assert entries == ENTRIES[ :3 ] and pages == [ { "id": "a", "sig": "", "doc": "About a." }, { "id": "b", "sig": "", "doc": "About b." } ]


@pytest.mark.parametrize( "flag", [ "NOT_LUPIN_TREE", "INDEX_STALE", "DEPENDENCY_MISSING" ] )
def test_an_index_that_is_not_ready_is_refused_by_name( monkeypatch, flag ):
    fake_index( monkeypatch, { flag, "KEY_UNREADABLE" }, [] )
    with pytest.raises( rr.RunnerRefused, match=flag ): rr.load_inputs( "." )


def test_a_repeated_page_slug_is_named_before_any_arm_runs( monkeypatch ):
    fake_index( monkeypatch, set(), [ { "slug": "a", "text": "One.", "scope": "x" }, { "slug": "a", "text": "Two.", "scope": "x" } ] )
    with pytest.raises( rr.RunnerRefused, match="'a'" ): rr.load_inputs( "." )


def test_a_live_run_with_no_paths_named_reads_the_real_data_folder_and_the_real_ledger( scratch ):
    scratch.real_ledger.parent.mkdir(); rl.AccountLedger.create( scratch.real_ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "scratch" )
    env = rr.open_env( scratch.root, None, None, True, 5 )
    assert env.data == scratch.real_data and env.ledger.path == scratch.real_ledger and env.live is True


def test_a_report_on_a_folder_with_no_arm_file_says_so_and_returns_the_analysis_code( scratch, capsys ):
    run( scratch, "ledger-init" ); capsys.readouterr()
    assert run( scratch, "report" ) == 2
    assert "no arm files" in capsys.readouterr().out


def test_a_path_refusal_comes_before_the_index_is_read( scratch ):
    def never( root ): raise AssertionError( "the index was read" )
    argv = [ "--root", str( scratch.root ), "--data", str( scratch.real_data ), "--ledger", str( scratch.ledger ), "status" ]
    with pytest.raises( rr.RunnerRefused, match="real data folder" ): rr.main( argv, loader=never )


def test_ledger_init_makes_the_scratch_ledgers_folder_when_it_is_not_there( scratch ):
    nested = scratch.ledger.parent / "new" / "folder" / "ledger.jsonl"
    argv   = [ "--root", str( scratch.root ), "--data", str( scratch.data ), "--ledger", str( nested ), "ledger-init" ]
    assert rr.main( argv, loader=loader ) == 0 and nested.exists()


def test_the_stand_in_reports_the_attempt_log_and_client_version_the_live_transport_does():
    class Budget:
        def take( self ): pass
    _, meta = rr.StandIn( Budget() ).post_with_meta( { "model": "m", "questions": { "q": { "instructions": "x" } } } )
    assert meta[ "attempt_log" ] == [ { "status": 200, "request_ids": {} } ] and meta[ "client_version" ] == rr.STAND_IN_CLIENT == "stand-in"


def test_an_arm_the_stand_in_ran_keeps_the_attempt_log_and_client_version_in_its_file( scratch ):
    run( scratch, "ledger-init" )
    run( scratch, "arm", "--question", "1", "--arm", "single1", "--ceiling", "5000000" )
    record = read( scratch, "s1-q1-single1" )
    assert record[ "rows" ][ 0 ][ "attempt_log" ] == [ { "status": 200, "request_ids": {} } ]
    assert record[ "transport_calls" ][ 0 ][ "client_version" ] == "stand-in" and record[ "transport_calls" ][ 0 ][ "attempt_log" ] == [ { "status": 200, "request_ids": {} } ]


@pytest.mark.parametrize( "refusal", [ rr.RunnerRefused( "no data folder" ), s1.KeyMissing( "JEV_API_TOASTER is not set" ), s1.CanaryNotApproved( "the canary of question 1 is not approved" ),
                                       s1.CanaryTripped( "the canary tripped: refusal" ), s1.StageRefused( "9 asked, 1 remaining" ) ] )
def test_a_refusal_the_runner_makes_is_one_line_on_the_error_stream_and_exit_code_two( monkeypatch, capsys, refusal ):
    def refuse( argv=None, loader=None ): raise refusal
    monkeypatch.setattr( rr, "main", refuse )
    assert rr.cli( [ "status" ] ) == 2
    seen = capsys.readouterr()
    lines = seen.err.strip().splitlines()
    assert seen.out == "" and len( lines ) == 1 and lines[ 0 ] == f"refused ({type( refusal ).__name__}): {refusal}"


@pytest.mark.parametrize( "error", [ ValueError( "bad" ), RuntimeError( "boom" ), KeyError( "x" ) ] )
def test_any_other_error_is_not_dressed_as_a_refusal( monkeypatch, error ):
    def fail( argv=None, loader=None ): raise error
    monkeypatch.setattr( rr, "main", fail )
    with pytest.raises( type( error ) ): rr.cli( [ "status" ] )


def test_a_gated_arm_before_the_canary_is_approved_gives_the_one_line_through_the_real_command( scratch, capsys ):
    run( scratch, "ledger-init" ); capsys.readouterr()
    argv = [ "--root", str( scratch.root ), "--data", str( scratch.data ), "--ledger", str( scratch.ledger ), "arm", "--question", "1", "--arm", "single2", "--ceiling", "1000000" ]
    assert rr.cli( argv, loader=loader ) == 2
    assert "the canary of question 1 is not approved" in capsys.readouterr().err


def test_a_command_that_works_returns_its_own_code_through_cli( scratch ):
    run( scratch, "ledger-init" )
    argv = [ "--root", str( scratch.root ), "--data", str( scratch.data ), "--ledger", str( scratch.ledger ), "status" ]
    assert rr.cli( argv, loader=loader ) == 0


@pytest.mark.parametrize( "code", [ 0, 2, 3 ] )
def test_cli_returns_whatever_code_main_returns( monkeypatch, code ):
    monkeypatch.setattr( rr, "main", lambda argv=None, loader=None: code )
    assert rr.cli( [ "report" ] ) == code
