"""
The fresh-needs driver: reserved hash, estimate, recorded sample, sweep, fixed settings.

Nothing here reaches Jev: the transport is the stand-in and the ledger is a scratch file.
The reserved file of the run is never opened: the tests write a scratch file of their own under the same layout.
"""
import ast
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_flip_run as frun
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_phase5_run as p5
from lupin_mcp import reuse_stage1 as s1
from tests.unit.test_reuse_e2e_cli import put
from tests.unit.test_reuse_e2e_run import make_wide_repo
from tests.unit.test_reuse_flip_run import rows_of


class Scratch:
    """A projects-data directory with a 30-row needs file, a tree and a ledger."""

    def __init__( self, tmp_path, monkeypatch ):
        folder = tmp_path / "projects-data" / p5.FRESH_NEEDS_DIR
        folder.mkdir( parents=True )
        self.projects_data = str( tmp_path / "projects-data" )
        self.sha    = put( folder / p5.FRESH_NEEDS_NAME, { "format": frun.NEEDS_FORMAT, "needs": rows_of( 30 ) } )
        self.root   = make_wide_repo( tmp_path )
        self.data   = tmp_path / "data"
        self.ledger = tmp_path / "ledger.jsonl"
        rl.AccountLedger.create( self.ledger, rl.ACCOUNT_LIMIT_TOKENS, "test", "scratch" )
        monkeypatch.setattr( e2e, "FRESH_SHA_PREFIX", self.sha[ :8 ] )

    def args( self, command, *extra, sha=None ):
        base = [ command, "--projects-data", self.projects_data, "--needs-sha", sha or self.sha ]
        if command == "estimate": return base
        base += [ "--data", str( self.data ) ]
        if command != "sample": base += [ "--root", str( self.root ), "--ledger", str( self.ledger ) ]
        return base + list( extra )

    def sample( self, seed="seed-before-the-run", arm="new-question-full", index="ix-123" ):
        return p5.cli( self.args( "sample", "--seed", seed, "--arm", arm, "--index-sha", index ) )


@pytest.fixture
def scratch( tmp_path, monkeypatch ):
    return Scratch( tmp_path, monkeypatch )


def items_of( n=30 ):
    return [ { "member": f"n{i:02d}", "need": f"need {i}", "exclude": None, "kind": "distinct" } for i in range( n ) ]


def test_estimate_parts_pin_each_part_and_the_sum_to_literals():
    parts = p5.estimate_parts( 30 )
    assert parts == { "run": 368_040_000, "canary": 61_400_000, "sample": 24_536_000, "total": 453_976_000 }
    assert parts[ "total" ] == parts[ "run" ] + parts[ "canary" ] + parts[ "sample" ]


def test_estimate_parts_follow_the_files_own_count_of_needs():
    assert p5.estimate_parts( 2, repeats=3, sample=1 )[ "run" ] == 6 * 2_453_600
    assert p5.estimate_parts( 40 )[ "run" ] == 40 * 5 * 2_453_600


def test_estimate_lines_show_three_parts_then_the_total_with_dollars():
    lines = p5.estimate_lines( p5.estimate_parts( 30 ), 30 )
    assert lines[ :3 ] == [ "run: 368.0 M tokens", "canary: 61.4 M tokens", "sample: 24.5 M tokens" ]
    assert lines[ 3 ].startswith( "total: 454.0 M tokens, about $19.07 at $0.042 per M, 15.13 M per need" )
    assert "estimate, not measured" in lines[ 3 ]


def test_pick_sample_is_ten_members_in_file_order_and_repeatable():
    items = items_of()
    first = p5.pick_sample( items, "seed-one" )
    assert len( first ) == 10 and len( set( first ) ) == 10
    assert first == sorted( first )
    assert first == p5.pick_sample( items, "seed-one" )


def test_pick_sample_changes_with_the_seed_and_the_order_of_the_file_does_not_matter():
    items = items_of()
    assert p5.pick_sample( items, "seed-one" ) != p5.pick_sample( items, "seed-two" )          # positive control: the seed is what decides
    assert set( p5.pick_sample( list( reversed( items ) ), "seed-one" ) ) == set( p5.pick_sample( items, "seed-one" ) )


@pytest.mark.parametrize( "seed", [ "", "   ", None, 7 ] )
def test_pick_sample_refuses_an_empty_seed( seed ):
    with pytest.raises( s1.DriverRefused, match="seed" ): p5.pick_sample( items_of(), seed )


