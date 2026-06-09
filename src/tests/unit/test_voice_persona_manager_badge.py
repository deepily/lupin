"""
Unit — _resolve_manager_persona (focus-bar manager badge server resolver, Rick 2026-06-08).

A worker's bridge carries `spawned_by` = the MANAGER's session_id (set by
session_spawner). The resolver reads it, looks up the manager's voice_persona, and
shapes a compact { icon, color, name, initial } badge dict for the
voice_persona_assigned event payload. Returns None for root sessions / any failure.

Venue: :7999 (pure unit, no server, no state).
"""

import json

import pytest

from cosa.rest.routers import voice_persona


def _write_bridge( tmp_path, data ):
    p = tmp_path / "cc-bridge.json"
    p.write_text( json.dumps( data ) )
    return str( p )


def test_resolves_manager_persona_when_spawned_by_present( tmp_path, monkeypatch ):
    bridge = _write_bridge( tmp_path, { "spawned_by": "mgr-sess-1" } )
    monkeypatch.setattr( voice_persona, "find_session_path_by_id", lambda sid: bridge )
    monkeypatch.setattr( voice_persona, "get_voice_persona",
                         lambda sid: { "name": "Tiberius", "icon": "👑", "color": "#3F51B5" } )

    result = voice_persona._resolve_manager_persona( "worker-1" )

    assert result == { "icon": "👑", "color": "#3F51B5", "name": "Tiberius", "initial": "T" }


def test_returns_none_when_no_spawned_by( tmp_path, monkeypatch ):
    bridge = _write_bridge( tmp_path, { "voice_persona": { "name": "Rio" } } )   # root: no spawned_by
    monkeypatch.setattr( voice_persona, "find_session_path_by_id", lambda sid: bridge )
    assert voice_persona._resolve_manager_persona( "root-1" ) is None


def test_returns_none_when_worker_bridge_missing( monkeypatch ):
    monkeypatch.setattr( voice_persona, "find_session_path_by_id", lambda sid: None )
    assert voice_persona._resolve_manager_persona( "ghost" ) is None


def test_returns_none_when_manager_persona_unresolvable( tmp_path, monkeypatch ):
    bridge = _write_bridge( tmp_path, { "spawned_by": "mgr-x" } )
    monkeypatch.setattr( voice_persona, "find_session_path_by_id", lambda sid: bridge )
    monkeypatch.setattr( voice_persona, "get_voice_persona", lambda sid: None )
    assert voice_persona._resolve_manager_persona( "worker-2" ) is None


def test_returns_none_when_manager_persona_empty_dict( tmp_path, monkeypatch ):
    bridge = _write_bridge( tmp_path, { "spawned_by": "mgr-x" } )
    monkeypatch.setattr( voice_persona, "find_session_path_by_id", lambda sid: bridge )
    monkeypatch.setattr( voice_persona, "get_voice_persona", lambda sid: {} )
    assert voice_persona._resolve_manager_persona( "worker-3" ) is None


def test_initial_empty_when_manager_name_missing( tmp_path, monkeypatch ):
    bridge = _write_bridge( tmp_path, { "spawned_by": "mgr-y" } )
    monkeypatch.setattr( voice_persona, "find_session_path_by_id", lambda sid: bridge )
    monkeypatch.setattr( voice_persona, "get_voice_persona",
                         lambda sid: { "icon": "🎙️", "color": "#888" } )           # no name
    result = voice_persona._resolve_manager_persona( "worker-4" )
    assert result == { "icon": "🎙️", "color": "#888", "name": "", "initial": "" }


def test_returns_none_on_bad_bridge_json( tmp_path, monkeypatch ):
    p = tmp_path / "bad.json"
    p.write_text( "{ not valid json" )
    monkeypatch.setattr( voice_persona, "find_session_path_by_id", lambda sid: str( p ) )
    assert voice_persona._resolve_manager_persona( "worker-5" ) is None


# ── _manager_persona_for_sender_id (senders-visible HYDRATION helper) ──────────
# Fixes the cold-reload gap (Rick 2026-06-08): a force-refreshed page must hydrate the
# manager badge for EXISTING workers (e.g. Cheech), not wait for the next live event.
# Resolves a sender_id by extracting its #-suffix session prefix and delegating to
# _resolve_manager_persona.

from cosa.rest.routers import notifications as _notif


class TestManagerPersonaForSenderId:

    def test_resolves_via_sender_id_suffix( self, monkeypatch ):
        monkeypatch.setattr(
            _notif, "_resolve_manager_persona",
            lambda sid: { "icon": "👑", "color": "#3F51B5", "name": "Tiberius", "initial": "T" }
                        if sid == "5e9bf4b7" else None,
        )
        result = _notif._manager_persona_for_sender_id( "claude.code@lupin.deepily.ai#5e9bf4b7" )
        assert result == { "icon": "👑", "color": "#3F51B5", "name": "Tiberius", "initial": "T" }

    def test_none_without_hash_suffix( self, monkeypatch ):
        monkeypatch.setattr( _notif, "_resolve_manager_persona", lambda sid: { "x": 1 } )
        assert _notif._manager_persona_for_sender_id( "claude.code@lupin.deepily.ai" ) is None

    def test_none_on_empty_suffix( self, monkeypatch ):
        monkeypatch.setattr( _notif, "_resolve_manager_persona", lambda sid: { "x": 1 } )
        assert _notif._manager_persona_for_sender_id( "claude.code@lupin.deepily.ai#" ) is None

    def test_none_when_resolver_unavailable( self, monkeypatch ):
        monkeypatch.setattr( _notif, "_resolve_manager_persona", None )
        assert _notif._manager_persona_for_sender_id( "a.b@c.deepily.ai#abc12345" ) is None

    def test_none_when_resolver_raises( self, monkeypatch ):
        def boom( sid ):
            raise RuntimeError( "bridge fail" )
        monkeypatch.setattr( _notif, "_resolve_manager_persona", boom )
        assert _notif._manager_persona_for_sender_id( "a.b@c.deepily.ai#abc12345" ) is None


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
