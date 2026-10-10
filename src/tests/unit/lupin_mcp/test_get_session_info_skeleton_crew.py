"""
Tests that get_session_info tells a manager whether skeleton crew is on.

A manager must be able to read the switch without asking the operator, and the answer has to
survive a context clear. Session info is the first call every session makes, so the state
rides there.

The field is read fresh from the configuration file on every call, so a flip shows up with
no restart. It is present even when the session bridge cannot be read. When the state
cannot be read at all the field is None, and a manager must read None as unknown and not as
off.

Venue: no server, no network. The switch file is a file in tmp_path.
"""
import pytest

import lupin_mcp.cosa_voice_mcp as cv
from lupin_mcp import skeleton_crew as sc


def _write( path, value ):
    path.write_text( f"[Lupin: Baseline]\n{sc.SKELETON_CREW_KEY} = {value}\n", encoding="utf-8" )


@pytest.fixture
def switch( tmp_path, monkeypatch ):
    path = tmp_path / "switch.ini"
    _write( path, "false" )
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( path ) )
    monkeypatch.setenv( sc.SETTINGS_ENV, str( tmp_path / "no-settings.json" ) )
    return path


def test_the_field_reports_the_state_and_follows_a_flip_without_a_restart( switch ):
    assert cv.get_session_info.fn()[ "skeleton_crew" ][ "on" ] is False
    _write( switch, "true" )
    assert cv.get_session_info.fn()[ "skeleton_crew" ][ "on" ] is True


def test_the_field_carries_the_attribution_keys( switch ):
    assert sorted( cv.get_session_info.fn()[ "skeleton_crew" ] ) == [
        "on", "set_by", "settings_mute_while_off", "since" ]


def test_the_field_is_present_when_the_session_bridge_cannot_be_read( switch, monkeypatch ):
    def boom():
        raise RuntimeError( "no bridge" )
    monkeypatch.setattr( cv, "_get_cc_metadata", boom )
    assert cv.get_session_info.fn()[ "skeleton_crew" ][ "on" ] is False


def test_an_unreadable_state_is_none_and_never_breaks_session_info( switch, monkeypatch ):
    def boom():
        raise RuntimeError( "state unreadable" )
    monkeypatch.setattr( sc, "describe", boom )
    info = cv.get_session_info.fn()
    assert info[ "skeleton_crew" ] is None
    assert info[ "project" ] == cv.PROJECT
