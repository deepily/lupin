#!/usr/bin/env python3
"""
Smoke test for CRUD agent via live pipeline.

Verifies the full end-to-end pipeline:
  TodoFifoQueue -> mode bypass -> CrudForDataFramesAgent -> Phi-4 intent extraction
  -> dispatch -> storage -> voice confirmation -> TTS response

Tests 8 scenarios covering: add, query, dedup guard, delete with confirmation,
calendar schema, and LORA routing.

Usage:
    # Direct-mode only — scenarios 0-5, no LORA needed (DEFAULT)
    python src/tests/smoke/test_crud_live_pipeline.py --mode direct

    # LORA routing tests — scenarios 6-7, requires trained adapter
    python src/tests/smoke/test_crud_live_pipeline.py --mode lora

    # All scenarios — direct + LORA (requires trained adapter)
    python src/tests/smoke/test_crud_live_pipeline.py --mode all

    # With notification proxy for auto-confirmed delete:
    # Terminal 2: python -m cosa.agents.notification_proxy --profile crud --debug
    # Terminal 3: python src/tests/smoke/test_crud_live_pipeline.py --mode direct

Requires:
    - Server running on localhost:7999
    - Phi-4 LLM server running for intent extraction
    - Environment variables:
        LUPIN_TEST_EMAIL / LUPIN_TEST_PASSWORD

Created: 2026-02-11 (Session 189)
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

# Delete confirmation timeout — longer to allow proxy or manual response
DELETE_POLL_SECONDS = 180


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Matrix
# ═══════════════════════════════════════════════════════════════════════════════

CRUD_SCENARIOS = [
    # --- Direct-mode scenarios (0-5) ---
    {
        "id"                : "ADD_TODO",
        "query"             : "add buy milk to my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "milk" ],
        "expected_status"   : [ "added", "duplicate" ],
    },
    {
        "id"                : "ADD_TODO_2",
        "query"             : "add buy bread to my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "bread" ],
        "expected_status"   : [ "added" ],
    },
    {
        "id"                : "QUERY_TODO",
        "query"             : "what's on my grocery list?",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "found", "milk", "bread", "item" ],
        "expected_status"   : [ "ok" ],
    },
    {
        "id"                : "ADD_DUPLICATE",
        "query"             : "add buy milk to my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "already exists", "duplicate" ],
        "expected_status"   : [ "duplicate" ],
    },
    {
        "id"                : "DELETE_TODO",
        "query"             : "delete buy bread from my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : True,
        "expected_keywords" : [ "done", "deleted", "removed", "cancelled", "cancel" ],
        "expected_status"   : [ "deleted", "cancelled" ],
    },
    {
        "id"                : "ADD_CALENDAR",
        "query"             : "add dentist appointment on March 15 at 2pm",
        "mode"              : "calendar",
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "dentist" ],
        "expected_status"   : [ "added" ],
    },
    # --- LORA routing scenarios (6-7) ---
    {
        "id"                : "LORA_ADD_TODO",
        "query"             : "put eggs on my shopping list",
        "mode"              : None,
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "eggs" ],
        "expected_status"   : [ "added" ],
    },
    {
        "id"                : "LORA_QUERY_TODO",
        "query"             : "what do I need to buy?",
        "mode"              : None,
        "needs_confirm"     : False,
        "expected_keywords" : [ "found", "item", "milk", "eggs" ],
        "expected_status"   : [ "ok" ],
    },
]

# Mode -> scenario index mapping (internal, not user-facing)
MODE_SCENARIOS = {
    "direct" : [ 0, 1, 2, 3, 4, 5 ],
    "lora"   : [ 6, 7 ],
    "all"    : [ 0, 1, 2, 3, 4, 5, 6, 7 ],
}


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
        session_id = list( sessions.keys() )[ 0 ]
        return session_id

    return "smoke-test-session"


def _set_mode( headers, mode_name ):
    """
    Set user mode for direct routing.

    Requires:
        - headers contains valid auth token
        - mode_name is a valid mode string

    Ensures:
        - Returns True if mode set successfully
        - Returns False on failure
    """
    resp = requests.post(
        f"{BASE_URL}/api/mode/current",
        json={ "mode": mode_name },
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


def _submit_and_wait( scenario, headers, ws_id, timeout=None ):
    """
    Submit a question and poll the done queue for completion.

    Requires:
        - scenario is a dict from CRUD_SCENARIOS
        - headers contains valid auth token
        - ws_id is a valid session ID

    Ensures:
        - Returns (job_metadata_dict, error_msg) on completion
        - Returns (None, error_msg) on failure or timeout
    """
    if timeout is None:
        timeout = DELETE_POLL_SECONDS if scenario.get( "needs_confirm" ) else MAX_POLL_SECONDS

    question = scenario[ "query" ]

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

    confirm_note = " (confirmation required)" if scenario.get( "needs_confirm" ) else ""
    print( f"    Submitted, job_id={job_id}, polling (timeout={timeout}s){confirm_note}..." )

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
    Print a formatted summary table of all scenario results.

    Requires:
        - results is a list of dicts with keys: id, status, query, answer_preview, details

    Ensures:
        - Prints tabular summary to console
    """
    print( "\n" + "=" * 90 )
    print( f"  {'#':<4} {'Test ID':<18} {'Status':<8} {'Answer Preview':<36} {'Details'}" )
    print( "-" * 90 )

    for i, r in enumerate( results, 1 ):
        status_icon = "PASS" if r[ "status" ] == "pass" else "FAIL"
        icon        = "+" if r[ "status" ] == "pass" else "-"
        preview     = r.get( "answer_preview", "" )[ :34 ]
        print( f"  {icon} {i:<3} {r[ 'id' ]:<18} {status_icon:<8} {preview:<36} {r[ 'details' ]}" )

    print( "=" * 90 )

    passed = sum( 1 for r in results if r[ "status" ] == "pass" )
    failed = sum( 1 for r in results if r[ "status" ] == "fail" )

    print( f"\n  Total: {passed} passed, {failed} failed out of {len( results )}" )
    print( f"  Overall: {'PASS' if failed == 0 else 'FAIL'}" )


