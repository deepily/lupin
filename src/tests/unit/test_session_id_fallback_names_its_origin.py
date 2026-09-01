"""
The browser's session-ID fallback must say WHICH failure sent it there.

WHY THIS TEST EXISTS. Fixing the 403 (ad2cbbbe) made the degradation SILENT.
Before, a browser that failed to obtain a server-issued session id minted its
own, joined the words with an underscore, and reconnect-looped on 403 — loud,
and impossible to miss. After, the id is well-formed, the socket connects, and
nothing anywhere says the id was self-minted.

`getOrCreateSessionId()` in notifications.js has ONE catch shared by five
failures with five different causes and five different owners:

    token-refresh-failed   ensureValidToken() threw — NO HTTP request was made,
                           so the session endpoint is not implicated at all
    network-unreachable    fetch() rejected — transport: DNS, refused connection,
                           a dropped tunnel, CORS
    http-status            the endpoint answered non-2xx
    payload-not-json       a 200 that would not parse — the signature of an
                           intermediary answering instead of the endpoint
    payload-missing-field  parsed fine, no session_id in it

The original catch logged one line for all five. This test fails if a throw
inside that try can reach the catch WITHOUT naming its origin, and — the part a
string-matching test misses — if two origins carry the same value, which makes
them indistinguishable at the log line no matter how distinctly they are named.

⚠️ READ THE SHIPPED ASSET, DO NOT RESTATE IT. Same reasoning as
test_browser_fallback_session_id_is_server_valid.py: a test that hardcodes the
origin strings measures what this file wrote, not what the browser ships.
"""
import re
from pathlib import Path

import pytest

import cosa.utils.util as cu


NOTIFICATIONS_JS = "/src/lupin_app/static/js/notifications.js"

# Line-anchored at the class's method indent: a bare name also matches
# every call site, and a call site is not a definition.
_GET_OR_CREATE = r"^    async getOrCreateSessionId\("


def _source():
    """
    Read the shipped notifications.js.

    Requires:
        - notifications.js exists under the project root

    Ensures:
        - returns the file's full text

    Raises:
        - OSError if the asset is missing
    """
    return Path( cu.get_project_root() + NOTIFICATIONS_JS ).read_text()


def _method_body( source, anchor ):
    """
    Slice one method body out of the class by brace-matching from its signature.

    Brace-matching rather than a line count, so an edit above or below the method
    cannot silently change what this test is reading. The anchor is a REGEX and
    is expected to be line-anchored, because a method's DEFINITION is a substring
    of every `this.<name>( ... )` call to it — a plain literal matches both.

    Requires:
        - anchor matches exactly once in source
        - the method opens a brace on its signature line

    Ensures:
        - returns the text between the method's outermost braces

    Raises:
        - pytest.fail if the anchor does not match exactly once
    """
    hits = [ m.start() for m in re.finditer( anchor, source, re.MULTILINE ) ]

    if len( hits ) != 1:
        pytest.fail(
            f"expected exactly ONE match for {anchor!r} in {NOTIFICATIONS_JS}, found "
            f"{len( hits )}. The method moved or was duplicated — re-point this "
            f"test at it rather than relaxing the anchor."
        )

    start = source.index( "{", hits[ 0 ] )
    depth = 0

    for index in range( start, len( source ) ):
        if source[ index ] == "{": depth += 1
        if source[ index ] == "}":
            depth -= 1
            if depth == 0: return source[ start : index + 1 ]

    pytest.fail( f"unbalanced braces reading {signature!r} from {NOTIFICATIONS_JS}" )


def _strip_line_comments( body ):
    """
    Remove `//` line comments so a scan measures CODE, not prose about it.

    The word "throw" in a comment explaining the throws is not a throw. Scanning
    the raw text searches a population that includes the commentary.

    Requires:
        - body is JavaScript source text

    Ensures:
        - returns body with every `//`-to-end-of-line run removed

    Raises:
        - None
    """
    return re.sub( r"//[^\n]*", "", body )


def _declared_origins( source ):
    """
    Extract the FALLBACK_ORIGIN name->value map from the shipped JS.

    Requires:
        - source declares a FALLBACK_ORIGIN getter returning an object literal

    Ensures:
        - returns a dict of constant name to its string value

    Raises:
        - pytest.fail if the getter is absent or matches more than once
    """
    body = _method_body( source, r"^    get FALLBACK_ORIGIN\(\)" )

    return dict( re.findall( r"(\w+)\s*:\s*'([^']+)'", body ) )


def test_every_throw_in_the_session_id_try_names_its_origin():
    """
    The regression itself: a throw that reaches the shared catch untagged is a
    failure whose cause the log line cannot report.
    """
    body   = _strip_line_comments( _method_body( _source(), _GET_OR_CREATE ) )
    throws = re.findall( r"\bthrow\s+(\S+)", body )

    untagged = [ t for t in throws if "tagSessionIdFailure" not in t ]

    assert untagged == [], (
        f"{len( untagged )} throw(s) inside getOrCreateSessionId reach the shared "
        f"catch without an origin: {untagged}. Wrap each in "
        f"this.tagSessionIdFailure( error, this.FALLBACK_ORIGIN.<NAME> ) or the "
        f"log line cannot say which failure fired."
    )

    # A zero-throw body would pass the assertion above for the wrong reason —
    # nothing to be untagged. Prove the search found a population.
    assert len( throws ) >= 4, (
        f"only {len( throws )} throws found in getOrCreateSessionId; the method "
        f"is expected to distinguish at least four failure origins. The anchor "
        f"may be reading the wrong method."
    )


def test_the_declared_origins_are_pairwise_distinct():
    """
    The failure a string-matching test misses. Five distinctly NAMED constants
    that share a VALUE are indistinguishable in the log line — the code reads as
    correct, every throw is tagged, and two causes still report as one.
    """
    origins = _declared_origins( _source() )

    assert len( origins ) >= 5, (
        f"FALLBACK_ORIGIN declares {len( origins )} constants; at least five "
        f"distinguishable failures reach the shared catch."
    )

    duplicates = { value for value in origins.values() if list( origins.values() ).count( value ) > 1 }

    assert duplicates == set(), (
        f"FALLBACK_ORIGIN values {duplicates} are used by more than one constant. "
        f"Two origins sharing a value cannot be told apart at the log line, which "
        f"is the whole reason the origins exist."
    )


def test_each_declared_origin_is_actually_reachable():
    """
    Negative control against the opposite failure: a constant that nothing throws
    is a cause the log can name and never will, and it inflates the count above
    without adding any diagnostic power.
    """
    source  = _source()
    origins = _declared_origins( source )
    body    = _method_body( source, _GET_OR_CREATE )

    # UNCLASSIFIED is the catch's own default for an untagged error and is
    # deliberately not thrown anywhere.
    unreachable = [
        name for name in origins
        if name != "UNCLASSIFIED" and f"FALLBACK_ORIGIN.{name}" not in body
    ]

    assert unreachable == [], (
        f"FALLBACK_ORIGIN declares {unreachable} but nothing in "
        f"getOrCreateSessionId throws with them — either wire them up or drop them."
    )


def test_the_fallback_announces_at_error_level():
    """
    A working socket on an id the server never issued is the state this row
    exists to make visible. Logging it at this.log leaves it invisible at the
    default log level, which is how the condition went unnoticed.
    """
    body = _method_body( _source(), r"^    useFallbackSessionId\(" )

    assert "this.error(" in body, (
        "useFallbackSessionId does not announce via this.error(). A client "
        "running on a self-minted session id must be visible without raising "
        "the log level."
    )
