"""
Durable notify outbox — Phase 1 (lever A) of the messaging-coordination plane.

Design: `src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md` (lever A1).

Problem it solves: the cosa-voice MCP fires notifications at the shared `:7999`
server with a bounded per-call timeout + in-call retry. When that whole budget is
exhausted (server slow/down under fleet load), the message is **lost** — no
durable retry, no ack. That is the FM-7/FM-11 "black-hole."

This module adds the durable layer: on a FINAL send failure, the request is
spooled to a small on-disk outbox; a background flusher retries each spooled item
(reusing its `idempotency_key`, so the server de-dups a maybe-already-delivered
message) until it is acked or ages past TTL. Survives process restarts.

Key design choices (for testability + isolation):
  - Pure functions take an explicit `outbox_dir` (a `Path`) — tests use a tmp dir.
  - Delivery is via an injected `send_fn( request ) -> bool` — no network in unit
    tests; production wraps `notify_user_async`.
  - Time is injectable (`now_epoch`) for deterministic TTL tests.
  - Rides ONLY local disk — no cosa-voice messaging dependency, no fleet (so it
    cannot itself re-trigger the black-hole it is fixing).
"""

import os
import json
import time
import threading

from typing import Callable, Optional, Any


# Module-level guard so the flusher daemon is started at most once per process.
_flusher_started = False
_flusher_lock    = threading.Lock()


def spool( request: Any, outbox_dir: str, now_epoch: Optional[ float ] = None ) -> str:
    """
    Persist a failed notification request to the durable outbox.

    Requires:
        - request is a Pydantic model exposing `model_dump( mode="json" )` and an
          `idempotency_key` attribute (may be None — a fallback id is synthesized)
        - outbox_dir is a writable directory path (created if missing)

    Ensures:
        - writes exactly one JSON file `<epoch_ms>-<idempotency_key>.json` into
          outbox_dir containing the JSON-serialized request
        - returns the full path of the file written
        - is idempotent on idempotency_key collisions only insofar as a later
          spool of the SAME key overwrites the earlier file (same logical item)

    Raises:
        - OSError if outbox_dir cannot be created or the file cannot be written
    """
    if now_epoch is None:
        now_epoch = time.time()

    os.makedirs( outbox_dir, exist_ok=True )

    payload = request.model_dump( mode="json" )
    key     = payload.get( "idempotency_key" ) or getattr( request, "idempotency_key", None )
    if not key:
        # Defensive: synthesize a stable-ish id so the file is still writable.
        key = f"nokey-{int( now_epoch * 1000 )}"

    record = {
        "spooled_at"      : now_epoch,
        "idempotency_key" : key,
        "request"         : payload,
    }

    fname = f"{int( now_epoch * 1000 )}-{key}.json"
    fpath = os.path.join( outbox_dir, fname )
    with open( fpath, "w" ) as f:
        json.dump( record, f )
    return fpath


def list_spooled( outbox_dir: str ) -> list:
    """
    List spooled outbox files, oldest-first (FIFO retry order).

    Ensures:
        - returns a sorted list of absolute paths to `*.json` files in outbox_dir
        - returns [] when outbox_dir does not exist or holds no json files
    """
    if not os.path.isdir( outbox_dir ):
        return []
    files = [
        os.path.join( outbox_dir, n )
        for n in os.listdir( outbox_dir )
        if n.endswith( ".json" )
    ]
    return sorted( files )


def _load_record( fpath: str ) -> Optional[ dict ]:
    """Load a spooled record; return None on any parse/read error (corrupt file)."""
    try:
        with open( fpath ) as f:
            return json.load( f )
    except ( OSError, ValueError ):
        return None


def flush(
    send_fn      : Callable[ [ dict ], bool ],
    outbox_dir   : str,
    ttl_seconds  : int,
    now_epoch    : Optional[ float ] = None
) -> dict:
    """
    Attempt redelivery of every spooled item; drop the delivered + the expired.

    Requires:
        - send_fn( request_payload: dict ) -> bool returns True iff the server
          acked the (re)delivery; it MUST be safe to call repeatedly because each
          payload carries its original `idempotency_key` (server de-dups)
        - outbox_dir is the spool directory
        - ttl_seconds > 0

    Ensures:
        - oldest-first: items are attempted in FIFO order
        - on send_fn True  → the spool file is deleted (delivered)
        - on age > ttl     → the spool file is deleted (expired, counted separately)
        - on send_fn False → the file is LEFT for a later flush (still pending)
        - a corrupt/unreadable file is deleted (counted as dropped_corrupt)
        - never raises out of a single item's failure — one bad item cannot wedge
          the sweep
        - returns counts { delivered, expired, pending, dropped_corrupt, attempted }
    """
    if now_epoch is None:
        now_epoch = time.time()

    stats = { "delivered": 0, "expired": 0, "pending": 0, "dropped_corrupt": 0, "attempted": 0 }

    for fpath in list_spooled( outbox_dir ):
        stats[ "attempted" ] += 1
        record = _load_record( fpath )
        if record is None:
            _safe_remove( fpath )
            stats[ "dropped_corrupt" ] += 1
            continue

        spooled_at = record.get( "spooled_at", 0 )
        if ( now_epoch - spooled_at ) > ttl_seconds:
            _safe_remove( fpath )
            stats[ "expired" ] += 1
            continue

        try:
            delivered = bool( send_fn( record[ "request" ] ) )
        except Exception:
            # Any delivery error → keep the item for a later flush.
            delivered = False

        if delivered:
            _safe_remove( fpath )
            stats[ "delivered" ] += 1
        else:
            stats[ "pending" ] += 1

    return stats


def _safe_remove( fpath: str ) -> None:
    """Remove a file, swallowing OSError (already gone / racing flush)."""
    try:
        os.remove( fpath )
    except OSError:
        pass


def start_flusher(
    send_fn          : Callable[ [ dict ], bool ],
    outbox_dir       : str,
    ttl_seconds      : int,
    interval_seconds : int,
    logger           : Optional[ Any ] = None
) -> bool:
    """
    Start the background flush daemon exactly once per process.

    Requires:
        - send_fn / outbox_dir / ttl_seconds / interval_seconds as in flush()
        - interval_seconds > 0

    Ensures:
        - on first call: spawns ONE daemon thread that calls flush() every
          interval_seconds and returns True
        - on subsequent calls: no-op, returns False (already running)
        - the loop never dies on a flush() exception (logged if logger given)
    """
    global _flusher_started
    with _flusher_lock:
        if _flusher_started:
            return False
        _flusher_started = True

    def _loop():  # pragma: no cover - unbounded `while True` around a real time.sleep; any call enters a loop that never returns, so no test can execute this body and reach the next statement
        while True:
            time.sleep( interval_seconds )
            try:
                flush( send_fn, outbox_dir, ttl_seconds )
            except Exception as e:
                if logger is not None:
                    logger.warning( f"[notify-outbox] flush error: {e}" )

    t = threading.Thread( target=_loop, name="notify-outbox-flusher", daemon=True )
    t.start()
    return True
