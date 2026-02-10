#!/usr/bin/env python3
"""
Smoke test for Runtime Argument Expeditor via mock job endpoint.

Verifies that:
1. Login and auth token retrieval works
2. Mock job health endpoint is alive
3. Standard mock job (no voice_command) baseline works
4.1-4.9 Nine expeditor scenarios covering all 3 agents, audience params,
        missing args, confirmation loop, and cancellation (INTERACTIVE)

Tests 4.x require LUPIN_INTERACTIVE_TESTS=true because they:
- Call LLM for gap analysis (real inference cost)
- Call notify_user_sync() for missing args + confirmation (blocks for user response)

Requires:
- Server running on localhost:7999
- Environment variables: LUPIN_TEST_EMAIL, LUPIN_TEST_PASSWORD
- For tests 4.x: LUPIN_INTERACTIVE_TESTS=true

Created: 2026-02-05
Updated: 2026-02-07 — 9-scenario matrix with confirmation loop coverage
"""

import os
import sys
import time
import traceback

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import requests
import cosa.utils.util as cu


BASE_URL         = "http://localhost:7999"
MAX_POLL_SECONDS = 120
POLL_INTERVAL    = 2
REQUEST_TIMEOUT  = 600


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Matrix
# ═══════════════════════════════════════════════════════════════════════════════

EXPEDITOR_SCENARIOS = [
    {
        "id"            : "DR_HAPPY",
        "voice_command" : "do deep research on quantum computing",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command. You'll be asked to CONFIRM the summary — say 'yes'.",
    },
    {
        "id"            : "DR_MISSING",
        "voice_command" : "do some deep research",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "You'll be prompted for the topic. Provide one (e.g. 'climate change'), then CONFIRM — say 'yes'.",
    },
    {
        "id"            : "DR_BUDGET",
        "voice_command" : "do deep research on climate change with a budget of 5 dollars",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command (query + budget). CONFIRM the summary — say 'yes'.",
    },
    {
        "id"            : "DR_AUDIENCE",
        "voice_command" : "do deep research on machine learning for a beginner audience",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "Audience should auto-extract. Verify summary includes audience, then say 'yes'.",
    },
    {
        "id"            : "PG_MISSING",
        "voice_command" : "make me a podcast",
        "agent"         : "podcast",
        "key_arg"       : "research",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "You'll be prompted for a research document. Describe one, then CONFIRM — say 'yes'.",
    },
    {
        "id"            : "PG_AUDIENCE",
        "voice_command" : "make me a podcast for an expert audience",
        "agent"         : "podcast",
        "key_arg"       : "research",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "Audience should auto-extract. You'll be prompted for research doc. Provide one, then CONFIRM — say 'yes'.",
    },
    {
        "id"            : "RTP_HAPPY",
        "voice_command" : "research quantum gravity and turn it into a podcast",
        "agent"         : "research to podcast",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All args in voice command. CONFIRM the summary — say 'yes'.",
    },
    {
        "id"            : "RTP_MISSING",
        "voice_command" : "I want research to podcast",
        "agent"         : "research to podcast",
        "key_arg"       : "query",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "You'll be prompted for the topic. Provide one, then CONFIRM — say 'yes'.",
    },
    {
        "id"            : "DR_CANCEL",
        "voice_command" : "do some deep research for me",
        "agent"         : "deep research",
        "key_arg"       : None,
        "missing"       : True,
        "expect_cancel" : True,
        "instructions"  : "Say 'cancel' when prompted for the missing topic (or at confirmation).",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

def _login( email, password ):
    """
    Authenticate and return (token, headers) tuple.

    Requires:
        - email and password are non-empty strings
        - Server running on BASE_URL

    Ensures:
        - Returns (token_str, headers_dict) on success
        - Returns (None, None) on failure
    """
    login_resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password },
        timeout=30
    )

    if login_resp.status_code != 200:
        print( f"✗ Login failed: {login_resp.status_code}" )
        print( f"  Response: {login_resp.text[ :200 ]}" )
        return None, None

    token   = login_resp.json()[ "tokens" ][ "access_token" ]
    headers = { "Authorization": f"Bearer {token}" }
    return token, headers


