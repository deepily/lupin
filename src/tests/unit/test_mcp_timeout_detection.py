"""
Unit tests for MCP timeout detection → VoiceGateTimeoutError trigger.

Session 9056c113 doc 16 Phase 1. The cosa-voice MCP server signals user-timeout
via NotificationResponse.exit_code == 2. The AgentNotificationDispatcher now
raises VoiceGateTimeoutError instead of silently returning the default, enabling
the existing checkpoint-resume path in both TFE and BFE.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


def _make_response( exit_code=0, response_value=None ):
    """Build a mock NotificationResponse."""
    resp = MagicMock()
    resp.exit_code = exit_code
    resp.response_value = response_value
    return resp


# ---------------------------------------------------------------------------
# ask_confirmation timeout detection
# ---------------------------------------------------------------------------

class TestAskConfirmationTimeoutDetection:
    """ask_confirmation raises VoiceGateTimeoutError on exit_code==2."""

    @pytest.mark.asyncio
    async def test_ask_confirmation_raises_on_exit_code_2( self ):
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )

        timeout_response = _make_response( exit_code=2 )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=timeout_response ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.ask_confirmation( "Does this look right?", default="yes", timeout=5 )

        assert exc_info.value.phase == "confirmation"
        assert "timeout" in str( exc_info.value ).lower()

    @pytest.mark.asyncio
    async def test_ask_confirmation_returns_default_on_exit_code_1( self ):
        """exit_code=1 is a non-timeout error — fall back to default (existing behavior)."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        error_response = _make_response( exit_code=1 )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=error_response ):
            result = await dispatcher.ask_confirmation( "q", default="yes", timeout=5 )

        assert result is True  # default="yes"

    @pytest.mark.asyncio
    async def test_ask_confirmation_returns_user_response_on_exit_code_0( self ):
        """Normal success path unchanged: user answered, parse response_value."""
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        ok_response = _make_response( exit_code=0, response_value="yes" )

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=ok_response ):
            result = await dispatcher.ask_confirmation( "q", default="no", timeout=5 )

        assert result is True


# ---------------------------------------------------------------------------
# present_choices timeout detection
# ---------------------------------------------------------------------------

class TestPresentChoicesTimeoutDetection:
    """present_choices raises VoiceGateTimeoutError on exit_code==2."""

    @pytest.mark.asyncio
    async def test_present_choices_raises_on_exit_code_2( self ):
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        timeout_response = _make_response( exit_code=2 )

        questions = [ {
            "question": "Pick one", "header": "Choice", "multiSelect": False,
            "options": [ {"label": "A", "description": "opt A"}, {"label": "B", "description": "opt B"} ],
        } ]

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=timeout_response ):
            with pytest.raises( VoiceGateTimeoutError ) as exc_info:
                await dispatcher.present_choices( questions, timeout=5 )

        assert exc_info.value.phase == "choices"
        assert "timeout" in str( exc_info.value ).lower()

    @pytest.mark.asyncio
    async def test_present_choices_returns_empty_answers_on_exit_code_1( self ):
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher

        dispatcher = AgentNotificationDispatcher( agent_type="test.agent" )
        error_response = _make_response( exit_code=1 )

        questions = [ {"question": "q", "header": "h", "multiSelect": False, "options": [ {"label": "a", "description": "x"} ]} ]

        with patch( "cosa.agents.utils.agent_notification_dispatcher._notify_user_sync",
                    return_value=error_response ):
            result = await dispatcher.present_choices( questions, timeout=5 )

        assert result == { "answers": {} }


# ---------------------------------------------------------------------------
# Exception identity: BFE and TFE must see the SAME exception class
# ---------------------------------------------------------------------------

class TestExceptionIdentity:
    """The exception raised by the dispatcher must match what BFE/TFE catch."""

    def test_bfe_and_tfe_and_dispatcher_see_same_voicegate_timeout( self ):
        from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError as TFEExc
        from cosa.agents.bug_fix_expediter.state import VoiceGateTimeoutError as BFEExc
        # They must be the SAME class (BFE re-exports TFE's via __getattr__)
        assert TFEExc is BFEExc