@pytest.mark.parametrize( "size", [ 0, 31, -1 ] )
def test_pick_sample_refuses_a_size_outside_the_needs( size ):
    with pytest.raises( s1.DriverRefused, match="between 1 and 30" ): p5.pick_sample( items_of(), "s", size=size )


def test_needs_path_joins_the_pinned_layout_and_ignores_a_trailing_slash():
    assert p5.needs_path( "/x/projects-data/" ) == f"/x/projects-data/{p5.FRESH_NEEDS_DIR}/{p5.FRESH_NEEDS_NAME}"
    assert p5.needs_path( "/x/projects-data" ) == p5.needs_path( "/x/projects-data/" )


def test_the_reserved_prefix_is_the_one_the_plan_names_and_check_sha_pins_it( monkeypatch ):
    assert e2e.FRESH_SHA_PREFIX == "0a0da7b7"
    full = e2e.FRESH_SHA_PREFIX + "f" * 56
    assert p5.check_sha( full ) == full
    for bad in ( "1" * 64, None, 12 ):
        with pytest.raises( e2e.FrozenInputRefused, match="must start with" ): p5.check_sha( bad )


def test_the_shared_reader_refuses_the_reserved_hash_to_every_other_caller( scratch ):
    path = p5.needs_path( scratch.projects_data )
    with pytest.raises( e2e.FrozenInputRefused, match="reserved" ): e2e._read_checked( path, scratch.sha, "any file" )
    with pytest.raises( e2e.FrozenInputRefused, match="reserved" ): frun.load_flip_needs( path, scratch.sha )
    assert e2e._read_checked( path, scratch.sha, "any file", allow_fresh=True )[ "format" ] == frun.NEEDS_FORMAT
    assert len( frun.load_flip_needs( path, scratch.sha, allow_fresh=True ) ) == 30


def test_the_flip_driver_refuses_the_reserved_file_and_has_no_flag_to_allow_it( scratch, capsys ):
    argv = [ "--root", str( scratch.root ), "--data", str( scratch.data ), "--ledger", str( scratch.ledger ), "canary",
             "--needs", p5.needs_path( scratch.projects_data ), "--needs-sha", scratch.sha, "--ceiling", "1" ]
    assert frun.cli( argv ) == 2
    assert "reserved" in capsys.readouterr().err
    with pytest.raises( SystemExit ): frun.cli( argv + [ "--allow-fresh" ] )                      # the command line carries no such flag


def test_estimate_command_prints_the_parts_for_the_files_own_count( scratch, capsys ):
    assert p5.cli( scratch.args( "estimate" ) ) == 0
    out = capsys.readouterr().out
    assert "run: 368.0 M tokens" in out and "total: 454.0 M tokens" in out


def test_sample_is_recorded_once_with_arm_and_index_and_the_same_call_repeats( scratch, capsys ):
    assert scratch.sample() == 0
    first = json.loads( capsys.readouterr().out )
    held  = json.loads( ( scratch.data / p5.SAMPLE_FILE ).read_text( encoding="utf-8" ) )
    assert first == held
    assert held[ "seed" ] == "seed-before-the-run" and held[ "arm" ] == "new-question-full" and held[ "index_sha" ] == "ix-123" and held[ "needs_sha" ] == scratch.sha
    assert len( held[ "members" ] ) == 10
    assert scratch.sample() == 0 and json.loads( capsys.readouterr().out ) == held


@pytest.mark.parametrize( "change", [ { "seed": "another" }, { "arm": "other-arm" }, { "index": "ix-999" } ] )
def test_a_different_seed_arm_or_index_is_refused_after_the_sample_is_recorded( scratch, capsys, change ):
    assert scratch.sample() == 0
    before = ( scratch.data / p5.SAMPLE_FILE ).read_text( encoding="utf-8" )
    capsys.readouterr()
    assert scratch.sample( **change ) == 2
    assert "already recorded" in capsys.readouterr().err
    assert ( scratch.data / p5.SAMPLE_FILE ).read_text( encoding="utf-8" ) == before


@pytest.mark.parametrize( "step", [ ( "canary", "--ceiling", "1" ), ( "approve", "--by", "c", "--why", "w" ), ( "run", "--ceiling", "1" ), ( "report", ), ( "sweep", "--ceiling", "1" ) ] )
def test_a_step_that_spends_or_reports_is_refused_before_the_sample_is_recorded( scratch, capsys, step ):
    assert p5.cli( scratch.args( *step ) ) == 2
    assert "no sample is recorded" in capsys.readouterr().err
    assert not ( scratch.data / "e2e-results" ).exists()                                        # nothing was created or sent


