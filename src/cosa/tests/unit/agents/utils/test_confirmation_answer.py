"""
Unit tests for ask_confirmation_answer, which keeps the whole answer.

The notification boundary is patched, so nothing leaves the process and nothing is spent.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.agents.utils.agent_notification_dispatcher as mod
from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher, ConfirmationAnswer
from cosa.agents.test_fix_expediter.state import VoiceGateTimeoutError


def _resp( exit_code=0, response_value=None ):
    r = MagicMock()
    r.exit_code      = exit_code
    r.response_value = response_value
    r.status         = "ok"
    r.notification_id = "n-1"
    return r


def _run( coro ):
    return asyncio.run( coro )


# The four answer shapes, then the edge shapes. The bool column is written as literals: it is what
# ask_confirmation returned before this change, `raw.lower().strip().startswith( "yes" )`.
SHAPES = [
    ( "yes",                          "yes",     None,       True  ),
    ( "no",                           "no",      None,       False ),
    ( "neither",                      "neither", None,       False ),
    ( "yes [comment: fix the tests]", "yes",     "fix the tests", True ),
    ( "no [comment: not ready]",      "no",      "not ready",     False ),
    ( "neither [comment: re-frame]",  "neither", "re-frame",      False ),
    ( "  YES  ",                      "yes",     None,       True  ),
    ( "Yes, proceed",                 None,      None,       True  ),
    ( "yesterday",                    None,      None,       True  ),
    ( "Maybe later",                  None,      None,       False ),
]


@pytest.mark.parametrize( "raw, stance, comment, approved", SHAPES )
def test_answer_carries_stance_comment_and_raw_text( raw, stance, comment, approved ):
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, raw ) ):
        answer = _run( d.ask_confirmation_answer( "Proceed?" ) )
    assert answer == ConfirmationAnswer( stance=stance, comment=comment, raw=raw )
    assert answer.approved is approved


@pytest.mark.parametrize( "raw, stance, comment, approved", SHAPES )
def test_bool_wrapper_returns_exactly_todays_value_for_every_shape( raw, stance, comment, approved ):
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, raw ) ):
        assert _run( d.ask_confirmation( "Proceed?" ) ) is approved


def test_answer_records_the_carrying_notification_id():
    d = AgentNotificationDispatcher( agent_type="test.agent" )

    async def go():
        with patch.object( mod, "_notify_user_sync", return_value=_resp( 0, "no" ) ):
            await d.ask_confirmation_answer( "Proceed?" )
        return mod.take_last_ask_notification_id()

    assert _run( go() ) == "n-1"


def test_answer_with_no_response_raises_the_same_timeout_as_the_bool_wrapper():
    d = AgentNotificationDispatcher( agent_type="test.agent" )
    with patch.object( mod, "_notify_user_sync", return_value=_resp( 2, None ) ):
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.ask_confirmation_answer( "Proceed?" ) )
        with pytest.raises( VoiceGateTimeoutError ):
            _run( d.ask_confirmation( "Proceed?" ) )


def test_role_wrapper_forwards_to_the_dispatcher_sibling_with_the_role():
    d = MagicMock()
    d.ask_confirmation_answer = AsyncMock( return_value=ConfirmationAnswer( "neither", None, "neither" ) )
    ns = { "__name__": "fake.role_module", "_dispatcher": d, "SESSION_ID": "s", "SESSION_NAME": "n", "TARGET_USER": "u@x" }
    wrapper = mod.make_role_interface_functions( ns )[ 4 ]
    assert wrapper.__name__ == "ask_confirmation_answer"
    assert _run( wrapper( "ok?", "tester", "yes", 30, "abs" ) ) == ConfirmationAnswer( "neither", None, "neither" )
    args, kwargs = d.ask_confirmation_answer.await_args
    assert args == ( "ok?", ) and kwargs == { "default": "yes", "timeout": 30, "abstract": "abs", "role": "tester" }
    assert ( d.session_id, d.target_user ) == ( "s", "u@x" )
