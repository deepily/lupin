"""
Unit tests for cosa.rest.user_id_generator.

Covers the email -> system-ID conversion utility ( the single source of truth for
Lupin's email->system_id mapping ) and its companion helpers:

    - email_to_system_id      ( deterministic, collision-resistant, input-validated )
    - system_id_to_display_name
    - validate_system_id      ( format regex )
    - get_user_info           ( MOCK_USER_DATABASE lookup )
    - get_user_info_by_email  ( email -> system_id -> lookup )

Pure-function module: no DB, network, JWT, or crypto seams to mock. Reference output
values are pinned from the live implementation ( the module docstring's illustrative
hash suffixes are NOT authoritative — the real algorithm is the contract ).
"""

import unittest

from cosa.rest.user_id_generator import (
    email_to_system_id,
    system_id_to_display_name,
    validate_system_id,
    get_user_info,
    get_user_info_by_email,
    MOCK_USER_DATABASE,
)


class TestEmailToSystemId( unittest.TestCase ):
    """
    Tests for email_to_system_id().

    Ensures:
        - Deterministic, collision-resistant conversion
        - Safe-character output ( lowercase / digits / underscore )
        - Input validation raises ValueError on malformed email
    """

    def test_known_email_exact_value( self ):
        """
        Ensures:
            - A known email maps to its pinned system ID ( regression guard )
        """
        self.assertEqual( email_to_system_id( "ricardo.felipe.ruiz@gmail.com" ), "ricardo_felipe_ruiz_6bdc" )
        self.assertEqual( email_to_system_id( "alice.smith@example.com" ), "alice_smith_6e52" )

    def test_deterministic( self ):
        """
        Ensures:
            - Same email always produces the same system ID
        """
        first  = email_to_system_id( "bob.jones@example.com" )
        second = email_to_system_id( "bob.jones@example.com" )
        self.assertEqual( first, second )

    def test_collision_resistant( self ):
        """
        Ensures:
            - Different emails produce different system IDs
        """
        self.assertNotEqual(
            email_to_system_id( "alice.smith@example.com" ),
            email_to_system_id( "bob.jones@example.com" )
        )

    def test_output_is_safe_characters( self ):
        """
        Ensures:
            - Output contains only lowercase letters, digits, and underscores
        """
        system_id = email_to_system_id( "Ricardo.Felipe.RUIZ+tag@gmail.com" )
        self.assertRegex( system_id, r'^[a-z0-9_]+$' )

    def test_all_special_local_part_collapses_to_hash_only( self ):
        """
        Ensures:
            - A local part of only special chars collapses to an empty base name,
              yielding a leading-underscore + hash-suffix system ID
        """
        self.assertEqual( email_to_system_id( "...@x.com" ), "_3eb9" )

    def test_empty_email_raises_value_error( self ):
        """
        Ensures:
            - Empty email triggers the `not email` validation arm
        """
        with self.assertRaises( ValueError ):
            email_to_system_id( "" )

    def test_missing_at_sign_raises_value_error( self ):
        """
        Ensures:
            - A non-empty email without '@' triggers the `'@' not in email` arm
        """
        with self.assertRaises( ValueError ):
            email_to_system_id( "no-at-sign-here" )


class TestSystemIdToDisplayName( unittest.TestCase ):
    """
    Tests for system_id_to_display_name().

    Ensures:
        - Returns the capitalized first underscore-delimited token
    """

    def test_multi_token_system_id( self ):
        """
        Ensures:
            - First token before underscore is capitalized
        """
        self.assertEqual( system_id_to_display_name( "ricardo_felipe_ruiz_6bdc" ), "Ricardo" )

    def test_single_token_no_underscore( self ):
        """
        Ensures:
            - A token with no underscore is returned capitalized
        """
        self.assertEqual( system_id_to_display_name( "ricardo" ), "Ricardo" )

    def test_empty_string_returns_empty( self ):
        """
        Ensures:
            - Empty input yields an empty display name ( ''.split('_') -> [''] )
        """
        self.assertEqual( system_id_to_display_name( "" ), "" )


class TestValidateSystemId( unittest.TestCase ):
    """
    Tests for validate_system_id().

    Ensures:
        - True only for lowercase-alphanumeric-underscore IDs ending in a 4-char hex suffix
    """

    def test_valid_format( self ):
        """
        Ensures:
            - A well-formed system ID validates True
        """
        self.assertTrue( validate_system_id( "ricardo_felipe_ruiz_6bdc" ) )

    def test_uppercase_rejected( self ):
        """
        Ensures:
            - Uppercase characters fail the lowercase-only pattern
        """
        self.assertFalse( validate_system_id( "Ricardo_6bdc" ) )

    def test_missing_hash_suffix_rejected( self ):
        """
        Ensures:
            - An ID without the trailing 4-char hex suffix fails
        """
        self.assertFalse( validate_system_id( "ricardo" ) )

    def test_empty_string_rejected( self ):
        """
        Ensures:
            - Empty input fails validation
        """
        self.assertFalse( validate_system_id( "" ) )


class TestUserLookup( unittest.TestCase ):
    """
    Tests for get_user_info() and get_user_info_by_email().

    Ensures:
        - Lookups resolve against MOCK_USER_DATABASE
        - Missing IDs / emails return None
        - Invalid emails propagate ValueError from email_to_system_id
    """

    def test_get_user_info_found( self ):
        """
        Ensures:
            - A known system ID returns its user record
        """
        info = get_user_info( "ricardo_felipe_ruiz_6bdc" )
        self.assertIsNotNone( info )
        self.assertEqual( info[ "name" ], "Ricardo" )
        self.assertIn( "ricardo_felipe_ruiz_6bdc", MOCK_USER_DATABASE )

    def test_get_user_info_not_found( self ):
        """
        Ensures:
            - An unknown system ID returns None
        """
        self.assertIsNone( get_user_info( "unknown_system_id_0000" ) )

    def test_get_user_info_by_email_found( self ):
        """
        Ensures:
            - A known email resolves to its user record via system-ID conversion
        """
        info = get_user_info_by_email( "ricardo.felipe.ruiz@gmail.com" )
        self.assertIsNotNone( info )
        self.assertEqual( info[ "name" ], "Ricardo" )

    def test_get_user_info_by_email_not_found( self ):
        """
        Ensures:
            - A valid email not present in the database returns None
        """
        self.assertIsNone( get_user_info_by_email( "nobody.here@example.com" ) )

    def test_get_user_info_by_email_invalid_raises( self ):
        """
        Ensures:
            - An invalid email propagates ValueError from email_to_system_id
        """
        with self.assertRaises( ValueError ):
            get_user_info_by_email( "not-an-email" )


if __name__ == "__main__":
    unittest.main()
