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
    _load_bridge_fields,
    _body_contains_reminder_framing,
    build_pseudo_sender_id,
    execute_broadcast,
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


# ─── filter_and_project_sessions (AC2 + T7 + T8) ────────────────────────────


def _make_session_tuple( path: str, sid: str, persona: dict ):
    """Mimics find_active_voice_persona_sessions return shape."""
    return ( path, sid, persona )


def test_filter_includes_same_user():
    raw = [
        _make_session_tuple( "/bridge/A", "sid-A", { "name": "Maria", "icon": "🌸", "color": "#A040A0" } ),
    ]
    loader = lambda p: { "user_id": "alice", "last_activity_epoch": 1000.0 }
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
    loader = lambda p: { "user_id": "bob", "last_activity_epoch": 1000.0 }
    out = filter_and_project_sessions(
        raw_sessions                     = raw,
        authenticated_user_id            = "alice",
        active_session_threshold_seconds = 600,
        now_epoch                        = 1000.0,
        bridge_loader                    = loader,
    )
    assert out == [ ]


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
    loader = lambda p: { "user_id": "alice", "last_activity_epoch": 100.0 }
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
