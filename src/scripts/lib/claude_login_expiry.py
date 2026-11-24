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
import os
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


def classify_refresh( refresh_len, refresh_expires_ms, now_ms, warn_days=7 ):
    """
    Classify the refresh token from its length and expiry number alone, never its text.

    Requires:
        - refresh_len is the length of the stored refresh token
        - refresh_expires_ms is its expiry in milliseconds since the epoch, 0 when absent

    Ensures:
        - returns ( "blank", reason ) when the token is empty: no renewal is possible
        - returns ( "lapsed", iso ) when its expiry is at or before now_ms
        - returns ( "soon", iso ) when it lapses within warn_days
        - returns ( "ok", iso ) otherwise; an absent expiry with a token present is ( "ok", "no expiry recorded" )
    """
    if refresh_len <= 0: return "blank", "the refresh token is empty, so no renewal is possible"
    if refresh_expires_ms <= 0: return "ok", "no expiry recorded"
    if refresh_expires_ms <= now_ms: return "lapsed", _iso( refresh_expires_ms )
    if refresh_expires_ms - now_ms < warn_days * 86400 * 1000: return "soon", _iso( refresh_expires_ms )
    return "ok", _iso( refresh_expires_ms )


def refresh_main( argv ):
    """
    Print the tick's finding for: --refresh <container> <refresh_len> <refresh_expires_ms>.

    Ensures:
        - prints nothing and returns 0 when ok
        - prints one line with the remedy and returns 2 for blank or lapsed, 3 for soon
    """
    container, refresh_len, expires = argv[ 2 ], int( argv[ 3 ] ), int( argv[ 4 ] )
    warn_days                       = int( os.environ.get( "CLAUDE_LOGIN_WARN_DAYS", "7" ) )
    status, detail                  = classify_refresh( refresh_len, expires, int( time.time() * 1000 ), warn_days )
    if status == "ok": return 0
    verb = { "blank": "is blank", "lapsed": "refresh token lapsed", "soon": "refresh token lapses" }[ status ]
    print( f"claude login in {container} {verb} {detail}; renew with: docker exec -it {container} claude /login" )
    return 3 if status == "soon" else 2


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
    sys.exit( refresh_main( sys.argv ) if len( sys.argv ) > 4 and sys.argv[ 1 ] == "--refresh" else main( sys.argv ) )
