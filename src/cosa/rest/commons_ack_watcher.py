"""
Server-side daemon that tails the `broadcast-acks` topic and pushes
`commons_broadcast_ack` custom notifications to the originating user.

Per AC7 + T9 (Pass 2) + F3 (REUSE) of
src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md.

**Phase 3 refactor (Q1 + F13-fit template-method)**: This class is now a
subclass of `CommonsTopicWatcher` (see `commons_topic_watcher.py`). The
base owns lifecycle scaffolding, lock, registry primitives, and prune
logic. This subclass provides domain-typed `_InFlightEntry`, the
`register_broadcast` / `unregister_broadcast` / `is_in_flight` public
API (preserves Phase 2 naming for 26-test compat), and the
broadcast-ack-specific `tick()` dispatch.

**In-flight broadcast tracker semantics** (T9 + AC7):
- Entries are added by `POST /api/commons/broadcast-to-cc-sessions` via
  `register_broadcast(bid, originating_user_id, expected_recipients)`
- The check-and-register operation is atomic under `self._lock` (inherited
  from base) — prevents TOCTOU race between concurrent inserts with the
  same caller-supplied UUID
- TTL: 5 minutes from registration (matches AC9's UI auto-dismiss window).
  Expired entries are pruned lazily on each `_tick()`
- Lookup uses `is_in_flight(bid)` — returns False once TTL elapses or after
  explicit `unregister_broadcast(bid)`

**Startup `last_seen_ts`**: initialized to the timestamp of the LAST ack
entry already in `broadcast-acks` at watcher-start, so historical acks
don't replay to the UI on every restart.
"""

import time
from typing import Any, Callable, Dict, Optional

from lupin_mcp.commons_store import CommonsStore
from cosa.rest.commons_topic_watcher import CommonsTopicWatcher


_BROADCAST_ACKS_TOPIC  = "broadcast-acks"
_DEFAULT_TTL_SECONDS   = 300.0
_DEFAULT_POLL_INTERVAL = 1.0
_READ_LIMIT_PER_TICK   = 10000


class _InFlightEntry:
    """Per-broadcast tracking state. Plain data — no methods."""
    def __init__(
        self,
        originating_user_id : str,
        expected_recipients : int,
        expires_at_monotonic: float,
    ):
        self.originating_user_id  = originating_user_id
        self.expected_recipients  = expected_recipients
        self.expires_at_monotonic = expires_at_monotonic
        self.received_acks        = 0


