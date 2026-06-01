"""
Unit tests for cosa.rest.routers.auth — the authentication router ( 10 endpoints + 2 helpers ).

Every endpoint is exercised by DIRECT call ( not via TestClient ); per handoff Gotcha 2,
every Header/Depends parameter is passed EXPLICITLY so no FieldInfo object leaks into a
branch decision. All collaborators are mocked at the router namespace
( cosa.rest.routers.auth.<fn> ) — the underlying auth services/JWT/email/DB are already
100% elsewhere and are NOT re-tested here. ZERO real DB/JWT/crypto/email/network, ZERO spend.

Seams mocked: create_user, authenticate_user, get_user_by_id, get_user_by_email,
mark_email_verified, reset_password_with_token, update_user_password, create_access_token,
create_refresh_token, decode_and_validate_token, store_refresh_token, rotate_refresh_token,
revoke_refresh_token, send_verification_email, send_password_reset_email,
generate_verification_token, validate_verification_token, generate_password_reset_token,
validate_password_reset_token, check_account_lockout, record_failed_login,
clear_failed_attempts, log_auth_event, config_mgr.get, and jwt.decode ( logout recovery ).

Covers:
    - _create_token_response   ( success / store-fail 500 / generic-exception 500 )
    - _user_dict_to_response   ( with + without last_login_at )
    - register                 ( create-fail 400 / retrieval-fail 500 / success )
    - login                    ( locked 429 / auth-fail 401 / success + client-None arm )
    - refresh                  ( rotate-fail 401 / user-not-found / decode-raise 500 / success )
    - logout                   ( success / revoke-fail 400 / expired-recovery success+fail+no-jti+decode-raise )
    - get_current_user (/me)   ( no-header / len!=2 / not-bearer / not-found 404 / decode-raise 401 / success )
    - change_password          ( no-header / not-bearer / no-sub / decode-raise / incorrect|invalid|not-found|else / success )
    - request_verification     ( already-verified 400 / token-fail 500 / email-fail 500 / success / generic 500 )
    - verify_email             ( token-fail 400 / mark-fail 500 / success / generic 500 )
    - request_password_reset   ( no-user / token-fail / success / generic — all return success )
    - reset_password           ( token-fail 400 / reset-fail 400 / success / generic 500 )
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from fastapi import HTTPException

import cosa.rest.routers.auth as auth_router
from cosa.rest.routers.auth import (
    _create_token_response,
    _user_dict_to_response,
    register,
    login,
    refresh,
    logout,
    get_current_user,
    change_password,
    request_verification,
    verify_email,
    request_password_reset,
    reset_password,
)


def _user_dict( **overrides ):
    """
    Ensures:
        - Returns a complete user dict valid for UserResponse construction
    """
    base = {
        "id"             : "uid-1",
        "email"          : "alice@example.com",
        "roles"          : [ "user" ],
        "email_verified" : True,
        "is_active"      : True,
        "created_at"     : "2026-06-01T00:00:00Z",
        "last_login_at"  : "2026-06-01T01:00:00Z",
    }
    base.update( overrides )
    return base


def _ns( **kw ):
    """
    Ensures:
        - Returns a SimpleNamespace request stand-in ( attribute access, no Pydantic validation )
    """
    return SimpleNamespace( **kw )


class TestCreateTokenResponse( unittest.TestCase ):
    """
    Tests for _create_token_response().

    Ensures:
        - Success builds a bearer TokenResponse with expires_in in seconds
        - A failed refresh-token store raises 500
        - A generic failure is wrapped as 500
    """

    def test_success( self ):
        """
        Ensures:
            - Returns TokenResponse with the generated tokens and seconds-scaled expiry
        """
        with patch( "cosa.rest.routers.auth.create_access_token", return_value="acc" ), \
             patch( "cosa.rest.routers.auth.create_refresh_token", return_value="ref" ), \
             patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "jti": "j1" } ), \
             patch( "cosa.rest.routers.auth.store_refresh_token", return_value=( True, "ok" ) ), \
             patch.object( auth_router.config_mgr, "get", return_value=30 ):
            resp = _create_token_response( "uid-1", "alice@example.com", [ "user" ] )
        self.assertEqual( resp.access_token, "acc" )
        self.assertEqual( resp.refresh_token, "ref" )
        self.assertEqual( resp.token_type, "bearer" )
        self.assertEqual( resp.expires_in, 1800 )

    def test_store_failure_raises_500( self ):
        """
        Ensures:
            - A False store result raises 500 ( re-raised cleanly through except HTTPException )
        """
        with patch( "cosa.rest.routers.auth.create_access_token", return_value="acc" ), \
             patch( "cosa.rest.routers.auth.create_refresh_token", return_value="ref" ), \
             patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "jti": "j1" } ), \
             patch( "cosa.rest.routers.auth.store_refresh_token", return_value=( False, "db down" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                _create_token_response( "uid-1", "a@b.com", [ "user" ] )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "db down", ctx.exception.detail )

    def test_generic_exception_wrapped_500( self ):
        """
        Ensures:
            - An unexpected error is wrapped as 500 "Token generation failed"
        """
        with patch( "cosa.rest.routers.auth.create_access_token", side_effect=Exception( "boom" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                _create_token_response( "uid-1", "a@b.com", [ "user" ] )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Token generation failed", ctx.exception.detail )


class TestUserDictToResponse( unittest.TestCase ):
    """
    Tests for _user_dict_to_response().

    Ensures:
        - All fields map through; last_login_at present or absent both handled
    """

    def test_with_last_login( self ):
        """
        Ensures:
            - A dict with last_login_at maps it onto the response
        """
        resp = _user_dict_to_response( _user_dict() )
        self.assertEqual( resp.id, "uid-1" )
        self.assertEqual( resp.last_login_at, "2026-06-01T01:00:00Z" )

    def test_without_last_login_defaults_none( self ):
        """
        Ensures:
            - A dict lacking last_login_at yields None ( .get default arm )
        """
        d = _user_dict()
        del d[ "last_login_at" ]
        resp = _user_dict_to_response( d )
        self.assertIsNone( resp.last_login_at )


class TestRegister( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the register endpoint.

    Ensures:
        - create-fail -> 400; post-create retrieval-fail -> 500; success -> RegisterResponse
    """

    async def test_create_failure_raises_400( self ):
        """
        Ensures:
            - A failed create_user raises 400 with the service message
        """
        with patch( "cosa.rest.routers.auth.create_user", return_value=( False, "email exists", None ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await register( _ns( email="a@b.com", password="pw", roles=[ "user" ] ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertEqual( ctx.exception.detail, "email exists" )

    async def test_retrieval_failure_raises_500( self ):
        """
        Ensures:
            - A created user that cannot be retrieved raises 500
        """
        with patch( "cosa.rest.routers.auth.create_user", return_value=( True, "", "uid-1" ) ), \
             patch( "cosa.rest.routers.auth.get_user_by_id", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await register( _ns( email="a@b.com", password="pw", roles=[ "user" ] ) )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success_returns_register_response( self ):
        """
        Ensures:
            - A successful registration returns RegisterResponse with user + tokens
        """
        with patch( "cosa.rest.routers.auth.create_user", return_value=( True, "", "uid-1" ) ), \
             patch( "cosa.rest.routers.auth.get_user_by_id", return_value=_user_dict() ), \
             patch( "cosa.rest.routers.auth.create_access_token", return_value="acc" ), \
             patch( "cosa.rest.routers.auth.create_refresh_token", return_value="ref" ), \
             patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "jti": "j1" } ), \
             patch( "cosa.rest.routers.auth.store_refresh_token", return_value=( True, "ok" ) ), \
             patch.object( auth_router.config_mgr, "get", return_value=30 ):
            resp = await register( _ns( email="alice@example.com", password="pw", roles=[ "user" ] ) )
        self.assertEqual( resp.message, "User registered successfully" )
        self.assertEqual( resp.user.id, "uid-1" )
        self.assertEqual( resp.tokens.access_token, "acc" )


class TestLogin( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the login endpoint.

    Ensures:
        - Locked account -> 429; bad credentials -> 401; success -> LoginResponse
        - The request.client-None arm resolves client_ip to "unknown"
    """

    async def test_account_locked_raises_429( self ):
        """
        Ensures:
            - A locked account logs the failure and raises 429 ( client-None -> "unknown" arm )
        """
        with patch( "cosa.rest.routers.auth.check_account_lockout", return_value=( True, "2026-06-01T02:00:00Z" ) ), \
             patch( "cosa.rest.routers.auth.log_auth_event" ) as mock_log:
            with self.assertRaises( HTTPException ) as ctx:
                await login( _ns( email="a@b.com", password="pw" ), _ns( client=None ) )
        self.assertEqual( ctx.exception.status_code, 429 )
        self.assertEqual( mock_log.call_args.kwargs[ "ip_address" ], "unknown" )

    async def test_bad_credentials_raises_401( self ):
        """
        Ensures:
            - Failed authentication records the attempt, logs it, and raises 401
        """
        with patch( "cosa.rest.routers.auth.check_account_lockout", return_value=( False, None ) ), \
             patch( "cosa.rest.routers.auth.authenticate_user", return_value=( False, "bad creds", None ) ), \
             patch( "cosa.rest.routers.auth.record_failed_login" ) as mock_record, \
             patch( "cosa.rest.routers.auth.log_auth_event" ):
            with self.assertRaises( HTTPException ) as ctx:
                await login( _ns( email="a@b.com", password="pw" ), _ns( client=SimpleNamespace( host="1.2.3.4" ) ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        mock_record.assert_called_once()

    async def test_success_returns_login_response( self ):
        """
        Ensures:
            - Valid credentials clear failed attempts, log success, and return LoginResponse
        """
        with patch( "cosa.rest.routers.auth.check_account_lockout", return_value=( False, None ) ), \
             patch( "cosa.rest.routers.auth.authenticate_user", return_value=( True, "", _user_dict() ) ), \
             patch( "cosa.rest.routers.auth.clear_failed_attempts" ) as mock_clear, \
             patch( "cosa.rest.routers.auth.log_auth_event" ), \
             patch( "cosa.rest.routers.auth.create_access_token", return_value="acc" ), \
             patch( "cosa.rest.routers.auth.create_refresh_token", return_value="ref" ), \
             patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "jti": "j1" } ), \
             patch( "cosa.rest.routers.auth.store_refresh_token", return_value=( True, "ok" ) ), \
             patch.object( auth_router.config_mgr, "get", return_value=30 ):
            resp = await login( _ns( email="alice@example.com", password="pw" ),
                                _ns( client=SimpleNamespace( host="1.2.3.4" ) ) )
        self.assertEqual( resp.message, "Login successful" )
        self.assertEqual( resp.user.email, "alice@example.com" )
        mock_clear.assert_called_once()


class TestRefresh( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the refresh endpoint.

    Ensures:
        - rotate-fail -> 401; user-not-found / decode-raise -> 500; success -> RefreshResponse
    """

    async def test_rotate_failure_raises_401( self ):
        """
        Ensures:
            - A failed rotation raises 401 with the service message
        """
        with patch( "cosa.rest.routers.auth.rotate_refresh_token", return_value=( False, "invalid", None ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await refresh( _ns( refresh_token="rt" ) )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_user_not_found_surfaces_500( self ):
        """
        Ensures:
            - A rotated token whose user is missing surfaces as 500
        """
        with patch( "cosa.rest.routers.auth.rotate_refresh_token", return_value=( True, "", "newref" ) ), \
             patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "sub": "uid-1", "email": "a@b.com" } ), \
             patch( "cosa.rest.routers.auth.get_user_by_id", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await refresh( _ns( refresh_token="rt" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "User not found", ctx.exception.detail )

    async def test_decode_exception_wrapped_500( self ):
        """
        Ensures:
            - A decode failure after rotation is wrapped as 500 "Token refresh failed"
        """
        with patch( "cosa.rest.routers.auth.rotate_refresh_token", return_value=( True, "", "newref" ) ), \
             patch( "cosa.rest.routers.auth.decode_and_validate_token", side_effect=Exception( "boom" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await refresh( _ns( refresh_token="rt" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Token refresh failed", ctx.exception.detail )

    async def test_success_returns_refresh_response( self ):
        """
        Ensures:
            - A valid refresh returns a new token pair
        """
        with patch( "cosa.rest.routers.auth.rotate_refresh_token", return_value=( True, "", "newref" ) ), \
             patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "sub": "uid-1", "email": "a@b.com" } ), \
             patch( "cosa.rest.routers.auth.get_user_by_id", return_value=_user_dict() ), \
             patch( "cosa.rest.routers.auth.create_access_token", return_value="acc" ), \
             patch.object( auth_router.config_mgr, "get", return_value=30 ):
            resp = await refresh( _ns( refresh_token="rt" ) )
        self.assertEqual( resp.message, "Token refreshed successfully" )
        self.assertEqual( resp.tokens.access_token, "acc" )
        self.assertEqual( resp.tokens.refresh_token, "newref" )


class TestLogout( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the logout endpoint, including the expired-token recovery path.

    Ensures:
        - Clean revoke -> 200; revoke-fail -> 400
        - On decode failure, the unverified-jti recovery handles success / fail / no-jti / decode-raise
    """

    async def test_clean_logout_success( self ):
        """
        Ensures:
            - A valid token whose jti revokes cleanly returns 200
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "jti": "j1" } ), \
             patch( "cosa.rest.routers.auth.revoke_refresh_token", return_value=( True, "" ) ):
            resp = await logout( _ns( refresh_token="rt" ) )
        self.assertEqual( resp.message, "Logout successful" )

    async def test_revoke_failure_raises_400( self ):
        """
        Ensures:
            - A failed revoke on a valid token raises 400
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "jti": "j1" } ), \
             patch( "cosa.rest.routers.auth.revoke_refresh_token", return_value=( False, "already revoked" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await logout( _ns( refresh_token="rt" ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_expired_recovery_success( self ):
        """
        Ensures:
            - A decode failure triggers unverified-jti extraction; a clean revoke returns 200
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", side_effect=Exception( "expired" ) ), \
             patch( "jwt.decode", return_value={ "jti": "j2" } ), \
             patch( "cosa.rest.routers.auth.revoke_refresh_token", return_value=( True, "" ) ):
            resp = await logout( _ns( refresh_token="rt" ) )
        self.assertEqual( resp.message, "Logout successful" )

    async def test_expired_recovery_revoke_fail_raises_400( self ):
        """
        Ensures:
            - Recovery with a failing revoke falls through to 400
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", side_effect=Exception( "expired" ) ), \
             patch( "jwt.decode", return_value={ "jti": "j2" } ), \
             patch( "cosa.rest.routers.auth.revoke_refresh_token", return_value=( False, "x" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await logout( _ns( refresh_token="rt" ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_expired_recovery_no_jti_raises_400( self ):
        """
        Ensures:
            - Recovery with no jti in the unverified payload raises 400
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", side_effect=Exception( "expired" ) ), \
             patch( "jwt.decode", return_value={} ):
            with self.assertRaises( HTTPException ) as ctx:
                await logout( _ns( refresh_token="rt" ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_expired_recovery_unverified_decode_raises_400( self ):
        """
        Ensures:
            - When even unverified decode raises, the inner except is swallowed and 400 raised
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", side_effect=Exception( "expired" ) ), \
             patch( "jwt.decode", side_effect=Exception( "totally invalid" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await logout( _ns( refresh_token="rt" ) )
        self.assertEqual( ctx.exception.status_code, 400 )


class TestGetCurrentUserMe( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the /me get_current_user endpoint.

    Ensures:
        - Missing / malformed headers -> 401; not-found -> 404; decode-raise -> 401; success -> UserResponse
    """

    async def test_no_authorization_raises_401( self ):
        """
        Ensures:
            - A missing Authorization header raises 401
        """
        with self.assertRaises( HTTPException ) as ctx:
            await get_current_user( authorization=None )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Authorization header required", ctx.exception.detail )

    async def test_single_part_header_raises_401( self ):
        """
        Ensures:
            - A header that does not split into two parts raises 401 ( len != 2 arm )
        """
        with self.assertRaises( HTTPException ) as ctx:
            await get_current_user( authorization="onlyonepart" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_non_bearer_scheme_raises_401( self ):
        """
        Ensures:
            - A two-part non-Bearer header raises 401 ( scheme-mismatch arm )
        """
        with self.assertRaises( HTTPException ) as ctx:
            await get_current_user( authorization="Token abc" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_user_not_found_raises_404( self ):
        """
        Ensures:
            - A valid token whose user is missing raises 404
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "sub": "uid-1" } ), \
             patch( "cosa.rest.routers.auth.get_user_by_id", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_current_user( authorization="Bearer tok" )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_decode_exception_raises_401( self ):
        """
        Ensures:
            - A decode failure is wrapped as 401 "Token validation failed"
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", side_effect=Exception( "bad" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_current_user( authorization="Bearer tok" )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Token validation failed", ctx.exception.detail )

    async def test_success_returns_user_response( self ):
        """
        Ensures:
            - A valid Bearer token returns the user's UserResponse
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "sub": "uid-1" } ), \
             patch( "cosa.rest.routers.auth.get_user_by_id", return_value=_user_dict() ):
            resp = await get_current_user( authorization="Bearer tok" )
        self.assertEqual( resp.id, "uid-1" )


class TestChangePassword( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the change_password endpoint.

    Ensures:
        - Missing / non-Bearer header -> 401; no-sub / decode-raise -> 401
        - Update failure maps message to 400 ( incorrect / invalid ) or 404 ( not found ) or 400 ( else )
        - Success logs the event and returns MessageResponse
    """

    async def test_no_authorization_raises_401( self ):
        """
        Ensures:
            - Missing authorization raises 401 ( first operand )
        """
        with self.assertRaises( HTTPException ) as ctx:
            await change_password( _ns( current_password="old", new_password="new" ), authorization=None )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_non_bearer_raises_401( self ):
        """
        Ensures:
            - A non-Bearer header raises 401 ( second operand )
        """
        with self.assertRaises( HTTPException ) as ctx:
            await change_password( _ns( current_password="old", new_password="new" ), authorization="Basic xyz" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_missing_sub_surfaces_401( self ):
        """
        Ensures:
            - A token payload lacking sub surfaces as 401
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "sub": None } ):
            with self.assertRaises( HTTPException ) as ctx:
                await change_password( _ns( current_password="old", new_password="new" ), authorization="Bearer tok" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_decode_exception_raises_401( self ):
        """
        Ensures:
            - A decode failure is wrapped as 401
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", side_effect=Exception( "bad" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await change_password( _ns( current_password="old", new_password="new" ), authorization="Bearer tok" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_update_incorrect_message_raises_400( self ):
        """
        Ensures:
            - An "incorrect" failure message maps to 400 ( first or-operand )
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "sub": "uid-1" } ), \
             patch( "cosa.rest.routers.auth.update_user_password", return_value=( False, "Current password incorrect" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await change_password( _ns( current_password="old", new_password="new" ), authorization="Bearer tok" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_update_invalid_message_raises_400( self ):
        """
        Ensures:
            - An "invalid" failure message maps to 400 ( second or-operand )
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "sub": "uid-1" } ), \
             patch( "cosa.rest.routers.auth.update_user_password", return_value=( False, "password invalid" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await change_password( _ns( current_password="old", new_password="new" ), authorization="Bearer tok" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_update_not_found_message_raises_404( self ):
        """
        Ensures:
            - A "not found" failure message maps to 404 ( elif arm )
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "sub": "uid-1" } ), \
             patch( "cosa.rest.routers.auth.update_user_password", return_value=( False, "User not found" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await change_password( _ns( current_password="old", new_password="new" ), authorization="Bearer tok" )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_update_other_message_raises_400( self ):
        """
        Ensures:
            - An unclassified failure message maps to 400 ( else arm )
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token", return_value={ "sub": "uid-1" } ), \
             patch( "cosa.rest.routers.auth.update_user_password", return_value=( False, "database exploded" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await change_password( _ns( current_password="old", new_password="new" ), authorization="Bearer tok" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_success_returns_message_response( self ):
        """
        Ensures:
            - A successful change logs the audit event and returns the success message
        """
        with patch( "cosa.rest.routers.auth.decode_and_validate_token",
                    return_value={ "sub": "uid-1", "email": "alice@example.com" } ), \
             patch( "cosa.rest.routers.auth.update_user_password", return_value=( True, "" ) ), \
             patch( "cosa.rest.routers.auth.log_auth_event" ) as mock_log:
            resp = await change_password( _ns( current_password="old", new_password="new" ), authorization="Bearer tok" )
        self.assertEqual( resp.message, "Password changed successfully" )
        mock_log.assert_called_once()


class TestRequestVerification( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the request_verification endpoint ( authenticated via injected user dict ).

    Ensures:
        - Already-verified -> 400; token-gen fail -> 500; email-send fail -> 500;
          success -> MessageResponse; generic error -> 500
    """

    def _user( self, **kw ):
        base = { "email_verified": False, "user_id": "uid-1", "email": "alice@example.com" }
        base.update( kw )
        return base

    async def test_already_verified_raises_400( self ):
        """
        Ensures:
            - An already-verified user raises 400
        """
        with self.assertRaises( HTTPException ) as ctx:
            await request_verification( user=self._user( email_verified=True ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_token_generation_failure_raises_500( self ):
        """
        Ensures:
            - A failed verification-token generation raises 500
        """
        with patch( "cosa.rest.routers.auth.generate_verification_token", return_value=( False, "gen err", None ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await request_verification( user=self._user() )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_email_send_failure_raises_500( self ):
        """
        Ensures:
            - A failed email send raises 500
        """
        with patch( "cosa.rest.routers.auth.generate_verification_token", return_value=( True, "", "tok" ) ), \
             patch( "cosa.rest.routers.auth.send_verification_email", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                await request_verification( user=self._user() )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success_returns_message_response( self ):
        """
        Ensures:
            - A successful send returns the success message
        """
        with patch( "cosa.rest.routers.auth.generate_verification_token", return_value=( True, "", "tok" ) ), \
             patch( "cosa.rest.routers.auth.send_verification_email", return_value=True ):
            resp = await request_verification( user=self._user() )
        self.assertEqual( resp.message, "Verification email sent successfully" )

    async def test_generic_exception_wrapped_500( self ):
        """
        Ensures:
            - An unexpected error is wrapped as 500 "Request verification failed"
        """
        with patch( "cosa.rest.routers.auth.generate_verification_token", side_effect=Exception( "boom" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await request_verification( user=self._user() )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Request verification failed", ctx.exception.detail )


class TestVerifyEmail( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the verify_email endpoint.

    Ensures:
        - token-fail -> 400; mark-fail -> 500; success -> MessageResponse; generic -> 500
    """

    async def test_token_failure_raises_400( self ):
        """
        Ensures:
            - An invalid verification token raises 400
        """
        with patch( "cosa.rest.routers.auth.validate_verification_token", return_value=( False, "bad token", None ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_email( _ns( token="vt" ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_mark_failure_raises_500( self ):
        """
        Ensures:
            - A failed mark_email_verified raises 500
        """
        with patch( "cosa.rest.routers.auth.validate_verification_token", return_value=( True, "", "uid-1" ) ), \
             patch( "cosa.rest.routers.auth.mark_email_verified", return_value=( False, "db err" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_email( _ns( token="vt" ) )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success_returns_message_response( self ):
        """
        Ensures:
            - A valid token marks verified and returns the success message
        """
        with patch( "cosa.rest.routers.auth.validate_verification_token", return_value=( True, "", "uid-1" ) ), \
             patch( "cosa.rest.routers.auth.mark_email_verified", return_value=( True, "" ) ):
            resp = await verify_email( _ns( token="vt" ) )
        self.assertEqual( resp.message, "Email verified successfully" )

    async def test_generic_exception_wrapped_500( self ):
        """
        Ensures:
            - An unexpected error is wrapped as 500 "Email verification failed"
        """
        with patch( "cosa.rest.routers.auth.validate_verification_token", side_effect=Exception( "boom" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_email( _ns( token="vt" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Email verification failed", ctx.exception.detail )


class TestRequestPasswordReset( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the request_password_reset endpoint ( always returns success for security ).

    Ensures:
        - Unknown email / token-fail / success / generic-error ALL return the same success message
    """

    _MSG = "If the email exists, a password reset link has been sent"

    async def test_unknown_email_returns_success( self ):
        """
        Ensures:
            - An unknown email returns the neutral success message without sending
        """
        with patch( "cosa.rest.routers.auth.get_user_by_email", return_value=None ):
            resp = await request_password_reset( _ns( email="nobody@x.io" ) )
        self.assertEqual( resp.message, self._MSG )

    async def test_token_generation_failure_returns_success( self ):
        """
        Ensures:
            - A failed token generation still returns the neutral success message
        """
        with patch( "cosa.rest.routers.auth.get_user_by_email", return_value=_user_dict() ), \
             patch( "cosa.rest.routers.auth.generate_password_reset_token", return_value=( False, "err", None ) ):
            resp = await request_password_reset( _ns( email="alice@example.com" ) )
        self.assertEqual( resp.message, self._MSG )

    async def test_success_returns_success_message( self ):
        """
        Ensures:
            - A known email generates a token, sends the email, and returns the neutral message
        """
        with patch( "cosa.rest.routers.auth.get_user_by_email", return_value=_user_dict() ), \
             patch( "cosa.rest.routers.auth.generate_password_reset_token", return_value=( True, "", "tok" ) ), \
             patch( "cosa.rest.routers.auth.send_password_reset_email", return_value=True ) as mock_send:
            resp = await request_password_reset( _ns( email="alice@example.com" ) )
        self.assertEqual( resp.message, self._MSG )
        mock_send.assert_called_once()

    async def test_generic_exception_returns_success( self ):
        """
        Ensures:
            - An unexpected error is swallowed and still returns the neutral message
        """
        with patch( "cosa.rest.routers.auth.get_user_by_email", side_effect=Exception( "boom" ) ):
            resp = await request_password_reset( _ns( email="alice@example.com" ) )
        self.assertEqual( resp.message, self._MSG )


class TestResetPassword( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the reset_password endpoint.

    Ensures:
        - token-fail -> 400; reset-fail -> 400; success -> MessageResponse; generic -> 500
    """

    async def test_token_failure_raises_400( self ):
        """
        Ensures:
            - An invalid reset token raises 400
        """
        with patch( "cosa.rest.routers.auth.validate_password_reset_token", return_value=( False, "bad token", None ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await reset_password( _ns( token="rt", new_password="newpw" ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_reset_failure_raises_400( self ):
        """
        Ensures:
            - A failed password reset ( e.g. weak password ) raises 400
        """
        with patch( "cosa.rest.routers.auth.validate_password_reset_token", return_value=( True, "", "uid-1" ) ), \
             patch( "cosa.rest.routers.auth.reset_password_with_token", return_value=( False, "too weak" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await reset_password( _ns( token="rt", new_password="newpw" ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_success_returns_message_response( self ):
        """
        Ensures:
            - A valid token + acceptable password returns the success message
        """
        with patch( "cosa.rest.routers.auth.validate_password_reset_token", return_value=( True, "", "uid-1" ) ), \
             patch( "cosa.rest.routers.auth.reset_password_with_token", return_value=( True, "" ) ):
            resp = await reset_password( _ns( token="rt", new_password="newpw" ) )
        self.assertEqual( resp.message, "Password reset successfully" )

    async def test_generic_exception_wrapped_500( self ):
        """
        Ensures:
            - An unexpected error is wrapped as 500 "Password reset failed"
        """
        with patch( "cosa.rest.routers.auth.validate_password_reset_token", side_effect=Exception( "boom" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await reset_password( _ns( token="rt", new_password="newpw" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Password reset failed", ctx.exception.detail )


if __name__ == "__main__":
    unittest.main()
