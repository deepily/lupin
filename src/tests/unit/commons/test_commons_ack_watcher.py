"""
Unit tests for commons_ack_watcher (Phase 2 step 4).

Per AC7 + T9 (Pass 2) of
src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md.

Coverage target: 100% lines + branches + functions (AC12 hard gate).
"""

import tempfile
import threading
import time
from unittest.mock import patch

import pytest

from cosa.rest.commons_ack_watcher import (
    CommonsAckWatcher,
    _InFlightEntry,
)
from lupin_mcp.commons_store import CommonsStore


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def store():
    """Fresh CommonsStore in a tempdir."""
    with tempfile.TemporaryDirectory() as tmp:
        yield CommonsStore( tmp )


@pytest.fixture
def captured_pushes():
    """Mutable list to collect push_notification calls."""
    return [ ]


@pytest.fixture
def push_fn( captured_pushes ):
    """Mock push_notification_fn that captures all kwargs."""
    def _capture( **kwargs ):
        captured_pushes.append( kwargs )
    return _capture


@pytest.fixture
def watcher( store, push_fn ):
    """A fresh CommonsAckWatcher bound to the tempdir store and mock push_fn."""
    return CommonsAckWatcher( store=store, push_notification_fn=push_fn, poll_interval_seconds=0.05 )


def _post_ack( store: CommonsStore, broadcast_id: str, status: str = "completed",
               sender_session_id: str = "sess-1", persona_name: str = "Maria" ):
    """Helper: post a single ack entry with the broadcast_id correlation."""
    return store.post(
        topic             = "broadcast-acks",
        body              = status,
        sender_session_id = sender_session_id,
        persona_name      = persona_name,
        persona_icon      = "🌸",
        persona_color     = "#A040A0",
        metadata          = { "kind": "ack", "broadcast_id": broadcast_id, "status": status, "body_summary": "ok" },
    )


# ─── _InFlightEntry plain-data class ────────────────────────────────────────


def test_inflight_entry_default_received_count():
    """_InFlightEntry initializes received_acks=0."""
    e = _InFlightEntry( originating_user_id="u1", expected_recipients=3, expires_at_monotonic=999.0 )
    assert e.originating_user_id  == "u1"
    assert e.expected_recipients  == 3
    assert e.expires_at_monotonic == 999.0
    assert e.received_acks        == 0


# ─── In-flight tracker ──────────────────────────────────────────────────────


def test_register_broadcast_inserts( watcher ):
    """register_broadcast stores the entry and makes is_in_flight return True."""
    watcher.register_broadcast( "bid-1", "user-A", 3 )
    assert watcher.is_in_flight( "bid-1" ) is True


def test_register_broadcast_collision_raises( watcher ):
    """Second register_broadcast with same bid raises ValueError (T9 atomic)."""
    watcher.register_broadcast( "bid-1", "user-A", 3 )
    with pytest.raises( ValueError, match="broadcast_id collision" ):
        watcher.register_broadcast( "bid-1", "user-A", 3 )


def test_register_after_unregister_succeeds( watcher ):
    """After unregister, a fresh register with same bid is allowed."""
    watcher.register_broadcast( "bid-1", "user-A", 3 )
    watcher.unregister_broadcast( "bid-1" )
    watcher.register_broadcast( "bid-1", "user-A", 3 )   # must not raise
    assert watcher.is_in_flight( "bid-1" ) is True


def test_unregister_unknown_silent( watcher ):
    """unregister_broadcast on a never-seen bid does not raise."""
    watcher.unregister_broadcast( "bid-never-registered" )


def test_is_in_flight_unknown_returns_false( watcher ):
    """is_in_flight on a never-registered bid returns False."""
    assert watcher.is_in_flight( "bid-unknown" ) is False


# ─── TTL semantics ──────────────────────────────────────────────────────────


def test_register_expired_entry_pruned_on_reregister( store, push_fn ):
    """An entry past its TTL is pruned + a re-register with same bid succeeds."""
    w = CommonsAckWatcher( store=store, push_notification_fn=push_fn, in_flight_ttl_seconds=0.05 )
    w.register_broadcast( "bid-1", "user-A", 1 )
    time.sleep( 0.1 )   # let TTL elapse
    # Re-register should work because prune fires inside register_broadcast
    w.register_broadcast( "bid-1", "user-A", 1 )   # must not raise
    assert w.is_in_flight( "bid-1" ) is True


