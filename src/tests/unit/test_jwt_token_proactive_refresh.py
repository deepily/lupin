"""
Unit tests for JWT token proactive refresh configuration endpoint.

Tests the /api/config/client endpoint that provides timing parameters
for client-side proactive token refresh functionality.

Created: 2025-10-17
"""

import pytest
from fastapi.testclient import TestClient
from lupin_app.main import app
from cosa.rest.auth import get_current_user, get_current_user_id
from cosa.rest.jwt_service import create_access_token
from cosa.config.configuration_manager import ConfigurationManager


MOCK_USER_ID = "test-config-endpoint-user-id"
MOCK_EMAIL   = "test_config_endpoint@example.com"


async def mock_get_current_user():
    """Return mock user dict without database lookup."""
    return { "id": MOCK_USER_ID, "email": MOCK_EMAIL, "roles": ["user"] }


async def mock_get_current_user_id():
    """Return mock user ID without database lookup."""
    return MOCK_USER_ID


@pytest.fixture
def test_client():
    """Create plain test client (no auth overrides) for 401 tests."""
    return TestClient( app )


@pytest.fixture
def authenticated_client():
    """Create test client with auth dependencies overridden for authenticated endpoint tests."""
    app.dependency_overrides[ get_current_user ]    = mock_get_current_user
    app.dependency_overrides[ get_current_user_id ] = mock_get_current_user_id
    client = TestClient( app )
    yield client
    app.dependency_overrides.clear()


class TestConfigEndpointAuthentication:
    """Test authentication requirements for config endpoint."""

    def test_endpoint_requires_authentication( self, test_client ):
        """
        Test that /api/config/client returns 401 without authentication.

        Ensures:
            - Endpoint is protected by JWT authentication
            - Returns 401 Unauthorized without valid token
            - Response includes appropriate error message
        """
        response = test_client.get( "/api/config/client" )

        assert response.status_code == 401
        assert "detail" in response.json()
        assert "credentials" in response.json()["detail"].lower() or \
               "unauthorized" in response.json()["detail"].lower()

    def test_endpoint_rejects_invalid_token( self, test_client ):
        """
        Test that endpoint rejects malformed/invalid tokens.

        Ensures:
            - Malformed tokens are rejected
            - Returns 401 Unauthorized
            - Does not expose internal errors
        """
        invalid_tokens = [
            "invalid_token",
            "Bearer invalid",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature",
            ""
        ]

        for token in invalid_tokens:
            response = test_client.get(
                "/api/config/client",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 401, \
                f"Expected 401 for invalid token: {token[:20]}..."


class TestConfigEndpointResponse:
    """Test response structure and values from config endpoint."""

    def test_endpoint_returns_correct_structure( self, authenticated_client ):
        """
        Test that endpoint returns all required fields.

        Ensures:
            - Response is JSON
            - Contains all 4 required timing parameters
            - All values are integers
            - Values are positive (non-zero)
        """
        response = authenticated_client.get( "/api/config/client" )

        assert response.status_code == 200
        data = response.json()

        # Check all required keys present
        required_keys = [
            "token_refresh_check_interval_ms",
            "token_expiry_threshold_secs",
            "token_refresh_dedup_window_ms",
            "websocket_heartbeat_interval_secs"
        ]

        for key in required_keys:
            assert key in data, f"Missing required key: {key}"
            assert isinstance( data[key], int ), \
                f"Value for {key} should be integer, got {type( data[key] )}"
            assert data[key] > 0, f"Value for {key} should be positive"

    def test_endpoint_returns_correct_values( self, authenticated_client ):
        """
        Test that endpoint returns expected configuration values.

        Ensures:
            - Values match baseline configuration (or fallback defaults)
            - Timing values are reasonable for production use
        """
        response = authenticated_client.get( "/api/config/client" )

        assert response.status_code == 200
        data = response.json()

        # Expected default values (from lupin-app.ini baseline or fallback)
        assert data["token_refresh_check_interval_ms"] == 600000  # 10 mins
        assert data["token_expiry_threshold_secs"] == 300         # 5 mins
        assert data["token_refresh_dedup_window_ms"] == 60000     # 60 secs
        assert data["websocket_heartbeat_interval_secs"] == 30    # 30 secs


class TestConfigUnitConversions:
    """Test mathematical correctness of unit conversions."""

    def test_interval_conversion_mins_to_ms( self, authenticated_client ):
        """
        Test: 10 minutes → 600000 milliseconds.

        Ensures:
            - Conversion from minutes to milliseconds is correct
            - 10 mins * 60 secs/min * 1000 ms/sec = 600000 ms
        """
        response = authenticated_client.get( "/api/config/client" )
        data = response.json()

        # Verify conversion: 10 mins = 600000 ms
        expected_ms = 10 * 60 * 1000
        assert data["token_refresh_check_interval_ms"] == expected_ms

    def test_threshold_conversion_mins_to_secs( self, authenticated_client ):
        """
        Test: 5 minutes → 300 seconds.

        Ensures:
            - Conversion from minutes to seconds is correct
            - 5 mins * 60 secs/min = 300 secs
        """
        response = authenticated_client.get( "/api/config/client" )
        data = response.json()

        # Verify conversion: 5 mins = 300 secs
        expected_secs = 5 * 60
        assert data["token_expiry_threshold_secs"] == expected_secs

    def test_dedup_conversion_secs_to_ms( self, authenticated_client ):
        """
        Test: 60 seconds → 60000 milliseconds.

        Ensures:
            - Conversion from seconds to milliseconds is correct
            - 60 secs * 1000 ms/sec = 60000 ms
        """
        response = authenticated_client.get( "/api/config/client" )
        data = response.json()

        # Verify conversion: 60 secs = 60000 ms
        expected_ms = 60 * 1000
        assert data["token_refresh_dedup_window_ms"] == expected_ms


if __name__ == "__main__":
    import sys
    sys.path.insert( 0, '../..' )
    pytest.main( [__file__, "-v", "-s"] )
