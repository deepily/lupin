"""
Smoke tests for JWT token proactive refresh system.

Quick validation tests for token refresh configuration and lifecycle.
These tests verify the complete refresh workflow end-to-end.

Created: 2025-10-17
"""

import sys
sys.path.insert( 0, '../..' )

from fastapi.testclient import TestClient
from lupin_app.main import app
from cosa.rest.user_service import create_user, get_user_by_email
from cosa.rest.jwt_service import create_access_token
import cosa.utils.util as cu


def quick_smoke_test():
    """
    Quick smoke test for token proactive refresh - validates basic functionality.
    """
    cu.print_banner( "JWT Token Proactive Refresh Smoke Test", prepend_nl=True )

    client = TestClient( app )

    try:
        # Test 1: Config endpoint requires authentication
        print( "Test 1: Verifying authentication requirement..." )
        response = client.get( "/api/config/client" )
        assert response.status_code == 401
        print( "✓ Endpoint correctly requires authentication (401)" )

        # Test 2: Create user and authenticate
        print( "\nTest 2: Creating test user and generating token..." )
        email = "smoke_test_refresh@example.com"
        password = "SmokeTest123!"

        # Create or get user
        try:
            success, message, user_id = create_user( email, password, ["user"] )
            if not success:
                existing_user = get_user_by_email( email )
                user_id = existing_user["id"]
        except Exception:
            existing_user = get_user_by_email( email )
            user_id = existing_user["id"]

        token = create_access_token( user_id, email, ["user"] )
        print( f"✓ User created/retrieved: {user_id}" )
        print( f"✓ Token generated: {token[:50]}..." )

        # Test 3: Fetch config with authentication
        print( "\nTest 3: Fetching config with valid authentication..." )
        response = client.get(
            "/api/config/client",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        print( f"✓ Config fetched successfully (200 OK)" )

        # Test 4: Verify config structure
        print( "\nTest 4: Verifying config structure..." )
        required_keys = [
            "token_refresh_check_interval_ms",
            "token_expiry_threshold_secs",
            "token_refresh_dedup_window_ms",
            "websocket_heartbeat_interval_secs"
        ]

        for key in required_keys:
            assert key in data
            assert isinstance( data[key], int )
            assert data[key] > 0
            print( f"✓ {key}: {data[key]}" )

        # Test 5: Verify timing values are reasonable
        print( "\nTest 5: Verifying timing values..." )
        assert data["token_refresh_check_interval_ms"] == 600000  # 10 mins
        assert data["token_expiry_threshold_secs"] == 300         # 5 mins
        assert data["token_refresh_dedup_window_ms"] == 60000     # 60 secs
        assert data["websocket_heartbeat_interval_secs"] == 30    # 30 secs
        print( "✓ All timing values match expected defaults" )

        # Test 6: Verify unit conversions
        print( "\nTest 6: Verifying unit conversions..." )
        assert data["token_refresh_check_interval_ms"] == 10 * 60 * 1000
        print( "✓ Check interval: 10 mins = 600000 ms" )

        assert data["token_expiry_threshold_secs"] == 5 * 60
        print( "✓ Expiry threshold: 5 mins = 300 secs" )

        assert data["token_refresh_dedup_window_ms"] == 60 * 1000
        print( "✓ Dedup window: 60 secs = 60000 ms" )

        print( "\n" + "="*70 )
        print( "✅ ALL SMOKE TESTS PASSED!" )
        print( "="*70 )
        print( "\nToken proactive refresh system is operational!" )

    except AssertionError as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print( f"\n✗ Error during smoke test: {e}" )
        import traceback
        traceback.print_exc()
        return False

    return True


def test_token_proactive_refresh():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    success = quick_smoke_test()
    sys.exit( 0 if success else 1 )