class CommonsAckWatcher( CommonsTopicWatcher ):
    """
    Daemon thread + in-flight broadcast tracker for ack fanout.

    Requires:
        - `store` is a `CommonsStore` rooted at `<LUPIN_ROOT>/io/commons`
        - `push_notification_fn` is a callable matching `NotificationFifoQueue.push_notification`'s kwargs interface
        - `poll_interval_seconds` is a positive float (default 1.0)
        - `in_flight_ttl_seconds` is a positive float (default 300.0)

    Ensures:
        - `register_broadcast(bid, user_id, expected)` atomically inserts; raises ValueError on collision
        - `tick()` reads since `last_seen_ts`, fires push for each matching in-flight broadcast, prunes expired entries
        - `start()` / `stop()` spawn / signal the daemon (inherited from base)
        - All state mutation is guarded by `self._lock` (inherited from base)
    """

    def __init__(
        self,
        store                  : CommonsStore,
        push_notification_fn   : Callable[ ..., Any ],
        poll_interval_seconds  : float = _DEFAULT_POLL_INTERVAL,
        in_flight_ttl_seconds  : float = _DEFAULT_TTL_SECONDS,
        debug                  : bool  = False,
    ):
        super().__init__(
            store                 = store,
            poll_interval_seconds = poll_interval_seconds,
            in_flight_ttl_seconds = in_flight_ttl_seconds,
            debug                 = debug,
            thread_name           = "CommonsAckWatcher",
        )
        self.push_notification_fn = push_notification_fn

    # ─── In-flight tracker public API (domain-named wrappers per F13-fit) ───

    def register_broadcast( self, broadcast_id: str, originating_user_id: str, expected_recipients: int ) -> None:
        """
        Atomic insert-or-raise (per T9). Raises `ValueError` if `broadcast_id`
        is already in flight — the endpoint translates this to HTTP 409.
        """
        now = time.monotonic()
        entry = _InFlightEntry(
            originating_user_id  = originating_user_id,
            expected_recipients  = expected_recipients,
            expires_at_monotonic = now + self.in_flight_ttl_seconds,
        )
        try:
            self._register( broadcast_id, entry )
        except ValueError:
            # Re-raise with domain-specific message (preserves Phase 2 26-test contract)
            raise ValueError( f"broadcast_id collision: {broadcast_id}" )

    def unregister_broadcast( self, broadcast_id: str ) -> None:
        """Manual cleanup. Silent on unknown id."""
        self._unregister( broadcast_id )

    def is_in_flight( self, broadcast_id: str ) -> bool:
        """True if the broadcast is registered AND not expired."""
        with self._lock:
            self._prune_expired_locked( time.monotonic() )
            return broadcast_id in self._in_flight

    # ─── Subclass implementations of base-class abstracts ───────────────────

    def _initialize_last_seen_ts( self ) -> None:
        """
        On first start, set `_last_seen_ts` to the timestamp of the LAST existing
        ack entry — so historical acks (from a prior watcher run) don't replay
        when the server restarts. Per AC7 startup-cursor semantics.
        """
        try:
            entries = self.store.read( _BROADCAST_ACKS_TOPIC, limit=1 )
            if entries:
                self._last_seen_ts = entries[ 0 ][ "ts" ]
        except Exception as e:
            if self.debug: print( f"[CommonsAckWatcher] startup _last_seen_ts init failed: {e}" )
        self._initialized_last_seen = True

    def tick( self ) -> int:
        """
        Single poll iteration.

        Reads new ack entries since `_last_seen_ts`, fires push for each
        entry whose `metadata.broadcast_id` is in flight, prunes expired
        in-flight entries.

        Returns the number of acks dispatched (for testability).
        """
        try:
            entries = self.store.read(
                _BROADCAST_ACKS_TOPIC,
                since = self._last_seen_ts,
                limit = _READ_LIMIT_PER_TICK,
            )
        except FileNotFoundError:
            return 0

        dispatched = 0
        latest_ts = self._last_seen_ts
        for entry in entries:
            metadata     = entry.get( "metadata", { } ) or { }
            broadcast_id = metadata.get( "broadcast_id" )
            entry_ts     = entry.get( "ts" )

            if entry_ts is not None and ( latest_ts is None or entry_ts > latest_ts ):
                latest_ts = entry_ts

            if not broadcast_id:
                continue

            with self._lock:
                self._prune_expired_locked( time.monotonic() )
                inflight = self._in_flight.get( broadcast_id )
                if inflight is None:
                    continue
                inflight.received_acks += 1
                user_id  = inflight.originating_user_id

            self._push_ack_event( entry, broadcast_id, user_id, metadata )
            dispatched += 1

        if latest_ts is not None and latest_ts != self._last_seen_ts:
            self._last_seen_ts = latest_ts

        return dispatched

    def _push_ack_event(
        self,
        entry        : Dict[ str, Any ],
        broadcast_id : str,
        user_id      : str,
        metadata     : Dict[ str, Any ],
    ) -> None:
        """Fire the `commons_broadcast_ack` notification for one ack."""
        try:
            self.push_notification_fn(
                message            = "",
                type               = "commons_broadcast_ack",
                user_id            = user_id,
                suppress_ding      = True,
                response_requested = False,
                payload            = {
                    "broadcast_id"  : broadcast_id,
                    "session_id"    : entry.get( "sender_session_id" ),
                    "persona_name"  : entry.get( "persona_name" ),
                    "persona_icon"  : entry.get( "persona_icon" ),
                    "persona_color" : entry.get( "persona_color" ),
                    "status"        : metadata.get( "status" ),
                    "body_summary"  : metadata.get( "body_summary", "" ),
                },
            )
        except Exception as e:
            if self.debug: print( f"[CommonsAckWatcher] push failed for {broadcast_id}: {e}" )
