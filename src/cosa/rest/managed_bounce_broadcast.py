"""
Managed-bounce broadcasts for the `:7999` dev server (R4 + R5).

Design of record: `src/rnd/v0.1.9/2026.08.01-managed-bounce-review-tiffany.md`
(Tiffany 💍) + `2026.08.01-managed-bounce-for-7999.md` Rev 2 (María 🌸).

Two fleet-facing signals ride the server's own process edges so no bounce
path can skip them:

  · **All-clear (R5)** — emitted from the FastAPI lifespan STARTUP hook. Fires
    on EVERY start (script, hand-typed `docker restart`, `compose up`,
    crash-restart, host reboot), because the just-started server is the one
    process guaranteed alive at the moment "I am up" must be spoken.
  · **Warning (R4)** — emitted two ways: (a) best-effort from a SIGTERM handler
    (backstop for un-sanctioned bounce paths; loses the race to SIGKILL
    sometimes — see the handler's own comment), and (b) ack-CONFIRMED by the
    host-side bounce script before it restarts (the sanctioned path).

This module holds the PURE / INJECTABLE logic (message text, boot counter, the
in-process emit wrapper, and the host-side ack-poll) so all of it unit-tests to
100% with no live server, no real clock, and no real filesystem waits. The wiring
that binds it to live singletons lives in `main.py` (all-clear + SIGTERM) and in
`src/scripts/bounce_dev_warn.py` (the script's ack-confirmed warning).
"""

import sys
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


DEFAULT_SERVER_LABEL = ":7999"

# The fleet's service-account user. CC sessions are stamped with this
# owner_user_id (or none — commons scoping passes bridges that lack it), so a
# broadcast authored as this user reaches every fleet session. Same literal the
# notification layer uses (notification_repository.py, notification_fifo_queue.py).
FLEET_BROADCAST_USER_ID = "claude.code@lupin.deepily.ai"


# ─── Message text (pure) ────────────────────────────────────────────────────


def build_bounce_message(
    kind           : str,
    *,
    boot_id        : Optional[ int ]   = None,
    boot_started   : Optional[ str ]   = None,
    uptime_seconds : Optional[ float ] = None,
    server_label   : str               = DEFAULT_SERVER_LABEL,
) -> str:
    """
    Build the fleet broadcast body for a managed bounce.

    Requires:
        - kind is "warning" or "all-clear"
        - for "all-clear", boot_id / boot_started / uptime_seconds are supplied
          (they make the message SELF-DISTINGUISHING so a crash-loop reads as N
          distinct all-clears, not one message people learn to ignore — María's
          R5 delta, 2026-08-01)

    Ensures:
        - returns a non-empty single-line string with no system-reminder framing

    Raises:
        - ValueError if kind is not one of the two known signals
    """
    if kind == "warning":
        # SELF-LIMITING hold (Tiffany's ruling, 2026-08-01): the exit must NOT be
        # "an all-clear" alone — all-clear delivery is best-effort, and a session
        # that misses it would otherwise stay suppressed INDEFINITELY, not just
        # miss news. The "or confirm health yourself" clause closes that trap with
        # a sentence, no mechanism (no auto-timeout, no polling, no re-fire).
        return (
            f"⚠️ {server_label} is bouncing NOW — hold notifications and blocking asks until the "
            f"all-clear, OR until you can confirm the server is healthy yourself. Any in-flight "
            f"question will drop and need re-asking."
        )
    if kind == "all-clear":
        up = "?" if uptime_seconds is None else f"{uptime_seconds:.1f}"
        return (
            f"✅ {server_label} is back up — boot #{boot_id}, started {boot_started}, "
            f"up {up}s. Notifications and blocking asks are live again."
        )
    raise ValueError( f"unknown bounce broadcast kind: {kind!r} (want 'warning' or 'all-clear')" )


# ─── Boot counter (self-distinguishing all-clear) ───────────────────────────


