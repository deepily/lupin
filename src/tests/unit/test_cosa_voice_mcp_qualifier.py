"""
Unit tests for cosa_voice_mcp qualifier extraction and formatting.

Tests cover:
    - _extract_qualifier() regex parsing for yes/no with optional [comment: ...]
    - _format_qualified_response() enriched output generation
    - ask_yes_no() integration: plain answers pass through, qualifiers get enriched
"""

import pytest
from unittest.mock import patch, MagicMock

from lupin_mcp.cosa_voice_mcp import (
    _extract_qualifier,
    _format_qualified_response,
)


# ═════════════════════════════════════════════════════════════════════════════
# TestExtractQualifier
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractQualifier:
    """Tests for _extract_qualifier() regex parsing."""

    def test_plain_yes( self ):
        """'yes' → ('yes', None)."""
        answer, qualifier = _extract_qualifier( "yes" )
        assert answer == "yes"
        assert qualifier is None

    def test_plain_no( self ):
        """'no' → ('no', None)."""
        answer, qualifier = _extract_qualifier( "no" )
        assert answer == "no"
        assert qualifier is None

    def test_yes_with_comment( self ):
        """'yes [comment: fix tests]' → ('yes', 'fix tests')."""
        answer, qualifier = _extract_qualifier( "yes [comment: fix tests]" )
        assert answer == "yes"
        assert qualifier == "fix tests"

    def test_no_with_comment( self ):
        """'no [comment: what time?]' → ('no', 'what time?')."""
        answer, qualifier = _extract_qualifier( "no [comment: what time?]" )
        assert answer == "no"
        assert qualifier == "what time?"

    def test_case_insensitive_yes( self ):
        """'YES [comment: Do It Now]' → ('yes', 'Do It Now')."""
        answer, qualifier = _extract_qualifier( "YES [comment: Do It Now]" )
        assert answer == "yes"
        assert qualifier == "Do It Now"

    def test_case_insensitive_no( self ):
        """'NO' → ('no', None)."""
        answer, qualifier = _extract_qualifier( "NO" )
        assert answer == "no"
        assert qualifier is None

    def test_leading_trailing_whitespace( self ):
        """Whitespace around value is stripped."""
        answer, qualifier = _extract_qualifier( "  yes [comment: fix tests]  " )
        assert answer == "yes"
        assert qualifier == "fix tests"

    def test_none_input( self ):
        """None → (None, None)."""
        answer, qualifier = _extract_qualifier( None )
        assert answer is None
        assert qualifier is None

    def test_empty_string( self ):
        """'' → (None, None)."""
        answer, qualifier = _extract_qualifier( "" )
        assert answer is None
        assert qualifier is None

    def test_long_qualifier( self ):
        """Long comment text is preserved."""
        text = "document and checkpoint your work before continuing"
        answer, qualifier = _extract_qualifier( f"yes [comment: {text}]" )
        assert answer == "yes"
        assert qualifier == text


# ═════════════════════════════════════════════════════════════════════════════
# TestFormatQualifiedResponse
# ═════════════════════════════════════════════════════════════════════════════

class TestFormatQualifiedResponse:
    """Tests for _format_qualified_response() enriched output."""

    def test_yes_with_instruction( self ):
        """Enriched response for 'yes' + instruction qualifier."""
        result = _format_qualified_response( "yes", "fix the tests" )
        assert result.startswith( "yes\n" )
        assert "IMPORTANT" in result
        assert "fix the tests" in result
        assert "You MUST act on this comment" in result

    def test_no_with_question( self ):
        """Enriched response for 'no' + question qualifier."""
        result = _format_qualified_response( "no", "what time is the meeting?" )
        assert result.startswith( "no\n" )
        assert "IMPORTANT" in result
        assert "what time is the meeting?" in result
        assert "their no response" in result

    def test_contains_action_mandate( self ):
        """Response includes strong action language."""
        result = _format_qualified_response( "yes", "do X" )
        assert "Do NOT ignore it" in result
        assert "If it is a question, answer it" in result
        assert "If it is an instruction, carry it out" in result


# ═════════════════════════════════════════════════════════════════════════════
# TestAskYesNoIntegration
# ═════════════════════════════════════════════════════════════════════════════

class TestAskYesNoIntegration:
    """Integration tests for ask_yes_no() with mocked notification backend.

    Note: @mcp.tool wraps ask_yes_no into a FastMCP FunctionTool object.
    We call ask_yes_no.fn() to invoke the underlying function directly.
    """

    def _mock_response( self, exit_code=0, response_value="yes" ):
        """Create a mock NotificationResponse."""
        mock = MagicMock()
        mock.exit_code     = exit_code
        mock.response_value = response_value
        return mock

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_plain_yes_passthrough( self, mock_notify, mock_sender, mock_abstract, mock_request ):
        """Plain 'yes' returns 'yes' unchanged."""
        mock_notify.return_value = self._mock_response( exit_code=0, response_value="yes" )

        from lupin_mcp.cosa_voice_mcp import ask_yes_no
        result = ask_yes_no.fn( "Proceed?" )
        assert result == "yes"

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_plain_no_passthrough( self, mock_notify, mock_sender, mock_abstract, mock_request ):
        """Plain 'no' returns 'no' unchanged."""
        mock_notify.return_value = self._mock_response( exit_code=0, response_value="no" )

        from lupin_mcp.cosa_voice_mcp import ask_yes_no
        result = ask_yes_no.fn( "Proceed?" )
        assert result == "no"

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_qualifier_enriched( self, mock_notify, mock_sender, mock_abstract, mock_request ):
        """'yes [comment: fix tests]' returns enriched string."""
        mock_notify.return_value = self._mock_response(
            exit_code=0, response_value="yes [comment: fix tests]"
        )

        from lupin_mcp.cosa_voice_mcp import ask_yes_no
        result = ask_yes_no.fn( "Proceed?" )
        assert result.startswith( "yes\n" )
        assert "IMPORTANT" in result
        assert "fix tests" in result

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_no_qualifier_enriched( self, mock_notify, mock_sender, mock_abstract, mock_request ):
        """'no [comment: what time?]' returns enriched string."""
        mock_notify.return_value = self._mock_response(
            exit_code=0, response_value="no [comment: what time?]"
        )

        from lupin_mcp.cosa_voice_mcp import ask_yes_no
        result = ask_yes_no.fn( "Delete files?" )
        assert result.startswith( "no\n" )
        assert "IMPORTANT" in result
        assert "what time?" in result

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_timeout_returns_default( self, mock_notify, mock_sender, mock_abstract, mock_request ):
        """Timeout (exit_code=1) returns default value."""
        mock_notify.return_value = self._mock_response( exit_code=1, response_value=None )

        from lupin_mcp.cosa_voice_mcp import ask_yes_no
        result = ask_yes_no.fn( "Proceed?", default="no" )
        assert result == "no"

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_empty_response_returns_default( self, mock_notify, mock_sender, mock_abstract, mock_request ):
        """Empty response_value returns default."""
        mock_notify.return_value = self._mock_response( exit_code=0, response_value="" )

        from lupin_mcp.cosa_voice_mcp import ask_yes_no
        result = ask_yes_no.fn( "Proceed?", default="yes" )
        assert result == "yes"
