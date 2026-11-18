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


def parse_iso( value ):
    """
    Parse an ISO-8601 timestamp string into a datetime, or None.

    Requires:
        - value is anything; only a non-blank str can parse

    Ensures:
        - a trailing "Z" reads as "+00:00"; surrounding whitespace is ignored
        - a stamp with no zone is read as UTC
        - returns an aware datetime
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
    return parsed


def aware_moment( value ):
    """
    Read a datetime or an ISO-8601 string as an aware datetime, passing None through.

    Requires:
        - value is None, a datetime or an ISO-8601 string; a value with no offset is read as UTC

    Ensures:
        - returns None for None
        - returns a timezone-aware datetime otherwise

    Raises:
        - AttributeError if value is a string that does not parse; parse_iso answers None and the
          zone check then fails. Callers that must survive a bad stamp use parse_iso instead
    """
    if value is None: return None
    moment = parse_iso( value ) if isinstance( value, str ) else value
    return moment if moment.tzinfo is not None else moment.replace( tzinfo=datetime.timezone.utc )
