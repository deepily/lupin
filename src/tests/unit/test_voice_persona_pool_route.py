#!/usr/bin/env python3
"""
Unit — GET /api/cosa-voice/voice-persona/pool serialization contract.

The pool diagnostics endpoint builds `active_sessions` entries from the
(bridge_path, session_id, persona) tuples returned by
`find_active_voice_persona_sessions`. The bridge persona dict carries an
`assigned_at` ISO-8601 UTC timestamp (stamped at allocation by
voice_persona_helpers), but the route historically dropped it during
serialization — mobile's AC-D4 wire-contract test pins a NON-NULL
`assigned_at` per active session, so the omission broke the fixture.

These tests pin the serialized entry shape:
    { session_id, persona_name, borrowed, assigned_at }

Venue: :7999 (pure unit, no server, no state — endpoint called directly
with monkeypatched helpers).
"""

import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.routers import voice_persona


POOL_2 = [
    { "name": "Rachel",   "voice_id": "v-rachel",   "icon": "🕊️", "color": "#FFD54F", "profile": "Calm female" },
    { "name": "Tiberius", "voice_id": "v-tiberius", "icon": "👑", "color": "#3F51B5", "profile": "Regal male"  },
]


class _FakeConfigMgr:
    """Minimal ConfigurationManager stand-in for the pool route's single .get call."""

    def get( self, key, default=None, return_type=None, silent=False ):
        return default


def _active_tuple( session_id, persona ):
    return ( f"/tmp/cc-{session_id}.json", session_id, persona )


async def _call_pool_endpoint( monkeypatch, active ):
    monkeypatch.setattr( voice_persona, "load_persona_pool_from_config",      lambda cm: POOL_2 )
    monkeypatch.setattr( voice_persona, "find_active_voice_persona_sessions", lambda stale_threshold_seconds: active )
    response = await voice_persona.get_voice_persona_pool(
        authenticated_user_id = "test-user",
        config_mgr            = _FakeConfigMgr()
    )
    return json.loads( response.body )


class TestPoolRouteActiveSessionsSerialization:

    @pytest.mark.asyncio
    async def test_assigned_at_is_serialized_and_non_null( self, monkeypatch ):
        active = [
            _active_tuple( "sess-1", {
                "name"        : "Rachel",
                "voice_id"    : "v-rachel",
                "borrowed"    : False,
                "assigned_at" : "2026-06-12T04:23:23+00:00"
            } )
        ]
        body  = await _call_pool_endpoint( monkeypatch, active )
        entry = body[ "active_sessions" ][ 0 ]

        assert "assigned_at" in entry
        assert entry[ "assigned_at" ] is not None
        assert entry[ "assigned_at" ] == "2026-06-12T04:23:23+00:00"

    @pytest.mark.asyncio
    async def test_entry_shape_pins_all_four_fields( self, monkeypatch ):
        active = [
            _active_tuple( "sess-2", {
                "name"        : "Tiberius",
                "borrowed"    : True,
                "assigned_at" : "2026-06-11T22:00:00+00:00"
            } )
        ]
        body  = await _call_pool_endpoint( monkeypatch, active )
        entry = body[ "active_sessions" ][ 0 ]

        assert entry == {
            "session_id"   : "sess-2",
            "persona_name" : "Tiberius",
            "borrowed"     : True,
            "assigned_at"  : "2026-06-11T22:00:00+00:00"
        }

    @pytest.mark.asyncio
    async def test_legacy_bridge_without_assigned_at_serializes_null( self, monkeypatch ):
        # Pre-feature bridge personas lack the stamp — the key must still be
        # present (stable wire shape) with an explicit null, never absent.
        active = [ _active_tuple( "sess-3", { "name": "Rachel" } ) ]
        body   = await _call_pool_endpoint( monkeypatch, active )
        entry  = body[ "active_sessions" ][ 0 ]

        assert "assigned_at" in entry
        assert entry[ "assigned_at" ] is None

    @pytest.mark.asyncio
    async def test_occupied_and_free_names_unaffected( self, monkeypatch ):
        active = [
            _active_tuple( "sess-4", {
                "name"        : "Rachel",
                "assigned_at" : "2026-06-12T01:00:00+00:00"
            } )
        ]
        body = await _call_pool_endpoint( monkeypatch, active )

        assert body[ "occupied_names" ] == [ "Rachel" ]
        assert body[ "free_names" ]     == [ "Tiberius" ]
        assert body[ "pool" ]           == POOL_2

    @pytest.mark.asyncio
    async def test_non_dict_persona_rows_are_skipped( self, monkeypatch ):
        active = [
            _active_tuple( "sess-5", None ),
            _active_tuple( "sess-6", {
                "name"        : "Tiberius",
                "assigned_at" : "2026-06-12T02:00:00+00:00"
            } )
        ]
        body = await _call_pool_endpoint( monkeypatch, active )

        assert len( body[ "active_sessions" ] ) == 1
        assert body[ "active_sessions" ][ 0 ][ "session_id" ] == "sess-6"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
