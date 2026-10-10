#!/usr/bin/env python3
"""
Tests that skeleton crew mutes the Stop poke, through the one stored switch.

The operator ruled that the skeleton crew toggle does both jobs. The switch has one stored
value, the key in the main configuration file. The poke reads it at read time, so there is
no second copy to drift.

The poke is muted when any of three things says so. They are the hand switch in the
settings file, the fleet switch file that the poke mute button writes, and skeleton crew.
Nothing is retired. The mute button's route and file keep working. The route reports which
source muted.

The Stop hook is a fresh process per stop. It must stay quiet and fail open: a key that is
absent or unreadable never mutes, and nothing is printed.

Every test writes to tmp_path. The live configuration file is never touched.
"""
import json
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.auth_middleware import get_current_user
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers.heartbeat import router
from lupin_cli.claude_code.hooks.lib import heartbeat_poke_mute as pm
from lupin_cli.claude_code.hooks.lib import heartbeat_settings as hs
from lupin_mcp import skeleton_crew as sc


ADMIN = { "email": "rick@example.com", "roles": [ "admin" ] }


@pytest.fixture
def settings_file( tmp_path, monkeypatch ):
    home = tmp_path / "home"
    ( home / ".claude" ).mkdir( parents=True )
    monkeypatch.setattr( hs.os.path, "expanduser", lambda p: p.replace( "~", str( home ) ) )

    def write( block ):
        ( home / ".claude" / "settings.json" ).write_text( json.dumps( { "heartbeat": block } ) )
    return write


@pytest.fixture
def switch( tmp_path, monkeypatch ):
    path = tmp_path / "switch.ini"
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( path ) )

    def write( value ):
        if value is None:
            path.write_text( "[Lupin: Baseline]\nother = 1\n", encoding="utf-8" )
        else:
            path.write_text( f"[Lupin: Baseline]\n{sc.SKELETON_CREW_KEY} = {value}\n", encoding="utf-8" )
    write( "false" )
    return write


def _client():
    app = FastAPI()
    app.include_router( router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "u-any"
    app.dependency_overrides[ get_current_user ] = lambda: ADMIN
    return TestClient( app )


# ── the settings loader ──────────────────────────────────────────────────────

def test_skeleton_crew_on_mutes_the_poke_with_the_operators_line( settings_file, switch ):
    settings_file( { "enabled": True } )
    switch( "true" )
    loaded = hs.load_heartbeat_settings()
    assert loaded[ "poke_output_enabled" ] is False
    assert loaded[ "poke_disabled_message" ] == hs.SKELETON_CREW_POKE_MESSAGE
    assert "skeleton crew" in hs.SKELETON_CREW_POKE_MESSAGE.lower()


def test_the_settings_files_own_line_wins_over_the_skeleton_line( settings_file, switch ):
    settings_file( { "enabled": True, "poke_disabled_message": "hand message" } )
    switch( "true" )
    loaded = hs.load_heartbeat_settings()
    assert loaded[ "poke_output_enabled" ] is False
    assert loaded[ "poke_disabled_message" ] == "hand message"


def test_skeleton_crew_off_restores_the_poke( settings_file, switch ):
    settings_file( { "enabled": True } )
    switch( "false" )
    assert hs.load_heartbeat_settings()[ "poke_output_enabled" ] is True


def test_the_hand_switch_still_mutes_when_skeleton_crew_is_off( settings_file, switch ):
    settings_file( { "enabled": True, "poke_output_enabled": False } )
    switch( "false" )
    assert hs.load_heartbeat_settings()[ "poke_output_enabled" ] is False


def test_the_fleet_switch_file_still_mutes_when_skeleton_crew_is_off( settings_file, switch ):
    settings_file( { "enabled": True } )
    switch( "false" )
    pm.write_poke_mute( True, "rick@example.com" )
    loaded = hs.load_heartbeat_settings()
    assert loaded[ "poke_output_enabled" ] is False
    assert "rick@example.com" in loaded[ "poke_disabled_message" ]


def test_both_sources_muting_keeps_the_fleet_switch_line( settings_file, switch ):
    settings_file( { "enabled": True } )
    switch( "true" )
    pm.write_poke_mute( True, "rick@example.com" )
    loaded = hs.load_heartbeat_settings()
    assert loaded[ "poke_output_enabled" ] is False
    assert "rick@example.com" in loaded[ "poke_disabled_message" ]


def test_a_garbled_value_reads_as_on_and_an_absent_key_as_off( settings_file, switch ):
    settings_file( { "enabled": True } )
    switch( "maybe" )
    assert hs.load_heartbeat_settings()[ "poke_output_enabled" ] is False
    switch( None )
    assert hs.load_heartbeat_settings()[ "poke_output_enabled" ] is True


def test_the_hook_prints_nothing_when_the_key_is_absent( settings_file, switch, capsys ):
    settings_file( { "enabled": True } )
    switch( None )
    hs.load_heartbeat_settings()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_an_unreadable_configuration_file_never_mutes( settings_file, tmp_path, monkeypatch, capsys ):
    settings_file( { "enabled": True } )
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( tmp_path / "missing.ini" ) )
    assert hs.load_heartbeat_settings()[ "poke_output_enabled" ] is True
    assert capsys.readouterr().err == ""


def test_a_hook_whose_settings_file_is_missing_is_not_asked_about_the_switch( tmp_path, monkeypatch ):
    monkeypatch.setattr( hs.os.path, "expanduser", lambda p: p.replace( "~", str( tmp_path / "nohome" ) ) )
    assert hs.load_heartbeat_settings()[ "enabled" ] is False


# ── the route keeps working and says which source muted ──────────────────────

@pytest.mark.parametrize( "skeleton, file_muted, muted, source", [
    ( "false", False, False, "none" ),
    ( "false", True,  True,  "file" ),
    ( "true",  False, True,  "skeleton_crew" ),
    ( "true",  True,  True,  "both" ),
] )
def test_the_read_reports_the_derived_state_and_its_source( switch, skeleton, file_muted, muted, source ):
    switch( skeleton )
    if file_muted:
        pm.write_poke_mute( True, "rick@example.com" )
    body = _client().get( "/api/heartbeat/poke-mute" ).json()
    assert body[ "muted" ] is muted
    assert body[ "source" ] == source


def test_the_old_flip_still_writes_the_file_while_skeleton_crew_is_on( switch ):
    switch( "true" )
    response = _client().put( "/api/heartbeat/poke-mute", json={ "muted": False },
                              headers={ "Authorization": "Bearer t" } )
    assert response.status_code == 200
    assert pm.read_poke_mute()[ "muted" ] is False
    assert response.json()[ "muted" ] is True
    assert response.json()[ "source" ] == "skeleton_crew"


def test_the_old_flip_on_with_skeleton_crew_off_reports_the_file_as_source( switch ):
    switch( "false" )
    response = _client().put( "/api/heartbeat/poke-mute", json={ "muted": True },
                              headers={ "Authorization": "Bearer t" } )
    assert response.json()[ "source" ] == "file"
    assert pm.read_poke_mute()[ "muted" ] is True
