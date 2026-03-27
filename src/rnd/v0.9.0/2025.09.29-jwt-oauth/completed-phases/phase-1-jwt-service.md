# Phase 1: JWT Service Foundation

**Status**: ✅ COMPLETED on 2025.09.29

---


**Timeline**: Week 1, Days 1-2
**Status**: NOT_STARTED
**Blocking**: None

#### Objectives
- Create JWT token generation and validation module
- Implement core cryptographic operations
- Establish testing patterns for authentication

#### Files to Create

**1. `src/cosa/rest/jwt_service.py`** (Core JWT module)

```python
"""
JWT Token Service for Lupin Authentication.

This module provides JWT token generation, validation, and management
using PyJWT library with HS256 algorithm.

Responsibilities:
- Generate access tokens (short-lived, 30 min)
- Generate refresh tokens (long-lived, 7 days)
- Validate token signatures and expiration
- Decode token claims
- Handle token revocation checking
"""

import jwt
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from cosa.app.configuration_manager import ConfigurationManager

# Initialize configuration
config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

# Load JWT configuration
SECRET_KEY = os.getenv( "JWT_SECRET_KEY" )
if not SECRET_KEY:
    if os.getenv( "ENVIRONMENT" ) == "production":
        raise ValueError( "JWT_SECRET_KEY environment variable must be set in production!" )
    else:
        print( "[JWT] ⚠️  WARNING: Using default development secret key" )
        print( "[JWT] ⚠️  Set JWT_SECRET_KEY environment variable for production" )
        SECRET_KEY = "dev-secret-key-DO-NOT-USE-IN-PRODUCTION-8x7mp3"

ALGORITHM                     = config_mgr.get( "jwt algorithm", "HS256" )
ACCESS_TOKEN_EXPIRE_MINUTES   = config_mgr.get( "jwt access token expire minutes", 30 )
REFRESH_TOKEN_EXPIRE_DAYS     = config_mgr.get( "jwt refresh token expire days", 7 )


def create_access_token( user_id: str, email: str, roles: List[str] ) -> str:
    """
    Generate short-lived JWT access token.

    Requires:
        - user_id is a non-empty system ID string
        - email is a valid email address string
        - roles is a list of role strings (e.g., ["user", "admin"])
        - SECRET_KEY is configured

    Ensures:
        - Returns signed JWT string
        - Token includes sub, email, roles, exp, iat, jti claims
        - Token is valid for configured expiration time
        - Token can be decoded with same SECRET_KEY

    Raises:
        - ValueError if user_id or email is empty
        - jwt.PyJWTError if encoding fails

    Returns:
        str: Encoded JWT token
    """
    if not user_id or not email:
        raise ValueError( "user_id and email are required" )

    # Calculate expiration
    expire = datetime.utcnow() + timedelta( minutes=ACCESS_TOKEN_EXPIRE_MINUTES )

    # Build payload
    payload = {
        "sub"   : user_id,
        "email" : email,
        "roles" : roles if roles else ["user"],
        "exp"   : expire,
        "iat"   : datetime.utcnow(),
        "jti"   : _generate_jti()  # Unique token ID
    }

    # Encode token
    token = jwt.encode( payload, SECRET_KEY, algorithm=ALGORITHM )

    return token


def create_refresh_token( user_id: str, email: str ) -> str:
    """
    Generate long-lived JWT refresh token.

    Requires:
        - user_id is a non-empty system ID string
        - email is a valid email address string
        - SECRET_KEY is configured

    Ensures:
        - Returns signed JWT string
        - Token includes sub, email, exp, iat, jti, token_type claims
        - Token is valid for configured expiration time
        - token_type claim is "refresh" (distinguishes from access tokens)

    Raises:
        - ValueError if user_id or email is empty
        - jwt.PyJWTError if encoding fails

    Returns:
        str: Encoded JWT refresh token
    """
    if not user_id or not email:
        raise ValueError( "user_id and email are required" )

    # Calculate expiration
    expire = datetime.utcnow() + timedelta( days=REFRESH_TOKEN_EXPIRE_DAYS )

    # Build payload
    payload = {
        "sub"        : user_id,
        "email"      : email,
        "exp"        : expire,
        "iat"        : datetime.utcnow(),
        "jti"        : _generate_jti(),
        "token_type" : "refresh"  # Distinguish from access tokens
    }

    # Encode token
    token = jwt.encode( payload, SECRET_KEY, algorithm=ALGORITHM )

    return token


def decode_and_validate_token( token: str, expected_type: Optional[str] = None ) -> Dict:
    """
    Decode and validate JWT token.

    Requires:
        - token is a non-empty JWT string
        - SECRET_KEY matches the key used to sign token
        - expected_type is None, "access", or "refresh"

    Ensures:
        - Token signature is valid
        - Token is not expired
        - Token type matches expected_type (if specified)
        - Returns decoded payload as dictionary

    Raises:
        - jwt.ExpiredSignatureError if token expired
        - jwt.InvalidTokenError if signature invalid
        - ValueError if token_type doesn't match expected_type

    Returns:
        dict: Decoded token payload
    """
    # Decode token (validates signature and expiration automatically)
    payload = jwt.decode( token, SECRET_KEY, algorithms=[ALGORITHM] )

    # Validate token type if specified
    if expected_type:
        token_type = payload.get( "token_type" )

        if expected_type == "access" and token_type == "refresh":
            raise ValueError( "Refresh token cannot be used as access token" )

        if expected_type == "refresh" and token_type != "refresh":
            raise ValueError( "Expected refresh token, got access token" )

    return payload


def _generate_jti() -> str:
    """
    Generate unique JWT ID for token tracking.

    Requires:
        - None

    Ensures:
        - Returns unique identifier string
        - Format: UUID4 (e.g., "7f3a9c2e-4b1d-4f8e-9d6c-1a2b3c4d5e6f")
        - Suitable for database primary key

    Raises:
        - None

    Returns:
        str: Unique token identifier
    """
    import uuid
    return str( uuid.uuid4() )


def quick_smoke_test():
    """
    Quick smoke test for JWT service functionality.

    Requires:
        - jwt library installed
        - SECRET_KEY configured
        - All JWT functions available

    Ensures:
        - Tests access token generation
        - Tests refresh token generation
        - Tests token validation
        - Tests expiration handling
        - Tests invalid token rejection
        - Returns True if all tests pass

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du

    du.print_banner( "JWT Service Smoke Test", prepend_nl=True )

    try:
        # Test 1: Access token generation
        print( "Testing access token generation..." )
        access_token = create_access_token(
            user_id = "test_user_123",
            email   = "test@example.com",
            roles   = ["user", "admin"]
        )
        if access_token and len( access_token ) > 100:
            print( f"✓ Access token generated ({len( access_token )} chars)" )
        else:
            print( "✗ Access token generation failed" )
            return False

        # Test 2: Access token validation
        print( "Testing access token validation..." )
        payload = decode_and_validate_token( access_token, expected_type="access" )
        if payload["sub"] == "test_user_123" and payload["email"] == "test@example.com":
            print( "✓ Access token validated correctly" )
        else:
            print( "✗ Access token validation failed" )
            return False

        # Test 3: Refresh token generation
        print( "Testing refresh token generation..." )
        refresh_token = create_refresh_token(
            user_id = "test_user_123",
            email   = "test@example.com"
        )
        if refresh_token and len( refresh_token ) > 100:
            print( f"✓ Refresh token generated ({len( refresh_token )} chars)" )
        else:
            print( "✗ Refresh token generation failed" )
            return False

        # Test 4: Refresh token validation
        print( "Testing refresh token validation..." )
        payload = decode_and_validate_token( refresh_token, expected_type="refresh" )
        if payload["sub"] == "test_user_123" and payload["token_type"] == "refresh":
            print( "✓ Refresh token validated correctly" )
        else:
            print( "✗ Refresh token validation failed" )
            return False

        # Test 5: Invalid token rejection
        print( "Testing invalid token rejection..." )
        try:
            decode_and_validate_token( "invalid.token.string" )
            print( "✗ Invalid token was accepted (security issue!)" )
            return False
        except jwt.InvalidTokenError:
            print( "✓ Invalid token rejected correctly" )

        # Test 6: Expired token detection
        print( "Testing expired token detection..." )
        # Create token that expired in the past
        past_expire = datetime.utcnow() - timedelta( minutes=1 )
        expired_payload = {
            "sub"   : "test_user",
            "email" : "test@example.com",
            "exp"   : past_expire,
            "iat"   : datetime.utcnow() - timedelta( minutes=2 )
        }
        expired_token = jwt.encode( expired_payload, SECRET_KEY, algorithm=ALGORITHM )

        try:
            decode_and_validate_token( expired_token )
            print( "✗ Expired token was accepted (security issue!)" )
            return False
        except jwt.ExpiredSignatureError:
            print( "✓ Expired token rejected correctly" )

        # Test 7: Token type validation
        print( "Testing token type validation..." )
        try:
            decode_and_validate_token( refresh_token, expected_type="access" )
            print( "✗ Refresh token accepted as access token (security issue!)" )
            return False
        except ValueError:
            print( "✓ Token type validation working" )

        print( "\\n✓ All JWT service tests passed!" )
        return True

    except Exception as e:
        print( f"✗ JWT service test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()
```

