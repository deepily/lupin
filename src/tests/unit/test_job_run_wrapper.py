"""The cron wrapper that writes a record for a shell job."""
import json
import pathlib
import types

import pytest

from lupin_mcp import job_run as jr_mod
import cosa.rest.job_registry as jr


ON = types.SimpleNamespace( get_required=lambda key, return_type="string": True )     # a configuration stand-in whose every switch is on


def fake( code=0, out="", err="" ):
    """Ensures: returns a runner stand-in that answers with the given result."""
    return lambda command, **kw: types.SimpleNamespace( returncode=code, stdout=out, stderr=err )


def test_last_int_reads_the_last_capture_with_commas_and_tolerates_no_match():
    assert jr_mod.last_int( r"eligible (\d[\d,]*)", "eligible 1\neligible 61,278\n" ) == 61278
    assert jr_mod.last_int( r"eligible (\d+)", "nothing" ) is None and jr_mod.last_int( None, "x" ) is None
    assert jr_mod.last_int( r"(a|b)", "a" ) is None and jr_mod.last_int( r"(\d)(\d)", "12" ) == 1


def test_a_clean_command_writes_a_clean_record_with_counts_and_passes_output_through(tmp_path, capsys):
    path = tmp_path / "s.json"
    code = jr_mod.run_and_report( path, "sweep", [ "x" ], "daily", r"eligible (\d+)", r"reclaimed (\d+)", {}, fake( 0, "eligible 61278\nreclaimed 61275\n", "warn\n" ) )
    doc  = json.loads( path.read_text() )
    assert code == 0 and doc[ "last_attempt" ][ "outcome" ] == "clean" and doc[ "last_attempt" ][ "mode" ] == "daily"
    assert doc[ "scan_debt" ][ "count" ] == 61278 and doc[ "scan_debt" ][ "drained_last_run" ] == 61275 and doc[ "work_found_last_run" ] == 61278
    seen = capsys.readouterr()
    assert "eligible 61278" in seen.out and "warn" in seen.err


def test_a_failing_or_unstartable_command_is_failed_and_keeps_its_exit_code(tmp_path, capsys):
    path = tmp_path / "s.json"
    assert jr_mod.run_and_report( path, "sweep", [ "x" ], environ={ "LUPIN_JOB_TRIGGER": "hand" }, runner=fake( 3 ) ) == 3
    got = json.loads( path.read_text() )
    assert got[ "last_attempt" ][ "failure" ] == "exit 3" and got[ "last_attempt" ][ "trigger" ] == "hand" and got[ "scan_debt" ] is None
    def missing( command, **kw ): raise FileNotFoundError( command[ 0 ] )
    assert jr_mod.run_and_report( path, "sweep", [ "nope" ], runner=missing ) == 127
    assert "could not start nope" in capsys.readouterr().err and json.loads( path.read_text() )[ "consecutive_failures" ] == 2


def test_main_finds_the_job_in_the_registry_and_refuses_an_unknown_job_or_an_empty_command(tmp_path, monkeypatch, capsys):
    reg = tmp_path / jr.REGISTRY_FILE
    reg.parent.mkdir( parents=True )
    reg.write_text( json.dumps( { "schema": "job-registry/1", "defaults": {}, "jobs": [ { "job": "j", "enabled_key": "cron job j enabled", "title": "J", "owner": "cheech", "summary_path": "{root}/out/j.json" } ] } ) )
    import cosa.repo.symindex.paths as paths
    monkeypatch.setattr( paths, "data_dir", lambda root: tmp_path / "data" )
    env = { "LUPIN_ROOT": str( tmp_path ) }
    assert jr_mod.main( [ "--job", "j", "--", "echo", "hi" ], env, fake( 0, "hi\n" ), config=ON ) == 0 and ( tmp_path / "out" / "j.json" ).exists()
    assert jr_mod.main( [ "--job", "j", "echo" ], env, fake( 0 ), config=ON ) == 0
    assert jr_mod.main( [ "--job", "zzz", "--", "echo" ], env, fake( 0 ), config=ON ) == jr_mod.EXIT_NO_JOB and "no job zzz" in capsys.readouterr().err
    assert jr_mod.main( [ "--job", "j" ], env, fake( 0 ), config=ON ) == jr_mod.EXIT_NO_JOB and "no command" in capsys.readouterr().err
    monkeypatch.chdir( tmp_path )
    assert jr_mod.main( [ "--job", "j", "--", "x" ], {}, fake( 0 ), config=ON ) == 0


