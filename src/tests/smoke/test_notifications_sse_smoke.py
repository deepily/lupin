#!/usr/bin/env python3
"""
Smoke Test for SSE Response-Required Notifications (Phase 2.1).

Quick end-to-end test of response-required notification flow:
- Fire-and-forget mode (backward compatibility)
- Response-required with timeout
- Response submission endpoint
- Offline detection with defaults

Run: python src/tests/smoke/test_notifications_sse_smoke.py

🔴 VENUE — THIS FILE IS HETEROGENEOUS. THE FOLDER NAME IS NOT THE VERDICT.
Route each test by the CLAUDE.md § TESTING VENUES rubric. Read from the route's
own ordering at sha 98319e12, 2026-09-08 — READ, NOT DRIVEN:

  `notify_user` persists at routers/notifications.py:1063 (`_persist_notification_sync`).
  Every validation refusal raises BEFORE that line, so a refused call writes nothing:

    (the two row-WRITING tests were MOVED OUT on 2026-09-08 — see the note below)
    test_a_missing_response_type_is_rejected     400   raises at :872, < :1063          -> :7999 ok
    test_an_invalid_response_type_is_rejected    400   raises at :879, < :1063          -> :7999 ok
    test_api_key_validation                401          `Depends( require_api_key_or_jwt )`, never
                                                        enters the handler at all              -> :7999 ok
    the four response-door tests below     404 / 422    a different route, no write path       -> :7999 ok

⇒ EVERY TEST REMAINING IN THIS FILE IS :7999-ELIGIBLE. It writes nothing.

🔴 THE TWO THAT DID WRITE ARE GONE — `test_fire_and_forget_mode` and
`test_offline_with_default` moved to
`src/tests/integration/test_notify_door_persists_rows_live.py`, which
`run-integration-tests.sh:227` sweeps as the :8000-scheduled gate. They each
created a Notification row nothing cleans up, while `run-smoke-tests.sh:47`
swept this whole directory on the :7999 leg of the merge pyramid.

⚠️ DO NOT MOVE THEM BACK, AND DO NOT ADD A ROW-WRITING TEST HERE. The second of
them creates the ORPHAN SPECIES of row bf4f65c3 — `response_requested=True` with
a `response_default`, never marked expired. It has never actually made one only
because it fails at the credential defect (row c46ba7c0) before reaching the
handler; measured 2026-09-08, zero such rows in lupin_db_dev or lupin_db_test
against 490,996 and 567 rows respectively. Repairing that credential defect
while a row-writer sits in this directory would start minting orphans on every
merge-gate fire.

⚠️ THIS IS A CODE READING, NOT A MEASUREMENT. Proving the six write nothing needs
a row-count around each call WITH a positive control showing the counter can move
— and that control requires deliberately writing one row, which is the very thing
the :7999 rubric bars. So the negative is argued from the route's ordering, not
observed. Do not upgrade it to "measured" without that arm.
"""

import sys
import os
import requests
import json
import time
from threading import Thread

# Bootstrap imports
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    print( "ERROR: LUPIN_ROOT environment variable not set" )
    sys.exit( 1 )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu


# Configuration
BASE_URL = "http://localhost:7999"
API_KEY  = "claude_code_simple_key"
TEST_USER = os.environ.get( "LUPIN_DEV_EMAIL", "test@example.com" )  # From env or fallback for smoke tests


def print_test_header( test_name ):
    """Print formatted test header."""
    print( f"\n{'=' * 60}" )
    print( f"  {test_name}" )
    print( f"{'=' * 60}" )


# ---------------------------------------------------------------------------
# Test 2: response-required validation, ONE REQUEST PER TEST.
#
# 🔴 WHY THIS IS TWO FUNCTIONS AND NOT ONE. It was one function holding two
# cases behind a bare `assert`. An assert ENDS the function, so case 2's POST
# was never issued whenever case 1 failed — and case 1 has been failing.
#
# Measured 2026-09-08 ~20:03 EDT, live :7999, using case 2's own print marker
# as the instrument: "Invalid type - Status Code" appeared ZERO times in the
# run. The suite was not testing the invalid-response_type path weakly. It was
# not asking at all, and no coverage number or green tick can show you a
# request that never left the process.
#
# ⚠️ THIS IS A DIFFERENT MECHANISM FROM THE EXCEPTION SWALLOW REPAIRED
# ELSEWHERE IN THIS FILE, and the swallow fix does NOT repair it. The swallow
# hid an answer already fetched; this loses the QUESTION.
# ---------------------------------------------------------------------------

