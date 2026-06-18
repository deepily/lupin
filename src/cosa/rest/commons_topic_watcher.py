"""
Abstract base class for commons topic watchers.

Per Phase 3 Q1 (hybrid base class) + F13-fit (template-method pattern) of
src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md.

`CommonsTopicWatcher` owns the lifecycle scaffolding shared by all watcher
subclasses that tail a commons topic and dispatch on matches:

- Daemon thread (start / stop / _run_loop)
- threading.Lock + in-flight registry dict
- Protected `_register(record_id, record)` / `_unregister(record_id)` —
  atomic insert-or-raise (T9 mirror) and silent pop, both lock-guarded.
- `_prune_expired_locked(now_monotonic)` — caller must hold `self._lock`;
  removes entries past their `expires_at_monotonic` field.

Subclasses (e.g. `CommonsAckWatcher`) provide:

- Domain-typed in-flight record class (must expose `expires_at_monotonic`)
- Domain-named public API wrapping `_register` / `_unregister`
  (per F13-fit: `register_broadcast`, `register_question`, etc.)
- `_initialize_last_seen_ts()` — topic-specific cursor seed at startup
- `tick()` — topic-specific dispatch logic

**Thread-safety contract** (T6 ratification):
- All mutations of `self._in_flight` happen under `with self._lock:`.
- Lookup happens under lock; dispatch (calling the inject_fn / push_fn) happens
  OUTSIDE the lock to avoid blocking the lock on network/disk I/O.
- Race window between lookup and dispatch resolves in favor of in-flight
  dispatch — semantically acceptable per Pass 2 analysis.
"""

import threading
import time
from typing import Any, Dict, Optional

from lupin_mcp.commons_store import CommonsStore


_DEFAULT_POLL_INTERVAL = 1.0
_DEFAULT_TTL_SECONDS   = 300.0


class CommonsTopicWatcher:
    """
    Abstract base for commons topic watchers.

    Requires:
        - `store` is a `CommonsStore` rooted at `<LUPIN_ROOT>/io/commons`
        - `poll_interval_seconds` is a positive float
        - `in_flight_ttl_seconds` is a positive float (default ttl applied when
           subclasses construct records without an explicit per-record override)

    Ensures:
        - `_register(record_id, record)` atomically inserts; raises ValueError on collision
        - `_unregister(record_id)` silently pops (no-op on unknown id)
        - `start()` / `stop()` spawn / signal the daemon thread
        - All state mutation is guarded by `self._lock`
        - `_prune_expired_locked(now)` removes entries whose `expires_at_monotonic <= now`
    """

    def __init__(
        self,
        store                  : CommonsStore,
        poll_interval_seconds  : float = _DEFAULT_POLL_INTERVAL,
        in_flight_ttl_seconds  : float = _DEFAULT_TTL_SECONDS,
        debug                  : bool  = False,
        thread_name            : str   = "CommonsTopicWatcher",
    ):
        self.store                 = store
        self.poll_interval_seconds = float( poll_interval_seconds )
        self.in_flight_ttl_seconds = float( in_flight_ttl_seconds )
        self.debug                 = debug
        self._thread_name          = thread_name

        self._in_flight: Dict[ str, Any ] = { }
        self._lock                   = threading.Lock()
        self._last_seen_ts: Optional[ str ] = None
        self._stop_event             = threading.Event()
        self._thread: Optional[ threading.Thread ] = None
        self._initialized_last_seen  = False

    # ─── Protected registry primitives (template-method per F13-fit) ────────

    def _register( self, record_id: str, record: Any ) -> None:
        """
        Atomic insert-or-raise (T9 mirror).

        Raises:
            - ValueError if `record_id` is already in flight — subclass router
              typically translates this to HTTP 409.

        Requires:
            - `record` has an `expires_at_monotonic` float attribute (for prune)

        Note: subclass-domain public methods (e.g. `register_broadcast`,
        `register_question`) wrap this with domain-specific record-construction.
        """
        now = time.monotonic()
        with self._lock:
            self._prune_expired_locked( now )
            if record_id in self._in_flight:
                raise ValueError( f"record_id collision: {record_id}" )
            self._in_flight[ record_id ] = record

    def _unregister( self, record_id: str ) -> None:
        """Manual cleanup. Silent on unknown id."""
        with self._lock:
            self._in_flight.pop( record_id, None )

    def _prune_expired_locked( self, now_monotonic: float ) -> None:
        """
        Remove entries past their `expires_at_monotonic` TTL.

        Caller MUST hold `self._lock`. Each record in `_in_flight` MUST expose
        an `expires_at_monotonic: float` attribute.
        """
        expired = [
            rid for rid, rec in self._in_flight.items()
            if rec.expires_at_monotonic <= now_monotonic
        ]
        for rid in expired:
            del self._in_flight[ rid ]

    # ─── Daemon lifecycle ───────────────────────────────────────────────────

    def start( self ) -> None:
        """Initialize last_seen_ts (if not yet) and spawn the daemon thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        if not self._initialized_last_seen:
            self._initialize_last_seen_ts()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target = self._run_loop,
            daemon = True,
            name   = self._thread_name,
        )
        self._thread.start()

    def stop( self, join_timeout: Optional[ float ] = 5.0 ) -> None:
        """Signal stop + join. Safe to call on never-started watcher."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join( timeout=join_timeout )

    def _run_loop( self ) -> None:
        """Daemon body — call tick() every poll_interval until stop signal."""
        while not self._stop_event.wait( timeout=self.poll_interval_seconds ):
            try:
                self.tick()
            except Exception as e:
                if self.debug: print( f"[{self._thread_name}] tick raised: {e}" )

    # ─── Abstract methods (subclass implements) ─────────────────────────────

    def _initialize_last_seen_ts( self ) -> None:
        """
        On first start, seed `self._last_seen_ts` so historical entries
        don't replay. Subclass reads from its domain topic.
        """
        raise NotImplementedError(
            "Subclass must implement _initialize_last_seen_ts() to seed cursor "
            "from its domain-specific topic."
        )

    def tick( self ) -> int:
        """
        Single poll iteration. Subclass implements topic + dispatch logic.

        Returns the number of records dispatched (for testability).
        """
        raise NotImplementedError(
            "Subclass must implement tick() to read its topic, "
            "match against in-flight records, and dispatch."
        )
