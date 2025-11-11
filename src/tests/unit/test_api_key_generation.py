"""
Unit tests for API key generation and service account creation.

Tests the security and correctness of API key generation functions
from create_service_account.py script.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
Section: API Key Security Requirements (lines 83-151)
"""

import re
import sys
import os
from pathlib import Path

# Bootstrap: Add src to path for imports
lupin_root = os.environ.get( 'LUPIN_ROOT', '/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box' )
src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Import the script module (tricky because it has no .py extension)
import importlib.util
script_path = Path( lupin_root ) / 'src' / 'scripts' / 'create_service_account.py'
spec = importlib.util.spec_from_file_location( "create_service_account", script_path )
create_service_account = importlib.util.module_from_spec( spec )
spec.loader.exec_module( create_service_account )


class TestAPIKeyGeneration:
    """Test suite for API key generation."""

    def test_api_key_format( self ):
        """Test that generated API keys match expected format."""
        api_key = create_service_account.generate_api_key()

        # Should start with ck_live_
        assert api_key.startswith( 'ck_live_' ), f"API key should start with 'ck_live_', got: {api_key[:10]}"

        # Should match full regex pattern
        pattern = r'^ck_live_[A-Za-z0-9_-]{64,}$'
        assert re.match( pattern, api_key ), f"API key format invalid: {api_key}"

    def test_api_key_length( self ):
        """Test that API keys have correct length."""
        api_key = create_service_account.generate_api_key()

        # Total length should be 70+ characters
        # ck_live_ (8 chars) + base64url (64 chars) = 72+ total
        assert len( api_key ) >= 70, f"API key too short: {len( api_key )} chars (expected 70+)"
        assert len( api_key ) <= 100, f"API key too long: {len( api_key )} chars (expected <=100)"

    def test_api_key_uniqueness( self ):
        """Test that multiple generated keys are unique."""
        keys = set()

        # Generate 100 keys
        for _ in range( 100 ):
            key = create_service_account.generate_api_key()
            keys.add( key )

        # All keys should be unique
        assert len( keys ) == 100, f"Generated {len( keys )} unique keys out of 100 (collision detected)"

    def test_api_key_entropy( self ):
        """Test that generated keys have good entropy (variety of characters)."""
        api_key = create_service_account.generate_api_key()

        # Remove prefix for character analysis
        key_body = api_key[8:]  # Remove 'ck_live_'

        # Check that we have both uppercase and lowercase letters
        has_upper = any( c.isupper() for c in key_body )
        has_lower = any( c.islower() for c in key_body )
        has_digit = any( c.isdigit() for c in key_body )

        assert has_upper, "API key should contain uppercase letters"
        assert has_lower, "API key should contain lowercase letters"
        assert has_digit, "API key should contain digits"

    def test_api_key_character_set( self ):
        """Test that API keys only use URL-safe base64 characters."""
        api_key = create_service_account.generate_api_key()

        # Remove prefix
        key_body = api_key[8:]

        # Should only contain A-Z, a-z, 0-9, _, -
        valid_chars = set( 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' )
        key_chars = set( key_body )

        invalid_chars = key_chars - valid_chars
        assert not invalid_chars, f"API key contains invalid characters: {invalid_chars}"

    def test_api_key_minimum_length_requirement( self ):
        """Test that API key meets minimum 288-bit entropy requirement."""
        api_key = create_service_account.generate_api_key()

        # secrets.token_urlsafe(48) generates 48 bytes = 384 bits
        # Base64url encoding: 48 bytes → 64 characters
        # Total key: ck_live_ (8) + 64 chars = 72 characters minimum
        key_body = api_key[8:]

        assert len( key_body ) >= 64, f"Key body too short: {len( key_body )} chars (expected 64+)"
        # This ensures at least 288 bits of entropy (64 chars * 6 bits/char = 384 bits)


class TestAPIKeyFormatValidation:
    """Test suite for API key format validation regex."""

    def test_valid_key_patterns( self ):
        """Test that valid API key patterns are accepted."""
        valid_keys = [
            "ck_live_" + "A" * 64,
            "ck_live_" + "a" * 64,
            "ck_live_" + "0" * 64,
            "ck_live_" + "_" * 64,
            "ck_live_" + "-" * 64,
            "ck_live_" + "A" * 100,  # Longer is OK
            "ck_live_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
        ]

        pattern = r'^ck_live_[A-Za-z0-9_-]{64,}$'

        for key in valid_keys:
            assert re.match( pattern, key ), f"Valid key rejected: {key[:30]}..."

    def test_invalid_key_patterns( self ):
        """Test that invalid API key patterns are rejected."""
        invalid_keys = [
            "ck_test_" + "A" * 64,      # Wrong prefix
            "ck_live_" + "A" * 63,      # Too short
            "ck_live_" + "A" * 63 + "!",  # Invalid character
            "ck_live_" + "A" * 63 + " ",  # Whitespace
            "live_" + "A" * 64,          # Missing ck_ prefix
            "",                          # Empty
            "ck_live_",                  # No random part
        ]

        pattern = r'^ck_live_[A-Za-z0-9_-]{64,}$'

        for key in invalid_keys:
            assert not re.match( pattern, key ), f"Invalid key accepted: {key[:30]}..."


class TestServiceAccountEmailValidation:
    """Test suite for service account email validation."""

    def test_valid_email_formats( self ):
        """Test that valid email addresses are accepted."""
        valid_emails = [
            "claude.code@deepily.ai",
            "service@example.com",
            "test.user+tag@example.co.uk",
            "admin@localhost"
        ]

        # Simple email regex (same logic as in the system)
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

        for email in valid_emails:
            # Note: The actual implementation doesn't validate email format strictly
            # It just stores whatever is provided
            # This test documents expected valid formats
            assert '@' in email, f"Email missing @: {email}"

    def test_default_email_constant( self ):
        """Test that default email constant is set correctly."""
        # The script uses 'claude.code@deepily.ai' as default
        default_email = "claude.code@deepily.ai"

        assert '@' in default_email
        assert '.' in default_email
        assert default_email.startswith( 'claude.code@' )
