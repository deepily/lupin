"""
Pins the exact result tuples of the four email token service functions.

The older tests check message fragments. These check the whole tuple on every path.
They also check the lifetime given to create_token and the repository calls, for both kinds.
"""

import unittest
import uuid
from unittest.mock import patch, MagicMock

from cosa.rest import email_token_service as svc

USER_ID = "550e8400-e29b-41d4-a716-446655440000"

KINDS = {
    "verification" : {
        "repo_name"  : "EmailVerificationTokenRepository",
        "generate"   : svc.generate_verification_token,
        "validate"   : svc.validate_verification_token,
        "hours"      : 24,
        "gen_ok"     : "Verification token generated",
        "gen_fail"   : "Failed to generate verification token: boom",
        "invalid"    : "Invalid verification token",
        "used"       : "Verification token already used",
        "expired"    : "Verification token expired",
        "valid"      : "Email verification token valid",
        "val_fail"   : "Failed to validate verification token: boom",
    },
    "password reset" : {
        "repo_name"  : "PasswordResetTokenRepository",
        "generate"   : svc.generate_password_reset_token,
        "validate"   : svc.validate_password_reset_token,
        "hours"      : 1,
        "gen_ok"     : "Password reset token generated",
        "gen_fail"   : "Failed to generate password reset token: boom",
        "invalid"    : "Invalid password reset token",
        "used"       : "Password reset token already used",
        "expired"    : "Password reset token expired",
        "valid"      : "Password reset token valid",
        "val_fail"   : "Failed to validate password reset token: boom",
    },
}


class _Case( unittest.TestCase ):
    """Runs each test once per token kind with the database and repository class patched."""

    def _run_kinds( self, body ):
        for name, kind in KINDS.items():
            with self.subTest( kind=name ):
                with patch( "cosa.rest.email_token_service.get_db" ), \
                     patch( f"cosa.rest.email_token_service.{kind[ 'repo_name' ]}" ) as repo_cls:
                    body( kind, repo_cls.return_value )


class TestGenerate( _Case ):

    def test_success_stores_the_token_with_the_kinds_lifetime_and_returns_it( self ):
        def body( kind, repo ):
            with patch( "cosa.rest.email_token_service.secrets" ) as secrets_mod:
                secrets_mod.token_urlsafe.return_value = "secure_token"
                result = kind[ "generate" ]( USER_ID )
            secrets_mod.token_urlsafe.assert_called_once_with( 32 )
            self.assertEqual( result, ( True, kind[ "gen_ok" ], "secure_token" ) )
            repo.create_token.assert_called_once_with(
                token = "secure_token", user_id = uuid.UUID( USER_ID ), expires_hours = kind[ "hours" ] )
        self._run_kinds( body )

    def test_a_repository_error_is_returned_in_the_message_not_raised( self ):
        def body( kind, repo ):
            repo.create_token.side_effect = RuntimeError( "boom" )
            self.assertEqual( kind[ "generate" ]( USER_ID ), ( False, kind[ "gen_fail" ], None ) )
        self._run_kinds( body )

    def test_a_bad_user_id_is_returned_in_the_message_not_raised( self ):
        def body( kind, repo ):
            ok, message, token = kind[ "generate" ]( "not-a-uuid" )
            self.assertFalse( ok )
            self.assertIsNone( token )
            self.assertTrue( message.startswith( kind[ "gen_fail" ].split( ":" )[ 0 ] + ": " ) )
            repo.create_token.assert_not_called()
        self._run_kinds( body )


class TestValidate( _Case ):

    def test_a_valid_token_is_marked_used_and_returns_the_user_id_as_a_string( self ):
        def body( kind, repo ):
            repo.is_valid.return_value = True
            repo.get_by_token.return_value = MagicMock( user_id = uuid.UUID( USER_ID ) )
            self.assertEqual( kind[ "validate" ]( "tok" ), ( True, kind[ "valid" ], USER_ID ) )
            repo.is_valid.assert_called_once_with( "tok" )
            repo.mark_used.assert_called_once_with( "tok" )
        self._run_kinds( body )

    def test_an_unknown_token_is_invalid_and_not_marked( self ):
        def body( kind, repo ):
            repo.is_valid.return_value = False
            repo.get_by_token.return_value = None
            self.assertEqual( kind[ "validate" ]( "tok" ), ( False, kind[ "invalid" ], None ) )
            repo.mark_used.assert_not_called()
        self._run_kinds( body )

    def test_a_used_token_says_already_used_and_is_not_marked( self ):
        def body( kind, repo ):
            repo.is_valid.return_value = False
            repo.get_by_token.return_value = MagicMock( used = True )
            self.assertEqual( kind[ "validate" ]( "tok" ), ( False, kind[ "used" ], None ) )
            repo.mark_used.assert_not_called()
        self._run_kinds( body )

    def test_an_unused_invalid_token_says_expired_and_is_not_marked( self ):
        def body( kind, repo ):
            repo.is_valid.return_value = False
            repo.get_by_token.return_value = MagicMock( used = False )
            self.assertEqual( kind[ "validate" ]( "tok" ), ( False, kind[ "expired" ], None ) )
            repo.mark_used.assert_not_called()
        self._run_kinds( body )

    def test_a_token_that_vanishes_between_the_checks_is_invalid_and_not_marked( self ):
        def body( kind, repo ):
            repo.is_valid.return_value = True
            repo.get_by_token.return_value = None
            self.assertEqual( kind[ "validate" ]( "tok" ), ( False, kind[ "invalid" ], None ) )
            repo.mark_used.assert_not_called()
        self._run_kinds( body )

    def test_a_repository_error_is_returned_in_the_message_not_raised( self ):
        def body( kind, repo ):
            repo.is_valid.side_effect = RuntimeError( "boom" )
            self.assertEqual( kind[ "validate" ]( "tok" ), ( False, kind[ "val_fail" ], None ) )
        self._run_kinds( body )


if __name__ == "__main__":
    unittest.main()
