"""
Unit tests for cosa_voice_mcp.ask_multiple_choice `default` parameter.

Tests cover:
    - _validate_multiple_choice_default() validation helper (direct unit tests)
    - ask_multiple_choice() integration with mocked notification backend:
        * default-provided timeout returns {"answers": <default>} (new behavior)
        * default-absent timeout returns legacy error dict (backward compat)
        * pre-call validation rejects bad header / bad label / wrong type
        * multi-select questions accept a list of valid labels
        * multi-select questions reject string default or bad-label list
"""

import pytest
from unittest.mock import patch, MagicMock

from lupin_mcp.cosa_voice_mcp import (
    _validate_multiple_choice_default,
    ask_multiple_choice,
)


# ═════════════════════════════════════════════════════════════════════════════
# TestValidateMultipleChoiceDefault — direct unit tests on the helper
# ═════════════════════════════════════════════════════════════════════════════

class TestValidateMultipleChoiceDefault:
    """Tests for _validate_multiple_choice_default() schema validation."""

    SINGLE_SELECT_QUESTIONS = [
        {
            "question"    : "Which database?",
            "header"      : "Database",
            "multiSelect" : False,
            "options"     : [
                { "label": "PostgreSQL" },
                { "label": "MongoDB" }
            ]
        }
    ]

    MULTI_SELECT_QUESTIONS = [
        {
            "question"    : "Which features?",
            "header"      : "Features",
            "multiSelect" : True,
            "options"     : [
                { "label": "Auth" },
                { "label": "Caching" },
                { "label": "Logging" }
            ]
        }
    ]

    def test_valid_single_select_default( self ):
        """Valid single-select default passes silently (returns None)."""
        result = _validate_multiple_choice_default(
            { "Database": "PostgreSQL" }, self.SINGLE_SELECT_QUESTIONS
        )
        assert result is None

    def test_valid_multi_select_default( self ):
        """Valid multi-select default (list of valid labels) passes silently."""
        result = _validate_multiple_choice_default(
            { "Features": [ "Auth", "Caching" ] }, self.MULTI_SELECT_QUESTIONS
        )
        assert result is None

    def test_unknown_header_raises_value_error( self ):
        """Default with a header not in questions raises ValueError."""
        with pytest.raises( ValueError ) as exc_info:
            _validate_multiple_choice_default(
                { "Bogus": "PostgreSQL" }, self.SINGLE_SELECT_QUESTIONS
            )
        assert "Bogus" in str( exc_info.value )
        assert "Database" in str( exc_info.value )  # lists available headers

    def test_unknown_label_single_select_raises( self ):
        """Single-select default with a label not in options raises ValueError."""
        with pytest.raises( ValueError ) as exc_info:
            _validate_multiple_choice_default(
                { "Database": "Redis" }, self.SINGLE_SELECT_QUESTIONS
            )
        assert "Redis" in str( exc_info.value )
        assert "Database" in str( exc_info.value )

    def test_unknown_label_multi_select_raises( self ):
        """Multi-select default with one bad label in list raises ValueError."""
        with pytest.raises( ValueError ) as exc_info:
            _validate_multiple_choice_default(
                { "Features": [ "Auth", "Telemetry" ] }, self.MULTI_SELECT_QUESTIONS
            )
        assert "Telemetry" in str( exc_info.value )

    def test_single_select_value_must_be_string( self ):
        """Single-select default with non-string value raises ValueError."""
        with pytest.raises( ValueError ) as exc_info:
            _validate_multiple_choice_default(
                { "Database": [ "PostgreSQL" ] }, self.SINGLE_SELECT_QUESTIONS
            )
        assert "must be a string" in str( exc_info.value )
        assert "list" in str( exc_info.value )

    def test_multi_select_value_must_be_list( self ):
        """Multi-select default with string (not list) raises ValueError."""
        with pytest.raises( ValueError ) as exc_info:
            _validate_multiple_choice_default(
                { "Features": "Auth" }, self.MULTI_SELECT_QUESTIONS
            )
        assert "must be a list" in str( exc_info.value )
        assert "str" in str( exc_info.value )


# ═════════════════════════════════════════════════════════════════════════════
# TestAskMultipleChoiceDefault — integration with mocked notification backend
# ═════════════════════════════════════════════════════════════════════════════

