"""
Unit tests for cosa.rest.auth_middleware.

The single external seam — verify_token() from cosa.rest.auth ( async ) — is mocked
with AsyncMock; no real token validation. Covers the FastAPI auth dependencies and the
synchronous role-checking helpers:

    - get_current_user_optional ( no header / bad format / valid / HTTPException / generic )
    - get_current_user          ( no header / falsy user / valid )
    - require_roles / require_all_roles ( empty -> ValueError; has / lacks roles -> 403 )
    - is_admin / is_user / has_role / has_any_role / has_all_roles
"""

import unittest
from unittest.mock import patch, AsyncMock

from fastapi import HTTPException

from cosa.rest.auth_middleware import (
    get_current_user_optional,
    get_current_user,
    require_roles,
    require_all_roles,
    is_admin,
    is_user,
    has_role,
    has_any_role,
    has_all_roles,
)


class TestGetCurrentUserOptional( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for get_current_user_optional().

    Ensures:
        - Missing header -> None; malformed header -> 401
        - Valid token -> user; HTTPException re-raised; generic error -> 401
    """

    async def test_no_authorization_returns_none( self ):
        """
        Ensures:
            - No Authorization header returns None ( anonymous )
        """
        self.assertIsNone( await get_current_user_optional( None ) )

    async def test_malformed_header_wrong_part_count( self ):
        """
        Ensures:
            - A header that is not exactly two parts -> 401
        """
        with self.assertRaises( HTTPException ) as ctx:
            await get_current_user_optional( "Bearer" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_malformed_header_wrong_scheme( self ):
        """
        Ensures:
            - A non-"bearer" scheme -> 401
        """
        with self.assertRaises( HTTPException ) as ctx:
            await get_current_user_optional( "Basic abc123" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_valid_token_returns_user( self ):
        """
        Ensures:
            - A valid Bearer token returns verify_token's user dict
        """
        with patch( 'cosa.rest.auth_middleware.verify_token', new=AsyncMock( return_value={ "email": "a@b.com" } ) ):
            result = await get_current_user_optional( "Bearer goodtoken" )
            self.assertEqual( result, { "email": "a@b.com" } )

    async def test_verify_token_httpexception_reraised( self ):
        """
        Ensures:
            - An HTTPException from verify_token is propagated unchanged
        """
        exc = HTTPException( status_code=403, detail="nope" )
        with patch( 'cosa.rest.auth_middleware.verify_token', new=AsyncMock( side_effect=exc ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_current_user_optional( "Bearer tok" )
            self.assertEqual( ctx.exception.status_code, 403 )

    async def test_verify_token_generic_error_becomes_401( self ):
        """
        Ensures:
            - A non-HTTP exception from verify_token is wrapped as 401
        """
        with patch( 'cosa.rest.auth_middleware.verify_token', new=AsyncMock( side_effect=ValueError( "boom" ) ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_current_user_optional( "Bearer tok" )
            self.assertEqual( ctx.exception.status_code, 401 )


class TestGetCurrentUser( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for get_current_user().

    Ensures:
        - Missing header -> 401
        - A falsy user from the optional dependency -> 401
        - A valid user is returned
    """

    async def test_no_authorization_raises_401( self ):
        """
        Ensures:
            - Missing Authorization header -> 401
        """
        with self.assertRaises( HTTPException ) as ctx:
            await get_current_user( None )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_falsy_user_raises_401( self ):
        """
        Ensures:
            - verify_token returning None ( falsy user ) -> 401
        """
        with patch( 'cosa.rest.auth_middleware.verify_token', new=AsyncMock( return_value=None ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_current_user( "Bearer tok" )
            self.assertEqual( ctx.exception.status_code, 401 )

    async def test_valid_user_returned( self ):
        """
        Ensures:
            - A valid token yields the user dict
        """
        with patch( 'cosa.rest.auth_middleware.verify_token', new=AsyncMock( return_value={ "email": "a@b.com" } ) ):
            self.assertEqual( await get_current_user( "Bearer tok" ), { "email": "a@b.com" } )


class TestRequireRoles( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for require_roles() ( ANY-of semantics ).

    Ensures:
        - Empty roles -> ValueError at factory time
        - Dependency passes when a required role is present, 403 otherwise
    """

    def test_empty_roles_raises( self ):
        """
        Ensures:
            - require_roles([]) raises ValueError
        """
        with self.assertRaises( ValueError ):
            require_roles( [] )

    async def test_user_with_required_role_passes( self ):
        """
        Ensures:
            - A user holding one of the required roles is returned
        """
        check = require_roles( [ "admin", "auditor" ] )
        user = { "roles": [ "admin" ] }
        self.assertEqual( await check( user=user ), user )

    async def test_user_without_required_role_403( self ):
        """
        Ensures:
            - A user lacking all required roles -> 403
        """
        check = require_roles( [ "admin" ] )
        with self.assertRaises( HTTPException ) as ctx:
            await check( user={ "roles": [ "user" ] } )
        self.assertEqual( ctx.exception.status_code, 403 )


class TestRequireAllRoles( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for require_all_roles() ( ALL-of semantics ).

    Ensures:
        - Empty roles -> ValueError
        - Dependency passes only when ALL roles present, else 403
    """

    def test_empty_roles_raises( self ):
        """
        Ensures:
            - require_all_roles([]) raises ValueError
        """
        with self.assertRaises( ValueError ):
            require_all_roles( [] )

    async def test_user_with_all_roles_passes( self ):
        """
        Ensures:
            - A user holding every required role is returned
        """
        check = require_all_roles( [ "admin", "auditor" ] )
        user = { "roles": [ "admin", "auditor", "user" ] }
        self.assertEqual( await check( user=user ), user )

    async def test_user_missing_a_role_403( self ):
        """
        Ensures:
            - A user missing any required role -> 403
        """
        check = require_all_roles( [ "admin", "auditor" ] )
        with self.assertRaises( HTTPException ) as ctx:
            await check( user={ "roles": [ "admin" ] } )
        self.assertEqual( ctx.exception.status_code, 403 )


class TestRoleHelpers( unittest.TestCase ):
    """
    Tests for the synchronous role-checking helpers.

    Ensures:
        - Each helper returns True/False per the user's roles
    """

    def test_is_admin( self ):
        """
        Ensures:
            - is_admin reflects presence of the "admin" role
        """
        self.assertTrue( is_admin( { "roles": [ "admin", "user" ] } ) )
        self.assertFalse( is_admin( { "roles": [ "user" ] } ) )

    def test_is_user( self ):
        """
        Ensures:
            - is_user reflects presence of the "user" role
        """
        self.assertTrue( is_user( { "roles": [ "user" ] } ) )
        self.assertFalse( is_user( { "roles": [ "admin" ] } ) )

    def test_has_role( self ):
        """
        Ensures:
            - has_role checks an arbitrary role; missing 'roles' defaults to []
        """
        self.assertTrue( has_role( { "roles": [ "beta" ] }, "beta" ) )
        self.assertFalse( has_role( {}, "beta" ) )

    def test_has_any_role( self ):
        """
        Ensures:
            - has_any_role is True if at least one role matches
        """
        self.assertTrue( has_any_role( { "roles": [ "user" ] }, [ "admin", "user" ] ) )
        self.assertFalse( has_any_role( { "roles": [ "guest" ] }, [ "admin", "user" ] ) )

    def test_has_all_roles( self ):
        """
        Ensures:
            - has_all_roles is True only if every role matches
        """
        self.assertTrue( has_all_roles( { "roles": [ "admin", "user" ] }, [ "admin", "user" ] ) )
        self.assertFalse( has_all_roles( { "roles": [ "admin" ] }, [ "admin", "user" ] ) )


if __name__ == "__main__":
    unittest.main()
