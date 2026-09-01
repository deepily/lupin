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


# ---------------------------------------------------------------------------
# EXECUTION TESTS
#
# Everything above reads the asset and asserts a property of its TEXT: the
# origins are declared, distinct, and reachable. That cannot see a WIRING
# mistake — two arms tagged with each other's constant read as five correct
# tags and produce two wrong answers. Running the code is the only thing that
# separates "the tags exist" from "the tags discriminate".
#
# Raised by Mr Radio reviewing the first cut: prove the tag discriminates by
# driving it under different conditions. The text tests alone would have passed
# a crossed pair.
# ---------------------------------------------------------------------------

import json
import shutil
import subprocess

DRIVER_MJS = "/src/tests/unit/js/drive-session-id-fallback.mjs"


def _drive():
    """
    Run the shipped getOrCreateSessionId under each failure condition.

    Requires:
        - node is on PATH
        - the driver script and notifications.js both exist

    Ensures:
        - returns the driver's parsed report: per-condition origins plus the
          happy-path control

    Raises:
        - pytest.skip if node is absent, naming what did NOT get checked
        - pytest.fail if the driver exits non-zero
    """
    node = shutil.which( "node" )

    if node is None:
        # A skip is a no-op, so say plainly which guard did not run rather than
        # letting a green suite imply it did.
        pytest.skip(
            "node is not on PATH — the session-ID fallback origins were NOT "
            "exercised. The text-level tests above still ran; the wiring is "
            "unverified in this environment."
        )

    root   = cu.get_project_root()
    result = subprocess.run(
        [ node, root + DRIVER_MJS, root + NOTIFICATIONS_JS ],
        capture_output = True,
        text           = True,
        timeout        = 60
    )

    if result.returncode != 0:
        pytest.fail(
            f"the fallback driver exited {result.returncode}. This is the DRIVER "
            f"failing, not a verdict on the code under test — its anchors may "
            f"need re-pointing.\nstderr:\n{result.stderr}"
        )

    return json.loads( result.stdout )


def test_each_failure_condition_produces_its_own_origin():
    """
    The assertion the text tests cannot make. Five conditions, each breaking
    exactly one thing; a crossed pair of tags shows up here and nowhere else.
    """
    report = _drive()

    expected = {
        "token refresh fails"             : "token-refresh-failed",
        "transport failure (tunnel down)" : "network-unreachable",
        "endpoint answers 502"            : "http-status",
        "a 200 that is not JSON"          : "payload-not-json",
        "JSON without session_id"         : "payload-missing-field",
    }

    observed = { row[ "label" ]: row[ "origin" ] for row in report[ "results" ] }

    assert observed == expected, (
        f"a failure condition reported the wrong origin.\n"
        f"expected: {expected}\nobserved: {observed}\n"
        f"Two arms tagged with each other's constant produce exactly this, and "
        f"every text-level check still passes."
    )


def test_the_five_origins_are_distinct_when_actually_run():
    """
    Distinct DECLARED values (asserted above) do not imply distinct OBSERVED
    ones — a copy-paste at the throw sites collapses two conditions onto one
    origin while the constants themselves stay pairwise distinct.
    """
    origins = [ row[ "origin" ] for row in _drive()[ "results" ] ]

    assert len( set( origins ) ) == len( origins ), (
        f"two failure conditions produced the SAME origin: {origins}. They are "
        f"indistinguishable at the log line, which is the defect this row exists "
        f"to close."
    )


def test_the_token_arm_reports_without_reaching_the_endpoint():
    """
    ensureValidToken() runs inside the try and BEFORE the fetch, so a token
    failure implicates the endpoint not at all. The driver's fetch stub throws a
    distinctive error if reached; the token message appearing here is what
    proves the short-circuit.
    """
    row = next(
        r for r in _drive()[ "results" ] if r[ "label" ] == "token refresh fails"
    )

    assert "fetch must NOT be reached" not in row[ "message" ], (
        "the token arm reached fetch(). It is supposed to throw before any HTTP "
        "request is made — otherwise a token failure gets reported as a network "
        "or status failure."
    )
    assert row[ "origin" ] == "token-refresh-failed"


def test_the_happy_path_writes_no_fallback_record():
    """
    Negative control, and the one that makes the others mean anything. If a
    fallback record were written when the server answers normally, its presence
    would not be evidence of a failure and every origin above would be noise.
    """
    happy = _drive()[ "happyPath" ]

    assert happy[ "id" ] == "server issued", (
        f"the happy path returned {happy[ 'id' ]!r} instead of the server's id — "
        f"the normal path is not being taken at all."
    )
    assert happy[ "wroteFallbackRecord" ] is False, (
        "a fallback record was written on the happy path. Its presence would no "
        "longer indicate a degraded session."
    )


def test_a_refusing_localstorage_does_not_escape_as_a_throw():
    """
    Tiberius's review nit, and it was a real one: the DIAGNOSTIC write was
    guarded while the PRIMARY write was not, so a full or disabled localStorage
    turned a degraded-but-working session into an exception escaping
    getOrCreateSessionId() — and the docstring claimed otherwise.

    Two arms, one variable, measured at 733829ab+: with the guard reverted the
    driver reports threw=True and id=None; with it in place, threw=False and a
    valid id. Nothing else in this file moves between those two arms, which is
    why the assertion below is the one that holds the fix.
    """
    refusal = _drive()[ "storageRefusal" ]

    assert refusal[ "threw" ] is False, (
        f"a refusing localStorage propagated out of getOrCreateSessionId: "
        f"{refusal.get( 'error' )}. The caller asked for a session id and one "
        f"was available — a storage failure must not deny it."
    )
    assert refusal[ "id" ], "no session id was returned when localStorage refused every write"


def test_a_non_object_throw_still_reports_its_real_origin():
    """
    Tiberius's second review nit, and the measurement corrected the claim.

    `error` is not guaranteed to be an object — a rejected promise can carry
    null or a primitive, and a class body is strict mode, so tagging one raises
    a TypeError. The obvious reading is that this crashes the method. IT DOES
    NOT: measured with both guards reverted, all four non-object throws still
    returned an id, because the tagger's TypeError is caught by the same catch
    it was about to reach.

    What is actually lost is the DIAGNOSIS. Guards reverted, every one of the
    four reports origin 'unclassified' and carries the TypeError's message
    instead of the real cause. Guards in place, all four report
    'network-unreachable'. That is the whole point of this row, so it earns a
    test — but as a diagnosis guarantee, not a crash guarantee.
    """
    rows = _drive()[ "nonObjectThrows" ]

    assert len( rows ) == 4, f"expected four non-object throw cases, got {len( rows )}"

    misreported = [ r for r in rows if r[ "origin" ] != "network-unreachable" ]

    assert misreported == [], (
        f"a non-object throw lost its origin: {misreported}. The fetch stub "
        f"rejected, so every one of these is a transport failure and must say "
        f"so — 'unclassified' here means the tagger failed and the real cause "
        f"was replaced by its own TypeError."
    )

    # The crash guarantee is asserted too, but it holds in BOTH arms — it is
    # not what the guards buy, and recording that keeps the next reader from
    # crediting them with it.
    assert all( r[ "threw" ] is False for r in rows ), (
        "a non-object throw escaped getOrCreateSessionId entirely."
    )
