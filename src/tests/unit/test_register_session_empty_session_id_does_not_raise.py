"""
`register_session.main()` with a payload that has no session_id must finish, not raise.

Before the fix, the listener-spawn step read `stable_session_id`, which is only assigned inside `if session_id:`.
An empty or missing session_id therefore died with UnboundLocalError after printing its
"no session bridge written" warning, and the final `emit_json( {} )` never ran.

Hermetic: `$HOME` and the bridge seam point into tmp_path; every network or process call is a stand-in.
"""

import importlib

import pytest

HOOK = "lupin_cli.claude_code.hooks.register_session"
BRIDGE_MOD = "lupin_cli.claude_code.hooks.lib.session_bridge"


@pytest.fixture
def driven( monkeypatch, tmp_path ):
    module = importlib.import_module( HOOK )
    seam   = tmp_path / "seam"; seam.mkdir()
    monkeypatch.setenv( "HOME", str( tmp_path ) )
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( seam ) )
    emitted = [ ]
    monkeypatch.setattr( module, "emit_json", emitted.append )
    monkeypatch.setattr( module, "emit_context_clear_marker", lambda payload: None )
    monkeypatch.setattr( module, "send_tts", lambda *a, **k: None )
    monkeypatch.setattr( module, "log_payload", lambda *a, **k: None )
    monkeypatch.setattr( module, "_spawn_listener", lambda *a, **k: None )
    monkeypatch.setattr( f"{BRIDGE_MOD}.prune_dead_persona_bridges", lambda: 0 )
    return module, seam, emitted


@pytest.mark.parametrize( "payload", [ { "cwd": "/tmp" }, { "session_id": "", "cwd": "/tmp" }, { "session_id": None } ] )
def test_a_payload_with_no_session_id_finishes_with_an_empty_response_and_no_bridge( driven, monkeypatch, payload ):
    module, seam, emitted = driven
    monkeypatch.setattr( module, "read_hook_input", lambda: payload )
    module.main()                                                  # must not raise UnboundLocalError
    assert emitted == [ { } ]
    assert not list( seam.glob( "cc-*.json" ) )


def test_no_listener_is_started_for_a_payload_with_no_session_id( driven, monkeypatch ):
    module, _seam, _emitted = driven
    spawned = [ ]
    monkeypatch.setattr( module, "_spawn_listener", lambda *a, **k: spawned.append( a ) )
    monkeypatch.setattr( module, "read_hook_input", lambda: { "cwd": "/tmp" } )
    module.main()
    assert [ a[ 0 ] for a in spawned ] == [ "" ]                   # asked once, with the empty id (_spawn_listener refuses it)
