#!/usr/bin/env python3
"""
Smoke test for Calculator agent via live pipeline (Step 24 of testing ladder).

Verifies the full end-to-end pipeline:
  TodoFifoQueue -> mode bypass -> CalculatorAgent -> Phi-4 intent extraction
  -> dispatch -> TTS response

Tests 6 queries covering: unit conversion, price comparison, mortgage calculation.

Usage:
    # Run all 6 queries (default)
    python src/tests/smoke/test_calculator_live_pipeline.py

    # Run only query 0 (CONVERT_KM)
    python src/tests/smoke/test_calculator_live_pipeline.py --queries 0

    # Run queries 0, 2, 4
    python src/tests/smoke/test_calculator_live_pipeline.py -q 0,2,4

Query index reference:
    0: CONVERT_KM      — How many miles is 10 kilometers?
    1: CONVERT_TEMP    — Convert 72 Fahrenheit to Celsius
    2: CONVERT_WEIGHT  — 500 grams in pounds
    3: COMPARE_PRICE   — Compare 12 oz at $3.49 vs 24 oz at $5.99
    4: MORTGAGE        — Monthly payment on $300k mortgage at 6.5% for 30 years
    5: CONVERT_ML      — What's 500 ml in cups?

Requires:
    - Server running on localhost:7999
    - Phi-4 LLM server running for intent extraction
    - Environment variables:
        LUPIN_TEST_EMAIL / LUPIN_TEST_PASSWORD

Created: 2026-02-10 (Session 172)
"""

import argparse
import os
import sys
import time
import traceback

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import requests

try:
    import cosa.utils.util as cu
except ImportError:
    cu = None


BASE_URL         = "http://localhost:7999"
MAX_POLL_SECONDS = 120
POLL_INTERVAL    = 2
REQUEST_TIMEOUT  = 60


# ═══════════════════════════════════════════════════════════════════════════════
# Test Matrix
# ═══════════════════════════════════════════════════════════════════════════════

