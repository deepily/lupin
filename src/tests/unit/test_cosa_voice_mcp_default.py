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

import json
import uuid

import pytest
from unittest.mock import patch, MagicMock

from lupin_mcp.cosa_voice_mcp import (
    ask_yes_no,
    converse,
    DEFAULT_USED_MARKER,
    _stamp_answer_provenance,
    _validate_multiple_choice_default,
    ask_multiple_choice,
    _with_idempotency_key,
)
from lupin_cli.notifications.notification_models import NotificationRequest, ResponseType


# ═════════════════════════════════════════════════════════════════════════════
# TestWithIdempotencyKey — bug f433fbae, D2
#
# The blocking-ask verbs never stamped an idempotency_key, so notify_user_sync's
# retry_on_timeout re-POST (and any durable resend) looked like a brand-new ask
# and minted a duplicate card. This helper fills the gap the way notify() does.
# ═════════════════════════════════════════════════════════════════════════════

class TestWithIdempotencyKey:
    """Assign a key iff absent; never clobber a caller-supplied one."""

    def _req( self, key=None ):
        return NotificationRequest(
            message       = "hi",
            response_type = ResponseType.YES_NO,
            sender_id     = "claude.code@lupin.deepily.ai#abcd1234",
            idempotency_key = key,
        )

    def test_assigns_a_uuid_when_absent( self ):
        out = _with_idempotency_key( self._req( None ) )
        assert out.idempotency_key is not None
        uuid.UUID( out.idempotency_key )                 # parses → it is a real uuid

    def test_preserves_a_caller_supplied_key( self ):
        # NEGATIVE-CONTROL twin: a present key must survive untouched, else the
        # helper would overwrite a deliberate key on every retry (the opposite bug).
        out = _with_idempotency_key( self._req( "keep-me" ) )
        assert out.idempotency_key == "keep-me"


class TestAskVerbsStampIdempotencyKey:
    """End-to-end: each blocking-ask verb stamps a key onto the request it sends."""

    def _resp( self, exit_code=0, response_value="yes", default_used=False ):
        mock                = MagicMock()
        mock.exit_code      = exit_code
        mock.response_value = response_value
        mock.status         = ""
        mock.is_timeout     = ( exit_code == 2 )
        mock.default_used   = default_used
        return mock

    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_ask_yes_no_stamps_a_key( self, mock_notify, mock_sender ):
        # NEGATIVE CONTROL: delete `request = _with_idempotency_key(request)` from
        # ask_yes_no and this fails with `assert None is not None` — the request
        # reaches notify_user_sync with no key.
        mock_notify.return_value = self._resp()
        ask_yes_no.fn( question="Ship it?" )
        sent = mock_notify.call_args.kwargs[ "request" ]
        assert sent.idempotency_key is not None
        uuid.UUID( sent.idempotency_key )

    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_ask_multiple_choice_stamps_a_key( self, mock_notify, mock_sender ):
        mock_notify.return_value = self._resp( response_value='{"answers": {"Database": "MongoDB"}}' )
        ask_multiple_choice.fn( questions=[ {
            "question": "Which database?", "header": "Database", "multiSelect": False,
            "options": [ { "label": "PostgreSQL" }, { "label": "MongoDB" } ]
        } ] )
        sent = mock_notify.call_args.kwargs[ "request" ]
        assert sent.idempotency_key is not None
        uuid.UUID( sent.idempotency_key )


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

    def _mock_response( self, exit_code=0, response_value=None, status="", is_timeout=None, default_used=False , error_detail=None ):
        """Create a mock NotificationResponse.

        is_timeout defaults to (exit_code == 2) to mirror notify_user_sync's real
        wiring, but the caller can force it True (e.g. the exit_code==1 /
        "expired_no_default" expiry path, which IS a timeout) or False (a genuine
        transport error at exit_code==1).

        ⚠️ `default_used` MUST be set explicitly (row e5f21fff). An unset
        attribute on a MagicMock is a TRUTHY Mock, so a mock that omits it makes
        every response look defaulted the moment the code starts reading the
        field. It defaults to False here to mirror a RespondedEvent carrying the
        server's own False — pass True to model an OfflineEvent or a server-side
        default substitution.
        """
        if is_timeout is None:
            is_timeout = ( exit_code == 2 )
        mock                = MagicMock()
        mock.exit_code      = exit_code
        mock.response_value = response_value
        mock.status         = status
        mock.is_timeout     = is_timeout
        mock.default_used   = default_used
        # Same MagicMock trap the docstring above names for default_used: an unset
        # attribute is a TRUTHY Mock. `error_detail` (row cd283a77) is read by
        # _error_dict, so leaving it unset makes every error look like it carries a
        # server sentence. None models the honest case — a transport failure has no
        # server body to quote; a test wanting one passes error_detail=.
        mock.error_detail   = error_detail
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
        assert result == { "answers": { "Database": "PostgreSQL" }, "default_used": True, "answered": False }

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
        assert result == { "answers": { "Features": [ "Auth", "Caching" ] }, "default_used": True, "answered": False }

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
        assert result == { "answers": { "Database": "PostgreSQL" }, "default_used": True, "answered": False }

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
        assert result == { "answers": { "Database": "PostgreSQL" }, "default_used": True, "answered": False }

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
        assert result == { "answers": { "Merge gate": "Not mine — hold" }, "default_used": True, "answered": False }

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
        assert result == { "answers": { "Database": "MongoDB" }, "default_used": False, "answered": True }