**2. `src/tests/unit/test_jwt_service.py`** (Comprehensive unit tests)

```python
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
```

#### Tasks & Checklist

- [ ] **Task 1.1**: Create `src/cosa/rest/jwt_service.py`
  - [ ] Implement `create_access_token()`
  - [ ] Implement `create_refresh_token()`
  - [ ] Implement `decode_and_validate_token()`
  - [ ] Implement `_generate_jti()` helper
  - [ ] Add configuration loading
  - [ ] Add `quick_smoke_test()` function

- [ ] **Task 1.2**: Create `src/tests/unit/test_jwt_service.py`
  - [ ] Write access token generation tests (5 tests)
  - [ ] Write refresh token generation tests (3 tests)
  - [ ] Write token validation tests (6 tests)
  - [ ] Write security tests (tampering, expiration)

- [ ] **Task 1.3**: Configuration Integration
  - [ ] Add JWT config keys to `lupin-app.ini`
  - [ ] Add explanations to `lupin-app-splainer.ini`
  - [ ] Test configuration loading

- [ ] **Task 1.4**: Testing & Validation
  - [ ] Run `quick_smoke_test()` - all tests pass
  - [ ] Run pytest suite - 100% pass rate
  - [ ] Test with missing SECRET_KEY (should warn in dev)
  - [ ] Test token generation performance (<10ms per token)

#### Testing Checkpoints

| Test Category | Status | Notes |
|---------------|--------|-------|
| Access token generation | PENDING | - |
| Access token validation | PENDING | - |
| Refresh token generation | PENDING | - |
| Refresh token validation | PENDING | - |
| Token expiration handling | PENDING | - |
| Invalid token rejection | PENDING | - |
| Token type validation | PENDING | - |
| Configuration loading | PENDING | - |
| Performance (<10ms) | PENDING | - |

#### Rollback Procedure

1. Delete `src/cosa/rest/jwt_service.py`
2. Delete `src/tests/unit/test_jwt_service.py`
3. Remove JWT config keys from `lupin-app.ini` and `lupin-app-splainer.ini`
4. No system impact (module not yet integrated)

#### Success Criteria

✅ All unit tests passing (100% pass rate)
✅ Quick smoke test passing
✅ Tokens generate in <10ms
✅ Invalid tokens properly rejected
✅ Configuration integration working
✅ Documentation complete

---


---

**Source**: Extracted from original monolithic design document (2025.09.29-jwt-oauth-implementation-design-and-tracker.md)
