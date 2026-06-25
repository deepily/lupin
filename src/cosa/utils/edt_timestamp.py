#!/usr/bin/env python3
"""
Central EDT timestamp formatter — the ONE owner of Rick's outreach-stamp shape.

Rick (2026-06-24): every DM (worker↔manager, manager↔manager, all directions) must
carry the SAME bracketed local-time prefix the arbiter pings already carry — e.g.
`[2026.06.24 at 18:44:09]` — sourced from ONE central, neutral place reused
everywhere (don't reinvent the wheel).

The format + tz + renderer originally lived INSIDE the heartbeat_arbiter package
(`arbiter_journal.py`). That made it un-reusable by the REST DM path without a bad
dependency direction (REST → arbiter). This module is the neutral home in
`cosa/utils/`, importable by BOTH the REST layer (`rest/routers/dm.py`) and the
arbiter (`agents/heartbeat_arbiter/arbiter_journal.py`, which now re-exports these
names so the arbiter ping output stays BYTE-IDENTICAL).

Two public renderers, distinct only by bracketing:
    - format_outreach_ts( dt, tz ) -> "2026.06.24 at 18:44:09"   (INNER string; the
      arbiter caller wraps its own brackets at arbiter_job.py _stamp).
    - format_edt_timestamp( dt=None, tz_name=None ) -> "[2026.06.24 at 18:44:09]"
      (BRACKETED, self-contained prefix; the DM chokepoint prepends this + a space).

The two are drift-locked: format_edt_timestamp( dt, tz ) + " " is VISUALLY IDENTICAL
to the arbiter caller's f"[{format_outreach_ts( dt, tz )}] " — a reader cannot tell a
DM's stamp from an arbiter ping's stamp (test-locked in test_edt_timestamp.py).

Degrade-safe by the observer invariant: an invalid/unknown timezone must never raise
— it falls back to UTC rendering (resolve_tz returns a UTC ZoneInfo + an error string
the caller may journal once).

Design: src/rnd/v0.1.9/2026.06.24-central-edt-timestamp-on-all-dms.md
"""
import datetime
import re
from typing import Any, Optional
from zoneinfo import ZoneInfo

# Rick's ratified OUTREACH-stamp format (2026-06-24): "2026.06.24 at 11:47:57"
# — the human-facing leading prefix on every arbiter shoulder-tap/outreach message
# AND (as of this milestone) every peer DM.
OUTREACH_TS_FORMAT  = "%Y.%m.%d at %H:%M:%S"
DEFAULT_TZ_NAME     = "America/New_York"

# A body that ALREADY leads with a bracketed EDT stamp of the exact shape this
# module emits — "[YYYY.MM.DD at HH:MM:SS]" — anchored at string start, tolerating
# one optional leading space. Used by the DM chokepoint to stay IDEMPOTENT (bug
# f49a8b34 / bc8d9d82): a body the arbiter (or any caller) already stamped must NOT
# be re-wrapped into a "[outer] [inner]" double-stamp.
_LEADING_EDT_STAMP_RE = re.compile( r"^ ?\[\d{4}\.\d{2}\.\d{2} at \d{2}:\d{2}:\d{2}\]" )


def resolve_tz( tz_name: Optional[ str ] ):
    """
    Resolve a tz-database name to a ZoneInfo, degrade-safe.

    Requires:
        - tz_name is a string tz-database name (e.g. "America/New_York") or None

    Ensures:
        - returns ( ZoneInfo, None ) for a valid name (None → DEFAULT_TZ_NAME)
        - returns ( ZoneInfo("UTC"), <error string> ) for an invalid/unknown
          name — the caller journals the error ONCE; rendering falls back to UTC
        - never raises
    """
    name = tz_name if tz_name else DEFAULT_TZ_NAME
    try:
        return ZoneInfo( name ), None
    except Exception as e:
        return ZoneInfo( "UTC" ), f"unknown timezone {name!r}: {e}"


