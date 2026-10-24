"""
Unit tests for the daily vector-freshness job.

They cover the due rule, the freshness check, the retry, the failure record, the cron lines
and the command line. The index, the job transport and the embeddings client are fakes. The
data folder is a temporary folder and the crontab is the librarian tests' fake script.
Venue: :7999-eligible.
"""
import datetime
import json
import os
import pathlib

import pytest

from cosa.repo.symindex import candidate_build as cb
from cosa.repo.symindex import librarian_tick as lt
from cosa.repo.symindex import vector_refresh as vr
from cosa.repo.symindex.candidates import freshness as fr
from cosa.repo.symindex.candidates import purpose_lines as pl
from cosa.repo.symindex.candidates.errors import CandidateError, STORAGE_KEY_MISSING, DEPENDENCY_MISSING, ENGINE_NOT_LOADED

import test_candidates_vector_build as tvb
from test_librarian_tick import cron  # noqa: F401  (fixture: the fake crontab and the fake lock)

NOON     = datetime.datetime( 2026, 10, 15, 12, 0, 0 )
EARLY    = datetime.datetime( 2026, 10, 15, 3, 0, 0 )
TOMORROW = datetime.datetime( 2026, 10, 16, 10, 30, 0 )


class ConfigFor:
    def get( self, key, default=None, silent=False, return_type="string" ):
        return { "reuse candidate vectors subdir": "vec", "reuse candidate query cache subdir": "qc",
                 "reuse candidate purpose lines subdir": "pl" }.get( key, default )


def answering_writer( calls ):
    def w( ids ):
        calls.append( list( ids ) )
        return { i: f"Return {i}." for i in ids }
    return w


def symbol( name, pin ):
    return { **tvb.entry( name, pin, doc=f"Does {name}." ), "lang": "py", "kind": "function", "line": 1, "public": True }


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """Two public entries in a fake index, a data folder in tmp_path and a state path beside it."""
    symbols = [ symbol( "b", "pb" ), symbol( "a", "pa" ) ]
    header  = { "manifest": { "m.py": [ 1, 2 ] }, "symbols_sha": "sha-1" }
    monkeypatch.setattr( vr.sx_build, "ensure", lambda root: "gen" )
    monkeypatch.setattr( vr.sx_build, "read_header", lambda gen: header )
    monkeypatch.setattr( vr.sx_build, "read_searchable", lambda gen: symbols )
    monkeypatch.setattr( vr, "data_dir", lambda root: tmp_path / "data" )
    monkeypatch.setattr( cb, "data_dir", lambda root: tmp_path / "data" )
    return { "root": tmp_path / "repo", "data": tmp_path / "data", "state": str( tmp_path / "data" / "refresh" / vr.STATE_NAME ),
             "symbols": symbols, "header": header, "log": [] }


def go( world, writer=None, client=None, now=NOON, force=False, **extra ):
    return vr.run_refresh( world[ "root" ], writer or answering_writer( [] ), client or tvb.FakeClient(), world[ "state" ], now,
                           force=force, log=world[ "log" ].append, config=ConfigFor(), environ={}, **extra )


def state_of( world ): return json.loads( pathlib.Path( world[ "state" ] ).read_text() )


# ── due ─────────────────────────────────────────────────────────────────────


def test_a_run_before_ten_is_not_due_and_touches_nothing( world ):
    code, summary = go( world, now=EARLY )
    assert ( code, summary ) == ( 0, { "ran": False, "reason": "not due" } )
    assert not pathlib.Path( world[ "state" ] ).exists() and not world[ "data" ].exists()


def test_force_runs_before_ten( world ):
    code, summary = go( world, now=EARLY, force=True )
    assert code == 0 and summary[ "outcome" ] == "built"


# ── build, then fresh ───────────────────────────────────────────────────────


