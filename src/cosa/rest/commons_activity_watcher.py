"""
CommonsActivityWatcher — Phase 2.5/3.5 admin-oversight surface.

Tails ALL commons topics (minus a configurable exclude list) and fires a
`commons_activity` WS notification for each new entry. Powers the live update
side of the broadcast-card Recent Activity stream.

Per src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md (AC3 — WS
push delivery; AC2 — `commons traffic visibility ws push enabled` INI gate).

Architecture:
- Subclasses `CommonsTopicWatcher` for daemon-thread lifecycle (start/stop/_run_loop).
- Uses ONE global `_last_seen_ts` cursor across all included topics rather than
  per-topic cursors — simpler bookkeeping, correct under the "newest-first
  reverse-chrono" UX semantics.
- Each tick:
  1. Enumerate active topics via `store._all_topic_names()`, drop excluded.
  2. For each included topic, read entries with `since=_last_seen_ts`.
  3. Merge across topics, sort newest-first, dispatch one `commons_activity`
     push per entry.
  4. Advance the cursor to the max ts seen.

Note: this watcher does NOT use the `_in_flight` registry from the base class —
activity-stream traffic is fire-and-forget, no in-flight correlation needed.
The base class's `_in_flight` dict remains an empty dict for the watcher's life.
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from cosa.rest.commons_topic_watcher import CommonsTopicWatcher
from lupin_mcp.commons_store import CommonsStore


_DEFAULT_POLL_INTERVAL = 1.0
_READ_LIMIT_PER_TICK   = 100


class CommonsActivityWatcher( CommonsTopicWatcher ):
    """
    Multi-topic activity-stream watcher.

    Requires:
        - `store` is a `CommonsStore`
        - `push_notification_fn` matches the kwargs interface of `NotificationFifoQueue.push_notification`
        - `excluded_topics` is a list of topic names to skip (e.g., `presence`, `system-events`)
        - `bridge_owner_resolver_fn` returns a fresh {session_id: owner_user_id|None}
           map on each call — used to determine the entry's owning user for
           per-recipient WS routing
        - `poll_interval_seconds` is a positive float

    Ensures:
        - `start()` spawns the daemon thread (idempotent)
        - `tick()` is exception-safe — failures in individual entries are logged
          and skipped; failures in the topic-listing step return 0 gracefully
        - Per-entry dispatch is best-effort; a `push_notification_fn` failure on
          one entry does not abort the tick
    """

    def __init__(
        self,
        store                    : CommonsStore,
        push_notification_fn     : Callable[ ..., Any ],
        excluded_topics          : List[ str ],
        bridge_owner_resolver_fn : Callable[ [ ], Dict[ str, Optional[ str ] ] ],
        poll_interval_seconds    : float = _DEFAULT_POLL_INTERVAL,
        debug                    : bool  = False,
    ):
        super().__init__(
            store                  = store,
            poll_interval_seconds  = poll_interval_seconds,
            debug                  = debug,
            thread_name            = "CommonsActivityWatcher",
        )
        self.push_notification_fn     = push_notification_fn
        self.excluded_topics          = set( excluded_topics )
        self.bridge_owner_resolver_fn = bridge_owner_resolver_fn

    # ─── Subclass implementations of base abstracts ─────────────────────────

    def _initialize_last_seen_ts( self ) -> None:
        """
        Seed `_last_seen_ts` so historical entries don't replay on first start.

        Walks every non-excluded topic, finds the maximum `ts` across all of them,
        and uses that as the cursor floor. If no topics exist yet, the cursor stays
        None and the first tick will pick up the first entry (which is the desired
        behavior for a freshly-initialized commons store).
        """
        try:
            topics  = [ t for t in self.store._all_topic_names() if t not in self.excluded_topics ]
            max_ts: Optional[ str ] = None
            for t in topics:
                try:
                    entries = self.store.read( t, limit=1 )
                except FileNotFoundError:
                    continue
                if entries:
                    ts = entries[ 0 ].get( "ts" )
                    if ts is not None and ( max_ts is None or ts > max_ts ):
                        max_ts = ts
            self._last_seen_ts = max_ts
        except Exception as e:
            if self.debug: print( f"[CommonsActivityWatcher] startup _last_seen_ts init failed: {e}" )
        self._initialized_last_seen = True

    def tick( self ) -> int:
        """
        Single poll iteration.

        Returns the number of `commons_activity` events dispatched (for testability).
        """
        try:
            topics = [ t for t in self.store._all_topic_names() if t not in self.excluded_topics ]
        except Exception as e:
            if self.debug: print( f"[CommonsActivityWatcher] topic enumeration failed: {e}" )
            return 0

        # Collect new entries across all included topics
        new_entries: List[ Dict[ str, Any ] ] = [ ]
        for t in topics:
            try:
                entries = self.store.read( t, since=self._last_seen_ts, limit=_READ_LIMIT_PER_TICK )
            except FileNotFoundError:
                continue
            except Exception as e:
                if self.debug: print( f"[CommonsActivityWatcher] read failed for topic {t!r}: {e}" )
                continue
            for e in entries:
                e[ "_topic" ] = t   # decorate for downstream dispatch
                new_entries.append( e )

        if not new_entries:
            return 0

        # Sort newest-first across all topics
        new_entries.sort( key=lambda e: e.get( "ts" ) or "", reverse=True )

        # Collapse per-recipient + write-side fan-out before dispatch (2026-05-16 bug fix).
        # The HTTP `broadcast-history` read path already dedupes via
        # `_dedupe_broadcasts_by_id` and `_dedupe_broadcast_acks_by_recipient` in
        # `routers/commons.py`. The WS push path (this watcher) historically
        # bypassed both dedupes — symptom: a single system broadcast against N
        # active sessions produced N "commons_activity" pushes → N rows in the
        # Recent Activity panel. Mirror the HTTP-path dedupe here so the WS
        # stream emits one canonical row per logical broadcast / per (broadcast,
        # sender, status) ack.
        # Cursor advancement uses the ORIGINAL (pre-dedupe) ts set so we don't
        # rescan dropped duplicates on the next tick.
        latest_ts_pre_dedupe = max(
            ( e.get( "ts" ) for e in new_entries if e.get( "ts" ) is not None ),
            default = self._last_seen_ts,
        )
        new_entries = self._dedupe_for_dispatch( new_entries )

        # Resolve bridge owner map ONCE per tick
        try:
            bridge_owner_map = self.bridge_owner_resolver_fn()
        except Exception as e:
            if self.debug: print( f"[CommonsActivityWatcher] bridge resolver failed: {e}" )
            bridge_owner_map = { }

        dispatched = 0
        latest_ts  = self._last_seen_ts
        for entry in new_entries:
            entry_ts = entry.get( "ts" )
            if entry_ts is not None and ( latest_ts is None or entry_ts > latest_ts ):
                latest_ts = entry_ts

            try:
                self._dispatch_activity_event( entry, bridge_owner_map )
                dispatched += 1
            except Exception as e:
                if self.debug:
                    print( f"[CommonsActivityWatcher] dispatch failed for entry ts={entry_ts}: {e}" )
                # Best-effort — keep going
                continue

        # Bug-fix 2026-05-16: cursor MUST advance to the max ts of the original
        # (pre-dedupe) entry set, not just the dispatched subset. Otherwise the
        # dropped-duplicate entries would re-surface on the next tick.
        if latest_ts_pre_dedupe is not None and (
            self._last_seen_ts is None or latest_ts_pre_dedupe > self._last_seen_ts
        ):
            self._last_seen_ts = latest_ts_pre_dedupe
        elif latest_ts is not None and latest_ts != self._last_seen_ts:  # pragma: no cover - unreachable: commons_store guarantees non-None ts (mandatory header regex orphan-drops non-matching blocks; read(since=) sorts/compares ts so None would TypeError) and the since-filter is exclusive, so when entries exist latest_ts_pre_dedupe > cursor (or cursor is None) → the L183 if always fires; an empty tick early-returns at L135 — the elif can never be reached
            self._last_seen_ts = latest_ts

        return dispatched

    # ─── Pre-dispatch dedupe (2026-05-16) ───────────────────────────────────

    def _dedupe_for_dispatch(
        self,
        entries: List[ Dict[ str, Any ] ],
    ) -> List[ Dict[ str, Any ] ]:
        """
        Collapse per-recipient broadcasts fan-out + write-side ack multiplicity
        before WS dispatch. Mirrors the HTTP-path helpers in `routers/commons.py`
        (`_dedupe_broadcasts_by_id` + `_dedupe_broadcast_acks_by_recipient`) but
        operates on the watcher's decorated-entry shape (each dict carries
        `_topic` from `tick`'s collection step).

        Rules:
        - `broadcasts` topic: collapse on `metadata.broadcast_id`. The first
          occurrence (newest after the outer DESC sort) is kept; subsequent
          per-recipient duplicates are dropped. The kept entry's `metadata`
          is shallow-copied with `target_session_id` removed so the dispatched
          row represents the broadcast as a whole, not any one recipient slice.
        - `broadcast-acks` topic: collapse on `(broadcast_id, sender_session_id,
          metadata.status)`. Acks that share the same triple (write-side
          multiplicity bug shape — see Arnold's investigation in the
          `_dedupe_broadcast_acks_by_recipient` docstring) are collapsed to
          the first occurrence.
        - Any other topic: pass through unchanged.
        - Defensive passthrough on missing / non-string keys (a malformed entry
          must not silently disappear).

        Requires:
            - `entries` is the watcher's `new_entries` list (each dict carries
              `_topic` from the collection step in `tick`)

        Ensures:
            - Returns a new list (input is not mutated)
            - Order is preserved relative to input (which is newest-first by
              outer sort)
            - For `broadcasts` rows kept, `metadata.target_session_id` is removed
              from the dispatched copy
        """
        seen_broadcast_ids : Set[ str ]                       = set()
        seen_ack_keys      : Set[ Tuple[ str, str, str ] ]    = set()
        out                : List[ Dict[ str, Any ] ]         = [ ]

        for entry in entries:
            topic = entry.get( "_topic" )

            if topic == "broadcasts":
                md  = entry.get( "metadata" ) or { }
                bid = md.get( "broadcast_id" )
                if not isinstance( bid, str ):
                    out.append( entry )
                    continue
                if bid in seen_broadcast_ids:
                    continue
                seen_broadcast_ids.add( bid )
                # Shallow-copy + strip per-recipient field
                new_md    = { k: v for k, v in md.items() if k != "target_session_id" }
                new_entry = dict( entry )
                new_entry[ "metadata" ] = new_md
                out.append( new_entry )
                continue

            if topic == "broadcast-acks":
                md  = entry.get( "metadata" ) or { }
                bid = md.get( "broadcast_id" )
                sid = entry.get( "sender_session_id" )
                st  = md.get( "status" )
                if not ( isinstance( bid, str ) and isinstance( sid, str ) and isinstance( st, str ) ):
                    out.append( entry )
                    continue
                key = ( bid, sid, st )
                if key in seen_ack_keys:
                    continue
                seen_ack_keys.add( key )
                out.append( entry )
                continue

            # All other topics: passthrough
            out.append( entry )

        return out

    # ─── Per-entry dispatch ─────────────────────────────────────────────────

    _RESERVED = { "broadcasts", "broadcast-acks", "presence", "system-events" }

    def _resolve_recipient_user_id(
        self,
        entry            : Dict[ str, Any ],
        bridge_owner_map : Dict[ str, Optional[ str ] ],
    ) -> Optional[ str ]:
        """
        Best-effort recipient user_id resolution for WS routing.

        Priority:
          1. `metadata.sender_user_id` — direct authorial attribution (e.g. broadcasts)
          2. Bridge owner of `sender_session_id` — for AI-to-AI commons posts
        Returns None if neither path resolves — caller fans out without user_id
        filter (degraded to broadcast-to-all-authenticated-WS in single-user dev).
        """
        metadata = entry.get( "metadata" ) or { }
        sender_user_id = metadata.get( "sender_user_id" )
        if sender_user_id:
            return sender_user_id
        sender_sid = entry.get( "sender_session_id" )
        if sender_sid:
            return bridge_owner_map.get( sender_sid )
        return None

    def _dispatch_activity_event(
        self,
        entry            : Dict[ str, Any ],
        bridge_owner_map : Dict[ str, Optional[ str ] ],
    ) -> None:
        """
        Fire one `commons_activity` WS notification for the entry.
        """
        topic = entry.pop( "_topic", "unknown" )
        topic_kind = "reserved" if topic in self._RESERVED else "free-form"
        user_id = self._resolve_recipient_user_id( entry, bridge_owner_map )

        payload = {
            "ts"                : entry.get( "ts" ),
            "topic"             : topic,
            "topic_kind"        : topic_kind,
            "sender_session_id" : entry.get( "sender_session_id" ),
            "persona_name"      : entry.get( "persona_name" ),
            "persona_icon"      : entry.get( "persona_icon" ),
            "persona_color"     : entry.get( "persona_color" ),
            "body"              : entry.get( "body" ),
            "metadata"          : entry.get( "metadata" ) or { },
        }

        push_kwargs = {
            "message"            : "",
            "type"               : "commons_activity",
            "suppress_ding"      : True,
            "response_requested" : False,
            "payload"            : payload,
        }
        if user_id is not None:
            push_kwargs[ "user_id" ] = user_id

        self.push_notification_fn( **push_kwargs )