def format_outreach_ts( dt: datetime.datetime, tz: Any ) -> str:
    """
    Render an aware datetime as Rick's outreach stamp "YYYY.MM.DD at HH:MM:SS"
    (2026-06-24) in the given tz — the INNER string (no brackets); the arbiter
    caller wraps its own brackets.

    Requires:
        - dt is an AWARE datetime
        - tz is a tzinfo (ZoneInfo) — REUSE resolve_tz to obtain it; this function
          builds NO tz infra

    Ensures:
        - returns the same instant as `dt` rendered "%Y.%m.%d at %H:%M:%S"
          (e.g. "2026.06.24 at 11:47:57"); DST handled by the tz database
    """
    return dt.astimezone( tz ).strftime( OUTREACH_TS_FORMAT )


def format_edt_timestamp( dt: Optional[ datetime.datetime ] = None, tz_name: Optional[ str ] = None ) -> str:
    """
    The self-contained, BRACKETED EDT prefix for any DM body — "[YYYY.MM.DD at
    HH:MM:SS]" — matching the arbiter ping's bracketed shape exactly.

    Requires:
        - dt is an AWARE datetime, or None (None → current aware UTC instant)
        - tz_name is a tz-database name, or None (None → DEFAULT_TZ_NAME); an
          invalid/unknown name degrades to UTC (never raises)

    Ensures:
        - returns "[" + format_outreach_ts( dt, resolve_tz( tz_name ) ) + "]"
          (e.g. "[2026.06.24 at 18:44:09]"); DST handled by the tz database
        - dt=None renders "now" in the resolved tz
        - an invalid tz_name renders the instant in UTC (degrade-safe)
        - never raises
    """
    if dt is None:
        dt = datetime.datetime.now( datetime.timezone.utc )
    tz, _error = resolve_tz( tz_name )
    return f"[{format_outreach_ts( dt, tz )}]"


def is_already_stamped( text: Any ) -> bool:
    """
    True iff `text` ALREADY begins with a bracketed EDT stamp of the exact shape
    `format_edt_timestamp` emits — "[YYYY.MM.DD at HH:MM:SS]" — anchored at string
    start (tolerating one optional leading space).

    The DM chokepoint (`rest/routers/dm.py`) calls this to stay IDEMPOTENT: a body
    an upstream caller already stamped (an arbiter ping pre-stamped via _route, then
    pushed through /api/dm/send) is passed through UNCHANGED instead of being
    re-wrapped into a "[push-ts] [compose-ts]" double-stamp (bug f49a8b34 / bc8d9d82).

    Requires:
        - text is any value (defensive — a non-string is never "stamped")

    Ensures:
        - returns True iff text is a str whose start matches
          "^ ?\\[YYYY.MM.DD at HH:MM:SS\\]" (the exact format_edt_timestamp shape)
        - returns False for a non-string, an empty string, an unstamped body, or a
          stamp that appears only MID-string (must lead)
        - never raises (pure)
    """
    return isinstance( text, str ) and _LEADING_EDT_STAMP_RE.match( text ) is not None


def quick_smoke_test():
    """Self-contained smoke test (no IO). Returns True or raises AssertionError."""
    june = datetime.datetime( 2026, 6, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )
    jan  = datetime.datetime( 2026, 1, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )

    # inner renderer: EDT in June, EST in January (DST handled by the tz database)
    tz, err = resolve_tz( "America/New_York" )
    assert err is None
    assert format_outreach_ts( june, tz ) == "2026.06.11 at 17:28:46"
    assert format_outreach_ts( jan,  tz ) == "2026.01.11 at 16:28:46"

    # bracketed prefix: matches the arbiter ping's "[...]" shape exactly
    assert format_edt_timestamp( june )                    == "[2026.06.11 at 17:28:46]"
    assert format_edt_timestamp( jan, "America/New_York" ) == "[2026.01.11 at 16:28:46]"

    # invalid tz → UTC fallback, never raises
    assert format_edt_timestamp( june, "Not/AZone" )       == "[2026.06.11 at 21:28:46]"

    # drift-lock: DM prefix + " " is visually identical to the arbiter caller's wrap
    assert format_edt_timestamp( june ) + " " == f"[{format_outreach_ts( june, tz )}] "

    # None dt renders "now" — just assert the bracketed shape (length + delimiters)
    now_prefix = format_edt_timestamp()
    assert now_prefix.startswith( "[" ) and now_prefix.endswith( "]" ) and " at " in now_prefix
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"edt_timestamp smoke: {'PASS' if ok else 'FAIL'}" )