def test_the_first_run_builds_records_the_day_and_writes_build_info_into_the_live_set( world ):
    calls = []
    code, summary = go( world, writer=answering_writer( calls ) )
    assert code == 0
    assert summary[ "outcome" ] == "built" and summary[ "reason" ] == "the live set has no build info" and summary[ "rows" ] == 2
    assert summary[ "purposes_written" ] == 2 and sorted( calls[ 0 ] ) == [ "m.a", "m.b" ]
    state = state_of( world )
    assert state[ "last_run_date" ] == "2026-10-15" and state[ "last_outcome" ] == "built" and state[ "last_error" ] is None
    assert state[ "built_at" ] == summary[ "built_at" ] and state[ "last_attempt_at" ] == NOON.isoformat( timespec="seconds" )
    info = fr.read_build_info( world[ "data" ] / "vec" )
    assert info[ "index_manifest" ] == fr.index_manifest( world[ "header" ] ) and info[ "built_at" ] == summary[ "built_at" ]


def test_the_same_day_is_not_due_again_but_a_forced_run_on_an_unchanged_tree_is_fresh_and_does_no_work( world ):
    go( world )
    assert go( world )[ 1 ] == { "ran": False, "reason": "not due" }
    calls, client = [], tvb.FakeClient()
    before = ( world[ "data" ] / "vec" / "manifest.json" ).read_text()
    code, summary = go( world, writer=answering_writer( calls ), client=client, force=True )
    assert ( code, summary[ "outcome" ], summary[ "reason" ] ) == ( 0, "fresh", "fresh" )
    assert calls == [] and client.calls == []
    assert ( world[ "data" ] / "vec" / "manifest.json" ).read_text() == before
    assert state_of( world )[ "last_outcome" ] == "fresh" and state_of( world )[ "built_at" ] == fr.read_build_info( world[ "data" ] / "vec" )[ "built_at" ]


def test_the_next_day_after_a_build_is_due_and_finds_the_set_fresh( world ):
    go( world )
    code, summary = go( world, now=TOMORROW )
    assert summary[ "outcome" ] == "fresh" and state_of( world )[ "last_run_date" ] == "2026-10-16"


# ── what makes a set not fresh ──────────────────────────────────────────────


def test_a_changed_index_manifest_forces_a_rebuild( world ):
    go( world )
    world[ "header" ][ "manifest" ] = { "m.py": [ 1, 3 ] }
    code, summary = go( world, force=True )
    assert summary[ "outcome" ] == "built" and summary[ "reason" ] == "the index changed since the set was built"
    assert fr.read_build_info( world[ "data" ] / "vec" )[ "index_manifest" ] == fr.index_manifest( world[ "header" ] )


def test_an_engine_revision_change_forces_a_rebuild_and_names_the_engines( world ):
    go( world )
    code, summary = go( world, client=tvb.FakeClient( revision="rev2" ), force=True )
    assert summary[ "outcome" ] == "built" and summary[ "reason" ] == "engines: ENGINE_MISMATCH"


def test_an_engine_that_is_not_loaded_is_a_reason_and_the_build_then_fails_with_the_named_error( world ):
    go( world )
    code, summary = go( world, client=tvb.FakeClient( revision=None ), force=True )
    assert code == 2 and summary[ "outcome" ] == "failed" and summary[ "reason" ].startswith( ENGINE_NOT_LOADED )
    assert any( "refresh needed: engines: ENGINE_NOT_LOADED" in line for line in world[ "log" ] )


def test_a_pin_without_a_stored_line_forces_a_rebuild( world ):
    go( world )
    world[ "symbols" ].append( symbol( "c", "pc" ) )
    calls = []
    code, summary = go( world, writer=answering_writer( calls ), force=True )
    assert summary[ "reason" ] == "1 pins have no purpose line" and summary[ "outcome" ] == "built"
    assert calls == [ [ "m.c" ] ]


def test_a_set_with_no_build_info_is_never_taken_as_fresh( world ):
    go( world )
    ( world[ "data" ] / "vec" / fr.BUILD_INFO_FILE ).unlink()
    code, summary = go( world, force=True )
    assert summary[ "outcome" ] == "built" and summary[ "reason" ] == "the live set has no build info"


def test_an_unreadable_manifest_forces_a_rebuild( world ):
    go( world )
    ( world[ "data" ] / "vec" / "manifest.json" ).write_text( "{bad" )
    code, summary = go( world, force=True )
    assert summary[ "outcome" ] == "built" and summary[ "reason" ] == "the live set's manifest cannot be read"


# ── failure behaviour ───────────────────────────────────────────────────────