def test_a_sample_recorded_for_another_needs_file_is_refused( scratch, capsys ):
    assert scratch.sample() == 0
    record = json.loads( ( scratch.data / p5.SAMPLE_FILE ).read_text( encoding="utf-8" ) )
    record[ "needs_sha" ] = "0" * 64
    ( scratch.data / p5.SAMPLE_FILE ).write_text( json.dumps( record ), encoding="utf-8" )
    capsys.readouterr()
    assert p5.cli( scratch.args( "report" ) ) == 2
    assert "recorded for needs file" in capsys.readouterr().err


def test_flip_argv_fixes_the_settings_and_holds_the_estimate_to_the_run_and_the_canary( scratch ):
    class A: pass
    a = A()
    a.root, a.data, a.ledger, a.pack_size, a.live, a.command = "/r", "/d", "/l", 50, False, "canary"
    a.projects_data, a.needs_sha, a.ceiling = scratch.projects_data, scratch.sha, 9
    parts = p5.estimate_parts( 30 )
    argv  = p5.flip_argv( a, parts )
    assert argv[ :8 ] == [ "--root", "/r", "--data", "/d", "--ledger", "/l", "--pack-size", "50" ]
    assert argv[ 8: ] == [ "--prefix", "p5", "--estimate-tokens", "429440000", "--repeats", "5", "--route", "full", "--question", "new",
                           "canary", "--needs", p5.needs_path( scratch.projects_data ), "--needs-sha", scratch.sha, "--ceiling", "9" ]
    assert 429_440_000 == parts[ "run" ] + parts[ "canary" ] == parts[ "total" ] - parts[ "sample" ]
    a.live, a.command, a.by, a.why = True, "approve", "me", "ok"
    argv = p5.flip_argv( a, parts )
    assert argv[ 6 ] == "--live" and argv[ -4: ] == [ "--by", "me", "--why", "ok" ]
    a.command = "report"
    assert p5.flip_argv( a, parts )[ -5: ] == [ "report", "--needs", p5.needs_path( scratch.projects_data ), "--needs-sha", scratch.sha ]


def test_the_steps_run_end_to_end_on_the_stand_in_and_the_report_names_the_recorded_sample( scratch, capsys ):
    assert scratch.sample() == 0
    members = json.loads( capsys.readouterr().out )[ "members" ]
    assert p5.cli( scratch.args( "canary", "--ceiling", "100000000" ) ) == 0
    canary = json.loads( ( scratch.data / "e2e-results" / "p5-canary.json" ).read_text( encoding="utf-8" ) )
    assert canary[ "questions" ] == [ "r1", "r2", "r3", "r4", "r5" ] and canary[ "pack_size" ] == 50
    assert p5.cli( scratch.args( "approve", "--by", "cheech", "--why", "read it" ) ) == 0
    assert p5.cli( scratch.args( "sweep", "--ceiling", "36000000" ) ) == 0
    sweep = json.loads( ( scratch.data / "e2e-results" / "p5s-sample.json" ).read_text( encoding="utf-8" ) )
    assert sweep[ "members" ] == members and sweep[ "questions" ] == [ "r1" ] and len( sweep[ "searches" ] ) == 10
    assert all( s[ "status" ] == "complete" for s in sweep[ "searches" ] )
    assert { s[ "rows" ][ 0 ][ "question" ] for s in sweep[ "searches" ] } == { "provides" }      # the new question, never the old one
    assert p5.cli( scratch.args( "run", "--ceiling", "300000000" ) ) == 0
    want = hashlib.sha256( ( scratch.data / p5.SAMPLE_FILE ).read_bytes() ).hexdigest()
    for name in ( "p5-canary", "p5-run", "p5s-sample" ):
        assert json.loads( ( scratch.data / "e2e-results" / f"{name}.json" ).read_text( encoding="utf-8" ) )[ "sample_sha256" ] == want
    capsys.readouterr()
    assert p5.cli( scratch.args( "report" ) ) == 0
    out = capsys.readouterr().out
    assert "flip rate (new question, route full)" in out
    assert "sample: seed 'seed-before-the-run', arm 'new-question-full', index ix-123, members " + ", ".join( members ) in out


