#!/usr/bin/env python3
"""
Both session-topic writers go through atomic_write_json, so the bridge is never torn.

Store ids 767d7ad9-ace0-4773-bd97-727f22047f79 and 0f25b871-48cb-4866-ac69-7ca854e9ce0d, one defect.
`set_session_topic` in the MCP server and `CCNotificationListener._update_session_topic` read the
bridge file, then reopened it for writing, which truncates it first. A reader between the truncate
and the write saw an empty file, and two writers could splice one. Every other bridge setter writes
through `session_bridge.atomic_write_json`.

Seams driven for real: both writers against a real bridge file, and the real atomic_write_json.
Faked: the UI push, and the metadata lookup that names the bridge path.
"""

import builtins
import json

import pytest

import lupin_mcp.cosa_voice_mcp as cv
from lupin_cli.claude_code.hooks.lib import session_bridge
from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener


def _bridge( tmp_path ):
    """Ensures: returns a real bridge file holding a session id and a persona."""
    p = tmp_path / "cc-bridge.json"
    p.write_text( json.dumps( { "session_id": "abcd1234", "voice_persona": { "name": "sam" } } ) )
    return p


def _listener():
    """Ensures: returns a listener that needs no tmux lookup, bridge lookup or WebSocket."""
    return CCNotificationListener(
        email="service@lupin.deepily.ai", password="service-pass", session_id_hash="abc12345",
        tmux_session="test tmux", host="localhost", port=7999, debug=False, verbose=False )


@pytest.fixture
def opens_for_write( monkeypatch ):
    """Ensures: yields a function listing the paths opened for writing since the fixture began."""
    seen, real_open = [], builtins.open

    def watching( file, mode="r", *args, **kwargs ):
        if any( c in mode for c in "wax+" ): seen.append( str( file ) )
        return real_open( file, mode, *args, **kwargs )

    monkeypatch.setattr( builtins, "open", watching )
    return lambda: list( seen )


def _write_mcp_topic( bridge, monkeypatch, topic="a topic" ):
    monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "_bridge_path": str( bridge ) } )
    monkeypatch.setattr( cv, "_notify_impl", lambda **k: "sent" )
    return cv.set_session_topic.fn( topic )


def _write_listener_topic( bridge, monkeypatch, topic="a topic" ):
    monkeypatch.setattr( session_bridge, "get_session_metadata", lambda: { "_bridge_path": str( bridge ) } )
    _listener()._update_session_topic( topic )


# =============================================================================
# The MCP writer
# =============================================================================

def test_the_MCP_writer_never_opens_the_bridge_itself_for_writing( tmp_path, monkeypatch, opens_for_write ):
    bridge = _bridge( tmp_path )
    _write_mcp_topic( bridge, monkeypatch )
    assert str( bridge ) not in opens_for_write(), "a plain open( path, 'w' ) truncates the bridge before it is rewritten"


def test_the_MCP_writer_goes_through_atomic_write_json_and_keeps_the_other_keys( tmp_path, monkeypatch ):
    bridge, calls = _bridge( tmp_path ), []
    real = session_bridge.atomic_write_json
    monkeypatch.setattr( cv, "atomic_write_json", lambda path, data: calls.append( ( str( path ), dict( data ) ) ) or real( path, data ), raising=False )

    got = _write_mcp_topic( bridge, monkeypatch, "Bug Fix: WS queue crash" )

    assert got[ "status" ] == "ok"
    assert [ c[ 0 ] for c in calls ] == [ str( bridge ) ]
    assert calls[ 0 ][ 1 ][ "session_topic" ] == "Bug Fix: WS queue crash"
    on_disk = json.loads( bridge.read_text() )
    assert on_disk[ "session_topic" ] == "Bug Fix: WS queue crash"
    assert on_disk[ "voice_persona" ] == { "name": "sam" }


def test_the_MCP_writer_reports_an_error_and_pushes_nothing_when_the_bridge_write_fails( tmp_path, monkeypatch ):
    bridge, pushed = _bridge( tmp_path ), []
    monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "_bridge_path": str( bridge ) } )
    monkeypatch.setattr( cv, "_notify_impl", lambda **k: pushed.append( k ) or "sent" )
    monkeypatch.setattr( cv, "atomic_write_json", lambda path, data: False, raising=False )

    got = cv.set_session_topic.fn( "a topic" )

    assert got[ "status" ] == "error"
    assert str( bridge ) in got[ "reason" ]
    assert pushed == [], "the focus bar must not show a topic the bridge does not hold"
    assert "session_topic" not in json.loads( bridge.read_text() )


# =============================================================================
# The listener writer
# =============================================================================

def test_the_listener_writer_never_opens_the_bridge_itself_for_writing( tmp_path, monkeypatch, opens_for_write ):
    bridge = _bridge( tmp_path )
    _write_listener_topic( bridge, monkeypatch )
    assert str( bridge ) not in opens_for_write()


def test_the_listener_writer_goes_through_atomic_write_json_and_keeps_the_other_keys( tmp_path, monkeypatch ):
    bridge, calls = _bridge( tmp_path ), []
    real = session_bridge.atomic_write_json
    monkeypatch.setattr( session_bridge, "atomic_write_json", lambda path, data: calls.append( ( str( path ), dict( data ) ) ) or real( path, data ) )

    _write_listener_topic( bridge, monkeypatch, "My New Topic" )

    assert [ c[ 0 ] for c in calls ] == [ str( bridge ) ]
    on_disk = json.loads( bridge.read_text() )
    assert on_disk[ "session_topic" ] == "My New Topic"
    assert on_disk[ "voice_persona" ] == { "name": "sam" }


def test_the_listener_writer_logs_a_failure_and_not_a_success_when_the_bridge_write_fails( tmp_path, monkeypatch ):
    bridge, lines = _bridge( tmp_path ), []
    monkeypatch.setattr( session_bridge, "get_session_metadata", lambda: { "_bridge_path": str( bridge ) } )
    monkeypatch.setattr( session_bridge, "atomic_write_json", lambda path, data: False )
    listener      = _listener()
    listener._log = lambda message, *a, **k: lines.append( str( message ) )

    listener._update_session_topic( "a topic" )

    assert any( "Failed to set session topic" in m for m in lines )
    assert not any( "Session topic set" in m for m in lines )
