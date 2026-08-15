#!/usr/bin/env python3
"""
Unit tests for the requested-persona allocation feature.

Covers:
    - voice_persona_helpers._find_persona_in_pool
    - voice_persona_helpers.pick_requested_persona
    - voice_persona_helpers.allocate_requested_persona_for_session
    - routers/voice_persona.allocate_voice_persona_endpoint (request branch)

Feature shape per Rachel's 2026-05-19 R1 design (commons DM `3139380d`):
    POST /api/cosa-voice/voice-persona/{sid}/allocate?requested_persona_name=<name>

    - Name matches existing → idempotent return (newly_allocated=False, swapped=False)
    - Name differs from existing → atomic swap (newly_allocated=True, swapped=True)
    - Name not in pool → 422 with available list in body.detail
    - Name occupied by another session → 409 with holding info + available in body.detail
    - No request param → existing random-allocate behavior preserved

Also covers the STRICT ordered-fallback `persona_chain` query param (2026-06-11
replacement for the retired soft-preference `preferred_persona_name`):

    POST /api/cosa-voice/voice-persona/{sid}/allocate?persona_chain=<name,...[,*]>

    See TestPersonaChainQueryParam and
    src/rnd/v0.1.8/2026.06.11-multi-manager-env-var-and-persona-preference-transport-fix.md
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi          import FastAPI
from fastapi.testclient import TestClient


# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.voice_persona_helpers import (
    _find_persona_in_pool,
    pick_requested_persona,
    allocate_requested_persona_for_session,
    pick_persona_chain_from_env
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

POOL_6 = [
    { "name": "maria",    "voice_id": "v_maria",    "icon": "🌸", "color": "#E91E63", "profile": "warm female"        },
    { "name": "mr radio", "voice_id": "v_mrnpr",    "icon": "🦉", "color": "#FFA000", "profile": "authoritative male" },
    { "name": "Rachel",   "voice_id": "v_rachel",   "icon": "🕊️", "color": "#4CAF50", "profile": "calm female"        },
    { "name": "Tiberius", "voice_id": "v_tiberius", "icon": "🌑", "color": "#3F51B5", "profile": "deep male"          },
    { "name": "Rio",      "voice_id": "v_domi",     "icon": "⚡", "color": "#C2185B", "profile": "young female"       },
    { "name": "Arnold",   "voice_id": "v_arnold",   "icon": "🪨", "color": "#C62828", "profile": "gravelly male"      }
]


# ── _find_persona_in_pool ────────────────────────────────────────────────────

class TestFindPersonaInPool:

    def test_exact_match_by_key( self ):
        match = _find_persona_in_pool( POOL_6, "Rachel" )
        assert match is not None
        assert match[ "name" ] == "Rachel"

    def test_case_insensitive_match( self ):
        match = _find_persona_in_pool( POOL_6, "RACHEL" )
        assert match is not None and match[ "name" ] == "Rachel"

    def test_lowercase_match( self ):
        match = _find_persona_in_pool( POOL_6, "tiberius" )
        assert match is not None and match[ "name" ] == "Tiberius"

    def test_match_via_display_name_overrides( self ):
        # "maria" key → display "María" — both forms should match
        match = _find_persona_in_pool( POOL_6, "María" )
        assert match is not None and match[ "name" ] == "maria"

    def test_match_via_display_name_with_period( self ):
        # "mr radio" key → display "Mr. Radio"
        match = _find_persona_in_pool( POOL_6, "Mr. Radio" )
        assert match is not None and match[ "name" ] == "mr radio"

    def test_match_is_canonical_key_consistent( self ):
        # Phase 2: the lookup now matches by canonical_persona_key on BOTH the
        # pool-key and display-name branches, so an accented/punctuated request
        # resolves to the same pool entry as its bare pool-key form. (The display
        # branch was already accent-tolerant via the override; this pins that the
        # canonical route preserves every prior match.)
        for needle in ( "maria", "María", "MARÍA", "mr radio", "Mr. Radio", "MR. RADIO" ):
            match = _find_persona_in_pool( POOL_6, needle )
            assert match is not None, needle
            assert match[ "name" ] in ( "maria", "mr radio" ), needle

    def test_whitespace_stripped( self ):
        match = _find_persona_in_pool( POOL_6, "  arnold  " )
        assert match is not None and match[ "name" ] == "Arnold"

    def test_unknown_name_returns_none( self ):
        assert _find_persona_in_pool( POOL_6, "NotAPersona" ) is None

    def test_empty_string_returns_none( self ):
        assert _find_persona_in_pool( POOL_6, "" )    is None

    def test_whitespace_only_returns_none( self ):
        assert _find_persona_in_pool( POOL_6, "   " ) is None

    def test_none_returns_none( self ):
        assert _find_persona_in_pool( POOL_6, None )  is None

    def test_empty_pool_returns_none( self ):
        assert _find_persona_in_pool( [], "Rachel" ) is None


# ── pick_requested_persona ───────────────────────────────────────────────────

class TestPickRequestedPersona:

    def test_ok_when_unoccupied( self ):
        result = pick_requested_persona( POOL_6, {}, "Rachel" )
        assert result[ "status" ]              == "ok"
        assert result[ "persona" ][ "name" ]   == "Rachel"
        assert result[ "persona" ][ "borrowed" ] is False
        assert result[ "persona" ][ "voice_id" ] == "v_rachel"
        # available list is the full pool when nothing's occupied
        assert sorted( result[ "available" ] ) == sorted( [ p[ "name" ] for p in POOL_6 ] )

    def test_ok_returns_fresh_dict_not_alias( self ):
        # Mutating the returned persona must NOT alter the pool entry
        result = pick_requested_persona( POOL_6, {}, "Rachel" )
        result[ "persona" ][ "name" ] = "MUTATED"
        # Pool entry should still be "Rachel"
        rachel = [ p for p in POOL_6 if p[ "name" ] == "Rachel" ][ 0 ]
        assert rachel[ "name" ] == "Rachel"

    def test_not_in_pool_status( self ):
        result = pick_requested_persona( POOL_6, {}, "Bogus" )
        assert result[ "status" ]  == "not_in_pool"
        assert result[ "persona" ] is None
        # available still listed for caller to surface alternatives
        assert len( result[ "available" ] ) == 6

    def test_occupied_status_includes_holder_info( self ):
        occupied = { "Rachel": "sid-other-session" }
        result   = pick_requested_persona( POOL_6, occupied, "Rachel" )
        assert result[ "status" ]               == "occupied"
        assert result[ "persona" ]              is None
        assert result[ "holding_session_id" ]   == "sid-other-session"
        assert result[ "holding_persona_name" ] == "Rachel"
        # Rachel must NOT appear in available (she's the held one)
        assert "Rachel" not in result[ "available" ]
        # Other pool members are available
        assert len( result[ "available" ] ) == 5

    def test_occupied_via_case_insensitive_match( self ):
        # User requests "RACHEL" — pool match is "Rachel" — should still detect occupied
        occupied = { "Rachel": "sid-x" }
        result   = pick_requested_persona( POOL_6, occupied, "RACHEL" )
        assert result[ "status" ]               == "occupied"
        assert result[ "holding_persona_name" ] == "Rachel"

    def test_available_excludes_all_occupied( self ):
        occupied = { "Rachel": "sid-a", "Arnold": "sid-b", "Rio": "sid-c" }
        result   = pick_requested_persona( POOL_6, occupied, "Tiberius" )
        assert result[ "status" ]      == "ok"
        assert sorted( result[ "available" ] ) == sorted( [ "Tiberius", "maria", "mr radio" ] )

    def test_empty_pool_returns_not_in_pool( self ):
        result = pick_requested_persona( [], {}, "Rachel" )
        assert result[ "status" ]    == "not_in_pool"
        assert result[ "persona" ]   is None
        assert result[ "available" ] == []


# ── allocate_requested_persona_for_session ───────────────────────────────────

def _make_mock_config_mgr( pool=POOL_6, stale_seconds=43200 ):
    """Mock config_mgr that backs load_persona_pool_from_config."""
    mgr = MagicMock()

    persona_table = {
        p[ "name" ]: {
            "voice id": p[ "voice_id" ], "icon": p[ "icon" ],
            "color": p[ "color" ], "profile": p[ "profile" ]
        } for p in pool
    }

    def get( key, default=None, silent=False, return_type="string" ):
        if key == "cc session voice persona pool":
            return ", ".join( [ p[ "name" ] for p in pool ] )
        if key == "cc session voice persona stale threshold seconds":
            return stale_seconds
        if key == "cc session voice persona overflow":
            return ""  # no overflow persona for these tests
        prefix = "cc session voice persona "
        if key.startswith( prefix ):
            rest = key[ len( prefix ): ]
            for name, fields in persona_table.items():
                if rest.startswith( name + " " ):
                    field = rest[ len( name ) + 1: ]
                    return fields.get( field, default )
        return default

    mgr.get = get
    return mgr


class TestAllocateRequestedPersonaForSession:

    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions" )
    def test_happy_path_unoccupied( self, mock_find_active ):
        mock_find_active.return_value = []  # No live sessions
        cfg = _make_mock_config_mgr()
        result = allocate_requested_persona_for_session( cfg, "sid-mine", "Rachel" )
        assert result is not None
        assert result[ "status" ]              == "ok"
        assert result[ "persona" ][ "name" ]   == "Rachel"
        assert "assigned_at" in result[ "persona" ]

    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions" )
    def test_excludes_own_session_from_occupied_scan( self, mock_find_active ):
        # Caller currently holds Arnold; requests María. Without self-exclusion,
        # Arnold would falsely register as "occupied by another session" — but
        # since it's MINE, María should allocate cleanly (swap semantics).
        own_persona = { "name": "Arnold", "voice_id": "v_arnold", "icon": "🪨", "color": "#C62828", "profile": "" }
        mock_find_active.return_value = [
            ( "/tmp/cc-1.json", "sid-mine", own_persona )
        ]
        cfg = _make_mock_config_mgr()
        result = allocate_requested_persona_for_session( cfg, "sid-mine", "maria" )
        assert result[ "status" ]            == "ok"
        assert result[ "persona" ][ "name" ] == "maria"

    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions" )
    def test_occupied_by_other_returns_holding_info( self, mock_find_active ):
        other_persona = { "name": "maria", "voice_id": "v_maria", "icon": "🌸", "color": "#E91E63", "profile": "" }
        mock_find_active.return_value = [
            ( "/tmp/cc-2.json", "sid-other", other_persona )
        ]
        cfg = _make_mock_config_mgr()
        result = allocate_requested_persona_for_session( cfg, "sid-mine", "maria" )
        assert result[ "status" ]               == "occupied"
        assert result[ "holding_session_id" ]   == "sid-other"
        assert result[ "holding_persona_name" ] == "maria"
        assert "maria" not in result[ "available" ]

    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions" )
    def test_not_in_pool_status( self, mock_find_active ):
        mock_find_active.return_value = []
        cfg = _make_mock_config_mgr()
        result = allocate_requested_persona_for_session( cfg, "sid-mine", "Bogus" )
        assert result[ "status" ]    == "not_in_pool"
        assert result[ "persona" ]   is None
        assert len( result[ "available" ] ) == 6

    @patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions" )
    def test_skips_malformed_persona_entries_in_scan( self, mock_find_active ):
        # Bridge with non-dict or name-less persona is skipped (defense)
        mock_find_active.return_value = [
            ( "/tmp/cc-3.json", "sid-other", None ),
            ( "/tmp/cc-4.json", "sid-other2", { "voice_id": "x" } )  # no name
        ]
        cfg = _make_mock_config_mgr()
        result = allocate_requested_persona_for_session( cfg, "sid-mine", "Rachel" )
        assert result[ "status" ] == "ok"

    def test_pool_empty_returns_none( self ):
        cfg = _make_mock_config_mgr( pool=[] )
        result = allocate_requested_persona_for_session( cfg, "sid-mine", "Rachel" )
        assert result is None


# ── Route handler — TestClient + dependency overrides ────────────────────────

@pytest.fixture
def test_app():
    """
    Build a minimal FastAPI app with only the voice_persona router mounted
    + dependency overrides for auth + notification queue + config_mgr.
    """
    from cosa.rest.routers.voice_persona import (
        router as voice_persona_router,
        get_notification_queue, get_config_manager
    )
    from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

    app = FastAPI()
    app.include_router( voice_persona_router )

    yield app

    app.dependency_overrides.clear()


def _setup_overrides( app, config_mgr=None ):
    """Wire dependency overrides so the handler runs without external infra."""
    from cosa.rest.routers.voice_persona import (
        get_notification_queue, get_config_manager
    )
    from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

    mock_queue = MagicMock()
    mock_queue.push_notification = MagicMock( return_value=None )

    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "service-account"
    app.dependency_overrides[ get_notification_queue ] = lambda: mock_queue
    app.dependency_overrides[ get_config_manager ]     = lambda: ( config_mgr or _make_mock_config_mgr() )

    return mock_queue


class TestAllocateRouteRequestedPersona:

    def test_request_happy_path_when_no_existing( self, test_app ):
        mock_queue = _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=Rachel"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "voice_persona" ][ "name" ] == "Rachel"
        assert body[ "newly_allocated" ]         is True
        assert body[ "swapped" ]                 is False

    def test_request_idempotent_same_name( self, test_app ):
        """Request matching existing → 200, newly_allocated=False, swapped=False."""
        _setup_overrides( test_app )

        existing = { "name": "Rachel", "voice_id": "v_rachel", "icon": "🕊️", "color": "#4CAF50",
                     "profile": "calm", "borrowed": False, "display_name": "Rachel" }

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=existing ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=Rachel"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "newly_allocated" ] is False
        assert body[ "swapped" ]         is False
        assert body[ "voice_persona" ]   == existing

    def test_request_idempotent_display_form_vs_store_form_FLIP( self, test_app ):
        """FLIP (voice idempotency seam): existing is the store form "mr radio";
        the request is the display form "Mr. Radio". They are the SAME persona,
        so the endpoint must be idempotent (newly_allocated=False, no swap). Under
        the retired bare .lower() the request normalized to "mr. radio" (period
        kept) != existing "mr radio" -> it would have SWAPPED. canonical_persona_key
        collapses both to "mr radio" -> idempotent."""
        _setup_overrides( test_app )

        existing = { "name": "mr radio", "voice_id": "v_mrnpr", "icon": "🦉", "color": "#FFA000",
                     "profile": "authoritative", "borrowed": False, "display_name": "Mr. Radio" }

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=existing ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=Mr.%20Radio"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "newly_allocated" ] is False
        assert body[ "swapped" ]         is False
        assert body[ "voice_persona" ]   == existing

    def test_request_swap_path( self, test_app ):
        """Request differs from existing → atomic swap. newly_allocated=True, swapped=True."""
        mock_queue = _setup_overrides( test_app )

        existing = { "name": "Arnold", "voice_id": "v_arnold", "icon": "🪨", "color": "#C62828",
                     "profile": "gravelly", "borrowed": False, "display_name": "Arnold" }

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=existing ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                    return_value=[ ( "/tmp/cc-1.json", "sid-mine", existing ) ] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=maria"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "voice_persona" ][ "name" ] == "maria"
        assert body[ "newly_allocated" ]         is True
        assert body[ "swapped" ]                 is True

        # Swap announcement was pushed
        push_calls = mock_queue.push_notification.call_args_list
        assert any(
            "Voice re-assigned:" in ( c.kwargs.get( "message", "" ) or "" )
            for c in push_calls
        )

    def test_request_409_when_held_by_other_session( self, test_app ):
        _setup_overrides( test_app )

        held = { "name": "maria", "voice_id": "v_maria", "icon": "🌸", "color": "#E91E63",
                 "profile": "warm", "borrowed": False }

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                    return_value=[ ( "/tmp/cc-2.json", "sid-other", held ) ] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=maria"
            )

        assert resp.status_code == 409
        detail = resp.json()[ "detail" ]
        assert detail[ "holding_persona_name" ] == "maria"
        assert detail[ "holding_session_id" ]   == "sid-other"
        assert "available" in detail
        assert "maria" not in detail[ "available" ]

    def test_request_422_when_name_not_in_pool( self, test_app ):
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=Bogus"
            )

        assert resp.status_code == 422
        detail = resp.json()[ "detail" ]
        assert detail[ "requested" ] == "Bogus"
        assert "available" in detail
        assert len( detail[ "available" ] ) == 6  # full pool listed

    def test_request_500_when_pool_empty( self, test_app ):
        empty_cfg = _make_mock_config_mgr( pool=[] )
        _setup_overrides( test_app, config_mgr=empty_cfg )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=Rachel"
            )

        assert resp.status_code == 500

    def test_request_422_at_pydantic_layer_when_name_too_long( self, test_app ):
        """Query(max_length=64) validation kicks in at parse time."""
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ):
            client = TestClient( test_app )
            resp   = client.post(
                f"/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name={'x' * 65}"
            )

        assert resp.status_code == 422

    def test_request_422_at_pydantic_layer_when_name_empty( self, test_app ):
        """Query(min_length=1) validation kicks in at parse time."""
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ):
            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name="
            )

        assert resp.status_code == 422

    def test_request_session_not_found_returns_404( self, test_app ):
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value=None ):
            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=Rachel"
            )

        assert resp.status_code == 404


class TestAllocateRouteLegacyBehavior:
    """Verify the no-request path preserves the existing random-allocate contract."""

    def test_no_request_idempotent_returns_existing( self, test_app ):
        _setup_overrides( test_app )

        existing = { "name": "Rachel", "voice_id": "v_rachel", "icon": "🕊️", "color": "#4CAF50",
                     "profile": "calm", "borrowed": False }

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=existing ):

            client = TestClient( test_app )
            resp   = client.post( "/api/cosa-voice/voice-persona/sid-mine/allocate" )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "newly_allocated" ] is False
        assert body[ "swapped" ]         is False
        assert body[ "voice_persona" ]   == existing

    def test_no_request_no_existing_does_random_allocate( self, test_app ):
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post( "/api/cosa-voice/voice-persona/sid-mine/allocate" )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "newly_allocated" ] is True
        assert body[ "voice_persona" ][ "name" ] in [ p[ "name" ] for p in POOL_6 ]

    def test_no_request_race_returns_existing_inside_lock( self, test_app ):
        """Race protection: existing appears between outer check and lock acquire."""
        _setup_overrides( test_app )

        existing = { "name": "Rachel", "voice_id": "v_rachel", "icon": "🕊️", "color": "#4CAF50",
                     "profile": "calm", "borrowed": False }

        # First call returns None (outer check), second returns existing (inside lock)
        call_count = [ 0 ]
        def _get_voice_persona_race( sid ):
            call_count[ 0 ] += 1
            return None if call_count[ 0 ] == 1 else existing

        # Outer check uses non-None requested → take request branch... but we want
        # legacy no-request race. Outer no-request returns None → enters lock →
        # inner check returns existing → returns existing without re-allocating.
        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", side_effect=_get_voice_persona_race ):

            client = TestClient( test_app )
            resp   = client.post( "/api/cosa-voice/voice-persona/sid-mine/allocate" )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "newly_allocated" ] is False
        assert body[ "voice_persona" ]   == existing

    def test_no_request_pool_empty_returns_500( self, test_app ):
        empty_cfg = _make_mock_config_mgr( pool=[] )
        _setup_overrides( test_app, config_mgr=empty_cfg )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post( "/api/cosa-voice/voice-persona/sid-mine/allocate" )

        assert resp.status_code == 500


# ── previous_persona_name announcement (regression) ──────────────────────────

class TestPreviousPersonaAnnouncement:
    """The hook's `previous_persona_name` query param still triggers an audible
    handoff announcement when supplied. Regression guard."""

    def test_previous_persona_name_triggers_announce( self, test_app ):
        mock_queue = _setup_overrides( test_app )

        # Mark Arnold as occupied by another session so the random allocator
        # cannot pick Arnold — that would make the announcement branch
        # legitimately suppress the duplicate-name handoff and break this test.
        # By occupying Arnold elsewhere, the picked persona is guaranteed
        # to be different from previous_persona_name="Arnold".
        arnold_held_elsewhere = [
            ( "/tmp/cc-99.json", "sid-other",
              { "name": "Arnold", "voice_id": "v_arnold", "icon": "🪨",
                "color": "#C62828", "profile": "", "borrowed": False } )
        ]

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                    return_value=arnold_held_elsewhere ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?previous_persona_name=Arnold"
            )

        assert resp.status_code == 200
        push_calls = mock_queue.push_notification.call_args_list
        # Should see at least one push call with "Arnold" in the message
        # ("Voice re-assigned: Arnold → <new>")
        assert any(
            "Arnold" in ( c.kwargs.get( "message", "" ) or "" )
            for c in push_calls
        )

    def test_announce_suppressed_when_picked_matches_previous( self, test_app ):
        """If random picks the same name as previous_persona_name, suppress the
        announcement — no "Voice re-assigned: X → X" garbage."""
        # Force allocator to deterministically pick Arnold (only Arnold in pool)
        single_pool = [
            { "name": "Arnold", "voice_id": "v_arnold", "icon": "🪨",
              "color": "#C62828", "profile": "gravelly male" }
        ]
        single_cfg = _make_mock_config_mgr( pool=single_pool )
        mock_queue = _setup_overrides( test_app, config_mgr=single_cfg )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?previous_persona_name=Arnold"
            )

        assert resp.status_code == 200
        # voice_persona_assigned broadcast fired, but no "Voice re-assigned:" push
        push_calls = mock_queue.push_notification.call_args_list
        re_assigned_calls = [
            c for c in push_calls
            if "Voice re-assigned:" in ( c.kwargs.get( "message", "" ) or "" )
        ]
        assert len( re_assigned_calls ) == 0


# ── Bridge write failure (error path coverage) ───────────────────────────────

class TestBridgeWriteFailures:

    def test_request_bridge_write_failure_returns_500( self, test_app ):
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=Rachel"
            )

        assert resp.status_code == 500

    def test_no_request_bridge_write_failure_returns_500( self, test_app ):
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post( "/api/cosa-voice/voice-persona/sid-mine/allocate" )

        assert resp.status_code == 500


# ── Notification-push failure tolerance (best-effort) ────────────────────────

class TestNotificationPushFailureTolerance:

    def test_request_push_failure_does_not_break_allocate( self, test_app ):
        """Push failures are swallowed; bridge write is what matters."""
        from cosa.rest.routers.voice_persona import get_notification_queue
        from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
        from cosa.rest.routers.voice_persona import get_config_manager

        broken_queue = MagicMock()
        broken_queue.push_notification = MagicMock( side_effect=RuntimeError( "ws down" ) )

        test_app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "svc"
        test_app.dependency_overrides[ get_notification_queue ] = lambda: broken_queue
        test_app.dependency_overrides[ get_config_manager ]     = lambda: _make_mock_config_mgr()

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=Rachel&previous_persona_name=Arnold"
            )

        # Push fails on both broadcast AND announcement, but allocate succeeds
        assert resp.status_code == 200
        body = resp.json()
        assert body[ "voice_persona" ][ "name" ] == "Rachel"
        assert body[ "broadcast_delivered" ]     is False


# ── pick_persona_chain_from_env (pure helper) ────────────────────────────────

class TestPickPersonaChainFromEnv:
    """
    Tests for the env-var lookup helper. Pure function — no I/O, no MCP, no
    HTTP — just reads `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>` (now a chain
    expression) from os.environ with project-name normalization, or from an
    explicit `environ=` mapping when supplied.

    See: src/rnd/v0.1.8/2026.06.11-multi-manager-env-var-and-persona-preference-transport-fix.md
    """

    def test_env_var_unset_returns_none( self, monkeypatch ):
        # Ensure the var is absent
        monkeypatch.delenv( "COSA_VOICE_PREFERRED_PERSONA__LUPIN", raising=False )
        assert pick_persona_chain_from_env( "lupin" ) is None

    def test_project_normalization_hyphen( self, monkeypatch ):
        # project="cosa-voice" must resolve to ...__COSA_VOICE (hyphens → underscores)
        monkeypatch.setenv( "COSA_VOICE_PREFERRED_PERSONA__COSA_VOICE", "Rio" )
        assert pick_persona_chain_from_env( "cosa-voice" ) == "Rio"

    def test_project_normalization_uppercase( self, monkeypatch ):
        # Project name is case-insensitive — both "plan" and "PLAN" hit the same var
        monkeypatch.setenv( "COSA_VOICE_PREFERRED_PERSONA__PLAN", "María" )
        assert pick_persona_chain_from_env( "plan" ) == "María"
        assert pick_persona_chain_from_env( "PLAN" ) == "María"
        assert pick_persona_chain_from_env( "Plan" ) == "María"

    def test_empty_project_string( self, monkeypatch ):
        # Empty / None / whitespace-only project returns None silently — no env read
        monkeypatch.setenv( "COSA_VOICE_PREFERRED_PERSONA__", "Tiberius" )  # legal env var, but project="" → no lookup
        assert pick_persona_chain_from_env( ""    ) is None
        assert pick_persona_chain_from_env( None  ) is None
        assert pick_persona_chain_from_env( "   " ) is None

    def test_chain_expression_returned_verbatim( self, monkeypatch ):
        # Chain syntax is NOT parsed here — returned verbatim for the allocator
        monkeypatch.setenv( "COSA_VOICE_PREFERRED_PERSONA__LUPIN", "Mr. Radio,Tiberius,*" )
        assert pick_persona_chain_from_env( "lupin" ) == "Mr. Radio,Tiberius,*"

    def test_explicit_environ_mapping_wins_over_os_environ( self, monkeypatch ):
        # environ= param bypasses os.environ entirely (testability seam)
        monkeypatch.setenv( "COSA_VOICE_PREFERRED_PERSONA__LUPIN", "FromOsEnviron" )
        environ = { "COSA_VOICE_PREFERRED_PERSONA__LUPIN": "Rio,Krishna,*" }
        assert pick_persona_chain_from_env( "lupin", environ=environ ) == "Rio,Krishna,*"
        assert pick_persona_chain_from_env( "lupin", environ={} )      is None


# ── Router: `persona_chain` query param (STRICT ordered fallback) ────────────

class TestPersonaChainQueryParam:
    """
    Tests for the chain branch of /allocate — the 2026-06-11 replacement for
    the retired soft-preference `preferred_persona_name` param. STRICT
    ordered-fallback semantics: each named element is tried in order, the
    first FREE one wins; `*` means "then take anything free"; exhaustion
    without `*` is a LOUD 409 + `voice_persona_conflict` notification (NO
    silent random fallback). The old single-name behavior "María with soft
    fallback" is now expressed as the chain "María,*".

    Branches covered end-to-end through the real helpers (only the bridge
    boundary is mocked):
      - first element free → allocated, silent, chain_conflict None
      - first held + `*` → wildcard fallback + conflict notify (holder short-id)
      - first held + later NAMED element free → silent (expressed intent)
      - exhausted (no `*`) → 409 + conflict notify (kind=chain_exhausted)
      - empty chain (",,,") → 422 with message + chain echo
      - mutual exclusivity with requested_persona_name → 422
      - chain does NOT override an existing allocation
      - empty pool → 500 (pool_error)
    """

    def test_chain_first_element_free_allocates_silently( self, test_app ):
        """First chain element free → allocated; no conflict notify; chain_conflict None."""
        mock_queue = _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?persona_chain=Tiberius,*"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "voice_persona" ][ "name" ] == "Tiberius"
        assert body[ "newly_allocated" ]         is True
        assert body[ "chain_conflict" ]          is None
        assert "preference_conflict" not in body    # retired response key is GONE
        push_types = [ call.kwargs.get( "type" ) for call in mock_queue.push_notification.call_args_list ]
        assert "voice_persona_assigned" in push_types
        assert "voice_persona_conflict" not in push_types

    def test_chain_held_then_wildcard_fallback_notifies( self, test_app ):
        """First element held + `*` → wildcard allocates another; conflict notify carries holder short-id."""
        mock_queue = _setup_overrides( test_app )

        held_persona = { "name": "Tiberius", "voice_id": "v_tiberius", "icon": "🌑", "color": "#3F51B5", "profile": "" }
        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                    return_value=[ ( "/tmp/cc-2.json", "sid-other-12345678", held_persona ) ] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?persona_chain=Tiberius,*"
            )

        assert resp.status_code == 200
        body = resp.json()
        # Wildcard allocated something OTHER than Tiberius
        assert body[ "voice_persona" ][ "name" ] != "Tiberius"
        # chain_conflict reports the named miss with holder info
        assert body[ "chain_conflict" ][ "kind" ]  == "wildcard_fallback"
        assert body[ "chain_conflict" ][ "chain" ] == "Tiberius,*"
        outcome = body[ "chain_conflict" ][ "outcomes" ][ 0 ]
        assert outcome[ "name" ]               == "Tiberius"
        assert outcome[ "status" ]             == "occupied"
        assert outcome[ "holding_session_id" ] == "sid-other-12345678"
        # Both pushes fire; the conflict message names the holder's SHORT id
        push_calls = mock_queue.push_notification.call_args_list
        push_types = [ c.kwargs.get( "type" ) for c in push_calls ]
        assert "voice_persona_assigned" in push_types
        assert "voice_persona_conflict" in push_types
        conflict_msg = next(
            c.kwargs[ "message" ] for c in push_calls
            if c.kwargs.get( "type" ) == "voice_persona_conflict"
        )
        assert "sid-othe" in conflict_msg    # holding_session_id[:8]

    def test_chain_success_on_second_name_is_silent( self, test_app ):
        """First held, second NAMED element free → allocated silently (expressed intent)."""
        mock_queue = _setup_overrides( test_app )

        held_persona = { "name": "Tiberius", "voice_id": "v_tiberius", "icon": "🌑", "color": "#3F51B5", "profile": "" }
        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                    return_value=[ ( "/tmp/cc-2.json", "sid-other-12345678", held_persona ) ] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?persona_chain=Tiberius,Rio"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "voice_persona" ][ "name" ] == "Rio"
        assert body[ "chain_conflict" ]          is None
        push_types = [ call.kwargs.get( "type" ) for call in mock_queue.push_notification.call_args_list ]
        assert "voice_persona_conflict" not in push_types

    def test_chain_nonexistent_name_then_named_hit_is_distinguishable( self, test_app ):
        """A chain naming a NONEXISTENT persona that lands on a later NAMED element
        must not return a body the caller cannot tell from a clean first-element
        hit (row 462b985c). Both land on Rio; the not_in_pool skip is a caller
        error, not expressed intent, so it stays visible on chain_outcomes."""
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                    return_value=[] ):

            client   = TestClient( test_app )
            degraded = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?persona_chain=Frobozz,Rio"
            ).json()
            clean    = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?persona_chain=Rio"
            ).json()

        # Same landing persona — the ONLY real difference is the skipped typo.
        assert degraded[ "voice_persona" ][ "name" ] == "Rio"
        assert clean[ "voice_persona" ][ "name" ]    == "Rio"
        # The headline invariant: a degraded chain is NOT indistinguishable from a
        # clean hit. Without the fix both bodies are byte-identical and this fails.
        assert degraded != clean, "degraded chain is identical to a clean hit — the not_in_pool skip vanished"
        # Specifically: the nonexistent name is named, with status not_in_pool.
        assert [ ( o[ "name" ], o[ "status" ] ) for o in degraded[ "chain_outcomes" ][ "outcomes" ] ] == [ ( "Frobozz", "not_in_pool" ) ]
        assert degraded[ "chain_outcomes" ][ "satisfied_by" ] == "Rio"
        # A clean single-name hit carries no skips.
        assert clean[ "chain_outcomes" ][ "outcomes" ] == []

    def test_chain_exhausted_409_with_conflict_notification( self, test_app ):
        """Every named element missed, no `*` → 409 + conflict notify; session stays persona-less."""
        mock_queue = _setup_overrides( test_app )

        held_persona = { "name": "Tiberius", "voice_id": "v_tiberius", "icon": "🌑", "color": "#3F51B5", "profile": "" }
        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "cosa.rest.routers.voice_persona.set_voice_persona", return_value=True ) as mock_set, \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                    return_value=[ ( "/tmp/cc-2.json", "sid-other-12345678", held_persona ) ] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?persona_chain=Tiberius,Frobozz"
            )

        assert resp.status_code == 409
        detail = resp.json()[ "detail" ]
        assert "message" in detail
        assert detail[ "chain" ] == "Tiberius,Frobozz"
        assert [ o[ "status" ] for o in detail[ "outcomes" ] ] == [ "occupied", "not_in_pool" ]
        assert "Tiberius" not in detail[ "available" ]
        # NO bridge write — the session keeps no persona (Sam TTS fallback)
        mock_set.assert_not_called()
        # Conflict notification pushed BEFORE the 409
        conflict_calls = [ c for c in mock_queue.push_notification.call_args_list
                           if c.kwargs.get( "type" ) == "voice_persona_conflict" ]
        assert len( conflict_calls ) == 1
        kw = conflict_calls[ 0 ].kwargs
        assert kw[ "payload" ][ "kind" ] == "chain_exhausted"
        assert kw[ "voice_persona" ]     is None
        assert "sid-othe" in kw[ "message" ]

    def test_chain_empty_expression_422( self, test_app ):
        """A chain parsing to zero elements (',,,') → 422 with message + chain echo."""
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?persona_chain=,,,"
            )

        assert resp.status_code == 422
        detail = resp.json()[ "detail" ]
        assert "message" in detail
        assert detail[ "chain" ] == ",,,"

    def test_chain_mutually_exclusive_with_requested_422( self, test_app ):
        """Supplying BOTH requested_persona_name and persona_chain → 422."""
        _setup_overrides( test_app )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ):
            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?requested_persona_name=Rachel&persona_chain=Rio,*"
            )

        assert resp.status_code == 422
        assert "mutually exclusive" in resp.json()[ "detail" ]

    def test_chain_does_not_override_existing_allocation( self, test_app ):
        """Existing persona + chain → idempotent return of the EXISTING persona."""
        _setup_overrides( test_app )

        existing = { "name": "Rachel", "voice_id": "v_rachel", "icon": "🕊️", "color": "#4CAF50",
                     "profile": "calm", "borrowed": False }

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=existing ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?persona_chain=Tiberius,*"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body[ "newly_allocated" ] is False
        assert body[ "voice_persona" ]   == existing

    def test_chain_empty_pool_returns_500( self, test_app ):
        """Pool empty/misconfigured → pool_error → 500."""
        empty_cfg = _make_mock_config_mgr( pool=[] )
        _setup_overrides( test_app, config_mgr=empty_cfg )

        with patch( "cosa.rest.routers.voice_persona.find_session_path_by_id", return_value="/tmp/cc-1.json" ), \
             patch( "cosa.rest.routers.voice_persona.get_voice_persona", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions", return_value=[] ):

            client = TestClient( test_app )
            resp   = client.post(
                "/api/cosa-voice/voice-persona/sid-mine/allocate?persona_chain=Rio,*"
            )

        assert resp.status_code == 500
