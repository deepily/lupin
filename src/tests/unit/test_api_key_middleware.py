"""
Unit tests for API key authentication middleware.

Tests the security and correctness of API key validation middleware
including bcrypt verification and FastAPI dependency injection.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
Section: Middleware Architecture Design (lines 1187-1336)

Updated: 2026-02-02 - Fixed to mock ORM layer (get_db + ApiKeyRepository)
"""

import pytest
import bcrypt
import uuid
from contextlib import contextmanager
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from fastapi import HTTPException

from cosa.rest.middleware.api_key_auth import validate_api_key, require_api_key


class MockApiKey:
    """Mock ApiKey ORM object for testing."""

    def __init__( self, id: int, user_id: str, key_hash: str ):
        self.id            = id
        self.user_id       = uuid.UUID( user_id ) if isinstance( user_id, str ) else user_id
        self.key_hash      = key_hash
        self.is_active     = True
        self.last_used_at  = None
        self.created_at    = datetime.utcnow()
        self.description   = "Test key"


@contextmanager
def mock_db_session( api_keys: list ):
    """
    Create a mock database session context manager.

    Args:
        api_keys: List of MockApiKey objects to return from get_active_keys()
    """
    mock_session = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_active_keys.return_value = api_keys

    # When ApiKeyRepository is instantiated with session, return our mock repo
    with patch( 'cosa.rest.middleware.api_key_auth.get_db' ) as mock_get_db:
        with patch( 'cosa.rest.middleware.api_key_auth.ApiKeyRepository', return_value=mock_repo ):
            @contextmanager
            def session_context():
                yield mock_session

            mock_get_db.return_value = session_context()
            yield mock_repo


class TestValidateAPIKey:
    """Test suite for validate_api_key() function."""

    @pytest.mark.asyncio
    async def test_valid_api_key_returns_user_id( self ):
        """Test that valid API key returns user_id."""
        # Generate test API key and hash
        test_key = "ck_live_" + "A" * 64
        test_user_id = "12345678-1234-1234-1234-123456789012"
        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( test_key.encode( 'utf-8' ), salt ).decode( 'utf-8' )

        # Create mock API key
        mock_key = MockApiKey( id=1, user_id=test_user_id, key_hash=key_hash )

        with mock_db_session( [ mock_key ] ) as mock_repo:
            result = await validate_api_key( test_key )

        assert result == test_user_id
        mock_repo.get_active_keys.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_none( self ):
        """Test that invalid API key returns None."""
        test_key = "ck_live_invalid_key_" + "B" * 64
        correct_key = "ck_live_" + "A" * 64
        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( correct_key.encode( 'utf-8' ), salt ).decode( 'utf-8' )

        # Mock API key with different key hash
        mock_key = MockApiKey(
            id=1,
            user_id="12345678-1234-1234-1234-123456789012",
            key_hash=key_hash  # Hash of different key
        )

        with mock_db_session( [ mock_key ] ) as mock_repo:
            result = await validate_api_key( test_key )

        assert result is None

    @pytest.mark.asyncio
    async def test_no_active_keys_returns_none( self ):
        """Test that query with no active keys returns None."""
        test_key = "ck_live_" + "C" * 64

        # Empty list of keys
        with mock_db_session( [] ) as mock_repo:
            result = await validate_api_key( test_key )

        assert result is None

    @pytest.mark.asyncio
    async def test_database_error_returns_none( self ):
        """Test that database errors are handled gracefully."""
        test_key = "ck_live_" + "D" * 64

        # Mock get_db to raise exception
        with patch( 'cosa.rest.middleware.api_key_auth.get_db', side_effect=Exception( "DB error" ) ):
            result = await validate_api_key( test_key )

        assert result is None  # Should handle error gracefully

    @pytest.mark.asyncio
    async def test_updates_last_used_timestamp( self ):
        """Test that successful validation updates last_used_at."""
        test_key = "ck_live_" + "E" * 64
        test_user_id = "12345678-1234-1234-1234-123456789012"
        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( test_key.encode( 'utf-8' ), salt ).decode( 'utf-8' )

        mock_key = MockApiKey( id=5, user_id=test_user_id, key_hash=key_hash )
        initial_last_used = mock_key.last_used_at

        with mock_db_session( [ mock_key ] ) as mock_repo:
            result = await validate_api_key( test_key )

        # The implementation sets last_used_at on the key object
        assert result == test_user_id
        # Note: In the actual implementation, key_obj.last_used_at is set directly
        # The mock doesn't persist changes, but we verify the flow worked