def test_a_refusal_of_the_flip_driver_is_returned_as_its_code( scratch, capsys ):
    assert scratch.sample() == 0
    capsys.readouterr()
    assert p5.cli( scratch.args( "run", "--ceiling", "100000000" ) ) == 2                       # the canary has not run
    assert "refused" in capsys.readouterr().err


def test_the_hash_is_checked_before_the_sample_or_anything_else_is_read( scratch, capsys ):
    assert p5.cli( scratch.args( "sample", "--seed", "s", "--arm", "a", "--index-sha", "i", sha="9" * 64 ) ) == 2
    assert "must start with" in capsys.readouterr().err
    assert p5.cli( scratch.args( "sample", "--seed", "s", "--arm", "a", "--index-sha", "i", sha=scratch.sha[ :8 ] + "0" * 56 ) ) == 2    # right prefix, not the file
    assert "sha256" in capsys.readouterr().err
    assert p5.cli( scratch.args( "sample", "--seed", " ", "--arm", "a", "--index-sha", "i" ) ) == 2
    assert "seed" in capsys.readouterr().err
    assert not ( scratch.data / p5.SAMPLE_FILE ).exists()


def test_another_file_at_the_path_is_refused_even_with_its_own_hash( scratch, capsys ):
    other = put( Path( p5.needs_path( scratch.projects_data ) ), { "format": frun.NEEDS_FORMAT, "needs": rows_of( 31 ) } )
    assert other != scratch.sha
    assert p5.cli( scratch.args( "estimate", sha=other ) ) == 2
    assert "must start with" in capsys.readouterr().err


def grep_tracked( root, needle ):
    """Ensures: returns the tracked text files that hold needle; binary files are skipped."""
    out = subprocess.run( [ "git", "grep", "-l", "-I", "-F", "-e", needle ], capture_output=True, text=True, cwd=root )
    assert out.returncode in ( 0, 1 ), out.stderr
    return sorted( out.stdout.split() )


def test_only_this_driver_names_the_reserved_file_and_only_the_reader_and_this_test_hold_its_hash():
    root  = Path( subprocess.run( [ "git", "rev-parse", "--show-toplevel" ], capture_output=True, text=True, check=True, cwd=Path( __file__ ).parent ).stdout.strip() )
    files = subprocess.run( [ "git", "ls-files" ], capture_output=True, text=True, check=True, cwd=root ).stdout.split()
    assert len( files ) > 1000                                                                 # the population is every tracked file, not an empty listing
    driver, reader, here = "src/lupin_mcp/reuse_phase5_run.py", "src/lupin_mcp/reuse_e2e.py", "src/tests/unit/test_reuse_phase5_run.py"
    statement = "src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.14-reuse-lookup-candidate-stage-problem-statement.md"   # a document that says where the file is; it cannot open it
    assert grep_tracked( root, p5.FRESH_NEEDS_NAME ) == sorted( [ driver, statement ] )         # positive control: the driver itself is found
    assert grep_tracked( root, p5.FRESH_NEEDS_DIR ) == sorted( [ driver, statement ] )
    assert grep_tracked( root, "0a0da7b7" ) == sorted( [ reader, here ] )
    flip = "src/lupin_mcp/reuse_flip_run.py"
    assert grep_tracked( root, "allow_fresh" ) == sorted( [ reader, flip, driver, here ] )         # the keyword appears nowhere else


def test_the_flip_drivers_main_refuses_the_reserved_hash_when_called_without_the_allow( scratch ):
    argv = [ "--root", str( scratch.root ), "--data", str( scratch.data ), "--ledger", str( scratch.ledger ), "canary",
             "--needs", p5.needs_path( scratch.projects_data ), "--needs-sha", scratch.sha, "--ceiling", "1" ]
    with pytest.raises( e2e.FrozenInputRefused, match="reserved" ): frun.main( argv )


def test_the_estimate_follows_the_count_of_the_file_it_was_given( scratch, monkeypatch, capsys ):
    other = put( Path( p5.needs_path( scratch.projects_data ) ), { "format": frun.NEEDS_FORMAT, "needs": rows_of( 31 ) } )
    monkeypatch.setattr( e2e, "FRESH_SHA_PREFIX", other[ :8 ] )
    assert p5.cli( scratch.args( "estimate", sha=other ) ) == 0
    assert "run: 380.3 M tokens" in capsys.readouterr().out                                      # 31 x 5 x 2,453,600