# ═════════════════════════════════════════════════════════════════════════════
# TestResponseDefaultPlumbedToRequest — bug f433fbae, D1
#
# The FALSE-503-while-online defect: ask_multiple_choice never passed
# response_default to the NotificationRequest, so the server raised
# HTTPException(503, "User is offline and no default response provided") on the
# offline branch — including the false-offline window after a bounce wipes the
# in-memory ws_manager, i.e. a user sitting at the keyboard. ask_yes_no has
# always plumbed its string default; this class proves the MULTIPLE_CHOICE path
# now does too, and in the shape _parse_multiple_choice_response round-trips.
#
# These assert on what reaches NotificationRequest (the mocked build), which is
# the exact seam the defect lived at — the request was constructed without the
# field. The negative control is documented per-test.
# ═════════════════════════════════════════════════════════════════════════════

class TestResponseDefaultPlumbedToRequest:
    """response_default must reach the request when (and only when) a default is given."""

    SINGLE_QUESTION = TestAskMultipleChoiceDefault.SINGLE_QUESTION
    MULTI_QUESTION  = TestAskMultipleChoiceDefault.MULTI_QUESTION

    def _resp( self, exit_code=2, response_value=None, status="", is_timeout=None, default_used=False , error_detail=None ):
        if is_timeout is None:
            is_timeout = ( exit_code == 2 )
        mock                = MagicMock()
        mock.exit_code      = exit_code
        mock.response_value = response_value
        mock.status         = status
        mock.is_timeout     = is_timeout
        mock.default_used   = default_used
        # Same MagicMock trap the docstring above names for default_used: an unset
        # attribute is a TRUTHY Mock. `error_detail` (row cd283a77) is read by
        # _error_dict, so leaving it unset makes every error look like it carries a
        # server sentence. None models the honest case — a transport failure has no
        # server body to quote; a test wanting one passes error_detail=.
        mock.error_detail   = error_detail
        return mock

    def _patches( fn ):
        fn = patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )( fn )
        return fn

    @_patches
    def test_single_select_default_serialized_into_response_default( self, mock_notify, mock_sender, mock_abstract, mock_request ):
        # NEGATIVE CONTROL: delete the `response_default=` line in
        # ask_multiple_choice and this fails with
        # `AssertionError: assert None == '{"answers": {"Database": "PostgreSQL"}}'`
        # — the field is absent from the call, so .get() returns None.
        mock_notify.return_value = self._resp( exit_code=2 )

        ask_multiple_choice.fn(
            questions = self.SINGLE_QUESTION,
            default   = { "Database": "PostgreSQL" }
        )

        passed = mock_request.call_args.kwargs.get( "response_default" )
        assert passed == json.dumps( { "answers": { "Database": "PostgreSQL" } } )
        # And it round-trips through the client's own parser back to the default.
        assert json.loads( passed ) == { "answers": { "Database": "PostgreSQL" } }

    @_patches
    def test_multi_select_default_serialized_into_response_default( self, mock_notify, mock_sender, mock_abstract, mock_request ):
        mock_notify.return_value = self._resp( exit_code=2 )

        ask_multiple_choice.fn(
            questions = self.MULTI_QUESTION,
            default   = { "Features": [ "Auth", "Caching" ] }
        )

        passed = mock_request.call_args.kwargs.get( "response_default" )
        assert passed == json.dumps( { "answers": { "Features": [ "Auth", "Caching" ] } } )

    @_patches
    def test_no_default_leaves_response_default_none( self, mock_notify, mock_sender, mock_abstract, mock_request ):
        # The honest 503 stays for "offline and no safe default to substitute".
        # NEGATIVE CONTROL: if the code hard-coded a non-None default, this fails
        # with `assert '<something>' is None`.
        mock_notify.return_value = self._resp( exit_code=2 )

        ask_multiple_choice.fn( questions=self.SINGLE_QUESTION )

        assert mock_request.call_args.kwargs.get( "response_default" ) is None