CALCULATOR_QUERIES = [
    {
        "id"               : "CONVERT_KM",
        "query"            : "How many miles is 10 kilometers?",
        "expected_op"      : "convert",
        "expected_keywords" : [ "6.21", "6.2" ],
    },
    {
        "id"               : "CONVERT_TEMP",
        "query"            : "Convert 72 Fahrenheit to Celsius",
        "expected_op"      : "convert",
        "expected_keywords" : [ "22.2", "22.22" ],
    },
    {
        "id"               : "CONVERT_WEIGHT",
        "query"            : "500 grams in pounds",
        "expected_op"      : "convert",
        "expected_keywords" : [ "1.1", "1.10" ],
    },
    {
        "id"               : "COMPARE_PRICE",
        "query"            : "Compare 12 oz at $3.49 vs 24 oz at $5.99",
        "expected_op"      : "compare_prices",
        "expected_keywords" : [ "cheaper", "better", "value", "per" ],
    },
    {
        "id"               : "MORTGAGE",
        "query"            : "Monthly payment on $300k mortgage at 6.5% for 30 years",
        "expected_op"      : "mortgage",
        "expected_keywords" : [ "1,896", "1896", "1,897", "1897" ],
    },
    {
        "id"               : "CONVERT_ML",
        "query"            : "What's 500 ml in cups?",
        "expected_op"      : "convert",
        "expected_keywords" : [ "2.1", "2.11" ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

def _get_credentials():
    """
    Get test credentials from environment.

    Requires:
        - LUPIN_TEST_EMAIL and LUPIN_TEST_PASSWORD are set

    Ensures:
        - Returns (email, password) tuple
        - Returns (None, None) if no credentials found
    """
    email    = os.environ.get( "LUPIN_TEST_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_PASSWORD" )

    if email and password:
        return email, password

    return None, None


def _login( email, password ):
    """
    Authenticate and return (token, headers) tuple.

    Requires:
        - email and password are non-empty strings
        - Server running on BASE_URL

    Ensures:
        - Returns (token_str, headers_dict) on success
        - Returns (None, None) on failure with remediation instructions
    """
    login_resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password },
        timeout=30
    )

    if login_resp.status_code != 200:
        print( f"  Login failed: {login_resp.status_code}" )
        print( f"  Response: {login_resp.text[ :200 ]}" )
        print()
        print( "  Possible fixes:" )
        print( "  1. Account may not exist. Register it:" )
        print( f'     curl -X POST "{BASE_URL}/auth/register" \\' )
        print( f'       -H "Content-Type: application/json" \\' )
        print( f'       -d \'{{"email": "{email}", "password": "<your-password>"}}\'' )
        print( "  2. Password may be wrong. Check your env vars:" )
        print( "     LUPIN_TEST_EMAIL / LUPIN_TEST_PASSWORD" )
        return None, None

    token   = login_resp.json()[ "tokens" ][ "access_token" ]
    headers = { "Authorization": f"Bearer {token}" }
    return token, headers


def _get_websocket_session_id( headers ):
    """
    Get a valid WebSocket session ID for API calls.

    Requires:
        - headers contains valid auth token

    Ensures:
        - Returns session_id string on success
        - Returns None on failure
    """
    resp = requests.get(
        f"{BASE_URL}/api/debug/websocket-state",
        headers=headers,
        timeout=10
    )

    if resp.status_code != 200:
        print( f"  WebSocket state endpoint failed: {resp.status_code}" )
        return None

    data     = resp.json()
    sessions = data.get( "sessions", {} )

    if sessions:
        # Use the first active session
        session_id = list( sessions.keys() )[ 0 ]
        return session_id

    # No active sessions — use a placeholder
    return "smoke-test-session"


def _set_calculator_mode( headers ):
    """
    Set user mode to calculator for direct routing.

    Requires:
        - headers contains valid auth token

    Ensures:
        - Returns True if mode set successfully
        - Returns False on failure
    """
    resp = requests.post(
        f"{BASE_URL}/api/mode/current",
        json={ "mode": "calculator" },
        headers=headers,
        timeout=10
    )

    if resp.status_code != 200:
        print( f"  Set mode failed: {resp.status_code} - {resp.text[ :200 ]}" )
        return False

    data = resp.json()
    print( f"  Mode set to: {data.get( 'display_name', 'unknown' )} (was: {data.get( 'previous_mode', 'system' )})" )
    return True


def _clear_mode( headers ):
    """
    Clear user mode back to system.

    Requires:
        - headers contains valid auth token

    Ensures:
        - Mode is cleared regardless of success/failure
    """
    try:
        requests.post(
            f"{BASE_URL}/api/mode/current",
            json={ "mode": None },
            headers=headers,
            timeout=10
        )
    except Exception:
        pass  # Best effort


def _submit_and_wait( query_info, headers, ws_id, timeout=None ):
    """
    Submit a question and poll the done queue for completion.

    Requires:
        - query_info is a dict from CALCULATOR_QUERIES
        - headers contains valid auth token
        - ws_id is a valid session ID

    Ensures:
        - Returns (job_metadata_dict, error_msg) on completion
        - Returns (None, error_msg) on failure or timeout
    """
    if timeout is None:
        timeout = MAX_POLL_SECONDS

    question = query_info[ "query" ]

    # Submit
    try:
        resp = requests.post(
            f"{BASE_URL}/api/push",
            json={ "question": question, "websocket_id": ws_id },
            headers={ **headers, "X-Session-ID": ws_id },
            timeout=REQUEST_TIMEOUT
        )
    except requests.exceptions.Timeout:
        return None, f"Submit timed out after {REQUEST_TIMEOUT}s"
    except Exception as e:
        return None, f"Submit error: {e}"

    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: {resp.text[ :200 ]}"

    push_data = resp.json()
    job_id    = push_data.get( "job_id" )

    if not job_id:
        return None, f"No job_id in push response: {push_data}"

    print( f"    Submitted, job_id={job_id}, polling..." )

    # Poll done queue
    elapsed = 0
    while elapsed < timeout:
        try:
            done_resp = requests.get(
                f"{BASE_URL}/api/get-queue/done",
                headers=headers,
                timeout=30
            )

            if done_resp.status_code == 200:
                done_data = done_resp.json()
                jobs      = done_data.get( "done_jobs_metadata", [] )

                for job in jobs:
                    if job.get( "job_id" ) == job_id:
                        return job, None

        except Exception as e:
            print( f"    Poll error: {e}" )

        time.sleep( POLL_INTERVAL )
        elapsed += POLL_INTERVAL

    return None, f"Timeout after {timeout}s waiting for job_id={job_id}"


def _check_answer( answer_text, expected_keywords ):
    """
    Check if the answer contains any of the expected keywords.

    Requires:
        - answer_text is a string (may be None)
        - expected_keywords is a non-empty list of strings

    Ensures:
        - Returns (True, matched_keyword) if any keyword found
        - Returns (False, None) if no keyword found
    """
    if not answer_text:
        return False, None

    answer_lower = answer_text.lower()
    for keyword in expected_keywords:
        if keyword.lower() in answer_lower:
            return True, keyword

    return False, None


def _print_results_table( results ):
    """
    Print a formatted summary table of all query results.

    Requires:
        - results is a list of dicts with keys: id, status, query, answer_preview, details

    Ensures:
        - Prints tabular summary to console
    """
    print( "\n" + "=" * 90 )
    print( f"  {'#':<4} {'Test ID':<16} {'Status':<8} {'Answer Preview':<40} {'Details'}" )
    print( "-" * 90 )

    for i, r in enumerate( results, 1 ):
        status_icon = "PASS" if r[ "status" ] == "pass" else "FAIL"
        icon        = "+" if r[ "status" ] == "pass" else "-"
        preview     = r.get( "answer_preview", "" )[ :38 ]
        print( f"  {icon} {i:<3} {r[ 'id' ]:<16} {status_icon:<8} {preview:<40} {r[ 'details' ]}" )

    print( "=" * 90 )

    passed = sum( 1 for r in results if r[ "status" ] == "pass" )
    failed = sum( 1 for r in results if r[ "status" ] == "fail" )

    print( f"\n  Total: {passed} passed, {failed} failed out of {len( results )}" )
    print( f"  Overall: {'PASS' if failed == 0 else 'FAIL'}" )


# ═══════════════════════════════════════════════════════════════════════════════
# Main Test
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( query_indices=None ):
    """
    Smoke test for Calculator agent via live pipeline.

    Requires:
        - Server running on port 7999
        - Phi-4 LLM server running for intent extraction
        - Test credentials available via environment variables
        - query_indices is None (run all) or a list of valid ints (0-5)

    Ensures:
        - Sets calculator mode
        - Submits selected queries (all 6 by default)
        - Polls for completion via job_id
        - Validates answers contain expected keywords
        - Resets mode to system on exit
        - Returns True if all selected queries pass
    """
    if query_indices is not None:
        queries = [ CALCULATOR_QUERIES[ i ] for i in query_indices if i < len( CALCULATOR_QUERIES ) ]
        label   = f"Calculator Live Pipeline Smoke Test ({len( queries )} of {len( CALCULATOR_QUERIES )} queries)"
    else:
        queries = CALCULATOR_QUERIES
        label   = f"Calculator Live Pipeline Smoke Test ({len( queries )}-Query Matrix)"

    banner = label
    if cu:
        cu.print_banner( banner, prepend_nl=True )
    else:
        print( f"\n{'=' * 60}" )
        print( f"  {banner}" )
        print( f"{'=' * 60}" )

    # Get credentials
    email, password = _get_credentials()
    if not email or not password:
        print( "Missing environment variables. Set:" )
        print( "  export LUPIN_TEST_EMAIL='your@email.com'" )
        print( "  export LUPIN_TEST_PASSWORD='<your-password>'" )
        return False

    try:
        # ═══════════════════════════════════════════════════════════════════
        # Step 1: Login (with auto-registration for mock test account)
        # ═══════════════════════════════════════════════════════════════════
        print( f"\nStep 1: Logging in as {email}..." )

        token, headers = _login( email, password )

        if not token:
            print( "Login failed." )
            return False

        print( f"  Login successful, token: {token[ :30 ]}..." )

        # ═══════════════════════════════════════════════════════════════════
        # Step 2: Get WebSocket session ID
        # ═══════════════════════════════════════════════════════════════════
        print( "\nStep 2: Getting WebSocket session ID..." )
        ws_id = _get_websocket_session_id( headers )
        print( f"  Using session ID: {ws_id}" )

        # ═══════════════════════════════════════════════════════════════════
        # Step 3: Set calculator mode
        # ═══════════════════════════════════════════════════════════════════
        print( "\nStep 3: Setting calculator mode..." )
        if not _set_calculator_mode( headers ):
            print( "Failed to set calculator mode." )
            return False

        # ═══════════════════════════════════════════════════════════════════
        # Step 4: Run 6-query test matrix
        # ═══════════════════════════════════════════════════════════════════
        print( "\n" + "=" * 70 )
        print( f"  CALCULATOR QUERY MATRIX ({len( queries )} queries)" )
        print( "  Each query is submitted via /api/push and polled for completion." )
        print( f"  Timeout: {MAX_POLL_SECONDS}s per query." )
        print( "=" * 70 )

        results = []

        for i, query_info in enumerate( queries, 1 ):
            print( f"\n{'─' * 70}" )
            print( f"  Query {i}/{len( queries )}: {query_info[ 'id' ]}" )
            print( f"  Question: \"{query_info[ 'query' ]}\"" )
            print( f"  Expected op: {query_info[ 'expected_op' ]}" )
            print( f"  Expected keywords: {query_info[ 'expected_keywords' ]}" )
            print( f"{'─' * 70}" )

            result = {
                "id"             : query_info[ "id" ],
                "status"         : "fail",
                "query"          : query_info[ "query" ],
                "answer_preview" : "",
                "details"        : "",
            }

            job_data, error = _submit_and_wait( query_info, headers, ws_id )

            if error:
                result[ "details" ] = error
                print( f"    FAIL: {error}" )
            elif job_data:
                answer = job_data.get( "response_text", "" ) or ""
                result[ "answer_preview" ] = answer[ :80 ]

                matched, keyword = _check_answer( answer, query_info[ "expected_keywords" ] )

                if matched:
                    result[ "status" ]  = "pass"
                    result[ "details" ] = f"matched '{keyword}'"
                    print( f"    PASS: Answer contains '{keyword}'" )
                    print( f"    Answer: {answer[ :120 ]}" )
                else:
                    result[ "details" ] = f"no keyword match in answer"
                    print( f"    FAIL: Expected one of {query_info[ 'expected_keywords' ]}" )
                    print( f"    Got: {answer[ :200 ]}" )
            else:
                result[ "details" ] = "No job data returned"
                print( f"    FAIL: No job data" )

            results.append( result )

        # ═══════════════════════════════════════════════════════════════════
        # Step 5: Reset mode
        # ═══════════════════════════════════════════════════════════════════
        print( f"\n{'─' * 70}" )
        print( "Step 5: Clearing calculator mode..." )
        _clear_mode( headers )
        print( "  Mode cleared." )

        # ═══════════════════════════════════════════════════════════════════
        # Step 6: Results summary
        # ═══════════════════════════════════════════════════════════════════
        _print_results_table( results )

        passed = sum( 1 for r in results if r[ "status" ] == "pass" )
        failed = sum( 1 for r in results if r[ "status" ] == "fail" )

        all_passed = failed == 0

        print( f"\n{'=' * 70}" )
        if all_passed:
            print( f"ALL CALCULATOR SMOKE TESTS PASSED ({passed}/{len( queries )})!" )
        else:
            print( f"CALCULATOR SMOKE TESTS: {passed} passed, {failed} failed" )
        print( "=" * 70 )

        return all_passed

    except requests.exceptions.ConnectionError:
        print( f"\nConnection failed - is the server running on {BASE_URL}?" )
        return False
    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        traceback.print_exc()
        return False
    finally:
        # Always try to clear mode on exit
        try:
            if "headers" in dir():
                _clear_mode( headers )
        except Exception:
            pass


def test_calculator_live_pipeline():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    parser = argparse.ArgumentParser( description="Calculator live pipeline smoke test" )
    parser.add_argument(
        "--queries", "-q",
        type=str,
        default=None,
        help="Comma-separated query indices to run (e.g., '0,1,3'). Default: all."
    )
    args = parser.parse_args()

    indices = None
    if args.queries:
        indices = [ int( x.strip() ) for x in args.queries.split( "," ) ]

    try:
        success = quick_smoke_test( query_indices=indices )
        sys.exit( 0 if success else 1 )
    except Exception as e:
        traceback.print_exc()
        sys.exit( 1 )
