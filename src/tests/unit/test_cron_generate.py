"""The cron generator, the cron entry script's registry path, and the streaming runner."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

import cosa.repo.symindex.paths as paths
import cosa.rest.job_registry as jr
import cosa.rest.job_service as js_service
from cosa.repo.symindex import librarian_tick as lt
from lupin_mcp import cron_generate as cg
from lupin_mcp import job_run as jrun
from tests.unit.test_librarian_tick import cron   # noqa: F401  (fixture: the fake crontab and the fake lock)


def job( name, schedule, **extra ):
    """Ensures: returns a managed registry job with the keys load_registry demands."""
    return { "job": name, "title": name, "owner": "cheech", "schedule": schedule, "summary_path": "{root}/io/jobs/" + name + "/job-summary.json",
             "run": { "argv": [ "{python}", "-m", "x", "--trigger", "hand" ], "env": { "JOB_VAR": "{root}/j" } }, "cron_managed": True, "cron_tag": name + "-tag", **extra }


@pytest.fixture
def tree( tmp_path, monkeypatch ):
    """A root with a registry of three managed jobs and one that is not managed."""
    monkeypatch.setattr( paths, "data_dir", lambda root: tmp_path / "data" )
    jobs = [ job( "alpha", [ { "cron": "0 10 * * *" }, { "after_boot_seconds": 120 } ], cron_log="{data}/alpha.log" ),
             job( "beta", [ { "cron": "5 * * * *" }, { "after_boot_seconds": 0 }, { "every_seconds": 60 } ], cron_replaces=[ "beta-old.sh" ] ),
             job( "gamma", [ { "cron": "1 1 * * *" } ], cron_enabled=False ),
             { **job( "delta", [ { "cron": "2 2 * * *" } ] ), "cron_managed": False, "cron_exclusion_reason": "another tool owns this line" } ]
    doc = { "schema": "job-registry/1", "defaults": { "run_env": { "LUPIN_ROOT": "{root}", "D": "{deepily_data}" } }, "jobs": jobs }
    conf = tmp_path / "src" / "conf"
    conf.mkdir( parents=True )
    ( conf / "job-registry.json" ).write_text( json.dumps( doc ) )
    return tmp_path


def test_only_managed_jobs_are_picked_and_a_managed_job_needs_a_tag( tree ):
    registry = jr.load_registry( str( tree ) )
    assert [ j[ "job" ] for j in cg.managed_jobs( registry ) ] == [ "alpha", "beta", "gamma" ]
    registry[ "jobs" ][ 3 ].pop( "cron_exclusion_reason" )
    with pytest.raises( ValueError, match="delta runs, has a cron_tag or is scheduled but is neither cron_managed nor given a cron_exclusion_reason" ): cg.managed_jobs( registry )
    registry[ "jobs" ][ 3 ][ "cron_exclusion_reason" ] = "   "
    with pytest.raises( ValueError, match="delta runs" ): cg.managed_jobs( registry )
    registry[ "jobs" ][ 3 ].pop( "run" ); registry[ "jobs" ][ 3 ].pop( "cron_tag" )
    with pytest.raises( ValueError, match="delta runs" ): cg.managed_jobs( registry )                      # a cron schedule alone still needs a reason
    registry[ "jobs" ][ 3 ][ "schedule" ] = [ { "every_seconds": 60 } ]
    assert [ j[ "job" ] for j in cg.managed_jobs( registry ) ] == [ "alpha", "beta", "gamma" ], "a job with no cron-form schedule, run or tag needs no reason"
    registry = jr.load_registry( str( tree ) )
    registry[ "jobs" ][ 3 ][ "cron_exclusion_reason" ] = "another tool owns this line"
    registry[ "jobs" ][ 0 ].pop( "cron_tag" )
    with pytest.raises( ValueError, match="alpha is cron_managed but has no cron_tag" ): cg.managed_jobs( registry )


def test_lines_for_job_cover_cron_boot_with_and_without_a_wait_and_skip_the_rest( tree, tmp_path ):
    registry = jr.load_registry( str( tree ) )
    alpha, beta, gamma, _ = registry[ "jobs" ]
    script = f"{tree}/src/scripts/cron-job.sh"
    assert cg.lines_for_job( alpha, str( tree ), tmp_path / "data", {} ) == [
        f"0 10 * * * {script} alpha cron >> {tmp_path}/data/alpha.log 2>&1 # alpha-tag",
        f"@reboot sleep 120 && {script} alpha boot >> {tmp_path}/data/alpha.log 2>&1 # alpha-tag" ]
    assert cg.lines_for_job( beta, str( tree ), tmp_path / "data", {} ) == [
        f"5 * * * * {script} beta cron >> {tree}/io/jobs/beta/cron.log 2>&1 # beta-tag",
        f"@reboot {script} beta boot >> {tree}/io/jobs/beta/cron.log 2>&1 # beta-tag" ]
    assert cg.lines_for_job( gamma, str( tree ), tmp_path / "data", {} ) == [], "a disabled job writes nothing"


def test_a_path_with_a_space_is_quoted_in_the_line( tree, tmp_path ):
    alpha = jr.load_registry( str( tree ) )[ "jobs" ][ 0 ]
    line  = cg.lines_for_job( alpha, "/a b", tmp_path / "data", {} )[ 0 ]
    assert "'/a b/src/scripts/cron-job.sh'" in line


def test_generate_returns_the_block_its_tags_and_the_legacy_words_and_keeps_a_disabled_jobs_tag( tree ):
    lines, tags, legacy = cg.generate( str( tree ), {} )
    assert lines[ 0 ] == cg.HEADER and len( lines ) == 1 + 2 + 2
    assert tags == ( cg.BLOCK_TAG, "# alpha-tag", "# beta-tag", "# gamma-tag" ) and legacy == ( "beta-old.sh", )
    assert not any( "delta" in line for line in lines ), "an unmanaged job is left alone"


def test_every_generated_line_is_read_back_by_the_registry_as_its_schedule( tree ):
    lines, _, _ = cg.generate( str( tree ), {} )
    text = "\n".join( lines )
    assert jr.crontab_schedule( text, "alpha-tag" ) == [ { "cron": "0 10 * * *" }, { "after_boot_seconds": 120 } ]
    assert jr.crontab_schedule( text, "beta-tag" ) == [ { "cron": "5 * * * *" }, { "after_boot_seconds": 0 } ]


def run_main( tree, argv, cron, environ=None ):
    """Ensures: runs the generator on the fake crontab; returns ( code, out lines, err lines )."""
    out, err = [], []
    code = cg.main( [ "--root", str( tree ), *argv ], environ={ **cron[ "env" ], **( environ or {} ) }, out=out.append, err=err.append, crontab_cmd=cron[ "cmd" ] )
    return code, out, err


def test_print_and_diff_change_nothing( tree, cron ):
    cron[ "file" ].write_text( "0 0 * * * keep\n" )
    code, out, _ = run_main( tree, [], cron )
    assert code == 0 and out[ 0 ].startswith( "# Generated by" ) and out[ 0 ].count( "\n" ) >= 4
    code, out, _ = run_main( tree, [ "--diff" ], cron )
    assert code == 0 and "+0 10 * * * " in out[ 0 ] and "-" not in out[ 0 ].split( "@@" )[ -1 ].replace( "-job", "" ).split( "\n" )[ 1 ][ :1 ]
    assert cron[ "file" ].read_text() == "0 0 * * * keep\n"


def test_install_replaces_old_tagged_and_legacy_lines_keeps_the_rest_and_a_second_run_changes_nothing( tree, cron ):
    cron[ "file" ].write_text( "0 0 * * * keep\n"
                               "0 9 * * * old alpha # alpha-tag\n"
                               "7 7 * * * /x/beta-old.sh --apply >> /l 2>&1\n"
                               "@reboot sleep 5 && old gamma # gamma-tag\n"
                               "# stale header # lupin-cron-generated\n" )
    code, out, err = run_main( tree, [ "--install" ], cron )
    after = cron[ "file" ].read_text().splitlines()
    assert code == 0 and not err
    assert after[ 0 ] == "0 0 * * * keep" and after[ 1 ] == cg.HEADER and len( after ) == 1 + 1 + 4
    assert not any( word in "\n".join( after ) for word in ( "old alpha", "beta-old.sh", "old gamma", "stale header" ) )
    assert out[ 0 ].startswith( "backup of the old crontab: " ) and "-0 9 * * * old alpha # alpha-tag" in out[ 1 ]
    assert len( list( ( tree / "io" / "jobs" / "crontab-backups" ).glob( "crontab-*.txt" ) ) ) == 1
    assert ( tree / "io" / "jobs" / "beta" ).is_dir() and ( tree / "data" ).is_dir(), "the log folders exist before cron needs them"
    once = cron[ "file" ].read_text()
    now   = cg.datetime.datetime( 2026, 11, 9, 12, 0, 0 )
    first = [ p.read_text() for p in ( tree / "io" / "jobs" / "crontab-backups" ).glob( "crontab-*.txt" ) ]
    code, out, _ = cg.main( [ "--root", str( tree ), "--install" ], environ=cron[ "env" ], now=now, out=lambda t: None, crontab_cmd=cron[ "cmd" ] ), [], []
    assert code == 0 and cron[ "file" ].read_text() == once
    code, out, _ = run_main( tree, [ "--install" ], cron )
    assert code == 0 and out[ 0 ].startswith( "no change" ) and cron[ "file" ].read_text() == once
    backups = [ p.read_text() for p in ( tree / "io" / "jobs" / "crontab-backups" ).glob( "crontab-*.txt" ) ]
    assert backups == first and "old alpha" in backups[ 0 ], "a run with nothing to change leaves the pre-install backup as it was"
    assert cron[ "log" ].read_text().count( "lock-enter " + cg.LOCK_OWNER ) == 1, "only the run that changed something took the lock"


def test_status_counts_the_block_and_uninstall_removes_only_our_lines( tree, cron ):
    code, out, _ = run_main( tree, [ "--status" ], cron )
    assert out == [ "not installed; 0 of 4 job lines" ]
    cron[ "file" ].write_text( "0 0 * * * keep\n" )
    run_main( tree, [ "--install" ], cron )
    assert run_main( tree, [ "--status" ], cron )[ 1 ] == [ "installed: 1 lines; 4 of 4 job lines" ]
    code, out, _ = run_main( tree, [ "--uninstall" ], cron )
    assert code == 0 and cron[ "file" ].read_text() == "0 0 * * * keep\n"


def test_an_install_without_the_shared_lock_is_refused_with_one_and_the_reason( tree, cron ):
    code, out, err = run_main( tree, [ "--install" ], cron, { "PLANNING_IS_PROMPTING_ROOT": "/nonexistent" } )
    assert code == 1 and err and err[ 0 ].startswith( "cron-generate: " ) and out == []
    assert not cron[ "file" ].exists()


def test_a_failed_crontab_write_is_one_and_the_reason( tree, cron, monkeypatch ):
    monkeypatch.setenv( "FAKE_CRON_FAIL", "-" )
    code, _, err = run_main( tree, [ "--install" ], cron )
    assert code == 1 and "crontab write failed" in err[ 0 ]


def test_an_unreadable_crontab_command_reads_as_empty( tree ):
    assert cg.hs.crontab_text( cmd=[ "/nonexistent-crontab" ] ) is None
    out = []
    assert cg.main( [ "--root", str( tree ) ], environ={}, out=out.append, crontab_cmd=[ "/nonexistent-crontab" ] ) == 0 and out[ 0 ].startswith( "# Generated" ), "no readable crontab is an empty one"


def test_make_log_folders_skips_the_header_and_makes_every_parent( tmp_path ):
    cg.make_log_folders( [ cg.HEADER, f"* * * * * s j cron >> '{tmp_path}/a b/c/x.log' 2>&1 # t" ] )
    assert ( tmp_path / "a b" / "c" ).is_dir()


def test_main_defaults_the_root_to_the_environment_then_the_current_folder( tree, cron, monkeypatch ):
    out = []
    assert cg.main( [], environ={ "LUPIN_ROOT": str( tree ) }, out=out.append, crontab_cmd=cron[ "cmd" ] ) == 0 and out[ 0 ].startswith( "# Generated" )
    monkeypatch.chdir( tree )
    out = []
    assert cg.main( [], environ={}, out=out.append, crontab_cmd=cron[ "cmd" ] ) == 0 and out[ 0 ].startswith( "# Generated" )


def test_the_default_error_sink_is_stderr( tree, cron, capsys ):
    code = cg.main( [ "--root", str( tree ), "--install" ], environ={ "PLANNING_IS_PROMPTING_ROOT": "/nonexistent" }, out=lambda t: None, crontab_cmd=cron[ "cmd" ] )
    assert code == 1 and "cron-generate:" in capsys.readouterr().err


# ---- the real registry -------------------------------------------------------------------------------------------

REAL_ROOT = str( __import__( "pathlib" ).Path( __file__ ).resolve().parents[ 3 ] )


def test_the_real_registry_generates_a_line_set_with_the_gates_demands():
    registry = jr.load_registry( REAL_ROOT )
    managed  = { j[ "job" ]: j for j in cg.managed_jobs( registry ) }
    assert set( managed ) >= { "duplicate-check", "wiki-librarian", "reuse-behaviour", "vector-refresh", "shadow-audit", "host-snapshot", "hook-link-tick" }
    assert managed[ "hook-link-tick" ][ "clean_exit_codes" ] == [ 0, 2, 4, 5 ], "its exit codes 2, 4 and 5 are outcomes, not failures; 1 and 3 stay failures"
    assert registry[ "defaults" ][ "run_env" ][ "LUPIN_CONFIG_MGR_CLI_ARGS" ] and registry[ "defaults" ][ "run_env" ][ "COSA_VOICE_MANAGERS__LUPIN" ]
    dup = managed[ "duplicate-check" ][ "run" ][ "argv" ]
    assert dup[ dup.index( "--ceiling" ) + 1 ] == "800" and "--adaptive" in dup and dup[ dup.index( "--branch" ) + 1 ] == "auto"
    assert managed[ "duplicate-check" ].get( "cron_enabled", True ) is True, "filing fixes D3 and D4 merged on 9 Nov, so the hourly adaptive line ships enabled"
    assert managed[ "duplicate-check" ][ "schedule" ] == [ { "cron": "0 10-22 * * *" }, { "after_boot_seconds": 300 } ]
    assert managed[ "host-snapshot" ][ "schedule" ] == [ { "cron": "*/5 * * * *" } ]
    for j in managed.values(): assert j[ "cron_tag" ] and j[ "schedule" ], f"{j[ 'job' ]} has no tag or schedule"
    assert len( { j[ "cron_tag" ] for j in managed.values() } ) == len( managed ), "tags are unique, so a tag-replace never removes another job's line"


# ---- job_run --from-registry --------------------------------------------------------------------------------------

def test_run_command_is_what_run_now_and_cron_share( tree ):
    registry = jr.load_registry( str( tree ) )
    argv, env = js_service.run_command( registry, registry[ "jobs" ][ 0 ], str( tree ), tree / "data", "boot", base_env={ "KEEP": "1" } )
    assert argv[ :2 ] == [ str( tree / ".venv" / "bin" / "python" ), "-m" ] and env[ "KEEP" ] == "1" and env[ "JOB_VAR" ] == f"{tree}/j"
    assert env[ "LUPIN_ROOT" ] == str( tree ) and env[ "LUPIN_JOB_TRIGGER" ] == "boot"
    argv, env = js_service.run_command( registry, registry[ "jobs" ][ 0 ], str( tree ), tree / "data", "cron" )
    assert "PATH" in env, "with no base_env the process environment is the base"


def test_with_trigger_names_cron_or_reboot_in_a_command_that_has_the_flag():
    assert jrun.with_trigger( [ "p", "--trigger", "hand", "--x" ], "cron" ) == [ "p", "--trigger", "cron", "--x" ]
    assert jrun.with_trigger( [ "p", "--trigger", "hand" ], "boot" ) == [ "p", "--trigger", "reboot" ]
    assert jrun.with_trigger( [ "p", "--x" ], "cron" ) == [ "p", "--x" ] and jrun.with_trigger( [ "p", "--trigger" ], "cron" ) == [ "p", "--trigger" ]


def test_from_registry_runs_the_registry_command_with_the_registry_environment_and_writes_the_record( tree, monkeypatch ):
    seen = {}

    def fake( command, **kw ):
        seen.update( command=command, env=kw[ "env" ] )
        return type( "R", (), { "returncode": 0, "stdout": "", "stderr": "" } )()

    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )
    code = jrun.main( [ "--job", "alpha", "--from-registry", "--trigger", "boot" ], { "LUPIN_ROOT": str( tree ) }, fake )
    assert code == 0 and seen[ "command" ] == [ str( tree / ".venv" / "bin" / "python" ), "-m", "x", "--trigger", "reboot" ]
    assert seen[ "env" ][ "JOB_VAR" ] == f"{tree}/j" and seen[ "env" ][ "LUPIN_JOB_TRIGGER" ] == "boot"
    record = json.loads( ( tree / "io" / "jobs" / "alpha" / "job-summary.json" ).read_text() )
    assert record[ "last_attempt" ][ "trigger" ] == "boot" and record[ "last_attempt" ][ "outcome" ] == "clean"


def test_from_registry_with_a_job_that_has_no_run_block_is_refused( tree, capsys ):
    doc = json.loads( ( tree / "src/conf/job-registry.json" ).read_text() )
    doc[ "jobs" ][ 0 ].pop( "run" )
    ( tree / "src/conf/job-registry.json" ).write_text( json.dumps( doc ) )
    assert jrun.main( [ "--job", "alpha", "--from-registry" ], { "LUPIN_ROOT": str( tree ) }, lambda *a, **k: None ) == jrun.EXIT_NO_JOB
    assert "no command given" in capsys.readouterr().err


# ---- the streaming runner ------------------------------------------------------------------------------------------

def test_stream_run_passes_both_streams_through_as_they_arrive_and_returns_a_copy( capsys ):
    done = jrun.stream_run( [ sys.executable, "-c", "import sys; print('o1'); sys.stderr.write('e1\\n'); sys.exit(3)" ], env=None, capture_output=True, text=True )
    seen = capsys.readouterr()
    assert done.returncode == 3 and done.stdout == "o1\n" and done.stderr == "e1\n" and "o1" in seen.out and "e1" in seen.err


def test_stream_run_writes_a_line_before_the_command_finishes( tmp_path ):
    marker = tmp_path / "go"
    code   = "import sys, time, os; print('early', flush=True); [time.sleep(0.05) for _ in range(100) if not os.path.exists(sys.argv[1])]; print('late')"
    proc   = subprocess.Popen( [ sys.executable, "-c", f"from lupin_mcp import job_run as j; import sys; sys.exit( j.stream_run( [ sys.executable, '-c', {code!r}, {str( marker )!r} ] ).returncode )" ],
                               stdout=subprocess.PIPE, text=True )
    assert proc.stdout.readline() == "early\n", "the first line arrived while the command was still running"
    marker.write_text( "x" )
    assert proc.stdout.read() == "late\n" and proc.wait() == 0


def test_run_and_report_with_the_streaming_runner_does_not_print_the_output_twice( tmp_path, capsys, monkeypatch ):
    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )
    jrun.run_and_report( tmp_path / "s.json", "j", [ sys.executable, "-c", "print('once')" ] )
    assert capsys.readouterr().out.count( "once" ) == 1


# ---- merge_lines legacy ---------------------------------------------------------------------------------------------

def test_merge_lines_drops_a_legacy_line_whatever_its_ending_and_takes_a_tuple_of_tags():
    old = "keep\n1 * * * * a-script.sh >> log 2>&1\n2 * * * * b # t1\n3 * * * * c # t2\n"
    assert lt.merge_lines( old, [ "new # t1" ], ( "# t1", "# t2" ), ( "a-script.sh", ) ) == "keep\nnew # t1\n"
    assert lt.merge_lines( old, [], "# t1" ) == "keep\n1 * * * * a-script.sh >> log 2>&1\n3 * * * * c # t2\n"


def test_a_disabled_job_still_clears_its_old_lines_and_one_flag_flip_turns_it_on( tree, cron ):
    cron[ "file" ].write_text( "0 10 * * * old # gamma-tag\n" )
    run_main( tree, [ "--install" ], cron )
    assert "gamma" not in cron[ "file" ].read_text(), "disabled: no gamma line, and the old one is gone"
    doc = json.loads( ( tree / "src/conf/job-registry.json" ).read_text() )
    del [ j for j in doc[ "jobs" ] if j[ "job" ] == "gamma" ][ 0 ][ "cron_enabled" ]
    ( tree / "src/conf/job-registry.json" ).write_text( json.dumps( doc ) )
    run_main( tree, [ "--install" ], cron )
    assert "cron-job.sh gamma cron" in cron[ "file" ].read_text()


# ---- the bare-cron path, end to end -----------------------------------------------------------------------------

def test_the_registry_settings_that_data_dir_needs_come_before_it_runs( tree, monkeypatch ):
    registry = jr.load_registry( str( tree ) )
    got      = js_service.bootstrap_env( registry, str( tree ) )
    assert got == { "LUPIN_ROOT": str( tree ) }, "an entry that names {deepily_data} waits until the data folder is known"
    seen = {}
    monkeypatch.setattr( paths, "data_dir", lambda root: seen.update( at_data_dir=os.environ.get( "LUPIN_ROOT" ) ) or tree / "data" )
    monkeypatch.setattr( os, "environ", { "LUPIN_ROOT": str( tree ) } )
    registry[ "defaults" ][ "run_env" ][ "LUPIN_ROOT" ] = "{root}/boot"
    ( tree / "src/conf/job-registry.json" ).write_text( json.dumps( { "schema": "job-registry/1", "defaults": registry[ "defaults" ], "jobs": registry[ "jobs" ] } ) )
    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )
    jrun.main( [ "--job", "alpha", "--from-registry" ], None, lambda command, **kw: type( "R", (), { "returncode": 0, "stdout": "", "stderr": "" } )() )
    assert seen[ "at_data_dir" ] == f"{tree}/boot", "data_dir saw the registry's setting, not the bare environment's"


def test_cron_job_sh_under_env_i_gets_past_environment_loading_and_runs_the_job( tmp_path ):
    """Ensures: the script, run with cron's empty environment, reaches the job's own code."""
    real = pathlib.Path( REAL_ROOT )
    tree = tmp_path / "tree"
    ( tree / "src" / "conf" ).mkdir( parents=True )
    for child in ( real / "src" ).iterdir():
        if child.name != "conf": ( tree / "src" / child.name ).symlink_to( child )
    for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ): ( tree / "src" / "conf" / name ).symlink_to( real / "src" / "conf" / name )
    ( tree / ".venv" ).symlink_to( sys.prefix )
    shipped = jr.load_registry( REAL_ROOT )
    probe   = { "job": "probe", "title": "probe", "owner": "cheech", "schedule": [], "summary_path": "{root}/io/jobs/probe/job-summary.json",
                "run": { "argv": [ "{python}", "-c", "import os; print( 'ran', os.environ[ 'COSA_VOICE_MANAGERS__LUPIN' ] )" ], "env": {} } }
    ( tree / "src" / "conf" / "job-registry.json" ).write_text( json.dumps( { "schema": "job-registry/1", "defaults": shipped[ "defaults" ], "jobs": [ probe ] } ) )
    done = subprocess.run( [ "env", "-i", f"HOME={tmp_path}", f"DEEPILY_DATA_DIR={tmp_path / 'data'}", f"LUPIN_ROOT={tree}", str( real / "src/scripts/cron-job.sh" ), "probe", "cron" ],
                           capture_output=True, text=True, cwd=str( tmp_path ), timeout=120 )
    assert done.returncode == 0, done.stderr[ -600: ]
    assert "ran Tiberius, Mr. Radio" in done.stdout, "the registry's settings reached the job"
    record = json.loads( ( tree / "io" / "jobs" / "probe" / "job-summary.json" ).read_text() )
    assert record[ "last_attempt" ][ "outcome" ] == "clean" and record[ "last_attempt" ][ "trigger" ] == "cron"


def test_cron_job_sh_with_no_job_or_no_interpreter_or_an_unreadable_secrets_file_says_so( tmp_path ):
    script = str( pathlib.Path( REAL_ROOT ) / "src/scripts/cron-job.sh" )
    bare   = lambda *args, **env: subprocess.run( [ "env", "-i", f"HOME={tmp_path}", *[ f"{k}={v}" for k, v in env.items() ], script, *args ], capture_output=True, text=True, timeout=60 )
    none   = bare()
    assert none.returncode == 64 and "usage" in none.stderr
    gone   = bare( "x", LUPIN_ROOT=tmp_path )
    assert gone.returncode == 1 and "no interpreter" in gone.stderr
    ( tmp_path / ".venv" / "bin" ).mkdir( parents=True )
    ( tmp_path / ".venv" / "bin" / "python" ).write_text( "#!/bin/sh\necho ran \"$@\"\n" )
    ( tmp_path / ".venv" / "bin" / "python" ).chmod( 0o755 )
    secret = tmp_path / "locked.env"
    secret.write_text( "A=1\n" )
    secret.chmod( 0 )
    if os.geteuid() != 0:
        locked = bare( "x", LUPIN_ROOT=tmp_path, LUPIN_CRON_ENV=secret )
        assert locked.returncode == 1 and "cannot read" in locked.stderr
    secret.chmod( 0o644 )
    loose = bare( "x", LUPIN_ROOT=tmp_path, LUPIN_CRON_ENV=secret )
    assert loose.returncode == 1 and "must be mode 600" in loose.stderr and "chmod 600" in loose.stderr, "a secrets file other users can read is refused"
    secret.chmod( 0o600 )
    ok = bare( "x", "boot", LUPIN_ROOT=tmp_path, LUPIN_CRON_ENV=secret )
    assert ok.returncode == 0 and "--job x --from-registry --trigger boot" in ok.stdout
    absent = bare( "x", LUPIN_ROOT=tmp_path, LUPIN_CRON_ENV=tmp_path / "nope.env" )
    assert absent.returncode == 0 and "--trigger cron" in absent.stdout, "a missing secrets file is fine"


def test_a_job_that_writes_its_own_record_is_not_overwritten_by_job_run( tmp_path, monkeypatch ):
    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )
    path = tmp_path / "s.json"
    assert jrun.run_and_report( path, "j", [ "x" ], runner=lambda command, **kw: type( "R", (), { "returncode": 0, "stdout": "", "stderr": "" } )(), write_record=False ) == 0
    assert not path.exists()


def test_main_passes_own_summary_through_as_no_record_written( tree, monkeypatch ):
    doc = json.loads( ( tree / "src/conf/job-registry.json" ).read_text() )
    doc[ "jobs" ][ 0 ][ "own_summary" ] = True
    ( tree / "src/conf/job-registry.json" ).write_text( json.dumps( doc ) )
    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )
    code = jrun.main( [ "--job", "alpha", "--from-registry" ], { "LUPIN_ROOT": str( tree ) }, lambda command, **kw: type( "R", (), { "returncode": 0, "stdout": "", "stderr": "" } )() )
    assert code == 0 and not ( tree / "io" / "jobs" / "alpha" / "job-summary.json" ).exists()


def test_the_four_jobs_that_write_their_own_record_are_marked_so_in_the_shipped_registry():
    own = { j[ "job" ] for j in jr.load_registry( REAL_ROOT )[ "jobs" ] if j.get( "own_summary" ) }
    assert own == { "duplicate-check", "wiki-librarian", "vector-refresh", "reuse-behaviour" }


def test_exit_codes_a_job_lists_as_clean_are_recorded_clean_and_the_rest_failed( tmp_path, monkeypatch ):
    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )
    answer = lambda code: ( lambda command, **kw: type( "R", (), { "returncode": code, "stdout": "", "stderr": "" } )() )
    path   = tmp_path / "s.json"
    for code, outcome in ( ( 0, "clean" ), ( 2, "clean" ), ( 5, "clean" ), ( 1, "failed" ), ( 3, "failed" ) ):
        assert jrun.run_and_report( path, "j", [ "x" ], runner=answer( code ), clean_codes=( 0, 2, 4, 5 ) ) == code, "the exit code itself is passed on unchanged"
        attempt = json.loads( path.read_text() )[ "last_attempt" ]
        assert attempt[ "outcome" ] == outcome and attempt[ "failure" ] == ( None if outcome == "clean" else f"exit {code}" )
    jrun.run_and_report( path, "j", [ "x" ], runner=answer( 2 ) )
    assert json.loads( path.read_text() )[ "last_attempt" ][ "outcome" ] == "failed", "with no list, only 0 is clean"


def test_main_reads_clean_exit_codes_from_the_registry_entry( tree, monkeypatch ):
    doc = json.loads( ( tree / "src/conf/job-registry.json" ).read_text() )
    doc[ "jobs" ][ 0 ][ "clean_exit_codes" ] = [ 0, 2 ]
    ( tree / "src/conf/job-registry.json" ).write_text( json.dumps( doc ) )
    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )
    code = jrun.main( [ "--job", "alpha", "--from-registry" ], { "LUPIN_ROOT": str( tree ) }, lambda command, **kw: type( "R", (), { "returncode": 2, "stdout": "", "stderr": "" } )() )
    assert code == 2 and json.loads( ( tree / "io" / "jobs" / "alpha" / "job-summary.json" ).read_text() )[ "last_attempt" ][ "outcome" ] == "clean"


def test_every_registry_job_that_runs_or_has_a_cron_tag_is_managed_or_says_why_not():
    jobs     = jr.load_registry( REAL_ROOT )[ "jobs" ]
    runnable = [ j for j in jobs if j.get( "run" ) or j.get( "cron_tag" ) or any( "cron" in e or "after_boot_seconds" in e for e in j.get( "schedule", [] ) ) ]
    managed  = [ j for j in runnable if j.get( "cron_managed" ) ]
    excluded = [ j for j in runnable if not j.get( "cron_managed" ) ]
    assert len( managed ) >= 9 and len( excluded ) >= 3, "the loop below sees both populations"
    assert "yearly-reminders" in { j[ "job" ] for j in excluded }
    assert "worktree-census" in { j[ "job" ] for j in managed }
    census = next( j for j in managed if j[ "job" ] == "worktree-census" )
    assert census[ "clean_exit_codes" ] == [ 0, 1 ], "it exits 1 whenever it has findings, which is its report, not a failure"
    for j in excluded: assert ( j.get( "cron_exclusion_reason" ) or "" ).strip(), f"{j[ 'job' ]} runs or has a cron tag but is neither managed nor excluded with a reason"
    for j in managed: assert not j.get( "cron_exclusion_reason" ), f"{j[ 'job' ]} is managed, so it carries no exclusion reason"


# ---- an own_summary job that crashes before it writes ------------------------------------------------------------

def answer( code, before=None ):
    """Ensures: returns a runner stand-in that runs before() when given, then exits with code."""
    def run( command, **kw ):
        if before: before()
        return type( "R", (), { "returncode": code, "stdout": "", "stderr": "" } )()
    return run


def test_an_own_summary_job_that_fails_before_writing_still_leaves_a_failed_record( tmp_path, monkeypatch ):
    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )
    path = tmp_path / "s.json"
    jrun.run_and_report( path, "j", [ "x" ], runner=answer( 1 ), write_record=False )
    assert json.loads( path.read_text() )[ "last_attempt" ][ "outcome" ] == "failed", "no record at all: one is written"
    path.write_text( json.dumps( { **json.loads( path.read_text() ), "last_attempt": { **json.loads( path.read_text() )[ "last_attempt" ], "outcome": "clean", "failure": None, "finished_at": "2020-01-01T00:00:00+00:00" } } ) )
    jrun.run_and_report( path, "j", [ "x" ], runner=answer( 3 ), write_record=False )
    got = json.loads( path.read_text() )[ "last_attempt" ]
    assert got[ "outcome" ] == "failed" and got[ "failure" ] == "exit 3", "an old clean record does not stand in for this crash"


def test_an_own_summary_job_that_wrote_its_own_record_or_exited_clean_is_left_alone( tmp_path, monkeypatch ):
    monkeypatch.setattr( jrun.hs, "refresh_best_effort", lambda environ=None: None )
    path = tmp_path / "s.json"
    own  = lambda: jrun.js.write_summary( path, "j", { "started_at": jrun.js.iso_now(), "finished_at": jrun.js.iso_now(), "trigger": "cron", "outcome": "failed", "stage": "mine", "failure": "its own words", "evidence": None, "mode": None } )
    jrun.run_and_report( path, "j", [ "x" ], runner=answer( 2, own ), write_record=False )
    assert json.loads( path.read_text() )[ "last_attempt" ][ "stage" ] == "mine", "a failing job that wrote its own record keeps it"
    path.unlink()
    jrun.run_and_report( path, "j", [ "x" ], runner=answer( 0 ), write_record=False )
    assert not path.exists(), "a clean exit writes nothing for an own_summary job"


def test_recorded_since_reads_the_finish_time_and_refuses_what_it_cannot_read( tmp_path ):
    started = jrun.datetime.datetime( 2026, 11, 9, 12, 0, 0, tzinfo=jrun.datetime.timezone.utc )
    path    = tmp_path / "s.json"
    assert jrun.recorded_since( path, started ) is False, "missing file"
    base    = { "schema": jrun.js.SCHEMA, "last_attempt": { "finished_at": "2026-11-09T12:00:01+00:00" } }
    path.write_text( json.dumps( base ) )
    assert jrun.recorded_since( path, started ) is True
    for bad in ( { **base, "last_attempt": { "finished_at": "2026-11-09T11:59:59+00:00" } }, { **base, "last_attempt": {} }, { **base, "last_attempt": { "finished_at": "not a time" } }, { **base, "last_attempt": { "finished_at": "2026-11-09T12:00:01" } } ):
        path.write_text( json.dumps( bad ) )
        assert jrun.recorded_since( path, started ) is False


# ---- one scratch-crontab override for every tool --------------------------------------------------------------

def test_crontab_command_prefers_the_shared_override_then_the_tools_own_variable_then_crontab():
    assert lt.crontab_command( { "LUPIN_CRONTAB": "/scratch", "X": "/own" }, "X" ) == [ "/scratch" ]
    assert lt.crontab_command( { "X": "/own" }, "X" ) == [ "/own" ] and lt.crontab_command( { "LUPIN_CRONTAB": "" , "X": "/own" }, "X" ) == [ "/own" ]
    assert lt.crontab_command( {}, "X" ) == [ "crontab" ] and lt.crontab_command( {} ) == [ "crontab" ] and lt.crontab_command( { "LUPIN_CRONTAB": "/s" } ) == [ "/s" ]


def test_the_vector_refresh_install_refuses_on_every_crontab_and_writes_nothing( cron, tmp_path, monkeypatch ):
    import io
    from cosa.repo.symindex import vector_refresh as vr
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    def install():
        out, err = io.StringIO(), io.StringIO()
        code = vr.main( [ "--install", "--root", str( tmp_path / "repo" ), "--python", "/py" ], environ=cron[ "env" ], now=cg.datetime.datetime( 2026, 11, 9, 12, 0 ), out=out, err=err, crontab_cmd=cron[ "cmd" ] )
        return code, out.getvalue(), err.getvalue()
    for text in ( f"0 * * * * x\n{cg.HEADER}\n", "0 * * * * x\n" ):          # a host crontab with the generated block, then the VM's without one
        cron[ "file" ].write_text( text )
        code, out, err = install()
        assert code == 1 and out == "" and "lupin_mcp.cron_generate --install" in err and cron[ "file" ].read_text() == text


def test_with_the_shared_override_set_no_tool_touches_the_real_crontab( cron, tmp_path, monkeypatch ):
    """Ensures: each writer, given only LUPIN_CRONTAB, uses the scratch crontab."""
    import io
    poison = tmp_path / "poison"
    poison.mkdir()
    ( poison / "crontab" ).write_text( f"#!/bin/sh\necho \"$@\" >> {tmp_path}/real-crontab-calls\nexit 1\n" )
    ( poison / "crontab" ).chmod( 0o755 )
    monkeypatch.setenv( "PATH", f"{poison}:{os.environ[ 'PATH' ]}" )
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    ( tmp_path / "repo" ).mkdir()
    env = dict( cron[ "env" ] )
    scratch = tmp_path / "scratch-crontab"
    scratch.write_text( "#!/bin/sh\nexec " + " ".join( cron[ "cmd" ] ) + ' "$@"\n' )
    scratch.chmod( 0o755 )
    env[ "LUPIN_CRONTAB" ] = str( scratch )
    cron[ "file" ].write_text( f"0 * * * * x\n1 1 * * * a {lt.CRON_TAG}\n" )
    from cosa.repo.symindex import vector_refresh as vr
    from lupin_mcp import host_snapshot as hs, reuse_shadow as rs, duplicate_check_daily as dd
    now = cg.datetime.datetime( 2026, 11, 9, 12, 0 )
    root = str( tmp_path / "repo" )
    sink = lambda text: None
    results = [ cg.main( [ "--root", REAL_ROOT, "--install" ], environ=env, now=now, out=sink, err=sink ),
                vr.main( [ "--install", "--root", root ], environ=env, now=now, out=io.StringIO(), err=io.StringIO() ),
                lt.main( [ "--uninstall", "--root", root ], environ=env, now=now, out=io.StringIO(), err=io.StringIO() ),
                rs.main( [ "--uninstall", "--root", root ], environ=env, now=now, out=io.StringIO(), err=io.StringIO() ),
                dd.main( [ "--uninstall", "--root", root ], environ=env, now=now, out=sink, err=sink ),
                hs.main( [ "--uninstall", "--root", root ], environ=env, now=now, out=sink, err=sink ) ]
    assert results == [ 0, 1, 0, 0, 0, 0 ], results                     # the kept vector-refresh install refuses: the scratch crontab now holds cron_generate's block, which it read through the override
    assert not ( tmp_path / "real-crontab-calls" ).exists(), "the crontab on PATH was never run"
    assert cron[ "log" ].read_text().count( "lock-enter" ) >= 5, "every writer went through the scratch crontab's lock path"
    assert cg.HEADER in cron[ "file" ].read_text() and "0 * * * * x" in cron[ "file" ].read_text()


def test_only_prints_just_that_jobs_lines_with_no_header_and_names_an_unknown_job( tree, cron ):
    code, out, _ = run_main( tree, [ "--only", "alpha" ], cron )
    assert code == 0 and cg.HEADER not in out[ 0 ] and out[ 0 ].count( "# alpha-tag" ) >= 1 and "beta" not in out[ 0 ]
    code, out, err = run_main( tree, [ "--only", "nope" ], cron )
    assert code == 1 and out == [] and "--only names nope, which is not a cron_managed job" in err[ 0 ]
    with pytest.raises( ValueError, match="not a cron_managed job" ): cg.generate( str( tree ), {}, "delta" )


def test_only_installs_one_jobs_lines_and_leaves_every_other_line_and_the_header_alone( tree, cron ):
    cron[ "file" ].write_text( "0 0 * * * keep\n0 9 * * * old alpha # alpha-tag\n5 5 * * * old beta # beta-tag\n# header # lupin-cron-generated\n" )
    code, out, err = run_main( tree, [ "--only", "alpha", "--install" ], cron )
    after = cron[ "file" ].read_text().splitlines()
    assert code == 0 and not err
    assert "0 0 * * * keep" in after and "5 5 * * * old beta # beta-tag" in after and "# header # lupin-cron-generated" in after
    assert not any( "old alpha" in line for line in after ) and sum( line.endswith( "# alpha-tag" ) for line in after ) >= 1
    assert cg.HEADER not in after, "the full block's header is not rewritten"
    code, out, _ = run_main( tree, [ "--only", "alpha", "--status" ], cron )
    assert code == 0 and out[ 0 ].startswith( "installed: " ), out
    code, out, _ = run_main( tree, [ "--only", "alpha", "--install" ], cron )
    assert code == 0 and out[ 0 ].startswith( "no change" )
    code, out, _ = run_main( tree, [ "--only", "alpha", "--uninstall" ], cron )
    left = cron[ "file" ].read_text()
    assert code == 0 and "# alpha-tag" not in left and "keep" in left and "old beta" in left


def test_cron_job_sh_falls_back_to_the_vm_interpreter_when_the_checkout_has_no_venv( tmp_path ):
    script = str( pathlib.Path( REAL_ROOT ) / "src/scripts/cron-job.sh" )
    run    = lambda: subprocess.run( [ "env", "-i", f"HOME={tmp_path}", f"LUPIN_ROOT={tmp_path / 'checkout'}", script, "x" ], capture_output=True, text=True, timeout=60 )
    ( tmp_path / "checkout" ).mkdir()
    gone = run()
    assert gone.returncode == 1 and ".venv-lupin-mcp/bin/python" in gone.stderr and "no interpreter" in gone.stderr
    ( tmp_path / ".venv-lupin-mcp" / "bin" ).mkdir( parents=True )
    ( tmp_path / ".venv-lupin-mcp" / "bin" / "python" ).write_text( "#!/bin/sh\necho vm-python \"$@\"\n" )
    ( tmp_path / ".venv-lupin-mcp" / "bin" / "python" ).chmod( 0o755 )
    ok = run()
    assert ok.returncode == 0 and "vm-python -m lupin_mcp.job_run --job x" in ok.stdout
    ( tmp_path / "checkout" / ".venv" / "bin" ).mkdir( parents=True )
    ( tmp_path / "checkout" / ".venv" / "bin" / "python" ).write_text( "#!/bin/sh\necho checkout-python\n" )
    ( tmp_path / "checkout" / ".venv" / "bin" / "python" ).chmod( 0o755 )
    assert "checkout-python" in run().stdout, "the checkout's own venv still wins"


def test_backup_dir_prints_the_folder_and_does_nothing_else( tree, cron ):
    code, out, err = run_main( tree, [ "--backup-dir" ], cron )
    assert code == 0 and out == [ cg.BACKUP_DIR ] and err == []
    assert not ( tree / cg.BACKUP_DIR ).exists()
