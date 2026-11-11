"""The host snapshot: what a host job leaves for the container, with its time limits."""
import datetime
import json
import types

import pytest

from lupin_mcp import host_snapshot as hs

NOW = datetime.datetime( 2026, 11, 7, 12, 0, tzinfo=datetime.timezone.utc )


def runner( crontab="0 1 * * * x\n", crontab_rc=0, unit="LoadState=loaded\nActiveState=active\n" ):
    """Ensures: returns a subprocess.run stand-in answering crontab and systemctl."""
    def run( argv, **kw ):
        if argv[ 0 ] == "crontab": return types.SimpleNamespace( stdout=crontab, returncode=crontab_rc )
        return types.SimpleNamespace( stdout=unit, returncode=0 )
    return run


def test_crontab_text_and_unit_state_answer_or_say_none():
    assert hs.crontab_text( runner() ) == "0 1 * * * x\n" and hs.crontab_text( runner( crontab_rc=1 ) ) is None
    assert hs.unit_state( "u", runner() ) == "active" and hs.unit_state( "u", runner( unit="LoadState=loaded\nActiveState=failed\n" ) ) == "inactive"
    assert hs.unit_state( "u", runner( unit="LoadState=not-found\n" ) ) == "not-loaded" and hs.unit_state( "u", runner( unit="junk\n" ) ) is None
    def gone( *a, **k ): raise FileNotFoundError( "x" )
    assert hs.crontab_text( gone ) is None and hs.unit_state( "u", gone ) is None


def test_registry_units_lists_jobs_and_targets_once():
    reg = { "jobs": [ { "liveness": { "unit": "a" } }, { "targets": [ { "liveness": { "unit": "b" } }, { "liveness": { "unit": "a" } }, {} ] }, {} ] }
    assert hs.registry_units( reg ) == [ "a", "b" ]


def test_health_ok_is_active_only_for_a_200():
    class Answer:
        def __init__( self, status ): self.status = status
        def __enter__( self ): return self
        def __exit__( self, *a ): return False
    assert hs.health_ok( "u", lambda url, timeout: Answer( 200 ) ) == "active" and hs.health_ok( "u", lambda url, timeout: Answer( 503 ) ) == "inactive"
    def down( url, timeout ): raise OSError( "refused" )
    assert hs.health_ok( "u", down ) == "inactive"


def test_a_job_run_refreshes_only_the_crontab_and_a_tick_refreshes_both(tmp_path):
    tick = hs.write_snapshot( tmp_path, NOW, [ "u" ], runner() )
    assert tick[ "units" ] == { "u": "active" } and tick[ "units_at" ] == NOW.isoformat() and tick[ "crontab" ] == "0 1 * * * x\n"
    later = NOW + datetime.timedelta( hours=5 )
    job = hs.write_snapshot( tmp_path, later, None, runner( crontab="0 2 * * * y\n" ) )
    assert job[ "crontab" ] == "0 2 * * * y\n" and job[ "crontab_at" ] == later.isoformat() and job[ "units" ] == { "u": "active" } and job[ "units_at" ] == NOW.isoformat()
    assert [ p.name for p in tmp_path.iterdir() ] == [ hs.SNAPSHOT_FILE ]


def test_each_part_expires_on_its_own_limit_and_a_bad_file_reads_as_nothing(tmp_path):
    hs.write_snapshot( tmp_path, NOW, [ "u" ], runner() )
    fresh = hs.read_snapshot( tmp_path, NOW + datetime.timedelta( seconds=hs.UNITS_MAX_AGE ) )
    assert fresh[ "units" ] == { "u": "active" } and fresh[ "crontab" ] is not None
    mid = hs.read_snapshot( tmp_path, NOW + datetime.timedelta( seconds=hs.UNITS_MAX_AGE + 1 ) )
    assert mid[ "units" ] is None and mid[ "crontab" ] is not None                     # units expired, crontab still good
    late = hs.read_snapshot( tmp_path, NOW + datetime.timedelta( seconds=hs.CRONTAB_MAX_AGE + 1 ) )
    assert late[ "crontab" ] is None and late[ "units" ] is None
    nothing = { "crontab": None, "units": None, "zone": None }
    assert hs.read_snapshot( tmp_path / "none", NOW ) == nothing
    path = tmp_path / hs.SNAPSHOT_FILE
    path.write_text( "{bad" ); assert hs.read_snapshot( tmp_path, NOW ) == nothing
    path.write_text( json.dumps( { "schema": "x" } ) ); assert hs.read_snapshot( tmp_path, NOW ) == nothing
    path.write_text( "[1]" ); assert hs.read_snapshot( tmp_path, NOW ) == nothing
    path.write_text( json.dumps( { "schema": hs.SCHEMA, "crontab": "c", "crontab_at": "junk", "units": {}, "units_at": "2026-11-07T12:00:00" } ) )
    assert hs.read_snapshot( tmp_path, NOW ) == nothing                                # unparseable and naive times are not trusted
    hs.write_snapshot( tmp_path, NOW, [], lambda argv, **k: types.SimpleNamespace( stdout="", returncode=1 ) )
    assert hs.read_snapshot( tmp_path, NOW )[ "crontab" ] is None