def test_is_in_flight_returns_false_after_ttl( store, push_fn ):
    """is_in_flight prunes + returns False once TTL passes."""
    w = CommonsAckWatcher( store=store, push_notification_fn=push_fn, in_flight_ttl_seconds=0.05 )
    w.register_broadcast( "bid-1", "user-A", 1 )
    assert w.is_in_flight( "bid-1" ) is True
    time.sleep( 0.1 )
    assert w.is_in_flight( "bid-1" ) is False


# ─── Daemon lifecycle ───────────────────────────────────────────────────────


def test_start_stop_lifecycle( watcher ):
    """start() spawns; stop() joins cleanly."""
    watcher.start()
    assert watcher._thread is not None
    assert watcher._thread.is_alive()
    watcher.stop( join_timeout=2.0 )
    assert not watcher._thread.is_alive()


def test_start_idempotent( watcher ):
    """Second start() on a live watcher is a no-op."""
    watcher.start()
    first = watcher._thread
    watcher.start()
    assert watcher._thread is first
    watcher.stop( join_timeout=2.0 )


def test_stop_before_start_safe( watcher ):
    """stop() on a never-started watcher does not raise."""
    watcher.stop()


def test_restart_works( watcher ):
    """start() → stop() → start() works (covers thread-not-alive branch)."""
    watcher.start()
    watcher.stop( join_timeout=2.0 )
    watcher.start()
    assert watcher._thread.is_alive()
    watcher.stop( join_timeout=2.0 )


# ─── Startup last_seen_ts initialization (AC7 cursor) ───────────────────────


def test_startup_skips_existing_acks( store, push_fn ):
    """
    A pre-existing ack in the topic file is NOT replayed when the watcher starts —
    last_seen_ts is initialized to the topmost (newest) entry's ts.
    """
    # Seed an existing ack BEFORE the watcher starts
    _post_ack( store, "bid-old" )

    w = CommonsAckWatcher( store=store, push_notification_fn=push_fn, poll_interval_seconds=10.0 )
    w._initialize_last_seen_ts()
    assert w._initialized_last_seen is True
    assert w._last_seen_ts is not None

    # Register a NEW broadcast and post a fresh ack
    w.register_broadcast( "bid-new", "user-A", 1 )
    time.sleep( 0.01 )   # ensure new ts strictly greater
    _post_ack( store, "bid-new" )

    dispatched = w.tick()
    assert dispatched == 1   # only the new ack fires, not the pre-existing one


def test_startup_with_no_acks( watcher ):
    """Watcher init with empty broadcast-acks file leaves _last_seen_ts=None."""
    watcher._initialize_last_seen_ts()
    assert watcher._last_seen_ts is None
    assert watcher._initialized_last_seen is True


def test_startup_init_handles_read_failure( store, push_fn ):
    """Watcher init swallows store.read exceptions."""
    w = CommonsAckWatcher( store=store, push_notification_fn=push_fn, debug=True )
    with patch.object( w.store, "read", side_effect=RuntimeError( "boom" ) ):
        w._initialize_last_seen_ts()   # must not raise
    assert w._initialized_last_seen is True
    assert w._last_seen_ts is None


# ─── tick() core behavior ───────────────────────────────────────────────────


def test_tick_dispatches_matching_ack( watcher, store, captured_pushes ):
    """Tick fires push for an ack whose broadcast_id is in flight."""
    watcher.register_broadcast( "bid-1", "user-A", 1 )
    _post_ack( store, "bid-1" )
    dispatched = watcher.tick()
    assert dispatched == 1
    assert len( captured_pushes ) == 1
    pushed = captured_pushes[ 0 ]
    assert pushed[ "type" ]    == "commons_broadcast_ack"
    assert pushed[ "user_id" ] == "user-A"
    assert pushed[ "payload" ][ "broadcast_id" ] == "bid-1"
    assert pushed[ "payload" ][ "status" ]       == "completed"
    assert pushed[ "payload" ][ "persona_name" ] == "Maria"


def test_tick_ignores_unknown_broadcast_id( watcher, store, captured_pushes ):
    """Ack for a bid NOT in flight is silently ignored."""
    _post_ack( store, "bid-not-tracked" )
    dispatched = watcher.tick()
    assert dispatched == 0
    assert captured_pushes == [ ]


