"""
Unit tests for the wiki-librarian tick: due rule, run, cron lines, locked install.

Venue: :7999-eligible. The crontab is a fake script writing to a temporary file, the lock module is
a temporary file, and the store is a stand-in. The real crontab is never touched.
"""
import datetime
import io
import json
import os
import pathlib
import sys
import types

import pytest

from cosa.repo.symindex import librarian_queue as lq
from cosa.repo.symindex import librarian_tick as lt

NOON    = datetime.datetime( 2026, 10, 14, 12, 0, 0 )
EARLY   = datetime.datetime( 2026, 10, 14, 3, 0, 0 )
TOMORROW = datetime.datetime( 2026, 10, 15, 10, 30, 0 )

FAKE_CRONTAB = '''
import os, sys
store = os.environ["FAKE_CRON_FILE"]
log   = os.environ.get( "FAKE_CRON_LOG" )
mode  = sys.argv[ 1 ]
if log:
    with open( log, "a" ) as h: h.write( mode + "\\n" )
if os.environ.get( "FAKE_CRON_FAIL" ) == mode:
    sys.stderr.write( "forced failure" ); sys.exit( 2 )
if mode == "-l":
    if not os.path.exists( store ):
        sys.stderr.write( "no crontab for user" ); sys.exit( 1 )
    sys.stdout.write( open( store ).read() ); sys.exit( 0 )
open( store, "w" ).write( sys.stdin.read() )
'''

FAKE_LOCK = '''
import contextlib, os

@contextlib.contextmanager
def crontab_lock( timeout=None, path=None, owner="" ):
    log = os.environ.get( "FAKE_CRON_LOG" )
    if log:
        with open( log, "a" ) as h: h.write( "lock-enter " + owner + "\\n" )
    try:
        yield None
    finally:
        if log:
            with open( log, "a" ) as h: h.write( "lock-exit\\n" )
'''


@pytest.fixture
def cron( tmp_path, monkeypatch ):
    """A fake crontab command, a fake lock module and the environment that points at them."""
    script = tmp_path / "fake_crontab.py"
    script.write_text( FAKE_CRONTAB )
    scripts = tmp_path / "pip" / "workflow" / "scripts"
    scripts.mkdir( parents=True )
    ( scripts / "crontab_lock.py" ).write_text( FAKE_LOCK )
    monkeypatch.setenv( "FAKE_CRON_FILE", str( tmp_path / "crontab.txt" ) )
    monkeypatch.setenv( "FAKE_CRON_LOG", str( tmp_path / "calls.log" ) )
    monkeypatch.delenv( "FAKE_CRON_FAIL", raising=False )
    return { "cmd": [ sys.executable, str( script ) ], "env": { "PLANNING_IS_PROMPTING_ROOT": str( tmp_path / "pip" ) },
             "file": tmp_path / "crontab.txt", "log": tmp_path / "calls.log", "backups": tmp_path / "backups" }