def test_refresh_best_effort_writes_into_the_named_folder_and_never_raises(tmp_path):
    assert hs.refresh_best_effort( { "LUPIN_REUSE_REVIEW_DATA_ROOT": str( tmp_path ) }, NOW, runner() ) is True and ( tmp_path / hs.SNAPSHOT_FILE ).exists()
    blocker = tmp_path / "f"; blocker.write_text( "x" )
    assert hs.refresh_best_effort( { "LUPIN_REUSE_REVIEW_DATA_ROOT": str( blocker / "sub" ) }, NOW, runner() ) is False


def test_refresh_best_effort_derives_the_folder_from_the_root_when_the_variable_is_missing(tmp_path, monkeypatch):
    import cosa.repo.symindex.paths as paths
    monkeypatch.setattr( paths, "data_dir", lambda root: tmp_path / "derived" )
    assert hs.refresh_best_effort( { "LUPIN_ROOT": "/r" }, NOW, runner() ) is True and ( tmp_path / "derived" / hs.SNAPSHOT_FILE ).exists()
    monkeypatch.chdir( tmp_path )
    assert hs.refresh_best_effort( {}, NOW, runner() ) is True


def test_main_writes_crontab_and_the_registry_units(tmp_path, monkeypatch):
    import cosa.rest.job_registry as jr
    reg = tmp_path / jr.REGISTRY_FILE
    reg.parent.mkdir( parents=True )
    reg.write_text( json.dumps( { "schema": "job-registry/1", "defaults": {}, "jobs": [ { "job": "j", "title": "J", "owner": "cheech", "liveness": { "kind": "systemd", "unit": "j.service" } } ] } ) )
    data = tmp_path / "data"
    assert hs.main( [], { "LUPIN_ROOT": str( tmp_path ), "LUPIN_REUSE_REVIEW_DATA_ROOT": str( data ) }, NOW, runner() ) == 0
    doc = json.loads( ( data / hs.SNAPSHOT_FILE ).read_text() )
    assert doc[ "units" ] == { "j.service": "active" } and doc[ "crontab" ] == "0 1 * * * x\n"
    import cosa.repo.symindex.paths as paths
    monkeypatch.setattr( paths, "data_dir", lambda root: tmp_path / "d2" )
    assert hs.main( [], { "LUPIN_ROOT": str( tmp_path ) }, NOW, runner() ) == 0 and ( tmp_path / "d2" / hs.SNAPSHOT_FILE ).exists()


def test_the_host_zone_is_the_tz_variable_or_the_localtime_link_and_none_when_neither_names_a_zone(tmp_path):
    assert hs.host_zone_name( { "TZ": "America/New_York" }, "/nonexistent" ) == "America/New_York"
    link = tmp_path / "zoneinfo" / "Europe" / "Paris"; link.parent.mkdir( parents=True ); link.write_text( "" )
    lt = tmp_path / "localtime"; lt.symlink_to( link )
    assert hs.host_zone_name( {}, str( lt ) ) == "Europe/Paris" if hs.zone_of( "Europe/Paris" ) else True
    assert hs.host_zone_name( { "TZ": "Bad/Zone" }, str( tmp_path / "none" ) ) is None and hs.host_zone_name( {}, str( tmp_path / "none" ) ) is None
    assert hs.zone_of( "" ) is None and hs.zone_of( None ) is None and hs.zone_of( "Bad/Zone" ) is None and str( hs.zone_of( "UTC" ) ) == "UTC"


def test_the_snapshot_records_the_zone_and_the_reader_returns_a_tzinfo(tmp_path, monkeypatch):
    monkeypatch.setattr( hs, "host_zone_name", lambda: "America/New_York" )
    hs.write_snapshot( tmp_path, NOW, [], runner() )
    assert str( hs.read_snapshot( tmp_path, NOW )[ "zone" ] ) == "America/New_York"


def test_the_limits_are_pinned_to_literals_so_a_changed_constant_cannot_pass_itself():
    assert hs.UNITS_MAX_AGE == 1800 and hs.CRONTAB_MAX_AGE == 36 * 3600


