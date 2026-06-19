"""
Unit tests for cosa.rest.jwt_service.

The PyJWT crypto seam ( jwt.encode / jwt.decode ) is mocked so token generation and
decoding are deterministic with no real signing/verification. The module-level
SECRET_KEY configuration branches ( import-time ) are covered via importlib.reload
under patched os.environ — the only way to exercise the production-raise and
secret-from-env arms.

Covered:
    - create_access_token   ( validation, payload shape, roles default )
    - create_refresh_token  ( validation, token_type="refresh" )
    - decode_and_validate_token ( type-match matrix )
    - _generate_jti         ( unique string ids )
    - module-level SECRET_KEY config ( dev default / from-env / production-raise )
"""

import os
import importlib
import unittest
from unittest.mock import patch

import cosa.rest.jwt_service as jwt_service
from cosa.rest.jwt_service import (
    create_access_token,
    create_refresh_token,
    decode_and_validate_token,
    _generate_jti,
)


class TestCreateAccessToken( unittest.TestCase ):
    """
    Tests for create_access_token().

    Ensures:
        - Missing user_id/email raises ValueError before encoding
        - Payload carries sub/email/roles/exp/iat/jti
        - Empty roles default to ["user"]
    """

    def test_missing_user_id_raises( self ):
        """
        Ensures:
            - Empty user_id raises ValueError
        """
        with self.assertRaises( ValueError ):
            create_access_token( "", "user@example.com", [ "user" ] )

    def test_missing_email_raises( self ):
        """
        Ensures:
            - Empty email raises ValueError ( user_id present )
        """
        with self.assertRaises( ValueError ):
            create_access_token( "uid_1", "", [ "user" ] )

    def test_payload_shape_and_roles_preserved( self ):
        """
        Ensures:
            - Encoded payload carries the expected claims with supplied roles
        """
        with patch( 'cosa.rest.jwt_service.jwt' ) as mock_jwt:
            mock_jwt.encode.return_value = "fake.access.token"
            token = create_access_token( "uid_1", "user@example.com", [ "user", "admin" ] )
            self.assertEqual( token, "fake.access.token" )
            payload = mock_jwt.encode.call_args[0][0]
            self.assertEqual( payload[ "sub" ], "uid_1" )
            self.assertEqual( payload[ "email" ], "user@example.com" )
            self.assertEqual( payload[ "roles" ], [ "user", "admin" ] )
            for claim in ( "exp", "iat", "jti" ):
                self.assertIn( claim, payload )

    def test_empty_roles_defaults_to_user( self ):
        """
        Ensures:
            - Falsy roles default to ["user"] ( covers the roles-or-default branch )
        """
        with patch( 'cosa.rest.jwt_service.jwt' ) as mock_jwt:
            mock_jwt.encode.return_value = "fake.access.token"
            create_access_token( "uid_1", "user@example.com", [] )
            payload = mock_jwt.encode.call_args[0][0]
            self.assertEqual( payload[ "roles" ], [ "user" ] )


class TestCreateRefreshToken( unittest.TestCase ):
    """
    Tests for create_refresh_token().

    Ensures:
        - Missing user_id/email raises ValueError
        - Payload carries token_type="refresh"
    """

    def test_missing_user_id_raises( self ):
        """
        Ensures:
            - Empty user_id raises ValueError
        """
        with self.assertRaises( ValueError ):
            create_refresh_token( "", "user@example.com" )

    def test_missing_email_raises( self ):
        """
        Ensures:
            - Empty email raises ValueError ( user_id present )
        """
        with self.assertRaises( ValueError ):
            create_refresh_token( "uid_1", "" )

    def test_payload_marks_token_type_refresh( self ):
        """
        Ensures:
            - Refresh payload includes token_type="refresh" + core claims
        """
        with patch( 'cosa.rest.jwt_service.jwt' ) as mock_jwt:
            mock_jwt.encode.return_value = "fake.refresh.token"
            token = create_refresh_token( "uid_1", "user@example.com" )
            self.assertEqual( token, "fake.refresh.token" )
            payload = mock_jwt.encode.call_args[0][0]
            self.assertEqual( payload[ "token_type" ], "refresh" )
            self.assertEqual( payload[ "sub" ], "uid_1" )


