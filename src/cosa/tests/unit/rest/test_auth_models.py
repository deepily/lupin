"""
Unit tests for cosa.rest.auth_models.

These are pure Pydantic request/response models ( no methods or branches ), so the
tests verify the field CONTRACTS that matter at runtime: required vs optional fields,
default values, length constraints, EmailStr validation, and nested-model composition.
No external seams — model validation is in-process.
"""

import unittest

from pydantic import ValidationError

from cosa.rest.auth_models import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    LogoutRequest,
    TokenResponse,
    UserResponse,
    RegisterResponse,
    LoginResponse,
    RefreshResponse,
    LogoutResponse,
    ErrorResponse,
    RequestVerificationRequest,
    VerifyEmailRequest,
    RequestPasswordResetRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    MessageResponse,
)


def _valid_user_response():
    """
    Ensures:
        - Returns a fully-populated UserResponse for reuse in nested-model tests
    """
    return UserResponse(
        id="550e8400-e29b-41d4-a716-446655440000",
        email="user@example.com",
        roles=[ "user" ],
        email_verified=False,
        is_active=True,
        created_at="2025-09-29T12:34:56.789012",
    )


def _valid_token_response():
    """
    Ensures:
        - Returns a fully-populated TokenResponse for reuse in nested-model tests
    """
    return TokenResponse( access_token="acc", refresh_token="ref", expires_in=1800 )


class TestRequestModels( unittest.TestCase ):
    """
    Tests for the authentication REQUEST models.

    Ensures:
        - Required fields, defaults, length constraints, and EmailStr validation
    """

    def test_register_request_valid_and_role_default( self ):
        """
        Ensures:
            - Valid registration parses; roles defaults to None
        """
        req = RegisterRequest( email="user@example.com", password="SecurePass123!" )
        self.assertEqual( req.email, "user@example.com" )
        self.assertIsNone( req.roles )

    def test_register_request_explicit_roles( self ):
        """
        Ensures:
            - Explicit roles list is preserved
        """
        req = RegisterRequest( email="user@example.com", password="SecurePass123!", roles=[ "user", "admin" ] )
        self.assertEqual( req.roles, [ "user", "admin" ] )

    def test_register_request_password_too_short( self ):
        """
        Ensures:
            - Password under min_length=8 raises ValidationError
        """
        with self.assertRaises( ValidationError ):
            RegisterRequest( email="user@example.com", password="short" )

    def test_register_request_invalid_email( self ):
        """
        Ensures:
            - Malformed email raises ValidationError ( EmailStr )
        """
        with self.assertRaises( ValidationError ):
            RegisterRequest( email="not-an-email", password="SecurePass123!" )

    def test_login_request_valid( self ):
        """
        Ensures:
            - Valid login parses with email + password
        """
        req = LoginRequest( email="user@example.com", password="SecurePass123!" )
        self.assertEqual( req.password, "SecurePass123!" )

    def test_login_request_invalid_email( self ):
        """
        Ensures:
            - Malformed login email raises ValidationError
        """
        with self.assertRaises( ValidationError ):
            LoginRequest( email="bad", password="x" )

    def test_refresh_and_logout_requests( self ):
        """
        Ensures:
            - Refresh/Logout requests carry the refresh_token string
        """
        self.assertEqual( RefreshRequest( refresh_token="tok" ).refresh_token, "tok" )
        self.assertEqual( LogoutRequest( refresh_token="tok" ).refresh_token, "tok" )

    def test_refresh_request_missing_token( self ):
        """
        Ensures:
            - Missing required refresh_token raises ValidationError
        """
        with self.assertRaises( ValidationError ):
            RefreshRequest()

    def test_request_verification_request_empty_body( self ):
        """
        Ensures:
            - RequestVerificationRequest accepts an empty body ( uses token identity )
        """
        self.assertIsInstance( RequestVerificationRequest(), RequestVerificationRequest )

    def test_verify_email_request( self ):
        """
        Ensures:
            - Verification token is required and preserved
        """
        self.assertEqual( VerifyEmailRequest( token="abc123" ).token, "abc123" )
        with self.assertRaises( ValidationError ):
            VerifyEmailRequest()

    def test_request_password_reset_request_email_validation( self ):
        """
        Ensures:
            - Reset-request email is EmailStr-validated
        """
        self.assertEqual( RequestPasswordResetRequest( email="user@example.com" ).email, "user@example.com" )
        with self.assertRaises( ValidationError ):
            RequestPasswordResetRequest( email="bad" )

    def test_reset_password_request_new_password_min_length( self ):
        """
        Ensures:
            - new_password under min_length=8 raises ValidationError
        """
        ok = ResetPasswordRequest( token="xyz", new_password="NewPass123!" )
        self.assertEqual( ok.token, "xyz" )
        with self.assertRaises( ValidationError ):
            ResetPasswordRequest( token="xyz", new_password="short" )

    def test_change_password_request_constraints( self ):
        """
        Ensures:
            - current_password requires min_length=1, new_password min_length=8
        """
        ok = ChangePasswordRequest( current_password="OldPass123!", new_password="NewPass123!" )
        self.assertEqual( ok.current_password, "OldPass123!" )
        with self.assertRaises( ValidationError ):
            ChangePasswordRequest( current_password="", new_password="NewPass123!" )
        with self.assertRaises( ValidationError ):
            ChangePasswordRequest( current_password="OldPass123!", new_password="short" )


class TestResponseModels( unittest.TestCase ):
    """
    Tests for the authentication RESPONSE models.

    Ensures:
        - Defaults ( token_type, optional fields ), required fields, nested composition
    """

    def test_token_response_defaults( self ):
        """
        Ensures:
            - token_type defaults to "bearer"; expires_in required
        """
        tok = _valid_token_response()
        self.assertEqual( tok.token_type, "bearer" )
        self.assertEqual( tok.expires_in, 1800 )
        with self.assertRaises( ValidationError ):
            TokenResponse( access_token="a", refresh_token="b" )  # missing expires_in

    def test_user_response_optional_last_login( self ):
        """
        Ensures:
            - last_login_at defaults to None when omitted
        """
        user = _valid_user_response()
        self.assertIsNone( user.last_login_at )
        self.assertEqual( user.roles, [ "user" ] )

    def test_register_and_login_responses_nest_user_and_tokens( self ):
        """
        Ensures:
            - RegisterResponse/LoginResponse compose UserResponse + TokenResponse
        """
        user, tokens = _valid_user_response(), _valid_token_response()
        reg = RegisterResponse( message="ok", user=user, tokens=tokens )
        login = LoginResponse( message="ok", user=user, tokens=tokens )
        self.assertEqual( reg.user.email, "user@example.com" )
        self.assertEqual( login.tokens.token_type, "bearer" )

    def test_refresh_response_nests_tokens( self ):
        """
        Ensures:
            - RefreshResponse carries a TokenResponse
        """
        resp = RefreshResponse( message="ok", tokens=_valid_token_response() )
        self.assertEqual( resp.tokens.expires_in, 1800 )

    def test_logout_and_message_responses( self ):
        """
        Ensures:
            - LogoutResponse / MessageResponse carry a message string
        """
        self.assertEqual( LogoutResponse( message="bye" ).message, "bye" )
        self.assertEqual( MessageResponse( message="done" ).message, "done" )

    def test_error_response_optional_error_code( self ):
        """
        Ensures:
            - error_code defaults to None and is overridable
        """
        self.assertIsNone( ErrorResponse( detail="boom" ).error_code )
        self.assertEqual( ErrorResponse( detail="boom", error_code="X" ).error_code, "X" )


if __name__ == "__main__":
    unittest.main()
