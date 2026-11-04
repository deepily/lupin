"""
Managed-bounce broadcasts for the `:7999` dev server: the all-clear and the warning.

Two fleet-facing signals ride the server's own process edges so no bounce path can skip them.
The all-clear is emitted from the FastAPI lifespan startup hook. It fires on every start
(script, hand-typed `docker restart`, `compose up`, crash-restart, host reboot). The
just-started server is the one process certain to be alive when "I am up" must be spoken.
The warning is emitted two ways. A best-effort SIGTERM handler backs up un-sanctioned bounce
paths, and sometimes loses the race to SIGKILL. The host-side bounce script sends an
ack-confirmed warning before it restarts, which is the sanctioned path.

This module holds the pure, injectable logic: message text, boot counter, the in-process emit
wrapper and the host-side ack poll. It unit-tests to 100% with no live server, real clock or
filesystem waits. The wiring to live singletons lives in `main.py` (all-clear and SIGTERM) and
`src/scripts/bounce_dev_warn.py` (the ack-confirmed warning).
"""

import sys
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


DEFAULT_SERVER_LABEL = ":7999"

# Characters allowed in the filename derived from a server label. Anything else
# collapses to "-", so a label can never escape the counter directory.
_LABEL_SAFE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# The fleet's service-account user. CC sessions are stamped with this
# owner_user_id (or none — commons scoping passes bridges that lack it), so a
# broadcast authored as this user reaches every fleet session. Same literal the
# notification layer uses (notification_repository.py, notification_fifo_queue.py).
FLEET_BROADCAST_USER_ID = "claude.code@lupin.deepily.ai"


# ─── Message text (pure) ────────────────────────────────────────────────────

# Cap on how many dirty paths the warning broadcast names inline before it
# summarises the rest as "(+N more)". A bounce of a long-dirty tree must still
# fit one readable line — the point is to let an OWNER spot their file, not to
# reproduce the whole `git status`.
_DIRTY_BROADCAST_CAP = 12


def format_dirty_clause( dirty_files, cap: int = _DIRTY_BROADCAST_CAP ) -> str:
    """
    Fold `git status --short` output into one single-line clause naming the dirty paths.

    The warning broadcast carries the clause to the seat that owns those files, which a TTY
    prompt can never reach an agent with. Pure.

    Requires:
        - dirty_files is the raw `git status --short` output (multi-line str), or
          None / "" when the tree is clean

    Ensures:
        - returns "" when dirty_files is None / blank / whitespace-only (the
          warning is then unchanged; a clean bounce carries no clause)
        - otherwise returns a leading-space clause with the status lines joined by
          "; " (never a raw newline; the message stays single-line), at most `cap`
          named, the remainder summarised as "; …(+N more)"
        - never raises
    """
    if not dirty_files or not dirty_files.strip():
        return ""
    lines = [ line.strip() for line in dirty_files.splitlines() if line.strip() ]
    shown = lines[ :cap ]
    joined = "; ".join( shown )
    remainder = len( lines ) - len( shown )
    if remainder > 0:
        joined += f"; …(+{remainder} more)"
    return (
        f" Heads-up: this bounce also deploys these uncommitted files — {joined}. "
        f"If any are yours, object during this ack window."
    )


def build_bounce_message(
    kind           : str,
    *,
    boot_id        : Optional[ int ]   = None,
    boot_started   : Optional[ str ]   = None,
    uptime_seconds : Optional[ float ] = None,
    server_label   : str               = DEFAULT_SERVER_LABEL,
    dirty_files    : Optional[ str ]   = None,
    reason         : Optional[ str ]   = None,
) -> str:
    """
    Build the fleet broadcast body for a managed bounce.

    Requires:
        - kind is "warning" or "all-clear"
        - for "all-clear", boot_id / boot_started / uptime_seconds are supplied
          (they make the message self-distinguishing, so a crash-loop reads as N
          distinct all-clears, not one message people learn to ignore)
        - dirty_files (warning only) is the raw `git status --short` blob when the
          bouncer's tree is dirty, else None. It names the uncommitted files the
          bounce will deploy so their owner can object during the ack window, which
          a non-interactive caller's skipped prompt cannot reach.
          Ignored for "all-clear".
        - reason (warning only) is a short phrase saying why this bounce is
          happening, or None. The broadcast names the files a bounce deploys but
          never why, so a peer holding armed probes cannot tell, after reading it, a
          needed bounce from a casual one and has to ask. Ignored for "all-clear".

    Ensures:
        - returns a non-empty single-line string with no system-reminder framing
        - for "warning" with a non-blank dirty_files, the string additionally names
          the dirty paths (via format_dirty_clause); a clean warning is unchanged
        - for "warning" with a non-blank reason, the string states it directly after
          the opening clause; a warning without one is unchanged, so an omitted
          reason costs nothing and a supplied one is impossible to miss

    Raises:
        - ValueError if kind is not one of the two known signals
    """
    if kind == "warning":
        # SELF-LIMITING hold (Tiffany's ruling, 2026-08-01): the exit must NOT be
        # "an all-clear" alone — all-clear delivery is best-effort, and a session
        # that misses it would otherwise stay suppressed INDEFINITELY, not just
        # miss news. The "or confirm health yourself" clause closes that trap with
        # a sentence, no mechanism (no auto-timeout, no polling, no re-fire).
        # The reason goes FIRST, right after the opening clause, not appended at the
        # end. A reader deciding whether to object needs it before the file list, and
        # a clause at the tail of a long dirty-file blob is one nobody reads.
        why = f" Reason: {reason.strip()}." if reason and reason.strip() else ""
        return (
            f"⚠️ {server_label} is bouncing NOW —{why} hold notifications and blocking asks until the "
            f"all-clear, OR until you can confirm the server is healthy yourself. Any in-flight "
            f"question will drop and need re-asking."
            f"{format_dirty_clause( dirty_files )}"
        )
    if kind == "all-clear":
        up = "?" if uptime_seconds is None else f"{uptime_seconds:.1f}"
        return (
            f"✅ {server_label} is back up — boot #{boot_id}, started {boot_started}, "
            f"up {up}s. Notifications and blocking asks are live again."
        )
    raise ValueError( f"unknown bounce broadcast kind: {kind!r} (want 'warning' or 'all-clear')" )