def test_a_timeout_is_retried_once_and_the_second_attempt_finishes_the_run( world ):
    calls = []

    def flaky( ids ):
        calls.append( list( ids ) )
        if len( calls ) == 1: raise TimeoutError( "no response file x within 1800 s" )
        return { i: f"Return {i}." for i in ids }

    code, summary = go( world, writer=flaky )
    assert code == 0 and summary[ "outcome" ] == "built" and len( calls ) == 2
    assert any( "attempt 1 of 2 timed out" in line for line in world[ "log" ] )


def test_two_timeouts_end_the_run_with_the_failure_named_and_the_live_set_and_the_day_untouched( world ):
    go( world )
    set_before = ( world[ "data" ] / "vec" / "manifest.json" ).read_text()
    built_at   = state_of( world )[ "built_at" ]
    world[ "header" ][ "manifest" ] = { "m.py": [ 9, 9 ] }
    world[ "symbols" ].append( symbol( "c", "pc" ) )
    calls = []

    def always( ids ):
        calls.append( ids )
        raise TimeoutError( "stalled" )

    code, summary = go( world, writer=always, now=TOMORROW )
    assert code == 1 and summary == { "ran": False, "outcome": "failed", "reason": "TimeoutError: stalled" } and len( calls ) == 2
    state = state_of( world )
    assert state[ "last_outcome" ] == "failed" and state[ "last_error" ] == "TimeoutError: stalled"
    assert state[ "last_run_date" ] == "2026-10-15" and state[ "built_at" ] == built_at
    assert ( world[ "data" ] / "vec" / "manifest.json" ).read_text() == set_before
    assert go( world, writer=answering_writer( [] ), now=TOMORROW )[ 1 ][ "outcome" ] == "built"


@pytest.mark.parametrize( "error", [ RuntimeError( "submit answered 500" ), ValueError( "not a list" ), OSError( "disk full" ) ] )
def test_other_job_errors_end_the_run_with_exit_one_and_the_error_recorded( world, error ):
    def broken( ids ): raise error

    code, summary = go( world, writer=broken )
    assert code == 1 and summary[ "reason" ] == f"{type( error ).__name__}: {error}"
    assert state_of( world )[ "last_outcome" ] == "failed" and "last_run_date" not in state_of( world )


def test_a_named_candidate_error_is_exit_two_with_its_code_in_the_record( world ):
    def named( ids ): raise CandidateError( STORAGE_KEY_MISSING, "no key" )

    code, summary = go( world, writer=named )
    assert code == 2 and summary[ "reason" ] == "STORAGE_KEY_MISSING: no key"
    assert state_of( world )[ "last_error" ] == "STORAGE_KEY_MISSING: no key"


def test_a_held_build_lock_is_exit_four_and_leaves_the_state_file_alone( world ):
    go( world )
    before = pathlib.Path( world[ "state" ] ).read_text()
    world[ "header" ][ "manifest" ] = { "m.py": [ 5, 5 ] }
    with fr.refresh_lock( world[ "data" ] / fr.LOCK_FILE ):
        code, summary = go( world, force=True )
    assert ( code, summary ) == ( 4, { "ran": False, "reason": "BUILD_LOCK_HELD" } )
    assert pathlib.Path( world[ "state" ] ).read_text() == before


# ── the manual driver shares the lock ───────────────────────────────────────


def test_a_manual_build_refuses_while_the_lock_is_held_and_writes_nothing( world ):
    with fr.refresh_lock( world[ "data" ] / fr.LOCK_FILE ):
        with pytest.raises( CandidateError ) as e:
            cb.run( world[ "root" ], answering_writer( [] ), tvb.FakeClient(), config=ConfigFor(), environ={} )
    assert e.value.code == "BUILD_LOCK_HELD"
    assert not ( world[ "data" ] / "vec" ).exists() and not ( world[ "data" ] / "pl" ).exists()


# ── cron lines and the command line ─────────────────────────────────────────