def canary_and_approve( scratch ):
    assert scratch.sample() == 0
    assert p5.cli( scratch.args( "canary", "--ceiling", "100000000" ) ) == 0
    assert p5.cli( scratch.args( "approve", "--by", "cheech", "--why", "read it" ) ) == 0


def test_the_sweep_refuses_before_the_canary_is_run_and_before_it_is_approved( scratch, capsys ):
    assert scratch.sample() == 0
    capsys.readouterr()
    assert p5.cli( scratch.args( "sweep", "--ceiling", "36000000" ) ) == 2
    assert "has not been approved" in capsys.readouterr().err
    assert not ( scratch.data / "e2e-results" ).exists()
    assert p5.cli( scratch.args( "canary", "--ceiling", "100000000" ) ) == 0
    capsys.readouterr()
    assert p5.cli( scratch.args( "sweep", "--ceiling", "36000000" ) ) == 2                       # run, not approved
    assert "has not been approved" in capsys.readouterr().err
    assert not ( scratch.data / "e2e-results" / "p5s-sample.json" ).exists()


def test_the_sweep_refuses_a_ceiling_above_one_and_a_half_times_the_sample_estimate( scratch, capsys ):
    canary_and_approve( scratch )
    capsys.readouterr()
    assert p5.cli( scratch.args( "sweep", "--ceiling", "36804001" ) ) == 2                       # 1.5 x 24,536,000 is 36,804,000
    assert "36804000" in capsys.readouterr().err
    assert not ( scratch.data / "e2e-results" / "p5s-sample.json" ).exists()
    assert p5.cli( scratch.args( "sweep", "--ceiling", "36804000" ) ) == 0


def test_a_result_whose_sample_hash_differs_from_the_file_is_refused_by_the_next_step( scratch, capsys ):
    canary_and_approve( scratch )
    path   = scratch.data / "e2e-results" / "p5-canary.json"
    record = json.loads( path.read_text( encoding="utf-8" ) )
    record[ "sample_sha256" ] = "f" * 64
    path.write_text( json.dumps( record ), encoding="utf-8" )
    capsys.readouterr()
    for step in ( ( "run", "--ceiling", "300000000" ), ( "sweep", "--ceiling", "36000000" ), ( "report", ) ):
        assert p5.cli( scratch.args( *step ) ) == 2
        assert "carries sample hash" in capsys.readouterr().err
    assert not ( scratch.data / "e2e-results" / "p5-run.json" ).exists()                          # nothing was spent


def unstamp( path ):
    record = json.loads( path.read_text( encoding="utf-8" ) )
    del record[ "sample_sha256" ]
    path.write_text( json.dumps( record ), encoding="utf-8" )


def test_a_result_with_no_sample_hash_stops_a_step_that_spends_and_is_named_and_skipped_by_report( scratch, capsys ):
    canary_and_approve( scratch )
    unstamp( scratch.data / "e2e-results" / "p5-canary.json" )
    capsys.readouterr()
    for step in ( ( "run", "--ceiling", "300000000" ), ( "sweep", "--ceiling", "36000000" ), ( "approve", "--by", "c", "--why", "w" ) ):
        assert p5.cli( scratch.args( *step ) ) == 2
        assert "carries no sample hash" in capsys.readouterr().err
    assert p5.cli( scratch.args( "report" ) ) == 0                                                # not refused as a whole
    out = capsys.readouterr().out
    assert "skipped, no sample hash: p5-canary" in out and "no searches have run yet" in out


def test_report_leaves_out_only_the_unstamped_result_and_reads_the_others( scratch, capsys ):
    canary_and_approve( scratch )
    assert p5.cli( scratch.args( "run", "--ceiling", "300000000" ) ) == 0
    assert p5.cli( scratch.args( "sweep", "--ceiling", "36000000" ) ) == 0
    unstamp( scratch.data / "e2e-results" / "p5-run.json" )
    unstamp( scratch.data / "e2e-results" / "p5s-sample.json" )
    capsys.readouterr()
    assert p5.cli( scratch.args( "report" ) ) == 0
    out = capsys.readouterr().out
    assert "skipped, no sample hash: p5-run, p5s-sample" in out
    assert "0 of 5 needs flipped" in out                                                          # only the canary's 5 needs were read; the run's 25 were skipped


