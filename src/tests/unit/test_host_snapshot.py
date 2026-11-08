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
    assert late == { "crontab": None, "units": None }
    nothing = { "crontab": None, "units": None }
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
