"""
Unit tests for cosa.rest.auth — the unified token-verification orchestrator.

Every external seam is mocked ( no real JWT/DB/firebase/network, ZERO API spend ):
    - ConfigurationManager ( cosa.config.configuration_manager )  -> auth-mode source
    - verify_jwt_token / verify_mock_token / verify_firebase_token -> dispatch targets
    - decode_and_validate_token ( cosa.rest.jwt_service )         -> JWT decode seam
    - get_user_by_id ( cosa.rest.user_service )                   -> JWT user lookup
    - get_user_info / email_to_system_id ( .user_id_generator )   -> mock-token lookup
    - HTTPBearer.__call__ ( fastapi.security )                    -> bearer-scheme parent
    - init_firebase / verify_firebase_token                       -> dependency wiring

Covers every branch:
    - TokenExpiredException                ( construction / 401 detail )
    - init_firebase                        ( uninitialized -> set; already-init no-op )
    - HTTPBearerWith401.__call__           ( creds None +header / None no-header / creds present )
    - verify_token                         ( env-override / config; jwt / mock / firebase / unsupported )
    - verify_jwt_token                     ( decode-fail expired|signature|malformed|other; missing sub;
                                             user-not-found; inactive; ExpiredSignatureError; success )
    - verify_mock_token                    ( non-str; empty; too-long; bad-prefix; email bad/good;
                                             legacy empty/good; unknown-id default; known-id lookup )
    - verify_firebase_token                ( delegates to verify_token )
    - get_current_user / get_current_user_id / get_optional_user ( all arms )

Direct-call discipline ( handoff Gotcha 2 ): every Depends/Header param is passed
EXPLICITLY so no FieldInfo object leaks into a branch decision.
"""

import os
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi import HTTPException
from jwt.exceptions import ExpiredSignatureError

import cosa.rest.auth as auth
from cosa.rest.auth import (
    TokenExpiredException,
    init_firebase,
    HTTPBearerWith401,
    verify_token,
    verify_jwt_token,
    verify_mock_token,
    verify_firebase_token,
    get_current_user,
    get_current_user_id,
    get_optional_user,
)


class _FirebaseStateMixin:
    """
    Mixin that snapshots + restores the module-level FIREBASE_INITIALIZED global so
    init_firebase()-touching tests never leak state into one another.

    Ensures:
        - auth.FIREBASE_INITIALIZED is restored to its pre-test value in tearDown
    """

    def setUp( self ):
        self._saved_fb = auth.FIREBASE_INITIALIZED

    def tearDown( self ):
        auth.FIREBASE_INITIALIZED = self._saved_fb


class TestTokenExpiredException( unittest.TestCase ):
    """
    Tests for TokenExpiredException.

    Ensures:
        - Constructs a 401 HTTPException with the canonical detail
    """

    def test_construction( self ):
        """
        Ensures:
            - status_code is 401 and detail is "Token expired"
        """
        exc = TokenExpiredException()
        self.assertIsInstance( exc, HTTPException )
        self.assertEqual( exc.status_code, 401 )
        self.assertEqual( exc.detail, "Token expired" )


class TestInitFirebase( _FirebaseStateMixin, unittest.TestCase ):
    """
    Tests for init_firebase().

    Ensures:
        - The uninitialized arm sets the global True and prints
        - The already-initialized arm is a no-op ( idempotent )
    """

    def test_initializes_when_unset( self ):
        """
        Ensures:
            - Starting False, init_firebase sets FIREBASE_INITIALIZED True
        """
        auth.FIREBASE_INITIALIZED = False
        init_firebase()
        self.assertTrue( auth.FIREBASE_INITIALIZED )

    def test_noop_when_already_initialized( self ):
        """
        Ensures:
            - Starting True, init_firebase leaves the global True ( no-op arm )
        """
        auth.FIREBASE_INITIALIZED = True
        init_firebase()
        self.assertTrue( auth.FIREBASE_INITIALIZED )


