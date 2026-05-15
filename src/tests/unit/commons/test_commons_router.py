"""
Unit tests for commons router pure-logic helpers (Phase 2 step 5).

Per AC1 + AC2 + AC3 + AC4 + AC5 + T7 + T8 + T9 of
src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md.

Coverage target: 100% lines + branches + functions on the pure-logic helpers.
Route handlers are `# pragma: no cover` per AC12 (endpoint integration tests
do not contribute to the gate).
"""

import json
import re
import tempfile
import time
from pathlib import Path

import pytest

from pydantic import ValidationError

from cosa.rest.commons_ack_watcher import CommonsAckWatcher
from cosa.rest.commons_question_watcher import CommonsQuestionWatcher
from cosa.rest.commons_rate_limiter import CommonsBroadcastRateLimiter
from cosa.rest.routers.commons import (
    BroadcastRequestBody,
    RegisterQuestionRequest,
    _bridge_last_activity_epoch,
    _dedupe_broadcasts_by_id,
    _entry_passes_same_user_scoping,
    _load_bridge_fields,
    _body_contains_reminder_framing,
    _project_history_entry,
    _resolve_since_cutoff,
    build_pseudo_sender_id,
    execute_broadcast,
    execute_broadcast_history,
    execute_register_question,
    execute_unregister_question,
    filter_and_project_sessions,
    init_commons_state,
    make_question_inject_fn,
    perform_fanout,
    project_session_response,
    validate_broadcast_body,
    validate_broadcast_id,
)
from lupin_mcp.commons_store import CommonsStore


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        yield CommonsStore( tmp )


@pytest.fixture
def rate_limiter():
    return CommonsBroadcastRateLimiter( window_seconds=30 )


@pytest.fixture
def captured_pushes():
    return [ ]


@pytest.fixture
def push_fn( captured_pushes ):
    class _Q:
        def push_notification( self, **kwargs ):
            captured_pushes.append( kwargs )
    return _Q()


@pytest.fixture
def ack_watcher( store, push_fn ):
    return CommonsAckWatcher( store=store, push_notification_fn=push_fn.push_notification )


# ─── _body_contains_reminder_framing + validate_broadcast_body (AC1 + T1) ───


def test_body_contains_open_tag():
    assert _body_contains_reminder_framing( "<system-reminder>" ) is True


def test_body_contains_close_tag():
    assert _body_contains_reminder_framing( "</system-reminder>" ) is True


def test_body_does_not_contain_normal():
    assert _body_contains_reminder_framing( "hello <code>" ) is False


def test_validate_body_accepts_normal():
    ok, err = validate_broadcast_body( "hello world" )
    assert ok is True
    assert err is None


def test_validate_body_rejects_none():
    ok, err = validate_broadcast_body( None )
    assert ok is False
    assert "required" in err


def test_validate_body_rejects_empty_string():
    ok, err = validate_broadcast_body( "" )
    assert ok is False


def test_validate_body_rejects_whitespace_only():
    ok, err = validate_broadcast_body( "   \n  " )
    assert ok is False
    assert "required" in err


def test_validate_body_rejects_non_string():
    ok, err = validate_broadcast_body( 42 )
    assert ok is False


def test_validate_body_rejects_open_tag_substring():
    ok, err = validate_broadcast_body( "hello <SYSTEM-REMINDER> world" )
    assert ok is False
    assert "framing" in err


def test_validate_body_rejects_close_tag_substring():
    ok, err = validate_broadcast_body( "trick </system-reminder> trick" )
    assert ok is False


# ─── validate_broadcast_id (AC1) ────────────────────────────────────────────


def test_validate_broadcast_id_none_allowed():
    ok, err = validate_broadcast_id( None )
    assert ok is True
    assert err is None


def test_validate_broadcast_id_valid_uuidv4():
    ok, err = validate_broadcast_id( "f47ac10b-58cc-4372-a567-0e02b2c3d479" )
    assert ok is True


def test_validate_broadcast_id_uppercase_valid():
    ok, err = validate_broadcast_id( "F47AC10B-58CC-4372-A567-0E02B2C3D479" )
    assert ok is True


def test_validate_broadcast_id_v1_rejected():
    """UUIDv1 has version digit 1 in position 14, not 4."""
    ok, err = validate_broadcast_id( "f47ac10b-58cc-1372-a567-0e02b2c3d479" )
    assert ok is False


def test_validate_broadcast_id_garbage_rejected():
    ok, err = validate_broadcast_id( "not-a-uuid" )
    assert ok is False


def test_validate_broadcast_id_non_string_rejected():
    ok, err = validate_broadcast_id( 12345 )
    assert ok is False


# ─── build_pseudo_sender_id (AC4 + F8) ──────────────────────────────────────


def test_build_pseudo_sender_id_shape():
    """Hyphen separator (NOT @) + 8 lowercase hex chars."""
    sid = build_pseudo_sender_id( "user@example.com" )
    assert sid.startswith( "broadcast-" )
    assert "@" not in sid   # F8 — would fail _HEADER_RE round-trip
    assert re.match( r"^broadcast-[0-9a-f]{8}$", sid )


def test_build_pseudo_sender_id_deterministic():
    a = build_pseudo_sender_id( "user@example.com" )
    b = build_pseudo_sender_id( "user@example.com" )
    assert a == b


def test_build_pseudo_sender_id_different_users_different_ids():
    a = build_pseudo_sender_id( "alice@example.com" )
    b = build_pseudo_sender_id( "bob@example.com" )
    assert a != b


def test_build_pseudo_sender_id_round_trips_through_store( store ):
    """Per AC4 verification: post via the pseudo-sid + read back cleanly (regex compat)."""
    pseudo = build_pseudo_sender_id( "alice@example.com" )
    store.post(
        topic             = "broadcasts",
        body              = "hello",
        sender_session_id = pseudo,
        persona_name      = "System Broadcast",
        persona_icon      = "📢",
        persona_color     = "#FFC107",
        metadata          = { "broadcast_id": "x", "target_session_id": "t1", "sender_user_id": "alice@example.com" },
    )
    entries = store.read( "broadcasts", limit=10 )
    assert len( entries ) == 1
    assert entries[ 0 ][ "sender_session_id" ] == pseudo


# ─── _load_bridge_fields + _bridge_last_activity_epoch ──────────────────────


def test_load_bridge_fields_success( tmp_path ):
    p = tmp_path / "bridge.json"
    p.write_text( json.dumps( { "user_id": "alice@example.com", "voice_persona": { "name": "Maria" } } ) )
    bridge = _load_bridge_fields( p )
    assert bridge[ "user_id" ] == "alice@example.com"


def test_load_bridge_fields_missing_returns_none( tmp_path ):
    bridge = _load_bridge_fields( tmp_path / "nonexistent.json" )
    assert bridge is None


def test_load_bridge_fields_bad_json_returns_none( tmp_path ):
    p = tmp_path / "bad.json"
    p.write_text( "{ this is not json" )
    assert _load_bridge_fields( p ) is None


def test_bridge_last_activity_epoch_field():
    assert _bridge_last_activity_epoch( { "last_activity_epoch": 1000.0 } ) == 1000.0


def test_bridge_last_activity_legacy_field():
    assert _bridge_last_activity_epoch( { "last_activity": 999.0 } ) == 999.0


def test_bridge_last_activity_updated_at():
    assert _bridge_last_activity_epoch( { "updated_at": 500.0 } ) == 500.0


def test_bridge_last_activity_int_accepted():
    assert _bridge_last_activity_epoch( { "last_activity_epoch": 12345 } ) == 12345.0


def test_bridge_last_activity_none_when_missing():
    assert _bridge_last_activity_epoch( { } ) is None


