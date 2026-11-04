#!/usr/bin/env python3
"""
Tests for the skeleton crew route and the state the cap payload now carries.

The operator flips the switch from a client. The route writes the main configuration file
and reads it back. It tells the live sessions and returns the same body the cap read
returns. Every client then repaints from the file and not from its own request.

Only an administrator login may flip it. A Claude session authenticates with an API key. It
may read the state and may not change it, so a manager cannot turn the switch off for itself.

A bad write is refused loudly and nothing is announced. A key defined twice answers 409. A
body that is not a bare boolean answers 422. A file that cannot be written answers 500.

The state has one stored value. The route never copies it into the configuration manager. A
hand edit of the file shows up as an unknown setter and not as a lie.

Every test writes to tmp_path. The live configuration file is never touched.
"""
import asyncio
import json
import os
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.auth_middleware import require_admin
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import arbiter
from lupin_mcp import config_write_lock
from lupin_mcp import fleet_cap_ini_io as io
from lupin_mcp import skeleton_crew as sc


GET_PATH = "/api/arbiter/fleet-size-cap"
PUT_PATH = "/api/arbiter/skeleton-crew"

BODY = """\
[Lupin: Baseline]
cc session fleet size cap                        = 8
cc session fleet size cap maximum                = 18
cc session skeleton crew enabled                 = false
"""


@pytest.fixture
def ini( tmp_path, monkeypatch ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( BODY, encoding="utf-8" )
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( path ) )
    from lupin_mcp import fleet_size_cap
    monkeypatch.setattr( fleet_size_cap, "config_file_path", lambda: str( path ) )
    return path


@pytest.fixture
def state_dir( tmp_path, monkeypatch ):
    folder = tmp_path / "flow"
    monkeypatch.setenv( config_write_lock.LOCK_DIR_ENV, str( folder ) )
    return folder


@pytest.fixture
def no_settings( tmp_path, monkeypatch ):
    monkeypatch.setenv( sc.SETTINGS_ENV, str( tmp_path / "no-settings.json" ) )


@pytest.fixture
def announced( monkeypatch ):
    calls = []
    async def fake( on, user_id, notification_queue ):
        calls.append( ( on, user_id ) )
    monkeypatch.setattr( arbiter, "_announce_flip", fake )
    return calls