class TestHTTPBearerWith401( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for HTTPBearerWith401.__call__.

    The HTTPBearer parent __call__ is mocked to control the credentials result.

    Ensures:
        - None credentials + Authorization header present -> 401 ( logs header arm )
        - None credentials + no header -> 401 ( logs client-host arm )
        - Present credentials -> returned unchanged
    """

    def _make_request( self, auth_header ):
        """
        Requires:
            - auth_header is the value .headers.get( "Authorization" ) should return

        Ensures:
            - Returns a Mock request with .headers.get and .client.host wired
        """
        request = MagicMock()
        request.headers.get.return_value = auth_header
        request.client.host = "203.0.113.7"
        return request

    async def test_none_credentials_with_header_raises_401( self ):
        """
        Ensures:
            - Missing credentials while a ( malformed ) Authorization header is present
              raises 401 with the WWW-Authenticate header
        """
        bearer = HTTPBearerWith401()
        with patch.object( auth.HTTPBearer, "__call__", new=AsyncMock( return_value=None ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await bearer( self._make_request( "Token abcdefghijklmnop" ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertEqual( ctx.exception.headers, { "WWW-Authenticate": "Bearer" } )

    async def test_none_credentials_no_header_raises_401( self ):
        """
        Ensures:
            - Missing credentials and no Authorization header raises 401 ( client-host log arm )
        """
        bearer = HTTPBearerWith401()
        with patch.object( auth.HTTPBearer, "__call__", new=AsyncMock( return_value=None ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await bearer( self._make_request( None ) )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_present_credentials_returned( self ):
        """
        Ensures:
            - Valid credentials are returned unchanged
        """
        creds = MagicMock()
        bearer = HTTPBearerWith401()
        with patch.object( auth.HTTPBearer, "__call__", new=AsyncMock( return_value=creds ) ):
            result = await bearer( self._make_request( "Bearer good" ) )
        self.assertIs( result, creds )


class TestVerifyToken( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for verify_token() — the auth-mode dispatcher.

    Ensures:
        - AUTH_MODE env override bypasses ConfigurationManager
        - Config-sourced mode used when env unset
        - jwt / mock / firebase modes dispatch to the matching verifier
        - An unsupported mode raises 401
    """

    async def test_env_override_dispatches_jwt( self ):
        """
        Ensures:
            - AUTH_MODE=jwt routes to verify_jwt_token without touching ConfigurationManager
        """
        with patch.dict( os.environ, { "AUTH_MODE": "jwt" }, clear=False ):
            with patch( "cosa.rest.auth.verify_jwt_token", new=AsyncMock( return_value={ "uid": "j" } ) ) as mock_jwt, \
                 patch( "cosa.config.configuration_manager.ConfigurationManager" ) as mock_cm:
                result = await verify_token( "tok" )
        self.assertEqual( result, { "uid": "j" } )
        mock_jwt.assert_awaited_once_with( "tok" )
        mock_cm.assert_not_called()

    async def test_config_sourced_mock_mode( self ):
        """
        Ensures:
            - With AUTH_MODE unset, the ConfigurationManager-reported "mock" mode dispatches
              to verify_mock_token
        """
        mock_cm_instance = MagicMock()
        mock_cm_instance.get.return_value = "mock"
        with patch.dict( os.environ, {}, clear=True ):
            with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=mock_cm_instance ), \
                 patch( "cosa.rest.auth.verify_mock_token", new=AsyncMock( return_value={ "uid": "m" } ) ) as mock_mock:
                result = await verify_token( "tok" )
        self.assertEqual( result, { "uid": "m" } )
        mock_mock.assert_awaited_once_with( "tok" )
        mock_cm_instance.get.assert_called_once_with( "auth mode", default="mock" )

    async def test_firebase_mode_dispatch( self ):
        """
        Ensures:
            - AUTH_MODE=firebase routes to verify_firebase_token
        """
        with patch.dict( os.environ, { "AUTH_MODE": "firebase" }, clear=False ):
            with patch( "cosa.rest.auth.verify_firebase_token", new=AsyncMock( return_value={ "uid": "f" } ) ) as mock_fb:
                result = await verify_token( "tok" )
        self.assertEqual( result, { "uid": "f" } )
        mock_fb.assert_awaited_once_with( "tok" )

    async def test_unsupported_mode_raises_401( self ):
        """
        Ensures:
            - An unrecognized auth mode raises 401 with the mode echoed in the detail
        """
        with patch.dict( os.environ, { "AUTH_MODE": "saml" }, clear=False ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_token( "tok" )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "saml", ctx.exception.detail )