def test_bridge_last_activity_none_for_bad_type():
    """Non-numeric value → None (defensive)."""
    assert _bridge_last_activity_epoch( { "last_activity_epoch": "not-a-number" } ) is None


# 2026-05-13 fix per src/rnd/v0.1.7/2026.05.13-broadcast-stale-bridge-phantom.md —
# fall back to `idle_detection.last_interaction_at` ISO string (the field the
# real bridge writer populates) when no numeric epoch field is present.


def test_bridge_last_activity_falls_back_to_idle_detection_iso():
    """ISO string under `idle_detection.last_interaction_at` parses to epoch."""
    bridge = { "idle_detection": { "last_interaction_at": "2026-05-13T10:00:00-04:00" } }
    epoch = _bridge_last_activity_epoch( bridge )
    assert epoch is not None
    # 2026-05-13T10:00:00-04:00 == 2026-05-13T14:00:00 UTC == 1779711600.0
    from datetime import datetime
    expected = datetime.fromisoformat( "2026-05-13T10:00:00-04:00" ).timestamp()
    assert abs( epoch - expected ) < 1.0


def test_bridge_last_activity_numeric_wins_over_idle_detection():
    """When BOTH numeric field and idle_detection ISO exist, numeric wins (back-compat)."""
    bridge = {
        "last_activity_epoch": 99999.0,
        "idle_detection"     : { "last_interaction_at": "2026-05-13T10:00:00-04:00" },
    }
    assert _bridge_last_activity_epoch( bridge ) == 99999.0


def test_bridge_last_activity_idle_detection_malformed_iso_returns_none():
    """Malformed ISO string in idle_detection → None, no raise."""
    bridge = { "idle_detection": { "last_interaction_at": "not an iso timestamp" } }
    assert _bridge_last_activity_epoch( bridge ) is None


def test_bridge_last_activity_idle_detection_missing_field_returns_none():
    """idle_detection dict present but no last_interaction_at → None."""
    bridge = { "idle_detection": { "backoff_index": 0 } }
    assert _bridge_last_activity_epoch( bridge ) is None


def test_bridge_last_activity_idle_detection_non_string_returns_none():
    """idle_detection.last_interaction_at non-string → None (defensive)."""
    bridge = { "idle_detection": { "last_interaction_at": 12345 } }
    assert _bridge_last_activity_epoch( bridge ) is None


def test_bridge_last_activity_idle_detection_non_dict_returns_none():
    """`idle_detection` is not a dict (e.g. None, list, string) → None."""
    assert _bridge_last_activity_epoch( { "idle_detection": None } )    is None
    assert _bridge_last_activity_epoch( { "idle_detection": [ ] } )     is None
    assert _bridge_last_activity_epoch( { "idle_detection": "oops" } )  is None


# ─── project_session_response (AC2 + T8) ────────────────────────────────────


def test_project_session_response_basic_shape():
    out = project_session_response(
        session_id = "sid-1",
        persona    = { "name": "Maria", "icon": "🌸", "color": "#A040A0" },
        bridge     = { "user_id": "alice", "last_activity_iso": "2026-05-12T00:00:00", "speakerphone_on": True },
    )
    assert out[ "session_id" ]               == "sid-1"
    assert out[ "persona_name" ]             == "Maria"
    assert out[ "persona_icon" ]             == "🌸"
    assert out[ "persona_color" ]            == "#A040A0"
    assert out[ "last_seen_iso" ]            == "2026-05-12T00:00:00"
    assert out[ "speakerphone_on" ] is True


def test_project_session_response_no_bridge_path_leak():
    """T8: response must NOT contain bridge_path or absolute filesystem paths."""
    out = project_session_response(
        session_id = "sid-1",
        persona    = { "name": "Maria", "icon": "🌸", "color": "#A040A0" },
        bridge     = { "user_id": "alice", "_bridge_path": "/home/user/.claude/sessions/cc-123.json" },
    )
    assert "bridge_path" not in out
    assert "_bridge_path" not in out
    for v in out.values():
        if isinstance( v, str ):
            assert not v.startswith( "/home/" )
            assert "/.claude/" not in v


def test_project_session_response_fallback_iso_field():
    """Picks `updated_at_iso` when `last_activity_iso` is missing."""
    out = project_session_response(
        session_id = "sid-1",
        persona    = { "name": "X", "icon": "?", "color": "#000" },
        bridge     = { "updated_at_iso": "2026-05-12T00:00:00" },
    )
    assert out[ "last_seen_iso" ] == "2026-05-12T00:00:00"


def test_project_session_response_missing_speakerphone_on_defaults_false():
    out = project_session_response( "sid", { }, { } )
    assert out[ "speakerphone_on" ] is False


# 2026-05-13 fix — projection mirrors `_bridge_last_activity_epoch`'s fallback
# so `last_seen_iso` actually populates when only `idle_detection.last_interaction_at`
# is present (the field the real bridge writer uses).


def test_project_session_response_falls_back_to_idle_detection_iso():
    """When top-level iso fields are absent, fall back to idle_detection.last_interaction_at."""
    out = project_session_response(
        session_id = "sid-1",
        persona    = { "name": "X", "icon": "?", "color": "#000" },
        bridge     = { "idle_detection": { "last_interaction_at": "2026-05-13T10:00:00-04:00" } },
    )
    assert out[ "last_seen_iso" ] == "2026-05-13T10:00:00-04:00"


def test_project_session_response_top_level_iso_wins_over_idle_detection():
    """When BOTH exist, top-level wins (back-compat with hypothetical future writer)."""
    out = project_session_response(
        session_id = "sid-1",
        persona    = { "name": "X", "icon": "?", "color": "#000" },
        bridge     = {
            "last_activity_iso": "2026-01-01T00:00:00",
            "idle_detection"  : { "last_interaction_at": "2026-05-13T10:00:00-04:00" },
        },
    )
    assert out[ "last_seen_iso" ] == "2026-01-01T00:00:00"


def test_project_session_response_no_iso_anywhere_returns_none():
    """No iso source anywhere → last_seen_iso is None (no crash)."""
    out = project_session_response(
        session_id = "sid-1",
        persona    = { "name": "X", "icon": "?", "color": "#000" },
        bridge     = { "user_id": "alice" },
    )
    assert out[ "last_seen_iso" ] is None


# ─── filter_and_project_sessions (AC2 + T7 + T8) ────────────────────────────


def _make_session_tuple( path: str, sid: str, persona: dict ):
    """Mimics find_active_voice_persona_sessions return shape."""
    return ( path, sid, persona )


def test_filter_includes_same_user():
    raw = [
        _make_session_tuple( "/bridge/A", "sid-A", { "name": "Maria", "icon": "🌸", "color": "#A040A0" } ),
    ]
    loader = lambda p: { "owner_user_id": "alice", "last_activity_epoch": 1000.0 }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
    )
    assert len( out ) == 1


def test_filter_excludes_other_user():
    """T7: cross-user session is excluded from results."""
    raw = [
        _make_session_tuple( "/bridge/A", "sid-A", { "name": "Maria" } ),
    ]
    loader = lambda p: { "owner_user_id": "bob", "last_activity_epoch": 1000.0 }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
    )
    assert out == [ ]


def test_filter_graceful_includes_bridge_without_owner_user_id():
    """
    2026-05-14 carry-forward (was `user_id` pre-Option-C) — bridge lacking an
    `owner_user_id` field passes through (graceful degradation for legacy /
    un-stamped bridges per
    `src/rnd/v0.1.7/2026.05.14-broadcast-listener-stamps-wrong-user-id.md`).
    """
    raw = [ _make_session_tuple( "/bridge/legacy", "sid-legacy", { "name": "Maria" } ) ]
    # Bridge has NO owner_user_id key
    loader = lambda p: { "last_activity_epoch": 1000.0 }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
    )
    assert len( out ) == 1
    assert out[ 0 ][ "session_id" ] == "sid-legacy"