# The params every /api/notify validation case shares. Only the fields under
# test differ between the two functions below.
def _validation_params( **overrides ):
    """
    Build the query params for a response-required /api/notify call.

    Requires:
        - overrides names only keys this endpoint accepts

    Ensures:
        - returns a fresh dict; callers cannot contaminate each other
    """
    params = {
        "message"           : "Test notification",
        "type"              : "task",
        "priority"          : "high",
        "target_user"       : TEST_USER,
        "api_key"           : API_KEY,
        "response_requested": True
    }
    params.update( overrides )
    return params


def _assert_not_the_auth_wall( response ):
    """
    Fail with the RIGHT cause named when a request never reaches validation.

    🔴 WITHOUT THIS, THE TWO DEFECTS HIDE EACH OTHER AGAIN. A 401 and a wrong
    validation message are different failures; asserting only `== 400` reports
    both as "expected 400, got X" and sends the reader at the validation code,
    which is innocent. Row c46ba7c0: this file sends `api_key` as a QUERY PARAM
    and api_key_auth.py:208 reads a Header, so the dependency refuses before
    the handler is entered and the validation at notifications.py:876 is never
    reached.

    Requires:
        - response is a requests.Response from an /api/notify call

    Raises:
        - AssertionError naming the auth defect, NOT the validation, on a 401
    """
    assert response.status_code != 401, (
        f"401 — the request never reached validation. This is the CREDENTIAL "
        f"defect (row c46ba7c0), not a validation defect: the api_key is sent "
        f"as a query param and the door reads an X-API-Key header. Do not go "
        f"looking at notifications.py:876; it was never executed. "
        f"Body: {response.text[:200]}"
    )


def test_a_missing_response_type_is_rejected():
    """
    response_requested=True with NO response_type must be refused.

    Ensures:
        - the request is actually ISSUED (this is the point of the split)
        - a 401 fails naming the credential defect, not the validation
        - status is 400 and the detail names response_type
    """
    print_test_header( "Test 2a: missing response_type -> 400" )

    response = requests.post(
        f"{BASE_URL}/api/notify",
        params=_validation_params(),
        timeout=5
    )

    print( f"Status Code: {response.status_code} | {response.text[:160]}" )

    _assert_not_the_auth_wall( response )
    assert response.status_code == 400, (
        f"expected 400, got {response.status_code}. Body: {response.text[:200]}"
    )
    assert "response_type is required" in response.json()[ "detail" ], (
        f"status was 400 but the detail does not name the missing response_type, "
        f"so this is some other 400 on the same door. Body: {response.text[:200]}"
    )


def test_an_invalid_response_type_is_rejected():
    """
    response_type set to a value the endpoint does not accept must be refused.

    🔴 THIS IS THE CASE THE SUITE WAS NOT SENDING. Before the split it sat
    behind a failing assert in the same function and its POST never left the
    process.

    Ensures:
        - the request is actually ISSUED
        - a 401 fails naming the credential defect, not the validation
        - status is 400 and the detail names the invalid response_type
    """
    print_test_header( "Test 2b: invalid response_type -> 400" )

    response = requests.post(
        f"{BASE_URL}/api/notify",
        params=_validation_params( response_type="invalid_type" ),
        timeout=5
    )

    print( f"Status Code: {response.status_code} | {response.text[:160]}" )

    _assert_not_the_auth_wall( response )
    assert response.status_code == 400, (
        f"expected 400, got {response.status_code}. Body: {response.text[:200]}"
    )
    assert "Invalid response_type" in response.json()[ "detail" ], (
        f"status was 400 but the detail does not name the invalid response_type, "
        f"so this could be the MISSING-response_type 400 — a different condition "
        f"with the same status. Body: {response.text[:200]}"
    )