def next_boot_id( counter_path: Any ) -> int:
    """
    Read-increment-write a persistent boot counter, returning the NEW value.

    A crash-loop then emits all-clears numbered 41, 42, 43… — five in two minutes
    read as a flap instead of five identical lines. Fail-SOFT: a missing,
    unreadable, or garbage counter file restarts the count at 1 rather than
    blocking the all-clear (the counter is a readability aid, never a gate).

    Requires:
        - counter_path is a path-like to a small text file

    Ensures:
        - returns an int >= 1
        - the file is left holding the returned value (best-effort; a write
          failure is swallowed and the returned value still advances in-process)
    """
    path = Path( counter_path )
    current = 0
    try:
        current = int( path.read_text( encoding="utf-8" ).strip() )
    except ( FileNotFoundError, ValueError, OSError ):
        current = 0
    nxt = current + 1 if current >= 0 else 1
    try:
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( str( nxt ), encoding="utf-8" )
    except OSError as e:
        print( f"[managed-bounce] WARN: could not persist boot counter to {path}: {e}", file=sys.stderr )
    return nxt


# ─── In-process emit (all-clear + SIGTERM warning) ──────────────────────────


def emit_bounce_broadcast_in_process(
    *,
    kind                             : str,
    message                          : str,
    user_id                          : str,
    store                            : Any,
    rate_limiter                     : Any,
    ack_watcher                      : Any,
    notification_queue               : Any,
    active_session_threshold_seconds : float,
    raw_sessions_fn                  : Callable[ [ ], Any ],
    bridge_loader                    : Callable[ [ Any ], Optional[ Dict[ str, Any ] ] ],
    build_sender_id                  : Callable[ [ str ], Optional[ str ] ],
    execute_broadcast_fn             : Callable[ ..., Dict[ str, Any ] ],
    broadcast_request_cls            : Callable[ ..., Any ],
    broadcast_id                     : Optional[ str ] = None,
    require_ack                      : bool            = True,
) -> Dict[ str, Any ]:
    """
    Fire a fleet broadcast from INSIDE the server process, never raising.

    Used by the lifespan all-clear (R5) and the SIGTERM warning backstop (R4).
    Wraps the router's pure-logic `execute_broadcast` with the live singletons.

    Two failure modes get a LOUD stderr line, by design (María's R5 delta):
      · rate-limit 429 — "getting 429'd is acceptable; getting 429'd QUIETLY is
        not." A silently-eaten all-clear reopens the exact silence-means-nothing
        hole this feature exists to close.
      · any exception — this is best-effort edge code; it must degrade to a log,
        never take down startup or block SIGTERM shutdown.

    Ensures:
        - returns None when commons is not wired (store / rate_limiter /
          ack_watcher is None) — nothing to broadcast through; logs one line
        - returns the `execute_broadcast` result dict on the happy path, or
          `{"error": <str>}` if it threw
        - never propagates an exception to the caller
    """
    if store is None or rate_limiter is None or ack_watcher is None:
        print( f"[managed-bounce] WARN: {kind} broadcast skipped — commons not wired", file=sys.stderr )
        return None

    try:
        body   = broadcast_request_cls( message=message, broadcast_id=broadcast_id, require_ack=require_ack )
        result = execute_broadcast_fn(
            authenticated_user_id            = user_id,
            body                             = body,
            store                            = store,
            rate_limiter                     = rate_limiter,
            ack_watcher                      = ack_watcher,
            notification_queue               = notification_queue,
            active_session_threshold_seconds = active_session_threshold_seconds,
            raw_sessions_fn                  = raw_sessions_fn,
            bridge_loader                    = bridge_loader,
            build_sender_id                  = build_sender_id,
        )
    except Exception as e:                                        # noqa: BLE001 — best-effort edge code, must never raise
        print( f"[managed-bounce] ERROR: {kind} broadcast raised, not sent: {e}", file=sys.stderr )
        return { "error": str( e ) }

    http_status = result.get( "http_status" )
    if http_status == 429:
        print(
            f"[managed-bounce] ⚠️ {kind} broadcast SUPPRESSED by the rate limiter "
            f"(429, retry_after={result.get( 'retry_after' )}s) — the fleet was NOT told. "
            f"Silence is not proof the server is down; check the bounce log.",
            file=sys.stderr,
        )
    elif http_status and http_status >= 400:
        print(
            f"[managed-bounce] ⚠️ {kind} broadcast returned {http_status}: "
            f"{result.get( 'detail' )} — the fleet was NOT told.",
            file=sys.stderr,
        )
    return result


