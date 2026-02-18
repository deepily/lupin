#!/usr/bin/env python3
"""
Smoke Test for Progress Group Notifications.

End-to-end test of progress_group_id notification grouping:
- Single notification with progress_group_id accepted
- Multi-step progress series with same group ID
- Mixed grouped + standalone notifications
- Grouped notifications with job_id (job card path)
- Backward compatibility (no progress_group_id)

Requires environment variables:
    LUPIN_TEST_EMAIL    - Email for login
    LUPIN_TEST_PASSWORD - Password for login

Run: python src/tests/smoke/test_notifications_progress_group_smoke.py
"""

import sys
import os
import requests
import json
import time

# Bootstrap imports
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    print( "ERROR: LUPIN_ROOT environment variable not set" )
    sys.exit( 1 )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu


# Configuration
BASE_URL     = "http://127.0.0.1:7999"
REQ_TIMEOUT  = 15  # seconds — server can be slow under load


def print_test_header( test_name ):
    """Print formatted test header."""
    print( f"\n{'=' * 60}" )
    print( f"  {test_name}" )
    print( f"{'=' * 60}" )


def login_and_get_auth():
    """
    Login with LUPIN_TEST_EMAIL / LUPIN_TEST_PASSWORD and return auth header + email.

    Requires:
        - LUPIN_TEST_EMAIL and LUPIN_TEST_PASSWORD environment variables set
        - Server running on BASE_URL

    Ensures:
        - Returns ( auth_header_dict, test_user_email ) on success
        - Returns ( None, None ) on failure

    Raises:
        - Prints error details to stdout on failure
    """
    email    = os.environ.get( "LUPIN_TEST_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_PASSWORD" )

    if not email or not password:
        print( "✗ Missing environment variables:" )
        print( "  export LUPIN_TEST_EMAIL='your@email.com'" )
        print( "  export LUPIN_TEST_PASSWORD='yourpassword'" )
        return None, None

    try:
        print( f"Logging in as {email}..." )
        login_resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={ "email": email, "password": password },
            timeout=REQ_TIMEOUT
        )

        if login_resp.status_code != 200:
            print( f"✗ Login failed: {login_resp.status_code}" )
            print( f"  Response: {login_resp.text[ :200 ]}" )
            return None, None

        token = login_resp.json()[ "tokens" ][ "access_token" ]
        print( f"✓ Login successful, token: {token[ :30 ]}..." )

        auth_header = { "Authorization": f"Bearer {token}" }
        return auth_header, email

    except Exception as e:
        print( f"✗ Login error: {e}" )
        return None, None


