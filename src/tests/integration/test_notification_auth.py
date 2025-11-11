"""
Integration tests for notification endpoint authentication.

Tests the complete authentication flow from API request through middleware
to database validation. Requires running FastAPI server.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
"""

import pytest
import requests
import bcrypt
import secrets
from datetime import datetime

from cosa.rest.auth_database import get_auth_db_connection


@pytest.fixture
def test_api_key( clean_test_db ):
    """Create a test API key and store its hash in the database."""
    # Generate test API key
    api_key = "ck_live_" + secrets.token_urlsafe( 48 )

    # Hash the key
    key_bytes = api_key.encode( 'utf-8' )
    salt = bcrypt.gensalt( rounds=12 )
    key_hash = bcrypt.hashpw( key_bytes, salt ).decode( 'utf-8' )

    # Create test service account (api_keys table created by clean_test_db)
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    # Create user
    import uuid
    import json
    user_id = str( uuid.uuid4() )
    email = f"test-{user_id}@test.com"

    cursor.execute(
        """
        INSERT INTO users ( id, email, password_hash, created_at, roles, is_active, email_verified )
        VALUES ( ?, ?, ?, ?, ?, ?, ? )
        """,
        (
            user_id,
            email,
            "dummy_hash",
            datetime.utcnow().isoformat(),
            json.dumps( ['service_account'] ),
            1,
            1
        )
    )

    # Create API key
    cursor.execute(
        """
        INSERT INTO api_keys ( user_id, key_hash, description, created_at, is_active )
        VALUES ( ?, ?, ?, ?, ? )
        """,
        (
            user_id,
            key_hash,
            "Integration test key",
            datetime.utcnow().isoformat(),
            1
        )
    )

    conn.commit()
    key_id = cursor.lastrowid
    conn.close()

    yield {
        'api_key': api_key,
        'user_id': user_id,
        'key_id': key_id,
        'email': email
    }

    # Cleanup
    conn = get_auth_db_connection()
    cursor = conn.cursor()
    cursor.execute( "DELETE FROM api_keys WHERE id = ?", ( key_id, ) )
    cursor.execute( "DELETE FROM users WHERE id = ?", ( user_id, ) )
    conn.commit()
    conn.close()


class TestNotificationAuthentication:
    """Integration tests for notification endpoint authentication."""

    BASE_URL = "http://localhost:7999"

    def test_valid_api_key_allows_access( self, test_api_key ):
        """Test that valid API key allows notification to be sent."""
        response = requests.post(
            f"{self.BASE_URL}/api/notify",
            params={
                'message': 'Integration test notification',
                'type': 'task',
                'priority': 'low',
                'target_user': test_api_key['email']
            },
            headers={
                'X-API-Key': test_api_key['api_key']
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data['status'] in ['queued', 'user_not_available']

    def test_invalid_api_key_returns_401( self ):
        """Test that invalid API key returns 401 Unauthorized."""
        invalid_key = "ck_live_" + "X" * 64

        response = requests.post(
            f"{self.BASE_URL}/api/notify",
            params={
                'message': 'Should fail',
                'type': 'task',
                'priority': 'low'
            },
            headers={
                'X-API-Key': invalid_key
            }
        )

        assert response.status_code == 401
        data = response.json()
        assert 'Invalid or inactive API key' in data['detail']

    def test_missing_api_key_returns_401( self ):
        """Test that missing API key returns 401 Unauthorized."""
        response = requests.post(
            f"{self.BASE_URL}/api/notify",
            params={
                'message': 'Should fail',
                'type': 'task',
                'priority': 'low'
            }
            # No X-API-Key header
        )

        assert response.status_code == 401
        data = response.json()
        assert 'Missing API key' in data['detail']

    def test_invalid_format_returns_401( self ):
        """Test that invalid API key format returns 401."""
        invalid_keys = [
            'invalid_key',
            'ck_test_' + 'A' * 64,  # Wrong prefix
            'ck_live_' + 'A' * 63,  # Too short
            'ck_live_ABC!@#',        # Invalid characters
        ]

        for invalid_key in invalid_keys:
            response = requests.post(
                f"{self.BASE_URL}/api/notify",
                params={
                    'message': 'Should fail',
                    'type': 'task',
                    'priority': 'low'
                },
                headers={
                    'X-API-Key': invalid_key
                }
            )

            assert response.status_code == 401, f"Expected 401 for key: {invalid_key}"
            data = response.json()
            assert 'Invalid API key format' in data['detail']

    def test_inactive_api_key_returns_401( self, test_api_key ):
        """Test that inactive API key returns 401."""
        # Deactivate the test key
        conn = get_auth_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE api_keys SET is_active = 0 WHERE id = ?",
            ( test_api_key['key_id'], )
        )
        conn.commit()
        conn.close()

        # Try to use inactive key
        response = requests.post(
            f"{self.BASE_URL}/api/notify",
            params={
                'message': 'Should fail',
                'type': 'task',
                'priority': 'low'
            },
            headers={
                'X-API-Key': test_api_key['api_key']
            }
        )

        assert response.status_code == 401
        data = response.json()
        assert 'Invalid or inactive API key' in data['detail']

        # Reactivate for cleanup
        conn = get_auth_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE api_keys SET is_active = 1 WHERE id = ?",
            ( test_api_key['key_id'], )
        )
        conn.commit()
        conn.close()

    def test_last_used_timestamp_updated( self, test_api_key ):
        """Test that last_used_at timestamp is updated on successful auth."""
        # Get initial timestamp
        conn = get_auth_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_used_at FROM api_keys WHERE id = ?",
            ( test_api_key['key_id'], )
        )
        initial_timestamp = cursor.fetchone()['last_used_at']
        conn.close()

        # Use the API key
        response = requests.post(
            f"{self.BASE_URL}/api/notify",
            params={
                'message': 'Timestamp test',
                'type': 'task',
                'priority': 'low',
                'target_user': test_api_key['email']
            },
            headers={
                'X-API-Key': test_api_key['api_key']
            }
        )

        assert response.status_code == 200

        # Check updated timestamp
        conn = get_auth_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_used_at FROM api_keys WHERE id = ?",
            ( test_api_key['key_id'], )
        )
        updated_timestamp = cursor.fetchone()['last_used_at']
        conn.close()

        # Timestamp should be updated
        assert updated_timestamp != initial_timestamp
        assert updated_timestamp is not None

    def test_www_authenticate_header_present( self ):
        """Test that WWW-Authenticate header is present in 401 responses."""
        response = requests.post(
            f"{self.BASE_URL}/api/notify",
            params={
                'message': 'Should fail',
                'type': 'task',
                'priority': 'low'
            }
        )

        assert response.status_code == 401
        assert 'WWW-Authenticate' in response.headers
        assert response.headers['WWW-Authenticate'] == 'API-Key'


