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

    def _mock_response( self, exit_code=0, response_value=None, status="", is_timeout=None ):
        """Create a mock NotificationResponse.

        is_timeout defaults to (exit_code == 2) to mirror notify_user_sync's real
        wiring, but the caller can force it True (e.g. the exit_code==1 /
        "expired_no_default" expiry path, which IS a timeout) or False (a genuine
        transport error at exit_code==1).
        """
        if is_timeout is None:
            is_timeout = ( exit_code == 2 )
        mock                = MagicMock()
        mock.exit_code      = exit_code
        mock.response_value = response_value
        mock.status         = status
        mock.is_timeout     = is_timeout
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

    # ─────────────────────────────────────────────────────────────────────────
    # Bug d13a3a30 regression — the REAL expiry path returns exit_code==1 with
    # status "expired_no_default" (is_timeout=True), NOT exit_code==2. The
    # MULTIPLE_CHOICE request never plumbs a server-side response_default, so a
    # genuine expiry ALWAYS lands on exit_code==1. Keying default application on
    # exit_code==2 alone dropped the caller's `default` on every real expiry and
    # leaked {"error": "error: expired_no_default"} — the exact live failures
    # observed 2026-07-07 (Tiberius). Discriminate on is_timeout instead.
    # ─────────────────────────────────────────────────────────────────────────

    UNICODE_QUESTION = [
        {
            "question"    : "How should the merge gate resolve?",
            "header"      : "Merge gate",
            "multiSelect" : False,
            "options"     : [
                { "label": "Not mine — hold" },   # em-dash (U+2014) in the label
                { "label": "Take it" }
            ]
        }
    ]

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_expired_no_default_exit1_with_default_returns_answers(
        self, mock_notify, mock_sender, mock_abstract, mock_request
    ):
        """THE BUG: real expiry (exit_code=1, status='expired_no_default',
        is_timeout=True) with a valid default must return {"answers": <default>},
        NOT {"error": "error: expired_no_default"}."""
        mock_notify.return_value = self._mock_response(
            exit_code=1, status="expired_no_default", is_timeout=True
        )

        result = ask_multiple_choice.fn(
            questions = self.SINGLE_QUESTION,
            default   = { "Database": "PostgreSQL" }
        )
        assert result == { "answers": { "Database": "PostgreSQL" } }

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_expired_no_default_exit1_without_default_returns_timeout_error(
        self, mock_notify, mock_sender, mock_abstract, mock_request
    ):
        """Real expiry WITHOUT a default returns the friendly timeout error, not
        the raw internal status string."""
        mock_notify.return_value = self._mock_response(
            exit_code=1, status="expired_no_default", is_timeout=True
        )

        result = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION )
        assert result == { "error": "timeout - no response received", "timeout": True }

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_genuine_error_not_timeout_returns_error_dict(
        self, mock_notify, mock_sender, mock_abstract, mock_request
    ):
        """A genuine transport error (exit_code=1, is_timeout=False) must NOT be
        treated as an expiry — even with a default present, it surfaces the
        status error dict so real failures stay visible."""
        mock_notify.return_value = self._mock_response(
            exit_code=1, status="connection_error", is_timeout=False
        )

        result = ask_multiple_choice.fn(
            questions = self.SINGLE_QUESTION,
            default   = { "Database": "PostgreSQL" }
        )
        assert result == { "error": "error: connection_error" }

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_request_timeout_exit2_with_default_returns_answers(
        self, mock_notify, mock_sender, mock_abstract, mock_request
    ):
        """The other timeout shape (exit_code=2 request_timeout, is_timeout=True)
        with a default also returns {"answers": <default>} — no regression."""
        mock_notify.return_value = self._mock_response(
            exit_code=2, status="request_timeout"
        )

        result = ask_multiple_choice.fn(
            questions = self.SINGLE_QUESTION,
            default   = { "Database": "PostgreSQL" }
        )
        assert result == { "answers": { "Database": "PostgreSQL" } }

    def test_unicode_emdash_label_default_validates_at_call_time(
        self
    ):
        """An em-dash (unicode) option label matched EXACTLY by the default passes
        call-time validation — exact-string match is codepoint-correct, so the
        em-dash is not a silent mismatch."""
        # No timeout needed — validation is pre-call. A mismatch would return an
        # error dict here; an exact match falls through to the notify path.
        result = _validate_multiple_choice_default(
            { "Merge gate": "Not mine — hold" }, self.UNICODE_QUESTION
        )
        assert result is None

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_unicode_emdash_label_applied_on_expiry(
        self, mock_notify, mock_sender, mock_abstract, mock_request
    ):
        """The em-dash default survives the full expiry path and is returned
        verbatim in {"answers": ...} — mirrors the observed call-2 failure."""
        mock_notify.return_value = self._mock_response(
            exit_code=1, status="expired_no_default", is_timeout=True
        )

        result = ask_multiple_choice.fn(
            questions = self.UNICODE_QUESTION,
            default   = { "Merge gate": "Not mine — hold" }
        )
        assert result == { "answers": { "Merge gate": "Not mine — hold" } }

    # ─────────────────────────────────────────────────────────────────────────
    # Full-branch coverage of ask_multiple_choice (touched function → 100%)
    # ─────────────────────────────────────────────────────────────────────────

    def test_empty_questions_returns_error( self ):
        """Empty / non-list questions is rejected before any notify."""
        assert ask_multiple_choice.fn( questions=[] ) == {
            "error": "questions must be a non-empty list"
        }

    def test_non_dict_default_returns_error( self ):
        """A default that isn't a dict is rejected at call time with a type error."""
        result = ask_multiple_choice.fn(
            questions = self.SINGLE_QUESTION,
            default   = "PostgreSQL"  # must be a dict keyed by header
        )
        assert result == { "error": "default must be a dict, got str" }

    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest", side_effect=ValueError( "bad request" ) )
    def test_notification_request_construction_error_returns_validation_error(
        self, mock_request, mock_sender, mock_abstract
    ):
        """A NotificationRequest build failure surfaces as a validation error dict."""
        result = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION )
        assert "error" in result
        assert "validation error" in result[ "error" ]
        assert "bad request" in result[ "error" ]

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#test1234" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_success_exit0_parses_response(
        self, mock_notify, mock_sender, mock_abstract, mock_request
    ):
        """A real user response (exit_code=0) is parsed and returned as answers."""
        mock_notify.return_value = self._mock_response(
            exit_code      = 0,
            response_value = '{"answers": {"Database": "MongoDB"}}'
        )

        result = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION )
        assert result == { "answers": { "Database": "MongoDB" } }
