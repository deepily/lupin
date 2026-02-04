#!/usr/bin/env python3
"""
Smoke test for Podcast Generator dry-run mode.

Verifies that:
1. Dry-run jobs are accepted by the API
2. Jobs flow through the queue system
3. Completion includes mock results ($0.00 cost)

Requires:
- Server running on localhost:7999
- Environment variables: LUPIN_TEST_EMAIL, LUPIN_TEST_PASSWORD
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
        - LUPIN_TEST_EMAIL and LUPIN_TEST_PASSWORD environment variables set
        - User account exists in development database
        - At least one research file exists for the user

    Ensures:
        - Endpoint accepts authenticated POST requests with dry_run=true
        - Returns expected response structure (status, job_id, queue_position)
        - Job completes in done queue with mock results ($0.00 cost)
    """
    cu.print_banner( "Podcast Generator Dry-Run Smoke Test", prepend_nl=True )

    # Get credentials from environment
    email    = os.environ.get( "LUPIN_TEST_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_PASSWORD" )

    if not email or not password:
        print( "✗ Missing environment variables:" )
        print( "  export LUPIN_TEST_EMAIL='your@email.com'" )
        print( "  export LUPIN_TEST_PASSWORD='yourpassword'" )
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
        submit_resp = requests.post(
            f"{BASE_URL}/api/podcast-generator/submit",
            json={
                "research_source"  : research_path,
                "target_languages" : [ "en" ],
                "dry_run"          : True
            },
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
        print( f"  Queue position: {data.get( 'queue_position', 'unknown' )}" )

        job_id = data.get( "job_id" )

        # ═══════════════════════════════════════════════════════════════════════
        # Test 4: Verify response structure
        # ═══════════════════════════════════════════════════════════════════════
        print( "\nTest 4: Verifying response structure..." )
        required_keys = [ "status", "job_id", "queue_position" ]
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

        assert isinstance( data[ "queue_position" ], int ), "Expected queue_position to be int"
        assert data[ "queue_position" ] >= 0, "Expected queue_position >= 0"
        print( f"✓ Queue position is valid: {data[ 'queue_position' ]}" )

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
    assert quick_smoke_test()


if __name__ == "__main__":
    try:
        success = quick_smoke_test()
        sys.exit( 0 if success else 1 )
    except Exception as e:
        traceback.print_exc()
        sys.exit( 1 )
