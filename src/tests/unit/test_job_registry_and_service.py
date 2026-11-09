"""The registry, its run-time overrides, the live inputs, the response builder and Run now."""
import datetime
import json
import os
import pathlib
import subprocess
import types
import zoneinfo

import pytest

import cosa.rest.job_registry as jr
import cosa.rest.job_service as svc
from lupin_mcp import job_summary as js

NY  = zoneinfo.ZoneInfo( "America/New_York" )
NOW = datetime.datetime( 2026, 11, 7, 12, 0, tzinfo=NY )
REAL_ROOT = pathlib.Path( __file__ ).resolve().parents[ 3 ]


def write_registry( root, jobs, defaults=None ):
    """Ensures: writes a job-registry/1 file under root and returns root."""
    base = { "grace_minutes": 30, "notify_interval_minutes": 30, "window_days": 7, "growth_min_items": 5, "growth_min_percent": 5, "lock_stale_seconds": 10800, "run_env": { "LUPIN_ROOT": "{root}" } }
    path = pathlib.Path( root ) / jr.REGISTRY_FILE
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( json.dumps( { "schema": "job-registry/1", "defaults": defaults or base, "jobs": jobs } ) )
    return root


def job( name="j", **over ):
    """Ensures: returns a registry job."""
    return { "job": name, "title": name.upper(), "owner": "cheech", "schedule": [ { "cron": "0 10 * * *" } ], "summary_path": f"{{root}}/s/{name}.json", **over }


class Deps:
    """Fake inputs: every answer is a field, every call is recorded."""

    def __init__( self, units=None, locks=(), store=None, cron=None, zone=None ):
        self.units, self.locks, self.store, self.cron, self.zone, self.calls = units or {}, set( locks ), store, cron, zone, []

    def boot_time( self ): return datetime.datetime( 2026, 11, 1, 8, 0, tzinfo=NY )

    def unit_state( self, unit, health_url=None ): return self.units.get( unit )

    def crontab_text( self ): return self.cron

    def host_zone( self ): return self.zone

    def lock_held( self, path ):
        self.calls.append( ( "lock", str( path ) ) )
        return str( path ) in self.locks

    def store_counts( self, key, now, days ):
        self.calls.append( ( "store", key, days ) )
        return self.store


def summary_file( root, name, outcome="clean", when=None, **kw ):
    """Ensures: writes a real summary for a job and returns its path."""
    when = when or NOW - datetime.timedelta( hours=1 )
    path = pathlib.Path( root ) / "s" / f"{name}.json"
    js.write_summary( path, name, { "started_at": when.isoformat(), "finished_at": when.isoformat(), "trigger": "cron", "outcome": outcome }, **kw )
    return path


def test_the_shipped_registry_loads_and_holds_the_23_jobs_of_the_design_with_seat_owners():
    reg = jr.load_registry( REAL_ROOT )
    assert len( reg[ "jobs" ] ) == 23 and reg[ "defaults" ][ "grace_minutes" ] == 30 and reg[ "defaults" ][ "notify_interval_minutes" ] == 30
    assert {  j[ "catalog" ] for j in reg[ "jobs" ] if "catalog" in j } >= { "L1", "L2", "L3", "L4", "L5", "P1", "P3", "P4", "L28", "L30" }
    dup = next( j for j in reg[ "jobs" ] if j[ "job" ] == "duplicate-check" )
    assert dup[ "fix_debt_key" ] == "prefix:epic:dupcheck-" and dup[ "schedule" ] == [ { "cron": "0 10 * * *" }, { "cron": "7 11 * * *" }, { "after_boot_seconds": 300 } ] and dup[ "cron_tag" ] == "duplicate-check-daily"
    vec = next( j for j in reg[ "jobs" ] if j[ "job" ] == "vector-refresh" )
    assert "symbol index" in vec[ "title" ]