def test_a_wrapped_run_leaves_the_container_a_fresh_crontab_copy(tmp_path, monkeypatch):
    from lupin_mcp import host_snapshot as hs
    seen = []
    monkeypatch.setattr( hs, "refresh_best_effort", lambda environ=None, now=None, run=None: seen.append( environ ) or True )
    jr_mod.run_and_report( tmp_path / "s.json", "j", [ "x" ], environ={ "K": "v" }, runner=fake( 0 ) )
    assert seen == [ { "K": "v" } ]


def switch_tree( tmp_path, monkeypatch, own_summary=False ):
    """Ensures: returns the env of a root whose registry holds the job j with a switch."""
    reg = tmp_path / jr.REGISTRY_FILE
    reg.parent.mkdir( parents=True )
    entry = { "job": "j", "enabled_key": "cron job j enabled", "title": "J", "owner": "cheech", "summary_path": "{root}/out/j.json", "run": { "argv": [ "echo", "hi" ], "env": {} } }
    reg.write_text( json.dumps( { "schema": "job-registry/1", "defaults": { "run_env": {} }, "jobs": [ entry ] } ) )
    import cosa.repo.symindex.paths as paths
    monkeypatch.setattr( paths, "data_dir", lambda root: tmp_path / "data" )
    return { "LUPIN_ROOT": str( tmp_path ) }


def reader( value, asked ):
    """Ensures: returns a configuration stand-in that records each ask and answers value."""
    def get_required( key, return_type="string" ):
        asked.append( ( key, return_type ) )
        return value
    return types.SimpleNamespace( get_required=get_required )


@pytest.mark.parametrize( "argv", [ [ "--job", "j", "--", "echo", "hi" ], [ "--job", "j", "--trigger", "cron", "--from-registry" ], [ "--job", "j", "--trigger", "boot", "--from-registry" ], [ "--job", "j", "--from-registry" ] ] )
def test_a_switched_off_job_logs_its_key_and_exits_zero_before_any_work( tmp_path, monkeypatch, capsys, argv ):
    env, asked, ran = switch_tree( tmp_path, monkeypatch ), [], []
    code = jr_mod.main( argv, env, lambda command, **kw: ran.append( command ), config=reader( False, asked ) )
    out  = capsys.readouterr().out
    assert code == 0 and ran == [] and asked == [ ( "cron job j enabled", "boolean" ) ]
    assert out.count( "\n" ) == 1 and "cron job j enabled" in out and "switched off" in out
    assert not ( tmp_path / "out" ).exists() and not ( tmp_path / "data" ).exists()


def test_a_switched_on_job_runs_and_a_missing_key_or_missing_enabled_key_stops_the_run( tmp_path, monkeypatch ):
    env, asked, ran = switch_tree( tmp_path, monkeypatch ), [], []
    assert jr_mod.main( [ "--job", "j", "--", "echo", "hi" ], env, fake( 0 ), config=reader( True, asked ) ) == 0 and ( tmp_path / "out" / "j.json" ).exists()
    def absent( key, return_type="string" ): raise KeyError( key )
    with pytest.raises( KeyError ): jr_mod.main( [ "--job", "j", "--", "echo" ], env, fake( 0 ), config=types.SimpleNamespace( get_required=absent ) )
    reg  = tmp_path / jr.REGISTRY_FILE
    doc  = json.loads( reg.read_text() ); doc[ "jobs" ][ 0 ].pop( "enabled_key" ); reg.write_text( json.dumps( doc ) )
    with pytest.raises( ValueError, match="no enabled_key" ): jr_mod.main( [ "--job", "j", "--", "echo" ], env, fake( 0 ), config=reader( True, [] ) )


def test_the_switch_is_read_through_a_silent_configuration_manager( tmp_path, monkeypatch, capsys ):
    """The manager prints a 37-line banner, so it is built silent and its prints are swallowed."""
    import cosa.config.configuration_manager as cm
    built = []
    class Quiet:
        def __init__( self, **kw ): built.append( kw ); print( "banner noise" )
        def get_required( self, key, return_type="string" ): return False
    monkeypatch.setattr( cm, "ConfigurationManager", Quiet )
    env = switch_tree( tmp_path, monkeypatch )
    env[ "LUPIN_CONFIG_MGR_CLI_ARGS" ] = "x"
    assert jr_mod.main( [ "--job", "j", "--", "echo" ], env, fake( 0 ) ) == 0
    assert built == [ { "env_var_name": "LUPIN_CONFIG_MGR_CLI_ARGS", "silent": True, "mute_splainer": True } ]
    assert "banner noise" not in capsys.readouterr().out