def _run_valid_progress_group_id( auth_header, test_user ):
    """
    Test 1: Single notification with progress_group_id.

    Ensures:
        - HTTP 200 for a notification carrying pg-a1b2c3d4
        - Response contains 'status' field
    """
    print_test_header( "Test 1: Valid progress_group_id" )

    try:
        response = requests.post(
            f"{BASE_URL}/api/notify",
            headers=auth_header,
            params={
                "message"           : "[Smoke] Single grouped notification",
                "type"              : "progress",
                "priority"          : "low",
                "target_user"       : test_user,
                "progress_group_id" : "pg-a1b2c3d4"
            },
            timeout=REQ_TIMEOUT
        )

        print( f"Status Code: {response.status_code}" )
        data = response.json()
        print( f"Response: {json.dumps( data, indent=2 )}" )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert "status" in data, "Response missing 'status' field"

        print( "✓ Single progress_group_id notification accepted" )
        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def _run_five_step_progress_series( auth_header, test_user ):
    """
    Test 2: 5-step progress series with same progress_group_id.

    Ensures:
        - All 5 notifications return HTTP 200
        - 0.5s delay between each so frontend animation is visible
        - Frontend should show single in-place element with counter badge
    """
    print_test_header( "Test 2: 5-Step Progress Series" )

    group_id = "pg-smoke5001"

    try:
        for step in range( 1, 6 ):
            response = requests.post(
                f"{BASE_URL}/api/notify",
                headers=auth_header,
                params={
                    "message"           : f"[Smoke] Step {step}/5: Processing batch {step * 20}%",
                    "type"              : "progress",
                    "priority"          : "low",
                    "target_user"       : test_user,
                    "progress_group_id" : group_id
                },
                timeout=REQ_TIMEOUT
            )

            print( f"  Step {step}/5 — Status: {response.status_code}" )
            assert response.status_code == 200, f"Step {step}: Expected 200, got {response.status_code}"

            if step < 5:
                time.sleep( 0.5 )

        print( "✓ All 5 progress steps accepted with same group ID" )
        print( "  → Frontend should show 1 element with #5 counter badge" )
        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def _run_mixed_grouped_and_standalone( auth_header, test_user ):
    """
    Test 3: Mixed grouped + standalone notifications.

    Ensures:
        - 2 standalone (no group) + 2 grouped (same ID) all return HTTP 200
        - Frontend should show 3 visible elements (2 standalone + 1 grouped)
    """
    print_test_header( "Test 3: Mixed Grouped + Standalone" )

    group_id = "pg-smoke3001"

    try:
        # Standalone 1
        r1 = requests.post(
            f"{BASE_URL}/api/notify",
            headers=auth_header,
            params={
                "message"     : "[Smoke] Standalone notification A",
                "type"        : "task",
                "priority"    : "low",
                "target_user" : test_user
            },
            timeout=REQ_TIMEOUT
        )
        print( f"  Standalone A — Status: {r1.status_code}" )
        assert r1.status_code == 200, f"Standalone A: Expected 200, got {r1.status_code}"

        time.sleep( 0.5 )

        # Grouped 1
        r2 = requests.post(
            f"{BASE_URL}/api/notify",
            headers=auth_header,
            params={
                "message"           : "[Smoke] Grouped step 1/2",
                "type"              : "progress",
                "priority"          : "low",
                "target_user"       : test_user,
                "progress_group_id" : group_id
            },
            timeout=REQ_TIMEOUT
        )
        print( f"  Grouped 1/2  — Status: {r2.status_code}" )
        assert r2.status_code == 200, f"Grouped 1: Expected 200, got {r2.status_code}"

        time.sleep( 0.5 )

        # Standalone 2
        r3 = requests.post(
            f"{BASE_URL}/api/notify",
            headers=auth_header,
            params={
                "message"     : "[Smoke] Standalone notification B",
                "type"        : "task",
                "priority"    : "low",
                "target_user" : test_user
            },
            timeout=REQ_TIMEOUT
        )
        print( f"  Standalone B — Status: {r3.status_code}" )
        assert r3.status_code == 200, f"Standalone B: Expected 200, got {r3.status_code}"

        time.sleep( 0.5 )

        # Grouped 2
        r4 = requests.post(
            f"{BASE_URL}/api/notify",
            headers=auth_header,
            params={
                "message"           : "[Smoke] Grouped step 2/2",
                "type"              : "progress",
                "priority"          : "low",
                "target_user"       : test_user,
                "progress_group_id" : group_id
            },
            timeout=REQ_TIMEOUT
        )
        print( f"  Grouped 2/2  — Status: {r4.status_code}" )
        assert r4.status_code == 200, f"Grouped 2: Expected 200, got {r4.status_code}"

        print( "✓ All 4 notifications accepted (2 standalone + 2 grouped)" )
        print( "  → Frontend should show 3 visible elements" )
        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def _run_with_job_id( auth_header, test_user ):
    """
    Test 4: Grouped notifications with job_id (job card activity log path).

    Ensures:
        - 3 notifications with both job_id and progress_group_id return HTTP 200
        - Tests the job card activity log in-place update path
    """
    print_test_header( "Test 4: With job_id (Job Card Path)" )

    group_id = "pg-smoke4001"
    job_id   = "dr-smoke4001"

    try:
        for step in range( 1, 4 ):
            response = requests.post(
                f"{BASE_URL}/api/notify",
                headers=auth_header,
                params={
                    "message"           : f"[Smoke] Job card step {step}/3: Analyzing chunk {step}",
                    "type"              : "progress",
                    "priority"          : "low",
                    "target_user"       : test_user,
                    "progress_group_id" : group_id,
                    "job_id"            : job_id
                },
                timeout=REQ_TIMEOUT
            )

            print( f"  Step {step}/3 — Status: {response.status_code}" )
            assert response.status_code == 200, f"Step {step}: Expected 200, got {response.status_code}"

            if step < 3:
                time.sleep( 0.5 )

        print( "✓ All 3 job-card grouped notifications accepted" )
        print( f"  → Job card {job_id} should show in-place updates" )
        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def _run_backward_compat_no_group( auth_header, test_user ):
    """
    Test 5: Backward compatibility — no progress_group_id.

    Ensures:
        - 3 notifications without progress_group_id all return HTTP 200
        - Confirms existing append behavior is unchanged
    """
    print_test_header( "Test 5: Backward Compat (No Group)" )

    try:
        for i in range( 1, 4 ):
            response = requests.post(
                f"{BASE_URL}/api/notify",
                headers=auth_header,
                params={
                    "message"     : f"[Smoke] Ungrouped notification {i}/3",
                    "type"        : "task",
                    "priority"    : "low",
                    "target_user" : test_user
                },
                timeout=REQ_TIMEOUT
            )

            print( f"  Notification {i}/3 — Status: {response.status_code}" )
            assert response.status_code == 200, f"Notification {i}: Expected 200, got {response.status_code}"

            if i < 3:
                time.sleep( 0.5 )

        print( "✓ All 3 ungrouped notifications accepted (normal append)" )
        print( "  → Frontend should show 3 separate elements" )
        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """
    Run all smoke tests and report results.

    Ensures:
        - Returns 0 if all tests pass
        - Returns 1 if any test fails
    """
    cu.print_banner( "Progress Group Notifications Smoke Test Suite", prepend_nl=True )

    print( f"\nTarget Server: {BASE_URL}" )
    print( f"\nNOTE: Server must be running on {BASE_URL}" )
    print( "      Start with: src/scripts/run-fastapi-lupin.sh\n" )

    # Health check
    try:
        response = requests.get( f"{BASE_URL}/health", timeout=REQ_TIMEOUT )
        print( f"✓ Server is running (health check: {response.status_code})\n" )
    except Exception as e:
        print( f"✗ Server not responding: {e}" )
        print( "\nPlease start the server with: src/scripts/run-fastapi-lupin.sh\n" )
        return 1

    # Authenticate
    auth_header, test_user = login_and_get_auth()
    if auth_header is None:
        return 1

    print( f"Test User: {test_user}\n" )

    # Run tests
    results = []

    results.append( ( "Valid progress_group_id",       _run_valid_progress_group_id( auth_header, test_user ) ) )
    results.append( ( "5-Step Progress Series",        _run_five_step_progress_series( auth_header, test_user ) ) )
    results.append( ( "Mixed Grouped + Standalone",    _run_mixed_grouped_and_standalone( auth_header, test_user ) ) )
    results.append( ( "With job_id (Job Card Path)",   _run_with_job_id( auth_header, test_user ) ) )
    results.append( ( "Backward Compat (No Group)",    _run_backward_compat_no_group( auth_header, test_user ) ) )

    # Summary
    print( f"\n{'=' * 60}" )
    print( "  Test Results Summary" )
    print( f"{'=' * 60}\n" )

    passed = sum( 1 for _, result in results if result )
    failed = len( results ) - passed

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print( f"{status:10} | {test_name}" )

    print( f"\n{'=' * 60}" )
    print( f"Total: {passed} passed, {failed} failed out of {len( results )} tests" )
    print( f"{'=' * 60}\n" )

    if failed > 0:
        print( "✗ Some tests failed" )
        return 1
    else:
        print( "✓ All tests passed successfully" )
        return 0


def quick_smoke_test():
    """
    Quick smoke test for progress group notifications.

    Requires:
        - Server running on BASE_URL (localhost:7999)
        - LUPIN_TEST_EMAIL and LUPIN_TEST_PASSWORD environment variables set

    Ensures:
        - Returns True if all 5 notification tests pass
        - Returns False on any failure or connection error
    """
    return run_all_tests() == 0


def test_notifications_progress_group():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    sys.exit( run_all_tests() )
