#!/usr/bin/env python3
"""
Heartbeat arbiter auto-ping throttle: pure per-edge backoff and rate-cap decisions.

The arbiter DMs a blocker at most once per (holder, awaited, reason) edge per
backoff window. It never re-pings every poll, which keeps a ping storm from
forming. It also honors a global fleet-wide rate cap across all arbiter-originated
DMs.

These functions only decide. The consumer holds the per-edge state (last-ping ts
and attempt count) and the recent-DM count. Clear-on-resume, which drops an edge
when the holder stops awaiting, is the consumer's wiring.

Design authority: lupin →
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md §6.1 / §7.
"""

# Escalating per-edge backoff windows (seconds): 1m → 5m → 15m → 1h, clamped.
DEFAULT_BACKOFF_SCHEDULE = ( 60, 300, 900, 3600 )


def edge_key( holder, awaited, reason ):
    """
    Stable throttle key for one (holder, awaited-peer, reason) ping edge.

    Requires:
        - holder, awaited, reason are strings or None

    Ensures:
        - Returns a deterministic "holder|awaited|reason" key (None → "")
        - Never raises
    """
    return f"{holder or ''}|{awaited or ''}|{reason or ''}"


def backoff_for_attempt( attempt, schedule=DEFAULT_BACKOFF_SCHEDULE ):
    """
    The backoff window (seconds) for the Nth ping attempt (0-indexed).

    Requires:
        - attempt is an int (negative coerced to 0)
        - schedule is a non-empty tuple of positive numbers

    Ensures:
        - attempt < len(schedule)  → schedule[attempt]
        - attempt >= len(schedule) → schedule[-1] (clamped to the widest window)
        - Never raises
    """
    if attempt < 0:
        attempt = 0
    if attempt >= len( schedule ):
        return schedule[ -1 ]
    return schedule[ attempt ]


def should_ping( last_ping_ts, now, backoff_seconds ):
    """
    Should this edge be pinged now? (per-edge throttle)

    Requires:
        - last_ping_ts is an aware datetime or None (None = never pinged)
        - now is an aware datetime
        - backoff_seconds is a positive number

    Ensures:
        - Returns True iff never pinged, or the backoff window has elapsed
          ((now - last_ping_ts) >= backoff_seconds)
        - Returns False conservatively if the timestamps are unusable
        - Never raises
    """
    if last_ping_ts is None:
        return True
    try:
        elapsed = ( now - last_ping_ts ).total_seconds()
    except ( TypeError, AttributeError ):
        return False
    return elapsed >= backoff_seconds


def under_global_cap( recent_ping_count, cap ):
    """
    Is the fleet-wide arbiter-DM rate under the global cap? (no-storm check)

    Requires:
        - recent_ping_count is the count of arbiter DMs in the current window (int)
        - cap is the max allowed (positive int)

    Ensures:
        - Returns True iff recent_ping_count < cap
        - Never raises
    """
    return recent_ping_count < cap


def in_window( sent_ts, now, window_seconds ):
    """
    Keep the send timestamps whose age is within the trailing window.

    The consumer uses it to bound its per-recipient send history and count sends.
    Future-dated or unusable entries are dropped, so a junk ts can never inflate
    the count and wrongly suppress an outreach.

    Requires:
        - sent_ts is an iterable of aware datetimes (or None); now is an aware
          datetime; window_seconds is a number

    Ensures:
        - returns the list of entries with 0 <= (now − ts) <= window_seconds,
          in input order
        - None / empty / all-unusable → [ ]; never raises
    """
    kept = [ ]
    for ts in ( sent_ts or [ ] ):
        try:
            age = ( now - ts ).total_seconds()
        except ( TypeError, AttributeError ):
            continue                                    # unusable ts → drop (fail-safe)
        if 0 <= age <= window_seconds:
            kept.append( ts )
    return kept


def trailing_window_allows( sent_ts, now, max_messages, window_seconds ):
    """
    Is a new outreach to this recipient allowed under the trailing-window rate limit?

    The limit is N (`max_messages`) messages per Y (`window_seconds`). This is the
    per-recipient counterpart to the per-edge `should_ping` and the fleet-wide
    `under_global_cap`. It caps the count of recent sends in a sliding window.

    Requires:
        - sent_ts is an iterable of aware datetimes (the recipient's prior sends)
          or None; now is an aware datetime
        - max_messages (N) and window_seconds (Y·60) are numbers

    Ensures:
        - returns True (disabled — never suppress, fail-safe) when max_messages <= 0
          or window_seconds <= 0
        - otherwise returns True iff fewer than max_messages of `sent_ts` fall in the
          trailing window (in_window) — i.e. there is room for one more
        - never raises
    """
    if max_messages <= 0 or window_seconds <= 0:
        return True                                     # disabled → fail-safe allow
    return len( in_window( sent_ts, now, window_seconds ) ) < max_messages


def quick_smoke_test():
    """Self-contained smoke test. Returns True or raises AssertionError."""
    import datetime
    now  = datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=datetime.timezone.utc )

    assert edge_key( "Ann", "Bob", "blocked" ) == "Ann|Bob|blocked"
    assert edge_key( None, None, None )         == "||"

    assert backoff_for_attempt( 0 ) == 60
    assert backoff_for_attempt( 2 ) == 900
    assert backoff_for_attempt( 99 ) == 3600        # clamped
    assert backoff_for_attempt( -5 ) == 60          # negative → first

    assert should_ping( None, now, 60 ) is True     # never pinged
    assert should_ping( now - datetime.timedelta( seconds=120 ), now, 60 ) is True
    assert should_ping( now - datetime.timedelta( seconds=30 ),  now, 60 ) is False

    assert under_global_cap( 4, 5 ) is True
    assert under_global_cap( 5, 5 ) is False

    # Item C trailing-window throttle (N per Y)
    recent = [ now - datetime.timedelta( seconds=10 ), now - datetime.timedelta( seconds=20 ) ]
    old    = [ now - datetime.timedelta( seconds=10_000 ) ]
    assert in_window( recent, now, 60 )            == recent           # both within 60s
    assert in_window( recent + old, now, 60 )      == recent           # the 10_000s entry pruned
    assert in_window( [ now + datetime.timedelta( seconds=5 ) ], now, 60 ) == [ ]   # future ts dropped
    assert in_window( None, now, 60 )              == [ ]
    assert trailing_window_allows( recent, now, 3, 60 ) is True        # 2 < 3 → room
    assert trailing_window_allows( recent, now, 2, 60 ) is False       # 2 >= 2 → full
    assert trailing_window_allows( recent + old, now, 2, 60 ) is False # old pruned → 2 in window → full
    assert trailing_window_allows( recent, now, 0, 60 )  is True        # disabled (max<=0)
    assert trailing_window_allows( recent, now, 2, 0 )   is True        # disabled (window<=0)
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"ping_throttle smoke: {'PASS' if ok else 'FAIL'}" )
