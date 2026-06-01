"""
Unit tests for cosa.rest.email_token_service.

All persistence seams are mocked — get_db ( DB session context manager ),
EmailVerificationTokenRepository, PasswordResetTokenRepository — plus secrets/uuid.
NO real database, NO real crypto-token persistence. Covers every branch of:

    - generate_verification_token / generate_password_reset_token  ( success + failure )
    - validate_verification_token / validate_password_reset_token  ( valid / invalid /
      used / expired / race-None / exception )
    - cleanup_expired_tokens  ( success + failure )
"""

import unittest
from unittest.mock import patch, MagicMock

from cosa.rest.email_token_service import (
    generate_verification_token,
    validate_verification_token,
    generate_password_reset_token,
    validate_password_reset_token,
    cleanup_expired_tokens,
)


class TestGenerateVerificationToken( unittest.TestCase ):
    """
    Tests for generate_verification_token().

    Ensures:
        - Success stores a secure token and returns it
        - Repository/uuid failures are caught -> (False, error, None)
    """

    def test_success( self ):
        """
        Ensures:
            - Generates a urlsafe token, persists it ( 24h ), returns (True, msg, token)
        """
        with patch( 'cosa.rest.email_token_service.get_db' ) as mock_db, \
             patch( 'cosa.rest.email_token_service.EmailVerificationTokenRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.email_token_service.secrets' ) as mock_secrets, \
             patch( 'cosa.rest.email_token_service.uuid' ) as mock_uuid:
            mock_secrets.token_urlsafe.return_value = "secure_token"
            mock_uuid.UUID.return_value = "uuid-obj"
            repo = mock_repo_cls.return_value

            ok, msg, token = generate_verification_token( "550e8400-e29b-41d4-a716-446655440000" )

            self.assertTrue( ok )
            self.assertEqual( token, "secure_token" )
            repo.create_token.assert_called_once_with( token="secure_token", user_id="uuid-obj", expires_hours=24 )

    def test_failure_returns_false_none( self ):
        """
        Ensures:
            - A repository exception yields (False, error message, None)
        """
        with patch( 'cosa.rest.email_token_service.get_db' ), \
             patch( 'cosa.rest.email_token_service.EmailVerificationTokenRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.email_token_service.secrets' ), \
             patch( 'cosa.rest.email_token_service.uuid' ):
            mock_repo_cls.return_value.create_token.side_effect = Exception( "db down" )
            ok, msg, token = generate_verification_token( "uid" )
            self.assertFalse( ok )
            self.assertIn( "Failed to generate", msg )
            self.assertIsNone( token )