# ─── Boot counter (self-distinguishing all-clear) ───────────────────────────


def boot_counter_path( project_root: Any, server_label: str = DEFAULT_SERVER_LABEL ) -> Path:
    """
    The boot-counter file for one server, derived from that server's label.

    Requires:
        - project_root is a path-like to the repository root
        - server_label is a string

    Ensures:
        - returns a Path under <project_root>/io/managed-bounce/
        - two different labels never resolve to the same file
        - the filename contains no path separators regardless of the label
        - the label is reduced to its alphanumerics, so ":7999" and ":8000" become
          `boot-counter-7999.txt` and `boot-counter-8000.txt`; a label with no
          alphanumerics falls back to "default" rather than a hidden or empty filename
        - each server gets its own file because both containers bind-mount the same `io/`
          directory: a shared counter interleaves their boots, so a watcher is told the
          wrong boot number for a bounce, and a test-server boot gets announced as a dev
          bounce, which defeats the counter's purpose
    """
    slug = "".join( c if c in _LABEL_SAFE_CHARS else "-" for c in server_label ).strip( "-" )
    if not slug: slug = "default"

    return Path( project_root ) / "io" / "managed-bounce" / f"boot-counter-{slug}.txt"


def next_boot_id( counter_path: Any ) -> int:
    """
    Read, increment and write a persistent boot counter, returning the new value.

    A crash-loop then emits all-clears numbered 41, 42, 43 and so on. Five in two minutes read
    as a flap instead of five identical lines. It fails soft: a bad counter file restarts the
    count at 1 rather than blocking the all-clear. The counter is a readability aid, never a gate.

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
    Fire a fleet broadcast from inside the server process, never raising.

    Used by the lifespan all-clear and the SIGTERM warning backstop. Wraps the router's
    pure-logic `execute_broadcast` with the live singletons.

    Ensures:
        - returns None when commons is not wired (store / rate_limiter /
          ack_watcher is None); nothing to broadcast through, and it logs one line
        - returns the `execute_broadcast` result dict on the happy path, or
          `{"error": <str>}` if it threw
        - never propagates an exception to the caller: this is best-effort edge code, so it
          degrades to a loud stderr line rather than take down startup or block SIGTERM shutdown
        - a rate-limit 429 and any exception each get a loud stderr line, because a silently eaten all-clear
          reopens the hole where silence means nothing
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
    Count distinct recipient sessions that acked `broadcast_id` with `status`.

    Dedupes on `(broadcast_id, sender_session_id, status)`, the key `_dedupe_broadcast_acks_by_recipient` uses.
    One recipient can write the identical ack two to four times within milliseconds.
    A raw count would let the script restart before the warning reached everyone.

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
    Read the warning ack deadline and poll interval from an already-built config.

    Pure given `config_mgr` (just two `.get` lookups). It lives here so the coverage
    denominator measures it, rather than in the src/scripts caller, which is outside the
    measured source.

    Ensures:
        - returns (deadline_seconds, poll_interval_seconds) as floats, each the
          configured value or the supplied default when the key is absent
        - building a ConfigurationManager can raise in a bare host context; that fail-soft
          boundary stays in the caller's try/except
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


LISTENER_SID_PREFIX = "cc-listener-"

# The two id spaces meet at the SHORT session id — the first 8 characters of a
# Claude Code session id (`register_session.py`: `short_id = session_id[:8]`).
_SHORT_ID_LEN = 8


def socket_match_key( session_id : str ) -> str:
    """
    Reduce a roster id or a live-socket key to the short id the two spaces share.

    The two sides are different strings. A roster entry is a full session id from the bridge
    filename. A live-socket key is `cc-listener-` plus the first 8 characters. Comparing them
    raw never matches, so every roster entry would read as missing on every bounce.

    Requires:
        - session_id is a string

    Ensures:
        - returns the leading short id, with the listener prefix removed first
        - is idempotent: applying it to its own output returns the same value
        - a raw set difference of roster against present would name the whole roster every
          time and make the roster coverage gate unsatisfiable, a fixed wait to the deadline
        - browser sessions fail to match any roster id, which is correct since nobody waits
          for them; short ids are hex, so a browser id equal to a real short id is not reachable
        - two sessions sharing their first 8 characters would collide and one straggler would
          be marked covered; 8 is a ceiling because the socket side carries no more than that,
          so widening the key cannot fix it and the collision lives in listener naming upstream
    """
    sid = session_id[ len( LISTENER_SID_PREFIX ): ] if session_id.startswith( LISTENER_SID_PREFIX ) else session_id
    return sid[ :_SHORT_ID_LEN ]


def missed_sessions( expected_ids, present_ids ):
    """
    Sessions expected back (the roster) that have no live socket, so never rejoined.

    Naming them makes the delivery loss legible instead of a bare count. The roster is the
    bridge-file session list. Bridge files survive a bounce, so they answer "who do we expect
    back" but not "who is back now". Matching goes through `socket_match_key`, never raw equality.

    Requires:
        - expected_ids, present_ids are iterables of session-id strings

    Ensures:
        - returns a sorted, de-duplicated list of the full expected ids that have
          no matching live socket (full ids, so each straggler can be named)
    """
    live = { socket_match_key( p ) for p in present_ids }
    return sorted( { e for e in expected_ids if socket_match_key( e ) not in live } )


# ─── All-clear settle gate (R5 SOLE delivery path — no durable backstop) ─────


def wait_for_roster_coverage(
    *,
    roster_fn             : Callable[ [ ], List[ str ] ],
    present_fn            : Callable[ [ ], List[ str ] ],
    deadline_seconds      : float,
    poll_interval_seconds : float,
    now_fn                : Callable[ [ ], float ],
    sleep_fn              : Callable[ [ float ], None ],
) -> Dict[ str, Any ]:
    """
    Wait until live sockets cover the expected roster, then fire; else fire at the deadline.

    Fully injectable (`roster_fn`, `present_fn`, `now_fn`, `sleep_fn`), so it tests to 100%
    with no real clock and no real sockets. Firing conditions: coverage (every roster id has a
    live socket) or the deadline elapsing first (accepted delivery loss; `missing` names them).

    Requires:
        - roster_fn returns an iterable of expected session-id strings
        - present_fn returns an iterable of live session-id strings in the same
          id space as the roster (both go through `socket_match_key`)

    Ensures:
        - returns {reason, count, missing, roster_size, elapsed, curve};
          `reason` is "coverage" or "deadline"
        - `missing` is the roster-minus-live set at the firing observation, so the
          loss the caller reports is the one the gate decided on, not a later read
        - `curve` is the per-poll live-socket count series for the log
        - polls at least once; an empty roster is covered vacuously and fires on
          the first poll (nobody is expected, so nobody can be missed)
        - this is the sole delivery path for a live all-clear: `perform_fanout` targets each
          entry at the fire-time snapshot, so a straggler who rejoins after the fire gets no
          entry, and re-fire or replay is barred; the fire must wait until the fleet is back
        - coverage is a completion test, not a plateau of equal counts: a plateau cannot tell
          two equal reads at the final value from two sampled between arrivals (0, 1, 1 is the
          start of reconnection), and counting bridge files always reads true since they
          survive a bounce
        - the roster is the limiting factor: it is the bridge-file list on an 8-hour mtime
          window, so it can name a session gone for good, which holds the gate to the full
          deadline; this is accepted, and a better roster would be the warning phase's ack list
          carried across the restart in a file
    """
    start = now_fn()
    curve : List[ int ] = [ ]
    while True:
        roster  = list( roster_fn() )
        present = list( present_fn() )
        missing = missed_sessions( roster, present )
        curve.append( len( present ) )
        elapsed = now_fn() - start
        result  = {
            "count"       : len( present ),
            "missing"     : missing,
            "roster_size" : len( set( roster ) ),
            "elapsed"     : elapsed,
            "curve"       : curve,
        }
        if not missing:
            return { "reason": "coverage", **result }
        if elapsed >= deadline_seconds:
            return { "reason": "deadline", **result }
        sleep_fn( poll_interval_seconds )