def test_the_registry_refuses_a_role_label_owner_a_double_listing_a_missing_field_and_a_bad_schedule(tmp_path):
    for bad, why in ( ( [ job( owner="manager on duty" ) ], "seat name" ), ( [ job(), job() ], "twice" ), ( [ job( title="" ) ], "lacks title" ),
                      ( [ job( schedule=[ { "cron": "x", "every_seconds": 5 } ] ) ], "exactly one" ), ( [ job( schedule=[ {} ] ) ], "exactly one" ) ):
        write_registry( tmp_path, bad )
        with pytest.raises( ValueError, match=why ): jr.load_registry( tmp_path )
    ( tmp_path / jr.REGISTRY_FILE ).write_text( json.dumps( { "schema": "other" } ) )
    with pytest.raises( ValueError, match="schema" ): jr.load_registry( tmp_path )
    write_registry( tmp_path, [ job( owner="rick" ) ] )
    assert jr.load_registry( tmp_path )[ "jobs" ][ 0 ][ "owner" ] == "rick"


def test_overrides_are_read_each_time_win_over_the_registry_and_bad_edits_are_ignored(tmp_path):
    root = write_registry( tmp_path, [ job( "a", notify_interval_minutes=60 ), job( "b" ) ] )
    reg  = jr.load_registry( root )
    assert jr.load_overrides( root ) == {}
    path = pathlib.Path( root ) / jr.OVERRIDES_FILE
    path.parent.mkdir( parents=True )
    path.write_text( json.dumps( { "a": { "grace_minutes": 5, "notify_interval_minutes": 120, "owner": "x" }, "b": { "grace_minutes": -1, "notify_interval_minutes": "soon" }, "c": 5, "d": { "grace_minutes": True } } ) )
    assert jr.load_overrides( root ) == { "a": { "grace_minutes": 5, "notify_interval_minutes": 120 } }
    a, b = ( jr.effective( j, reg[ "defaults" ], jr.load_overrides( root ) ) for j in reg[ "jobs" ] )
    assert ( a[ "grace_minutes" ], a[ "notify_interval_minutes" ] ) == ( 5, 120 ) and ( b[ "grace_minutes" ], b[ "notify_interval_minutes" ] ) == ( 30, 30 )
    path.write_text( json.dumps( { "a": { "notify_interval_minutes": 15 } } ) )                    # edited without a restart
    assert jr.effective( reg[ "jobs" ][ 0 ], reg[ "defaults" ], jr.load_overrides( root ) )[ "notify_interval_minutes" ] == 15
    path.write_text( "[1]" ); assert jr.load_overrides( root ) == {}
    path.write_text( "{bad" ); assert jr.load_overrides( root ) == {}
    assert jr.effective( reg[ "jobs" ][ 1 ], reg[ "defaults" ], {} )[ "grace_minutes" ] == 30


def test_resolve_path_prefixes():
    assert jr.resolve_path( "{data}/x/y.json", "/r", "/d" ) == pathlib.Path( "/d/x/y.json" )
    assert jr.resolve_path( "{root}/x.json", "/r", "/d" ) == pathlib.Path( "/r/x.json" )
    assert jr.resolve_path( "x.json", "/r", "/d" ) == pathlib.Path( "/r/x.json" )


def test_boot_time_is_read_from_proc_stat_text():
    assert svc.boot_time_from( "cpu 1 2\nbtime 1700000000\nprocs 3\n" ) == datetime.datetime.fromtimestamp( 1700000000 ).astimezone()
    with pytest.raises( ValueError ): svc.boot_time_from( "cpu 1\n" )


def test_store_counts_from_rows_counts_only_what_each_name_says():
    row = lambda status, made, upd: types.SimpleNamespace( status=status, created_ts=NOW - datetime.timedelta( days=made ), updated_ts=NOW - datetime.timedelta( days=upd ) )
    rows = [ row( "queued", 1, 1 ), row( "done", 2, 1 ), row( "done", 20, 20 ), row( "queued", 30, 1 ), row( "done", 30, 3 ), row( "dropped", 9, 9 ) ]
    assert svc.store_counts_from_rows( rows, NOW, 7 ) == { "open_now": 2, "opened_in_window": 2, "closed_in_window": 2, "open_at_window_start": 2 }