class TestValidateVerificationToken( unittest.TestCase ):
    """
    Tests for validate_verification_token().

    Ensures:
        - Valid token -> marks used + returns user_id
        - Invalid / used / expired / race-None / exception paths each return False
    """

    def _patches( self ):
        """
        Ensures:
            - Returns ( get_db patch, repo-class patch ) context managers entered by caller
        """
        return (
            patch( 'cosa.rest.email_token_service.get_db' ),
            patch( 'cosa.rest.email_token_service.EmailVerificationTokenRepository' ),
        )

    def test_valid_marks_used_and_returns_user_id( self ):
        """
        Ensures:
            - is_valid True + token present -> mark_used + (True, msg, user_id)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = True
            token_obj = MagicMock( user_id="user-123" )
            repo.get_by_token.return_value = token_obj
            ok, msg, user_id = validate_verification_token( "tok" )
            self.assertTrue( ok )
            self.assertEqual( user_id, "user-123" )
            repo.mark_used.assert_called_once_with( "tok" )

    def test_valid_but_token_vanished_returns_invalid( self ):
        """
        Ensures:
            - is_valid True but get_by_token None ( race ) -> (False, "Invalid...", None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = True
            repo.get_by_token.return_value = None
            ok, msg, user_id = validate_verification_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Invalid", msg )
            self.assertIsNone( user_id )

    def test_invalid_unknown_token( self ):
        """
        Ensures:
            - is_valid False + get_by_token None -> (False, "Invalid verification token", None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = False
            repo.get_by_token.return_value = None
            ok, msg, _ = validate_verification_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Invalid verification token", msg )

    def test_invalid_already_used( self ):
        """
        Ensures:
            - is_valid False + token.used True -> (False, "already used", None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = False
            repo.get_by_token.return_value = MagicMock( used=True )
            ok, msg, _ = validate_verification_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "already used", msg )

    def test_invalid_expired( self ):
        """
        Ensures:
            - is_valid False + token.used False -> (False, "expired", None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = False
            repo.get_by_token.return_value = MagicMock( used=False )
            ok, msg, _ = validate_verification_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "expired", msg )

    def test_exception_returns_false( self ):
        """
        Ensures:
            - A repository exception yields (False, error, None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            mock_repo_cls.return_value.is_valid.side_effect = Exception( "db error" )
            ok, msg, _ = validate_verification_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Failed to validate", msg )


class TestGeneratePasswordResetToken( unittest.TestCase ):
    """
    Tests for generate_password_reset_token().

    Ensures:
        - Success persists a 1h token; failure returns (False, error, None)
    """

    def test_success( self ):
        """
        Ensures:
            - Generates + persists ( 1h expiry ) + returns the token
        """
        with patch( 'cosa.rest.email_token_service.get_db' ), \
             patch( 'cosa.rest.email_token_service.PasswordResetTokenRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.email_token_service.secrets' ) as mock_secrets, \
             patch( 'cosa.rest.email_token_service.uuid' ) as mock_uuid:
            mock_secrets.token_urlsafe.return_value = "reset_token"
            mock_uuid.UUID.return_value = "uuid-obj"
            repo = mock_repo_cls.return_value
            ok, msg, token = generate_password_reset_token( "uid" )
            self.assertTrue( ok )
            self.assertEqual( token, "reset_token" )
            repo.create_token.assert_called_once_with( token="reset_token", user_id="uuid-obj", expires_hours=1 )

    def test_failure( self ):
        """
        Ensures:
            - Exception -> (False, error, None)
        """
        with patch( 'cosa.rest.email_token_service.get_db' ), \
             patch( 'cosa.rest.email_token_service.PasswordResetTokenRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.email_token_service.secrets' ), \
             patch( 'cosa.rest.email_token_service.uuid' ):
            mock_repo_cls.return_value.create_token.side_effect = Exception( "db down" )
            ok, msg, token = generate_password_reset_token( "uid" )
            self.assertFalse( ok )
            self.assertIn( "Failed to generate", msg )
            self.assertIsNone( token )


class TestValidatePasswordResetToken( unittest.TestCase ):
    """
    Tests for validate_password_reset_token().

    Ensures:
        - Valid / invalid / used / expired / race-None / exception paths
    """

    def _patches( self ):
        """
        Ensures:
            - Returns ( get_db patch, PasswordResetTokenRepository patch )
        """
        return (
            patch( 'cosa.rest.email_token_service.get_db' ),
            patch( 'cosa.rest.email_token_service.PasswordResetTokenRepository' ),
        )

    def test_valid( self ):
        """
        Ensures:
            - Valid token -> mark_used + (True, msg, user_id)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = True
            repo.get_by_token.return_value = MagicMock( user_id="user-9" )
            ok, msg, user_id = validate_password_reset_token( "tok" )
            self.assertTrue( ok )
            self.assertEqual( user_id, "user-9" )
            repo.mark_used.assert_called_once_with( "tok" )

    def test_valid_but_vanished( self ):
        """
        Ensures:
            - is_valid True + get_by_token None -> (False, "Invalid...", None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = True
            repo.get_by_token.return_value = None
            ok, msg, _ = validate_password_reset_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Invalid", msg )

    def test_invalid_unknown( self ):
        """
        Ensures:
            - is_valid False + get_by_token None -> (False, "Invalid password reset token", None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = False
            repo.get_by_token.return_value = None
            ok, msg, _ = validate_password_reset_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Invalid password reset token", msg )

    def test_invalid_used( self ):
        """
        Ensures:
            - is_valid False + used True -> (False, "already used", None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = False
            repo.get_by_token.return_value = MagicMock( used=True )
            ok, msg, _ = validate_password_reset_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "already used", msg )

    def test_invalid_expired( self ):
        """
        Ensures:
            - is_valid False + used False -> (False, "expired", None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            repo = mock_repo_cls.return_value
            repo.is_valid.return_value = False
            repo.get_by_token.return_value = MagicMock( used=False )
            ok, msg, _ = validate_password_reset_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "expired", msg )

    def test_exception( self ):
        """
        Ensures:
            - Repository exception -> (False, error, None)
        """
        p_db, p_repo = self._patches()
        with p_db, p_repo as mock_repo_cls:
            mock_repo_cls.return_value.is_valid.side_effect = Exception( "boom" )
            ok, msg, _ = validate_password_reset_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Failed to validate", msg )


class TestCleanupExpiredTokens( unittest.TestCase ):
    """
    Tests for cleanup_expired_tokens().

    Ensures:
        - Returns ( verification_deleted, reset_deleted ) on success
        - Returns ( 0, 0 ) on failure
    """

    def test_success_returns_counts( self ):
        """
        Ensures:
            - Both repositories' cleanup counts are returned as a tuple
        """
        with patch( 'cosa.rest.email_token_service.get_db' ), \
             patch( 'cosa.rest.email_token_service.EmailVerificationTokenRepository' ) as mock_ver_cls, \
             patch( 'cosa.rest.email_token_service.PasswordResetTokenRepository' ) as mock_reset_cls:
            mock_ver_cls.return_value.cleanup_expired.return_value = 3
            mock_reset_cls.return_value.cleanup_expired.return_value = 2
            self.assertEqual( cleanup_expired_tokens(), ( 3, 2 ) )

    def test_failure_returns_zeros( self ):
        """
        Ensures:
            - An exception during cleanup yields ( 0, 0 )
        """
        with patch( 'cosa.rest.email_token_service.get_db' ), \
             patch( 'cosa.rest.email_token_service.EmailVerificationTokenRepository' ) as mock_ver_cls, \
             patch( 'cosa.rest.email_token_service.PasswordResetTokenRepository' ):
            mock_ver_cls.return_value.cleanup_expired.side_effect = Exception( "db error" )
            self.assertEqual( cleanup_expired_tokens(), ( 0, 0 ) )


if __name__ == "__main__":
    unittest.main()