def test_data_dir_sits_under_the_fleet_data_root( tmp_path, monkeypatch ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    assert lt.data_dir( str( tmp_path / "repo" ) ).endswith( os.path.join( "reuse-review", "librarian" ) )
    assert str( tmp_path / "data" ) in lt.data_dir( str( tmp_path / "repo" ) )


def test_due_is_false_before_ten_true_after_and_false_once_a_run_finished_today():
    assert lt.due( EARLY, {} ) is False
    assert lt.due( NOON, {} ) is True
    assert lt.due( NOON, { "last_run_date": "2026-10-14" } ) is False
    assert lt.due( TOMORROW, { "last_run_date": "2026-10-14" } ) is True


def test_state_reads_empty_for_absent_bad_and_non_dict_files_and_round_trips( tmp_path ):
    path = str( tmp_path / "s" / "state.json" )
    assert lt.read_state( path ) == {}
    lt.write_state( path, { "last_run_date": "2026-10-14" } )
    assert lt.read_state( path ) == { "last_run_date": "2026-10-14" }
    pathlib.Path( path ).write_text( "{not json" )
    assert lt.read_state( path ) == {}
    pathlib.Path( path ).write_text( "[1]" )
    assert lt.read_state( path ) == {}


def test_the_logger_appends_stamped_lines_and_drops_a_line_it_cannot_write( tmp_path ):
    path = tmp_path / "logs" / "librarian.log"
    lt.make_logger( str( path ) )( "hello" )
    assert path.read_text().rstrip().endswith( " hello" )
    blocker = tmp_path / "blocker"
    blocker.write_text( "a file where a folder should be" )
    lt.make_logger( str( blocker / "librarian.log" ) )( "dropped" )


class Client:
    """Stand-in for the task_store_client module."""

    def __init__( self ): self.calls = []
    def query_by_correlation_key( self, s, k, key ): self.calls.append( ( "query", key ) ); return True, 200, { "tasks": [] }
    def create_task( self, s, k, payload ): self.calls.append( ( "create", payload ) ); return True, 201, {}
    def amend_task( self, s, k, item_id, payload ): self.calls.append( ( "amend", item_id, payload ) ); return True, 200, {}
    def transition_task( self, s, k, item_id, payload ): self.calls.append( ( "transition", item_id, payload ) ); return True, 200, {}


def test_the_live_store_stamps_the_actor_and_maps_each_call_to_the_client():
    client = Client()
    store  = lt.LiveStore( { "api_base_url": "x" }, "key", client )
    store.query( "epic:wiki-librarian" )
    store.create( { "title": "t" } )
    store.amend( "id-1", "note" )
    store.close( "id-1", "why" )
    assert client.calls[ 0 ] == ( "query", "epic:wiki-librarian" )
    assert client.calls[ 1 ][ 1 ] == { "title": "t", "created_by": lt.ACTOR, "authority": "standing" }
    assert client.calls[ 2 ] == ( "amend", "id-1", { "note": "note", "actor": lt.ACTOR, "authority": "standing" } )
    assert client.calls[ 3 ] == ( "transition", "id-1", { "to_status": "done", "actor": lt.ACTOR, "authority": "standing", "reason": "why" } )


def test_notify_owner_is_true_only_on_201_and_never_raises():
    seen = []
    def post( base, key, path, payload ): seen.append( ( base, key, path, payload ) ); return 201, ""
    assert lt.notify_owner( "cheech", "hi", { "LUPIN_API_BASE": "http://h:1/" }, post=post, api_key=lambda: "k" ) is True
    assert seen[ 0 ][ 0 ] == "http://h:1" and seen[ 0 ][ 2 ] == "/api/dm/send" and seen[ 0 ][ 3 ][ "recipient_persona" ] == "cheech"
    assert lt.notify_owner( "cheech", "hi", {}, post=lambda *a: ( 500, "" ), api_key=lambda: "k" ) is False
    def broken(): raise OSError( "no key" )
    assert lt.notify_owner( "cheech", "hi", {}, post=post, api_key=broken ) is False


def test_notify_owner_falls_back_to_the_live_post_and_key( monkeypatch ):
    from cosa.utils import hook_link_tick as hlt
    monkeypatch.setattr( hlt, "post_json", lambda base, key, path, payload: ( 201, key ) )
    monkeypatch.setattr( hlt, "_api_key", lambda: "live-key" )
    assert lt.notify_owner( "cheech", "hi", {} ) is True


class FakeLibrarian:
    def __init__( self, counts=None, error=None, query=( True, 200, { "tasks": [ { "title": "t", "body": "b" } ] } ) ):
        self.counts = counts or { "created": 1, "amended": 0, "unchanged": 0, "closed": 0, "pending": 0 }
        self.error  = error
        self.store  = type( "S", (), { "query": lambda s, key: query } )()
        self.seen   = None

    def sync( self, findings ):
        self.seen = findings
        if self.error: raise self.error
        return self.counts


@pytest.fixture
def pipeline( monkeypatch ):
    monkeypatch.setattr( lt.build_mod, "ensure", lambda root, out: "gen-dir" )
    monkeypatch.setattr( lt, "queue", lambda wiki, gen: [ { "kind": "stale" }, { "kind": "orphan" } ] )


def test_a_run_that_is_not_due_does_nothing( tmp_path, pipeline ):
    state = str( tmp_path / "state.json" )
    code, summary = lt.run_tick( "r", "w", None, FakeLibrarian(), lambda rows, path: 0, "m", state, EARLY )
    assert code == 0 and summary == { "ran": False, "reason": "not due" }
    assert not os.path.exists( state )


def test_a_due_run_syncs_exports_and_records_the_day( tmp_path, pipeline ):
    state, lib, exported = str( tmp_path / "state.json" ), FakeLibrarian(), []
    code, summary = lt.run_tick( "r", "w", None, lib, lambda rows, path: exported.append( ( rows, path ) ) or 3, "m.jsonl", state, NOON )
    assert code == 0 and summary[ "ran" ] is True and summary[ "findings" ] == 2 and summary[ "misses" ] == 3
    assert lib.seen == [ { "kind": "stale" }, { "kind": "orphan" } ]
    assert exported == [ ( [ { "title": "t", "body": "b" } ], "m.jsonl" ) ]
    assert lt.read_state( state )[ "last_run_date" ] == "2026-10-14"
    assert lt.due( NOON, lt.read_state( state ) ) is False


def test_pending_rows_make_the_exit_code_two( tmp_path, pipeline ):
    lib = FakeLibrarian( counts={ "created": 0, "amended": 0, "unchanged": 0, "closed": 0, "pending": 2 } )
    assert lt.run_tick( "r", "w", None, lib, lambda r, p: 0, "m", str( tmp_path / "s.json" ), NOON )[ 0 ] == 2


def test_force_runs_a_tick_that_is_not_due( tmp_path, pipeline ):
    code, summary = lt.run_tick( "r", "w", None, FakeLibrarian(), lambda r, p: 0, "m", str( tmp_path / "s.json" ), EARLY, force=True )
    assert code == 0 and summary[ "ran" ] is True


def test_an_unreadable_store_ends_the_run_with_one_and_records_nothing( tmp_path, pipeline ):
    state, lines = str( tmp_path / "state.json" ), []
    code, summary = lt.run_tick( "r", "w", None, FakeLibrarian( error=RuntimeError( "down" ) ), lambda r, p: 0, "m", state, NOON, log=lines.append )
    assert code == 1 and summary[ "ran" ] is False and "down" in summary[ "reason" ]
    assert not os.path.exists( state ) and any( "could not finish" in line for line in lines )


def test_a_failed_export_query_ends_the_run_with_one( tmp_path, pipeline ):
    lib = FakeLibrarian( query=( False, 500, {} ) )
    code, summary = lt.run_tick( "r", "w", None, lib, lambda r, p: 0, "m", str( tmp_path / "s.json" ), NOON, log=lambda line: None )
    assert code == 1 and "export query failed" in summary[ "reason" ]


def test_cron_lines_carry_the_tag_the_schedule_and_the_reboot_catch_up():
    daily, reboot = lt.cron_lines( "/main", "/py", "/log" )
    assert daily.startswith( "17 10 * * * cd /main && LUPIN_ROOT=/main PYTHONPATH=/main/src /py -m cosa.repo.symindex.librarian_tick >> /log 2>&1" )
    assert reboot.startswith( "@reboot sleep 120 && cd /main" )
    assert daily.endswith( lt.CRON_TAG ) and reboot.endswith( lt.CRON_TAG )


def test_merge_lines_keeps_other_lines_replaces_ours_and_is_idempotent_and_removes_on_empty():
    lines = lt.cron_lines( "/main", "/py", "/log" )
    other = "0 3 * * * /usr/bin/other-job\n# a comment line\n"
    once  = lt.merge_lines( other, lines )
    assert once.splitlines()[ :2 ] == [ "0 3 * * * /usr/bin/other-job", "# a comment line" ]
    assert lt.merge_lines( once, lines ) == once
    assert lt.merge_lines( once, [] ) == other


def test_load_crontab_lock_refuses_when_the_variable_or_the_file_is_missing( tmp_path ):
    with pytest.raises( lt.InstallRefused, match="not set" ): lt.load_crontab_lock( {} )
    with pytest.raises( lt.InstallRefused, match="does not exist" ): lt.load_crontab_lock( { "PLANNING_IS_PROMPTING_ROOT": str( tmp_path ) } )


def test_the_real_shared_lock_module_loads_when_it_is_present():
    home = os.environ.get( "PLANNING_IS_PROMPTING_ROOT" )
    if not home or not os.path.isfile( os.path.join( home, "workflow", "scripts", "crontab_lock.py" ) ):
        pytest.skip( "planning-is-prompting is not on this host" )
    assert callable( lt.load_crontab_lock( { "PLANNING_IS_PROMPTING_ROOT": home } ) )


def test_install_writes_inside_the_lock_backs_up_first_and_keeps_other_lines( cron ):
    cron[ "file" ].write_text( "0 3 * * * /usr/bin/other-job\n" )
    new = lt.edit_crontab( lt.cron_lines( "/main", "/py", "/log" ), cron[ "env" ], cron[ "cmd" ], str( cron[ "backups" ] ), NOON )
    assert cron[ "file" ].read_text() == new
    assert new.startswith( "0 3 * * * /usr/bin/other-job\n" ) and new.count( lt.CRON_TAG ) == 2
    assert cron[ "log" ].read_text().split( "\n" )[ :5 ] == [ "lock-enter wiki-librarian-tick", "-l", "-", "lock-exit", "" ]
    backups = list( cron[ "backups" ].iterdir() )
    assert len( backups ) == 1 and backups[ 0 ].read_text() == "0 3 * * * /usr/bin/other-job\n"


def test_install_twice_is_idempotent_and_uninstall_removes_only_our_lines( cron ):
    cron[ "file" ].write_text( "0 3 * * * /usr/bin/other-job\n" )
    lines = lt.cron_lines( "/main", "/py", "/log" )
    first = lt.edit_crontab( lines, cron[ "env" ], cron[ "cmd" ], str( cron[ "backups" ] ), NOON )
    again = lt.edit_crontab( lines, cron[ "env" ], cron[ "cmd" ], str( cron[ "backups" ] ), NOON )
    assert first == again
    gone  = lt.edit_crontab( [], cron[ "env" ], cron[ "cmd" ], str( cron[ "backups" ] ), NOON )
    assert gone == "0 3 * * * /usr/bin/other-job\n"


def test_install_into_a_user_with_no_crontab_starts_from_empty( cron ):
    new = lt.edit_crontab( lt.cron_lines( "/main", "/py", "/log" ), cron[ "env" ], cron[ "cmd" ], str( cron[ "backups" ] ), NOON )
    assert new.count( "\n" ) == 2


def test_install_refuses_without_the_lock_and_writes_nothing( cron ):
    with pytest.raises( lt.InstallRefused ):
        lt.edit_crontab( lt.cron_lines( "/m", "/p", "/l" ), {}, cron[ "cmd" ], str( cron[ "backups" ] ), NOON )
    assert not cron[ "file" ].exists() and not cron[ "log" ].exists()


def test_a_failed_read_a_failed_backup_and_a_failed_write_each_raise_and_write_nothing( cron, monkeypatch ):
    lines = lt.cron_lines( "/m", "/p", "/l" )
    monkeypatch.setenv( "FAKE_CRON_FAIL", "-l" )
    with pytest.raises( RuntimeError, match="crontab -l failed" ):
        lt.edit_crontab( lines, cron[ "env" ], cron[ "cmd" ], str( cron[ "backups" ] ), NOON )
    monkeypatch.delenv( "FAKE_CRON_FAIL" )
    blocker = cron[ "backups" ].parent / "blocker"
    blocker.write_text( "file" )
    with pytest.raises( RuntimeError, match="no backup, so no write" ):
        lt.edit_crontab( lines, cron[ "env" ], cron[ "cmd" ], str( blocker / "sub" ), NOON )
    assert not cron[ "file" ].exists()
    monkeypatch.setenv( "FAKE_CRON_FAIL", "-" )
    with pytest.raises( RuntimeError, match="crontab write failed" ):
        lt.edit_crontab( lines, cron[ "env" ], cron[ "cmd" ], str( cron[ "backups" ] ), NOON )


def test_status_text_names_none_one_and_two_lines():
    two = "\n".join( lt.cron_lines( "/m", "/p", "/l" ) )
    assert lt.status_text( "" ) == "not installed"
    assert lt.status_text( two.splitlines()[ 0 ] ) == "partly installed: 1 lines"
    assert lt.status_text( two ) == "installed: 2 lines"


def run_main( args, cron, tmp_path, monkeypatch, **seams ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    out, err = io.StringIO(), io.StringIO()
    code = lt.main( [ *args, "--root", str( tmp_path / "repo" ), "--python", "/py" ], environ=cron[ "env" ], now=NOON, out=out, err=err,
                    crontab_cmd=cron[ "cmd" ], **seams )
    return code, out.getvalue(), err.getvalue()


def test_main_print_install_prints_the_lines_and_touches_no_crontab( cron, tmp_path, monkeypatch ):
    code, out, _ = run_main( [ "--print-install" ], cron, tmp_path, monkeypatch )
    assert code == 0 and out.count( lt.CRON_TAG ) == 2
    assert not cron[ "file" ].exists() and not cron[ "log" ].exists()


def test_main_install_status_and_uninstall_walk_through_the_fake_crontab( cron, tmp_path, monkeypatch ):
    assert run_main( [ "--status" ], cron, tmp_path, monkeypatch )[ 1 ].strip() == "not installed"
    assert run_main( [ "--install" ], cron, tmp_path, monkeypatch )[ 1 ].strip() == "installed: 2 lines"
    assert run_main( [ "--status" ], cron, tmp_path, monkeypatch )[ 1 ].strip() == "installed: 2 lines"
    assert run_main( [ "--uninstall" ], cron, tmp_path, monkeypatch )[ 1 ].strip() == "uninstalled"
    assert run_main( [ "--status" ], cron, tmp_path, monkeypatch )[ 1 ].strip() == "not installed"


def test_main_install_without_the_lock_prints_one_line_and_returns_one( cron, tmp_path, monkeypatch ):
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( tmp_path / "data" ) )
    out, err = io.StringIO(), io.StringIO()
    code = lt.main( [ "--install", "--root", str( tmp_path ) ], environ={}, now=NOON, out=out, err=err, crontab_cmd=cron[ "cmd" ] )
    assert code == 1 and "shared crontab lock" in err.getvalue() and not cron[ "file" ].exists()


def test_main_default_run_uses_the_injected_librarian_and_exporter( cron, tmp_path, monkeypatch, pipeline ):
    lib  = FakeLibrarian()
    made = []
    code, out, _ = run_main( [], cron, tmp_path, monkeypatch, make_librarian=lambda env, pending, log: made.append( pending ) or lib,
                             export_fn=lambda rows, path: 0 )
    assert code == 0 and json.loads( out )[ "ran" ] is True
    assert made[ 0 ].endswith( lt.PENDING_NAME )


def test_live_builders_wire_the_client_the_store_and_the_exporter( monkeypatch, tmp_path ):
    from lupin_cli.claude_code.hooks.lib import task_store_client, task_store_settings
    monkeypatch.setattr( task_store_settings, "load_task_store_settings", lambda: { "api_base_url": "http://x", "timeout_seconds": 1.0 } )
    monkeypatch.setattr( task_store_client, "read_api_key", lambda: "k" )
    lib = lt._live_librarian( { "WIKI_LIBRARIAN_OWNER": "tiffany" }, str( tmp_path / "p.jsonl" ), lambda line: None )
    assert isinstance( lib, lq.Librarian ) and lib.owner == "tiffany" and isinstance( lib.store, lt.LiveStore )
    sent = []
    monkeypatch.setattr( lt, "notify_owner", lambda persona, text, environ: sent.append( ( persona, text ) ) or True )
    lib.notify( "held" )
    assert sent == [ ( "tiffany", "held" ) ]
    stub = types.ModuleType( "cosa.repo.symindex.miss_record" )
    stub.export_misses = lambda rows, path: 0
    monkeypatch.setitem( sys.modules, "cosa.repo.symindex.miss_record", stub )
    assert lt._live_export() is stub.export_misses


def test_the_shell_wrapper_prints_the_install_lines_and_changes_nothing( tmp_path ):
    import subprocess
    script = pathlib.Path( __file__ ).resolve().parents[ 2 ] / "scripts" / "wiki-librarian-tick.sh"
    env    = { **os.environ, "DEEPILY_DATA_DIR": str( tmp_path / "data" ), "LUPIN_ROOT": str( script.parents[ 2 ] ) }
    done   = subprocess.run( [ str( script ), "--print-install" ], capture_output=True, text=True, env=env )
    assert done.returncode == 0, done.stderr
    assert done.stdout.count( lt.CRON_TAG ) == 2 and "librarian_tick" in done.stdout
    assert not ( tmp_path / "data" ).exists()