def test_the_response_has_one_entry_per_job_worst_first_with_a_target_job_taking_the_worst_target(tmp_path):
    ok = job( "ok" ); gone = job( "gone" ); fails = job( "fails" )
    tar = job( "tar", targets=[ { "target": "t1" }, { "target": "t2", "summary_path": "{root}/s/t2.json" } ] )
    live = job( "live", schedule=[], liveness={ "kind": "systemd", "unit": "u.service" } )
    root = write_registry( tmp_path, [ ok, gone, fails, tar, live ] )
    summary_file( root, "ok" ); summary_file( root, "fails", "failed" )
    ( pathlib.Path( root ) / "s" / "t1" ).mkdir(); js.write_summary( pathlib.Path( root ) / "s" / "t1" / "tar.json", "tar", { "started_at": ( NOW - datetime.timedelta( hours=1 ) ).isoformat(), "trigger": "cron", "outcome": "clean" }, target="t1" )
    summary_file( root, "t2", "failed" )
    ( pathlib.Path( root ) / "s" / "gone.json" ).write_text( "{broken" )
    got = svc.build_response( root, tmp_path / "data", NOW, Deps( units={ "u.service": "active" } ) )
    assert got[ "schema" ] == "jobs-summary/1" and got[ "generated_at" ] == NOW.isoformat()
    states = { j[ "job" ]: j[ "state" ] for j in got[ "jobs" ] }
    assert states == { "gone": "unknown", "fails": "failing", "tar": "failing", "ok": "healthy", "live": "healthy" }
    assert [ j[ "job" ] for j in got[ "jobs" ] ] == [ "gone", "fails", "tar", "live", "ok" ]                 # worst first, then by title
    assert next( j for j in got[ "jobs" ] if j[ "job" ] == "gone" )[ "unknown_reason" ] == "unreadable"
    tar_entry = next( j for j in got[ "jobs" ] if j[ "job" ] == "tar" )
    assert [ t[ "target" ] for t in tar_entry[ "targets" ] ] == [ "t1", "t2" ] and tar_entry[ "target" ] is None and tar_entry[ "reasons" ][ 0 ][ "text" ].startswith( "t2: " )
    assert tar_entry[ "unknown_reason" ] is None


def test_a_target_job_with_an_unreported_target_says_so_and_a_changed_override_applies_to_the_next_response(tmp_path):
    root = write_registry( tmp_path, [ job( "tar", targets=[ { "target": "t1" } ] ) ] )
    got = svc.build_response( root, tmp_path, NOW, Deps() )[ "jobs" ][ 0 ]
    assert got[ "state" ] == "unknown" and got[ "unknown_reason" ] == "a target has not reported"
    assert got[ "notify_interval_seconds" ] == 1800
    ( pathlib.Path( root ) / jr.OVERRIDES_FILE ).parent.mkdir( parents=True, exist_ok=True )
    ( pathlib.Path( root ) / jr.OVERRIDES_FILE ).write_text( json.dumps( { "tar": { "notify_interval_minutes": 600 } } ) )
    assert svc.build_response( root, tmp_path, NOW, Deps() )[ "jobs" ][ 0 ][ "notify_interval_seconds" ] == 36000


def test_a_held_lock_makes_a_late_job_running_and_the_store_is_asked_only_for_a_job_with_a_mark_that_has_reported(tmp_path):
    late = job( "late", lock_path="{root}/late.lock", fix_debt=True, fix_debt_key="job:late" )
    root = write_registry( tmp_path, [ late ] )
    summary_file( root, "late", when=NOW - datetime.timedelta( hours=2, minutes=30 ) )      # due 10:00, last ran 09:30, lock held
    deps = Deps( locks=[ str( pathlib.Path( root ) / "late.lock" ) ], store={ "open_now": 3, "opened_in_window": 1, "closed_in_window": 0, "open_at_window_start": 0 } )
    got = svc.build_response( root, tmp_path, NOW, deps )[ "jobs" ][ 0 ]
    assert got[ "running" ] and got[ "state" ] != "silent" and ( "store", "job:late", 7 ) in deps.calls
    quiet = Deps()
    root2 = write_registry( tmp_path / "two", [ late ] )
    svc.build_response( root2, tmp_path, NOW, quiet )
    assert not any( c[ 0 ] == "store" for c in quiet.calls ) and not any( c[ 0 ] == "lock" for c in quiet.calls )          # no summary yet: neither asked


def test_an_unusable_registry_raises_instead_of_answering_with_nothing(tmp_path):
    with pytest.raises( OSError ): svc.build_response( tmp_path, tmp_path, NOW, Deps() )


