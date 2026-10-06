#!/usr/bin/env python3
"""
Central EDT timestamp formatter: the one owner of the outreach-stamp shape.

Every DM, in every direction, carries the same bracketed local-time prefix the
arbiter pings carry, for example `[2026.06.24 at 18:44:09]`. One neutral module
supplies it, so nobody reinvents it.

The format, timezone and renderer began inside the heartbeat_arbiter package.
The REST DM path could not reuse them without a bad dependency direction (REST
importing the arbiter). This module is the neutral home in `cosa/utils/`. The
REST layer (`rest/routers/dm.py`) and the arbiter
(`agents/heartbeat_arbiter/arbiter_journal.py`) both import it. The arbiter
re-exports these names so its ping output stays byte-identical.

Two public renderers differ only by bracketing:
    - format_outreach_ts( dt, tz ) -> "2026.06.24 at 18:44:09" (inner string,
      no brackets; the arbiter caller adds its own brackets in `_stamp`).
    - format_edt_timestamp( dt=None, tz_name=None ) -> "[2026.06.24 at 18:44:09]"
      (bracketed and self-contained; the DM chokepoint prepends it plus a space).

The two are drift-locked. format_edt_timestamp( dt, tz ) + " " is identical to
the arbiter caller's f"[{format_outreach_ts( dt, tz )}] ". A reader cannot tell
a DM stamp from an arbiter ping stamp. test_edt_timestamp.py locks this.

An invalid or unknown timezone never raises. Rendering falls back to UTC, and
resolve_tz returns an error string the caller may journal once.
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
        - returns ( ZoneInfo, None ) for a valid name (None -> DEFAULT_TZ_NAME)
        - returns ( ZoneInfo("UTC"), <error string> ) for an invalid/unknown
          name; the caller journals the error once, and rendering falls back to UTC
        - never raises
    """
    name = tz_name if tz_name else DEFAULT_TZ_NAME
    try:
        return ZoneInfo( name ), None
    except Exception as e:
        return ZoneInfo( "UTC" ), f"unknown timezone {name!r}: {e}"


def format_outreach_ts( dt: datetime.datetime, tz: Any ) -> str:
    """
    Render an aware datetime as the inner outreach stamp "YYYY.MM.DD at HH:MM:SS".

    The result has no brackets; the arbiter caller adds its own.

    Requires:
        - dt is an aware datetime
        - tz is a tzinfo (ZoneInfo); obtain it with resolve_tz, since this function
          builds no timezone infrastructure

    Ensures:
        - returns the same instant as `dt` rendered "%Y.%m.%d at %H:%M:%S"
          (e.g. "2026.06.24 at 11:47:57"); DST is handled by the tz database
    """
    return dt.astimezone( tz ).strftime( OUTREACH_TS_FORMAT )


def format_edt_timestamp( dt: Optional[ datetime.datetime ] = None, tz_name: Optional[ str ] = None ) -> str:
    """
    Return the bracketed EDT prefix "[YYYY.MM.DD at HH:MM:SS]" for a DM body.

    The shape matches the arbiter ping's bracketed stamp exactly.

    Requires:
        - dt is an aware datetime, or None (None -> current aware UTC instant)
        - tz_name is a tz-database name, or None (None -> DEFAULT_TZ_NAME); an
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
    Return True iff `text` already begins with a bracketed EDT stamp.

    The shape is exactly what format_edt_timestamp emits, at the start of the string
    (one optional leading space tolerated). The DM chokepoint uses it to stay
    idempotent, so a pre-stamped arbiter ping is not re-wrapped into a double stamp.

    Requires:
        - text is any value (defensive: a non-string is never "stamped")

    Ensures:
        - returns True iff text is a str whose start matches
          "^ ?\\[YYYY.MM.DD at HH:MM:SS\\]" (the exact format_edt_timestamp shape)
        - returns False for a non-string, an empty string, an unstamped body, or a
          stamp that appears only mid-string (it must lead)
        - never raises (pure)
    """
    return isinstance( text, str ) and _LEADING_EDT_STAMP_RE.match( text ) is not None


def split_leading_stamp( text ):
    """
    Split a leading EDT stamp off `text` and return ( stamp, rest ).

    It matches the same shape as `is_already_stamped`. A non-timestamp leading
    bracket such as "[URGENT] ..." is never eaten. The peer-DM framing uses it to
    fold the stamp into the header line; the stored body is left untouched.

    Requires:
        - text is any value (defensive: a non-string has no stamp)

    Ensures:
        - text begins with a stamp -> ( stamp, rest ): stamp is the bracketed
          timestamp string with surrounding whitespace stripped (e.g.
          "[2026.08.15 at 21:29:37]"); rest is text with that stamp and the
          whitespace right after it removed
        - no leading stamp (or a non-string) -> ( None, text ) with text unchanged
          (byte-identical pass-through)
        - never raises (pure)
    """
    if not isinstance( text, str ):
        return None, text
    m = _LEADING_EDT_STAMP_RE.match( text )
    if m is None:
        return None, text
    stamp = m.group( 0 ).strip()
    rest  = text[ m.end(): ].lstrip()
    return stamp, rest


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

    # split_leading_stamp — BOTH branches (falsifiable):
    # stamp present → (stamp, clean rest); the stamp round-trips is_already_stamped.
    stamp, rest = split_leading_stamp( "[2026.08.15 at 21:29:37] hello there" )
    assert stamp == "[2026.08.15 at 21:29:37]" and rest == "hello there"
    assert is_already_stamped( stamp )
    # no leading stamp → (None, text) byte-identical pass-through, and a non-timestamp
    # leading bracket is NEVER eaten.
    assert split_leading_stamp( "[URGENT] ship it" )     == ( None, "[URGENT] ship it" )
    assert split_leading_stamp( "no stamp at all" )      == ( None, "no stamp at all" )
    assert split_leading_stamp( 12345 )                  == ( None, 12345 )   # non-string
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"edt_timestamp smoke: {'PASS' if ok else 'FAIL'}" )