def test_the_cron_lines_are_tagged_inside_the_window_and_the_reboot_line_starts_after_the_librarians():
    daily, reboot = vr.cron_lines( "/main", "/py", "/log", "/h/.lupin/x.env" )
    assert daily.startswith( "47 10 * * * cd /main && LUPIN_ROOT=/main REUSE_VECTOR_REFRESH_PYTHON=/py REUSE_VECTOR_REFRESH_ENV=/h/.lupin/x.env /main/src/scripts/reuse-vector-refresh.sh >> /log 2>&1" )
    assert reboot.startswith( "@reboot sleep 240 && cd /main" )
    assert daily.endswith( vr.CRON_TAG ) and reboot.endswith( vr.CRON_TAG ) and vr.CRON_TAG != lt.CRON_TAG
    assert lt.CRON_SCHEDULE.split()[ 1 ] == "10" and vr.CRON_SCHEDULE.split()[ 1 ] == "10"


def test_carried_env_keeps_only_the_set_nonempty_host_settings():
    assert vr.carried_env( { "DEEPILY_DATA_DIR": "/d", "PLANNING_IS_PROMPTING_ROOT": "/p", "HOME": "/h" } ) == { "DEEPILY_DATA_DIR": "/d", "PLANNING_IS_PROMPTING_ROOT": "/p" }
    assert vr.carried_env( { "DEEPILY_DATA_DIR": "", "HOME": "/h" } ) == {}


def test_the_cron_lines_carry_the_data_dir_and_the_lock_root_so_a_cron_run_sees_what_the_install_saw():
    carried = { "DEEPILY_DATA_DIR": "/mnt/d", "PLANNING_IS_PROMPTING_ROOT": "/mnt/p" }
    for line in vr.cron_lines( "/main", "/py", "/log", "/e", carried ):
        assert "LUPIN_ROOT=/main DEEPILY_DATA_DIR=/mnt/d PLANNING_IS_PROMPTING_ROOT=/mnt/p REUSE_VECTOR_REFRESH_PYTHON=/py" in line
    assert "DEEPILY_DATA_DIR" not in vr.cron_lines( "/main", "/py", "/log", "/e" )[ 0 ]


def test_print_install_carries_the_callers_data_dir_into_both_lines( world ):
    rc, out, _ = run_main( world, [ "--print-install" ], environ={ "DEEPILY_DATA_DIR": "/mnt/d", "PLANNING_IS_PROMPTING_ROOT": "/mnt/p" } )
    assert rc == 0 and out.count( "DEEPILY_DATA_DIR=/mnt/d PLANNING_IS_PROMPTING_ROOT=/mnt/p" ) == 2


def test_the_env_file_is_under_the_home_folder_and_falls_back_to_the_users_home( monkeypatch ):
    assert vr.env_file_path( { "HOME": "/h" } ) == "/h/.lupin/reuse-vector-refresh.env"
    monkeypatch.setattr( vr.os.path, "expanduser", lambda p: "/fallback" )
    assert vr.env_file_path( {} ) == "/fallback/.lupin/reuse-vector-refresh.env"


def test_the_install_writes_the_env_file_path_of_the_host_it_runs_on_into_both_lines( world, cron ):
    env = { **cron[ "env" ], "HOME": "/home/someone" }
    run_main( world, [ "--install", "--python", "/py" ], environ=env, crontab_cmd=cron[ "cmd" ] )
    mine = [ l for l in cron[ "file" ].read_text().splitlines() if vr.CRON_TAG in l ]
    assert len( mine ) == 2 and all( "REUSE_VECTOR_REFRESH_ENV=/home/someone/.lupin/reuse-vector-refresh.env " in l for l in mine )


def test_refresh_dir_sits_under_the_data_dir( world ):
    assert vr.refresh_dir( "/x" ) == world[ "data" ] / "refresh"


def run_main( world, argv, **kw ):
    import io
    out, err = io.StringIO(), io.StringIO()
    kw.setdefault( "environ", {} )
    kw.setdefault( "now", NOON )
    rc = vr.main( [ "--root", str( world[ "root" ] ), *argv ], out=out, err=err, **kw )
    return rc, out.getvalue(), err.getvalue()


def test_print_install_prints_both_lines_and_changes_nothing( world ):
    rc, out, _ = run_main( world, [ "--print-install", "--python", "/py" ] )
    assert rc == 0 and out.count( vr.CRON_TAG ) == 2 and "REUSE_VECTOR_REFRESH_PYTHON=/py" in out
    assert not world[ "data" ].exists()


