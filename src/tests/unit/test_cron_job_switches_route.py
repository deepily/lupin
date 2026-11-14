#!/usr/bin/env python3
"""
Tests for the scheduled-job switch routes, GET and PUT under /api/cron-jobs.

Only an administrator login may flip a switch. An API key alone, and a login without the admin
role, get 403 and nothing is written. An unknown job is 404 and a body that is not a bare boolean
is 422. A job that does not read its switch is 409, so is a key the file lacks or defines twice.
A file that cannot be written is 500.

Every test writes to tmp_path. The live configuration file is never touched.
"""
import json
import os
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.utils.util as cu
from cosa.rest import cron_job_switches as sw
from cosa.rest import job_registry as jr
from cosa.rest.auth_middleware import get_current_user_optional, require_admin
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import cron_jobs
from lupin_mcp import config_write_lock
from lupin_mcp import fleet_cap_ini_io as io

LIST_PATH = "/api/cron-jobs"


def _registry():
    return jr.load_registry( cu.get_project_root() )[ "jobs" ]


def _ini_text( value="true", skip=None, twice=None ):
    lines = [ "[Lupin: Baseline]" ]
    for entry in _registry():
        if entry[ "job" ] == skip: continue
        lines.append( f"{sw.switch_key( entry[ 'job' ] )} = {value}" )
        if entry[ "job" ] == twice: lines.append( f"{sw.switch_key( twice )} = {value}" )
    return "\n".join( lines ) + "\n"


