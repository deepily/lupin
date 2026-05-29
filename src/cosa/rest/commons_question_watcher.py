"""
Server-side daemon that tails per-question free-form topics, correlates
`metadata.in_reply_to` entries with in-flight registered questions, and
dispatches a per-question `inject_fn` callback to push the answer back to
the asking CC session as a `<system-reminder>` injection.

Per Phase 3 (`04-phase3-push-mode-and-llm-fallback-design.md`) — implements
the `CommonsQuestionWatcher` subclass referenced by AC1 / AC2 / AC3 / AC8
and the Pass 2 Adversarial ratifications T1 / T3 / T4 / T5 / T6 / T8.

**In-flight question tracker semantics**:
- Entries are added by `POST /api/commons/register-question` (auth-gated)
  via `register_question(qid, user_id, topic, inject_fn, ttl_seconds=...)`.
- Per-user cap (`commons question tracker per user max`) and global cap
  (`commons question tracker global max`) checked before atomic insert (T3).
- Atomic check-cap-and-register operation is under `self._lock` (T6) —
  prevents TOCTOU race between concurrent registrations on the same
  question_id.
- TTL defaults to `commons question tracker ttl seconds` (1h) with per-
  call override; expired entries lazy-pruned on each `tick()`.
- Each question carries its OWN `last_seen_ts` cursor (F3-fit) so a
  long-TTL question doesn't re-replay history when registered late.

**Dispatch semantics** (per AC3 + T1/T6/T8):
- `tick()` snapshots in-flight under `self._lock`, then for each question
  reads `store.read(topic, since=last_seen_ts)` OUTSIDE the lock.
- Each candidate entry is validated (T1): `in_reply_to` must be a string,
  match `[A-Za-z0-9_-]+`, length ≤ 64. Non-matching entries are skipped.
- Lookup + `_dispatched_set` check + `inject_fn` capture happen INSIDE
  `self._lock` (T6); the actual `inject_fn(entry)` call runs OUTSIDE the
  lock to avoid blocking on network/disk I/O.
- `inject_fn` exceptions are caught and logged at debug (T8) — a failing
  dispatch on one question does NOT prevent dispatches on other questions
  in the same tick batch.

**Cross-user isolation** (T5):
- `unregister_question(qid, user_id)` raises `QuestionNotFound` for BOTH
  unknown ids AND known-but-not-owned ids via a single internal path —
  router translates to uniform `404 {"detail": "question_id not found or
  not owned by caller"}` to prevent enumeration.

**`<system-reminder>` framing** (Q3, applied by the listener — not here):
The listener (`cc_notification_listener.py` `_handle_commons_answer_received`)
reads the stamped `persona_name` from the answer entry (F9-fit immutability,
NOT live lookup) and renders the body as:
    `"COMMONS PEER REPLY (question_id X, from @PersonaName):\\n\\n[body]"`
This watcher just dispatches the raw answer entry via `inject_fn`.
"""

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set, Tuple

from lupin_mcp.commons_store import CommonsStore
from cosa.rest.commons_topic_watcher import CommonsTopicWatcher


_DEFAULT_POLL_INTERVAL = 1.0
_DEFAULT_TTL_SECONDS   = 3600.0
_DEFAULT_PER_USER_MAX  = 50
_DEFAULT_GLOBAL_MAX    = 1000
_READ_LIMIT_PER_TICK   = 10000

_IN_REPLY_TO_RE      = re.compile( r"^[A-Za-z0-9_-]+$" )
_MAX_IN_REPLY_TO_LEN = 64


class CapExceededError( Exception ):
    """Raised by `register_question` when per-user or global tracker cap would be exceeded (T3)."""
    pass


class QuestionNotFound( Exception ):
    """Raised by `unregister_question` when question_id is unknown OR not owned by caller (T5)."""
    pass


class _InFlightQuestion:
    """Per-question tracking state. Plain data — no methods."""
    def __init__(
        self,
        topic                : str,
        user_id              : str,
        inject_fn            : Callable[ [ Dict[ str, Any ] ], None ],
        last_seen_ts         : str,
        expires_at_monotonic : float,
    ):
        self.topic                = topic
        self.user_id              = user_id
        self.inject_fn            = inject_fn
        self.last_seen_ts         = last_seen_ts
        self.expires_at_monotonic = expires_at_monotonic


def _now_iso() -> str:
    """Wall-clock ISO timestamp matching commons_store entry `ts` format."""
    return datetime.now( timezone.utc ).isoformat()


def _is_valid_in_reply_to( value: Any ) -> bool:
    """T1 validation: must be a string, ≤ 64 chars, matching `[A-Za-z0-9_-]+`."""
    if not isinstance( value, str ):              return False
    if len( value ) == 0:                          return False
    if len( value ) > _MAX_IN_REPLY_TO_LEN:        return False
    if _IN_REPLY_TO_RE.fullmatch( value ) is None: return False
    return True


