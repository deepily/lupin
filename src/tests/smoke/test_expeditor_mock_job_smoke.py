#!/usr/bin/env python3
"""
Smoke test for Runtime Argument Expeditor via mock job endpoint.

Verifies that:
1. Login and auth token retrieval works
2. Mock job health endpoint is alive
3. Standard mock job (no voice_command) baseline works
4.1-4.13 Thirteen expeditor scenarios covering all 3 agents, audience params,
        missing args, confirmation loop, and cancellation (INTERACTIVE)

Tests 4.x require LUPIN_INTERACTIVE_TESTS=true because they:
- Call LLM for gap analysis (real inference cost)
- Call notify_user_sync() for missing args + confirmation (blocks for user response)

Scenario Index Reference:
    0  DR_HAPPY    — "do deep research on quantum computing"
    1  DR_MISSING  — "do some deep research"
    2  DR_BUDGET   — "...climate change with a budget of 5 dollars"
    3  DR_AUDIENCE — "...machine learning for a beginner audience"
    4  PG_MISSING  — "make me a podcast"
    5  PG_AUDIENCE — "...for an expert audience"
    6  RTP_HAPPY   — "research quantum gravity and turn it into a podcast"
    7  RTP_MISSING — "I want research to podcast"
    8  DR_CANCEL   — "do some deep research for me" (user cancels)
    9  DR_FULL       — "...dark matter with a budget of 10 dollars for an expert audience"
   10  RTP_LANGUAGES — "research artificial intelligence and make a podcast in Spanish"
   11  PG_LANGUAGES  — "make me a podcast in English and Spanish"
   12  RTP_BARE      — "I want a research to podcast job"

Usage:
    # Run all 13 scenarios
    LUPIN_INTERACTIVE_TESTS=true python src/tests/smoke/test_expeditor_mock_job_smoke.py

    # Run only DR_HAPPY (scenario 0) to diagnose first
    LUPIN_INTERACTIVE_TESTS=true python -m tests.smoke.test_expeditor_mock_job_smoke -s 0

    # Run DR scenarios only (0-3 and cancel)
    LUPIN_INTERACTIVE_TESTS=true python -m tests.smoke.test_expeditor_mock_job_smoke -s 0,1,2,3,8

    # Run just PG scenarios (4, 5)
    LUPIN_INTERACTIVE_TESTS=true python -m tests.smoke.test_expeditor_mock_job_smoke -s 4,5

Requires:
- Server running on localhost:7999
- Environment variables: LUPIN_TEST_EMAIL, LUPIN_TEST_PASSWORD
- For tests 4.x: LUPIN_INTERACTIVE_TESTS=true
  (uses LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / PASSWORD)

Created: 2026-02-05
Updated: 2026-02-11 — Expanded to 13 scenarios, single-pass proxy docs

Automated Execution with Notification Proxy (scenarios 0-7, 9-12):
    Terminal 1: Server running on port 7999
    Terminal 2: PYTHONPATH=src python -m cosa.agents.notification_proxy --profile expeditor_smoke --debug
    Terminal 3: LUPIN_INTERACTIVE_TESTS=true python -m tests.smoke.test_expeditor_mock_job_smoke -s 0,1,2,3,4,5,6,7,9,10,11,12

    Scenario 8 (DR_CANCEL) excluded: The proxy auto-answers all notifications,
    but DR_CANCEL needs a "cancel" response. Its notification is identical to
    DR_MISSING (same response_type, title, sender_id) so the proxy cannot
    distinguish them. Cancel path is unit-tested in test_notification_proxy.py
    and test_runtime_argument_expeditor.py.
"""

