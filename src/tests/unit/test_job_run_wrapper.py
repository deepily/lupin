"""The cron wrapper that writes a record for a shell job."""
import json
import pathlib
import types

import pytest

from lupin_mcp import job_run as jr_mod
import cosa.rest.job_registry as jr


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
    reg.write_text( json.dumps( { "schema": "job-registry/1", "defaults": {}, "jobs": [ { "job": "j", "title": "J", "owner": "cheech", "summary_path": "{root}/out/j.json" } ] } ) )
    import cosa.repo.symindex.paths as paths
    monkeypatch.setattr( paths, "data_dir", lambda root: tmp_path / "data" )
    env = { "LUPIN_ROOT": str( tmp_path ) }
    assert jr_mod.main( [ "--job", "j", "--", "echo", "hi" ], env, fake( 0, "hi\n" ) ) == 0 and ( tmp_path / "out" / "j.json" ).exists()
    assert jr_mod.main( [ "--job", "j", "echo" ], env, fake( 0 ) ) == 0
    assert jr_mod.main( [ "--job", "zzz", "--", "echo" ], env, fake( 0 ) ) == jr_mod.EXIT_NO_JOB and "no job zzz" in capsys.readouterr().err
    assert jr_mod.main( [ "--job", "j" ], env, fake( 0 ) ) == jr_mod.EXIT_NO_JOB and "no command" in capsys.readouterr().err
    monkeypatch.chdir( tmp_path )
    assert jr_mod.main( [ "--job", "j", "--", "x" ], {}, fake( 0 ) ) == 0