class TestAskMultipleChoiceDefault:
    """Integration tests for ask_multiple_choice(default=...) with mocked backend.

    Note: @mcp.tool wraps ask_multiple_choice into a FastMCP FunctionTool object.
    We call ask_multiple_choice.fn() to invoke the underlying function directly.
    """

    SINGLE_QUESTION = [
        {
            "question"    : "Which database?",
            "header"      : "Database",
            "multiSelect" : False,
            "options"     : [
                { "label": "PostgreSQL" },
                { "label": "MongoDB" }
            ]
        }
    ]

    MULTI_QUESTION = [
        {
            "question"    : "Which features?",
            "header"      : "Features",
            "multiSelect" : True,
            "options"     : [
                { "label": "Auth" },
                { "label": "Caching" },
                { "label": "Logging" }
            ]
        }
    ]

    def _mock_response( self, exit_code=0, response_value=None, status="" ):
        """Create a mock NotificationResponse."""
        mock                = MagicMock()
        mock.exit_code      = exit_code
        mock.response_value = response_value
        mock.status         = status
        return mock

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_default_provided_timeout_returns_default_in_answers_shape(
        self, mock_notify, mock_sender, mock_abstract, mock_request
    ):
        """Timeout (exit_code=2) with default returns {"answers": <default>}."""
        mock_notify.return_value = self._mock_response( exit_code=2 )

        result = ask_multiple_choice.fn(
            questions = self.SINGLE_QUESTION,
            default   = { "Database": "PostgreSQL" }
        )
        assert result == { "answers": { "Database": "PostgreSQL" } }

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_default_absent_timeout_returns_existing_error(
        self, mock_notify, mock_sender, mock_abstract, mock_request
    ):
        """Timeout (exit_code=2) WITHOUT default preserves legacy error return (backward compat)."""
        mock_notify.return_value = self._mock_response( exit_code=2 )

        result = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION )
        assert result == { "error": "timeout - no response received", "timeout": True }

    def test_default_validates_label_must_match_option( self ):
        """Default with a label not in question options is rejected at call time."""
        result = ask_multiple_choice.fn(
            questions = self.SINGLE_QUESTION,
            default   = { "Database": "Redis" }  # not an option label
        )
        assert "error" in result
        assert "default validation error" in result[ "error" ]
        assert "Redis" in result[ "error" ]

    def test_default_validates_header_must_match_question( self ):
        """Default with a header not matching any question is rejected at call time."""
        result = ask_multiple_choice.fn(
            questions = self.SINGLE_QUESTION,
            default   = { "Bogus": "PostgreSQL" }  # not a question header
        )
        assert "error" in result
        assert "default validation error" in result[ "error" ]
        assert "Bogus" in result[ "error" ]
        assert "Database" in result[ "error" ]  # lists available headers

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_default_multi_select_accepts_list_of_valid_labels(
        self, mock_notify, mock_sender, mock_abstract, mock_request
    ):
        """Multi-select question with list default returns {"answers": {"Features": [labels]}} on timeout."""
        mock_notify.return_value = self._mock_response( exit_code=2 )

        result = ask_multiple_choice.fn(
            questions = self.MULTI_QUESTION,
            default   = { "Features": [ "Auth", "Caching" ] }
        )
        assert result == { "answers": { "Features": [ "Auth", "Caching" ] } }

    def test_default_multi_select_rejects_string_or_invalid_label( self ):
        """Multi-select question rejects (a) string default and (b) list with bad label."""
        # (a) string default for multi-select
        result_a = ask_multiple_choice.fn(
            questions = self.MULTI_QUESTION,
            default   = { "Features": "Auth" }  # wrong type — should be list
        )
        assert "error" in result_a
        assert "default validation error" in result_a[ "error" ]
        assert "must be a list" in result_a[ "error" ]

        # (b) list with one bad label
        result_b = ask_multiple_choice.fn(
            questions = self.MULTI_QUESTION,
            default   = { "Features": [ "Auth", "Telemetry" ] }  # Telemetry not in options
        )
        assert "error" in result_b
        assert "default validation error" in result_b[ "error" ]
        assert "Telemetry" in result_b[ "error" ]