def test_a_file_of_another_schema_is_refused_even_with_good_times(tmp_path):
    ( tmp_path / hs.SNAPSHOT_FILE ).write_text( json.dumps( { "schema": "other/1", "crontab": "c", "crontab_at": NOW.isoformat(), "units": {}, "units_at": NOW.isoformat(), "zone": "UTC" } ) )
    assert hs.read_snapshot( tmp_path, NOW ) == { "crontab": None, "units": None, "zone": None }


ENV = { "LUPIN_CONFIG_MGR_CLI_ARGS": "config_path=/a b=c", "DEEPILY_DATA_DIR": "/mnt/data dir" }


def args( **over ):
    """Ensures: returns parsed-argument stand-ins, with the given flags set."""
    base = { "root": "/r", "python": "/py", "status": False, "uninstall": False, "print_install": False, "install": False }
    return types.SimpleNamespace( **{ **base, **over } )


def test_print_install_prints_the_line_the_registry_gives_this_job_through_the_generator(monkeypatch):
    import os
    said = []
    root = os.environ[ "LUPIN_ROOT" ]
    assert hs.install_mode( args( print_install=True, root=root ), ENV, NOW, said.append, said.append, None ) == 0
    assert said[ 0 ].startswith( "*/5 * * * * " ) and f"{root}/src/scripts/cron-job.sh host-snapshot cron" in said[ 0 ] and said[ 0 ].endswith( "# job-host-snapshot" )
    assert not hasattr( hs, "cron_line" )


def test_print_install_changes_nothing_install_is_retired_and_uninstall_uses_the_locked_editor_with_this_tag(monkeypatch):
    import os
    from cosa.repo.symindex import librarian_tick as lt
    calls, said = [], []
    monkeypatch.setattr( lt, "edit_crontab", lambda lines, environ, cmd, backups, now, tag, owner: calls.append( ( lines, backups, tag, owner ) ) )
    assert hs.install_mode( args( print_install=True, root=os.environ[ "LUPIN_ROOT" ] ), ENV, NOW, said.append, said.append, None ) == 0 and calls == [] and said[ 0 ].endswith( "# job-host-snapshot" ) and "cron-job.sh host-snapshot cron" in said[ 0 ]
    assert hs.install_mode( args( install=True ), ENV, NOW, said.append, said.append, None ) == 1 and calls == [] and "lupin_mcp.cron_generate --install" in said[ -1 ]
    assert hs.install_mode( args( uninstall=True ), ENV, NOW, said.append, said.append, None ) == 0 and calls[ 0 ][ 0 ] == [] and said[ -1 ] == "uninstalled"
    assert calls[ 0 ][ 1: ] == ( "/r/io/jobs/crontab-backups", "# job-host-snapshot", "job-host-snapshot" )


def test_status_reports_the_line_and_a_refused_uninstall_prints_one_line_and_returns_one(monkeypatch):
    import sys
    from cosa.repo.symindex import librarian_tick as lt
    said = []
    have = [ sys.executable, "-c", "print('*/5 * * * * x # job-host-snapshot')", "--" ]
    assert hs.install_mode( args( status=True ), {}, NOW, said.append, said.append, have[ :3 ] ) == 0 and said[ -1 ] == "installed: 1 lines"
    none = [ sys.executable, "-c", "import sys; sys.exit(1)" ]
    assert hs.install_mode( args( status=True ), {}, NOW, said.append, said.append, none ) == 0 and said[ -1 ] == "not installed"
    def refuse( *a, **k ): raise lt.InstallRefused( "no lock" )
    monkeypatch.setattr( lt, "edit_crontab", refuse )
    assert hs.install_mode( args( uninstall=True ), ENV, NOW, said.append, said.append, None ) == 1 and said[ -1 ] == "job-host-snapshot: no lock"
    assert hs.install_mode( args( uninstall=True, root=None ), { "LUPIN_ROOT": "/e" }, NOW, said.append, said.append, None ) == 1
    monkeypatch.chdir( "/" )
    assert hs.install_mode( args( uninstall=True, root=None ), {}, NOW, said.append, said.append, None ) == 1


def test_main_dispatches_the_verbs_to_install_mode_and_defaults_to_writing_the_snapshot(tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr( hs, "install_mode", lambda a, environ, now, out, err, cmd: seen.append( ( a.install, a.print_install, a.python ) ) or 0 )
    assert hs.main( [ "--print-install", "--python", "/p" ], {}, NOW ) == 0 and hs.main( [ "--install" ], {}, NOW, err=print ) == 0
    assert seen == [ ( False, True, "/p" ), ( True, False, hs.sys.executable ) ]