class TestVerifyJwtToken( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for verify_jwt_token().

    decode_and_validate_token + get_user_by_id are mocked at their source modules.

    Ensures:
        - decode failures log the right diagnostic arm and surface as 401
        - ExpiredSignatureError maps to TokenExpiredException
        - missing sub / user-not-found / inactive each raise 401
        - the success path returns the firebase-compatible user dict
    """

    def _patch_decode( self, **kwargs ):
        return patch( "cosa.rest.jwt_service.decode_and_validate_token", **kwargs )

    def _patch_get_user( self, **kwargs ):
        return patch( "cosa.rest.user_service.get_user_by_id", **kwargs )

    async def test_decode_expired_arm_raises_401( self ):
        """
        Ensures:
            - A generic decode exception mentioning "expired" logs the expired arm and
              surfaces as a 401 ( outer generic-Exception handler )
        """
        with self._patch_decode( side_effect=ValueError( "token is expired now" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_jwt_token( "tok" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_decode_signature_arm_raises_401( self ):
        """
        Ensures:
            - A decode exception mentioning "signature" ( not expired ) -> 401
        """
        with self._patch_decode( side_effect=ValueError( "bad signature detected" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_jwt_token( "tok" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_decode_malformed_arm_raises_401( self ):
        """
        Ensures:
            - A decode exception mentioning "malformed" -> 401
        """
        with self._patch_decode( side_effect=ValueError( "malformed payload" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_jwt_token( "tok" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_decode_other_arm_raises_401( self ):
        """
        Ensures:
            - A decode exception matching none of the keyword arms hits the generic
              diagnostic else-branch and -> 401
        """
        with self._patch_decode( side_effect=ValueError( "kaboom" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_jwt_token( "tok" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_expired_signature_error_maps_to_token_expired( self ):
        """
        Ensures:
            - ExpiredSignatureError raised by decode surfaces as TokenExpiredException ( 401 )
        """
        with self._patch_decode( side_effect=ExpiredSignatureError( "Signature has expired" ) ):
            with self.assertRaises( TokenExpiredException ) as ctx:
                await verify_jwt_token( "tok" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_missing_sub_raises_401( self ):
        """
        Ensures:
            - A decoded payload with no "sub" raises 401 ( missing user ID )
        """
        with self._patch_decode( return_value={ "sub": None } ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_jwt_token( "tok" )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "missing user ID", ctx.exception.detail )

    async def test_user_not_found_raises_401( self ):
        """
        Ensures:
            - A valid sub whose user lookup returns falsy raises 401 ( user not found )
        """
        with self._patch_decode( return_value={ "sub": "u1", "iat": 123 } ), \
             self._patch_get_user( return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_jwt_token( "tok" )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "User not found", ctx.exception.detail )

    async def test_inactive_user_raises_401( self ):
        """
        Ensures:
            - An is_active=False user raises 401 ( account inactive )
        """
        user = { "id": "u1", "email": "a@b.com", "email_verified": True, "roles": [ "user" ], "is_active": False }
        with self._patch_decode( return_value={ "sub": "u1", "iat": 123 } ), \
             self._patch_get_user( return_value=user ):
            with self.assertRaises( HTTPException ) as ctx:
                await verify_jwt_token( "tok" )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "inactive", ctx.exception.detail )

    async def test_success_returns_firebase_compatible_dict( self ):
        """
        Ensures:
            - A valid active user returns the firebase-compatible dict with derived name + claims
        """
        user = { "id": "u1", "email": "alice@example.com", "email_verified": True, "roles": [ "user", "admin" ] }
        with self._patch_decode( return_value={ "sub": "u1", "iat": 999 } ), \
             self._patch_get_user( return_value=user ):
            result = await verify_jwt_token( "tok" )
        self.assertEqual( result[ "uid" ], "u1" )
        self.assertEqual( result[ "email" ], "alice@example.com" )
        self.assertEqual( result[ "name" ], "alice" )
        self.assertEqual( result[ "roles" ], [ "user", "admin" ] )
        self.assertEqual( result[ "iss" ], "lupin-jwt" )
        self.assertEqual( result[ "auth_time" ], 999 )
        self.assertEqual( result[ "user_id" ], "u1" )

    async def test_success_defaults_is_active_true_when_absent( self ):
        """
        Ensures:
            - A user dict lacking is_active is treated as active ( default True arm )
        """
        user = { "id": "u2", "email": "bob@x.io", "email_verified": False, "roles": [ "user" ] }
        with self._patch_decode( return_value={ "sub": "u2", "iat": 1 } ), \
             self._patch_get_user( return_value=user ):
            result = await verify_jwt_token( "tok" )
        self.assertEqual( result[ "uid" ], "u2" )
        self.assertFalse( result[ "email_verified" ] )


class TestVerifyMockToken( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for verify_mock_token().

    get_user_info + email_to_system_id are mocked at the auth module namespace.

    Ensures:
        - All input-validation guards raise 401
        - Email-based and legacy formats resolve a system id
        - Unknown ids generate a default user; known ids merge a uid field
    """

    async def test_non_string_token_raises_401( self ):
        """
        Ensures:
            - A non-string token raises 401 ( isinstance guard )
        """
        with self.assertRaises( HTTPException ) as ctx:
            await verify_mock_token( 12345 )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_empty_token_raises_401( self ):
        """
        Ensures:
            - A whitespace-only token raises 401 ( strip guard )
        """
        with self.assertRaises( HTTPException ) as ctx:
            await verify_mock_token( "   " )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_overlong_token_raises_401( self ):
        """
        Ensures:
            - A token exceeding 500 chars raises 401 ( DoS guard )
        """
        with self.assertRaises( HTTPException ) as ctx:
            await verify_mock_token( "a" * 501 )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_bad_prefix_raises_401( self ):
        """
        Ensures:
            - A token not starting with mock_token_ raises 401 ( format guard )
        """
        with self.assertRaises( HTTPException ) as ctx:
            await verify_mock_token( "not_a_mock_token" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_email_format_bad_email_raises_401( self ):
        """
        Ensures:
            - An email-form token whose payload lacks "@" raises 401
        """
        with self.assertRaises( HTTPException ) as ctx:
            await verify_mock_token( "mock_token_email_noatsign" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_email_format_empty_email_raises_401( self ):
        """
        Ensures:
            - An email-form token with an empty payload raises 401 ( not email arm )
        """
        with self.assertRaises( HTTPException ) as ctx:
            await verify_mock_token( "mock_token_email_" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_legacy_empty_system_id_raises_401( self ):
        """
        Ensures:
            - The bare "mock_token_" legacy form ( empty system id ) raises 401
        """
        with self.assertRaises( HTTPException ) as ctx:
            await verify_mock_token( "mock_token_" )
        self.assertEqual( ctx.exception.status_code, 401 )

    async def test_email_format_known_user_merges_uid( self ):
        """
        Ensures:
            - A valid email token converts to a system id, looks up the user, and merges uid
        """
        with patch( "cosa.rest.auth.email_to_system_id", return_value="alice_sys" ) as mock_e2s, \
             patch( "cosa.rest.auth.get_user_info",
                    return_value={ "email": "alice@example.com", "email_verified": True, "name": "Alice" } ):
            result = await verify_mock_token( "mock_token_email_alice@example.com" )
        mock_e2s.assert_called_once_with( "alice@example.com" )
        self.assertEqual( result[ "uid" ], "alice_sys" )
        self.assertEqual( result[ "email" ], "alice@example.com" )
        self.assertEqual( result[ "name" ], "Alice" )
        self.assertEqual( result[ "sub" ], "alice_sys" )

    async def test_legacy_unknown_id_generates_default_user( self ):
        """
        Ensures:
            - A legacy token for an unknown system id generates a default user dict
        """
        with patch( "cosa.rest.auth.get_user_info", return_value=None ):
            result = await verify_mock_token( "mock_token_charlie_dev" )
        self.assertEqual( result[ "uid" ], "charlie_dev" )
        self.assertEqual( result[ "email" ], "charlie_dev@generated.local" )
        self.assertEqual( result[ "name" ], "Charlie" )
        self.assertFalse( result[ "email_verified" ] )

    async def test_legacy_known_id_merges_uid( self ):
        """
        Ensures:
            - A legacy token for a known system id merges the uid into the looked-up record
        """
        with patch( "cosa.rest.auth.get_user_info",
                    return_value={ "email": "dora@x.io", "email_verified": True, "name": "Dora" } ):
            result = await verify_mock_token( "mock_token_dora_sys" )
        self.assertEqual( result[ "uid" ], "dora_sys" )
        self.assertEqual( result[ "email" ], "dora@x.io" )


class TestVerifyFirebaseToken( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for verify_firebase_token() ( backward-compat shim ).

    Ensures:
        - Delegates directly to verify_token and returns its result
    """

    async def test_delegates_to_verify_token( self ):
        """
        Ensures:
            - verify_firebase_token forwards the token to verify_token and returns its value
        """
        with patch( "cosa.rest.auth.verify_token", new=AsyncMock( return_value={ "uid": "z" } ) ) as mock_vt:
            result = await verify_firebase_token( "tok" )
        self.assertEqual( result, { "uid": "z" } )
        mock_vt.assert_awaited_once_with( "tok" )


class TestGetCurrentUser( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the get_current_user / get_current_user_id dependencies.

    Ensures:
        - get_current_user initializes firebase, verifies the bearer token, returns the user
        - get_current_user_id extracts the uid
    """

    async def test_get_current_user_returns_user_info( self ):
        """
        Ensures:
            - init_firebase is called and the verified user dict is returned
        """
        creds = MagicMock()
        creds.credentials = "the-token"
        with patch( "cosa.rest.auth.init_firebase" ) as mock_init, \
             patch( "cosa.rest.auth.verify_firebase_token",
                    new=AsyncMock( return_value={ "uid": "u9" } ) ) as mock_verify:
            result = await get_current_user( credentials=creds )
        mock_init.assert_called_once_with()
        mock_verify.assert_awaited_once_with( "the-token" )
        self.assertEqual( result, { "uid": "u9" } )

    async def test_get_current_user_id_extracts_uid( self ):
        """
        Ensures:
            - get_current_user_id returns the uid field from the passed user dict
        """
        result = await get_current_user_id( current_user={ "uid": "abc-123" } )
        self.assertEqual( result, "abc-123" )


class TestGetOptionalUser( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for get_optional_user().

    Ensures:
        - No credentials -> None
        - Valid credentials -> verified user
        - Verification failure -> None ( swallowed )
    """

    async def test_none_credentials_returns_none( self ):
        """
        Ensures:
            - Passing no credentials returns None without verifying
        """
        result = await get_optional_user( credentials=None )
        self.assertIsNone( result )

    async def test_valid_credentials_returns_user( self ):
        """
        Ensures:
            - Valid credentials are verified and the user dict returned
        """
        creds = MagicMock()
        creds.credentials = "tok"
        with patch( "cosa.rest.auth.init_firebase" ), \
             patch( "cosa.rest.auth.verify_firebase_token",
                    new=AsyncMock( return_value={ "uid": "opt" } ) ):
            result = await get_optional_user( credentials=creds )
        self.assertEqual( result, { "uid": "opt" } )

    async def test_verification_failure_returns_none( self ):
        """
        Ensures:
            - An exception during verification is swallowed and None is returned
        """
        creds = MagicMock()
        creds.credentials = "tok"
        with patch( "cosa.rest.auth.init_firebase" ), \
             patch( "cosa.rest.auth.verify_firebase_token",
                    new=AsyncMock( side_effect=Exception( "boom" ) ) ):
            result = await get_optional_user( credentials=creds )
        self.assertIsNone( result )


if __name__ == "__main__":
    unittest.main()
