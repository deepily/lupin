#!/usr/bin/env python3
"""
Arbiter fleet-snapshot store — the server-side cache behind the v2.1
`/api/arbiter/fleet-snapshot` surface (arbiter design `03` §10.4, redline C2).

A tiny thread-safe singleton holding the latest fleet snapshot the Heartbeat
Arbiter produces, so `:7999` can serve it from a distance — mirroring how
`RunningFifoQueue.get_pool_status()` backs `GET /api/queue/pool-status`.

Two write paths converge here (design §10.4):
    - **in-pool arbiter** (runs inside the :7999 process) updates this singleton
      directly via `set_snapshot()` — no HTTP hop;
    - **standalone arbiter** (separate process) POSTs to
      `POST /api/arbiter/fleet-snapshot`, whose handler calls `set_snapshot()`.

Either way `GET /api/arbiter/fleet-snapshot` reads the cached value via
`get_snapshot()`. No standalone arbiter HTTP server (redline C2) — one HTTP
surface, reusing the existing auth.
"""
import threading
from typing import Optional


_lock     = threading.Lock()
_snapshot = None   # the latest fleet snapshot dict (build_snapshot output), or None


def set_snapshot( snapshot: dict ) -> None:
    """
    Replace the cached fleet snapshot (last-writer-wins).

    Requires:
        - snapshot is a JSON-able dict (build_snapshot output) or None

    Ensures:
        - the cached snapshot becomes `snapshot` under the lock
        - never raises
    """
    global _snapshot
    with _lock:
        _snapshot = snapshot


def get_snapshot() -> Optional[ dict ]:
    """
    Read the cached fleet snapshot.

    Ensures:
        - returns the latest snapshot dict, or None if none pushed yet
        - read under the lock (consistent with set_snapshot); never raises
    """
    with _lock:
        return _snapshot


def clear_snapshot() -> None:
    """Reset the cache to None (test hygiene + cold-start). Never raises."""
    global _snapshot
    with _lock:
        _snapshot = None


def quick_smoke_test():
    """Self-contained smoke test. Returns True or raises AssertionError."""
    clear_snapshot()
    assert get_snapshot() is None
    set_snapshot( { "session_count": 2, "sessions": [ ] } )
    assert get_snapshot()[ "session_count" ] == 2
    set_snapshot( { "session_count": 5 } )                 # last-writer-wins
    assert get_snapshot()[ "session_count" ] == 5
    clear_snapshot()
    assert get_snapshot() is None
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"arbiter_snapshot_store smoke: {'PASS' if ok else 'FAIL'}" )