import os
import sys
import time
import argparse
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
        "expected_args" : { "query": "quantum computing breakthroughs 2026" },
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
        "expected_args" : { "research": "/tmp/mock-research-document.md" },
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
        "expected_args" : { "query": "quantum computing breakthroughs 2026" },
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
    {
        "id"            : "DR_FULL",
        "voice_command" : "do deep research on dark matter with a budget of 10 dollars for an expert audience",
        "agent"         : "deep research",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "All main args in voice command. Confirm the summary — say 'yes'.",
    },
    {
        "id"            : "RTP_LANGUAGES",
        "voice_command" : "research artificial intelligence and make a podcast in Spanish",
        "agent"         : "research to podcast",
        "key_arg"       : "query",
        "missing"       : False,
        "expect_cancel" : False,
        "instructions"  : "Query + languages should extract. You'll be asked about budget/audience. Provide answers, then say 'yes'.",
    },
    {
        "id"            : "PG_LANGUAGES",
        "voice_command" : "make me a podcast in English and Spanish",
        "agent"         : "podcast",
        "key_arg"       : "research",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "Languages should extract. You'll be asked for research doc + audience. Provide answers, then say 'yes'.",
        "expected_args" : { "research": "/tmp/mock-research-document.md" },
    },
    {
        "id"            : "RTP_BARE",
        "voice_command" : "I want a research to podcast job",
        "agent"         : "research to podcast",
        "key_arg"       : "query",
        "missing"       : True,
        "expect_cancel" : False,
        "instructions"  : "No args extracted. Provide all values when prompted, then say 'yes'.",
        "expected_args" : { "query": "quantum computing breakthroughs 2026" },
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

        # Soft verification: check proxy-provided args match expected values
        expected = scenario.get( "expected_args" )
        if expected and config.get( "args_resolved" ):
            for arg_name, expected_value in expected.items():
                actual = config[ "args_resolved" ].get( arg_name )
                if actual != expected_value:
                    print( f"    ⚠ Arg mismatch: {arg_name} expected='{expected_value}' got='{actual}'" )

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

def quick_smoke_test( scenario_indices=None ):
    """
    Smoke test for Runtime Argument Expeditor via mock job endpoint.

    Requires:
        - Server running on port 7999
        - LUPIN_TEST_EMAIL and LUPIN_TEST_PASSWORD environment variables set
        - User account exists in development database
        - scenario_indices is None (all) or a list of valid int indices into EXPEDITOR_SCENARIOS

    Ensures:
        - Health endpoint returns ok
        - Standard mock job submits and queues correctly
        - Selected expeditor scenarios execute (interactive tests only)
        - Results are summarized in tabular form
    """
    cu.print_banner( "Expeditor Mock Job Smoke Test (13-Scenario Matrix)", prepend_nl=True )

    interactive = os.environ.get( "LUPIN_INTERACTIVE_TESTS", "" ).lower() == "true"
    if not interactive:
        print( "Note: Scenario tests skipped (set LUPIN_INTERACTIVE_TESTS=true to enable)" )

    # Get credentials from environment
    # Interactive tests use a dedicated tester account for voice I/O routing
    if interactive:
        email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
        password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
        env_prefix = "LUPIN_TEST_INTERACTIVE_MOCK_JOBS"
    else:
        email    = os.environ.get( "LUPIN_TEST_EMAIL" )
        password = os.environ.get( "LUPIN_TEST_PASSWORD" )
        env_prefix = "LUPIN_TEST"

    if not email or not password:
        print( f"✗ Missing environment variables:" )
        print( f"  export {env_prefix}_EMAIL='your@email.com'" )
        print( f"  export {env_prefix}_PASSWORD='yourpassword'" )
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
        # Tests 4.1-4.13: Expeditor Scenarios (INTERACTIVE)
        # ═══════════════════════════════════════════════════════════════════
        if not interactive:
            print( "\nTests 4.1-4.13: SKIPPED (requires LUPIN_INTERACTIVE_TESTS=true)" )

            print( "\n" + "=" * 70 )
            print( "AUTOMATED SMOKE TESTS PASSED (3/3)!" )
            print( "  Scenario tests skipped: set LUPIN_INTERACTIVE_TESTS=true to enable" )
            print( "=" * 70 )
            return True

        # Filter scenarios if indices provided
        if scenario_indices is not None:
            scenarios = [ EXPEDITOR_SCENARIOS[ i ] for i in scenario_indices if i < len( EXPEDITOR_SCENARIOS ) ]
            label     = f"INTERACTIVE EXPEDITOR SCENARIOS ({len( scenarios )} of {len( EXPEDITOR_SCENARIOS )})"
        else:
            scenarios = EXPEDITOR_SCENARIOS
            label     = f"INTERACTIVE EXPEDITOR SCENARIOS ({len( scenarios )} total)"

        print( "\n" + "=" * 70 )
        print( f"  {label}" )
        print( "  Each scenario will prompt you via voice. Follow the instructions." )
        print( "  Timeout: 600s per scenario. Say 'cancel' to skip any scenario." )
        print( "=" * 70 )

        results = []

        for i, scenario in enumerate( scenarios, 1 ):
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
            print( f"ALL EXPEDITOR SMOKE TESTS PASSED ({3 + passed}/{3 + len( scenarios )})!" )
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
    parser = argparse.ArgumentParser( description="Expeditor mock job smoke test (13-scenario matrix)" )
    parser.add_argument(
        "--scenarios", "-s",
        type=str,
        default=None,
        help="Comma-separated scenario indices to run (e.g., '0,3,8'). Default: all."
    )
    args = parser.parse_args()

    indices = None
    if args.scenarios:
        indices = [ int( x.strip() ) for x in args.scenarios.split( "," ) ]

    try:
        success = quick_smoke_test( scenario_indices=indices )
        sys.exit( 0 if success else 1 )
    except Exception as e:
        traceback.print_exc()
        sys.exit( 1 )