class CommonsQuestionWatcher( CommonsTopicWatcher ):
    """
    Daemon thread + per-question tracker for `ask_async` push-mode dispatch.

    Requires:
        - `store` is a `CommonsStore` rooted at `<LUPIN_ROOT>/io/commons`
        - `poll_interval_seconds` is a positive float (default 1.0)
        - `in_flight_ttl_seconds` is a positive float (default 3600.0)
        - `per_user_max` is a positive int (default 50)
        - `global_max` is a positive int (default 1000)

    Ensures:
        - `register_question(qid, user_id, topic, inject_fn, ttl_seconds=None, last_seen_ts=None)`
          atomically inserts under `self._lock` (T6); raises `CapExceededError`
          on per-user or global cap overflow (T3); raises `ValueError` on
          question_id collision (T9 mirror).
        - `unregister_question(qid, user_id)` raises `QuestionNotFound` for
          unknown ids OR known-but-not-owned ids (T5).
        - `tick()` polls each in-flight question's topic with its OWN cursor
          (F3-fit); validates `in_reply_to` (T1); idempotency-deduplicates
          via `_dispatched_by_question`; dispatches `inject_fn` outside the
          lock (T6); isolates per-question dispatch failures (T8).
        - All state mutation guarded by `self._lock` (inherited from base).
    """

    def __init__(
        self,
        store                 : CommonsStore,
        poll_interval_seconds : float = _DEFAULT_POLL_INTERVAL,
        in_flight_ttl_seconds : float = _DEFAULT_TTL_SECONDS,
        per_user_max          : int   = _DEFAULT_PER_USER_MAX,
        global_max            : int   = _DEFAULT_GLOBAL_MAX,
        debug                 : bool  = False,
    ):
        super().__init__(
            store                 = store,
            poll_interval_seconds = poll_interval_seconds,
            in_flight_ttl_seconds = in_flight_ttl_seconds,
            debug                 = debug,
            thread_name           = "CommonsQuestionWatcher",
        )
        self.per_user_max = int( per_user_max )
        self.global_max   = int( global_max )

        # T1 idempotency: keyed by question_id → set of entry ts strings already dispatched
        self._dispatched_by_question: Dict[ str, Set[ str ] ] = { }

    # ─── Public API ─────────────────────────────────────────────────────────

    def register_question(
        self,
        question_id   : str,
        user_id       : str,
        topic         : str,
        inject_fn     : Callable[ [ Dict[ str, Any ] ], None ],
        ttl_seconds   : Optional[ float ] = None,
        last_seen_ts  : Optional[ str ]   = None,
    ) -> None:
        """
        Atomic check-caps-and-register (T3 + T6 + T9 mirror).

        Requires:
            - `question_id`, `user_id`, `topic` are non-empty strings
            - `inject_fn` is callable
            - `ttl_seconds` is a positive float (default: `self.in_flight_ttl_seconds`)
            - `last_seen_ts` is None (auto = now_iso) or a string ISO timestamp

        Ensures:
            - inserts under lock; raises `CapExceededError` if per-user or
              global cap would be exceeded
            - raises `ValueError` if `question_id` is already in flight
              (router translates to HTTP 409)
            - stamps `user_id` and `last_seen_ts` on the in-flight record
              (T4 — re-register cursor)

        Raises:
            - CapExceededError if per-user or global cap reached
            - ValueError on question_id collision
        """
        ttl = float( ttl_seconds ) if ttl_seconds is not None else self.in_flight_ttl_seconds
        ts  = last_seen_ts if last_seen_ts is not None else _now_iso()

        now_monotonic = time.monotonic()
        record = _InFlightQuestion(
            topic                = topic,
            user_id              = user_id,
            inject_fn            = inject_fn,
            last_seen_ts         = ts,
            expires_at_monotonic = now_monotonic + ttl,
        )

        with self._lock:
            self._prune_expired_locked( now_monotonic )
            # T3 global cap
            if len( self._in_flight ) >= self.global_max:
                raise CapExceededError( f"global cap reached: {self.global_max}" )
            # T3 per-user cap
            user_count = sum( 1 for r in self._in_flight.values() if r.user_id == user_id )
            if user_count >= self.per_user_max:
                raise CapExceededError( f"per-user cap reached for user_id={user_id}: {self.per_user_max}" )
            # T9 collision
            if question_id in self._in_flight:
                raise ValueError( f"question_id collision: {question_id}" )
            self._in_flight[ question_id ] = record

    def unregister_question( self, question_id: str, user_id: str ) -> None:
        """
        Lock-guarded removal with cross-user enumeration prevention (T5).

        Requires:
            - `question_id` is a string
            - `user_id` is a string (the authenticated caller)

        Ensures:
            - removes the in-flight record and its `_dispatched_by_question`
              entry on success
            - raises `QuestionNotFound` for BOTH unknown question_ids AND
              known-but-not-owned ones via a single internal path

        Raises:
            - QuestionNotFound (router → uniform 404)
        """
        with self._lock:
            record = self._in_flight.get( question_id )
            if record is None or record.user_id != user_id:
                raise QuestionNotFound( "question_id not found or not owned by caller" )
            del self._in_flight[ question_id ]
            self._dispatched_by_question.pop( question_id, None )

    def is_in_flight( self, question_id: str ) -> bool:
        """True if the question is registered AND not expired. Lazy-prunes."""
        with self._lock:
            self._prune_expired_locked( time.monotonic() )
            return question_id in self._in_flight

    # ─── Subclass overrides ─────────────────────────────────────────────────

    def _prune_expired_locked( self, now_monotonic: float ) -> None:
        """
        Override base to also clear `_dispatched_by_question` entries for
        pruned questions (T1 memory hygiene).

        Caller MUST hold `self._lock`.
        """
        expired = [
            rid for rid, rec in self._in_flight.items()
            if rec.expires_at_monotonic <= now_monotonic
        ]
        for rid in expired:
            del self._in_flight[ rid ]
            self._dispatched_by_question.pop( rid, None )

    def _initialize_last_seen_ts( self ) -> None:
        """
        Per-question cursors live ON the in-flight records (F3-fit), not on
        the watcher itself. Watcher-level `_last_seen_ts` is unused; the
        base's start() still requires this hook to be implemented.
        """
        self._initialized_last_seen = True

    def tick( self ) -> int:
        """
        Single poll iteration.

        For each in-flight question: read new entries on its topic since its
        per-question cursor; validate `in_reply_to` (T1); idempotency-dedup
        via `_dispatched_by_question`; dispatch `inject_fn` outside the lock
        (T6); isolate per-dispatch failures (T8); advance the per-question
        cursor.

        Returns the number of answers dispatched across all questions
        (for testability).
        """
        with self._lock:
            self._prune_expired_locked( time.monotonic() )
            snapshot: list[ Tuple[ str, _InFlightQuestion ] ] = list( self._in_flight.items() )

        dispatched_total = 0
        for question_id, question in snapshot:
            dispatched_total += self._tick_one_question( question_id, question )
        return dispatched_total

    # ─── Internal helpers ───────────────────────────────────────────────────

    def _tick_one_question( self, question_id: str, question: _InFlightQuestion ) -> int:
        """Single-question slice of `tick()` — extracted for readability + testability."""
        topic  = question.topic
        cursor = question.last_seen_ts

        try:
            entries = self.store.read( topic, since=cursor, limit=_READ_LIMIT_PER_TICK )
        except FileNotFoundError:
            return 0
        except Exception as e:
            if self.debug: print( f"[CommonsQuestionWatcher] read failed for topic={topic}: {e!r}" )
            return 0

        dispatched = 0
        latest_ts  = cursor
        for entry in entries:
            entry_ts = entry.get( "ts" )
            if entry_ts is not None and ( latest_ts is None or entry_ts > latest_ts ):
                latest_ts = entry_ts

            metadata    = entry.get( "metadata" ) or { }
            in_reply_to = metadata.get( "in_reply_to" )

            # T1 validation — skip malformed entries (log at debug)
            if not _is_valid_in_reply_to( in_reply_to ):
                if in_reply_to is not None and self.debug:
                    print( f"[CommonsQuestionWatcher] skipping invalid in_reply_to: {in_reply_to!r}" )
                continue

            if in_reply_to != question_id:
                continue

            # T6 lock-guarded lookup + T1 idempotency + inject_fn capture
            with self._lock:
                current = self._in_flight.get( question_id )
                if current is None:
                    continue  # unregistered mid-tick
                qd = self._dispatched_by_question.setdefault( question_id, set() )
                if entry_ts in qd:
                    continue  # T1 dispatch-once idempotency
                qd.add( entry_ts )
                inject_fn_local = current.inject_fn

            # T8 dispatch isolation — failure on one entry does NOT block the rest
            try:
                inject_fn_local( entry )
                dispatched += 1
            except Exception as e:
                if self.debug: print( f"[CommonsQuestionWatcher] inject_fn raised for {question_id}: {e!r}" )

        # Advance per-question cursor (lock-guarded; re-check still-in-flight to avoid
        # writing to a record that was unregistered mid-tick)
        if latest_ts is not None and latest_ts != cursor:
            with self._lock:
                current = self._in_flight.get( question_id )
                if current is not None:
                    current.last_seen_ts = latest_ts

        return dispatched