def test_filter_graceful_includes_bridge_with_null_owner_user_id():
    """
    Bridge with explicit `owner_user_id: null` is treated as un-stamped
    (same as missing key) and passes through.
    """
    raw = [ _make_session_tuple( "/bridge/null", "sid-null", { "name": "Maria" } ) ]
    loader = lambda p: { "owner_user_id": None, "last_activity_epoch": 1000.0 }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
    )
    assert len( out ) == 1


def test_filter_uses_owner_user_id_not_legacy_user_id():
    """
    Regression — 2026-05-14 bug per
    `src/rnd/v0.1.7/2026.05.14-broadcast-listener-stamps-wrong-user-id.md`.

    Scoping MUST use `owner_user_id` (human owner), NOT the legacy `user_id`
    (which carries the listener service-account identity).

    Setup: bridge carries BOTH fields with DIFFERENT values —
      `user_id`        = "listener-svc"   (service account that wrote the bridge)
      `owner_user_id`  = "alice"           (human owner)

    Caller authenticates as "alice". Bridge MUST be included.
    Pre-Option-C: filter compared `user_id` ("listener-svc") to "alice" and
    rejected. Post-Option-C: filter compares `owner_user_id` ("alice") and
    includes. The legacy `user_id` field is now telemetry only.
    """
    raw = [ _make_session_tuple( "/bridge/A", "sid-A", { "name": "Maria" } ) ]
    loader = lambda p: {
        "user_id"             : "listener-svc",   # listener identity — irrelevant to filter
        "owner_user_id"       : "alice",           # human owner — the one that matters
        "last_activity_epoch" : 1000.0,
    }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
    )
    assert len( out ) == 1, "filter must use owner_user_id, not legacy user_id"
    assert out[ 0 ][ "session_id" ] == "sid-A"


def test_filter_excludes_session_stale_via_idle_detection_iso():
    """
    2026-05-13 fix — bridge with stale `idle_detection.last_interaction_at`
    is excluded by the time-threshold filter (previously a no-op because the
    filter looked at wrong field names). Per
    `src/rnd/v0.1.7/2026.05.13-broadcast-stale-bridge-phantom.md`.
    """
    raw = [ _make_session_tuple( "/bridge/stale", "sid-stale", { "name": "MrRadio" } ) ]
    from datetime import datetime, timedelta, timezone
    # Last interaction 2 hours ago — well past the 600s (10min) threshold
    stale_iso = ( datetime.now( timezone.utc ) - timedelta( hours=2 ) ).isoformat()
    now_epoch = datetime.now( timezone.utc ).timestamp()
    loader = lambda p: { "idle_detection": { "last_interaction_at": stale_iso } }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "anyone",
        active_session_threshold_seconds = 600,
        now_epoch                        = now_epoch,
        bridge_loader                    = loader,
    )
    assert out == [ ], "stale bridge should have been pruned by the time-threshold filter"


def test_filter_includes_session_recently_interactive_via_idle_detection_iso():
    """
    Counterpart: a bridge with RECENT `idle_detection.last_interaction_at`
    passes the time-threshold filter.
    """
    raw = [ _make_session_tuple( "/bridge/recent", "sid-recent", { "name": "Maria" } ) ]
    from datetime import datetime, timedelta, timezone
    recent_iso = ( datetime.now( timezone.utc ) - timedelta( seconds=60 ) ).isoformat()
    now_epoch  = datetime.now( timezone.utc ).timestamp()
    loader = lambda p: { "idle_detection": { "last_interaction_at": recent_iso } }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "anyone",
        active_session_threshold_seconds = 600,
        now_epoch                        = now_epoch,
        bridge_loader                    = loader,
    )
    assert len( out ) == 1
    # Bonus: last_seen_iso projection now populates
    assert out[ 0 ][ "last_seen_iso" ] == recent_iso


def test_filter_strict_when_bridge_has_owner_user_id():
    """
    Regression: bridges that DO carry owner_user_id still enforce strict
    equality — the graceful path only relaxes for missing/null owner_user_id.
    """
    raw = [
        _make_session_tuple( "/bridge/A", "sid-A", { "name": "Maria" } ),
        _make_session_tuple( "/bridge/B", "sid-B", { "name": "Tiberius" } ),
    ]
    def loader( p ):
        # A is owned by alice; B is owned by bob; bridge for path /unknown has no owner_user_id
        if str( p ) == "/bridge/A": return { "owner_user_id": "alice", "last_activity_epoch": 1000.0 }
        if str( p ) == "/bridge/B": return { "owner_user_id": "bob",   "last_activity_epoch": 1000.0 }
        return None
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
    )
    # Only alice's bridge is included — bob's is rejected because his bridge HAS owner_user_id and it doesn't match
    assert len( out ) == 1
    assert out[ 0 ][ "session_id" ] == "sid-A"


def test_filter_skips_unloadable_bridge():
    """Bridge loader returns None → session skipped."""
    raw = [ _make_session_tuple( "/bridge/A", "sid-A", { } ) ]
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = lambda p: None,
    )
    assert out == [ ]


def test_filter_excludes_stale_session():
    """Session past activity threshold is excluded."""
    raw = [ _make_session_tuple( "/bridge/A", "sid-A", { "name": "Maria" } ) ]
    loader = lambda p: { "owner_user_id": "alice", "last_activity_epoch": 100.0 }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,   # 900s after last_activity, > 600s threshold
        bridge_loader                    = loader,
    )
    assert out == [ ]


def test_filter_includes_session_with_no_activity_timestamp():
    """If bridge has NO last_activity field, treat as active (don't drop)."""
    raw = [ _make_session_tuple( "/bridge/A", "sid-A", { "name": "Maria" } ) ]
    loader = lambda p: { "user_id": "alice" }   # no last_activity_*
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
    )
    assert len( out ) == 1


def test_filter_excludes_originator_when_requested():
    raw = [
        _make_session_tuple( "/bridge/A", "sid-A", { "name": "Maria" } ),
        _make_session_tuple( "/bridge/B", "sid-B", { "name": "Tiberius" } ),
    ]
    loader = lambda p: { "user_id": "alice", "last_activity_epoch": 1000.0 }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
        originator_session_id            = "sid-A",
        include_originator               = False,
    )
    assert len( out ) == 1
    assert out[ 0 ][ "session_id" ] == "sid-B"


def test_filter_includes_originator_by_default():
    raw = [
        _make_session_tuple( "/bridge/A", "sid-A", { "name": "Maria" } ),
        _make_session_tuple( "/bridge/B", "sid-B", { "name": "Tiberius" } ),
    ]
    loader = lambda p: { "user_id": "alice", "last_activity_epoch": 1000.0 }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
        originator_session_id            = "sid-A",
        include_originator               = True,
    )
    assert len( out ) == 2


# ─── perform_fanout (AC4 + AC5 + F10) ───────────────────────────────────────


def test_fanout_happy_path( store, push_fn, captured_pushes ):
    sessions = [
        { "session_id": "sid-A", "persona_name": "Maria"   },
        { "session_id": "sid-B", "persona_name": "Tiberius" },
    ]
    successful, failed = perform_fanout(
        broadcast_id       = "bid-1",
        message            = "hello all",
        sessions           = sessions,
        sender_user_id     = "alice",
        store              = store,
        notification_queue = push_fn,
        build_sender_id    = lambda sid: f"sender-of-{sid}",
    )
    assert successful == 2
    assert failed == [ ]
    # Each call captured
    assert len( captured_pushes ) == 2
    assert captured_pushes[ 0 ][ "type" ]      == "user_initiated_message"
    assert captured_pushes[ 0 ][ "title" ]     == "action:broadcast_received"
    assert captured_pushes[ 0 ][ "sender_id" ] == "sender-of-sid-A"
    # broadcasts topic has both entries
    entries = store.read( "broadcasts", limit=10 )
    assert len( entries ) == 2
    assert { e[ "metadata" ][ "target_session_id" ] for e in entries } == { "sid-A", "sid-B" }


