"""The jobs endpoints through a real FastAPI app: auth, operator-only, status mapping."""
import datetime
import json
import pathlib
import zoneinfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.rest.job_service as svc
import cosa.rest.routers.job_summary as router
from cosa.rest.middleware.api_key_auth import authenticated_account_email, require_api_key_or_jwt

NOW = datetime.datetime( 2026, 11, 7, 12, 0, tzinfo=zoneinfo.ZoneInfo( "America/New_York" ) )


class Deps:
    """Fake inputs."""
    def boot_time( self ): return NOW - datetime.timedelta( days=3 )
    def unit_state( self, unit ): return "active"
    def lock_held( self, path ): return False
    def store_counts( self, key, now, days ): return None


def registry( root, jobs ):
    """Ensures: writes a registry under root."""
    path = pathlib.Path( root ) / "src" / "conf" / "job-registry.json"
    path.parent.mkdir( parents=True )
    path.write_text( json.dumps( { "schema": "job-registry/1", "defaults": { "grace_minutes": 30, "notify_interval_minutes": 30, "window_days": 7, "growth_min_items": 5, "growth_min_percent": 5, "lock_stale_seconds": 1, "run_env": {} }, "jobs": jobs } ) )


@pytest.fixture
def client( tmp_path, monkeypatch ):
    registry( tmp_path, [ { "job": "r", "title": "R", "owner": "cheech", "schedule": [], "summary_path": "{root}/s.json", "run": { "argv": [ "true" ] } } ] )
    monkeypatch.setattr( router, "live_deps", lambda: ( tmp_path, tmp_path / "data", Deps() ) )
    monkeypatch.setattr( router, "clock", lambda: NOW )
    monkeypatch.setattr( svc.subprocess, "Popen", lambda argv, **kw: type( "P", (), { "pid": 7 } )() )
    app = FastAPI()
    app.include_router( router.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "user"
    app.state.email = None
    app.dependency_overrides[ authenticated_account_email ] = lambda: app.state.email
    return TestClient( app ), app


def test_summary_answers_the_whole_accordion_to_any_authenticated_caller( client ):
    c, _ = client
    got = c.get( "/api/jobs/summary" )
    assert got.json()[ "caller_is_operator" ] is False
    assert got.status_code == 200 and got.json()[ "schema" ] == "jobs-summary/1" and [ j[ "job" ] for j in got.json()[ "jobs" ] ] == [ "r" ] and got.json()[ "jobs" ][ 0 ][ "runnable" ] is True


def test_summary_says_whether_the_caller_is_the_operator_by_the_same_rule_as_run_now( client, monkeypatch ):
    c, app = client
    monkeypatch.setattr( router, "caller_is_operator", lambda email: email == "rick@example.com" )
    app.state.email = "rick@example.com"
    assert c.get( "/api/jobs/summary" ).json()[ "caller_is_operator" ] is True
    app.state.email = "other@example.com"
    assert c.get( "/api/jobs/summary" ).json()[ "caller_is_operator" ] is False


def test_summary_is_a_500_with_the_cause_when_the_registry_is_unusable( client, tmp_path, monkeypatch ):
    c, _ = client
    ( tmp_path / "src" / "conf" / "job-registry.json" ).write_text( "{" )
    got = c.get( "/api/jobs/summary" )
    assert got.status_code == 500 and "job registry unusable" in got.json()[ "detail" ]


def test_run_now_is_refused_for_an_api_key_caller_and_for_any_other_login_before_the_registry_is_read( client, monkeypatch ):
    c, app = client
    monkeypatch.setattr( router, "live_deps", lambda: pytest.fail( "the registry must not be read for a refused caller" ) )
    assert c.post( "/api/jobs/r/run" ).status_code == 403
    app.state.email = "someone.else@example.com"
    got = c.post( "/api/jobs/r/run" )
    assert got.status_code == 403 and "operator" in got.json()[ "detail" ]


def test_run_now_for_the_operator_maps_started_unknown_and_locked_to_their_statuses( client, monkeypatch ):
    c, app = client
    monkeypatch.setattr( router, "caller_is_operator", lambda email: email == "rick@example.com" )
    app.state.email = "rick@example.com"
    ok = c.post( "/api/jobs/r/run?target=t" )
    assert ok.status_code == 200 and ok.json()[ "status" ] == "started" and ok.json()[ "trigger" ] == "hand" and ok.json()[ "target" ] == "t"
    assert c.post( "/api/jobs/zzz/run" ).status_code == 404


def test_live_deps_and_clock_are_the_real_ones( monkeypatch, tmp_path ):
    monkeypatch.setattr( router.cu, "get_project_root", lambda: str( tmp_path ) )
    import cosa.repo.symindex.paths as paths
    monkeypatch.setattr( paths, "data_dir", lambda root: tmp_path / "d" )
    root, data, deps = router.live_deps()
    assert str( root ) == str( tmp_path ) and data == tmp_path / "d" and isinstance( deps, svc.LiveDeps )
    assert router.clock().tzinfo is not None