# ─── Host-side ack poll (the bounce script's confirmed warning) ─────────────


def count_acked_sessions(
    entries      : List[ Dict[ str, Any ] ],
    broadcast_id : str,
    status       : str = "completed",
) -> int:
    """
    Count DISTINCT recipient sessions that acked `broadcast_id` with `status`.

    Dedupes on `(broadcast_id, sender_session_id, status)` — the same key
    `_dedupe_broadcast_acks_by_recipient` (`commons.py:640`) uses — because acks
    duplicate: one recipient can write the identical ack 2-4× within
    milliseconds (measured 2026-05-15, and again on `22f7a215` this morning). A
    raw row count OVER-counts and lets the script restart before the warning has
    actually reached everyone.

    Requires:
        - entries is a list of parsed commons entries (CommonsStore.read shape)
        - broadcast_id is the id from the warning's 200 body

    Ensures:
        - returns the number of unique sender_session_ids that acked, never
          double-counting a duplicated ack
    """
    seen : set = set()
    for e in entries:
        md = e.get( "metadata" ) or { }
        if md.get( "broadcast_id" ) != broadcast_id:
            continue
        if md.get( "status" ) != status:
            continue
        sid = e.get( "sender_session_id" )
        if not isinstance( sid, str ):
            continue
        seen.add( sid )
    return len( seen )


def resolve_ack_timing( config_mgr, *, default_deadline, default_poll ):
    """
    Read the warning ack deadline + poll interval from an already-built config.

    Pure given `config_mgr` (just two `.get` lookups), so it lives HERE where the
    cov denominator measures it — per Rio's ruling that the resolve logic belongs
    in the module, not in the src/scripts caller (which is outside source=["cosa"]).
    The fail-soft boundary — BUILDING a ConfigurationManager can raise in a bare
    host context — stays in the caller's try/except, which is the one genuinely
    unmeasurable boundary guard.

    Ensures:
        - returns (deadline_seconds, poll_interval_seconds) as floats, each the
          configured value or the supplied default when the key is absent
    """
    deadline = config_mgr.get( "managed bounce warning ack deadline seconds",      default=default_deadline, return_type="float" )
    poll     = config_mgr.get( "managed bounce warning ack poll interval seconds", default=default_poll,     return_type="float" )
    return ( deadline, poll )


def poll_acks_until_satisfied(
    *,
    read_entries_fn      : Callable[ [ ], List[ Dict[ str, Any ] ] ],
    broadcast_id         : str,
    expected_recipients  : int,
    deadline_seconds     : float,
    poll_interval_seconds: float,
    now_fn               : Callable[ [ ], float ],
    sleep_fn             : Callable[ [ float ], None ],
    status               : str = "completed",
) -> Dict[ str, Any ]:
    """
    Poll the broadcast-acks surface until every recipient acked, or the deadline.

    Fully injectable — `read_entries_fn`, `now_fn`, `sleep_fn` are supplied — so
    the loop unit-tests to 100% with no real clock and no real filesystem.

    Requires:
        - expected_recipients >= 0; deadline/interval are non-negative seconds

    Ensures:
        - returns {satisfied, acked, expected, elapsed} — `satisfied` True iff
          `acked >= expected_recipients` was reached before the deadline
        - a zero-recipient warning is satisfied immediately (nothing to wait for)
        - always polls at least once, so an already-complete set returns without
          sleeping
    """
    start = now_fn()
    while True:
        acked = count_acked_sessions( read_entries_fn(), broadcast_id, status=status )
        elapsed = now_fn() - start
        if acked >= expected_recipients:
            return { "satisfied": True, "acked": acked, "expected": expected_recipients, "elapsed": elapsed }
        if elapsed >= deadline_seconds:
            return { "satisfied": False, "acked": acked, "expected": expected_recipients, "elapsed": elapsed }
        sleep_fn( poll_interval_seconds )