class TestMultipleAPIKeys:
    """Test scenarios with multiple API keys."""

    BASE_URL = "http://localhost:7999"

    def test_multiple_keys_for_same_user( self, test_api_key ):
        """Test that user can have multiple active API keys."""
        # Create second key for same user
        api_key2 = "ck_live_" + secrets.token_urlsafe( 48 )
        key_bytes = api_key2.encode( 'utf-8' )
        salt = bcrypt.gensalt( rounds=12 )
        key_hash2 = bcrypt.hashpw( key_bytes, salt ).decode( 'utf-8' )

        conn = get_auth_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO api_keys ( user_id, key_hash, description, created_at, is_active )
            VALUES ( ?, ?, ?, ?, ? )
            """,
            (
                test_api_key['user_id'],
                key_hash2,
                "Second test key",
                datetime.utcnow().isoformat(),
                1
            )
        )
        conn.commit()
        key_id2 = cursor.lastrowid
        conn.close()

        try:
            # Both keys should work
            response1 = requests.post(
                f"{self.BASE_URL}/api/notify",
                params={'message': 'Key 1 test', 'type': 'task', 'priority': 'low', 'target_user': test_api_key['email']},
                headers={'X-API-Key': test_api_key['api_key']}
            )

            response2 = requests.post(
                f"{self.BASE_URL}/api/notify",
                params={'message': 'Key 2 test', 'type': 'task', 'priority': 'low', 'target_user': test_api_key['email']},
                headers={'X-API-Key': api_key2}
            )

            assert response1.status_code == 200
            assert response2.status_code == 200

        finally:
            # Cleanup second key
            conn = get_auth_db_connection()
            cursor = conn.cursor()
            cursor.execute( "DELETE FROM api_keys WHERE id = ?", ( key_id2, ) )
            conn.commit()
            conn.close()


class TestSecurityHeaders:
    """Test security-related headers and responses."""

    BASE_URL = "http://localhost:7999"

    def test_no_api_key_leakage_in_errors( self, test_api_key ):
        """Test that API keys are not leaked in error messages."""
        # Try with wrong key
        wrong_key = "ck_live_" + "Y" * 64

        response = requests.post(
            f"{self.BASE_URL}/api/notify",
            params={'message': 'Test', 'type': 'task', 'priority': 'low'},
            headers={'X-API-Key': wrong_key}
        )

        assert response.status_code == 401
        data = response.json()

        # Error message should not contain the actual key
        assert wrong_key not in str( data )
        assert test_api_key['api_key'] not in str( data )

    def test_case_sensitive_header_name( self, test_api_key ):
        """Test that X-API-Key header is case-insensitive (HTTP standard)."""
        # FastAPI/Starlette handles header case-insensitivity
        response = requests.post(
            f"{self.BASE_URL}/api/notify",
            params={'message': 'Test', 'type': 'task', 'priority': 'low', 'target_user': test_api_key['email']},
            headers={'x-api-key': test_api_key['api_key']}  # lowercase
        )

        # Should still work (HTTP headers are case-insensitive)
        assert response.status_code == 200
