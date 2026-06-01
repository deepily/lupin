"""
Unit tests for cosa/agents/test_suite/cosa_interface.py.

The notification dispatch is boundary-mocked at the shared `_dispatcher` instance,
so NO notification leaves the process. ZERO API spend.

TRIPWIRE: `ask_yes_no` is a confirmed PROD BUG — it calls a nonexistent
`_dispatcher.ask_yes_no` (the dispatcher only exposes `ask_confirmation`, with a
different signature). Per campaign doctrine the bug is NOT fixed here: an
xfail(strict=True) asserts the correct contract and a pin captures the current
(raising) behavior. Manager owns the fix + de-arm.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import cosa.agents.test_suite.cosa_interface as ci


def _run( coro ):
    return asyncio.run( coro )


# =========================================================================== #
# _get_sender_id
# =========================================================================== #
def test_get_sender_id_default():
    sid = ci._get_sender_id()
    assert "test.suite@" in sid


def test_get_sender_id_with_suffix():
    sid = ci._get_sender_id( suffix="a1b2c3d4" )
    assert sid.endswith( "#a1b2c3d4" )


# =========================================================================== #
# notify_progress  ( delegates to the shared dispatcher )
# =========================================================================== #
def test_notify_progress_delegates_and_sets_identity():
    with patch.object( ci._dispatcher, "notify_progress", new=AsyncMock() ) as m:
        _run( ci.notify_progress( "running suite", priority="low", abstract="ctx" ) )
    m.assert_awaited_once()
    # identity copied onto the dispatcher before dispatch
    assert ci._dispatcher.sender_id == ci.SENDER_ID


def test_notify_progress_session_name_override():
    with patch.object( ci._dispatcher, "notify_progress", new=AsyncMock() ) as m:
        _run( ci.notify_progress( "msg", session_name="my-session" ) )
    assert m.await_args[ 1 ][ "session_name" ] == "my-session"


def test_notify_progress_falls_back_to_module_session_name():
    with patch.object( ci, "SESSION_NAME", "module-session" ), \
         patch.object( ci._dispatcher, "notify_progress", new=AsyncMock() ) as m:
        _run( ci.notify_progress( "msg" ) )
    assert m.await_args[ 1 ][ "session_name" ] == "module-session"


# =========================================================================== #
# ask_yes_no  — TRIPWIRE for a confirmed prod bug
# =========================================================================== #
@pytest.mark.xfail(
    strict = True,
    reason = "PROD BUG: cosa_interface.ask_yes_no calls _dispatcher.ask_yes_no, which "
             "does not exist on AgentNotificationDispatcher (only ask_confirmation, with a "
             "different signature). Manager owns the fix + this xfail de-arm.",
)
def test_ask_yes_no_correct_contract_returns_yes_or_no():
    # CORRECT contract: returns a 'yes'/'no' string without raising.
    # Fails today (AttributeError) → recorded as xfail.
    result = _run( ci.ask_yes_no( "Proceed?", default="no" ) )
    assert result in ( "yes", "no" )


def test_ask_yes_no_pin_current_behavior_raises_attributeerror():
    # PIN of the CURRENT (buggy) behavior. Delete when the manager fixes ask_yes_no.
    with pytest.raises( AttributeError, match="ask_yes_no" ):
        _run( ci.ask_yes_no( "Proceed?" ) )
