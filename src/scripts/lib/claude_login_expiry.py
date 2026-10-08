#!/usr/bin/env python3
"""
Say whether a Claude Code login has expired, from its expiry field alone.

The test container keeps its own Claude Code login. When it expires every Claude Code job there fails.
The preflight reads one number from the credentials file, the expiry in milliseconds since the epoch.
That number is the only part of the file this module sees, so no token is ever read.

Usage:
    claude_login_expiry.py <expiresAt>

It prints one line, the verdict then a detail, and exits 0 for valid and 1 otherwise.
"""

import datetime
import sys
import time


def _iso( milliseconds ):
    """
    Render a millisecond epoch as an ISO 8601 UTC string.

    Requires:
        - milliseconds is a positive integer

    Ensures:
        - returns the instant in UTC with an explicit offset
    """
    return datetime.datetime.fromtimestamp( milliseconds / 1000, datetime.timezone.utc ).isoformat()


def classify( raw, now_ms ):
    """
    Classify an expiry value as expired, valid or unreadable.

    Requires:
        - raw is the text read from the credentials file
        - now_ms is the current time in milliseconds since the epoch

    Ensures:
        - returns ( "expired", iso ) when the expiry is at or before now_ms
        - returns ( "valid", iso ) when the expiry is after now_ms
        - returns ( "unreadable", reason ) unless raw is a positive whole number after trimming
    """
    text = raw.strip() if isinstance( raw, str ) else ""
    if not text.isdigit() or int( text ) <= 0:
        return "unreadable", f"expiry field is not a positive whole number: {text[ :40 ]!r}"
    expires_ms = int( text )
    return ( "expired" if expires_ms <= now_ms else "valid" ), _iso( expires_ms )


def main( argv ):
    """
    Print the verdict for the expiry given as the first argument.

    Requires:
        - argv[ 1 ], when present, is the raw expiry text

    Ensures:
        - prints exactly one line
        - returns 0 for valid and 1 for expired or unreadable
    """
    raw             = argv[ 1 ] if len( argv ) > 1 else ""
    status, detail  = classify( raw, int( time.time() * 1000 ) )
    print( f"{status} {detail}" )
    return 0 if status == "valid" else 1


if __name__ == "__main__":
    sys.exit( main( sys.argv ) )
