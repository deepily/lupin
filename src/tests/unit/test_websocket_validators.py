#!/usr/bin/env python3
"""
Unit tests for WebSocket validation functions.

Tests validation logic for session IDs, tokens, and auth messages
to ensure proper security validation at the component level.
"""

import pytest

# Python path configured by src/tests/conftest.py

# Import the validation function we need to test
from cosa.rest.routers.websocket import is_valid_session_id

class TestSessionIdValidation:
    """Test cases for session ID validation"""

    def test_valid_session_ids(self):
        """Test that valid session IDs are accepted"""
        valid_ids = [
            "wise penguin",
            "happy cat",
            "smart dog",
            "brave tiger",
            "clever fox"
        ]

        for session_id in valid_ids:
            assert is_valid_session_id(session_id), f"Valid session ID rejected: '{session_id}'"

    def test_invalid_session_ids_basic(self):
        """Test that basic invalid session IDs are rejected"""
        invalid_ids = [
            "",              # Empty string
            "   ",           # Whitespace only
            "singleword",    # Single word
            "too many words here",  # More than 2 words
            "UPPERCASE",     # Uppercase
            "With Numbers123"  # Numbers
        ]

        for session_id in invalid_ids:
            assert not is_valid_session_id(session_id), f"Invalid session ID accepted: '{session_id}'"

    def test_session_id_rejects_tab_character(self):
        """CRITICAL TEST: Session ID validation must reject tab characters"""
        # This test addresses the critical security issue from baseline
        tab_session_ids = [
            "wise\tpenguin",      # Tab between words
            "\twise penguin",     # Tab at start
            "wise penguin\t",     # Tab at end
            "wise\tpen\tguin"     # Multiple tabs
        ]

        for session_id in tab_session_ids:
            assert not is_valid_session_id(session_id), f"Session ID with tab accepted: '{session_id}'"

    def test_session_id_rejects_newline_character(self):
        """CRITICAL TEST: Session ID validation must reject newline characters"""
        # This test addresses the critical security issue from baseline
        newline_session_ids = [
            "wise\npenguin",      # Newline between words
            "\nwise penguin",     # Newline at start
            "wise penguin\n",     # Newline at end
            "wise\npen\nguin",    # Multiple newlines
            "wise\r\npenguin"     # Windows line ending
        ]

        for session_id in newline_session_ids:
            assert not is_valid_session_id(session_id), f"Session ID with newline accepted: '{session_id}'"

    def test_session_id_rejects_other_whitespace(self):
        """Test that other whitespace characters are rejected"""
        whitespace_session_ids = [
            "wise  penguin",      # Double space
            "wise\vpenguin",      # Vertical tab
            "wise\fpenguin",      # Form feed
            "wise\u00A0penguin"   # Non-breaking space
        ]

        for session_id in whitespace_session_ids:
            assert not is_valid_session_id(session_id), f"Session ID with invalid whitespace accepted: '{session_id}'"

    def test_session_id_case_sensitivity(self):
        """Test that session ID validation handles case correctly"""
        mixed_case_ids = [
            "Wise penguin",       # Capital first letter
            "wise Penguin",       # Capital second word
            "WISE PENGUIN",       # All caps
            "WiSe PeNgUiN"        # Mixed case
        ]

        # The function converts to lowercase, so these should all be valid
        for session_id in mixed_case_ids:
            # According to the current implementation, these should be valid
            # because it calls session_id.lower() before matching
            assert is_valid_session_id(session_id), f"Mixed case session ID incorrectly rejected: '{session_id}'"


if __name__ == "__main__":
    # Run tests when script is executed directly
    pytest.main([__file__, "-v"])