def test_fanout_continues_on_push_failure( store, captured_pushes ):
    """F10 + AC5: per-recipient failure does NOT abort the loop."""
    class _Q:
        def __init__( self ):
            self.calls = 0
        def push_notification( self, **kwargs ):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError( "transient push failure" )
            captured_pushes.append( kwargs )

    q = _Q()
    sessions = [
        { "session_id": "sid-A" }, { "session_id": "sid-B" }, { "session_id": "sid-C" },
    ]
    successful, failed = perform_fanout(
        broadcast_id       = "bid-1",
        message            = "hello",
        sessions           = sessions,
        sender_user_id     = "alice",
        store              = store,
        notification_queue = q,
        build_sender_id    = lambda sid: f"sid-of-{sid}",
    )
    assert successful == 2   # A + C
    assert failed == [ "sid-B" ]
    assert q.calls == 3   # all 3 attempted


def test_fanout_continues_on_store_failure( push_fn, captured_pushes ):
    """If store.post fails for one recipient, log + skip listener push too."""
    class _StoreFailFor:
        def __init__( self, fail_sid ):
            self.fail_sid = fail_sid
            self.posts    = 0
        def post( self, **kwargs ):
            self.posts += 1
            if kwargs[ "metadata" ][ "target_session_id" ] == self.fail_sid:
                raise RuntimeError( "store boom" )
            return { "ok": True }

    failing_store = _StoreFailFor( "sid-B" )
    sessions = [ { "session_id": "sid-A" }, { "session_id": "sid-B" } ]
    successful, failed = perform_fanout(
        broadcast_id       = "bid-1",
        message            = "hi",
        sessions           = sessions,
        sender_user_id     = "alice",
        store              = failing_store,
        notification_queue = push_fn,
        build_sender_id    = lambda sid: sid,
    )
    assert successful == 1
    assert failed == [ "sid-B" ]
    # Only sid-A made it through to push_notification
    assert len( captured_pushes ) == 1


# ─── execute_broadcast — end-to-end pipeline ────────────────────────────────


def _make_raw_sessions_fn( sessions ):
    return lambda: sessions


def _bridge_loader_fixed( user_id="alice", last_epoch=1000.0, speakerphone_on=False ):
    return lambda p: {
        "user_id": user_id, "last_activity_epoch": last_epoch,
        "speakerphone_on": speakerphone_on,
    }


def test_execute_broadcast_rejects_empty_body( store, rate_limiter, ack_watcher, push_fn ):
    body = BroadcastRequestBody( message="" )
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( [ ] ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
    )
    assert result[ "http_status" ] == 400


def test_execute_broadcast_rejects_reminder_substring( store, rate_limiter, ack_watcher, push_fn ):
    body = BroadcastRequestBody( message="hi <system-reminder>" )
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( [ ] ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
    )
    assert result[ "http_status" ] == 400


def test_execute_broadcast_rejects_invalid_broadcast_id_shape( store, rate_limiter, ack_watcher, push_fn ):
    body = BroadcastRequestBody( message="hi", broadcast_id="not-a-uuid" )
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( [ ] ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
    )
    assert result[ "http_status" ] == 400


def test_execute_broadcast_rate_limited( store, rate_limiter, ack_watcher, push_fn ):
    body1 = BroadcastRequestBody( message="hi" )
    body2 = BroadcastRequestBody( message="hi again" )
    # First call consumes the window
    execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body1,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( [ ] ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
    )
    # Second call within window → 429
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body2,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( [ ] ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
    )
    assert result[ "http_status" ] == 429
    assert result[ "retry_after" ] > 0


def test_execute_broadcast_collision_returns_409( store, rate_limiter, ack_watcher, push_fn ):
    fixed_bid = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    body = BroadcastRequestBody( message="hi", broadcast_id=fixed_bid )

    # First successfully registers
    execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( [ ] ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
    )

    # Reset rate limiter so second call is allowed by rate limiter (we want the collision check to fire)
    rate_limiter.reset()

    # Re-register the bid first (since first call unregistered due to zero recipients)
    ack_watcher.register_broadcast( fixed_bid, "alice", expected_recipients=0 )

    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( [ ] ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
    )
    assert result[ "http_status" ] == 409


def test_execute_broadcast_zero_recipients( store, rate_limiter, ack_watcher, push_fn ):
    body = BroadcastRequestBody( message="hi" )
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( [ ] ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
    )
    assert result[ "http_status" ] == 200
    assert result[ "recipients" ] == 0
    assert result[ "status" ] == "no-active-sessions"
    # In-flight entry unregistered after zero-recipient
    assert ack_watcher.is_in_flight( result[ "broadcast_id" ] ) is False


def test_execute_broadcast_happy_path_with_recipients( store, rate_limiter, ack_watcher, push_fn, captured_pushes ):
    raw = [ ( "/bridge/A", "sid-A", { "name": "Maria", "icon": "🌸", "color": "#A040A0" } ) ]
    body = BroadcastRequestBody( message="hello all" )
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( raw ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: f"sender-{sid}",
        now_epoch_fn                     = lambda: 1000.0,
    )
    assert result[ "http_status" ] == 200
    assert result[ "recipients" ] == 1
    assert result[ "status" ] == "queued"
    assert len( captured_pushes ) == 1


def test_execute_broadcast_inflight_pruned_mid_fanout( store, rate_limiter, ack_watcher, push_fn ):
    """
    require_ack=True but the in-flight entry gets unregistered between register and post-fanout
    (e.g., TTL prune in concurrent thread). Covers branch 355→358 false-arm.
    """
    fixed_bid = "f47ac10b-58cc-4372-a567-0e02b2c3d480"
    raw = [ ( "/bridge/A", "sid-A", { "name": "Maria" } ) ]

    def raw_sessions_with_side_effect():
        # Simulate a race: another thread unregistered the broadcast between register and fanout
        ack_watcher.unregister_broadcast( fixed_bid )
        return raw

    body = BroadcastRequestBody( message="hi", broadcast_id=fixed_bid )
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = raw_sessions_with_side_effect,
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
        now_epoch_fn                     = lambda: 1000.0,
    )
    # Fanout still happened; just the entry was gone for the update
    assert result[ "http_status" ] == 200
    assert result[ "recipients" ] == 1


def test_execute_broadcast_zero_recipients_require_ack_false( store, rate_limiter, ack_watcher, push_fn ):
    """Zero recipients + require_ack=False → unregister branch is the false arm (covers 331→333)."""
    body = BroadcastRequestBody( message="hi", require_ack=False )
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( [ ] ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
    )
    assert result[ "http_status" ] == 200
    assert result[ "recipients" ] == 0


def test_execute_broadcast_with_recipients_require_ack_false_no_inflight_update( store, rate_limiter, ack_watcher, push_fn ):
    """With recipients + require_ack=False → no in-flight entry exists, line 355 false-arm fires (covers 355→358)."""
    raw = [ ( "/bridge/A", "sid-A", { "name": "Maria" } ) ]
    body = BroadcastRequestBody( message="silent", require_ack=False )
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( raw ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
        now_epoch_fn                     = lambda: 1000.0,
    )
    assert result[ "http_status" ] == 200
    assert result[ "recipients" ] == 1
    assert ack_watcher.is_in_flight( result[ "broadcast_id" ] ) is False