def _client( admin=True, email="rick@example.com" ):
    app = FastAPI()
    app.include_router( arbiter.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    if admin:
        app.dependency_overrides[ require_admin ] = lambda: { "email": email }
    else:
        def refuse():
            raise HTTPException( status_code=403, detail="admin role required" )
        app.dependency_overrides[ require_admin ] = refuse
    return TestClient( app )


# ── the read ─────────────────────────────────────────────────────────────────

def test_the_cap_read_carries_the_switch_state( ini, state_dir, no_settings ):
    body = _client().get( GET_PATH ).json()
    assert body[ "skeleton_crew" ] == { "on": False, "since": None, "set_by": None,
                                        "settings_mute_while_off": None }
    assert body[ "cap" ] == 8 and body[ "ceiling" ] == 18


def test_the_read_follows_the_file_and_not_the_cached_configuration( ini, state_dir, no_settings, monkeypatch ):
    import cosa.rest.dependencies.config as config_dep
    class Cached:
        def get( self, key, default=None, return_type="string", silent=False ):
            return False if key == sc.SKELETON_CREW_KEY else default
    monkeypatch.setattr( config_dep, "get_config_manager", lambda: Cached() )
    io.write_bool_to_disk( str( ini ), sc.SKELETON_CREW_KEY, True )
    assert _client().get( GET_PATH ).json()[ "skeleton_crew" ][ "on" ] is True


def test_a_hand_edit_after_a_flip_reads_as_an_unknown_setter( ini, state_dir, no_settings, announced ):
    _client().put( PUT_PATH, json={ "on": True } )
    io.write_bool_to_disk( str( ini ), sc.SKELETON_CREW_KEY, False )
    state = _client().get( GET_PATH ).json()[ "skeleton_crew" ]
    assert state[ "on" ] is False
    assert state[ "set_by" ] == "unknown (file edited)"


@pytest.mark.parametrize( "mute, on, expected", [
    ( True,  False, True ),
    ( True,  True,  False ),
    ( False, False, False ),
    ( False, True,  False ),
] )
def test_the_settings_mute_warning( ini, state_dir, tmp_path, monkeypatch, mute, on, expected ):
    settings = tmp_path / "settings.json"
    settings.write_text( json.dumps( { "heartbeat": { "enabled": True, "poke_output_enabled": not mute } } ),
                         encoding="utf-8" )
    monkeypatch.setenv( sc.SETTINGS_ENV, str( settings ) )
    io.write_bool_to_disk( str( ini ), sc.SKELETON_CREW_KEY, on )
    assert _client().get( GET_PATH ).json()[ "skeleton_crew" ][ "settings_mute_while_off" ] is expected


def test_an_unreadable_settings_file_gives_no_warning_answer( ini, state_dir, tmp_path, monkeypatch ):
    bad = tmp_path / "settings.json"
    bad.write_text( "{not json", encoding="utf-8" )
    monkeypatch.setenv( sc.SETTINGS_ENV, str( bad ) )
    assert _client().get( GET_PATH ).json()[ "skeleton_crew" ][ "settings_mute_while_off" ] is None


def test_a_settings_file_without_the_key_means_the_poke_is_not_muted( ini, state_dir, tmp_path, monkeypatch ):
    plain = tmp_path / "settings.json"
    plain.write_text( json.dumps( { "model": "x" } ), encoding="utf-8" )
    monkeypatch.setenv( sc.SETTINGS_ENV, str( plain ) )
    assert _client().get( GET_PATH ).json()[ "skeleton_crew" ][ "settings_mute_while_off" ] is False


# ── the write ────────────────────────────────────────────────────────────────

def test_an_admin_flip_lands_in_the_file_and_the_body_is_the_re_read( ini, state_dir, no_settings, announced ):
    response = _client().put( PUT_PATH, json={ "on": True } )
    assert response.status_code == 200
    body = response.json()
    assert body[ "skeleton_crew" ][ "on" ] is True
    assert body[ "skeleton_crew" ][ "set_by" ] == "rick@example.com"
    assert body[ "skeleton_crew" ][ "since" ]
    assert body[ "cap" ] == 8 and body[ "ceiling" ] == 18
    assert io.read_value_from_disk( str( ini ), sc.SKELETON_CREW_KEY ) == "true"


def test_the_flip_is_announced_once_with_the_new_state( ini, state_dir, no_settings, announced ):
    _client().put( PUT_PATH, json={ "on": True } )
    _client().put( PUT_PATH, json={ "on": False } )
    assert announced == [ ( True, "test-user" ), ( False, "test-user" ) ]


def test_the_flip_back_to_off_is_written( ini, state_dir, no_settings, announced ):
    _client().put( PUT_PATH, json={ "on": True } )
    body = _client().put( PUT_PATH, json={ "on": False } ).json()
    assert body[ "skeleton_crew" ][ "on" ] is False
    assert io.read_value_from_disk( str( ini ), sc.SKELETON_CREW_KEY ) == "false"


def test_the_setter_falls_back_to_the_user_id_and_then_unknown( ini, state_dir, no_settings, announced ):
    app = FastAPI()
    app.include_router( arbiter.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    app.dependency_overrides[ require_admin ] = lambda: { "uid": "u-77" }
    assert TestClient( app ).put( PUT_PATH, json={ "on": True } ).json()[ "skeleton_crew" ][ "set_by" ] == "u-77"
    app.dependency_overrides[ require_admin ] = lambda: { }
    assert TestClient( app ).put( PUT_PATH, json={ "on": False } ).json()[ "skeleton_crew" ][ "set_by" ] == "unknown"


def test_a_missing_key_is_inserted_and_the_flip_succeeds( ini, state_dir, no_settings, announced ):
    ini.write_text( BODY.replace( "cc session skeleton crew enabled                 = false\n", "" ), encoding="utf-8" )
    response = _client().put( PUT_PATH, json={ "on": True } )
    assert response.status_code == 200
    assert io.read_value_from_disk( str( ini ), sc.SKELETON_CREW_KEY ) == "true"


def test_the_route_never_copies_the_value_into_the_configuration_manager( ini, state_dir, no_settings, announced, monkeypatch ):
    import cosa.rest.dependencies.config as config_dep
    class Recorder:
        def __init__( self ): self.sets = []
        def get( self, key, default=None, return_type="string", silent=False ): return default
        def set_config( self, key, value ): self.sets.append( ( key, value ) )
    recorder = Recorder()
    monkeypatch.setattr( config_dep, "get_config_manager", lambda: recorder )
    _client().put( PUT_PATH, json={ "on": True } )
    assert recorder.sets == []


# ── who may flip it ──────────────────────────────────────────────────────────

def test_an_api_key_without_an_admin_login_is_refused_and_changes_nothing( ini, state_dir, no_settings, announced ):
    response = _client().put( PUT_PATH, json={ "on": True }, headers={ "X-API-Key": "a-managers-key" } )
    assert response.status_code == 403
    assert response.json()[ "detail" ] == "Only an administrator may change the skeleton crew switch."
    assert io.read_value_from_disk( str( ini ), sc.SKELETON_CREW_KEY ) == "false"
    assert announced == []


def test_a_signed_in_user_who_is_not_an_admin_is_refused( ini, state_dir, no_settings, announced ):
    response = _client( admin=False ).put( PUT_PATH, json={ "on": True } )
    assert response.status_code == 403
    assert io.read_value_from_disk( str( ini ), sc.SKELETON_CREW_KEY ) == "false"
    assert announced == []


def test_an_admin_token_with_an_api_key_is_allowed( ini, state_dir, no_settings, announced ):
    response = _client().put( PUT_PATH, json={ "on": True },
                              headers={ "X-API-Key": "k", "Authorization": "Bearer t" } )
    assert response.status_code == 200


def test_any_authenticated_caller_may_read( ini, state_dir, no_settings ):
    assert _client( admin=False ).get( GET_PATH ).status_code == 200


# ── refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "body", [ {}, { "on": "yes" }, { "on": 1 }, { "on": True, "extra": 1 }, [] ] )
def test_a_body_that_is_not_a_bare_boolean_is_a_422( ini, state_dir, no_settings, announced, body ):
    response = _client().put( PUT_PATH, json=body )
    assert response.status_code == 422
    assert announced == []
    assert io.read_value_from_disk( str( ini ), sc.SKELETON_CREW_KEY ) == "false"


def test_a_key_defined_twice_is_a_409_naming_the_lines_and_nothing_is_announced( ini, state_dir, no_settings, announced ):
    ini.write_text( BODY + "[Lupin: Testing]\ncc session skeleton crew enabled = false\n", encoding="utf-8" )
    response = _client().put( PUT_PATH, json={ "on": True } )
    assert response.status_code == 409
    assert "defined 2 times" in response.json()[ "detail" ]
    assert announced == []


def test_a_file_that_cannot_be_written_is_a_500_that_names_the_cause( ini, state_dir, no_settings, announced, monkeypatch ):
    def refuse( *args, **kwargs ):
        raise OSError( "read-only file system" )
    monkeypatch.setattr( io, "write_bool_to_disk", refuse )
    response = _client().put( PUT_PATH, json={ "on": True } )
    assert response.status_code == 500
    assert "read-only file system" in response.json()[ "detail" ]
    assert announced == []


def test_a_folder_that_cannot_hold_the_state_file_is_a_500( ini, no_settings, announced, tmp_path, monkeypatch ):
    blocker = tmp_path / "file"
    blocker.write_text( "x", encoding="utf-8" )
    monkeypatch.setenv( config_write_lock.LOCK_DIR_ENV, str( blocker / "inside" ) )
    response = _client().put( PUT_PATH, json={ "on": True } )
    assert response.status_code == 500
    assert io.read_value_from_disk( str( ini ), sc.SKELETON_CREW_KEY ) == "false"
    assert announced == []


# ── the announcement ─────────────────────────────────────────────────────────

class _FakeCommons:
    class BroadcastRequestBody:
        def __init__( self, message, require_ack ):
            self.message     = message
            self.require_ack = require_ack

    def __init__( self, raises=None ):
        self.posted = []
        self.raises = raises

    def get_notification_queue( self ):
        return "queue-from-main"

    async def post_broadcast_to_cc_sessions( self, body, authenticated_user_id, notification_queue ):
        if self.raises is not None:
            raise self.raises
        self.posted.append( ( body, authenticated_user_id, notification_queue ) )


@pytest.fixture
def commons( monkeypatch ):
    fake = _FakeCommons()
    import cosa.rest.routers as routers_pkg
    monkeypatch.setattr( routers_pkg, "commons", fake, raising=False )
    monkeypatch.setitem( sys.modules, "cosa.rest.routers.commons", fake )
    return fake


def test_the_on_announcement_tells_workers_to_finish_and_managers_to_reap( commons ):
    asyncio.run( arbiter._announce_flip( True, "rick", "queue" ) )
    body, user, queue = commons.posted[ 0 ]
    assert body.require_ack is True
    assert user == "rick" and queue == "queue"
    assert "Skeleton crew is ON" in body.message
    assert "finish your current step" in body.message
    assert "reap your workers" in body.message


def test_the_off_announcement_says_managers_may_spawn_inside_the_cap( commons ):
    asyncio.run( arbiter._announce_flip( False, "rick", "queue" ) )
    body = commons.posted[ 0 ][ 0 ]
    assert "Skeleton crew is OFF" in body.message
    assert "inside the cap" in body.message


def test_a_broadcast_that_fails_never_fails_the_flip( commons, capsys ):
    commons.raises = RuntimeError( "commons not initialized" )
    asyncio.run( arbiter._announce_flip( True, "rick", "queue" ) )
    assert "flip broadcast failed" in capsys.readouterr().out


def test_the_queue_is_resolved_from_the_app_when_none_is_given( commons ):
    asyncio.run( arbiter._announce_flip( True, "rick" ) )
    assert commons.posted[ 0 ][ 2 ] == "queue-from-main"


# ── the order of the two writes, and the file's mode ─────────────────────────

def test_the_attribution_record_is_written_before_the_configuration_file( ini, state_dir, no_settings, announced, monkeypatch ):
    def refuse( *args, **kwargs ):
        raise OSError( "disk full" )
    monkeypatch.setattr( io, "write_bool_to_disk", refuse )
    response = _client().put( PUT_PATH, json={ "on": True } )
    assert response.status_code == 500
    record = sc.read_state_file()
    assert record is not None and record[ "on" ] is True
    state = _client().get( GET_PATH ).json()[ "skeleton_crew" ]
    assert state[ "on" ] is False
    assert state[ "set_by" ] == "unknown (file edited)"


def test_a_flip_leaves_the_configuration_file_readable_by_everyone( ini, state_dir, no_settings, announced ):
    import stat
    ini.chmod( 0o600 )
    _client().put( PUT_PATH, json={ "on": True } )
    assert stat.S_IMODE( ini.stat().st_mode ) == 0o644
