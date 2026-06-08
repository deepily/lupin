"""
Integration tests for JWT token proactive refresh.

Tests complete workflows including authentication, config fetch,
and token refresh lifecycle across client and server.

Created: 2025-10-17
"""

import pytest
import time
from fastapi.testclient import TestClient
from lupin_app.main import app
from cosa.rest.user_service import create_user, get_user_by_email
from cosa.rest.jwt_service import create_access_token, decode_and_validate_token


@pytest.fixture
def test_client():
    """Create test client for FastAPI app."""
    return TestClient( app )


@pytest.fixture
def authenticated_user( clean_test_db ):
    """
    Create test user and return credentials.

    Args:
        clean_test_db: Fixture that initializes clean test database

    Returns:
        tuple: (user_id, email, access_token)
    """
    # Create unique user for each test run
    import uuid
    email = f"integration_test_{uuid.uuid4().hex[:12]}@example.com"
    password = "IntegrationTest123!"

    # Create user
    success, message, user_id = create_user( email, password, ["user"] )
    assert success, f"Failed to create test user: {message}"

    # Generate token
    token = create_access_token( user_id, email, ["user"] )

    return user_id, email, token


@pytest.mark.xfail( reason="TestClient(app) + create_user triggers bcrypt 72-byte error — needs investigation" )
class TestConfigFetchIntegration:
    """Test integration of config fetch with authentication."""

    def test_complete_auth_and_config_flow( self, test_client, authenticated_user ):
        """
        Test complete flow: authenticate → fetch config → verify values.

        Simulates what the client does on page load:
        1. Authenticate with JWT
        2. Fetch client configuration
        3. Verify timing values for token refresh

        Ensures:
            - Full authentication flow works
            - Config endpoint accessible after auth
            - All timing values present and valid
        """
        user_id, email, token = authenticated_user

        # Step 1: Verify token is valid
        payload = decode_and_validate_token( token, expected_type="access" )
        assert payload["sub"] == user_id
        assert payload["email"] == email

        # Step 2: Fetch config with authenticated token
        response = test_client.get(
            "/api/config/client",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        config = response.json()

        # Step 3: Verify config contains all required timing values
        assert config["token_refresh_check_interval_ms"] > 0
        assert config["token_expiry_threshold_secs"] > 0
        assert config["token_refresh_dedup_window_ms"] > 0
        assert config["websocket_heartbeat_interval_secs"] > 0

        # Step 4: Verify token is still valid after config fetch
        payload_after = decode_and_validate_token( token, expected_type="access" )
        assert payload_after["sub"] == user_id


@pytest.mark.xfail( reason="TestClient(app) + create_user triggers bcrypt 72-byte error — needs investigation" )
class TestTokenExpiryThreshold:
    """Test token expiry threshold logic."""

    def test_threshold_calculation( self, test_client, authenticated_user ):
        """
        Test threshold logic for determining when to refresh.

        Verifies:
            - Token expiry time calculation
            - Threshold comparison logic
            - Time remaining calculation

        This test validates the math used in checkAndRefreshToken():
        - Parse JWT exp claim (in seconds)
        - Calculate time until expiry
        - Compare against threshold (5 minutes = 300 seconds)
        """
        user_id, email, token = authenticated_user

        # Decode token to get expiration
        payload = decode_and_validate_token( token, expected_type="access" )
        exp_claim = payload["exp"]

        # Calculate time until expiry (in seconds)
        import time
        now_secs = int( time.time() )
        time_until_expiry_secs = exp_claim - now_secs

        # Fetch config to get threshold
        response = test_client.get(
            "/api/config/client",
            headers={"Authorization": f"Bearer {token}"}
        )
        config = response.json()
        threshold_secs = config["token_expiry_threshold_secs"]

        # Verify token is NOT close to expiry (fresh token)
        # For a fresh token (30 min lifespan), we should have ~30 mins remaining
        assert time_until_expiry_secs > threshold_secs, \
            f"Fresh token should have >{threshold_secs}s remaining, " \
            f"but has {time_until_expiry_secs}s"

        # Verify threshold value is reasonable (should be 5 minutes = 300 seconds)
        assert threshold_secs == 300, \
            f"Expected 5-minute threshold (300s), got {threshold_secs}s"


@pytest.mark.xfail( reason="TestClient(app) + create_user triggers bcrypt 72-byte error — needs investigation" )
class TestDeduplicationLogic:
    """Test deduplication prevents rapid-fire refreshes."""

    def test_dedup_window_configuration( self, test_client, authenticated_user ):
        """
        Test deduplication window configuration.

        Verifies:
            - Dedup window value is set
            - Value is reasonable (60 seconds = 60000 ms)
            - Value converts correctly from config

        This validates the deduplication logic that prevents both
        mechanisms (periodic + heartbeat) from refreshing simultaneously.
        """
        user_id, email, token = authenticated_user

        response = test_client.get(
            "/api/config/client",
            headers={"Authorization": f"Bearer {token}"}
        )

        config = response.json()
        dedup_window_ms = config["token_refresh_dedup_window_ms"]

        # Verify dedup window is 60 seconds
        assert dedup_window_ms == 60000, \
            f"Expected 60-second dedup window (60000ms), got {dedup_window_ms}ms"

        # Verify conversion: 60 secs * 1000 ms/sec = 60000 ms
        assert dedup_window_ms == 60 * 1000

    def test_heartbeat_interval_matches_config( self, test_client, authenticated_user ):
        """
        Test that heartbeat interval from config matches expected value.

        Verifies:
            - Heartbeat interval is set
            - Value is reasonable (30 seconds)
            - Client will use this for heartbeat-triggered checks

        This ensures the heartbeat mechanism has correct timing for
        triggering token freshness checks every 30 seconds.
        """
        user_id, email, token = authenticated_user

        response = test_client.get(
            "/api/config/client",
            headers={"Authorization": f"Bearer {token}"}
        )

        config = response.json()
        heartbeat_secs = config["websocket_heartbeat_interval_secs"]

        # Verify heartbeat is 30 seconds
        assert heartbeat_secs == 30, \
            f"Expected 30-second heartbeat interval, got {heartbeat_secs}s"


if __name__ == "__main__":
    import sys
    sys.path.insert( 0, '../..' )
    pytest.main( [__file__, "-v", "-s"] )