# ═════════════════════════════════════════════════════════════════════════════
# TestDefaultUsedLaundering — row e5f21fff
#
# A timeout, or an ABSENT user, must not be shaped like a ruling. `default_used`
# is the only bit distinguishing "the user decided" from "the user was not
# there", and both MCP return sites discarded it.
#
# ⚠️ THE TRACE FOUND TWO DROP SITES, NOT ONE. The filed row names only the
# is_timeout branch (:1653). notify_user_sync.py:295-303 maps an OfflineEvent to
# exit_code=0 / default_used=True — commented "Offline with default = success" —
# so a PROVABLY OFFLINE user returns through the SUCCESS branch (:1637), is
# parsed as an answer, and never reaches the timeout branch at all.
#
# ⚠️ MagicMock hazard: an unset attribute is a truthy Mock, so `default_used`
# MUST be set explicitly on every mock here. A test that forgot it would read
# truthy and pass against a broken implementation.
# ═════════════════════════════════════════════════════════════════════════════

class TestDefaultUsedLaundering:
    """Both drop sites must distinguish a substituted default from a real answer."""

    SINGLE_QUESTION = TestAskMultipleChoiceDefault.SINGLE_QUESTION

    def _resp( self, exit_code=0, response_value=None, status="", is_timeout=None, default_used=False , error_detail=None ):
        if is_timeout is None:
            is_timeout = ( exit_code == 2 )
        mock                = MagicMock()
        mock.exit_code      = exit_code
        mock.response_value = response_value
        mock.status         = status
        mock.is_timeout     = is_timeout
        mock.default_used   = default_used          # NEVER leave this to MagicMock
        mock.error_detail   = error_detail           # nor this (row cd283a77) — same trap
        return mock

    # ⚠️ Applied in REVERSE of the decorator stack the sibling class uses, because
    # decorators apply bottom-up: the FIRST patch applied here is the innermost
    # and therefore supplies the FIRST mock argument. Writing these in the same
    # textual order as a top-down decorator stack silently hands you the WRONG
    # mock — `mock_notify` becomes the NotificationRequest patch, the real
    # notify_user_sync mock returns a bare MagicMock whose `.is_timeout` is a
    # TRUTHY Mock, and every test goes red for a reason that has nothing to do
    # with the code under test. Caught here on the first run; a red test proves
    # nothing until you know WHY it is red.
    def _patches( fn ):
        fn = patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )( fn )
        return fn

    # ---- drop site 1: the timeout branch (:1653) — the filed one -------------

    @_patches
    def test_timeout_with_default_admits_the_default_was_used( self, mock_notify, *_ ):
        # AC-1. A timed-out ask WITH a default must say so.
        mock_notify.return_value = self._resp( exit_code=2, default_used=False )
        default = { "Database": "PostgreSQL" }

        result = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION, default=default )

        assert result[ "answers" ] == default
        assert result[ "default_used" ] is True
        assert result[ "answered" ] is False

    # ---- drop site 2: the SUCCESS branch (:1637) — the one nobody filed ------

    @_patches
    def test_OFFLINE_user_does_not_return_a_ruling_shaped_answer( self, mock_notify, *_ ):
        """
        THE DROP SITE THE ROW MISSED. notify_user_sync maps OfflineEvent to
        exit_code=0 with default_used=True ("Offline with default = success").
        It never reaches the timeout branch, so the row's one-line fix at :1653
        cannot touch it. A provably-absent user must not read as a decision.
        """
        mock_notify.return_value = self._resp(
            exit_code      = 0,
            status         = "offline",
            response_value = '{"answers": {"Database": "MongoDB"}}',
            default_used   = True,
        )

        result = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION )

        assert result[ "default_used" ] is True
        assert result[ "answered" ] is False

    @_patches
    def test_real_selection_is_EXPLICITLY_not_defaulted( self, mock_notify, *_ ):
        # AC-2 / D4: an explicit False, never an absent key — so a caller reading
        # .get("default_used") gets False rather than None and cannot confuse
        # "the user answered" with "an old server that never sent the field".
        mock_notify.return_value = self._resp(
            exit_code      = 0,
            response_value = '{"answers": {"Database": "MongoDB"}}',
            default_used   = False,
        )

        result = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION )

        assert result[ "answers" ] == { "Database": "MongoDB" }
        assert result[ "default_used" ] is False
        assert result[ "answered" ] is True

    @_patches
    def test_THE_TWO_SHAPES_ARE_DISTINGUISHABLE( self, mock_notify, *_ ):
        """
        AC-7 — THE ASSERTION THAT IS THE POINT OF THE ROW. Not "each shape is
        well-formed" but "they cannot be mistaken for each other". A test
        checking only `answers == default` on both paths passes against the
        defect, which is how this survived.
        """
        default = { "Database": "PostgreSQL" }

        mock_notify.return_value = self._resp( exit_code=2, default_used=False )
        timed_out = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION, default=default )

        mock_notify.return_value = self._resp(
            exit_code      = 0,
            response_value = '{"answers": {"Database": "PostgreSQL"}}',
            default_used   = False,
        )
        chosen = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION, default=default )

        assert timed_out[ "answers" ] == chosen[ "answers" ]      # the VALUES agree...
        assert timed_out != chosen                                # ...the SHAPES must not
        assert timed_out[ "default_used" ] != chosen[ "default_used" ]

    # ---- the control that already fires correctly — must not move ------------

    @_patches
    def test_timeout_without_default_keeps_its_exact_prior_shape( self, mock_notify, *_ ):
        # AC-3. This path already surfaces a non-answer AS a non-answer; it is the
        # control proving the with-default silence was a defect and not a design.
        mock_notify.return_value = self._resp( exit_code=2, default_used=False )

        result = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION )

        assert result == { "error": "timeout - no response received", "timeout": True }

    @_patches
    def test_genuine_transport_error_is_untouched( self, mock_notify, *_ ):
        # A real error must stay an error — never masked by a default.
        mock_notify.return_value = self._resp(
            exit_code=1, status="stream_error", is_timeout=False, default_used=False
        )

        result = ask_multiple_choice.fn( questions=self.SINGLE_QUESTION, default={ "Database": "PostgreSQL" } )

        assert result == { "error": "error: stream_error" }


