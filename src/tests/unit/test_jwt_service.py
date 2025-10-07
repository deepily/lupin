"""
Unit tests for JWT Service.

Tests token generation, validation, expiration, and security features.
"""

import pytest
import jwt
from datetime import datetime, timedelta
from cosa.rest.jwt_service import (
    create_access_token,
    create_refresh_token,
    decode_and_validate_token,
    SECRET_KEY,
    ALGORITHM
)


class TestAccessTokenGeneration:
    """Test suite for access token generation."""

    def test_create_access_token_success( self ):
        """Test successful access token creation."""
        token = create_access_token(
            user_id = "test_user_123",
            email   = "test@example.com",
            roles   = ["user"]
        )

        assert token is not None
        assert len( token ) > 100  # JWT tokens are typically 200+ chars
        assert isinstance( token, str )

    def test_access_token_contains_required_claims( self ):
        """Test access token contains all required claims."""
        token = create_access_token(
            user_id = "test_user_123",
            email   = "test@example.com",
            roles   = ["user", "admin"]
        )

        payload = jwt.decode( token, SECRET_KEY, algorithms=[ALGORITHM] )

        assert payload["sub"] == "test_user_123"
        assert payload["email"] == "test@example.com"
        assert payload["roles"] == ["user", "admin"]
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_access_token_expiration_set_correctly( self ):
        """Test access token expiration is set to configured time."""
        token = create_access_token(
            user_id = "test_user_123",
            email   = "test@example.com",
            roles   = ["user"]
        )

        payload = jwt.decode( token, SECRET_KEY, algorithms=[ALGORITHM] )

        # Check expiration is approximately 30 minutes in future
        exp_time = datetime.fromtimestamp( payload["exp"] )
        now = datetime.utcnow()
        time_diff = (exp_time - now).total_seconds()

        # Should be ~30 minutes (allow 5 second tolerance for test execution)
        assert 1795 < time_diff < 1805  # 30 min = 1800 sec

    def test_create_access_token_requires_user_id( self ):
        """Test access token creation fails without user_id."""
        with pytest.raises( ValueError ):
            create_access_token(
                user_id = "",
                email   = "test@example.com",
                roles   = ["user"]
            )

    def test_create_access_token_requires_email( self ):
        """Test access token creation fails without email."""
        with pytest.raises( ValueError ):
            create_access_token(
                user_id = "test_user_123",
                email   = "",
                roles   = ["user"]
            )


class TestRefreshTokenGeneration:
    """Test suite for refresh token generation."""

    def test_create_refresh_token_success( self ):
        """Test successful refresh token creation."""
        token = create_refresh_token(
            user_id = "test_user_123",
            email   = "test@example.com"
        )

        assert token is not None
        assert len( token ) > 100
        assert isinstance( token, str )

    def test_refresh_token_contains_required_claims( self ):
        """Test refresh token contains all required claims."""
        token = create_refresh_token(
            user_id = "test_user_123",
            email   = "test@example.com"
        )

        payload = jwt.decode( token, SECRET_KEY, algorithms=[ALGORITHM] )

        assert payload["sub"] == "test_user_123"
        assert payload["email"] == "test@example.com"
        assert payload["token_type"] == "refresh"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_refresh_token_expiration_set_correctly( self ):
        """Test refresh token expiration is set to configured time."""
        token = create_refresh_token(
            user_id = "test_user_123",
            email   = "test@example.com"
        )

        payload = jwt.decode( token, SECRET_KEY, algorithms=[ALGORITHM] )

        # Check expiration is approximately 7 days in future
        exp_time = datetime.fromtimestamp( payload["exp"] )
        now = datetime.utcnow()
        time_diff = (exp_time - now).total_seconds()

        # Should be ~7 days (allow 10 second tolerance)
        expected = 7 * 24 * 60 * 60  # 604800 seconds
        assert expected - 10 < time_diff < expected + 10


class TestTokenValidation:
    """Test suite for token validation."""

    def test_decode_valid_access_token( self ):
        """Test decoding valid access token."""
        token = create_access_token(
            user_id = "test_user_123",
            email   = "test@example.com",
            roles   = ["user"]
        )

        payload = decode_and_validate_token( token )

        assert payload["sub"] == "test_user_123"
        assert payload["email"] == "test@example.com"

    def test_decode_valid_refresh_token( self ):
        """Test decoding valid refresh token."""
        token = create_refresh_token(
            user_id = "test_user_123",
            email   = "test@example.com"
        )

        payload = decode_and_validate_token( token )

        assert payload["sub"] == "test_user_123"
        assert payload["token_type"] == "refresh"

    def test_reject_invalid_token( self ):
        """Test invalid tokens are rejected."""
        with pytest.raises( jwt.InvalidTokenError ):
            decode_and_validate_token( "invalid.token.string" )

    def test_reject_expired_token( self ):
        """Test expired tokens are rejected."""
        # Create manually expired token
        past_expire = datetime.utcnow() - timedelta( minutes=1 )
        expired_payload = {
            "sub"   : "test_user",
            "email" : "test@example.com",
            "exp"   : past_expire
        }
        expired_token = jwt.encode( expired_payload, SECRET_KEY, algorithm=ALGORITHM )

        with pytest.raises( jwt.ExpiredSignatureError ):
            decode_and_validate_token( expired_token )

    def test_reject_wrong_token_type( self ):
        """Test refresh token rejected when access token expected."""
        refresh_token = create_refresh_token(
            user_id = "test_user_123",
            email   = "test@example.com"
        )

        with pytest.raises( ValueError ):
            decode_and_validate_token( refresh_token, expected_type="access" )

    def test_reject_tampered_token( self ):
        """Test tokens with tampered payload are rejected."""
        token = create_access_token(
            user_id = "test_user_123",
            email   = "test@example.com",
            roles   = ["user"]
        )

        # Tamper with token by changing a character
        tampered_token = token[:-5] + "XXXXX"

        with pytest.raises( jwt.InvalidTokenError ):
            decode_and_validate_token( tampered_token )


if __name__ == "__main__":
    pytest.main( [__file__, "-v"] )