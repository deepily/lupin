"""
The fleet switch for the heartbeat Stop poke (row 3526fb95): the file module, the
settings loader that obeys it, and the endpoint that flips it.

Rick's ruling: a plain on/off, admin role only, no timers.

Venue: :7999 (pure unit — tmp files and TestClient).
"""

import json
import os
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.auth_middleware import get_current_user
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers.heartbeat import router
from lupin_cli.claude_code.hooks.lib import heartbeat_poke_mute as pm
from lupin_cli.claude_code.hooks.lib import heartbeat_settings as hs


WHEN = datetime( 2026, 10, 2, 15, 0, 0, tzinfo=timezone.utc )


# ── where the file lives ─────────────────────────────────────────────────────

def test_path_prefers_the_explicit_file_then_the_settings_dir_then_the_fleet_root( monkeypatch, tmp_path ):
    monkeypatch.setenv( pm.MUTE_FILE_ENV, "/explicit/file.json" )
    monkeypatch.setenv( pm.SETTINGS_DIR_ENV, "/var/lupin/flow-ratio" )
    assert pm.poke_mute_path() == "/explicit/file.json"

    monkeypatch.delenv( pm.MUTE_FILE_ENV )
    assert pm.poke_mute_path() == "/var/lupin/flow-ratio/heartbeat-poke-mute.json"

    monkeypatch.delenv( pm.SETTINGS_DIR_ENV )
    monkeypatch.setattr( pm, "fleet_data_root", lambda: tmp_path / "projects-data" / "lupin" )
    assert pm.poke_mute_path() == str( tmp_path / "projects-data" / "lupin" / "flow-ratio" / "heartbeat-poke-mute.json" )


# ── reading: anything but a clean `muted: true` is not muted ─────────────────

@pytest.mark.parametrize( "content", [
    None,                              # no file at all
    "{ not json",
    "[ true ]",
    '{ "set_by": "rick" }',
    '{ "muted": "true" }',
    '{ "muted": 1 }',
] )
def test_a_missing_or_malformed_file_reads_as_not_muted( tmp_path, content ):
    path = tmp_path / "switch.json"
    if content is not None:
        path.write_text( content )
    assert pm.read_poke_mute( str( path ) ) == { "muted": False, "set_by": None, "set_at": None }


def test_read_defaults_to_the_resolved_path( tmp_path ):
    # the autouse conftest fixture points the switch at this test's tmp_path
    path = pm.poke_mute_path()
    assert path.startswith( str( tmp_path ) )
    assert pm.read_poke_mute()[ "muted" ] is False
    pm.write_poke_mute( True, "rick@example.com" )
    assert pm.read_poke_mute()[ "muted" ] is True
    assert os.path.isfile( path )


def test_write_then_read_round_trips_and_logs_each_flip( tmp_path ):
    path = str( tmp_path / "nested" / "switch.json" )

    on = pm.write_poke_mute( True, "rick@example.com", path=path, now=WHEN )
    assert on == { "muted": True, "set_by": "rick@example.com", "set_at": "2026-10-02T15:00:00+00:00" }
    assert pm.read_poke_mute( path ) == on

    off = pm.write_poke_mute( False, "maria@example.com", path=path, now=WHEN )
    assert off == { "muted": False, "set_by": "maria@example.com", "set_at": "2026-10-02T15:00:00+00:00" }

    lines = [ json.loads( l ) for l in ( tmp_path / "nested" / pm.AUDIT_FILENAME ).read_text().splitlines() ]
    assert lines == [
        { "ts": "2026-10-02T15:00:00+00:00", "set_by": "rick@example.com",  "old": False, "new": True },
        { "ts": "2026-10-02T15:00:00+00:00", "set_by": "maria@example.com", "old": True,  "new": False },
    ]
    leftovers = [ n for n in os.listdir( tmp_path / "nested" ) if n.endswith( ".tmp" ) ]
    assert leftovers == []


@pytest.mark.parametrize( "bad", [ "true", 1, None ] )
def test_write_refuses_a_non_boolean_and_writes_nothing( tmp_path, bad ):
    path = tmp_path / "switch.json"
    with pytest.raises( TypeError ):
        pm.write_poke_mute( bad, "rick", path=str( path ) )
    assert not path.exists()


def test_mute_message_names_who_and_when_and_survives_missing_fields():
    assert pm.mute_message( { "muted": True, "set_by": "rick", "set_at": "T" } ) == "Stop poke muted by rick at T."
    assert pm.mute_message( { "muted": True, "set_by": None, "set_at": None } ) == \
        "Stop poke muted by an admin at an unrecorded time."


# ── the settings loader obeys the switch ─────────────────────────────────────

@pytest.fixture
def settings_file( tmp_path, monkeypatch ):
    """A tmp ~/.claude/settings.json the loader reads; returns a writer for its heartbeat block."""
    home = tmp_path / "home"
    ( home / ".claude" ).mkdir( parents=True )
    monkeypatch.setattr( hs.os.path, "expanduser", lambda p: p.replace( "~", str( home ) ) )

    def write( block ):
        ( home / ".claude" / "settings.json" ).write_text( json.dumps( { "heartbeat": block } ) )
    return write