def test_install_status_and_uninstall_keep_other_lines_and_this_jobs_tag_apart_from_the_librarians( world, cron ):
    cron[ "file" ].write_text( "0 * * * * other\n17 10 * * * lib " + lt.CRON_TAG + "\n" )
    env = cron[ "env" ]
    rc, out, _ = run_main( world, [ "--install", "--python", "/py" ], environ=env, crontab_cmd=cron[ "cmd" ] )
    assert ( rc, out.strip() ) == ( 0, "installed: 2 lines" )
    text = cron[ "file" ].read_text()
    assert "0 * * * * other" in text and text.count( lt.CRON_TAG ) == 1 and text.count( vr.CRON_TAG ) == 2
    assert "lock-enter " + vr.LOCK_OWNER in cron[ "log" ].read_text()
    assert run_main( world, [ "--status" ], environ=env, crontab_cmd=cron[ "cmd" ] )[ 1 ].strip() == "installed: 2 lines"
    rc, out, _ = run_main( world, [ "--uninstall" ], environ=env, crontab_cmd=cron[ "cmd" ] )
    assert ( rc, out.strip() ) == ( 0, "uninstalled" )
    after = cron[ "file" ].read_text()
    assert vr.CRON_TAG not in after and lt.CRON_TAG in after


def test_status_reads_not_installed_when_there_is_no_crontab( world, cron ):
    assert run_main( world, [ "--status" ], environ=cron[ "env" ], crontab_cmd=cron[ "cmd" ] )[ 1 ].strip() == "not installed"


def test_an_install_without_the_shared_lock_is_refused_and_returns_one( world, cron ):
    rc, _, err = run_main( world, [ "--install" ], environ={}, crontab_cmd=cron[ "cmd" ] )
    assert rc == 1 and err.startswith( "reuse-vector-refresh:" )
    assert not cron[ "file" ].exists()


def test_a_missing_storage_key_in_the_data_dir_is_exit_two_with_the_code( world, monkeypatch ):
    def refuse( root ): raise CandidateError( STORAGE_KEY_MISSING, "no data subdir" )

    monkeypatch.setattr( vr, "data_dir", refuse )
    rc, out, _ = run_main( world, [] )
    assert rc == 2 and json.loads( out ) == { "error": "STORAGE_KEY_MISSING", "detail": "no data subdir" }


def test_a_switched_off_job_logs_one_line_and_builds_nothing( world, monkeypatch ):
    monkeypatch.setattr( vr.sx_build, "ensure", lambda root: pytest.fail( "the index must not be built" ) )
    rc, out, _ = run_main( world, [], enabled_fn=lambda: False )
    assert rc == 3 and json.loads( out ) == { "ran": False, "reason": "switched off" }
    assert "is switched off" in ( world[ "data" ] / "refresh" / vr.LOG_NAME ).read_text()


def test_an_unreadable_switch_stays_off_and_says_why( world, monkeypatch ):
    def failing( key ): raise OSError( "ini gone" )

    real = lt.read_enabled
    monkeypatch.setattr( lt, "read_enabled", lambda errors=None, key=None: real( reader=failing, errors=errors, key=key ) )
    rc, _, _ = run_main( world, [] )
    assert rc == 3 and "stays off: ini gone" in ( world[ "data" ] / "refresh" / vr.LOG_NAME ).read_text()


def test_the_switch_is_read_from_this_jobs_own_key( world, monkeypatch ):
    seen = []
    monkeypatch.setattr( lt, "read_value", lambda key, reader=None, errors=None: seen.append( key ) or "true" )
    rc, _, _ = run_main( world, [], writer_factory=lambda a: answering_writer( [] ), client=tvb.FakeClient() )
    assert rc == 0 and seen == [ vr.ENABLED_KEY ] and vr.ENABLED_KEY != lt.ENABLED_KEY


def test_a_switched_on_run_builds_and_prints_the_summary( world, monkeypatch ):
    monkeypatch.setattr( sp_config( ), "build_config", lambda: ConfigFor() )
    rc, out, _ = run_main( world, [], enabled_fn=lambda: True, writer_factory=lambda a: answering_writer( [] ), client=tvb.FakeClient() )
    assert rc == 0 and json.loads( out )[ "outcome" ] == "built"


def sp_config():
    from cosa.repo.symindex.candidates import storage_paths
    return storage_paths


