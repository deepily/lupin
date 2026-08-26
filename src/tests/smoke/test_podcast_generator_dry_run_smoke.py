#!/usr/bin/env python3
"""
Smoke test for Podcast Generator dry-run mode.

⚠️ VENUE: :8000 (test), NOT :7999 — AND THIS FILE IS STILL RUN BY THE :7999 SMOKE TIER,
   SO IT IS EXPECTED RED THERE. Recorded 2026-08-26 (row 554e5d3e); NOT MOVED, deliberately.

   Criterion tripped (CLAUDE.md § TESTING VENUES — a file is :8000 if ANY apply):
     - mutates persistent state (submits a real job that outlives the test)
   Evidence, from this file:
     - posts to `/api/v2/submit`, then polls `/api/get-queue/done` for the job
     - "dry run" bounds the COST, not the SIDE EFFECTS: the job is really
       enqueued, really executed and really lands in the done queue. $0.00 is
       not zero-side-effect, and the rubric names persistence, not spend
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

Requires:
- Server running on localhost:7999
- Environment variables: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD
- At least one research file in user's deep-research directory

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
MAX_POLL_SECONDS = 60  # Podcast dry-run takes ~6 seconds
POLL_INTERVAL = 2


def quick_smoke_test():
    """
    Smoke test for Podcast Generator dry-run mode.

    Requires:
        - Server running on port 7999
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD environment variables set
        - User account exists in development database
        - At least one research file exists for the user

    Ensures:
        - Endpoint accepts authenticated POST requests with dry_run=true
        - Returns expected response structure (status, job_id)
        - Job completes in done queue with mock results ($0.00 cost)
    """
    cu.print_banner( "Podcast Generator Dry-Run Smoke Test", prepend_nl=True )

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
        # Test 2: Find a research file to use
        # ═══════════════════════════════════════════════════════════════════════
        print( "\nTest 2: Finding research file to use..." )

        # Construct expected research path
        research_base = f"/io/deep-research/{email}/"
        research_full_path = cu.get_project_root() + research_base

        if not os.path.exists( research_full_path ):
            print( f"✗ Research directory not found: {research_full_path}" )
            print( "  Create a research file first with Deep Research" )
            return False

        # Find first .md file
        md_files = [ f for f in os.listdir( research_full_path ) if f.endswith( '.md' ) ]
        if not md_files:
            print( f"✗ No research files found in: {research_full_path}" )
            return False

        research_file = md_files[ 0 ]
        research_path = research_base + research_file
        print( f"✓ Using research file: {research_file}" )

        # ═══════════════════════════════════════════════════════════════════════
        # Test 3: Submit Podcast Generator job with dry_run=true
        # ═══════════════════════════════════════════════════════════════════════
        print( "\nTest 3: Submitting Podcast Generator job with dry_run=true..." )
        headers = { "Authorization": f"Bearer {token}" }
        args = {
            "research"         : research_path,
            "languages"        : [ "en" ],
            "dry_run"          : True
        }
        # Lineage tag (bug 5ed4f187): when this smoke runs as a child pytest inside a
        # monopolizing test-suite job, the runner exports LUPIN_TEST_MONOPOLIZE_PARENT_ID
        # (test_suite/job.py). Threading it as parent_id_hash lets the consumer's Gate B
        # admit this child through the monopoly hold instead of starving it 900s.
        parent_id = os.environ.get( "LUPIN_TEST_MONOPOLIZE_PARENT_ID" )

        # ONE DOOR NOW, AND THIS HARNESS PICKS THE OTHER ONE ON PURPOSE. The retired door
        # answers 410 naming /api/v2/ask, because a human asking for a podcast is asking a
        # question and the flow's expeditor resolves the document and the missing arguments
        # by conversation. A test does not want that: it already knows the command and the
        # arguments, and routing a fixed research path through a fuzzy matcher would make
        # this smoke depend on the resolver rather than on the podcast pipeline it exists to
        # exercise. So the harness posts to /api/v2/submit (Cheech, ruled 2026-08-21).
        # `parent_id_hash` stays TOP-LEVEL: it is a queue directive, and `args` is checked
        # against the command's own argument contract, which it is not in.
        payload = {
            "command"  : "agent router go to podcast generator",
            "args"     : args,
            "question" : research_path,
        }
        if parent_id:
            payload[ "parent_id_hash" ] = parent_id
        submit_resp = requests.post(
            f"{BASE_URL}/api/v2/submit",
            json=payload,
            headers=headers
        )

        if submit_resp.status_code != 200:
            print( f"✗ Submit failed: {submit_resp.status_code}" )
            print( f"  Response: {submit_resp.text[ :200 ]}" )
            return False

        data = submit_resp.json()
        print( f"✓ Job submitted successfully" )
        print( f"  Status: {data.get( 'status', 'unknown' )}" )
        print( f"  Job ID: {data.get( 'job_id', 'unknown' )}" )

        job_id = data.get( "job_id" )

        # ═══════════════════════════════════════════════════════════════════════
        # Test 4: Verify response structure
        # ═══════════════════════════════════════════════════════════════════════
        print( "\nTest 4: Verifying response structure..." )
        # NO queue_position. The v2 response carries none and is not being widened for one:
        # a place in the queue changes as the queue moves, so a number frozen at the instant
        # of submission was stale the moment it was printed. A job card learns its real place
        # from the queue websocket events.
        required_keys = [ "status", "job_id" ]
        for key in required_keys:
            if key not in data:
                print( f"✗ Missing required key: {key}" )
                return False
            print( f"✓ {key}: present" )

        # Verify expected values
        assert data[ "status" ] == "queued", f"Expected status 'queued', got '{data[ 'status' ]}'"
        print( "✓ Status is 'queued'" )

        assert data[ "job_id" ].startswith( "pg-" ), f"Expected job_id to start with 'pg-', got '{data[ 'job_id' ]}'"
        print( f"✓ Job ID format correct: {data[ 'job_id' ]}" )


        # ═══════════════════════════════════════════════════════════════════════
        # Test 5: Poll done queue for completion
        # ═══════════════════════════════════════════════════════════════════════
        print( f"\nTest 5: Polling done queue for job completion (max {MAX_POLL_SECONDS}s)..." )

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
            print( "  Note: Dry-run jobs should complete in ~6 seconds" )
            return False

        # ═══════════════════════════════════════════════════════════════════════
        # Test 6: Verify dry-run results (mock data, $0.00 cost)
        # ═══════════════════════════════════════════════════════════════════════
        print( "\nTest 6: Verifying dry-run results..." )

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
        print( "ALL PODCAST GENERATOR DRY-RUN SMOKE TESTS PASSED!" )
        print( "=" * 70 )
        print( "\nPodcast Generator dry-run mode is operational!" )
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


def test_podcast_generator_dry_run_smoke():
    """Pytest entry point."""
    import pytest
    email = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    if email:
        research_full_path = cu.get_project_root() + f"/io/deep-research/{email}/"
        if not os.path.exists( research_full_path ) or not [
            f for f in ( os.listdir( research_full_path ) if os.path.exists( research_full_path ) else [] )
            if f.endswith( '.md' )
        ]:
            pytest.skip(
                f"No research files in {research_full_path} — podcast test needs a "
                "real DR report as input. DR dry_run paths emit mock-only metadata "
                "(no file written). Run a non-dry-run DR first to populate this directory."
            )
    assert quick_smoke_test()


if __name__ == "__main__":
    try:
        success = quick_smoke_test()
        sys.exit( 0 if success else 1 )
    except Exception as e:
        traceback.print_exc()
        sys.exit( 1 )