class TestDecodeAndValidateToken( unittest.TestCase ):
    """
    Tests for decode_and_validate_token().

    Ensures:
        - Full token_type-vs-expected_type validation matrix
    """

    def test_no_expected_type_returns_payload( self ):
        """
        Ensures:
            - With no expected_type, the decoded payload is returned as-is
        """
        with patch( 'cosa.rest.jwt_service.jwt' ) as mock_jwt:
            mock_jwt.decode.return_value = { "sub": "u", "token_type": "refresh" }
            self.assertEqual( decode_and_validate_token( "tok" ), { "sub": "u", "token_type": "refresh" } )

    def test_refresh_used_as_access_raises( self ):
        """
        Ensures:
            - expected="access" + token_type="refresh" -> ValueError
        """
        with patch( 'cosa.rest.jwt_service.jwt' ) as mock_jwt:
            mock_jwt.decode.return_value = { "token_type": "refresh" }
            with self.assertRaises( ValueError ):
                decode_and_validate_token( "tok", expected_type="access" )

    def test_access_as_access_ok( self ):
        """
        Ensures:
            - expected="access" + token_type="access" returns payload
        """
        with patch( 'cosa.rest.jwt_service.jwt' ) as mock_jwt:
            mock_jwt.decode.return_value = { "token_type": "access" }
            self.assertEqual( decode_and_validate_token( "tok", expected_type="access" ), { "token_type": "access" } )

    def test_non_refresh_as_refresh_raises( self ):
        """
        Ensures:
            - expected="refresh" + token_type != "refresh" -> ValueError
        """
        with patch( 'cosa.rest.jwt_service.jwt' ) as mock_jwt:
            mock_jwt.decode.return_value = { "token_type": "access" }
            with self.assertRaises( ValueError ):
                decode_and_validate_token( "tok", expected_type="refresh" )

    def test_refresh_as_refresh_ok( self ):
        """
        Ensures:
            - expected="refresh" + token_type="refresh" returns payload
        """
        with patch( 'cosa.rest.jwt_service.jwt' ) as mock_jwt:
            mock_jwt.decode.return_value = { "token_type": "refresh" }
            self.assertEqual( decode_and_validate_token( "tok", expected_type="refresh" ), { "token_type": "refresh" } )


class TestGenerateJti( unittest.TestCase ):
    """
    Tests for _generate_jti().

    Ensures:
        - Returns unique non-empty string identifiers
    """

    def test_generates_unique_strings( self ):
        """
        Ensures:
            - Two calls yield distinct, non-empty strings
        """
        a, b = _generate_jti(), _generate_jti()
        self.assertIsInstance( a, str )
        self.assertTrue( a )
        self.assertNotEqual( a, b )


class TestModuleLevelSecretKeyConfig( unittest.TestCase ):
    """
    Tests for the import-time SECRET_KEY configuration branches.

    Ensures:
        - JWT_SECRET_KEY from env is honored ( the `not SECRET_KEY` False arm )
        - Production without a secret raises ValueError ( the production True arm )

    Reloads the module under patched os.environ and ALWAYS restores it afterward so
    later tests / suites see the normal dev-default module state.
    """

    def tearDown( self ):
        """
        Ensures:
            - jwt_service is reloaded back to the ambient ( dev-default ) environment
        """
        importlib.reload( jwt_service )

    def test_secret_key_loaded_from_env( self ):
        """
        Ensures:
            - When JWT_SECRET_KEY is set, SECRET_KEY adopts it ( skips the warning block )
        """
        env = dict( os.environ )
        env[ "JWT_SECRET_KEY" ] = "my-explicit-secret-key"
        env.pop( "ENVIRONMENT", None )
        with patch.dict( os.environ, env, clear=True ):
            importlib.reload( jwt_service )
            self.assertEqual( jwt_service.SECRET_KEY, "my-explicit-secret-key" )

    def test_production_without_secret_raises( self ):
        """
        Ensures:
            - production environment + missing JWT_SECRET_KEY raises at import
        """
        env = dict( os.environ )
        env.pop( "JWT_SECRET_KEY", None )
        env[ "ENVIRONMENT" ] = "production"
        with patch.dict( os.environ, env, clear=True ):
            with self.assertRaises( ValueError ):
                importlib.reload( jwt_service )


if __name__ == "__main__":
    unittest.main()