# ---------------------------------------------------------------------------
# Test 4: the response-submission door, ONE STATUS PER TEST.
#
# 🔴 WHAT WAS HERE BEFORE, AND WHY ONE FUNCTION COULD NOT SEE ITS OWN DEFECTS.
# A single `test_response_submission` sent `notification_id` as a QUERY PARAM:
#
#     requests.post( ".../api/notify/response",
#                    params={"notification_id": "nonexistent-uuid-12345"},
#                    json={"answer": "yes"} )
#
# The handler reads `request_body.get( "notification_id" )` — the BODY. So the
# door never saw an id at all. Driven at sha 98319e12 on live :7999,
# 2026-09-08 ~18:52 EDT, that call returns:
#
#     422  {"detail":"notification_id is required in request body"}
#
# while the test asserted 404 and called itself the not-found case.
#
# ⚠️ AND ITS SECOND CASE PASSED FOR A REASON IT DID NOT NAME. Case 2 dropped
# the query param and asserted 422 for MISSING. But case 1 already produced a
# byte-identical 422 with the same detail — so the two calls were the same
# request twice, and the status code alone cannot tell them apart. An
# assertion satisfiable by more than one path cannot say which one ran.
#
# ⚠️ AND A THIRD DEFECT NOBODY HAD NAMED: the body was `{"answer": "yes"}`.
# The handler wants `response_value`, not `answer`, and rejects a body missing
# it with its own 422. So even with the id routed correctly, that body could
# never have reached the not-found branch. Measured, same session:
#
#     {"notification_id": <well-formed>}                  -> 422 "response_value is required..."
#     {"notification_id": <well-formed>, "response_value": "yes"} -> 404
#
# ⇒ THREE DEFECTS IN ONE FUNCTION, EACH HIDING THE NEXT. Splitting them is not
# tidiness: it is the only arrangement in which a red names its own cause.
#
# 🔴 EVERY ASSERTION BELOW NAMES ITS PATH IN THE DETAIL STRING, NOT JUST THE
# STATUS. Three separate conditions on this door answer 422 — a malformed id,
# a missing id, and a missing response_value. A test asserting only
# `status_code == 422` passes on all three and therefore reports on none of
# them.
# ---------------------------------------------------------------------------

RESPONSE_DOOR = f"{BASE_URL}/api/notify/response"

# A syntactically valid UUID that will not exist in any database.
ABSENT_BUT_WELL_FORMED_ID = "00000000-0000-4000-8000-000000000000"


def test_a_well_formed_but_absent_notification_id_returns_404():
    """
    The NOT-FOUND case — the one the old single test believed it was covering.

    Requires:
        - a live server at BASE_URL
        - ABSENT_BUT_WELL_FORMED_ID parses as a UUID and matches no row

    Ensures:
        - the id travels in the BODY, where the handler reads it
        - status is 404
        - the detail names THAT id, so a 404 arriving for any other reason
          cannot satisfy this assertion
    """
    print_test_header( "Test 4a: well-formed but absent id -> 404" )

    response = requests.post(
        RESPONSE_DOOR,
        json={
            "notification_id" : ABSENT_BUT_WELL_FORMED_ID,
            "response_value"  : "yes"
        },
        timeout=5
    )

    print( f"Status Code: {response.status_code} | {response.text[:160]}" )

    assert response.status_code == 404, (
        f"expected 404, got {response.status_code}. Body: {response.text[:200]}. "
        f"A well-formed id that matches no row is NOT FOUND. If this is 422 the "
        f"id or the response_value is not reaching the handler; if it is 500 the "
        f"parse is failing, which is a different defect."
    )
    # Name the path: a 404 from some other route or cause must not pass here.
    assert ABSENT_BUT_WELL_FORMED_ID in response.text, (
        f"status was 404 but the detail does not name the id we sent. "
        f"Body: {response.text[:200]}"
    )