def test_live_deps_unit_state_lock_probe_and_boot_time(tmp_path, monkeypatch):
    live = svc.LiveDeps( tmp_path, tmp_path )
    assert live.boot_time().tzinfo is not None
    out = lambda text: types.SimpleNamespace( stdout=text )
    def answer( text ): return lambda *a, **k: out( text )
    monkeypatch.setattr( svc.subprocess, "run", answer( "LoadState=loaded\nActiveState=active\n" ) ); assert live.unit_state( "u" ) == "active"
    monkeypatch.setattr( svc.subprocess, "run", answer( "LoadState=loaded\nActiveState=failed\n" ) ); assert live.unit_state( "u" ) == "inactive"
    monkeypatch.setattr( svc.subprocess, "run", answer( "LoadState=not-found\nActiveState=inactive\n" ) ); assert live.unit_state( "u" ) == "not-loaded"
    monkeypatch.setattr( svc.subprocess, "run", answer( "garbage\n" ) ); assert live.unit_state( "u" ) is None
    def boom( *a, **k ): raise FileNotFoundError( "systemctl" )
    monkeypatch.setattr( svc.subprocess, "run", boom ); assert live.unit_state( "u" ) is None
    import fcntl
    lock = tmp_path / "x.lock"
    assert live.lock_held( lock ) is False and lock.exists()                                       # free: the probe creates and releases it
    with open( lock, "a" ) as held:
        fcntl.flock( held, fcntl.LOCK_EX )
        assert live.lock_held( lock ) is True
    assert live.lock_held( lock ) is False
    assert live.lock_held( tmp_path / "no" / "such" / "x.lock" ) is False


def test_live_store_counts_wraps_the_repository_and_answers_none_when_the_store_is_down(tmp_path, monkeypatch):
    import contextlib
    import cosa.rest.db.database as database
    import cosa.rest.db.repositories.task_repository as repo_mod
    seen = {}
    class Repo:
        def __init__( self, session ): seen[ "session" ] = session
        def query_tasks( self, **kw ):
            seen[ "kw" ] = kw
            return [ types.SimpleNamespace( status="queued", created_ts=NOW, updated_ts=NOW ) ]
    @contextlib.contextmanager
    def fake_db():
        yield "S"
    monkeypatch.setattr( database, "get_db", fake_db ); monkeypatch.setattr( repo_mod, "TaskRepository", Repo )
    got = svc.LiveDeps( tmp_path, tmp_path ).store_counts( "prefix:x", NOW, 7 )
    assert got[ "open_now" ] == 1 and seen[ "kw" ] == { "project": "lupin", "correlation_key_prefix": "x", "include_terminal": True, "limit": 500 }
    @contextlib.contextmanager
    def down():
        raise RuntimeError( "db down" )
        yield
    monkeypatch.setattr( database, "get_db", down )
    assert svc.LiveDeps( tmp_path, tmp_path ).store_counts( "prefix:x", NOW, 7 ) is None
    monkeypatch.setattr( database, "get_db", fake_db )
    assert svc.LiveDeps( tmp_path, tmp_path ).store_counts( "job:x", NOW, 7 ) is None      # a key without the prefix: form is "not reported", never a zero


def test_the_registry_mark_for_duplicate_check_is_the_key_prefix_the_filer_writes():
    from lupin_mcp import duplicate_check_filing as filing
    dup = next( j for j in jr.load_registry( REAL_ROOT )[ "jobs" ] if j[ "job" ] == "duplicate-check" )
    assert dup[ "fix_debt_key" ] == svc.MARK_PREFIX + filing.KEY_PREFIX
    assert filing.RUN_KEY_PREFIX.startswith( filing.KEY_PREFIX ) and filing.correlation_key( "d", "t" ).startswith( filing.KEY_PREFIX )


def test_expand_fills_every_placeholder_inside_strings_lists_and_dicts():
    got = svc.expand( { "a": [ "{root}/x", "{python}", 5 ], "b": "{data}:{home}:{pip}:{deepily_data}" }, "/R", "/D", "/H", "/P", "/E" )
    assert got == { "a": [ "/R/x", "/R/.venv/bin/python", 5 ], "b": "/D:/H:/P:/E" }