def test_a_worktree_root_and_a_missing_credential_are_named_errors_with_exit_two( world ):
    def worktree( a ): raise ValueError( "--root /wt is a worktree; Pass --root /main" )

    rc, out, _ = run_main( world, [], enabled_fn=lambda: True, writer_factory=worktree )
    assert rc == 2 and json.loads( out )[ "error" ] == "WORKTREE_ROOT" and "Pass --root /main" in json.loads( out )[ "detail" ]

    def no_credentials( a ): raise CandidateError( DEPENDENCY_MISSING, "the job credential variable X is not set" )

    rc, out, _ = run_main( world, [], enabled_fn=lambda: True, writer_factory=no_credentials )
    assert rc == 2 and json.loads( out ) == { "error": "DEPENDENCY_MISSING", "detail": "the job credential variable X is not set" }


def test_the_default_writer_and_client_come_from_the_driver( world, monkeypatch ):
    seen = {}
    monkeypatch.setattr( cb, "make_job_writer", lambda root, url, environ: seen.update( root=root, url=url ) or "WRITER" )
    monkeypatch.setattr( vr, "run_refresh", lambda root, writer, client, state, now, **kw: seen.update( writer=writer, client=client ) or ( 0, { "ran": False } ) )
    rc, _, _ = run_main( world, [ "--base-url", "http://t:8000" ], enabled_fn=lambda: True )
    assert rc == 0 and seen[ "writer" ] == "WRITER" and seen[ "url" ] == "http://t:8000" and seen[ "root" ] == str( world[ "root" ] )
    assert isinstance( seen[ "client" ], cb.vb.EndpointClient )


def test_the_root_defaults_to_the_environment_and_then_the_working_folder( world, monkeypatch ):
    import io
    out = io.StringIO()
    assert vr.main( [ "--print-install" ], environ={ "LUPIN_ROOT": "/from-env" }, out=out ) == 0
    assert "cd /from-env &&" in out.getvalue()
    monkeypatch.chdir( world[ "data" ].parent )
    out = io.StringIO()
    assert vr.main( [ "--print-install" ], environ={}, out=out ) == 0
    assert f"cd {os.getcwd()} &&" in out.getvalue()


def test_the_wrapper_script_the_cron_lines_name_exists_and_is_executable():
    script = pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src" / "scripts" / vr.SCRIPT_NAME
    assert script.is_file() and os.access( script, os.X_OK )
    text = script.read_text()
    assert "cosa.repo.symindex.vector_refresh" in text and "REUSE_VECTOR_REFRESH_ENV" in text


# ── a pin no line can be written for is settled for its index, not rebuilt every day ──


def omitting( omit ):
    """A writer that answers every id except those in omit."""
    def w( ids ): return { i: f"Return {i}." for i in ids if i not in omit }
    return w


def too_long( ids ): return { i: " ".join( [ "word" ] * 40 ) for i in ids }


def test_a_pin_the_writer_never_answers_is_settled_so_the_next_day_is_fresh_and_does_no_work( world ):
    code, first = go( world, writer=omitting( { "m.b" } ) )
    assert code == 0 and first[ "outcome" ] == "built"
    assert fr.read_build_info( world[ "data" ] / "vec" )[ "unwritten_pins" ] == [ "pb" ]
    calls, client = [], tvb.FakeClient()
    code, second = go( world, writer=answering_writer( calls ), client=client, now=TOMORROW )
    assert ( code, second[ "outcome" ], second[ "reason" ] ) == ( 0, "fresh", "fresh" ) and calls == [] and client.calls == []


def test_a_pin_the_judge_rejects_is_settled_the_same_way( world ):
    go( world, writer=too_long )
    assert sorted( fr.read_build_info( world[ "data" ] / "vec" )[ "unwritten_pins" ] ) == [ "pa", "pb" ]
    calls = []
    assert go( world, writer=answering_writer( calls ), now=TOMORROW )[ 1 ][ "outcome" ] == "fresh" and calls == []


def test_a_settled_pin_is_asked_for_again_when_the_index_changes( world ):
    go( world, writer=omitting( { "m.b" } ) )
    world[ "header" ][ "manifest" ] = { "m.py": [ 7, 7 ] }
    calls = []
    code, summary = go( world, writer=answering_writer( calls ), now=TOMORROW )
    assert summary[ "outcome" ] == "built" and calls == [ [ "m.b" ] ]
    assert fr.read_build_info( world[ "data" ] / "vec" )[ "unwritten_pins" ] == []