@pytest.fixture
def ini( tmp_path, monkeypatch ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( _ini_text(), encoding="utf-8" )
    monkeypatch.setenv( sw.INI_OVERRIDE_ENV, str( path ) )
    return path


@pytest.fixture
def announced( monkeypatch ):
    calls = []
    async def fake( row ):
        calls.append( row )
    monkeypatch.setattr( cron_jobs, "_announce", fake )
    return calls


def _client( role="admin", login=True ):
    """role: admin | user. login False is an API key caller with no login."""
    app = FastAPI()
    app.include_router( cron_jobs.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    app.dependency_overrides[ get_current_user_optional ] = lambda: ( { "email": "rick@example.com", "roles": [ role ] } if login else None )
    if role == "admin" and login:
        app.dependency_overrides[ require_admin ] = lambda: { "email": "rick@example.com", "roles": [ "admin" ] }
    else:
        def refuse():
            raise HTTPException( status_code=403, detail="admin role required" )
        app.dependency_overrides[ require_admin ] = refuse
    return TestClient( app )


def _put( client, job, body, headers=None ):
    return client.put( f"/api/cron-jobs/{job}/enabled", json=body, headers=headers )


# ── the read ─────────────────────────────────────────────────────────────────

def test_the_list_has_one_row_per_registry_job( ini ):
    rows = _client().get( LIST_PATH ).json()[ "jobs" ]
    names = [ r[ "job" ] for r in rows ]
    assert len( rows ) == len( json.load( open( os.path.join( cu.get_project_root(), "src/conf/job-registry.json" ) ) )[ "jobs" ] )
    assert len( rows ) == 24
    assert names == [ e[ "job" ] for e in _registry() ]
    first = rows[ 0 ]
    assert first[ "key" ] == f"cron job {first[ 'job' ]} enabled"
    assert first[ "enabled" ] is True
    assert first[ "schedule" ] == "cron 0 10-22 * * *; 300 s after boot"
    assert first[ "last_changed_by" ] is None and first[ "last_changed_at" ] is None


def test_a_job_without_a_schedule_says_so( ini ):
    rows = { r[ "job" ]: r for r in _client().get( LIST_PATH ).json()[ "jobs" ] }
    assert rows[ "fleet-arbiter" ][ "schedule" ] == "not scheduled"


def test_the_list_reads_the_file_every_time( ini ):
    client = _client()
    assert client.get( LIST_PATH ).json()[ "jobs" ][ 0 ][ "enabled" ] is True
    io.write_bool_to_disk( str( ini ), sw.switch_key( "duplicate-check" ), False )
    assert client.get( LIST_PATH ).json()[ "jobs" ][ 0 ][ "enabled" ] is False


@pytest.mark.parametrize( "value", [ "maybe", "" ] )
def test_a_value_that_is_not_true_or_false_reads_as_unknown( ini, value ):
    ini.write_text( _ini_text( value ), encoding="utf-8" )
    assert _client().get( LIST_PATH ).json()[ "jobs" ][ 0 ][ "enabled" ] is None


def test_a_missing_key_reads_as_unknown( ini ):
    ini.write_text( _ini_text( skip="duplicate-check" ), encoding="utf-8" )
    assert _client().get( LIST_PATH ).json()[ "jobs" ][ 0 ][ "enabled" ] is None


def test_upper_case_true_reads_as_true( ini ):
    ini.write_text( _ini_text( "TRUE" ), encoding="utf-8" )
    assert _client().get( LIST_PATH ).json()[ "jobs" ][ 0 ][ "enabled" ] is True


def test_caller_is_admin_follows_the_login( ini ):
    assert _client( "admin" ).get( LIST_PATH ).json()[ "caller_is_admin" ] is True
    assert _client( "user" ).get( LIST_PATH ).json()[ "caller_is_admin" ] is False
    assert _client( "admin", login=False ).get( LIST_PATH ).json()[ "caller_is_admin" ] is False


def test_an_unusable_registry_is_500( ini, monkeypatch ):
    def broken( root ): raise ValueError( "bad schema" )
    monkeypatch.setattr( jr, "load_registry", broken )
    response = _client().get( LIST_PATH )
    assert response.status_code == 500 and "bad schema" in response.json()[ "detail" ]


# ── the write: who may ───────────────────────────────────────────────────────

def test_an_admin_flip_writes_the_file_and_returns_the_reread_row( ini, tmp_path, announced ):
    response = _put( _client(), "duplicate-check", { "on": False } )
    assert response.status_code == 200
    row = response.json()
    assert row[ "enabled" ] is False and row[ "last_changed_by" ] == "rick@example.com"
    assert io.read_value_from_disk( str( ini ), sw.switch_key( "duplicate-check" ) ) == "false"
    assert io.read_value_from_disk( str( ini ), sw.switch_key( "wiki-librarian" ) ) == "true"
    assert announced == [ row ]
    listed = _client().get( LIST_PATH ).json()[ "jobs" ][ 0 ]
    assert listed[ "last_changed_by" ] == "rick@example.com" and listed[ "last_changed_at" ] is not None


def test_an_admin_without_an_email_is_named_by_uid( ini, announced ):
    app = FastAPI()
    app.include_router( cron_jobs.router )
    app.dependency_overrides[ require_admin ] = lambda: { "uid": "u-1" }
    assert _put( TestClient( app ), "duplicate-check", { "on": False } ).json()[ "last_changed_by" ] == "u-1"


def test_an_admin_without_email_or_uid_is_unknown( ini, announced ):
    app = FastAPI()
    app.include_router( cron_jobs.router )
    app.dependency_overrides[ require_admin ] = lambda: {}
    assert _put( TestClient( app ), "duplicate-check", { "on": False } ).json()[ "last_changed_by" ] == "unknown"


def test_an_api_key_alone_is_403_and_writes_nothing( ini, announced ):
    before = ini.read_text()
    # require_admin is overridden to pass, so only the key refusal can be what stops this.
    app = FastAPI()
    app.include_router( cron_jobs.router )
    app.dependency_overrides[ require_admin ] = lambda: { "email": "rick@example.com" }
    response = _put( TestClient( app ), "duplicate-check", { "on": False }, headers={ "X-API-Key": "k" } )
    assert response.status_code == 403
    assert ini.read_text() == before and announced == []
    assert not os.path.exists( sw.state_path() )


def test_a_non_admin_login_is_403_and_writes_nothing( ini, announced ):
    before = ini.read_text()
    response = _put( _client( "user" ), "duplicate-check", { "on": False } )
    assert response.status_code == 403
    assert ini.read_text() == before and announced == []
    assert not os.path.exists( sw.state_path() )


def test_no_login_at_all_is_refused_and_writes_nothing( ini, announced ):
    before = ini.read_text()
    response = _put( _client( "admin", login=False ), "duplicate-check", { "on": False } )
    assert response.status_code == 403
    assert ini.read_text() == before and announced == []


# ── the write: what is refused ───────────────────────────────────────────────

def test_an_unknown_job_is_404_and_writes_nothing( ini, announced ):
    before = ini.read_text()
    response = _put( _client(), "no-such-job", { "on": True } )
    assert response.status_code == 404
    assert ini.read_text() == before and announced == []


@pytest.mark.parametrize( "body", [ { "on": "yes" }, { "on": 1 }, { "on": None }, {}, { "on": True, "extra": 1 } ] )
def test_a_body_that_is_not_a_bare_boolean_is_422( ini, announced, body ):
    before = ini.read_text()
    assert _put( _client(), "duplicate-check", body ).status_code == 422
    assert ini.read_text() == before and announced == []


def test_a_key_the_file_lacks_is_409_and_is_not_invented( ini, announced ):
    ini.write_text( _ini_text( skip="duplicate-check" ), encoding="utf-8" )
    before = ini.read_text()
    assert _put( _client(), "duplicate-check", { "on": True } ).status_code == 409
    assert ini.read_text() == before and announced == []
    assert not os.path.exists( sw.state_path() )               # a refused flip leaves no attribution record


def test_a_key_defined_twice_is_409( ini, announced ):
    ini.write_text( _ini_text( twice="duplicate-check" ), encoding="utf-8" )
    before = ini.read_text()
    assert _put( _client(), "duplicate-check", { "on": False } ).status_code == 409
    assert ini.read_text() == before and announced == []
    assert not os.path.exists( sw.state_path() )               # a refused flip leaves no attribution record


def test_a_file_that_cannot_be_written_is_500_and_announces_nothing( ini, announced, monkeypatch ):
    def refuse( *args, **kwargs ): raise OSError( "disk full" )
    monkeypatch.setattr( sw, "write_switch", refuse )
    response = _put( _client(), "duplicate-check", { "on": False } )
    assert response.status_code == 500 and "disk full" in response.json()[ "detail" ]
    assert announced == []


def test_an_unusable_registry_refuses_the_write( ini, monkeypatch, announced ):
    def broken( root ): raise OSError( "no registry" )
    monkeypatch.setattr( jr, "load_registry", broken )
    assert _put( _client(), "duplicate-check", { "on": False } ).status_code == 500


# ── attribution ──────────────────────────────────────────────────────────────

def test_a_hand_edit_after_a_flip_shows_no_setter( ini, announced ):
    _put( _client(), "duplicate-check", { "on": False } )
    io.write_bool_to_disk( str( ini ), sw.switch_key( "duplicate-check" ), True )
    row = _client().get( LIST_PATH ).json()[ "jobs" ][ 0 ]
    assert row[ "enabled" ] is True and row[ "last_changed_by" ] is None


def test_a_second_flip_keeps_the_first_jobs_record( ini, announced ):
    _put( _client(), "duplicate-check", { "on": False } )
    _put( _client(), "wiki-librarian", { "on": False } )
    rows = { r[ "job" ]: r for r in _client().get( LIST_PATH ).json()[ "jobs" ] }
    assert rows[ "duplicate-check" ][ "last_changed_by" ] == "rick@example.com"
    assert rows[ "wiki-librarian" ][ "last_changed_by" ] == "rick@example.com"


@pytest.mark.parametrize( "content", [ "not json", "[1, 2]" ] )
def test_a_damaged_attribution_file_reads_as_empty( ini, content ):
    with open( sw.state_path(), "w" ) as handle: handle.write( content )
    assert sw.read_attribution() == {}


def test_the_default_paths_follow_the_main_checkout_and_the_lock_folder( monkeypatch, tmp_path ):
    monkeypatch.delenv( sw.INI_OVERRIDE_ENV, raising=False )
    monkeypatch.setenv( config_write_lock.LOCK_DIR_ENV, str( tmp_path ) )
    from lupin_mcp import fleet_size_cap
    assert sw.ini_path() == fleet_size_cap.main_checkout_ini_path()
    assert sw.state_path() == os.path.join( str( tmp_path ), sw.STATE_FILENAME )


# ── the event ────────────────────────────────────────────────────────────────

class _Manager:
    def __init__( self ): self.sent = []
    async def emit_to_all( self, event, data ): self.sent.append( ( event, data ) )


def test_a_flip_emits_the_event_to_every_client( ini, monkeypatch ):
    import types
    manager = _Manager()
    monkeypatch.setitem( sys.modules, "lupin_app.main", types.SimpleNamespace( websocket_manager=manager ) )
    row = _put( _client(), "duplicate-check", { "on": False } ).json()
    assert manager.sent == [ ( "cron_job_switch_changed", row ) ]


def test_a_failed_announcement_does_not_fail_the_flip( ini, monkeypatch, capsys ):
    import types
    monkeypatch.setitem( sys.modules, "lupin_app.main", types.SimpleNamespace() )
    response = _put( _client(), "duplicate-check", { "on": False } )
    assert response.status_code == 200
    assert "[CRON-JOBS] switch event failed" in capsys.readouterr().out


# ── honoured and drift (María's amendments 1 and 3) ──────────────────────────

def test_honoured_is_computed_from_the_registry_and_names_twelve_jobs( ini ):
    rows = _client().get( LIST_PATH ).json()[ "jobs" ]
    honoured = sorted( r[ "job" ] for r in rows if r[ "honoured" ] )
    pinned   = sorted( e[ "job" ] for e in json.load( open( os.path.join( cu.get_project_root(), "src/conf/job-registry.json" ) ) )[ "jobs" ] if e.get( "cron_managed" ) is True )
    assert honoured == pinned and len( honoured ) == 12
    assert all( r[ "honoured" ] is False for r in rows if r[ "job" ] in ( "fleet-arbiter", "context-tick", "yearly-reminders" ) )


def test_a_job_that_does_not_read_its_switch_answers_409_and_writes_nothing( ini, announced ):
    before = ini.read_text()
    response = _put( _client(), "fleet-arbiter", { "on": False } )
    assert response.status_code == 409 and "fleet-arbiter" in response.json()[ "detail" ]
    assert ini.read_text() == before and announced == []
    assert not os.path.exists( sw.state_path() )


def test_is_honoured_is_true_only_for_a_literal_true():
    assert sw.is_honoured( { "cron_managed": True } ) is True
    assert sw.is_honoured( { "cron_managed": "yes" } ) is False
    assert sw.is_honoured( {} ) is False


def test_a_job_never_flipped_has_no_drift( ini ):
    assert _client().get( LIST_PATH ).json()[ "jobs" ][ 0 ][ "drift" ] is False


def test_a_clean_flip_has_no_drift( ini, announced ):
    row = _put( _client(), "duplicate-check", { "on": False } ).json()
    assert row[ "drift" ] is False
    assert _client().get( LIST_PATH ).json()[ "jobs" ][ 0 ][ "drift" ] is False


def test_a_hand_edit_after_a_flip_is_drift( ini, announced ):
    _put( _client(), "duplicate-check", { "on": False } )
    io.write_bool_to_disk( str( ini ), sw.switch_key( "duplicate-check" ), True )
    row = _client().get( LIST_PATH ).json()[ "jobs" ][ 0 ]
    assert row[ "drift" ] is True and row[ "enabled" ] is True and row[ "last_changed_by" ] is None


def test_an_unknown_key_is_enabled_none_and_not_drift( ini, announced ):
    _put( _client(), "duplicate-check", { "on": False } )
    ini.write_text( _ini_text( skip="duplicate-check" ), encoding="utf-8" )
    row = _client().get( LIST_PATH ).json()[ "jobs" ][ 0 ]
    assert row[ "enabled" ] is None and row[ "drift" ] is False