def test_loader_leaves_the_poke_on_when_the_switch_is_off_or_absent( settings_file ):
    settings_file( { "enabled": True, "poke_disabled_message": "hand message" } )
    assert hs.load_heartbeat_settings()[ "poke_output_enabled" ] is True

    pm.write_poke_mute( False, "rick" )
    loaded = hs.load_heartbeat_settings()
    assert loaded[ "poke_output_enabled" ] is True
    assert loaded[ "poke_disabled_message" ] == "hand message"


@pytest.mark.parametrize( "block_message, expected", [
    ( "You're on skeleton crew", "You're on skeleton crew" ),
    ( "",                        "Stop poke muted by rick@example.com at 2026-10-02T15:00:00+00:00." ),
    ( None,                      "Stop poke muted by rick@example.com at 2026-10-02T15:00:00+00:00." ),
] )
def test_loader_mutes_when_the_switch_is_on_and_keeps_the_operators_line( settings_file, block_message, expected ):
    settings_file( { "enabled": True, "poke_disabled_message": block_message } )
    pm.write_poke_mute( True, "rick@example.com", now=WHEN )

    loaded = hs.load_heartbeat_settings()

    assert loaded[ "poke_output_enabled" ] is False
    assert loaded[ "poke_disabled_message" ] == expected
    assert loaded[ "enabled" ] is True


def test_the_hand_switch_in_settings_json_still_mutes_and_keeps_its_own_message( settings_file ):
    settings_file( { "enabled": True, "poke_output_enabled": False, "poke_disabled_message": "hand message" } )
    pm.write_poke_mute( False, "rick" )

    loaded = hs.load_heartbeat_settings()

    assert loaded[ "poke_output_enabled" ] is False
    assert loaded[ "poke_disabled_message" ] == "hand message"


# ── the endpoint ─────────────────────────────────────────────────────────────

ADMIN = { "uid": "u-1", "email": "rick@example.com", "roles": [ "admin" ] }
PLAIN = { "uid": "u-2", "email": "guest@example.com", "roles": [ "user" ] }


def _client( user ):
    app = FastAPI()
    app.include_router( router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "u-any"
    if user is not None:
        app.dependency_overrides[ get_current_user ] = lambda: user
    return TestClient( app )


def test_get_reports_the_switch_and_changes_nothing():
    client = _client( None )
    assert client.get( "/api/heartbeat/poke-mute" ).json() == { "muted": False, "set_by": None, "set_at": None,
                                                                "source": "none" }
    assert not os.path.exists( pm.poke_mute_path() )


def test_admin_put_flips_it_and_the_hook_reader_agrees():
    client = _client( ADMIN )

    on = client.put( "/api/heartbeat/poke-mute", json={ "muted": True }, headers={ "Authorization": "Bearer t" } )
    assert on.status_code == 200
    assert on.json()[ "muted" ] is True and on.json()[ "set_by" ] == "rick@example.com"
    assert on.json()[ "source" ] == "file"
    assert pm.read_poke_mute() == { k: v for k, v in on.json().items() if k != "source" }
    assert client.get( "/api/heartbeat/poke-mute" ).json() == on.json()

    off = client.put( "/api/heartbeat/poke-mute", json={ "muted": False }, headers={ "Authorization": "Bearer t" } )
    assert off.status_code == 200 and off.json()[ "muted" ] is False
    assert pm.read_poke_mute()[ "muted" ] is False


def test_put_names_the_uid_when_the_token_has_no_email_and_unknown_when_neither():
    by_uid = _client( { "uid": "u-9", "roles": [ "admin" ] } ).put( "/api/heartbeat/poke-mute", json={ "muted": True } )
    assert by_uid.json()[ "set_by" ] == "u-9"
    nameless = _client( { "roles": [ "admin" ] } ).put( "/api/heartbeat/poke-mute", json={ "muted": True } )
    assert nameless.json()[ "set_by" ] == "unknown"


def test_a_signed_in_user_without_the_admin_role_gets_403_and_nothing_is_written():
    response = _client( PLAIN ).put( "/api/heartbeat/poke-mute", json={ "muted": True },
                                     headers={ "Authorization": "Bearer t" } )
    assert response.status_code == 403
    assert not os.path.exists( pm.poke_mute_path() )


def test_an_api_key_caller_gets_403_on_put_even_when_the_key_would_resolve_to_an_admin():
    response = _client( ADMIN ).put( "/api/heartbeat/poke-mute", json={ "muted": True },
                                     headers={ "X-API-Key": "ck_live_whatever" } )
    assert response.status_code == 403
    assert "may not change it" in response.json()[ "detail" ]
    assert not os.path.exists( pm.poke_mute_path() )


def test_no_credentials_at_all_gets_401_on_put():
    app = FastAPI()
    app.include_router( router )
    response = TestClient( app ).put( "/api/heartbeat/poke-mute", json={ "muted": True } )
    assert response.status_code == 401
    assert not os.path.exists( pm.poke_mute_path() )


@pytest.mark.parametrize( "body", [ { "muted": "true" }, { "muted": 1 }, {}, { "muted": None } ] )
def test_put_rejects_anything_but_a_json_boolean( body ):
    response = _client( ADMIN ).put( "/api/heartbeat/poke-mute", json=body, headers={ "Authorization": "Bearer t" } )
    assert response.status_code == 422
    assert not os.path.exists( pm.poke_mute_path() )