def _run_scenario( scenario, headers ):
    """
    Submit a single expeditor scenario via mock job endpoint.

    Requires:
        - scenario is a dict from EXPEDITOR_SCENARIOS
        - headers contains valid auth token

    Ensures:
        - Returns (status, response_data) tuple
        - status is 'pass', 'fail', or 'cancel'

    Returns:
        tuple: (status_str, response_dict_or_None)
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/api/mock-job/submit",
            json={ "voice_command": scenario[ "voice_command" ] },
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        if resp.status_code != 200:
            print( f"    ✗ HTTP {resp.status_code}: {resp.text[ :200 ]}" )
            return "fail", None

        data = resp.json()

        if data[ "status" ] == "cancelled":
            if scenario[ "expect_cancel" ]:
                return "pass", data
            else:
                return "cancel", data

        # Verify config has expected command
        config = data.get( "config", {} )
        if scenario[ "agent" ] not in config.get( "command", "" ):
            print( f"    ✗ Expected '{scenario[ 'agent' ]}' in command, got: {config.get( 'command' )}" )
            return "fail", data

        return "pass", data

    except requests.exceptions.Timeout:
        print( f"    ✗ Request timed out after {REQUEST_TIMEOUT}s" )
        return "fail", None
    except Exception as e:
        print( f"    ✗ Error: {e}" )
        return "fail", None


def _poll_for_completion( job_id, headers ):
    """
    Poll done queue for a completed job.

    Requires:
        - job_id is a non-empty string
        - headers contains valid auth token

    Ensures:
        - Returns completed job dict if found within MAX_POLL_SECONDS
        - Returns None if not found

    Returns:
        dict or None
    """
    elapsed = 0

    while elapsed < MAX_POLL_SECONDS:
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
                    return job

        time.sleep( POLL_INTERVAL )
        elapsed += POLL_INTERVAL

    return None


def _verify_dry_run_cost( completed_job ):
    """
    Verify a completed job has $0.00 cost (dry-run).

    Requires:
        - completed_job is a dict from done queue

    Ensures:
        - Returns True if cost is $0.00
        - Returns False otherwise
    """
    cost_summary = completed_job.get( "cost_summary" )
    if cost_summary is None:
        total_cost = 0.0
    elif isinstance( cost_summary, dict ):
        total_cost = cost_summary.get( "total_cost_usd", cost_summary.get( "total_cost", -1 ) )
    else:
        total_cost = 0.0

    return total_cost == 0.0 or total_cost == 0


def _print_results_table( results ):
    """
    Print a formatted summary table of all scenario results.

    Requires:
        - results is a list of dicts with keys: id, status, agent, details

    Ensures:
        - Prints tabular summary to console
    """
    print( "\n" + "=" * 80 )
    print( f"  {'#':<4} {'Scenario':<14} {'Agent':<22} {'Status':<8} {'Details'}" )
    print( "-" * 80 )

    for i, r in enumerate( results, 1 ):
        status_icon = "✓" if r[ "status" ] == "pass" else "✗" if r[ "status" ] == "fail" else "⚠"
        print( f"  {i:<4} {r[ 'id' ]:<14} {r[ 'agent' ]:<22} {status_icon} {r[ 'status' ]:<5}  {r[ 'details' ]}" )

    print( "=" * 80 )

    passed = sum( 1 for r in results if r[ "status" ] == "pass" )
    failed = sum( 1 for r in results if r[ "status" ] == "fail" )
    cancel = sum( 1 for r in results if r[ "status" ] == "cancel" )

    print( f"\n  Total: {passed} passed, {failed} failed, {cancel} unexpected cancels" )
    print( f"  Overall: {'PASS' if failed == 0 and cancel == 0 else 'FAIL'}" )


# ═══════════════════════════════════════════════════════════════════════════════
# Main Test
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test():
    """
    Smoke test for Runtime Argument Expeditor via mock job endpoint.

    Requires:
        - Server running on port 7999
        - LUPIN_TEST_EMAIL and LUPIN_TEST_PASSWORD environment variables set
        - User account exists in development database

    Ensures:
        - Health endpoint returns ok
        - Standard mock job submits and queues correctly
        - All 9 expeditor scenarios execute (interactive tests only)
        - Results are summarized in tabular form
    """
    cu.print_banner( "Expeditor Mock Job Smoke Test (9-Scenario Matrix)", prepend_nl=True )

    interactive = os.environ.get( "LUPIN_INTERACTIVE_TESTS", "" ).lower() == "true"
    if not interactive:
        print( "Note: Scenario tests skipped (set LUPIN_INTERACTIVE_TESTS=true to enable)" )

    # Get credentials from environment
    email    = os.environ.get( "LUPIN_TEST_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_PASSWORD" )

    if not email or not password:
        print( "✗ Missing environment variables:" )
        print( "  export LUPIN_TEST_EMAIL='your@email.com'" )
        print( "  export LUPIN_TEST_PASSWORD='yourpassword'" )
        return False

    try:
        # ═══════════════════════════════════════════════════════════════════
        # Test 1: Login and get token
        # ═══════════════════════════════════════════════════════════════════
        print( f"\nTest 1: Logging in as {email}..." )
        token, headers = _login( email, password )

        if not token:
            return False

        print( f"✓ Login successful, token: {token[ :30 ]}..." )

        # ═══════════════════════════════════════════════════════════════════
        # Test 2: Health check
        # ═══════════════════════════════════════════════════════════════════
        print( "\nTest 2: Checking mock job health endpoint..." )
        health_resp = requests.get( f"{BASE_URL}/api/mock-job/health", timeout=10 )

        if health_resp.status_code != 200:
            print( f"✗ Health check failed: {health_resp.status_code}" )
            return False

        health_data = health_resp.json()
        assert health_data[ "status" ] == "ok", f"Expected status 'ok', got '{health_data[ 'status' ]}'"
        assert health_data[ "available" ] is True, "Expected available=True"
        print( "✓ Mock job health endpoint is alive" )

        # ═══════════════════════════════════════════════════════════════════
        # Test 3: Standard mock job (no voice_command) baseline
        # ═══════════════════════════════════════════════════════════════════
        print( "\nTest 3: Submitting standard mock job (baseline)..." )
        mock_resp = requests.post(
            f"{BASE_URL}/api/mock-job/submit",
            json={
                "fixed_iterations" : 2,
                "fixed_sleep"      : 0.5,
                "description"      : "expeditor smoke test baseline"
            },
            headers=headers,
            timeout=30
        )

        if mock_resp.status_code != 200:
            print( f"✗ Standard mock job failed: {mock_resp.status_code}" )
            print( f"  Response: {mock_resp.text[ :200 ]}" )
            return False

        mock_data = mock_resp.json()
        assert mock_data[ "status" ] == "queued", f"Expected 'queued', got '{mock_data[ 'status' ]}'"
        assert mock_data[ "job_id" ].startswith( "mock-" ), f"Expected job_id prefix 'mock-', got '{mock_data[ 'job_id' ]}'"
        print( f"✓ Standard mock job queued: {mock_data[ 'job_id' ]}" )
        print( f"  Config: {mock_data[ 'config' ]}" )

        # ═══════════════════════════════════════════════════════════════════
        # Tests 4.1-4.9: Expeditor Scenarios (INTERACTIVE)
        # ═══════════════════════════════════════════════════════════════════
        if not interactive:
            print( "\nTests 4.1-4.9: SKIPPED (requires LUPIN_INTERACTIVE_TESTS=true)" )

            print( "\n" + "=" * 70 )
            print( "AUTOMATED SMOKE TESTS PASSED (3/3)!" )
            print( "  Scenario tests skipped: set LUPIN_INTERACTIVE_TESTS=true to enable" )
            print( "=" * 70 )
            return True

        print( "\n" + "=" * 70 )
        print( "  INTERACTIVE EXPEDITOR SCENARIOS (9 total)" )
        print( "  Each scenario will prompt you via voice. Follow the instructions." )
        print( "  Timeout: 600s per scenario. Say 'cancel' to skip any scenario." )
        print( "=" * 70 )

        results = []

        for i, scenario in enumerate( EXPEDITOR_SCENARIOS, 1 ):
            print( f"\n{'─' * 70}" )
            print( f"  Scenario 4.{i}: {scenario[ 'id' ]}" )
            print( f"  Voice command: \"{scenario[ 'voice_command' ]}\"" )
            print( f"  Instructions: {scenario[ 'instructions' ]}" )
            print( f"{'─' * 70}" )

            status, data = _run_scenario( scenario, headers )

            result = {
                "id"      : scenario[ "id" ],
                "status"  : status,
                "agent"   : scenario[ "agent" ],
                "details" : "",
            }

            if status == "pass" and data:
                config = data.get( "config", {} )
                if scenario[ "expect_cancel" ]:
                    result[ "details" ] = "Cancelled as expected"
                    print( f"    ✓ Cancelled as expected" )
                else:
                    job_id = data.get( "job_id", "" )
                    args   = config.get( "args_resolved", {} )
                    result[ "details" ] = f"job={job_id}, args={list( args.keys() )}"
                    print( f"    ✓ Command: {config.get( 'command', 'N/A' )}" )
                    print( f"    ✓ Args: {args}" )
                    print( f"    ✓ Job ID: {job_id}" )

                    # Poll for completion and verify dry-run cost
                    if job_id and not scenario[ "expect_cancel" ]:
                        print( f"    Polling for completion..." )
                        completed = _poll_for_completion( job_id, headers )
                        if completed:
                            if _verify_dry_run_cost( completed ):
                                print( f"    ✓ Dry-run cost: $0.00" )
                            else:
                                print( f"    ⚠ Non-zero cost detected" )
                                result[ "details" ] += " (non-zero cost)"
                        else:
                            print( f"    ⚠ Job not found in done queue after {MAX_POLL_SECONDS}s" )
                            result[ "details" ] += " (poll timeout)"

            elif status == "cancel":
                result[ "details" ] = "User cancelled unexpectedly"
                print( f"    ⚠ User cancelled (expected to complete)" )

            elif status == "fail":
                result[ "details" ] = "Request failed"
                print( f"    ✗ Scenario failed" )

            results.append( result )

        # ═══════════════════════════════════════════════════════════════════
        # Results Summary
        # ═══════════════════════════════════════════════════════════════════
        _print_results_table( results )

        passed = sum( 1 for r in results if r[ "status" ] == "pass" )
        failed = sum( 1 for r in results if r[ "status" ] == "fail" )
        cancel = sum( 1 for r in results if r[ "status" ] == "cancel" )

        all_passed = failed == 0 and cancel == 0

        print( f"\n{'=' * 70}" )
        if all_passed:
            print( f"ALL EXPEDITOR SMOKE TESTS PASSED ({3 + passed}/{3 + len( EXPEDITOR_SCENARIOS )})!" )
        else:
            print( f"EXPEDITOR SMOKE TESTS: {3 + passed} passed, {failed} failed, {cancel} unexpected cancels" )
        print( "=" * 70 )

        return all_passed

    except AssertionError as e:
        print( f"\n✗ Assertion failed: {e}" )
        traceback.print_exc()
        return False
    except requests.exceptions.ConnectionError:
        print( f"\n✗ Connection failed - is the server running on {BASE_URL}?" )
        return False
    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        traceback.print_exc()
        return False


def test_expeditor_mock_job_smoke():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    try:
        success = quick_smoke_test()
        sys.exit( 0 if success else 1 )
    except Exception as e:
        traceback.print_exc()
        sys.exit( 1 )
