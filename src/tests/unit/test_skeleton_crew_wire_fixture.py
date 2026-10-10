#!/usr/bin/env python3
"""
The committed skeleton crew wire fixture is a response the real route gave.

The two web clients paint from a JSON body that the arbiter router builds. The TypeScript
tests read the committed file in src/tests/fixtures/skeleton_crew_wire/. Their input is a
captured body, not a shape typed from the design note.

This test re-captures the same bodies from the real handlers on a temporary configuration
file and compares them with the committed file. A change to the route that moves a field
fails here. Regenerate the fixture with LUPIN_REGEN_WIRE_FIXTURE=1.

The time stamp in `since` is replaced by the word "set" before the comparison, since it
differs on every run.
"""
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.auth_middleware import require_admin
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import arbiter
from lupin_mcp import config_write_lock
from lupin_mcp import skeleton_crew as sc


GET_PATH = "/api/arbiter/fleet-size-cap"
PUT_PATH = "/api/arbiter/skeleton-crew"
FIXTURE  = Path( os.environ[ "LUPIN_ROOT" ] ) / "src/tests/fixtures/skeleton_crew_wire/responses.json"

BODY = """\
[Lupin: Baseline]
cc session fleet size cap                        = 8
cc session fleet size cap maximum                = 18
cc session skeleton crew enabled                 = false
"""


@pytest.fixture
def world( tmp_path, monkeypatch ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( BODY, encoding="utf-8" )
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( path ) )
    monkeypatch.setenv( config_write_lock.LOCK_DIR_ENV, str( tmp_path / "flow" ) )
    from lupin_mcp import fleet_size_cap
    monkeypatch.setattr( fleet_size_cap, "config_file_path", lambda: str( path ) )

    async def silent( on, user_id, notification_queue ):
        return None
    monkeypatch.setattr( arbiter, "_announce_flip", silent )
    return tmp_path


def _client():
    app = FastAPI()
    app.include_router( arbiter.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    app.dependency_overrides[ require_admin ] = lambda: { "email": "rick@example.com" }
    return TestClient( app )


def _settings( tmp_path, monkeypatch, payload ):
    path = tmp_path / "settings.json"
    path.write_text( json.dumps( payload ), encoding="utf-8" )
    monkeypatch.setenv( sc.SETTINGS_ENV, str( path ) )


def _capture( world, monkeypatch ):
    """Return { name: { "status": int, "body": dict } } from the real handlers."""
    out = { }

    def record( name, response ):
        out[ name ] = { "status": response.status_code, "body": response.json() }

    _settings( world, monkeypatch, { "heartbeat": { "enabled": True, "poke_output_enabled": True } } )
    record( "get_never_flipped", _client().get( GET_PATH ) )
    record( "put_on", _client().put( PUT_PATH, json={ "on": True } ) )
    record( "put_refused_for_an_api_key", _client().put(
        PUT_PATH, json={ "on": False }, headers={ "X-API-Key": "a-managers-key" } ) )

    _settings( world, monkeypatch, { "heartbeat": { "enabled": True, "poke_output_enabled": False } } )
    record( "put_off_while_settings_mute_is_set", _client().put( PUT_PATH, json={ "on": False } ) )

    bad = world / "settings.json"
    bad.write_text( "{not json", encoding="utf-8" )
    record( "get_settings_file_unreadable", _client().get( GET_PATH ) )
    return out


def _normalised( captured ):
    text = json.dumps( captured )
    data = json.loads( text )
    for entry in data.values():
        crew = entry[ "body" ].get( "skeleton_crew" ) if isinstance( entry[ "body" ], dict ) else None
        if crew and crew.get( "since" ): crew[ "since" ] = "set"
    return data


def test_the_committed_fixture_is_what_the_real_route_answers( world, monkeypatch ):
    captured = _capture( world, monkeypatch )
    assert captured[ "put_on" ][ "status" ] == 200
    assert captured[ "put_refused_for_an_api_key" ][ "status" ] == 403

    if os.environ.get( "LUPIN_REGEN_WIRE_FIXTURE" ) == "1":
        FIXTURE.parent.mkdir( parents=True, exist_ok=True )
        FIXTURE.write_text( json.dumps( captured, indent=2, ensure_ascii=False ) + "\n", encoding="utf-8" )

    committed = json.loads( FIXTURE.read_text( encoding="utf-8" ) )
    assert _normalised( committed ) == _normalised( captured )


def test_the_fixture_carries_the_cases_the_clients_paint( ):
    committed = json.loads( FIXTURE.read_text( encoding="utf-8" ) )
    crew = { name: entry[ "body" ][ "skeleton_crew" ] for name, entry in committed.items()
             if "skeleton_crew" in entry[ "body" ] }
    assert crew[ "put_on" ][ "on" ] is True
    assert crew[ "put_off_while_settings_mute_is_set" ][ "settings_mute_while_off" ] is True
    assert crew[ "get_settings_file_unreadable" ][ "settings_mute_while_off" ] is None
