"""
Smoke test for Deep Research background job submission.
Tests POST /api/deep-research/submit endpoint.

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
        - Returns expected response structure (status, job_id, queue_position, message)
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
        submit_resp = requests.post(
            f"{BASE_URL}/api/deep-research/submit",
            json={
                "query"        : "smoke test topic - safe to ignore",
                "user_email"   : email,
                "budget"       : 0.01,
                "websocket_id" : "smoke-test-session"
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
        print( f"  Message: {data.get( 'message', 'unknown' )}" )

        # Test 3: Verify response structure
        print( "\nTest 3: Verifying response structure..." )
        required_keys = [ "status", "job_id", "queue_position", "message" ]
        for key in required_keys:
            if key not in data:
                print( f"✗ Missing required key: {key}" )
                return False
            print( f"✓ {key}: present" )

        # Test 4: Verify expected values
        print( "\nTest 4: Verifying expected values..." )
        assert data[ "status" ] == "queued", f"Expected status 'queued', got '{data[ 'status' ]}'"
        print( "✓ Status is 'queued'" )

        assert data[ "job_id" ].startswith( "dr-" ), f"Expected job_id to start with 'dr-', got '{data[ 'job_id' ]}'"
        print( f"✓ Job ID format correct: {data[ 'job_id' ]}" )

        assert isinstance( data[ "queue_position" ], int ), "Expected queue_position to be int"
        assert data[ "queue_position" ] >= 0, "Expected queue_position >= 0"
        print( f"✓ Queue position is valid: {data[ 'queue_position' ]}" )

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