# ═══════════════════════════════════════════════════════════════════════════════
# Main Test
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( mode="direct" ):
    """
    Smoke test for CRUD agent via live pipeline.

    Requires:
        - Server running on port 7999
        - Phi-4 LLM server running for intent extraction
        - Test credentials available via environment variables
        - mode is one of: "direct", "lora", "all"

    Ensures:
        - Sets appropriate mode per scenario
        - Submits selected scenarios
        - Polls for completion via job_id
        - Validates answers contain expected keywords
        - Resets mode to system on exit
        - Returns True if all selected scenarios pass
    """
    scenario_indices = MODE_SCENARIOS.get( mode, MODE_SCENARIOS[ "direct" ] )
    scenarios        = [ CRUD_SCENARIOS[ i ] for i in scenario_indices ]
    label            = f"CRUD Live Pipeline Smoke Test — {mode} mode ({len( scenarios )} scenarios)"

    if cu:
        cu.print_banner( label, prepend_nl=True )
    else:
        print( f"\n{'=' * 70}" )
        print( f"  {label}" )
        print( f"{'=' * 70}" )

    # Get credentials
    email, password = _get_credentials()
    if not email or not password:
        print( "Missing environment variables. Set:" )
        print( "  export LUPIN_TEST_EMAIL='your@email.com'" )
        print( "  export LUPIN_TEST_PASSWORD='<your-password>'" )
        return False

    try:
        # ═══════════════════════════════════════════════════════════════════
        # Step 1: Login
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
        # Step 3: Run scenario matrix
        # ═══════════════════════════════════════════════════════════════════
        print( "\n" + "=" * 70 )
        print( f"  CRUD SCENARIO MATRIX ({len( scenarios )} scenarios, mode={mode})" )
        print( f"  Each scenario is submitted via /api/push and polled for completion." )
        print( f"  Standard timeout: {MAX_POLL_SECONDS}s, delete confirm: {DELETE_POLL_SECONDS}s" )
        print( "=" * 70 )

        results      = []
        current_mode = None

        for i, scenario in enumerate( scenarios, 1 ):
            print( f"\n{'─' * 70}" )
            print( f"  Scenario {i}/{len( scenarios )}: {scenario[ 'id' ]}" )
            print( f"  Query: \"{scenario[ 'query' ]}\"" )
            print( f"  Mode: {scenario[ 'mode' ] or 'system (LORA routing)'}" )
            print( f"  Confirm: {'Yes' if scenario[ 'needs_confirm' ] else 'No'}" )
            print( f"  Expected keywords: {scenario[ 'expected_keywords' ]}" )
            print( f"{'─' * 70}" )

            # Switch mode if needed
            target_mode = scenario[ "mode" ]
            if target_mode != current_mode:
                if target_mode:
                    print( f"  Switching mode to '{target_mode}'..." )
                    if not _set_mode( headers, target_mode ):
                        print( f"  WARNING: Failed to set mode '{target_mode}', continuing anyway." )
                else:
                    print( "  Clearing mode for LORA routing..." )
                    _clear_mode( headers )
                current_mode = target_mode

            result = {
                "id"             : scenario[ "id" ],
                "status"         : "fail",
                "query"          : scenario[ "query" ],
                "answer_preview" : "",
                "details"        : "",
            }

            job_data, error = _submit_and_wait( scenario, headers, ws_id )

            if error:
                result[ "details" ] = error
                print( f"    FAIL: {error}" )
            elif job_data:
                answer = job_data.get( "response_text", "" ) or ""
                result[ "answer_preview" ] = answer[ :80 ]

                matched, keyword = _check_answer( answer, scenario[ "expected_keywords" ] )

                if matched:
                    result[ "status" ]  = "pass"
                    result[ "details" ] = f"matched '{keyword}'"
                    print( f"    PASS: Answer contains '{keyword}'" )
                    print( f"    Answer: {answer[ :120 ]}" )
                else:
                    result[ "details" ] = "no keyword match in answer"
                    print( f"    FAIL: Expected one of {scenario[ 'expected_keywords' ]}" )
                    print( f"    Got: {answer[ :200 ]}" )
            else:
                result[ "details" ] = "No job data returned"
                print( f"    FAIL: No job data" )

            results.append( result )

        # ═══════════════════════════════════════════════════════════════════
        # Step 4: Reset mode
        # ═══════════════════════════════════════════════════════════════════
        print( f"\n{'─' * 70}" )
        print( "Step 4: Clearing mode..." )
        _clear_mode( headers )
        print( "  Mode cleared." )

        # ═══════════════════════════════════════════════════════════════════
        # Step 5: Results summary
        # ═══════════════════════════════════════════════════════════════════
        _print_results_table( results )

        passed = sum( 1 for r in results if r[ "status" ] == "pass" )
        failed = sum( 1 for r in results if r[ "status" ] == "fail" )

        all_passed = failed == 0

        print( f"\n{'=' * 70}" )
        if all_passed:
            print( f"ALL CRUD SMOKE TESTS PASSED ({passed}/{len( scenarios )})!" )
        else:
            print( f"CRUD SMOKE TESTS: {passed} passed, {failed} failed" )
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


def test_crud_live_pipeline():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    parser = argparse.ArgumentParser( description="CRUD live pipeline smoke test" )
    parser.add_argument(
        "--mode", "-m",
        choices=[ "direct", "lora", "all" ],
        default="direct",
        help="Test mode: 'direct' (no LORA, default), 'lora' (LORA routing only), 'all' (everything)"
    )
    args = parser.parse_args()

    try:
        success = quick_smoke_test( mode=args.mode )
        sys.exit( 0 if success else 1 )
    except Exception as e:
        traceback.print_exc()
        sys.exit( 1 )
