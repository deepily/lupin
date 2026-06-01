"""
Unit tests for cosa.rest.password_service.

The bcrypt crypto seam ( pwd_context.hash / pwd_context.verify ) is mocked — per the
boundary-mock mandate AND to avoid slow real bcrypt rounds ( zero crypto cost ). The
pure-logic validate_password_strength() is exercised with real inputs.

Covered:
    - hash_password         ( empty -> ValueError; else delegates to pwd_context.hash )
    - verify_password       ( empty-input False; match True/False; exception -> False )
    - validate_password_strength ( length, common-password, char-type-count rules )
"""

import unittest
from unittest.mock import patch

from cosa.rest.password_service import (
    hash_password,
    verify_password,
    validate_password_strength,
)


class TestHashPassword( unittest.TestCase ):
    """
    Tests for hash_password().

    Ensures:
        - Empty password rejected before any crypto call
        - Non-empty password delegated to pwd_context.hash
    """

    def test_empty_password_raises( self ):
        """
        Ensures:
            - Empty password raises ValueError ( pwd_context never called )
        """
        with patch( 'cosa.rest.password_service.pwd_context' ) as mock_ctx:
            with self.assertRaises( ValueError ):
                hash_password( "" )
            mock_ctx.hash.assert_not_called()

    def test_valid_password_delegates_to_context( self ):
        """
        Ensures:
            - Non-empty password returns pwd_context.hash( plain )
        """
        with patch( 'cosa.rest.password_service.pwd_context' ) as mock_ctx:
            mock_ctx.hash.return_value = "$2b$12$fakehash"
            result = hash_password( "SecurePass123!" )
            self.assertEqual( result, "$2b$12$fakehash" )
            mock_ctx.hash.assert_called_once_with( "SecurePass123!" )


class TestVerifyPassword( unittest.TestCase ):
    """
    Tests for verify_password().

    Ensures:
        - Empty plain OR empty hash short-circuits to False
        - Match result delegated to pwd_context.verify
        - Any verify exception is swallowed -> False
    """

    def test_empty_plain_returns_false( self ):
        """
        Ensures:
            - Empty plain password -> False ( `not plain_password` arm )
        """
        with patch( 'cosa.rest.password_service.pwd_context' ) as mock_ctx:
            self.assertFalse( verify_password( "", "$2b$12$hash" ) )
            mock_ctx.verify.assert_not_called()

    def test_empty_hash_returns_false( self ):
        """
        Ensures:
            - Empty hash -> False ( `not hashed_password` arm )
        """
        with patch( 'cosa.rest.password_service.pwd_context' ) as mock_ctx:
            self.assertFalse( verify_password( "SecurePass123!", "" ) )
            mock_ctx.verify.assert_not_called()

    def test_matching_password_returns_true( self ):
        """
        Ensures:
            - A verifying password returns True
        """
        with patch( 'cosa.rest.password_service.pwd_context' ) as mock_ctx:
            mock_ctx.verify.return_value = True
            self.assertTrue( verify_password( "SecurePass123!", "$2b$12$hash" ) )
            mock_ctx.verify.assert_called_once_with( "SecurePass123!", "$2b$12$hash" )

    def test_non_matching_password_returns_false( self ):
        """
        Ensures:
            - A non-verifying password returns False
        """
        with patch( 'cosa.rest.password_service.pwd_context' ) as mock_ctx:
            mock_ctx.verify.return_value = False
            self.assertFalse( verify_password( "WrongPass", "$2b$12$hash" ) )

    def test_verify_exception_swallowed_returns_false( self ):
        """
        Ensures:
            - A pwd_context.verify exception is caught -> False ( never raises )
        """
        with patch( 'cosa.rest.password_service.pwd_context' ) as mock_ctx:
            mock_ctx.verify.side_effect = ValueError( "malformed hash" )
            self.assertFalse( verify_password( "SecurePass123!", "garbage" ) )


class TestValidatePasswordStrength( unittest.TestCase ):
    """
    Tests for validate_password_strength() ( pure logic, no crypto ).

    Ensures:
        - Length rule, common-password rule, and char-type-count rule all enforced
    """

    def test_too_short( self ):
        """
        Ensures:
            - Under 8 characters -> (False, length message)
        """
        ok, msg = validate_password_strength( "Ab1!" )
        self.assertFalse( ok )
        self.assertIn( "at least 8", msg )

    def test_common_password_rejected( self ):
        """
        Ensures:
            - A normalized common password is rejected even if it meets char rules
              ( "Password123!" -> "password123" which is in the common set )
        """
        ok, msg = validate_password_strength( "Password123!" )
        self.assertFalse( ok )
        self.assertIn( "common", msg.lower() )

    def test_insufficient_char_types( self ):
        """
        Ensures:
            - >= 8 chars, non-common, but < 3 char types -> rejected
              ( all-lowercase = 1 type )
        """
        ok, msg = validate_password_strength( "abcdefghij" )
        self.assertFalse( ok )
        self.assertIn( "at least 3", msg )

    def test_strong_password_accepted( self ):
        """
        Ensures:
            - A long, non-common password with >= 3 char types -> (True, "")
        """
        ok, msg = validate_password_strength( "Strong123!" )
        self.assertTrue( ok )
        self.assertEqual( msg, "" )


if __name__ == "__main__":
    unittest.main()