# ═════════════════════════════════════════════════════════════════════════════
# TestAskYesNoLaundering — row e5f21fff, sibling D2
#
# ask_yes_no is WORSE than the verb the row is titled after. Its terminal
# `return default` catches timeout, expiry, offline, transport error, server
# error AND a validation failure — it has NO error shape at all, so EVERY
# non-answer is returned as a bare "yes"/"no" indistinguishable from a keypress.
#
# It returns a STRING, so there is nowhere to put a flag without changing the
# return type. The marker is therefore the converse pattern (:1174) — the ruled
# reference — and it stays inside this verb's OWN documented contract, which
# already promises an ANNOTATED string ("yes [comment: ...]"). A caller doing
# `== "yes"` was already broken by a qualifier comment.
#
# Verified before changing it: the hooks that compare `== "yes"`
# (stop.py:843, idle_waiter.py:285, permission_request.py:169) call
# notify_user_sync DIRECTLY and never touch this verb's return.
# ═════════════════════════════════════════════════════════════════════════════

class TestAskYesNoLaundering:
    """Every path that returns the default must SAY it is the default."""

    def _resp( self, exit_code=0, response_value=None, status="", is_timeout=None, default_used=False , error_detail=None ):
        if is_timeout is None:
            is_timeout = ( exit_code == 2 )
        mock                = MagicMock()
        mock.exit_code      = exit_code
        mock.response_value = response_value
        mock.status         = status
        mock.is_timeout     = is_timeout
        mock.default_used   = default_used
        # Same MagicMock trap the docstring above names for default_used: an unset
        # attribute is a TRUTHY Mock. `error_detail` (row cd283a77) is read by
        # _error_dict, so leaving it unset makes every error look like it carries a
        # server sentence. None models the honest case — a transport failure has no
        # server body to quote; a test wanting one passes error_detail=.
        mock.error_detail   = error_detail
        return mock

    def _patches( fn ):
        fn = patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )( fn )
        return fn

    @_patches
    def test_real_keypress_is_returned_CLEAN( self, mock_notify, *_ ):
        # THE NEGATIVE CONTROL. A genuine answer must carry NO marker — otherwise
        # the marker means nothing. This is the arm that fails if I mark blindly.
        mock_notify.return_value = self._resp( exit_code=0, response_value="yes", default_used=False )

        assert ask_yes_no.fn( question="Ship it?" ) == "yes"

    @_patches
    def test_timeout_default_is_MARKED( self, mock_notify, *_ ):
        # The whole point: an unanswered question must not read as "yes".
        mock_notify.return_value = self._resp( exit_code=2, default_used=False )

        result = ask_yes_no.fn( question="Ship it?", default="yes" )

        assert result != "yes"                        # NOT mistakable for a ruling
        assert "yes" in result                        # the default is still conveyed
        assert "[default used]" in result

    @_patches
    def test_OFFLINE_user_is_MARKED_even_though_exit_code_is_zero( self, mock_notify, *_ ):
        # The success-door path again: notify_user_sync maps OfflineEvent to
        # exit_code=0 with default_used=True. A provably-absent user reaches the
        # `exit_code == 0` branch carrying a response_value.
        mock_notify.return_value = self._resp(
            exit_code=0, response_value="yes", status="offline", default_used=True
        )

        result = ask_yes_no.fn( question="Ship it?" )

        assert result != "yes"
        assert "[default used]" in result

    @_patches
    def test_transport_error_does_not_read_as_an_answer( self, mock_notify, *_ ):
        # The terminal `return default` also catches genuine errors. Marking it is
        # honest for what the caller actually receives: this value is the default,
        # NOT an answer. (That an error is indistinguishable from a timeout here at
        # all is a separate, breaking-to-fix asymmetry — converse returns
        # "[error: status]" and never substitutes. Recorded, not fixed.)
        mock_notify.return_value = self._resp(
            exit_code=1, status="stream_error", is_timeout=False, default_used=False
        )

        result = ask_yes_no.fn( question="Ship it?", default="no" )

        assert result != "no"
        assert "[default used]" in result

    @_patches
    def test_marker_matches_converse_exactly( self, mock_notify, *_ ):
        # D3: consistent with the established reference, not a third convention.
        mock_notify.return_value = self._resp( exit_code=2, default_used=False )

        result = ask_yes_no.fn( question="Ship it?", default="no" )

        assert result.startswith( "[default used] " )
        assert result == "[default used] no"