def test_a_new_pin_after_a_settled_one_still_forces_a_rebuild( world ):
    go( world, writer=omitting( { "m.b" } ) )
    world[ "symbols" ].append( symbol( "c", "pc" ) )
    code, summary = go( world, writer=answering_writer( [] ), now=TOMORROW )
    assert summary[ "outcome" ] == "built" and summary[ "reason" ] == "1 pins have no purpose line"


def test_a_set_whose_build_info_lacks_unwritten_pins_counts_every_missing_pin( world ):
    go( world, writer=omitting( { "m.b" } ) )
    path = world[ "data" ] / "vec" / fr.BUILD_INFO_FILE
    info = json.loads( path.read_text() )
    del info[ "unwritten_pins" ]
    path.write_text( json.dumps( info ) )
    assert go( world, writer=answering_writer( [] ), now=TOMORROW )[ 1 ][ "reason" ] == "1 pins have no purpose line"


def test_missing_purpose_lines_skips_settled_pins_and_counts_the_rest( tmp_path ):
    store = tmp_path / "purpose.jsonl"
    store.write_text( json.dumps( { "pin": "pa", "purpose": "Return a.", "prompt_hash": "h", "writer_version": "w" } ) + "\n" )
    entries = [ symbol( "a", "pa" ), symbol( "b", "pb" ), symbol( "c", "pc" ) ]
    screen  = pl.Screen( lambda es: ( es, [] ), lambda r: [] )
    assert vr.missing_purpose_lines( entries, store, screen ) == 2
    assert vr.missing_purpose_lines( entries, store, screen, [ "pb" ] ) == 1
    assert vr.missing_purpose_lines( entries, store, screen, [ "pb", "pc", "zz" ] ) == 0


def test_a_rebuild_reports_how_many_vector_rows_were_reused_and_embedded( world ):
    go( world )
    world[ "symbols" ][ 0 ][ "doc" ] = "Does b differently."
    world[ "header" ][ "manifest" ] = { "m.py": [ 8, 8 ] }
    code, summary = go( world, now=TOMORROW )
    assert summary[ "outcome" ] == "built"
    assert summary[ "vectors" ][ "code" ] == { "reused": 2, "embedded": 0 } and summary[ "vectors" ][ "prose" ] == { "reused": 1, "embedded": 1 }


# ── cron's environment is bare: the wrapper must hand the job a ConfigurationManager default ──

import subprocess
import sys

DEFAULT_CONFIG_ARGS = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"


def run_wrapper_bare( tmp_path, extra_env=None ):
    """Run the wrapper in a bare environment; a fake python dumps what it received."""
    fake = tmp_path / "fake-python"
    dump = tmp_path / "env.json"
    fake.write_text( f"#!{sys.executable}\nimport json, os, sys\n"
                     f"json.dump( {{ 'env': dict( os.environ ), 'argv': sys.argv[ 1: ] }}, open( {str( dump )!r}, 'w' ) )\n" )
    fake.chmod( 0o755 )
    script = pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src" / "scripts" / vr.SCRIPT_NAME
    env    = { "PATH": "/usr/bin:/bin", "REUSE_VECTOR_REFRESH_PYTHON": str( fake ), **( extra_env or {} ) }
    done   = subprocess.run( [ "/bin/bash", str( script ) ], env=env, capture_output=True, text=True, timeout=30 )
    assert done.returncode == 0, done.stderr
    return json.loads( dump.read_text() )


def test_the_wrapper_defaults_the_configuration_manager_args_under_a_bare_environment( tmp_path ):
    seen = run_wrapper_bare( tmp_path )
    assert seen[ "env" ][ "LUPIN_CONFIG_MGR_CLI_ARGS" ] == DEFAULT_CONFIG_ARGS


def test_the_wrapper_keeps_a_callers_own_configuration_manager_args( tmp_path ):
    seen = run_wrapper_bare( tmp_path, { "LUPIN_CONFIG_MGR_CLI_ARGS": "config_path=/mine.ini" } )
    assert seen[ "env" ][ "LUPIN_CONFIG_MGR_CLI_ARGS" ] == "config_path=/mine.ini"