def test_execute_broadcast_require_ack_false_skips_tracking( store, rate_limiter, ack_watcher, push_fn ):
    """require_ack=False: ack_watcher.register_broadcast is NOT called."""
    raw = [ ( "/bridge/A", "sid-A", { "name": "Maria" } ) ]
    body = BroadcastRequestBody( message="silent broadcast", require_ack=False )
    result = execute_broadcast(
        authenticated_user_id            = "alice",
        body                             = body,
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        notification_queue               = push_fn,
        active_session_threshold_seconds = 600,
        raw_sessions_fn                  = _make_raw_sessions_fn( raw ),
        bridge_loader                    = _bridge_loader_fixed(),
        build_sender_id                  = lambda sid: sid,
        now_epoch_fn                     = lambda: 1000.0,
    )
    assert result[ "http_status" ] == 200
    assert result[ "broadcast_id" ] is not None
    # require_ack=False → in_flight tracker is NOT populated for this bid
    assert ack_watcher.is_in_flight( result[ "broadcast_id" ] ) is False


# ─── init_commons_state — wiring smoke ──────────────────────────────────────


def test_init_commons_state_sets_singletons( store, rate_limiter, ack_watcher ):
    """init_commons_state writes the module-level singletons (called from main.py startup)."""
    from cosa.rest.routers import commons as commons_module
    init_commons_state( store, rate_limiter, ack_watcher, active_session_threshold_seconds=42.0 )
    assert commons_module._commons_store                    is store
    assert commons_module._commons_rate_limiter             is rate_limiter
    assert commons_module._commons_ack_watcher              is ack_watcher
    assert commons_module._active_session_threshold_seconds == 42.0


# ─── Step 6: RegisterQuestionRequest Pydantic validation ────────────────────


def test_register_question_request_happy_path():
    """All required fields populated; defaults applied."""
    req = RegisterQuestionRequest(
        topic            = "q-topic",
        question_id      = "qid-1234",
        asker_session_id = "abc12345",
    )
    assert req.topic            == "q-topic"
    assert req.question_id      == "qid-1234"
    assert req.asker_session_id == "abc12345"
    assert req.ttl_seconds      == 3600


def test_register_question_request_rejects_empty_topic():
    with pytest.raises( ValidationError ):
        RegisterQuestionRequest( topic="", question_id="q1", asker_session_id="sid" )


def test_register_question_request_rejects_topic_with_disallowed_chars():
    with pytest.raises( ValidationError ):
        RegisterQuestionRequest( topic="q.topic", question_id="q1", asker_session_id="sid" )


def test_register_question_request_rejects_oversize_question_id():
    with pytest.raises( ValidationError ):
        RegisterQuestionRequest( topic="t", question_id="a" * 65, asker_session_id="sid" )


def test_register_question_request_rejects_ttl_below_min():
    with pytest.raises( ValidationError ):
        RegisterQuestionRequest( topic="t", question_id="q1", asker_session_id="sid", ttl_seconds=0 )


def test_register_question_request_rejects_ttl_above_max():
    with pytest.raises( ValidationError ):
        RegisterQuestionRequest( topic="t", question_id="q1", asker_session_id="sid", ttl_seconds=604801 )


def test_register_question_request_rejects_empty_asker_session_id():
    with pytest.raises( ValidationError ):
        RegisterQuestionRequest( topic="t", question_id="q1", asker_session_id="" )


# ─── Step 6: make_question_inject_fn ────────────────────────────────────────


def test_make_question_inject_fn_pushes_notification_with_expected_shape( store, captured_pushes, push_fn ):
    """The inject_fn closure pushes a notification matching the AC4 framing."""
    inject = make_question_inject_fn(
        notification_queue = push_fn,
        user_id            = "user-A",
        question_id        = "qid-1",
        asker_session_id   = "asker-session-12345678",
        build_sender_id    = lambda sid: f"cc:{sid}",
    )
    entry = {
        "body"              : "answer body here",
        "persona_name"      : "Tiberius",
        "persona_icon"      : "🌑",
        "persona_color"     : "#000",
        "sender_session_id" : "answerer-session-abc",
        "ts"                : "2026-05-13T10:00:00+00:00",
    }
    inject( entry )

    assert len( captured_pushes ) == 1
    push = captured_pushes[ 0 ]
    assert push[ "type" ]              == "user_initiated_message"
    assert push[ "title" ]             == "action:commons_answer_received"
    assert push[ "sender_id" ]         == "cc:asker-session-12345678"
    assert push[ "job_id" ]            == "asker-se"  # first 8 chars
    assert push[ "user_id" ]           == "user-A"
    assert push[ "suppress_ding" ]     is True
    assert push[ "response_requested" ] is False
    payload = push[ "payload" ]
    assert payload[ "question_id" ]      == "qid-1"
    assert payload[ "body" ]             == "answer body here"
    assert payload[ "persona_name" ]     == "Tiberius"
    assert payload[ "persona_icon" ]     == "🌑"
    assert payload[ "answerer_session" ] == "answerer-session-abc"
    assert payload[ "answer_ts" ]        == "2026-05-13T10:00:00+00:00"


# ─── Step 6: execute_register_question ──────────────────────────────────────


@pytest.fixture
def question_watcher( store ):
    return CommonsQuestionWatcher(
        store        = store,
        per_user_max = 3,
        global_max   = 5,
    )


def _build_req( topic="t", qid="q1", sid="asker-sess", ttl=3600 ):
    return RegisterQuestionRequest(
        topic            = topic,
        question_id      = qid,
        asker_session_id = sid,
        ttl_seconds      = ttl,
    )


def test_execute_register_question_happy_path( question_watcher, push_fn ):
    """201 on success; question becomes in flight."""
    result = execute_register_question(
        authenticated_user_id = "user-A",
        body                  = _build_req( qid="q1" ),
        question_watcher      = question_watcher,
        notification_queue    = push_fn,
        build_sender_id       = lambda s: f"cc:{s}",
    )
    assert result[ "http_status" ] == 201
    assert result[ "question_id" ] == "q1"
    assert result[ "ttl_seconds" ] == 3600
    assert question_watcher.is_in_flight( "q1" ) is True


def test_execute_register_question_collision_returns_409( question_watcher, push_fn ):
    """Duplicate question_id → 409."""
    execute_register_question(
        authenticated_user_id = "user-A",
        body                  = _build_req( qid="q1" ),
        question_watcher      = question_watcher,
        notification_queue    = push_fn,
        build_sender_id       = lambda s: f"cc:{s}",
    )
    result = execute_register_question(
        authenticated_user_id = "user-A",
        body                  = _build_req( qid="q1" ),
        question_watcher      = question_watcher,
        notification_queue    = push_fn,
        build_sender_id       = lambda s: f"cc:{s}",
    )
    assert result[ "http_status" ] == 409
    assert "collision" in result[ "detail" ]


def test_execute_register_question_per_user_cap_returns_429( question_watcher, push_fn ):
    """Per-user cap exceeded → 429."""
    for i in range( 3 ):
        execute_register_question(
            authenticated_user_id = "user-A",
            body                  = _build_req( qid=f"q{i}" ),
            question_watcher      = question_watcher,
            notification_queue    = push_fn,
            build_sender_id       = lambda s: f"cc:{s}",
        )
    result = execute_register_question(
        authenticated_user_id = "user-A",
        body                  = _build_req( qid="q-overflow" ),
        question_watcher      = question_watcher,
        notification_queue    = push_fn,
        build_sender_id       = lambda s: f"cc:{s}",
    )
    assert result[ "http_status" ] == 429
    assert "cap reached" in result[ "detail" ]