# ═════════════════════════════════════════════════════════════════════════════
# TestConverseMarkerUnchanged — AC-5, row e5f21fff
#
# converse is the RULED REFERENCE (D3): it has carried "[default used] " since
# before the row was filed, and its marker is STRUCTURAL — you cannot read the
# value without reading it. The row's fix must leave its BEHAVIOUR untouched
# while sourcing the ONE shared constant, so the family cannot drift into two
# spellings of the same claim.
#
# These also cover the line the constant refactor touched. Both arms, because a
# marker that never appears and a marker that always appears are equally useless
# and only the pair distinguishes them.
# ═════════════════════════════════════════════════════════════════════════════

class TestConverseMarkerUnchanged:

    def _resp( self, exit_code=0, response_value="", status="", default_used=False ):
        mock                = MagicMock()
        mock.exit_code      = exit_code
        mock.response_value = response_value
        mock.status         = status
        mock.default_used   = default_used
        return mock

    def _patches( fn ):
        fn = patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )( fn )
        fn = patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )( fn )
        return fn

    @_patches
    def test_real_answer_carries_NO_marker( self, mock_notify, *_ ):
        mock_notify.return_value = self._resp( exit_code=0, response_value="ship it", default_used=False )
        assert converse.fn( message="What now?" ) == "ship it"

    @_patches
    def test_server_substituted_answer_IS_marked( self, mock_notify, *_ ):
        mock_notify.return_value = self._resp( exit_code=0, response_value="ship it", default_used=True )

        result = converse.fn( message="What now?" )

        assert result == "[default used] ship it"
        assert result != "ship it"

    @_patches
    def test_marker_is_the_ONE_shared_constant( self, mock_notify, *_ ):
        # The anti-drift assertion: converse and ask_yes_no must not grow two
        # spellings of "the user did not choose this".
        mock_notify.return_value = self._resp( exit_code=0, response_value="ship it", default_used=True )
        converse_out = converse.fn( message="What now?" )

        mock_notify.return_value = self._resp( exit_code=2, default_used=False )
        yes_no_out = ask_yes_no.fn( question="Ship it?", default="no" )

        assert converse_out.startswith( DEFAULT_USED_MARKER )
        assert yes_no_out.startswith( DEFAULT_USED_MARKER )


