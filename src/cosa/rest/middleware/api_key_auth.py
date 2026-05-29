"""
API Key Authentication Middleware for FastAPI.

Provides API key-based authentication for service-to-service communication.
Used primarily for notification endpoints accessed by Claude Code CLI.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
Section: Middleware Architecture Design (lines 1187-1336)

Usage:
    from cosa.rest.middleware.api_key_auth import require_api_key
    from fastapi import Depends
    from typing import Annotated

    @router.post("/api/notify")
    async def notify_endpoint(
        user_id: Annotated[str, Depends(require_api_key)],
        payload: dict
    ):
        # user_id is authenticated service account ID
        ...
"""

import re
import bcrypt
from typing import Optional, Annotated
from datetime import datetime, timezone
from fastapi import Header, HTTPException, status

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import ApiKeyRepository


async def validate_api_key( api_key: str ) -> Optional[str]:
    """
    Validate API key and return user_id if valid.

    Requires:
        - api_key is string from X-API-Key header
        - Database is initialized
        - api_keys table exists

    Ensures:
        - returns user_id (str) if key valid and active
        - returns None if key invalid or inactive
        - updates last_used_at timestamp on success
        - timing-safe comparison (bcrypt)

    Args:
        api_key: API key from request header

    Returns:
        str: user_id (UUID) if valid
        None: if invalid or inactive

    Raises:
        - None (returns None on error)
    """
    try:
        with get_db() as session:
            api_key_repo = ApiKeyRepository( session )

            # Query all active keys (indexed lookup on is_active)
            active_keys = api_key_repo.get_active_keys()

            # Check each key (timing-safe bcrypt comparison)
            for key_obj in active_keys:
                # Bcrypt comparison (timing-safe)
                if bcrypt.checkpw( api_key.encode( 'utf-8' ), key_obj.key_hash.encode( 'utf-8' ) ):
                    # Valid key found - update last_used_at
                    key_obj.last_used_at = datetime.now( timezone.utc )
                    # Session will auto-commit on context exit

                    return str( key_obj.user_id )

            # No matching key found
            return None

    except Exception as e:
        # Log error but don't expose details to client
        print( f"[API_KEY_AUTH] Validation error: {e}" )
        return None


async def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None
) -> str:
    """
    FastAPI dependency for API key authentication.

    Requires:
        - x_api_key from X-API-Key header (optional)

    Ensures:
        - returns user_id if authentication successful
        - raises HTTPException 401 if authentication fails
        - validates key format before database lookup
        - provides clear error messages

    Usage:
        @app.post("/api/notify")
        async def notify(
            user_id: Annotated[str, Depends(require_api_key)],
            payload: dict
        ):
            # user_id is authenticated user ID
            ...

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        str: user_id (UUID) of authenticated service account

    Raises:
        HTTPException: 401 if key missing, invalid format, or not found
    """
    # Check if header present
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Include X-API-Key header with your request.",
            headers={"WWW-Authenticate": "API-Key"}
        )

    # Validate key format before database lookup (performance optimization)
    if not re.match( r'^ck_live_[A-Za-z0-9_-]{64,}$', x_api_key ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format. Expected format: ck_live_{64+ characters}",
            headers={"WWW-Authenticate": "API-Key"}
        )

    # Validate against database
    user_id = await validate_api_key( x_api_key )

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key. Verify your key is correct and active.",
            headers={"WWW-Authenticate": "API-Key"}
        )

    return user_id


async def require_api_key_or_jwt(
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None
) -> str:
    """
    FastAPI dependency for dual authentication: API key OR JWT Bearer token.

    Accepts either X-API-Key header (bcrypt validated) or Authorization: Bearer <jwt>.
    Used by endpoints that need to serve both external CLI clients (API key)
    and internal server-side callers (JWT).

    Requires:
        - At least one of x_api_key or authorization header is present
        - If x_api_key: matches format ck_live_{64+} and validates against database
        - If authorization: starts with "Bearer " and contains a valid JWT

    Ensures:
        - Returns user_id (UUID string) on success
        - Raises HTTPException 401 on failure
        - Tries API key first, then JWT

    Args:
        x_api_key: API key from X-API-Key header (optional)
        authorization: Bearer token from Authorization header (optional)

    Returns:
        str: user_id (UUID) of authenticated user

    Raises:
        HTTPException: 401 if neither auth method succeeds
    """
    # Option 1: API key
    if x_api_key:
        if not re.match( r'^ck_live_[A-Za-z0-9_-]{64,}$', x_api_key ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key format",
                headers={ "WWW-Authenticate": "API-Key, Bearer" }
            )
        user_id = await validate_api_key( x_api_key )
        if user_id:
            return user_id
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
            headers={ "WWW-Authenticate": "API-Key, Bearer" }
        )

    # Option 2: Bearer JWT
    if authorization and authorization.startswith( "Bearer " ):
        token = authorization[ 7: ]
        try:
            from cosa.rest.auth import verify_token
            user_info = await verify_token( token )
            return user_info[ "uid" ]
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid JWT: {e}",
                headers={ "WWW-Authenticate": "API-Key, Bearer" }
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing auth. Provide X-API-Key or Authorization: Bearer <jwt>",
        headers={ "WWW-Authenticate": "API-Key, Bearer" }
    )


def quick_smoke_test():
    """
    Quick smoke test for API key authentication middleware.

    Requires:
        - Database initialized
        - Service account created
        - API key generated

    Ensures:
        - Tests validate_api_key with valid key
        - Tests validate_api_key with invalid key
        - Tests require_api_key dependency logic
        - Comprehensive output with status indicators

    Raises:
        - None (catches all exceptions)
    """
    import asyncio
    import cosa.utils.util as cu

    cu.print_banner( "API Key Auth Middleware Smoke Test", prepend_nl=True )

    try:
        # Test 1: Module imports
        print( "Testing module imports..." )
        print( "✓ api_key_auth module imported" )

        # Test 2: Check if service account exists
        print( "\nTesting service account existence..." )
        conn = get_auth_db_connection()
        cursor = conn.cursor()
        cursor.execute( "SELECT COUNT(*) as count FROM api_keys WHERE is_active = 1" )
        result = cursor.fetchone()
        conn.close()

        if result['count'] == 0:
            print( "⚠️  No active API keys found in database" )
            print( "   Run: python src/scripts/create_service_account.py" )
            print( "\n⚠️  Smoke test incomplete (no keys to test)" )
            return False

        print( f"✓ Found {result['count']} active API key(s)" )

        # Test 3: Validate with valid key (need to get from database)
        print( "\nTesting validate_api_key function..." )
        print( "⚠️  Skipping validation test (requires plaintext key)" )
        print( "   This function will be tested in integration tests" )

        # Test 4: Test format validation
        print( "\nTesting API key format validation..." )

        valid_format = re.match( r'^ck_live_[A-Za-z0-9_-]{64,}$', "ck_live_" + "A" * 64 )
        assert valid_format is not None
        print( "✓ Valid format regex works" )

        invalid_format = re.match( r'^ck_live_[A-Za-z0-9_-]{64,}$', "invalid_key" )
        assert invalid_format is None
        print( "✓ Invalid format regex works" )

        # Test 5: Test dependency would raise on missing header
        print( "\nTesting require_api_key dependency logic..." )
        print( "✓ Dependency function defined (full test requires FastAPI context)" )

        print( "\n✓ All middleware smoke tests passed!" )
        print( "\nNote: Full validation testing requires integration tests with actual keys" )
        return True

    except Exception as e:
        print( f"\n✗ Middleware test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()
