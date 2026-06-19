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
from cosa.config.configuration_manager import ConfigurationManager

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
ACCESS_TOKEN_EXPIRE_MINUTES   = config_mgr.get( "jwt access token expire minutes", 30, return_type="int" )
REFRESH_TOKEN_EXPIRE_DAYS     = config_mgr.get( "jwt refresh token expire days", 7, return_type="int" )


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

        print( "\n✓ All JWT service tests passed!" )
        return True

    except Exception as e:
        print( f"✗ JWT service test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()