def test_execute_register_question_global_cap_returns_429( store, push_fn ):
    """Global cap exceeded → 429 (different users)."""
    w = CommonsQuestionWatcher( store=store, per_user_max=100, global_max=2 )
    execute_register_question( authenticated_user_id="u1", body=_build_req( qid="q1" ),
                                question_watcher=w, notification_queue=push_fn,
                                build_sender_id=lambda s: f"cc:{s}" )
    execute_register_question( authenticated_user_id="u2", body=_build_req( qid="q2" ),
                                question_watcher=w, notification_queue=push_fn,
                                build_sender_id=lambda s: f"cc:{s}" )
    result = execute_register_question( authenticated_user_id="u3", body=_build_req( qid="q3" ),
                                         question_watcher=w, notification_queue=push_fn,
                                         build_sender_id=lambda s: f"cc:{s}" )
    assert result[ "http_status" ] == 429


# ─── Step 6: execute_unregister_question (T5) ───────────────────────────────


def test_execute_unregister_question_happy_path( question_watcher, push_fn ):
    """204 on successful removal."""
    execute_register_question(
        authenticated_user_id = "user-A",
        body                  = _build_req( qid="q1" ),
        question_watcher      = question_watcher,
        notification_queue    = push_fn,
        build_sender_id       = lambda s: f"cc:{s}",
    )
    result = execute_unregister_question(
        authenticated_user_id = "user-A",
        question_id           = "q1",
        question_watcher      = question_watcher,
    )
    assert result == { "http_status": 204 }


def test_execute_unregister_question_unknown_returns_404( question_watcher ):
    """Unknown question_id → uniform 404."""
    result = execute_unregister_question(
        authenticated_user_id = "user-A",
        question_id           = "ghost",
        question_watcher      = question_watcher,
    )
    assert result[ "http_status" ] == 404
    assert "not found or not owned" in result[ "detail" ]


def test_execute_unregister_question_wrong_owner_returns_404( question_watcher, push_fn ):
    """T5 — known question, wrong user → SAME uniform 404 (no enumeration)."""
    execute_register_question(
        authenticated_user_id = "user-A",
        body                  = _build_req( qid="q1" ),
        question_watcher      = question_watcher,
        notification_queue    = push_fn,
        build_sender_id       = lambda s: f"cc:{s}",
    )
    result = execute_unregister_question(
        authenticated_user_id = "user-B",
        question_id           = "q1",
        question_watcher      = question_watcher,
    )
    assert result[ "http_status" ] == 404
    assert "not found or not owned" in result[ "detail" ]
    # The record is NOT removed
    assert question_watcher.is_in_flight( "q1" ) is True


# ─── Step 6: init_commons_state accepts question_watcher ────────────────────


def test_init_commons_state_accepts_question_watcher( store, rate_limiter, ack_watcher, question_watcher ):
    """init_commons_state wires the question_watcher singleton too."""
    import cosa.rest.routers.commons as commons_module
    init_commons_state(
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        active_session_threshold_seconds = 600.0,
        question_watcher                 = question_watcher,
    )
    assert commons_module._commons_question_watcher is question_watcher


def test_init_commons_state_question_watcher_optional( store, rate_limiter, ack_watcher ):
    """Backward-compat: init_commons_state still accepts the Phase 2 4-arg signature."""
    import cosa.rest.routers.commons as commons_module
    init_commons_state(
        store                            = store,
        rate_limiter                     = rate_limiter,
        ack_watcher                      = ack_watcher,
        active_session_threshold_seconds = 600.0,
    )
    assert commons_module._commons_question_watcher is None


# ─── Phase 2.5/3.5 Step 2 — broadcast-history aggregator (AC1 + AC4-AC6 + AC9) ─


# Mock store with the same `_all_topic_names()` + `read()` surface as CommonsStore.
class _FakeStore:
    def __init__( self, topics_to_entries, raise_for_topics=None ):
        self._topics_to_entries = topics_to_entries
        self._raise_for_topics  = set( raise_for_topics or [ ] )

    def _all_topic_names( self ):
        return sorted( self._topics_to_entries.keys() )

    def read( self, topic, since=None, limit=50 ):
        if topic in self._raise_for_topics:
            raise FileNotFoundError( f"Synthetic: {topic}" )
        entries = self._topics_to_entries.get( topic, [ ] )
        if since is not None:
            entries = [ e for e in entries if e[ "ts" ] > since ]
        return entries[ :limit ]


def _make_entry( ts, topic_marker="x", sender_sid="sess-x", sender_user_id=None, target_sid=None, body="hello", broadcast_id=None ):
    md = { }
    if sender_user_id is not None: md[ "sender_user_id" ]    = sender_user_id
    if target_sid     is not None: md[ "target_session_id" ] = target_sid
    if broadcast_id   is not None: md[ "broadcast_id" ]      = broadcast_id
    return {
        "ts"                : ts,
        "sender_session_id" : sender_sid,
        "persona_name"      : f"persona-{topic_marker}",
        "persona_icon"      : "🌸",
        "persona_color"     : "#F06292",
        "body"              : body,
        "metadata"          : md,
    }


# ─── _resolve_since_cutoff ──────────────────────────────────────────────────


def test_resolve_since_cutoff_explicit_since_wins():
    """Caller-supplied `since_iso` is returned verbatim regardless of `hours` or now_fn."""
    got = _resolve_since_cutoff(
        since_iso  = "2026-05-14T00:00:00+00:00",
        hours      = 99,
        now_iso_fn = lambda: "2030-01-01T00:00:00+00:00",
    )
    assert got == "2026-05-14T00:00:00+00:00"


def test_resolve_since_cutoff_hours_window_computed_from_now():
    """When only `hours` supplied, return (now - hours) as ISO."""
    got = _resolve_since_cutoff(
        since_iso  = None,
        hours      = 24,
        now_iso_fn = lambda: "2026-05-14T20:00:00+00:00",
    )
    # 24h before 20:00 of 2026-05-14 → 2026-05-13T20:00:00+00:00
    assert got == "2026-05-13T20:00:00+00:00"


def test_resolve_since_cutoff_neither_returns_none():
    """When neither parameter supplied → no cutoff (return all retained)."""
    got = _resolve_since_cutoff(
        since_iso  = None,
        hours      = None,
        now_iso_fn = lambda: "2026-05-14T20:00:00+00:00",
    )
    assert got is None


def test_resolve_since_cutoff_handles_z_suffix_utc():
    """ISO `Z` suffix from JS `Date.toISOString()` is normalized to `+00:00` before parsing."""
    got = _resolve_since_cutoff(
        since_iso  = None,
        hours      = 1,
        now_iso_fn = lambda: "2026-05-14T20:00:00Z",
    )
    assert got == "2026-05-14T19:00:00+00:00"


# ─── _entry_passes_same_user_scoping ────────────────────────────────────────


def test_scoping_passes_via_sender_user_id():
    entry = _make_entry( "2026-05-14T19:00:00+00:00", sender_user_id="alice" )
    assert _entry_passes_same_user_scoping(
        entry, "alice", set(), lambda sid: None
    ) is True


def test_scoping_passes_via_target_session_id():
    entry = _make_entry( "2026-05-14T19:00:00+00:00", target_sid="my-sess" )
    assert _entry_passes_same_user_scoping(
        entry, "alice", { "my-sess" }, lambda sid: None
    ) is True


def test_scoping_passes_via_bridge_owner_match():
    entry = _make_entry( "2026-05-14T19:00:00+00:00", sender_sid="some-sess" )
    assert _entry_passes_same_user_scoping(
        entry, "alice", set(), lambda sid: "alice" if sid == "some-sess" else None
    ) is True


def test_scoping_passes_via_bridge_owner_graceful_none():
    """Bridge has no owner_user_id → graceful fallback, entry passes."""
    entry = _make_entry( "2026-05-14T19:00:00+00:00", sender_sid="some-sess" )
    assert _entry_passes_same_user_scoping(
        entry, "alice", set(), lambda sid: None
    ) is True