def test_every_write_of_a_result_carries_the_stamp_so_a_crash_leaves_a_stamped_file( scratch, monkeypatch, capsys ):
    from lupin_mcp import reuse_e2e_run as e2r
    writes = []
    real   = e2r._write_json
    def spy( path, record ):
        writes.append( ( path.name, dict( record ) ) )
        return real( path, record )
    monkeypatch.setattr( e2r, "_write_json", spy )
    canary_and_approve( scratch )
    want   = hashlib.sha256( ( scratch.data / p5.SAMPLE_FILE ).read_bytes() ).hexdigest()
    parts  = [ r for n, r in writes if n == "p5-canary.json" ]
    assert len( parts ) > 1 and all( r[ "sample_sha256" ] == want for r in parts )               # each member's write, not only the last
    calls = { "n": 0 }
    real_search = e2r._search
    def crashing( *a, **k ):
        calls[ "n" ] += 1
        if calls[ "n" ] == 12: raise RuntimeError( "the process died" )
        return real_search( *a, **k )
    monkeypatch.setattr( e2r, "_search", crashing )
    with pytest.raises( RuntimeError, match="died" ): p5.cli( scratch.args( "run", "--ceiling", "300000000" ) )
    run_writes = [ r for n, r in writes if n == "p5-run.json" ]
    assert len( run_writes ) >= 2 and all( r[ "sample_sha256" ] == want for r in run_writes )
    assert json.loads( ( scratch.data / "e2e-results" / "p5-run.json" ).read_text( encoding="utf-8" ) )[ "state" ] == "error"
    capsys.readouterr()
    assert p5.cli( scratch.args( "report" ) ) == 0                                                # a stamped partial result is read, not refused
    assert "skipped" not in capsys.readouterr().out


def test_a_changed_sample_file_makes_every_stamped_result_differ( scratch, capsys ):
    canary_and_approve( scratch )
    path = scratch.data / p5.SAMPLE_FILE
    path.write_text( path.read_text( encoding="utf-8" ) + " ", encoding="utf-8" )
    capsys.readouterr()
    assert p5.cli( scratch.args( "report" ) ) == 2
    assert "carries sample hash" in capsys.readouterr().err


def test_an_unreadable_sample_record_is_a_refusal_not_a_traceback( scratch, capsys ):
    scratch.data.mkdir()
    ( scratch.data / p5.SAMPLE_FILE ).write_text( '{"seed": "cut off', encoding="utf-8" )
    assert scratch.sample() == 2
    assert "not readable" in capsys.readouterr().err
    ( scratch.data / p5.SAMPLE_FILE ).write_text( "[1, 2]", encoding="utf-8" )
    assert p5.cli( scratch.args( "report" ) ) == 2
    assert "not a JSON object" in capsys.readouterr().err


def test_allow_fresh_is_keyword_only_everywhere_it_is_taken( scratch ):
    path = p5.needs_path( scratch.projects_data )
    with pytest.raises( TypeError ): e2e._read_checked( path, scratch.sha, "x", True )
    with pytest.raises( TypeError ): frun.load_flip_needs( path, scratch.sha, True )
    with pytest.raises( TypeError ): frun.main( [], True )
    with pytest.raises( TypeError ): frun.cli( [], True )


def test_the_flip_driver_never_turns_allow_fresh_on_and_has_no_option_for_it():
    tree = ast.parse( Path( frun.__file__ ).read_text( encoding="utf-8" ) )
    turned_on = [ n.lineno for n in ast.walk( tree ) if isinstance( n, ast.keyword ) and n.arg == "allow_fresh" and isinstance( n.value, ast.Constant ) and n.value.value is True ]
    assert turned_on == []                                                                        # it only passes its own parameter on
    defaults = [ d for n in ast.walk( tree ) if isinstance( n, ast.FunctionDef ) for d in n.args.kw_defaults if isinstance( d, ast.Constant ) and d.value is True ]
    assert defaults == []                                                                         # and no parameter of it defaults to true
    passed = [ n for n in ast.walk( tree ) if isinstance( n, ast.keyword ) and n.arg == "allow_fresh" ]
    assert len( passed ) == 3                                                                     # positive control: the three hand-offs the scan above saw
    options = [ a.value for n in ast.walk( tree ) if isinstance( n, ast.Call ) and isinstance( n.func, ast.Attribute ) and n.func.attr == "add_argument"
                for a in n.args if isinstance( a, ast.Constant ) ]
    assert options and not any( "fresh" in str( o ) for o in options )