def test_a_malformed_notification_id_is_a_client_error_not_a_server_error():
    """
    A malformed id is the CLIENT's error. The live server must not call it a 500.

    Requires:
        - a live server at BASE_URL

    Ensures:
        - status is 422, matching this endpoint's own precedent for a bad
          notification_id (it already answers 422 when the id is missing)
        - the detail names notification_id, so the response_value 422 — a
          different condition on the same door with the same status — cannot
          satisfy this assertion

    ⚠️ THIS ONE IS DELIBERATELY POINTED AT THE DEPLOYED SERVER, NOT AT THE
    SOURCE. The 422 landed in `routers/notifications.py` at commit 7580d938
    (2026-09-06 18:32 EDT). :7999 runs with auto-reload OFF, so a saved file
    is not a served file: measured 2026-09-08 ~18:52 EDT the running server
    still answered 500 for this case while the assembled app from the same
    sha answered 422. A red here means the server is stale, and that is this
    test earning its place — the unit guard
    `src/tests/unit/test_notify_response_malformed_id_is_a_client_error.py`
    covers the assembled app and structurally cannot see a stale deployment.
    """
    print_test_header( "Test 4b: malformed id -> 422, never 500" )

    response = requests.post(
        RESPONSE_DOOR,
        json={
            "notification_id" : "not-a-uuid",
            "response_value"  : "yes"
        },
        timeout=5
    )

    print( f"Status Code: {response.status_code} | {response.text[:160]}" )

    assert response.status_code != 500, (
        f"got 500. A malformed notification_id is the CLIENT's error; 500 tells "
        f"the caller THE SERVER BROKE, so a client retrying on 5xx retries a "
        f"request that can never succeed. Body: {response.text[:200]}. "
        f"If the source already carries the 422 parse guard, this server is "
        f"running stale code — :7999 does not auto-reload."
    )
    assert response.status_code == 422, (
        f"expected 422, got {response.status_code}. Body: {response.text[:200]}"
    )
    # 🔴 THIS ASSERTION IS THE ONE THAT DISCRIMINATES, AND THE FIRST CUT OF THIS
    # TEST DID NOT HAVE IT. That cut asserted only that the detail contained
    # "notification_id" — and the MISSING-id 422 says "notification_id is
    # required in request body", which contains it too. Measured 2026-09-08
    # ~19:05 EDT: with the id put back in the query param (the original defect),
    # this test stayed GREEN while its sibling reddened. Two 422 paths, one
    # assertion, and the wrong one satisfied it.
    #
    # The malformed detail is the landed fix's own wording at
    # routers/notifications.py:640 — `f"notification_id is not a valid UUID:
    # {notification_id!r}"` — so the id we SENT appears in it. The missing-id
    # 422 cannot name a value it never received.
    assert "not-a-uuid" in response.text, (
        f"status was 422 but the detail does not name the malformed value we "
        f"sent, so this is probably the MISSING-notification_id 422 — a "
        f"different condition with the same status. Body: {response.text[:200]}"
    )


def test_a_missing_notification_id_returns_422():
    """
    No id in the body at all.

    Ensures:
        - status is 422
        - the detail names notification_id — NOT merely 'a 422 came back'.
          This is the assertion the old test made, and it passed while the
          request it was paired with produced the identical response.
    """
    print_test_header( "Test 4c: missing notification_id -> 422" )

    response = requests.post(
        RESPONSE_DOOR,
        json={"response_value": "yes"},
        timeout=5
    )

    print( f"Status Code: {response.status_code} | {response.text[:160]}" )

    assert response.status_code == 422, (
        f"expected 422, got {response.status_code}. Body: {response.text[:200]}"
    )
    assert "notification_id" in response.text, (
        f"status was 422 but the detail does not name notification_id. "
        f"Body: {response.text[:200]}"
    )


def test_a_missing_response_value_returns_422():
    """
    The id is fine; `response_value` is absent.

    This case had no guard at all, and it is why the old test could not have
    reached 404 even with the id routed correctly: it sent `{"answer": "yes"}`,
    and the handler wants `response_value`.

    Ensures:
        - status is 422
        - the detail names response_value, distinguishing it from the two
          notification_id 422s above
    """
    print_test_header( "Test 4d: missing response_value -> 422" )

    response = requests.post(
        RESPONSE_DOOR,
        json={"notification_id": ABSENT_BUT_WELL_FORMED_ID},
        timeout=5
    )

    print( f"Status Code: {response.status_code} | {response.text[:160]}" )

    assert response.status_code == 422, (
        f"expected 422, got {response.status_code}. Body: {response.text[:200]}"
    )
    assert "response_value" in response.text, (
        f"status was 422 but the detail does not name response_value, so this is "
        f"probably the notification_id 422 instead. Body: {response.text[:200]}"
    )


