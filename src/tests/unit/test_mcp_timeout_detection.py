"""
Unit tests for MCP timeout / offline → VoiceGateTimeoutError conversion.

The cosa-voice MCP server signals:
  exit_code == 0 → user responded (or offline with caller-provided default)
  exit_code == 2 → explicit "user-unavailable timeout" (SSE `expired` event)
  exit_code == 1 → other errors (HTTP 503 "User is offline", connection error, etc.)

The AgentNotificationDispatcher converts BOTH exit_code==2 AND any other
non-0 code into VoiceGateTimeoutError so the orchestrator's
checkpoint-resume path fires reliably, instead of silently falling back
to the caller's default (which produces `status=completed` rows that the
UI Resume button cannot act on).

History:
  - Session 9056c113 doc 16 Phase 1: added exit_code==2 → raise (timeout signal)
  - Session f01fdc2f (2026-04-15, commit 49c238d): added empty-answers and
    catch-all raise to `present_choices` (Bug 7)
  - Session f01fdc2f-continuation (2026-04-16, Bug 12): extended catch-all
    to `ask_confirmation` and `get_feedback` so HTTP 503 "User is offline"
    also triggers stall instead of default fall-through
"""

import pytest
from unittest.mock import MagicMock, patch


def _make_response( exit_code=0, response_value=None, status="ok" ):
    """Build a mock NotificationResponse with explicit status for Bug 12 message."""
    resp = MagicMock()
    resp.exit_code      = exit_code
    resp.response_value = response_value
    resp.status         = status
    return resp


def _make_valid_questions( num_options=2 ):
    """Build a valid questions list (Pydantic requires 2-20 options)."""
    return [ {
        "question"    : "Pick one",
        "header"      : "Choice",
        "multiSelect" : False,
        "options"     : [ { "label": f"opt{i}", "description": f"option {i}" }
                          for i in range( num_options ) ],
    } ]


# ===========================================================================
# ask_confirmation — exit_code=2 (explicit timeout) AND exit_code=1 (offline)
# both raise VoiceGateTimeoutError (Bug 12, 2026-04-16)
# ===========================================================================

class TestAskConfirmationRaisesOnUnavailable:
    """ask_confirmation converts MCP non-0 responses to VoiceGateTimeoutError."""

    @pytest.mark.asyncio
    async def test_raises_on_exit_code_2( self ):
        """exit_code=2 is MCP's explicit timeout signal."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=2 )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.ask_confirmation( "Does this look right?", default="yes", timeout=5 )

        assert exc_info.value.phase == "confirmation"
        assert "timeout" in str( exc_info.value ).lower()

    @pytest.mark.asyncio
    async def test_raises_on_http_503_offline( self ):
        """exit_code=1 with http_error_503 is 'User is offline' — must raise (Bug 12)."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=1, status="http_error_503" )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.ask_confirmation( "q", default="yes", timeout=5 )

        assert exc_info.value.phase == "confirmation"
        assert "no answer" in str( exc_info.value ).lower()
        assert "http_error_503" in str( exc_info.value )

    @pytest.mark.asyncio
    async def test_raises_on_connection_error( self ):
        """Other non-0 exit codes (connection error, etc.) also raise (Bug 12)."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=1, status="connection_error" )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            with pytest.raises( VoiceGateTimeoutError ):
                await dispatcher.ask_confirmation( "q", default="yes", timeout=5 )

    @pytest.mark.asyncio
    async def test_happy_path_returns_true_on_yes( self ):
        """exit_code=0 + response_value='yes' → True (unchanged)."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=0, response_value="yes" )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            result = await dispatcher.ask_confirmation( "q", default="no", timeout=5 )

        assert result is True

    @pytest.mark.asyncio
    async def test_happy_path_returns_false_on_no( self ):
        """exit_code=0 + response_value='no' → False (unchanged)."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=0, response_value="no" )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            result = await dispatcher.ask_confirmation( "q", default="yes", timeout=5 )

        assert result is False


# ===========================================================================
# get_feedback — same contract (Bug 12)
# ===========================================================================

class TestGetFeedbackRaisesOnUnavailable:
    """get_feedback converts MCP non-0 responses to VoiceGateTimeoutError."""

    @pytest.mark.asyncio
    async def test_raises_on_exit_code_2( self ):
        """exit_code=2 timeout signal (new — was missing in get_feedback before Bug 12)."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=2 )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.get_feedback( "What do you think?", timeout=5 )

        assert exc_info.value.phase == "feedback"

    @pytest.mark.asyncio
    async def test_raises_on_http_503_offline( self ):
        """exit_code=1 http_error_503 (Bug 12) — must raise."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=1, status="http_error_503" )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.get_feedback( "q", timeout=5 )

        assert exc_info.value.phase == "feedback"
        assert "no answer" in str( exc_info.value ).lower()

    @pytest.mark.asyncio
    async def test_happy_path_returns_response_value( self ):
        """exit_code=0 → return the response string."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=0, response_value="hello world" )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            result = await dispatcher.get_feedback( "q", timeout=5 )

        assert result == "hello world"