def test_paths_of_reads_the_environment(monkeypatch):
    monkeypatch.setenv( "HOME", "/h" ); monkeypatch.setenv( "PLANNING_IS_PROMPTING_ROOT", "/pip" ); monkeypatch.setenv( "DEEPILY_DATA_DIR", "/dd" )
    assert svc.paths_of( "/r", pathlib.Path( "/x/y/z" ) ) == ( "/r", pathlib.Path( "/x/y/z" ), "/h", "/pip", "/dd" )
    monkeypatch.delenv( "HOME" ); monkeypatch.delenv( "PLANNING_IS_PROMPTING_ROOT" ); monkeypatch.delenv( "DEEPILY_DATA_DIR" )
    got = svc.paths_of( "/a/b/lupin", pathlib.Path( "/m/n/o/p" ) )
    assert got[ 2 ] == "/root" and got[ 3 ] == "/a/b/planning-is-prompting" and got[ 4 ] == "/m/n"


class Spawner:
    """Stands in for subprocess.Popen and records the call."""

    def __init__( self ): self.calls, self.waited = [], []

    def __call__( self, argv, **kw ):
        self.calls.append( ( argv, kw ) )
        return types.SimpleNamespace( pid=4242, wait=lambda: self.waited.append( True ) )


def test_run_now_starts_a_hand_run_with_the_trigger_in_its_environment_and_logs_its_output(tmp_path):
    runnable = job( "r", run={ "argv": [ "{python}", "-m", "x" ], "env": { "K": "{root}/k" } }, lock_path="{root}/r.lock" )
    root = write_registry( tmp_path, [ runnable ] )
    spawn = Spawner()
    status, body = svc.run_now( root, tmp_path, "r", None, Deps(), NOW, spawn )
    assert status == 200 and body == { "job": "r", "target": None, "status": "started", "trigger": "hand", "pid": 4242, "started_at": NOW.isoformat() }
    argv, kw = spawn.calls[ 0 ]
    assert argv == [ f"{root}/.venv/bin/python", "-m", "x" ] and kw[ "env" ][ "LUPIN_JOB_TRIGGER" ] == "hand" and kw[ "env" ][ "K" ] == f"{root}/k" and kw[ "env" ][ "LUPIN_ROOT" ] == str( root )
    assert kw[ "start_new_session" ] is True and kw[ "stdin" ] == subprocess.DEVNULL and ( pathlib.Path( root ) / svc.RUN_NOW_LOG ).exists()


def test_run_now_refuses_unknown_unrunnable_and_locked_jobs_and_starts_nothing(tmp_path):
    root = write_registry( tmp_path, [ job( "r", run={ "argv": [ "x" ] }, lock_path="{root}/r.lock" ), job( "n" ) ] )
    spawn = Spawner()
    assert svc.run_now( root, tmp_path, "zzz", None, Deps(), NOW, spawn ) == ( 404, { "status": "refused", "reason": "unknown_job" } )
    assert svc.run_now( root, tmp_path, "n", None, Deps(), NOW, spawn ) == ( 422, { "status": "refused", "reason": "not_runnable" } )
    assert svc.run_now( root, tmp_path, "r", None, Deps( locks=[ str( pathlib.Path( root ) / "r.lock" ) ] ), NOW, spawn ) == ( 409, { "status": "refused", "reason": "lock_held" } )
    assert spawn.calls == []
    root2 = write_registry( tmp_path / "b", [ job( "p", run={ "argv": [ "x" ] } ) ] )
    assert svc.run_now( root2, tmp_path, "p", "t1", Deps(), NOW, spawn )[ 0 ] == 200 and spawn.calls[ 0 ][ 0 ] == [ "x" ]


def test_a_record_with_the_right_schema_and_a_missing_field_reads_as_unreadable_not_a_500(tmp_path):
    root = write_registry( tmp_path, [ job( "bad" ) ] )
    path = pathlib.Path( root ) / "s" / "bad.json"
    path.parent.mkdir( parents=True )
    path.write_text( json.dumps( { "schema": "job-summary/1", "job": "bad", "last_attempt": { "started_at": NOW.isoformat(), "outcome": "failed" } } ) )
    got = svc.build_response( root, tmp_path, NOW, Deps() )[ "jobs" ][ 0 ]
    assert got[ "state" ] == "unknown" and got[ "unknown_reason" ] == "unreadable" and got[ "last_attempt" ] is None


