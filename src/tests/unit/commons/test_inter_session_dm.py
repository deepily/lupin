"""
Unit tests for Inter-Session DM (Phase 0 implementation 2026-05-15).

Covers AC9a layer of `src/rnd/v0.1.7/2026.05.15-inter-session-direct-messaging-design.md`:
- `RecipientResolutionError` Pydantic model
- `_resolve_dm_recipient` helper (chain levels, error paths)

All tests run on :7999 venue (AI-discretionary per CLAUDE.md §TESTING VENUES).
Coverage target: 100% lines + branches on new code paths.
"""
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

from cosa.rest.routers.commons import (
    RecipientResolutionError,
    _resolve_dm_recipient,
    _session_id_matches,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


def _build_raw_session( session_id: str, persona_name: str, user_id: str = "rick@example.com" ):
    """Build a raw_sessions tuple — (bridge_path_marker, session_id, persona_dict).

    The 3rd slot is the persona dict (per `project_session_response` contract),
    NOT the full bridge. The full bridge is loaded by bridge_loader(path).
    """
    persona_dict = { "name": persona_name, "icon": "🌸", "color": "#F06292" }
    return ( f"/fake/bridge/{session_id}.json", session_id, persona_dict )


def _build_fixture_bridge( session_id: str, user_id: str = "rick@example.com" ) -> Dict[ str, Any ]:
    """Build the bridge dict that `_fake_bridge_loader` returns for a session."""
    return {
        "stable_session_id"   : session_id,
        "session_id"          : session_id,
        "user_id"             : user_id,
        "owner_user_id"       : user_id,
        "last_activity_iso"   : "2026-05-15T12:00:00+00:00",
        "idle_detection"      : { "last_interaction_at" : time.time() },
    }


def _fake_raw_sessions_fn( sessions ):
    """Return a closure that yields the supplied sessions list."""
    return lambda: sessions


def _fake_bridge_loader( path ):
    """Identity bridge loader — the raw_sessions tuple already carries the bridge dict."""
    # filter_and_project_sessions calls bridge_loader(path) and expects the bridge dict.
    # For test fixtures we encode the bridge dict in the third tuple slot, so we look it up via path.
    return _FIXTURE_BRIDGES.get( path )


_FIXTURE_BRIDGES : Dict[ str, Dict[ str, Any ] ] = { }


def _register_fixture( raw_session, user_id: str = "rick@example.com" ):
    """Register the bridge dict in the fixture lookup so _fake_bridge_loader returns it."""
    path, sid, _persona = raw_session
    _FIXTURE_BRIDGES[ path ] = _build_fixture_bridge( sid, user_id )


# ─── RecipientResolutionError model ─────────────────────────────────────────


class TestRecipientResolutionError:
    def test_model_roundtrip_minimum_fields( self ):
        err = RecipientResolutionError(
            error                      = "recipient_required",
            suggested_next_action      = "Supply either recipient_session_id or recipient_persona.",
        )
        d = err.model_dump()
        assert d[ "error" ] == "recipient_required"
        assert d[ "supplied_persona" ] is None
        assert d[ "supplied_session_id" ] is None
        assert d[ "resolution_chain_attempted" ] == [ ]
        assert d[ "candidate_alternatives" ] == [ ]
        assert "Supply either" in d[ "suggested_next_action" ]

    def test_model_with_candidates( self ):
        err = RecipientResolutionError(
            error                      = "recipient_persona_ambiguous",
            supplied_persona           = "rad",
            resolution_chain_attempted = [ "exact", "case_insensitive" ],
            candidate_alternatives     = [ { "persona": "radio", "session_id": "abc123", "active_since": "2026-05-15T11:00:00" } ],
            suggested_next_action      = "Try recipient_session_id=abc123 directly.",
        )
        d = err.model_dump()
        assert d[ "candidate_alternatives" ][ 0 ][ "persona" ] == "radio"
        assert d[ "resolution_chain_attempted" ] == [ "exact", "case_insensitive" ]

    def test_model_rejects_empty_error( self ):
        with pytest.raises( Exception ):
            RecipientResolutionError(
                error                  = "",
                suggested_next_action  = "x",
            )


# ─── _resolve_dm_recipient ───────────────────────────────────────────────────


class TestResolveDmRecipient:
    def setup_method( self ):
        _FIXTURE_BRIDGES.clear()

    def test_session_id_direct_success( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        sess_b = _build_raw_session( "sid_b", "rachel" )
        _register_fixture( sess_a )
        _register_fixture( sess_b )

        result = _resolve_dm_recipient(
            recipient_session_id  = "sid_a",
            recipient_persona     = None,
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a, sess_b ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 200
        assert result[ "session_id" ]   == "sid_a"

    def test_session_id_inactive_returns_422( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = "sid_phantom",
            recipient_persona     = None,
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 422
        assert result[ "detail" ][ "error" ] == "recipient_inactive"
        assert result[ "detail" ][ "supplied_session_id" ] == "sid_phantom"
        assert any( c[ "persona" ] == "radio" for c in result[ "detail" ][ "candidate_alternatives" ] )

    def test_persona_exact_match( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = None,
            recipient_persona     = "radio",
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 200
        assert result[ "session_id" ]   == "sid_a"
        assert result[ "persona_name" ] == "radio"

    def test_persona_case_insensitive_match( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = None,
            recipient_persona     = "Radio",   # capitalized
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 200
        assert result[ "persona_name" ] == "radio"

    def test_persona_not_found_returns_422( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = None,
            recipient_persona     = "tiberius",
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 422
        assert result[ "detail" ][ "error" ] == "recipient_not_found"
        assert "exact" in result[ "detail" ][ "resolution_chain_attempted" ]
        assert "punct_tolerant" in result[ "detail" ][ "resolution_chain_attempted" ]

    def test_neither_returns_recipient_required( self ):
        sess_a = _build_raw_session( "sid_a", "radio" )
        _register_fixture( sess_a )

        result = _resolve_dm_recipient(
            recipient_session_id  = None,
            recipient_persona     = None,
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( [ sess_a ] ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge mtime → alive
        )
        assert result[ "http_status" ] == 422
        assert result[ "detail" ][ "error" ] == "recipient_required"


# ─── d57dbfea: null-persona worker inbound reachability ───────────────────────
#
# A worker spawned when the persona pool is EXHAUSTED boots voice_persona=null.
# It can DM its manager (outbound works), but the manager could not DM it back:
# `find_active_voice_persona_sessions` filtered persona-less bridges out of the
# resolution candidate list, so the worker was a black hole for inbound DMs.
# These tests pin the fix: the DM path sources `find_active_sessions(
# require_persona=False )`, whose persona-less sessions project to `{}`, and the
# session_id match tolerates the short (8-char) form the worker advertises.


def _build_null_persona_session( session_id: str ):
    """Raw session tuple for a worker that booted with NO voice_persona.

    The 3rd slot is `{}` — exactly what `find_active_sessions( require_persona=
    False )` projects for a persona-less bridge (so every consumer that does
    `p.get(...)` stays safe).
    """
    return ( f"/fake/bridge/{session_id}.json", session_id, {} )


class TestSessionIdMatches:
    """Short/full-tolerant session-id matching helper (d57dbfea)."""

    _FULL  = "23b3bfbc-32d2-4b6e-ae45-09c1721e646e"
    _SHORT = "23b3bfbc"

    def test_exact_match( self ):
        assert _session_id_matches( self._FULL, self._FULL ) is True

    def test_short_supplied_is_prefix_of_full_canonical( self ):
        # The repro: candidate keyed on full id, manager supplies the short id.
        assert _session_id_matches( self._FULL, self._SHORT ) is True

    def test_full_supplied_against_short_canonical_is_symmetric( self ):
        # Either side may be the shorter — the shorter must prefix the longer.
        assert _session_id_matches( self._SHORT, self._FULL ) is True

    def test_prefix_below_8_chars_rejected( self ):
        assert _session_id_matches( self._FULL, "23b3" ) is False

    def test_falsy_canonical_rejected( self ):
        assert _session_id_matches( None, self._SHORT ) is False
        assert _session_id_matches( "", self._SHORT ) is False

    def test_empty_supplied_rejected( self ):
        assert _session_id_matches( self._FULL, "" ) is False

    def test_non_prefix_mismatch_rejected( self ):
        assert _session_id_matches( self._FULL, "ffffffff" ) is False


class TestResolveDmNullPersonaReachability:
    _FULL  = "23b3bfbc-32d2-4b6e-ae45-09c1721e646e"
    _SHORT = "23b3bfbc"

    def setup_method( self ):
        _FIXTURE_BRIDGES.clear()

    def _resolve( self, *, recipient_session_id=None, recipient_persona=None, sessions ):
        return _resolve_dm_recipient(
            recipient_session_id  = recipient_session_id,
            recipient_persona     = recipient_persona,
            authenticated_user_id = "rick@example.com",
            raw_sessions_fn       = _fake_raw_sessions_fn( sessions ),
            bridge_loader         = _fake_bridge_loader,
            active_session_threshold_seconds = 600.0,
            mtime_fn              = lambda p: time.time(),   # fresh bridge → alive
        )

    def test_null_persona_resolvable_by_exact_session_id( self ):
        null_sess = _build_null_persona_session( self._FULL )
        _register_fixture( null_sess )
        result = self._resolve( recipient_session_id=self._FULL, sessions=[ null_sess ] )
        assert result[ "http_status" ]  == 200
        assert result[ "session_id" ]   == self._FULL
        assert result[ "persona_name" ] is None   # null-persona worker has no name

    def test_null_persona_resolvable_by_short_session_id( self ):
        # THE bug: manager replies with the short (8-char) id the worker advertised.
        null_sess = _build_null_persona_session( self._FULL )
        _register_fixture( null_sess )
        result = self._resolve( recipient_session_id=self._SHORT, sessions=[ null_sess ] )
        assert result[ "http_status" ]  == 200
        assert result[ "session_id" ]   == self._FULL   # canonical id returned
        assert result[ "persona_name" ] is None

    def test_short_session_id_ambiguous_returns_422( self ):
        # Two live sessions share the same 8-char prefix → the short id is ambiguous.
        s1 = _build_raw_session( "23b3bfbc-1111-1111-1111-111111111111", "radio" )
        s2 = _build_null_persona_session( "23b3bfbc-2222-2222-2222-222222222222" )
        _register_fixture( s1 )
        _register_fixture( s2 )
        result = self._resolve( recipient_session_id=self._SHORT, sessions=[ s1, s2 ] )
        assert result[ "http_status" ] == 422
        assert result[ "detail" ][ "error" ] == "recipient_session_id_ambiguous"
        assert "session_id_prefix" in result[ "detail" ][ "resolution_chain_attempted" ]

    def test_null_persona_listed_in_candidate_alternatives_on_miss( self ):
        # Regression for "candidate_alternatives never list the worker": even when
        # the supplied id misses, a null-persona worker must now appear (persona "").
        null_sess = _build_null_persona_session( self._FULL )
        _register_fixture( null_sess )
        result = self._resolve(
            recipient_session_id="ffffffff-0000-0000-0000-000000000000", sessions=[ null_sess ]
        )
        assert result[ "http_status" ] == 422
        assert result[ "detail" ][ "error" ] == "recipient_inactive"
        alts = result[ "detail" ][ "candidate_alternatives" ]
        worker = next( ( c for c in alts if c[ "session_id" ] == self._FULL ), None )
        assert worker is not None
        assert worker[ "persona" ] == ""   # null persona → empty string, but VISIBLE

    def test_null_persona_not_addressable_by_name( self ):
        # A persona-less worker has no name; the persona path must 422, never crash.
        null_sess = _build_null_persona_session( self._FULL )
        _register_fixture( null_sess )
        result = self._resolve( recipient_persona="anything", sessions=[ null_sess ] )
        assert result[ "http_status" ] == 422
        assert result[ "detail" ][ "error" ] == "recipient_not_found"

    def test_named_session_still_resolvable_by_short_id( self ):
        # The short-id tolerance is general — a NAMED worker is reachable by short id too.
        named = _build_raw_session( self._FULL, "rachel" )
        _register_fixture( named )
        result = self._resolve( recipient_session_id=self._SHORT, sessions=[ named ] )
        assert result[ "http_status" ]  == 200
        assert result[ "session_id" ]   == self._FULL
        assert result[ "persona_name" ] == "rachel"