def _script_mode( *cases ):
    """
    Script-mode adapter for `run_all_tests()` ONLY.

    Every test in this file is a plain pytest test: it asserts and returns None,
    so a failure PROPAGATES. `run_all_tests()` needs a bool per row, so the catch
    lives HERE, at the call site, rather than inside the tests.

    🔴 THE CATCH MUST NOT MOVE BACK INTO THE TESTS. Measured 2026-09-08 with
    pytest 8.4.2: a test body of `try: assert False ... except Exception: return
    False` PASSES — pytest emits only a PytestReturnNotNoneWarning, while a
    plain failing assert in the same file reddens. That shape made every
    assertion in this file unfalsifiable under pytest while still printing
    '✗ Test failed' in script mode.

    Requires:
        - each case is a zero-argument callable that asserts

    Ensures:
        - returns True only if every case completes without raising
        - returns False and prints the failure otherwise
    """
    ok = True
    for case in cases:
        try:
            case()
            print( f"✓ {case.__name__}" )
        except Exception as e:
            print( f"✗ {case.__name__}: {e}" )
            ok = False

    return ok


def test_api_key_validation():
    """
    Test 5: API key validation.

    Tests that invalid API keys are rejected.
    """
    print_test_header( "Test 5: API Key Validation" )

    response = requests.post(
        f"{BASE_URL}/api/notify",
        params={
            "message"     : "Test notification",
            "type"        : "task",
            "priority"    : "medium",
            "target_user" : TEST_USER,
            "api_key"     : "wrong_key_12345"
        },
        timeout=5
    )

    print( f"Status Code: {response.status_code}" )
    data = response.json()
    print( f"Response: {json.dumps(data, indent=2)}" )

    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    assert "Invalid API key" in data["detail"], "Wrong error message"

    print( "✓ Invalid API key rejected" )



def run_all_tests():
    """
    Run all smoke tests and report results.

    Ensures:
        - Returns 0 if all tests pass
        - Returns 1 if any test fails
    """
    cu.print_banner( "SSE Notifications Smoke Test Suite", prepend_nl=True )

    print( f"\nTarget Server: {BASE_URL}" )
    print( f"Test User: {TEST_USER}" )
    print( f"\nNOTE: Server must be running on {BASE_URL}" )
    print( "      Start with: src/scripts/run-fastapi-lupin.sh\n" )

    # Check if server is running
    try:
        response = requests.get( f"{BASE_URL}/health", timeout=2 )
        print( f"✓ Server is running (health check: {response.status_code})\n" )
    except Exception as e:
        print( f"✗ Server not responding: {e}" )
        print( "\nPlease start the server with: src/scripts/run-fastapi-lupin.sh\n" )
        return 1

    # Run tests
    results = []

    # 🔴 EVERY ROW GOES THROUGH `_script_mode`. Calling a test bare here would
    # require it to return a bool, which is the shape this file was repaired to
    # remove — see `_script_mode`'s docstring.
    results.append( ("Response-Required Validation",   _script_mode(
        test_a_missing_response_type_is_rejected,
        test_an_invalid_response_type_is_rejected,
    )) )
    results.append( ("Response Submission Endpoint",   _script_mode(
        test_a_well_formed_but_absent_notification_id_returns_404,
        test_a_malformed_notification_id_is_a_client_error_not_a_server_error,
        test_a_missing_notification_id_returns_422,
        test_a_missing_response_value_returns_422,
    )) )
    results.append( ("API Key Validation",             _script_mode( test_api_key_validation )) )

    # Summary
    print( f"\n{'=' * 60}" )
    print( "  Test Results Summary" )
    print( f"{'=' * 60}\n" )

    passed = sum( 1 for _, result in results if result )
    failed = len( results ) - passed

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print( f"{status:10} | {test_name}" )

    print( f"\n{'=' * 60}" )
    print( f"Total: {passed} passed, {failed} failed out of {len(results)} tests" )
    print( f"{'=' * 60}\n" )

    if failed > 0:
        print( "✗ Some tests failed" )
        return 1
    else:
        print( "✓ All tests passed successfully" )
        return 0


if __name__ == "__main__":
    sys.exit( run_all_tests() )