CRON = """# comment
0 10 * * * /bin/run --trigger cron # duplicate-check-daily
7 11 * * * /bin/run --baseline # duplicate-check-daily
@reboot sleep 300 && /bin/run --trigger reboot # duplicate-check-daily
@reboot /bin/early # io-sweep
#0 5 * * * /bin/old # duplicate-check-daily
0 5 * * * /bin/other # something-else
30 7 * * * /bin/mention duplicate-check-daily
bad # duplicate-check-daily
"""


def test_crontab_schedule_reads_cron_and_reboot_lines_and_ignores_comments_and_mentions():
    assert jr.crontab_schedule( CRON, "duplicate-check-daily" ) == [ { "cron": "0 10 * * *" }, { "cron": "7 11 * * *" }, { "after_boot_seconds": 300 } ]
    assert jr.crontab_schedule( CRON, "io-sweep" ) == [ { "after_boot_seconds": 0 } ] and jr.crontab_schedule( CRON, "missing" ) == []


def test_a_tagged_job_takes_the_installed_schedule_and_falls_back_when_none_is_installed_or_the_crontab_is_unreadable():
    tagged = job( "t", cron_tag="duplicate-check-daily", schedule=[ { "cron": "0 10-22 * * *" } ] )
    got = jr.with_installed_schedule( tagged, CRON )
    assert got[ "schedule" ][ 0 ] == { "cron": "0 10 * * *" } and got[ "schedule_unverified" ] is False
    for text in ( "0 1 * * * x # other\n", None ):                                          # tag not installed, or crontab unreadable
        fallback = jr.with_installed_schedule( tagged, text )
        assert fallback[ "schedule" ] == tagged[ "schedule" ] and fallback[ "schedule_unverified" ] is True
    plain = job( "p" )
    assert jr.with_installed_schedule( plain, CRON ) is plain                                # no tag: always the registry entry


def test_the_response_uses_the_installed_lines_in_one_crontab_state_and_the_registry_in_the_other(tmp_path):
    tagged = job( "t", cron_tag="t-tag", schedule=[ { "cron": "0 10-22 * * *" } ] )
    root = write_registry( tmp_path, [ tagged ] )
    summary_file( root, "t", when=NOW - datetime.timedelta( minutes=20 ) )                 # ran 11:40
    old = svc.build_response( root, tmp_path, NOW, Deps( cron="7 11 * * * /x # t-tag\n" ) )[ "jobs" ][ 0 ]
    assert old[ "schedule" ][ "entries" ] == [ "cron 7 11 * * *" ] and old[ "state" ] == "healthy"
    none = svc.build_response( root, tmp_path, NOW, Deps( cron=None ) )[ "jobs" ][ 0 ]
    assert none[ "schedule" ][ "entries" ] == [ "cron 0 10-22 * * *" ] and none[ "state" ] == "healthy"
    assert none[ "schedule_unverified" ] is True and old[ "schedule_unverified" ] is False
    hourly_gap = svc.build_response( root, tmp_path, NOW + datetime.timedelta( hours=2, minutes=45 ), Deps( cron="0 10-22 * * * /x # t-tag\n" ) )[ "jobs" ][ 0 ]
    assert hourly_gap[ "state" ] == "silent"                                                 # due 14:00 and not run since 11:40


def test_run_now_reaps_its_child_and_the_lock_probe_does_not_block_a_shared_holder(tmp_path):
    root = write_registry( tmp_path, [ job( "r", run={ "argv": [ "x" ] } ) ] )
    spawn = Spawner()
    import threading
    seen = []
    real = threading.Thread
    threading.Thread = lambda target, daemon: types.SimpleNamespace( start=lambda: seen.append( ( target, daemon ) ) )
    try: svc.run_now( root, tmp_path, "r", None, Deps(), NOW, spawn )
    finally: threading.Thread = real
    assert seen[ 0 ][ 1 ] is True and seen[ 0 ][ 0 ]() is None and spawn.waited == [ True ]
    import fcntl
    lock = tmp_path / "shared.lock"
    with open( lock, "a" ) as other:
        fcntl.flock( other, fcntl.LOCK_SH )
        assert svc.LiveDeps( tmp_path, tmp_path ).lock_held( lock ) is False               # a shared holder must not read as a held run lock


