#!/usr/bin/env python3
"""
One ISO-8601 timestamp parser for the code that reads stamps out of JSON files and rows.

Several arbiter modules each held an identical `_parse_iso`: strip, turn a trailing "Z" into
"+00:00", `fromisoformat`, and give a zone-less stamp UTC. This is the one copy. A stamp
that is unreadable is None, never an exception, so one bad row drops one row.

Hook-library code cannot import cosa, so `lupin_cli/claude_code/hooks/lib/heartbeat_hold.py`
keeps its own twin. Code that must refuse a zone-less stamp keeps its own stricter reader.
"""
import datetime


def parse_iso( value, naive=False ):
    """
    Parse an ISO-8601 timestamp string into a datetime, or None.

    Requires:
        - value is anything; only a non-blank str can parse
        - naive is a bool

    Ensures:
        - a trailing "Z" reads as "+00:00"; surrounding whitespace is ignored
        - a stamp with no zone is read as UTC
        - naive False: returns an aware datetime
        - naive True: returns the same instant as a naive datetime in UTC, with the zone dropped
        - returns None for None, a blank or non-string value, and unparseable text
        - never raises
    """
    if not value or not isinstance( value, str ): return None
    text = value.strip()
    if text.endswith( "Z" ): text = text[ :-1 ] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat( text )
    except ValueError:
        return None
    if parsed.tzinfo is None: parsed = parsed.replace( tzinfo=datetime.timezone.utc )
    if naive: return parsed.astimezone( datetime.timezone.utc ).replace( tzinfo=None )
    return parsed