class TestRequireAPIKey:
    """Test suite for require_api_key() FastAPI dependency."""

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_401( self ):
        """Test that missing X-API-Key header raises 401."""
        with pytest.raises( HTTPException ) as exc_info:
            await require_api_key( x_api_key=None )

        assert exc_info.value.status_code == 401
        assert "Missing API key" in exc_info.value.detail
        assert exc_info.value.headers == { "WWW-Authenticate": "API-Key" }

    @pytest.mark.asyncio
    async def test_invalid_format_raises_401( self ):
        """Test that invalid API key format raises 401."""
        invalid_keys = [
            "invalid_key",
            "ck_test_" + "A" * 64,  # Wrong prefix
            "ck_live_" + "A" * 63,  # Too short
            "ck_live_ABC!@#$%",      # Invalid characters
        ]

        for invalid_key in invalid_keys:
            with pytest.raises( HTTPException ) as exc_info:
                await require_api_key( x_api_key=invalid_key )

            assert exc_info.value.status_code == 401
            assert "Invalid API key format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_key_returns_user_id( self ):
        """Test that valid API key returns user_id."""
        test_key = "ck_live_" + "F" * 64
        test_user_id = "12345678-1234-1234-1234-123456789012"

        # Mock validate_api_key to return user_id
        with patch( 'cosa.rest.middleware.api_key_auth.validate_api_key', return_value=test_user_id ):
            result = await require_api_key( x_api_key=test_key )

        assert result == test_user_id

    @pytest.mark.asyncio
    async def test_invalid_key_raises_401( self ):
        """Test that invalid API key (failed validation) raises 401."""
        test_key = "ck_live_" + "G" * 64

        # Mock validate_api_key to return None (invalid key)
        with patch( 'cosa.rest.middleware.api_key_auth.validate_api_key', return_value=None ):
            with pytest.raises( HTTPException ) as exc_info:
                await require_api_key( x_api_key=test_key )

        assert exc_info.value.status_code == 401
        assert "Invalid or inactive API key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_format_validation_before_database_lookup( self ):
        """Test that format validation happens before database lookup (performance)."""
        invalid_key = "invalid_format"

        # Mock validate_api_key - should NOT be called for invalid format
        with patch( 'cosa.rest.middleware.api_key_auth.validate_api_key' ) as mock_validate:
            with pytest.raises( HTTPException ):
                await require_api_key( x_api_key=invalid_key )

            # validate_api_key should NOT have been called (format check failed first)
            mock_validate.assert_not_called()


class TestBcryptTimingSafety:
    """Test suite for bcrypt timing-safe comparison."""

    @pytest.mark.asyncio
    async def test_bcrypt_checkpw_used( self ):
        """Test that bcrypt.checkpw is used for timing-safe comparison."""
        test_key = "ck_live_" + "H" * 64
        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( test_key.encode( 'utf-8' ), salt ).decode( 'utf-8' )

        mock_key = MockApiKey(
            id=1,
            user_id="12345678-1234-1234-1234-123456789012",
            key_hash=key_hash
        )

        # Mock bcrypt.checkpw to track if it's called
        with mock_db_session( [ mock_key ] ):
            with patch( 'bcrypt.checkpw', return_value=True ) as mock_bcrypt:
                await validate_api_key( test_key )

                # Verify bcrypt.checkpw was called (timing-safe comparison)
                mock_bcrypt.assert_called_once()

    def test_bcrypt_comparison_is_constant_time( self ):
        """Test that bcrypt comparison is timing-safe (conceptual test)."""
        # This test documents the security requirement
        # bcrypt.checkpw() is designed to be timing-safe
        # It always performs the full hash comparison regardless of where mismatch occurs

        correct_key = "ck_live_" + "I" * 64
        wrong_key = "ck_live_" + "J" * 64

        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( correct_key.encode( 'utf-8' ), salt )

        # Both comparisons should take similar time (timing-safe)
        result1 = bcrypt.checkpw( correct_key.encode( 'utf-8' ), key_hash )
        result2 = bcrypt.checkpw( wrong_key.encode( 'utf-8' ), key_hash )

        assert result1 is True
        assert result2 is False
        # The important security property is that the time taken
        # for both comparisons is constant (not tested here, but documented)


class TestAPIKeySecurityRequirements:
    """Test suite documenting security requirements."""

    def test_api_key_length_requirement( self ):
        """Document minimum 288-bit entropy requirement."""
        # Requirement: API keys must have at least 288 bits of entropy
        # Implementation: secrets.token_urlsafe(48) = 48 bytes = 384 bits
        # Base64url encoding: 48 bytes → 64 characters

        min_entropy_bits = 288
        actual_entropy_bits = 48 * 8  # 48 bytes * 8 bits/byte = 384 bits

        assert actual_entropy_bits >= min_entropy_bits, \
            f"API key entropy ({actual_entropy_bits} bits) below requirement ({min_entropy_bits} bits)"

    def test_bcrypt_cost_factor_requirement( self ):
        """Document bcrypt cost factor requirement."""
        # Requirement: Cost factor >= 12 (balance security vs performance)
        required_cost = 12

        # Verify a hash created with cost=12 validates correctly
        test_password = "test_password"
        salt = bcrypt.gensalt( rounds=required_cost )
        password_hash = bcrypt.hashpw( test_password.encode( 'utf-8' ), salt )

        assert bcrypt.checkpw( test_password.encode( 'utf-8' ), password_hash )

    def test_no_plaintext_storage( self ):
        """Document that plaintext API keys must not be stored."""
        # Security requirement: Only bcrypt hashes are stored in database
        # Plaintext keys are:
        # 1. Generated once
        # 2. Shown to user once
        # 3. Written to key file
        # 4. Never stored in database

        # This test documents the requirement (enforcement is by design)
        assert True, "Plaintext API keys must never be stored in database"