def test_scoping_rejects_when_bridge_owner_mismatch():
    """Bridge owner is non-None and doesn't match caller → reject."""
    entry = _make_entry( "2026-05-14T19:00:00+00:00", sender_sid="some-sess" )
    assert _entry_passes_same_user_scoping(
        entry, "alice", set(), lambda sid: "bob"
    ) is False


def test_scoping_rejects_when_no_sender_session_id():
    """No sender_session_id AND no metadata attribution → reject."""
    entry = _make_entry( "2026-05-14T19:00:00+00:00", sender_sid=None )
    assert _entry_passes_same_user_scoping(
        entry, "alice", set(), lambda sid: pytest.fail( "lookup should not run" )
    ) is False


def test_scoping_rejects_when_metadata_missing_entirely():
    """Entry with no metadata at all + sender bridge belongs to someone else → reject."""
    entry = { "ts": "2026-05-14T19:00:00+00:00", "sender_session_id": "other-sess" }
    assert _entry_passes_same_user_scoping(
        entry, "alice", set(), lambda sid: "bob"
    ) is False


def test_scoping_target_session_id_must_be_in_user_set():
    """target_session_id present but not in user_session_ids → branch fails, falls through to bridge check."""
    entry = _make_entry( "2026-05-14T19:00:00+00:00", target_sid="not-mine" )
    # Bridge owner mismatches → overall reject
    assert _entry_passes_same_user_scoping(
        entry, "alice", { "my-sess" }, lambda sid: "bob"
    ) is False


# ─── _project_history_entry ─────────────────────────────────────────────────


def test_project_history_entry_reserved_topic_kind():
    """Reserved topics get `topic_kind: reserved`."""
    e = _make_entry( "2026-05-14T19:00:00+00:00" )
    out = _project_history_entry( e, "broadcasts" )
    assert out[ "topic" ]      == "broadcasts"
    assert out[ "topic_kind" ] == "reserved"
    assert out[ "body" ]       == "hello"


def test_project_history_entry_free_form_topic_kind():
    """Non-reserved topics get `topic_kind: free-form`."""
    e = _make_entry( "2026-05-14T19:00:00+00:00" )
    out = _project_history_entry( e, "coord-notifications-js" )
    assert out[ "topic_kind" ] == "free-form"


def test_project_history_entry_handles_missing_metadata():
    """Entry without metadata still projects to a dict with metadata={}."""
    e = { "ts": "2026-05-14T19:00:00+00:00", "sender_session_id": "s", "body": "x" }
    out = _project_history_entry( e, "broadcasts" )
    assert out[ "metadata" ] == { }
    assert out[ "persona_name" ] is None


# ─── execute_broadcast_history ──────────────────────────────────────────────


def test_execute_broadcast_history_empty_store_returns_empty():
    """No topics in the store → empty entries list."""
    store  = _FakeStore( topics_to_entries={ } )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = None,
        limit                 = 100,
        excluded_topics       = [ "presence", "system-events" ],
        max_entries_ceiling   = 1000,
        user_session_ids_fn   = lambda: set(),
        bridge_owner_lookup   = lambda sid: None,
    )
    assert result[ "entries" ]     == [ ]
    assert result[ "since_used" ]  is None
    assert result[ "next_cursor" ] is None


def test_execute_broadcast_history_excludes_topics():
    """Entries from excluded topics never appear in output."""
    store = _FakeStore( topics_to_entries={
        "presence"       : [ _make_entry( "2026-05-14T19:00:00+00:00", "p", sender_user_id="alice" ) ],
        "system-events"  : [ _make_entry( "2026-05-14T19:00:01+00:00", "s", sender_user_id="alice" ) ],
        "broadcasts"     : [ _make_entry( "2026-05-14T19:00:02+00:00", "b", sender_user_id="alice" ) ],
    } )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = None,
        limit                 = 100,
        excluded_topics       = [ "presence", "system-events" ],
        max_entries_ceiling   = 1000,
        user_session_ids_fn   = lambda: set(),
        bridge_owner_lookup   = lambda sid: None,
    )
    assert len( result[ "entries" ] ) == 1
    assert result[ "entries" ][ 0 ][ "topic" ] == "broadcasts"


def test_execute_broadcast_history_merges_topics_newest_first():
    """Entries from multiple topics are merged and sorted by ts DESC."""
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [ _make_entry( "2026-05-14T19:00:00+00:00", "b", sender_user_id="alice", body="oldest" ) ],
        "free-topic" : [
            _make_entry( "2026-05-14T19:30:00+00:00", "f", sender_user_id="alice", body="middle" ),
            _make_entry( "2026-05-14T20:00:00+00:00", "f", sender_user_id="alice", body="newest" ),
        ],
    } )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = None,
        limit                 = 100,
        excluded_topics       = [ ],
        max_entries_ceiling   = 1000,
        user_session_ids_fn   = lambda: set(),
        bridge_owner_lookup   = lambda sid: None,
    )
    bodies = [ e[ "body" ] for e in result[ "entries" ] ]
    assert bodies == [ "newest", "middle", "oldest" ]


def test_execute_broadcast_history_respects_caller_limit():
    """Caller's `limit` (when below max ceiling) caps the response."""
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [ _make_entry( f"2026-05-14T19:{i:02d}:00+00:00", "b", sender_user_id="alice" ) for i in range( 10 ) ],
    } )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = None,
        limit                 = 3,
        excluded_topics       = [ ],
        max_entries_ceiling   = 1000,
        user_session_ids_fn   = lambda: set(),
        bridge_owner_lookup   = lambda sid: None,
    )
    assert len( result[ "entries" ] ) == 3


def test_execute_broadcast_history_caps_at_max_ceiling():
    """Even if caller asks for `limit > max_entries_ceiling`, response is capped at ceiling."""
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [ _make_entry( f"2026-05-14T19:{i:02d}:00+00:00", "b", sender_user_id="alice" ) for i in range( 50 ) ],
    } )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = None,
        limit                 = 10000,    # absurdly high
        excluded_topics       = [ ],
        max_entries_ceiling   = 5,         # ceiling wins
        user_session_ids_fn   = lambda: set(),
        bridge_owner_lookup   = lambda sid: None,
    )
    assert len( result[ "entries" ] ) == 5


def test_execute_broadcast_history_skips_missing_topic_file():
    """FileNotFoundError from `store.read()` on one topic must not crash the aggregator."""
    store = _FakeStore(
        topics_to_entries = {
            "broadcasts"      : [ _make_entry( "2026-05-14T19:00:00+00:00", "b", sender_user_id="alice" ) ],
            "missing-on-disk" : [ ],     # store reports it via _all_topic_names but read() will raise
        },
        raise_for_topics = [ "missing-on-disk" ],
    )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = None,
        limit                 = 100,
        excluded_topics       = [ ],
        max_entries_ceiling   = 1000,
        user_session_ids_fn   = lambda: set(),
        bridge_owner_lookup   = lambda sid: None,
    )
    assert len( result[ "entries" ] ) == 1
    assert result[ "entries" ][ 0 ][ "topic" ] == "broadcasts"


def test_execute_broadcast_history_resolves_hours_to_cutoff():
    """`hours` parameter computes a `since_used` cutoff in the response."""
    store = _FakeStore( topics_to_entries={ "broadcasts": [ ] } )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = 24,
        limit                 = 100,
        excluded_topics       = [ ],
        max_entries_ceiling   = 1000,
        user_session_ids_fn   = lambda: set(),
        bridge_owner_lookup   = lambda sid: None,
        now_iso_fn            = lambda: "2026-05-14T20:00:00+00:00",
    )
    assert result[ "since_used" ] == "2026-05-13T20:00:00+00:00"


