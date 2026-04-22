"""
Integration tests for notification endpoint authentication.

Tests the complete authentication flow from API request through middleware
to database validation. Requires running FastAPI server.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
"""

import os

import pytest
import requests
import bcrypt
import secrets
import uuid
from datetime import datetime, timezone

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import UserRepository, ApiKeyRepository



@pytest.fixture
def test_api_key( clean_test_db ):
    """Create a test API key and store its hash in the database."""
    # Generate test API key
    api_key = "ck_live_" + secrets.token_urlsafe( 48 )

    # Hash the key
    key_bytes = api_key.encode( 'utf-8' )
    salt = bcrypt.gensalt( rounds=12 )
    key_hash = bcrypt.hashpw( key_bytes, salt ).decode( 'utf-8' )

    # Create test service account using PostgreSQL repositories
    user_id_obj = uuid.uuid4()
    email = f"test-{user_id_obj}@test.com"

    with get_db() as session:
        # Create user
        user_repo = UserRepository( session )
        user = user_repo.create_user(
            email=email,
            password_hash="dummy_hash",
            roles=['service_account']
        )
        user.email_verified = True
        user.is_active = True

        # Create API key
        api_key_repo = ApiKeyRepository( session )
        api_key_obj = api_key_repo.create_key(
            user_id=user.id,
            key_hash=key_hash,
            description="Integration test key"
        )

        # session.commit() happens automatically on context exit
        key_id = str( api_key_obj.id )
        user_id = str( user.id )

    yield {
        'api_key': api_key,
        'user_id': user_id,
        'key_id': key_id,
        'email': email
    }

    # Cleanup (note: clean_test_db fixture already drops all tables after each test)
    # This explicit cleanup is redundant but kept for clarity
    with get_db() as session:
        api_key_repo = ApiKeyRepository( session )
        user_repo = UserRepository( session )

        # Delete API key
        api_key_repo.delete( uuid.UUID( key_id ) )

        # Delete user
        user_repo.delete( uuid.UUID( user_id ) )


class TestNotificationAuthentication:
    """Integration tests for notification endpoint authentication."""

    BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

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
        assert 'Missing auth' in data['detail']

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
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories import ApiKeyRepository
        import uuid

        with get_db() as session:
            api_key_repo = ApiKeyRepository( session )
            api_key_repo.deactivate( uuid.UUID( test_api_key['key_id'] ) )

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
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories import ApiKeyRepository
        import uuid

        with get_db() as session:
            api_key_repo = ApiKeyRepository( session )
            api_key_obj = api_key_repo.get_by_id( uuid.UUID( test_api_key['key_id'] ) )
            api_key_obj.is_active = True

    def test_last_used_timestamp_updated( self, test_api_key ):
        """Test that last_used_at timestamp is updated on successful auth."""
        # Get initial timestamp
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories import ApiKeyRepository
        import uuid

        with get_db() as session:
            api_key_repo = ApiKeyRepository( session )
            api_key_obj = api_key_repo.get_by_id( uuid.UUID( test_api_key['key_id'] ) )
            initial_timestamp = api_key_obj.last_used_at

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
        with get_db() as session:
            api_key_repo = ApiKeyRepository( session )
            api_key_obj = api_key_repo.get_by_id( uuid.UUID( test_api_key['key_id'] ) )
            updated_timestamp = api_key_obj.last_used_at

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
        assert 'API-Key' in response.headers['WWW-Authenticate']


class TestMultipleAPIKeys:
    """Test scenarios with multiple API keys."""

    BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

    def test_multiple_keys_for_same_user( self, test_api_key ):
        """Test that user can have multiple active API keys."""
        # Create second key for same user
        api_key2 = "ck_live_" + secrets.token_urlsafe( 48 )
        key_bytes = api_key2.encode( 'utf-8' )
        salt = bcrypt.gensalt( rounds=12 )
        key_hash2 = bcrypt.hashpw( key_bytes, salt ).decode( 'utf-8' )

        with get_db() as session:
            api_key_repo = ApiKeyRepository( session )
            api_key_obj2 = api_key_repo.create_key(
                user_id=uuid.UUID( test_api_key['user_id'] ),
                key_hash=key_hash2,
                description="Second test key"
            )
            key_id2 = str( api_key_obj2.id )

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
            with get_db() as session:
                api_key_repo = ApiKeyRepository( session )
                api_key_repo.delete( uuid.UUID( key_id2 ) )


class TestSecurityHeaders:
    """Test security-related headers and responses."""

    BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

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