def test_tick_ignores_ack_with_missing_broadcast_id( watcher, store, captured_pushes ):
    """Ack entry whose metadata lacks broadcast_id is skipped."""
    store.post(
        topic             = "broadcast-acks",
        body              = "completed",
        sender_session_id = "sess",
        persona_name      = "X",
        persona_icon      = "?",
        persona_color     = "#000",
        metadata          = { "kind": "ack", "status": "completed" },   # NO broadcast_id
    )
    dispatched = watcher.tick()
    assert dispatched == 0


def test_tick_advances_last_seen_ts( watcher, store ):
    """After tick, _last_seen_ts moves forward to the latest entry."""
    watcher.register_broadcast( "bid-1", "user-A", 2 )
    _post_ack( store, "bid-1" )
    time.sleep( 0.01 )
    _post_ack( store, "bid-1" )
    initial_last = watcher._last_seen_ts
    watcher.tick()
    assert watcher._last_seen_ts is not None
    if initial_last is not None:
        assert watcher._last_seen_ts > initial_last


def test_tick_increments_received_acks_count( watcher, store ):
    """Each dispatched ack increments the in-flight entry's received_acks."""
    watcher.register_broadcast( "bid-1", "user-A", 3 )
    _post_ack( store, "bid-1" )
    _post_ack( store, "bid-1" )
    watcher.tick()
    entry = watcher._in_flight[ "bid-1" ]
    assert entry.received_acks == 2


def test_tick_with_no_new_entries_leaves_last_seen_unchanged( watcher, store ):
    """
    Tick over empty broadcast-acks file → _last_seen_ts stays None
    (covers branch 218 false-arm: latest_ts stayed at initial value).
    """
    initial = watcher._last_seen_ts
    assert watcher.tick() == 0
    assert watcher._last_seen_ts == initial


def test_tick_handles_filenotfound( store, push_fn ):
    """If broadcast-acks file is missing (race), tick returns 0 cleanly."""
    w = CommonsAckWatcher( store=store, push_notification_fn=push_fn )
    with patch.object( w.store, "read", side_effect=FileNotFoundError( "race" ) ):
        assert w.tick() == 0


def test_tick_swallows_push_exception( watcher, store, captured_pushes ):
    """A push_notification_fn raise should not break the tick loop."""
    watcher.debug = True
    def boom( **kwargs ):
        raise RuntimeError( "push down" )
    watcher.push_notification_fn = boom
    watcher.register_broadcast( "bid-1", "user-A", 1 )
    _post_ack( store, "bid-1" )
    assert watcher.tick() == 1   # still dispatched (count++); just push fails


def test_tick_prunes_expired_before_lookup( store, push_fn ):
    """
    If a broadcast's TTL expired before the ack arrives, tick prunes it +
    the ack is treated as unknown (silently ignored).
    """
    w = CommonsAckWatcher( store=store, push_notification_fn=push_fn, in_flight_ttl_seconds=0.05 )
    w.register_broadcast( "bid-1", "user-A", 1 )
    time.sleep( 0.1 )   # let TTL elapse BEFORE the ack
    _post_ack( store, "bid-1" )
    assert w.tick() == 0


# ─── Run-loop integration (slow but small) ──────────────────────────────────


def test_run_loop_invokes_tick( store, push_fn ):
    """Daemon loop invokes tick() at least once before stop."""
    w = CommonsAckWatcher( store=store, push_notification_fn=push_fn, poll_interval_seconds=0.05 )
    call_count = { "n": 0 }

    def tick_and_stop():
        call_count[ "n" ] += 1
        w._stop_event.set()
        return 0

    with patch.object( w, "tick", side_effect=tick_and_stop ):
        w.start()
        w._thread.join( timeout=3.0 )
    assert call_count[ "n" ] >= 1


def test_run_loop_swallows_tick_exception( store, push_fn ):
    """If tick raises, the loop catches + the daemon stays alive."""
    w = CommonsAckWatcher( store=store, push_notification_fn=push_fn, poll_interval_seconds=0.05, debug=True )
    call_count = { "n": 0 }

    def flaky_tick():
        call_count[ "n" ] += 1
        if call_count[ "n" ] == 1:
            raise RuntimeError( "transient" )
        w._stop_event.set()
        return 0

    with patch.object( w, "tick", side_effect=flaky_tick ):
        w.start()
        w._thread.join( timeout=3.0 )
    assert call_count[ "n" ] >= 2   # loop survived the exception + retried
