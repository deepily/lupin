"""
Unit tests for WG-8 — consumer-thread heartbeat exposure via pool-status.

The consumer worker writes `running_queue.last_consumer_heartbeat_at` at the
top of each loop iteration. `/api/queue/pool-status` reports
`seconds_since_heartbeat` so callers (operators or future watchdogs) can flag
a frozen consumer.

These tests exercise the get_pool_status payload computation in isolation
without spinning up an actual consumer thread.

Created: 2026-04-28 (WG-8)
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _make_running_queue_stub( hb_at, threshold_secs=120 ):
    """
    Build a minimal stub mimicking RunningFifoQueue.get_pool_status() preconditions.

    We import the real class but bypass __init__ to avoid the heavy graph
    (websocket_mgr, snapshot_mgr, timer threads, etc.). Then set the
    attributes get_pool_status reads.
    """
    from cosa.rest.running_fifo_queue import RunningFifoQueue
    import threading

    rq = RunningFifoQueue.__new__( RunningFifoQueue )
    rq._agentic_futures      = { }
    rq._agentic_futures_lock = threading.RLock()
    rq._pool_max_workers     = 3
    rq._monopolize_active    = None   # Shape-B (bug fe375cf6): get_pool_status reads this to exclude the out-of-pool monopolizer
    rq.last_consumer_heartbeat_at        = hb_at
    rq._consumer_stall_threshold_seconds = threshold_secs
    return rq


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────

def test_pool_status_heartbeat_none_when_consumer_never_ticked():
    rq = _make_running_queue_stub( hb_at=None )
    payload = rq.get_pool_status()
    assert payload[ "last_consumer_heartbeat_at" ] is None
    assert payload[ "seconds_since_heartbeat" ]    is None
    assert payload[ "consumer_stalled" ]           is False


def test_pool_status_heartbeat_recent_not_stalled():
    rq = _make_running_queue_stub( hb_at=datetime.now() - timedelta( seconds=5 ) )
    payload = rq.get_pool_status()
    assert payload[ "last_consumer_heartbeat_at" ] is not None
    assert payload[ "seconds_since_heartbeat" ] is not None
    assert 4 <= payload[ "seconds_since_heartbeat" ] < 10
    assert payload[ "consumer_stalled" ] is False
    assert payload[ "consumer_stall_threshold_secs" ] == 120


def test_pool_status_heartbeat_old_marks_stalled():
    rq = _make_running_queue_stub( hb_at=datetime.now() - timedelta( seconds=300 ) )
    payload = rq.get_pool_status()
    assert payload[ "seconds_since_heartbeat" ] >= 300
    assert payload[ "consumer_stalled" ] is True


def test_pool_status_heartbeat_threshold_boundary():
    """At exactly the threshold (-not yet-stalled), and just past it (stalled)."""
    rq_below = _make_running_queue_stub(
        hb_at=datetime.now() - timedelta( seconds=119 ),
        threshold_secs=120,
    )
    assert rq_below.get_pool_status()[ "consumer_stalled" ] is False

    rq_above = _make_running_queue_stub(
        hb_at=datetime.now() - timedelta( seconds=121 ),
        threshold_secs=120,
    )
    assert rq_above.get_pool_status()[ "consumer_stalled" ] is True


def test_pool_status_heartbeat_iso_format_when_set():
    """`last_consumer_heartbeat_at` is reported as ISO string (JSON-friendly)."""
    fixed = datetime( 2026, 4, 28, 12, 0, 0 )
    rq = _make_running_queue_stub( hb_at=fixed )
    payload = rq.get_pool_status()
    assert payload[ "last_consumer_heartbeat_at" ] == fixed.isoformat()


def test_pool_status_includes_inflight_and_pending():
    """Backward compat: pre-existing keys unchanged."""
    rq = _make_running_queue_stub( hb_at=None )
    payload = rq.get_pool_status()
    assert "inflight_agentic_jobs" in payload
    assert "pending_in_pool"       in payload
    assert "max_agentic_workers"   in payload
    assert payload[ "max_agentic_workers" ] == 3
