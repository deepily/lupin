#!/usr/bin/env python3
"""
Smoke Test for SSE Response-Required Notifications (Phase 2.1).

Quick end-to-end test of response-required notification flow:
- Fire-and-forget mode (backward compatibility)
- Response-required with timeout
- Response submission endpoint
- Offline detection with defaults

Run: python src/tests/smoke/test_notifications_sse_smoke.py
"""

import sys
import os
import requests
import json
import time
from threading import Thread

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
BASE_URL = "http://localhost:7999"
API_KEY  = "claude_code_simple_key"
TEST_USER = "ricardo.felipe.ruiz@gmail.com"  # Default test user (must exist in user database)


def print_test_header( test_name ):
    """Print formatted test header."""
    print( f"\n{'=' * 60}" )
    print( f"  {test_name}" )
    print( f"{'=' * 60}" )


def test_fire_and_forget_mode():
    """
    Test 1: Fire-and-forget mode (existing behavior).

    Ensures backward compatibility - notifications without response_requested
    should work as before.
    """
    print_test_header( "Test 1: Fire-and-Forget Mode" )

    try:
        response = requests.post(
            f"{BASE_URL}/api/notify",
            params={
                "message"     : "Smoke test fire-and-forget notification",
                "type"        : "task",
                "priority"    : "low",
                "target_user" : TEST_USER,
                "api_key"     : API_KEY
            },
            timeout=5
        )

        print( f"Status Code: {response.status_code}" )
        data = response.json()
        print( f"Response: {json.dumps(data, indent=2)}" )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert "status" in data, "Response missing 'status' field"
        assert data["status"] in ["queued", "user_not_available"], f"Unexpected status: {data['status']}"

        print( "✓ Fire-and-forget mode works" )
        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_response_required_validation():
    """
    Test 2: Response-required validation.

    Tests that response_type is required when response_requested=True.
    """
    print_test_header( "Test 2: Response-Required Validation" )

    try:
        # Test missing response_type
        response = requests.post(
            f"{BASE_URL}/api/notify",
            params={
                "message"           : "Test notification",
                "type"              : "task",
                "priority"          : "high",
                "target_user"       : TEST_USER,
                "api_key"           : API_KEY,
                "response_requested": True
                # Missing response_type
            },
            timeout=5
        )

        print( f"Status Code: {response.status_code}" )
        data = response.json()
        print( f"Response: {json.dumps(data, indent=2)}" )

        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert "response_type is required" in data["detail"], "Wrong error message"

        print( "✓ Validation works - response_type required" )

        # Test invalid response_type
        response = requests.post(
            f"{BASE_URL}/api/notify",
            params={
                "message"           : "Test notification",
                "type"              : "task",
                "priority"          : "high",
                "target_user"       : TEST_USER,
                "api_key"           : API_KEY,
                "response_requested": True,
                "response_type"     : "invalid_type"
            },
            timeout=5
        )

        print( f"\nInvalid type - Status Code: {response.status_code}" )
        data = response.json()
        print( f"Response: {json.dumps(data, indent=2)}" )

        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert "Invalid response_type" in data["detail"], "Wrong error message"

        print( "✓ Validation works - invalid response_type rejected" )
        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_offline_with_default():
    """
    Test 3: Offline detection with default response.

    Tests that when user is offline and default provided, system returns
    immediately without creating SSE stream.

    Note: This test assumes user is offline. If user is online, test will
    show different behavior (which is also valid).
    """
    print_test_header( "Test 3: Offline Detection with Default" )

    try:
        response = requests.post(
            f"{BASE_URL}/api/notify",
            params={
                "message"           : "Smoke test offline with default",
                "type"              : "task",
                "priority"          : "high",
                "target_user"       : TEST_USER,
                "api_key"           : API_KEY,
                "response_requested": True,
                "response_type"     : "yes_no",
                "response_default"  : "no"
            },
            timeout=5
        )

        print( f"Status Code: {response.status_code}" )

        # Response depends on whether user is online or offline
        if response.status_code == 200:
            # Check if it's JSON (offline) or SSE stream (online)
            content_type = response.headers.get( 'content-type', '' )

            if 'application/json' in content_type:
                # Offline path - returned default immediately
                data = response.json()
                print( f"Response (offline): {json.dumps(data, indent=2)}" )
                assert data["status"] == "offline", f"Expected 'offline', got '{data['status']}'"
                assert data["default_used"] == "no", f"Expected default 'no', got '{data['default_used']}'"
                print( "✓ Offline detection works - returned default immediately" )

            elif 'text/event-stream' in content_type:
                # Online path - created SSE stream
                print( "Response: SSE stream created (user is online)" )
                print( "✓ User is online - SSE stream created (expected behavior)" )
                print( "   (To test offline path, ensure user is not connected via WebSocket)" )
            else:
                print( f"✗ Unexpected content-type: {content_type}" )
                return False

        else:
            print( f"✗ Unexpected status code: {response.status_code}" )
            print( f"Response: {response.text}" )
            return False

        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_response_submission():
    """
    Test 4: Response submission endpoint.

    Tests POST /api/notify/response endpoint with various scenarios.
    """
    print_test_header( "Test 4: Response Submission Endpoint" )

    try:
        # Test 1: Non-existent notification
        response = requests.post(
            f"{BASE_URL}/api/notify/response",
            params={"notification_id": "nonexistent-uuid-12345"},
            json={"answer": "yes"},
            timeout=5
        )

        print( f"Non-existent notification - Status Code: {response.status_code}" )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print( "✓ Non-existent notification returns 404" )

        # Test 2: Invalid API structure (missing notification_id)
        response = requests.post(
            f"{BASE_URL}/api/notify/response",
            json={"answer": "yes"},
            timeout=5
        )

        print( f"\nMissing notification_id - Status Code: {response.status_code}" )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print( "✓ Missing notification_id returns 422 (validation error)" )

        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_api_key_validation():
    """
    Test 5: API key validation.

    Tests that invalid API keys are rejected.
    """
    print_test_header( "Test 5: API Key Validation" )

    try:
        response = requests.post(
            f"{BASE_URL}/api/notify",
            params={
                "message"     : "Test notification",
                "type"        : "task",
                "priority"    : "medium",
                "target_user" : TEST_USER,
                "api_key"     : "wrong_key_12345"
            },
            timeout=5
        )

        print( f"Status Code: {response.status_code}" )
        data = response.json()
        print( f"Response: {json.dumps(data, indent=2)}" )

        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        assert "Invalid API key" in data["detail"], "Wrong error message"

        print( "✓ Invalid API key rejected" )
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
    cu.print_banner( "SSE Notifications Smoke Test Suite", prepend_nl=True )

    print( f"\nTarget Server: {BASE_URL}" )
    print( f"Test User: {TEST_USER}" )
    print( f"\nNOTE: Server must be running on {BASE_URL}" )
    print( "      Start with: src/scripts/run-fastapi-lupin.sh\n" )

    # Check if server is running
    try:
        response = requests.get( f"{BASE_URL}/health", timeout=2 )
        print( f"✓ Server is running (health check: {response.status_code})\n" )
    except Exception as e:
        print( f"✗ Server not responding: {e}" )
        print( "\nPlease start the server with: src/scripts/run-fastapi-lupin.sh\n" )
        return 1

    # Run tests
    results = []

    results.append( ("Fire-and-Forget Mode", test_fire_and_forget_mode()) )
    results.append( ("Response-Required Validation", test_response_required_validation()) )
    results.append( ("Offline Detection with Default", test_offline_with_default()) )
    results.append( ("Response Submission Endpoint", test_response_submission()) )
    results.append( ("API Key Validation", test_api_key_validation()) )

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
    print( f"Total: {passed} passed, {failed} failed out of {len(results)} tests" )
    print( f"{'=' * 60}\n" )

    if failed > 0:
        print( "✗ Some tests failed" )
        return 1
    else:
        print( "✓ All tests passed successfully" )
        return 0


if __name__ == "__main__":
    sys.exit( run_all_tests() )