def no_binaries( *a, **k ):
    """Stands in for a container that has neither crontab nor systemctl."""
    raise FileNotFoundError( a[ 0 ][ 0 ] )


def test_without_crontab_or_systemctl_the_card_says_unverified_until_a_fresh_host_snapshot_arrives(tmp_path, monkeypatch):
    import cosa.rest.job_cron
    from lupin_mcp import host_snapshot as hs
    monkeypatch.setattr( hs.subprocess, "run", no_binaries )
    tagged = job( "t", cron_tag="t-tag", schedule=[ { "cron": "0 10-22 * * *" } ] )
    live   = job( "u", schedule=[], liveness={ "kind": "systemd", "unit": "u.service" } )
    root   = write_registry( tmp_path, [ tagged, live ] )
    summary_file( root, "t", when=NOW - datetime.timedelta( minutes=20 ) )
    data   = tmp_path / "data"; data.mkdir()
    deps   = svc.LiveDeps( root, data )
    deps.boot_time = lambda: NOW - datetime.timedelta( days=3 )
    deps.store_counts = lambda *a: None
    def cards():
        got = { j[ "job" ]: j for j in svc.build_response( root, data, datetime.datetime.now().astimezone(), deps )[ "jobs" ] }
        return got[ "t" ], got[ "u" ]
    t, u = cards()                                                                          # no snapshot at all
    assert t[ "schedule_unverified" ] is True and u[ "state" ] == "unknown" and "liveness unverified" in u[ "unknown_reason" ]
    now = datetime.datetime.now().astimezone()
    ( data / hs.SNAPSHOT_FILE ).write_text( json.dumps( { "schema": hs.SCHEMA, "crontab": "7 11 * * * x # t-tag\n", "crontab_at": now.isoformat(), "zone": "America/New_York", "units": { "u.service": "active" }, "units_at": now.isoformat() } ) )
    t, u = cards()                                                                          # fresh snapshot: both verified
    assert t[ "schedule_unverified" ] is False and t[ "schedule" ][ "entries" ] == [ "cron 7 11 * * *" ] and u[ "state" ] == "healthy"
    old = ( now - datetime.timedelta( hours=40 ) ).isoformat()
    ( data / hs.SNAPSHOT_FILE ).write_text( json.dumps( { "schema": hs.SCHEMA, "crontab": "7 11 * * * x # t-tag\n", "crontab_at": old, "units": { "u.service": "active" }, "units_at": old } ) )
    t, u = cards()                                                                          # stale: never trusted
    assert t[ "schedule_unverified" ] is True and u[ "state" ] == "unknown"


def test_a_health_endpoint_answers_for_a_service_when_systemd_and_the_snapshot_cannot(tmp_path, monkeypatch):
    from lupin_mcp import host_snapshot as hs
    monkeypatch.setattr( hs.subprocess, "run", no_binaries )
    monkeypatch.setattr( svc.hs, "health_ok", lambda url: "active" if url == "http://x/health" else "inactive" )
    live = svc.LiveDeps( tmp_path, tmp_path )
    assert live.unit_state( "a.service", "http://x/health" ) == "active" and live.unit_state( "a.service", "http://y/health" ) == "inactive" and live.unit_state( "a.service" ) is None


def test_live_inputs_prefer_the_direct_answer_over_the_snapshot(tmp_path, monkeypatch):
    from lupin_mcp import host_snapshot as hs
    monkeypatch.setattr( svc.hs, "crontab_text", lambda: "0 1 * * * a # tag\n" )
    monkeypatch.setattr( svc.hs, "unit_state", lambda unit: "inactive" )
    live = svc.LiveDeps( tmp_path, tmp_path )
    assert live.crontab_text() == "0 1 * * * a # tag\n" and live.unit_state( "x" ) == "inactive"