class TestStampAnswerProvenance:
    """Direct unit tests on the helper — including the arm nothing else reaches."""

    def test_error_payload_is_returned_UNTOUCHED( self ):
        # Provenance describes an ANSWER, and an error is not one. Stamping
        # "answered": False onto a transport failure would assert something about
        # the user that the failure says nothing about.
        payload = { "error": "error: stream_error" }
        assert _stamp_answer_provenance( payload, default_used=False ) == payload
        assert _stamp_answer_provenance( payload, default_used=True )  == payload

    def test_answer_payload_gets_both_keys_and_they_are_consistent( self ):
        stamped = _stamp_answer_provenance( { "answers": { "A": "b" } }, default_used=True )
        assert stamped == { "answers": { "A": "b" }, "default_used": True, "answered": False }

    def test_does_not_mutate_the_input( self ):
        original = { "answers": { "A": "b" } }
        _stamp_answer_provenance( original, default_used=True )
        assert original == { "answers": { "A": "b" } }          # caller's dict untouched

    @pytest.mark.parametrize( "default_used", [ True, False ] )
    def test_answered_is_always_the_negation( self, default_used ):
        stamped = _stamp_answer_provenance( { "answers": {} }, default_used=default_used )
        assert stamped[ "answered" ] is ( not default_used )


class TestAskYesNoValidationFailure:
    """The request never even left the building — that is not an answer either."""

    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )
    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest", side_effect=ValueError( "bad request" ) )
    def test_request_validation_failure_returns_a_MARKED_default( self, *_ ):
        # This path returned a bare default on a request that was never sent — the
        # caller was told "no" by a construction error. It is the least
        # answer-like path in the verb and it looked exactly like an answer.
        result = ask_yes_no.fn( question="Ship it?", default="no" )

        assert result == "[default used] no"
        assert result != "no"