def test_execute_broadcast_history_filters_other_users_entries():
    """Entries that fail same-user scoping are dropped."""
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [
            _make_entry( "2026-05-14T19:00:00+00:00", "alice-b", sender_user_id="alice", body="mine" ),
            _make_entry( "2026-05-14T19:30:00+00:00", "bob-b",   sender_user_id="bob",   body="theirs" ),
        ],
    } )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = None,
        limit                 = 100,
        excluded_topics       = [ ],
        max_entries_ceiling   = 1000,
        user_session_ids_fn   = lambda: set(),
        bridge_owner_lookup   = lambda sid: "bob",   # bridges all belong to bob
    )
    bodies = [ e[ "body" ] for e in result[ "entries" ] ]
    assert bodies == [ "mine" ]


def test_execute_broadcast_history_includes_target_session_attribution():
    """Entries whose `target_session_id` matches a user-owned session pass scoping."""
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [
            _make_entry( "2026-05-14T19:00:00+00:00", "incoming", sender_user_id="bob",
                         target_sid="alice-sess-1", body="addressed-to-me" ),
        ],
    } )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = None,
        limit                 = 100,
        excluded_topics       = [ ],
        max_entries_ceiling   = 1000,
        user_session_ids_fn   = lambda: { "alice-sess-1" },
        bridge_owner_lookup   = lambda sid: "bob",
    )
    assert len( result[ "entries" ] ) == 1
    assert result[ "entries" ][ 0 ][ "body" ] == "addressed-to-me"


# ─── _dedupe_broadcasts_by_id ──────────────────────────────────────────────
# Per `src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md` —
# collapse Phase 2 per-recipient fanout rows to one admin-overview row.


def test_dedupe_broadcasts_collapses_same_broadcast_id():
    """Five fanout rows sharing one broadcast_id collapse to one row."""
    bid     = "0a2b0b2e-2165-47d9-9f74-e969ca796ba4"
    merged  = [
        ( "broadcasts", _make_entry( "2026-05-15T14:00:00+00:00", target_sid=f"recip-{i}", broadcast_id=bid ) )
        for i in range( 5 )
    ]
    out = _dedupe_broadcasts_by_id( merged )
    assert len( out ) == 1
    assert out[ 0 ][ 0 ] == "broadcasts"


def test_dedupe_broadcasts_preserves_distinct_broadcast_ids():
    """Two distinct broadcasts with their own fanout sets stay as two rows."""
    bid_a   = "11111111-1111-4111-8111-111111111111"
    bid_b   = "22222222-2222-4222-8222-222222222222"
    merged  = [
        ( "broadcasts", _make_entry( "2026-05-15T14:00:00+00:00", target_sid=f"a-{i}", broadcast_id=bid_a ) )
        for i in range( 3 )
    ] + [
        ( "broadcasts", _make_entry( "2026-05-15T14:05:00+00:00", target_sid=f"b-{i}", broadcast_id=bid_b ) )
        for i in range( 3 )
    ]
    out      = _dedupe_broadcasts_by_id( merged )
    kept_ids = sorted( e[ "metadata" ][ "broadcast_id" ] for ( _t, e ) in out )
    assert kept_ids == [ bid_a, bid_b ]


def test_dedupe_broadcasts_strips_target_session_id_from_kept_row():
    """The dedup'd row represents the broadcast, not any single recipient slice."""
    bid    = "33333333-3333-4333-8333-333333333333"
    merged = [
        ( "broadcasts", _make_entry( "2026-05-15T14:00:00+00:00", target_sid="recip-A", broadcast_id=bid ) ),
        ( "broadcasts", _make_entry( "2026-05-15T14:00:00+00:00", target_sid="recip-B", broadcast_id=bid ) ),
    ]
    out = _dedupe_broadcasts_by_id( merged )
    assert len( out ) == 1
    assert "target_session_id" not in out[ 0 ][ 1 ][ "metadata" ]
    assert out[ 0 ][ 1 ][ "metadata" ][ "broadcast_id" ] == bid


def test_dedupe_does_not_mutate_input():
    """Input list and its entries must remain unchanged after dedupe."""
    bid    = "44444444-4444-4444-8444-444444444444"
    e1     = _make_entry( "2026-05-15T14:00:00+00:00", target_sid="recip-A", broadcast_id=bid )
    e2     = _make_entry( "2026-05-15T14:00:00+00:00", target_sid="recip-B", broadcast_id=bid )
    merged = [ ( "broadcasts", e1 ), ( "broadcasts", e2 ) ]
    _dedupe_broadcasts_by_id( merged )
    assert e1[ "metadata" ][ "target_session_id" ] == "recip-A"
    assert e2[ "metadata" ][ "target_session_id" ] == "recip-B"
    assert len( merged ) == 2


def test_dedupe_passes_through_non_broadcasts_topics():
    """`broadcast-acks` per-recipient rows are intentional and must NOT be collapsed."""
    bid    = "55555555-5555-4555-8555-555555555555"
    merged = [
        ( "broadcast-acks", _make_entry( "2026-05-15T14:00:00+00:00", target_sid="recip-A", broadcast_id=bid ) ),
        ( "broadcast-acks", _make_entry( "2026-05-15T14:00:00+00:00", target_sid="recip-B", broadcast_id=bid ) ),
        ( "free-topic",     _make_entry( "2026-05-15T14:00:00+00:00", body="chatter" ) ),
    ]
    out = _dedupe_broadcasts_by_id( merged )
    assert len( out ) == 3
    assert [ t for ( t, _e ) in out ] == [ "broadcast-acks", "broadcast-acks", "free-topic" ]


def test_dedupe_passes_through_broadcasts_entry_missing_broadcast_id():
    """Defensive — malformed broadcasts entry (no broadcast_id) must not vanish."""
    merged = [
        ( "broadcasts", _make_entry( "2026-05-15T14:00:00+00:00", target_sid="recip-A", body="malformed-1" ) ),
        ( "broadcasts", _make_entry( "2026-05-15T14:00:01+00:00", target_sid="recip-B", body="malformed-2" ) ),
    ]
    out = _dedupe_broadcasts_by_id( merged )
    assert len( out ) == 2
    assert [ e[ "body" ] for ( _t, e ) in out ] == [ "malformed-1", "malformed-2" ]


def test_dedupe_passes_through_broadcasts_entry_with_non_string_broadcast_id():
    """Defensive — non-string broadcast_id must not crash the type check."""
    merged = [
        ( "broadcasts", { "ts": "2026-05-15T14:00:00+00:00", "metadata": { "broadcast_id": 42 }, "body": "weird" } ),
    ]
    out = _dedupe_broadcasts_by_id( merged )
    assert len( out ) == 1
    assert out[ 0 ][ 1 ][ "body" ] == "weird"


def test_execute_broadcast_history_dedupes_broadcast_fanout_end_to_end():
    """End-to-end: 5-recipient broadcast through the aggregator yields one entry."""
    bid   = "0a2b0b2e-2165-47d9-9f74-e969ca796ba4"
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [
            _make_entry( f"2026-05-15T14:00:0{i}+00:00", sender_user_id="alice",
                         target_sid=f"recip-{i}", broadcast_id=bid )
            for i in range( 5 )
        ],
    } )
    result = execute_broadcast_history(
        authenticated_user_id = "alice",
        store                 = store,
        since_iso             = None,
        hours                 = None,
        limit                 = 100,
        excluded_topics       = [ ],
        max_entries_ceiling   = 1000,
        user_session_ids_fn   = lambda: set(),
        bridge_owner_lookup   = lambda sid: None,
    )
    assert len( result[ "entries" ] ) == 1
    assert result[ "entries" ][ 0 ][ "metadata" ][ "broadcast_id" ] == bid
    assert "target_session_id" not in result[ "entries" ][ 0 ][ "metadata" ]