def missed_sessions( expected_ids, present_ids ):
    """
    Sessions expected back (the roster) that have NO live socket — i.e. who never
    rejoined and therefore got no all-clear.

    Named on deadline expiry so the delivery LOSS is legible, not a bare count
    (Rio's requirement). The ROSTER is legitimately the bridge-file session list:
    bridge files survive a bounce, so they answer "who do we expect back", which
    is exactly what they cannot answer for "who is back NOW" (that is the live
    socket set). Roster minus live = missed.

    Requires:
        - expected_ids, present_ids are iterables of session-id strings

    Ensures:
        - returns a sorted, de-duplicated list of ids in expected but not present
    """
    return sorted( set( expected_ids ) - set( present_ids ) )


# ─── All-clear settle gate (R5 SOLE delivery path — no durable backstop) ─────


def wait_for_reconnection_plateau(
    *,
    count_fn              : Callable[ [ ], int ],
    minimum               : int,
    stable_polls          : int,
    deadline_seconds      : float,
    poll_interval_seconds : float,
    now_fn                : Callable[ [ ], float ],
    sleep_fn              : Callable[ [ float ], None ],
) -> Dict[ str, Any ]:
    """
    Wait for reconnecting sockets to PLATEAU, then fire — else fire at the deadline.

    This is the SOLE delivery path for a live all-clear: there is no durable
    backstop. `perform_fanout` writes each `broadcasts` entry targeted at the
    fire-time snapshot, so a straggler who rejoins after the fire has NO entry at
    all — emitted-≠-heard one layer down. Re-fire/replay is barred (Rick's
    do-not-implement on the durable-notify-path, 2026-07-28). So the fire must
    wait until the fleet is actually back.

    `count_fn` MUST be a LIVE-socket count that empties on a bounce
    (`websocket_manager.get_connection_count`), NOT a bridge-file count that
    survives one: the bridge proxy read "present" at 0.0s and fired into sockets
    that were not back — the 2026-08-01 zero-ack bug (all-clears 0 acks vs
    warnings 7, same sessions).

    Firing conditions:
      · PLATEAU — count >= `minimum` AND the SAME count has been observed in
        `stable_polls` consecutive polls (reconnections have stopped arriving). A
        single observation is NOT a plateau; `stable_polls` equal reads in a row are.
      · DEADLINE — `deadline_seconds` elapsed first. Accepted delivery LOSS: fire
        anyway so the fleet that IS back hears it; the caller names who was missed.

    Fully injectable (`count_fn`, `now_fn`, `sleep_fn`) → 100% testable with no
    real clock and no real sockets.

    Ensures:
        - returns {reason, count, elapsed, curve}; `reason` is "plateau" or "deadline"
        - `curve` is the per-poll count series (the reconnect curve) for the log
        - polls at least once; a plateau at a count below `minimum` never fires
          early (it rides to the deadline), so a still-empty fleet is not mistaken
          for a settled one
    """
    start = now_fn()
    curve : List[ int ] = [ ]
    run   = 0                            # length of the current run of equal counts
    while True:
        count = count_fn()
        run   = run + 1 if ( curve and count == curve[ -1 ] ) else 1
        curve.append( count )
        elapsed = now_fn() - start
        if count >= minimum and run >= stable_polls:
            return { "reason": "plateau", "count": count, "elapsed": elapsed, "curve": curve }
        if elapsed >= deadline_seconds:
            return { "reason": "deadline", "count": count, "elapsed": elapsed, "curve": curve }
        sleep_fn( poll_interval_seconds )
