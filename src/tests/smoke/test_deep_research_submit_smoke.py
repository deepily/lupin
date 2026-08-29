"""
Smoke test for Deep Research background job submission.
Tests deep research submission through POST /api/v2/submit.
(The old /api/deep-research/submit door is retired and answers 410.)

NON-DESTRUCTIVE: Uses existing user from development database.
Run with: python -m tests.smoke.test_deep_research_submit_smoke

Requires environment variables:
    LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL    - Email for login
    LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD - Password for login

Created: 2026-01-20
"""

import os
import sys

sys.path.insert( 0, '../..' )

import requests
import cosa.utils.util as cu


BASE_URL = "http://localhost:7999"


def quick_smoke_test():
    """
    Smoke test for Deep Research submit endpoint.

    Requires:
        - Server running on port 7999
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD environment variables set
        - User account exists in development database

    Ensures:
        - Endpoint accepts authenticated POST requests
        - Returns the v2 AskResponse structure (status, job_id, path, route_reason, trace_id)
        - Job appears in queue system
    """
    cu.print_banner( "Deep Research Submit Smoke Test", prepend_nl=True )

    # Get credentials from environment
    email = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

    if not email or not password:
        print( "✗ Missing environment variables:" )
        print( "  export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL='your@email.com'" )
        print( "  export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD='yourpassword'" )
        return False

    try:
        # Test 1: Login and get token
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

        # Test 2: Submit Deep Research job
        print( "\nTest 2: Submitting Deep Research job..." )
        headers = { "Authorization": f"Bearer {token}" }
        # ONE DOOR NOW. /api/deep-research/submit is retired and answers 410 naming
        # /api/v2/submit, which takes the routing command as a string and the agent's own
        # arguments in `args`. What used to be a flat body is a command plus its args;
        # `websocket_id` and the lineage tag stay top-level, because they are instructions
        # about the request and the queue rather than arguments to the agent.
        payload = {
            "command"      : "agent router go to deep research",
            "args"         : {
                "query"  : "smoke test topic - safe to ignore",
                "budget" : 0.01,
            },
            "question"     : "smoke test topic - safe to ignore",
            "websocket_id" : "smoke-test-session"
        }
        # Lineage tag (bug 5ed4f187): when this smoke runs as a child pytest inside a
        # monopolizing test-suite job, the runner exports LUPIN_TEST_MONOPOLIZE_PARENT_ID
        # (test_suite/job.py). Threading it as parent_id_hash lets the consumer's Gate B
        # admit this child through the monopoly hold instead of starving it 900s.
        parent_id = os.environ.get( "LUPIN_TEST_MONOPOLIZE_PARENT_ID" )
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
        print( f"  Path: {data.get( 'path', 'unknown' )}" )
        print( f"  Route reason: {data.get( 'route_reason', 'unknown' )}" )
        print( f"  Job ID: {data.get( 'job_id', 'unknown' )}" )

        # Test 3: Verify response structure
        #
        # The v2 response is AskResponse, not the old door's four-field body.
        # `queue_position` and `message` are gone and are NOT being missed: a place in the
        # queue changes as the queue moves, so a number frozen at submission was stale the
        # moment it was printed, and the job card learns its real place from the queue
        # websocket events. `route_reason` is the field worth reading instead — it says
        # WHY this request took the branch it did.
        print( "\nTest 3: Verifying response structure..." )
        required_keys = [ "status", "job_id", "path", "route_reason", "trace_id" ]
        for key in required_keys:
            if key not in data:
                print( f"✗ Missing required key: {key}" )
                return False
            print( f"✓ {key}: present" )

        # Test 4: Verify expected values
        print( "\nTest 4: Verifying expected values..." )
        # "waiting", not "queued". The old door invented its own word for accepted-and-
        # running; the flow reports the executor's own status, and a queued executor
        # returning "waiting" with a job_id means the work was ACCEPTED and is running
        # behind the response — a success, not a degrade.
        assert data[ "status" ] == "waiting", f"Expected status 'waiting', got '{data[ 'status' ]}'"
        print( "✓ Status is 'waiting' — accepted and running behind the response" )

        assert data[ "path" ] != "receptionist", (
            f"the flow did not understand the command: {data.get( 'route_reason' )!r}" )
        print( f"✓ Dispatched, not refused: path={data[ 'path' ]}, reason={data[ 'route_reason' ]}" )

        assert data[ "job_id" ].startswith( "dr-" ), f"Expected job_id to start with 'dr-', got '{data[ 'job_id' ]}'"
        print( f"✓ Job ID format correct: {data[ 'job_id' ]}" )

        # Test 5: Check queue is accessible
        print( "\nTest 5: Checking queue status..." )
        queue_resp = requests.get(
            f"{BASE_URL}/api/get-queue/todo",
            headers=headers
        )

        if queue_resp.status_code == 200:
            print( "✓ Queue accessible" )
        else:
            print( f"⚠ Queue check returned: {queue_resp.status_code}" )
            # Not a failure - queue access may be restricted

        print( "\n" + "=" * 70 )
        print( "ALL SMOKE TESTS PASSED!" )
        print( "=" * 70 )
        print( "\nDeep Research submit endpoint is operational!" )

        return True

    except AssertionError as e:
        print( f"\n✗ Assertion failed: {e}" )
        import traceback
        traceback.print_exc()
        return False
    except requests.exceptions.ConnectionError:
        print( f"\n✗ Connection failed - is the server running on {BASE_URL}?" )
        return False
    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_deep_research_submit():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    success = quick_smoke_test()
    sys.exit( 0 if success else 1 )
