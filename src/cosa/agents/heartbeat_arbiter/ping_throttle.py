#!/usr/bin/env python3
"""
Heartbeat Arbiter — auto-ping throttle / per-edge backoff (pure).

The arbiter (doc 03 §6.1 / §7) DMs a blocker at most once per (holder, awaited,
reason) edge per backoff window — never re-pinging every poll (the no-storm
invariant, Sam-TTS lesson) — and honors a global fleet-wide rate cap across all
arbiter-originated DMs.

Pure decisions only: the consumer holds the per-edge state (last-ping ts +
attempt count) and the recent-DM count; these functions decide. Clear-on-resume
(dropping an edge when the holder stops awaiting) is the consumer's wiring.

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
    Should this edge be pinged NOW? (per-edge throttle)

    Requires:
        - last_ping_ts is an aware datetime or None (None = never pinged)
        - now is an aware datetime
        - backoff_seconds is a positive number

    Ensures:
        - Returns True iff never pinged, OR the backoff window has elapsed
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
    Is the fleet-wide arbiter-DM rate under the global cap? (§7 no-storm)

    Requires:
        - recent_ping_count is the count of arbiter DMs in the current window (int)
        - cap is the max allowed (positive int)

    Ensures:
        - Returns True iff recent_ping_count < cap
        - Never raises
    """
    return recent_ping_count < cap


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
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"ping_throttle smoke: {'PASS' if ok else 'FAIL'}" )