def test_cron_is_read_in_the_hosts_zone_when_the_container_runs_in_another(tmp_path, monkeypatch):
    from lupin_mcp import host_snapshot as hs
    monkeypatch.setattr( hs.subprocess, "run", no_binaries )
    utc  = datetime.timezone.utc
    tagged = job( "t", cron_tag="t-tag", schedule=[] )
    root = write_registry( tmp_path, [ tagged ] )
    now_ny = datetime.datetime( 2026, 11, 7, 22, 42, tzinfo=NY )                              # 22:42 in New York, 03:42 UTC next day
    summary_file( root, "t", when=datetime.datetime( 2026, 11, 7, 19, 31, tzinfo=NY ) )
    data = tmp_path / "data"; data.mkdir()
    def write( zone ):
        doc = { "schema": hs.SCHEMA, "crontab": "0 10-22 * * * x # t-tag\n", "crontab_at": datetime.datetime.now().astimezone().isoformat(), "units": {}, "units_at": None }
        if zone: doc[ "zone" ] = zone
        ( data / hs.SNAPSHOT_FILE ).write_text( json.dumps( doc ) )
    deps = svc.LiveDeps( root, data )
    deps.boot_time = lambda: now_ny - datetime.timedelta( days=3 )
    write( "America/New_York" )
    got = svc.build_response( root, data, now_ny.astimezone( utc ), deps )[ "jobs" ][ 0 ]
    assert got[ "state" ] == "silent" and got[ "schedule" ][ "last_due" ] == datetime.datetime( 2026, 11, 7, 22, 0, tzinfo=NY ).isoformat()      # the New York 22:00 slot, not 22:00 UTC
    write( None )
    assert svc.build_response( root, data, now_ny.astimezone( utc ), deps )[ "jobs" ][ 0 ][ "schedule_unverified" ] is True                      # a snapshot with no zone is not trusted
    write( "Not/AZone" )
    assert svc.build_response( root, data, now_ny.astimezone( utc ), deps )[ "jobs" ][ 0 ][ "schedule_unverified" ] is True


READER_FILES = ( "src/cosa/rest/job_registry.py", "src/cosa/rest/job_service.py", "src/cosa/rest/job_health.py", "src/cosa/rest/job_cron.py",
                 "src/cosa/rest/routers/job_summary.py", "src/lupin_mcp/job_summary.py" )


NOTE_KEYS        = ( "catalog", "owner_confirmed", "owner_note", "schedule_note" )     # for people reading the file; no code is meant to read them


def _registry_keys( reg ):
    """Every key the registry file sets: defaults, each job's own keys and schedule-entry keys."""
    keys = set( reg[ "defaults" ] )
    for job in reg[ "jobs" ]:
        keys |= set( job )
        for entry in job.get( "schedule", [] ): keys |= set( entry )
    return keys


def _is_read( key, text ):
    """True when a reader names the key as a quoted string, as every reader looks one up."""
    return f'"{key}"' in text or f"'{key}'" in text


def test_every_key_the_registry_sets_is_read_by_some_code():
    reader_text = "\n".join( ( REAL_ROOT / path ).read_text() for path in READER_FILES )
    keys = _registry_keys( jr.load_registry( REAL_ROOT ) )
    assert len( keys ) > 20, f"only {len( keys )} keys found: the sweep is not reaching the registry"
    assert _is_read( "grace_minutes", reader_text ), "positive control: a key the readers certainly use must be found"
    assert not _is_read( "summary_every_seconds_unread_control", reader_text ), "negative control: an invented key must not be found"
    unread = sorted( k for k in keys if not _is_read( k, reader_text ) and k not in NOTE_KEYS )
    assert unread == [ ], f"registry keys no code reads (a setting that does nothing): {unread}"
    assert set( NOTE_KEYS ) <= keys, "an exemption names a key the registry no longer sets: drop it from the list"
    assert not any( _is_read( k, reader_text ) for k in NOTE_KEYS ), "an exempted key is now read: drop it from the exemption list"


def test_the_unread_key_sweep_would_catch_the_removed_key():
    reg = jr.load_registry( REAL_ROOT )
    reg[ "defaults" ][ "summary_every_seconds" ] = 60
    reader_text = "\n".join( ( REAL_ROOT / path ).read_text() for path in READER_FILES )
    unread = [ k for k in _registry_keys( reg ) if not _is_read( k, reader_text ) and k not in NOTE_KEYS ]
    assert unread == [ "summary_every_seconds" ]
