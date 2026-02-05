#!/usr/bin/env python3
"""
Smoke test for Runtime Argument Expeditor via mock job endpoint.

Verifies that:
1. Login and auth token retrieval works
2. Mock job health endpoint is alive
3. Standard mock job (no voice_command) baseline works
4. Expeditor test mode routes voice commands correctly (INTERACTIVE)
5. Dry-run job completes in done queue with $0.00 cost (INTERACTIVE)

Tests 4-5 require LUPIN_INTERACTIVE_TESTS=true because they:
- Call LLM for gap analysis (real inference cost)
- Call notify_user_sync() for missing args (blocks for user response)

Requires:
- Server running on localhost:7999
- Environment variables: LUPIN_TEST_EMAIL, LUPIN_TEST_PASSWORD
- For tests 4-5: LUPIN_INTERACTIVE_TESTS=true

Created: 2026-02-05
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
MAX_POLL_SECONDS = 60
POLL_INTERVAL    = 2


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
        - Expeditor test routes voice commands (interactive tests only)
        - Dry-run jobs complete with $0.00 cost (interactive tests only)
    """
    cu.print_banner( "Expeditor Mock Job Smoke Test", prepend_nl=True )

    interactive = os.environ.get( "LUPIN_INTERACTIVE_TESTS", "" ).lower() == "true"
    if not interactive:
        print( "Note: Tests 4-5 skipped (set LUPIN_INTERACTIVE_TESTS=true to enable)" )

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
        login_resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={ "email": email, "password": password }
        )

        if login_resp.status_code != 200:
            print( f"✗ Login failed: {login_resp.status_code}" )
            print( f"  Response: {login_resp.text[ :200 ]}" )
            return False

        token = login_resp.json()[ "tokens" ][ "access_token" ]
        print( f"✓ Login successful, token: {token[ :30 ]}..." )
        headers = { "Authorization": f"Bearer {token}" }

        # ═══════════════════════════════════════════════════════════════════
        # Test 2: Health check
        # ═══════════════════════════════════════════════════════════════════
        print( "\nTest 2: Checking mock job health endpoint..." )
        health_resp = requests.get( f"{BASE_URL}/api/mock-job/health" )

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
            headers=headers
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
        # Test 4: Expeditor test (INTERACTIVE)
        # ═══════════════════════════════════════════════════════════════════
        if not interactive:
            print( "\nTest 4: SKIPPED (requires LUPIN_INTERACTIVE_TESTS=true)" )
            print( "Test 5: SKIPPED (requires LUPIN_INTERACTIVE_TESTS=true)" )

            print( "\n" + "=" * 70 )
            print( "AUTOMATED SMOKE TESTS PASSED (3/3)!" )
            print( "  Tests 4-5 skipped: set LUPIN_INTERACTIVE_TESTS=true to enable" )
            print( "=" * 70 )
            return True

        print( "\nTest 4: Submitting expeditor test with voice_command..." )
        print( "  ⚠ This calls the LLM and may prompt you for missing args!" )

        expeditor_resp = requests.post(
            f"{BASE_URL}/api/mock-job/submit",
            json={
                "voice_command": "do deep research on quantum computing"
            },
            headers=headers
        )

        if expeditor_resp.status_code != 200:
            print( f"✗ Expeditor test failed: {expeditor_resp.status_code}" )
            print( f"  Response: {expeditor_resp.text[ :300 ]}" )
            return False

        exp_data = expeditor_resp.json()
        print( f"✓ Expeditor test returned: status={exp_data[ 'status' ]}" )
        print( f"  Job ID: {exp_data[ 'job_id' ]}" )

        # Check for cancelled vs queued
        if exp_data[ "status" ] == "cancelled":
            print( "  ⚠ User cancelled or timed out - this is valid behavior" )
            print( f"  Config: {exp_data[ 'config' ]}" )
            print( "\n" + "=" * 70 )
            print( "EXPEDITOR SMOKE TESTS: 4/5 PASSED (Test 5 skipped - user cancelled)" )
            print( "=" * 70 )
            return True

        # Verify expeditor resolved the command
        config = exp_data[ "config" ]
        assert "command" in config, "Missing 'command' in config"
        assert "deep research" in config[ "command" ], f"Expected deep research command, got: {config[ 'command' ]}"
        assert config.get( "dry_run" ) is True, "Expected dry_run=True"

        args_resolved = config.get( "args_resolved", {} )
        assert "query" in args_resolved, f"Expected 'query' in resolved args, got: {args_resolved}"
        print( f"  Command matched: {config[ 'command' ]}" )
        print( f"  Args resolved: {args_resolved}" )
        print( f"  dry_run: {config.get( 'dry_run' )}" )

        exp_job_id = exp_data[ "job_id" ]

        # ═══════════════════════════════════════════════════════════════════
        # Test 5: Verify dry-run job completes ($0.00 cost)
        # ═══════════════════════════════════════════════════════════════════
        print( f"\nTest 5: Polling done queue for expeditor job (max {MAX_POLL_SECONDS}s)..." )

        job_found     = False
        completed_job = None
        elapsed       = 0

        while elapsed < MAX_POLL_SECONDS:
            done_resp = requests.get(
                f"{BASE_URL}/api/get-queue/done",
                headers=headers
            )

            if done_resp.status_code == 200:
                done_data = done_resp.json()
                jobs      = done_data.get( "done_jobs_metadata", [] )

                for job in jobs:
                    if job.get( "job_id" ) == exp_job_id:
                        job_found     = True
                        completed_job = job
                        break

                if job_found:
                    print( f"✓ Job found in done queue after {elapsed}s" )
                    break

            print( f"  Polling... ({elapsed}s)" )
            time.sleep( POLL_INTERVAL )
            elapsed += POLL_INTERVAL

        if not job_found:
            print( f"✗ Job not found in done queue after {MAX_POLL_SECONDS}s" )
            print( "  Note: Dry-run jobs should complete in ~6 seconds" )
            return False

        # Verify cost is $0.00 (dry-run)
        cost_summary = completed_job.get( "cost_summary" )
        if cost_summary is None:
            total_cost = 0.0
        elif isinstance( cost_summary, dict ):
            total_cost = cost_summary.get( "total_cost_usd", cost_summary.get( "total_cost", -1 ) )
        else:
            total_cost = 0.0

        if total_cost == 0.0 or total_cost == 0:
            print( f"✓ Cost is $0.00 (dry-run mode confirmed)" )
        else:
            print( f"✗ Expected cost $0.00, got ${total_cost}" )
            return False

        # Check job status
        job_status = completed_job.get( "status", "" )
        if job_status == "completed":
            print( "✓ Job status is 'completed'" )
        else:
            print( f"✗ Expected status 'completed', got '{job_status}'" )
            return False

        # ═══════════════════════════════════════════════════════════════════
        # All tests passed
        # ═══════════════════════════════════════════════════════════════════
        print( "\n" + "=" * 70 )
        print( "ALL EXPEDITOR SMOKE TESTS PASSED (5/5)!" )
        print( "=" * 70 )
        print( f"\n  Expeditor correctly routed voice command:" )
        print( f"    Command: {config[ 'command' ]}" )
        print( f"    Args: {args_resolved}" )
        print( f"    Job ID: {exp_job_id}" )
        print( f"    Cost: ${total_cost:.2f}" )
        print( f"    Completed in: ~{elapsed}s" )

        return True

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
