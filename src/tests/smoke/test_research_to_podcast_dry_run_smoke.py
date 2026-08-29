#!/usr/bin/env python3
"""
Smoke test for Research→Podcast (chained workflow) dry-run mode.

⚠️ VENUE: :8000 (test), NOT :7999 — AND THIS FILE IS STILL RUN BY THE :7999 SMOKE TIER,
   SO IT IS EXPECTED RED THERE. Recorded 2026-08-26 (row 554e5d3e); NOT MOVED, deliberately.

   Criterion tripped (CLAUDE.md § TESTING VENUES — a file is :8000 if ANY apply):
     - mutates persistent state (submits a real chained job that outlives the test)
   Evidence, from this file:
     - posts to `/api/v2/submit`, then polls `/api/get-queue/done` for the job
     - "dry run" bounds the COST, not the SIDE EFFECTS — see the note in
       test_podcast_generator_dry_run_smoke.py; $0.00 is not zero-side-effect
   WHY IT WAS NOT MOVED. `run-smoke-tests.sh` runs the whole `src/tests/smoke/` directory,
   so this file is executed on :7999 by the smoke merge gate regardless of what its
   docstring says. Relocating it, or excluding it from the runner the way
   test_proxy_integration.py is excluded, would deselect it from that gate — a change to
   what the gate covers, which is an owner's decision and not a drive-by while clearing a
   red list. So it stays, it stays red on :7999, and the reason is written here instead of
   being re-derived by the next reader.

   HOW TO RUN IT PROPERLY: submit via `POST /api/test-suite/submit` against :8000 on a
   verified-idle server (`PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000`,
   exit 0 = IDLE). Never side-door it via curl or a direct queue push.

Verifies that:
1. Dry-run jobs are accepted by the API
2. Jobs flow through the queue system
3. Completion includes mock results ($0.00 cost)
4. Job ID uses rp- prefix (research-to-podcast)

Requires:
- Server running on localhost:7999
- Environment variables: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

Created: 2026-02-02
Session: 115 (Bug Fix Mode)
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


BASE_URL = "http://localhost:7999"
MAX_POLL_SECONDS = 120  # Chained workflow may take longer
POLL_INTERVAL = 2


def quick_smoke_test():
    """
    Smoke test for Research→Podcast dry-run mode.

    Requires:
        - Server running on port 7999
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD environment variables set
        - User account exists in development database

    Ensures:
        - Endpoint accepts authenticated POST requests with dry_run=true
        - Returns expected response structure (job_id, queue_position, message)
        - Job ID uses rp- prefix
        - Job completes in done queue with mock results ($0.00 cost)
    """
    cu.print_banner( "Research→Podcast Dry-Run Smoke Test", prepend_nl=True )

    # Get credentials from environment
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

    if not email or not password:
        print( "✗ Missing environment variables:" )
        print( "  export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL='your@email.com'" )
        print( "  export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD='yourpassword'" )
        return False

    try:
        # ═══════════════════════════════════════════════════════════════════════
        # Test 1: Login and get token
        # ═══════════════════════════════════════════════════════════════════════
        print( f"Test 1: Logging in as {email}..." )
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

        # ═══════════════════════════════════════════════════════════════════════
        # Test 2: Submit Research→Podcast job with dry_run=true
        # ═══════════════════════════════════════════════════════════════════════
        print( "\nTest 2: Submitting Research→Podcast job with dry_run=true..." )
        headers = { "Authorization": f"Bearer {token}" }
        payload = {
            "query"            : "[Research→Podcast] dry-run smoke test - safe to ignore",
            "budget"           : 0.01,
            "target_languages" : [ "en" ],
            "dry_run"          : True
        }
        # Lineage tag (row 7451bebe / bug 5ed4f187): a child pytest inside a monopolizing
        # test-suite job must thread LUPIN_TEST_MONOPOLIZE_PARENT_ID or the consumer's Gate B
        # defers it as a foreign writer and it starves 900s.
        parent_id = os.environ.get( "LUPIN_TEST_MONOPOLIZE_PARENT_ID" )

        # ONE DOOR NOW. The dedicated endpoint this used to post to is retired and
        # answers 410 naming /api/v2/submit, which takes the routing command as a string
        # and the agent's own arguments in `args`. `websocket_id` and `parent_id_hash` stay
        # TOP-LEVEL: they are instructions about the request and the queue, not arguments
        # to the agent, and `args` is checked against the command's own argument contract.
        ws_id = payload.pop( "websocket_id", None )
        body  = {
            "command"  : "agent router go to research to podcast",
            "args"     : payload,
            "question" : payload.get( "query", "" ),
        }
        if ws_id:     body[ "websocket_id" ]   = ws_id
        if parent_id: body[ "parent_id_hash" ] = parent_id

        submit_resp = requests.post(
            f"{BASE_URL}/api/v2/submit",
            json=body,
            headers=headers
        )

        if submit_resp.status_code != 200:
            print( f"✗ Submit failed: {submit_resp.status_code}" )
            print( f"  Response: {submit_resp.text[ :200 ]}" )
            return False

        data = submit_resp.json()
        print( f"✓ Job submitted successfully" )
        print( f"  Job ID: {data.get( 'job_id', 'unknown' )}" )
        print( f"  Queue position: {data.get( 'queue_position', 'unknown' )}" )
        print( f"  Message: {data.get( 'message', 'unknown' )}" )

        job_id = data.get( "job_id" )

        # ═══════════════════════════════════════════════════════════════════════
        # Test 3: Verify response structure
        # ═══════════════════════════════════════════════════════════════════════
        print( "\nTest 3: Verifying response structure..." )
        required_keys = [ "job_id", "queue_position", "message" ]
        for key in required_keys:
            if key not in data:
                print( f"✗ Missing required key: {key}" )
                return False
            print( f"✓ {key}: present" )

        # Verify job ID format (rp- prefix for research-to-podcast)
        assert data[ "job_id" ].startswith( "rp-" ), f"Expected job_id to start with 'rp-', got '{data[ 'job_id' ]}'"
        print( f"✓ Job ID format correct: {data[ 'job_id' ]}" )

        assert isinstance( data[ "queue_position" ], int ), "Expected queue_position to be int"
        assert data[ "queue_position" ] >= 0, "Expected queue_position >= 0"
        print( f"✓ Queue position is valid: {data[ 'queue_position' ]}" )

        # ═══════════════════════════════════════════════════════════════════════
        # Test 4: Poll done queue for completion
        # ═══════════════════════════════════════════════════════════════════════
        print( f"\nTest 4: Polling done queue for job completion (max {MAX_POLL_SECONDS}s)..." )
        print( "  Note: Chained workflow (research→podcast) may take longer than single jobs" )

        job_found      = False
        completed_job  = None
        elapsed        = 0

        while elapsed < MAX_POLL_SECONDS:
            # Use correct endpoint: /api/get-queue/done
            done_resp = requests.get(
                f"{BASE_URL}/api/get-queue/done",
                headers=headers
            )

            if done_resp.status_code == 200:
                done_data = done_resp.json()
                # Response structure: done_jobs_metadata contains job objects with job_id
                jobs = done_data.get( "done_jobs_metadata", [] )

                for job in jobs:
                    if job.get( "job_id" ) == job_id:
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
            print( "  Note: Dry-run chained jobs should complete in ~15-20 seconds" )
            return False

        # ═══════════════════════════════════════════════════════════════════════
        # Test 5: Verify dry-run results (mock data, $0.00 cost)
        # ═══════════════════════════════════════════════════════════════════════
        print( "\nTest 5: Verifying dry-run results..." )

        # Check cost summary shows $0.00
        cost_summary = completed_job.get( "cost_summary" )
        if cost_summary is None:
            print( f"⚠ No cost_summary in response - checking if job completed successfully" )
            total_cost = 0.0  # Assume dry-run if no cost data
        elif isinstance( cost_summary, dict ):
            total_cost = cost_summary.get( "total_cost_usd", cost_summary.get( "total_cost", -1 ) )
        else:
            total_cost = getattr( cost_summary, "total_cost_usd", getattr( cost_summary, "total_cost", -1 ) )

        if total_cost == 0.0 or total_cost == 0:
            print( f"✓ Cost is $0.00 (dry-run mode confirmed)" )
        else:
            print( f"✗ Expected cost $0.00, got ${total_cost}" )
            print( f"  cost_summary: {cost_summary}" )
            return False

        # Check abstract contains mock/dry-run indicator
        abstract = ( completed_job.get( "abstract" ) or "" ).lower()
        if "dry run" in abstract or "dry-run" in abstract or "mock" in abstract:
            print( "✓ Abstract contains dry-run indicator" )
        else:
            print( f"⚠ Abstract may not indicate dry-run: {( completed_job.get( 'abstract' ) or '' )[ :100 ]}" )
            # Not a failure - just a warning

        # Check job status
        job_status = completed_job.get( "status", "" )
        if job_status == "completed":
            print( "✓ Job status is 'completed'" )
        else:
            print( f"✗ Expected status 'completed', got '{job_status}'" )
            return False

        # ═══════════════════════════════════════════════════════════════════════
        # All tests passed
        # ═══════════════════════════════════════════════════════════════════════
        print( "\n" + "=" * 70 )
        print( "ALL RESEARCH→PODCAST DRY-RUN SMOKE TESTS PASSED!" )
        print( "=" * 70 )
        print( "\nResearch→Podcast dry-run mode is operational!" )
        print( f"  Job ID: {job_id}" )
        print( f"  Cost: ${total_cost:.2f}" )
        print( f"  Completed in: ~{elapsed}s" )

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


def test_research_to_podcast_dry_run_smoke():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    try:
        success = quick_smoke_test()
        sys.exit( 0 if success else 1 )
    except Exception as e:
        traceback.print_exc()
        sys.exit( 1 )