# ===========================================================================
# present_choices — already covered by commit 49c238d (Bug 7), regression-guarded
# ===========================================================================

class TestPresentChoicesRaisesOnUnavailable:
    """present_choices converts MCP non-0 responses to VoiceGateTimeoutError."""

    @pytest.mark.asyncio
    async def test_raises_on_exit_code_2( self ):
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=2 )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.present_choices( _make_valid_questions(), timeout=5 )

        assert exc_info.value.phase == "choices"
        assert "timeout" in str( exc_info.value ).lower()

    @pytest.mark.asyncio
    async def test_raises_on_http_503_offline( self ):
        """exit_code=1 http_error_503 → VoiceGateTimeoutError (regression guard for 49c238d)."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=1, status="http_error_503" )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.present_choices( _make_valid_questions(), timeout=5 )

        assert exc_info.value.phase == "choices"

    @pytest.mark.asyncio
    async def test_raises_on_empty_answers_payload( self ):
        """Bug 7 normalization: exit_code=0 + empty answers dict → treat as timeout."""
        import json
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        resp = _make_response( exit_code=0, response_value=json.dumps( { "answers": {} } ) )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            with pytest.raises( VoiceGateTimeoutError ):
                await dispatcher.present_choices( _make_valid_questions(), timeout=5 )

    @pytest.mark.asyncio
    async def test_happy_path_returns_parsed_answers( self ):
        """exit_code=0 + valid JSON answers → return dict."""
        import json
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"
        answer_payload = { "answers": { "Choice": "opt0" } }
        resp = _make_response( exit_code=0, response_value=json.dumps( answer_payload ) )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=resp ):
            result = await dispatcher.present_choices( _make_valid_questions(), timeout=5 )

        assert result == answer_payload


# ===========================================================================
# Exception identity: BFE and TFE must see the SAME exception class
# ===========================================================================

class TestExceptionIdentity:
    """The exception raised by the dispatcher must match what BFE/TFE catch."""

    def test_bfe_and_tfe_and_dispatcher_see_same_voicegate_timeout( self ):
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError as TFEExc
        from cosa.agents.bug_fix_expediter.state import VoiceGateTimeoutError as BFEExc
        # They must be the SAME class (BFE re-exports TFE's via __getattr__)
        assert TFEExc is BFEExc


# ===========================================================================
# Bug 13 (2026-04-16): Pre-MCP failures (ValidationError etc.) must also
# raise VoiceGateTimeoutError, not swallow to silent default/empty answers.
#
# Observed in tfe-e4c73d5c: abstract > 5000 chars triggered a Pydantic
# ValidationError at NotificationRequest construction time, before the
# MCP call. The outer except caught it and returned `{"answers": {}}`,
# which the orchestrator read as "user selected nothing" → status=completed
# instead of stalled. Fix: treat pre-MCP ValidationError / ConnectionError
# as "voice gate unreachable" → raise VoiceGateTimeoutError so the
# orchestrator stalls with a checkpoint.
#
# ALSO: the underlying 5000-char cap on `message` and `abstract` in
# NotificationRequest / AsyncNotificationRequest was the root cause —
# this was removed at the same time so TFE aggregate voice gates with
# long proposal lists don't fail in mysterious ways. These tests guard
# both behaviors.
# ===========================================================================

class TestBug13PreMCPFailureStalls:
    """Pre-MCP validation/connection failures stall instead of silently default."""

    def test_no_5000_char_cap_on_notification_request_abstract( self ):
        """Regression guard: 10_000-char abstract must validate cleanly."""
        from lupin_cli.notifications.notification_models import (
            NotificationRequest, ResponseType, NotificationType, NotificationPriority,
        )
        long_abstract = "x" * 10_000
        req = NotificationRequest(
            message           = "hi",
            response_type     = ResponseType.YES_NO,
            notification_type = NotificationType.CUSTOM,
            priority          = NotificationPriority.HIGH,
            target_user       = "test@example.com",
            timeout_seconds   = 5,
            abstract          = long_abstract,
        )
        assert len( req.abstract ) == 10_000

    def test_no_5000_char_cap_on_notification_request_message( self ):
        """Regression guard: 10_000-char message must validate cleanly."""
        from lupin_cli.notifications.notification_models import (
            NotificationRequest, ResponseType, NotificationType, NotificationPriority,
        )
        req = NotificationRequest(
            message           = "y" * 10_000,
            response_type     = ResponseType.YES_NO,
            notification_type = NotificationType.CUSTOM,
            priority          = NotificationPriority.HIGH,
            target_user       = "test@example.com",
            timeout_seconds   = 5,
        )
        assert len( req.message ) == 10_000

    @pytest.mark.asyncio
    async def test_present_choices_raises_on_pydantic_validation_error( self ):
        """
        If NotificationRequest construction raises (e.g. a future field cap),
        present_choices must convert it to VoiceGateTimeoutError (stall path),
        NOT swallow to `{"answers": {}}` (which the orchestrator misreads as
        'user selected nothing' → status=completed).
        """
        from pydantic import ValidationError
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"

        # Patch NotificationRequest in the dispatcher's namespace to raise on construction
        with patch( "cosa.agents.utils.agent_notification_dispatcher.NotificationRequest",
                    side_effect=ValidationError.from_exception_data(
                        "NotificationRequest",
                        [ { "type": "string_too_long", "loc": ( "abstract", ), "input": "x", "ctx": { "max_length": 5 } } ],
                    ) ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.present_choices( _make_valid_questions(), timeout=5 )

        assert exc_info.value.phase == "choices"
        assert "pre-MCP" in str( exc_info.value )
        assert "ValidationError" in str( exc_info.value )

    @pytest.mark.asyncio
    async def test_ask_confirmation_raises_on_pydantic_validation_error( self ):
        """Same Bug 13 fix on ask_confirmation."""
        from pydantic import ValidationError
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"

        with patch( "cosa.agents.utils.agent_notification_dispatcher.NotificationRequest",
                    side_effect=ValidationError.from_exception_data(
                        "NotificationRequest",
                        [ { "type": "string_too_long", "loc": ( "abstract", ), "input": "x", "ctx": { "max_length": 5 } } ],
                    ) ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.ask_confirmation( "proceed?", timeout=5 )

        assert exc_info.value.phase == "confirmation"
        assert "pre-MCP" in str( exc_info.value )

    @pytest.mark.asyncio
    async def test_get_feedback_raises_on_pydantic_validation_error( self ):
        """Same Bug 13 fix on get_feedback."""
        from pydantic import ValidationError
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"

        with patch( "cosa.agents.utils.agent_notification_dispatcher.NotificationRequest",
                    side_effect=ValidationError.from_exception_data(
                        "NotificationRequest",
                        [ { "type": "string_too_long", "loc": ( "abstract", ), "input": "x", "ctx": { "max_length": 5 } } ],
                    ) ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.get_feedback( "q", timeout=5 )

        assert exc_info.value.phase == "feedback"
        assert "pre-MCP" in str( exc_info.value )

    @pytest.mark.asyncio
    async def test_present_choices_raises_on_connection_error( self ):
        """ConnectionError is also a pre-MCP 'voice gate unreachable' condition."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    side_effect=ConnectionError( "refused" ) ):
            with pytest.raises( VoiceGateTimeoutError ):
                await dispatcher.present_choices( _make_valid_questions(), timeout=5 )

    @pytest.mark.asyncio
    async def test_present_choices_still_returns_empty_on_generic_exception( self ):
        """
        Non-pre-MCP exceptions (e.g. AttributeError from a code bug) must NOT
        silently stall — they should still log+return empty so real bugs surface
        and don't pollute the checkpoint with false-stall rows. Only
        ValidationError + ConnectionError are classified as 'voice gate
        unreachable'.
        """
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        dispatcher.target_user = "test@example.com"

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    side_effect=AttributeError( "bug" ) ):
            result = await dispatcher.present_choices( _make_valid_questions(), timeout=5 )

        assert result == { "answers": {} }
