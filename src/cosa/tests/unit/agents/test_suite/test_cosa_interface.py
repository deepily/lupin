"""
Unit tests for cosa/agents/test_suite/cosa_interface.py.

The notification dispatch is boundary-mocked at the shared `_dispatcher` instance,
so NO notification leaves the process. ZERO API spend.

FIXED (2026-06-03, Rick-authorized): `ask_yes_no` previously called a nonexistent
`_dispatcher.ask_yes_no` (AttributeError). It now delegates to the dispatcher's
real `ask_confirmation` (-> bool) and translates the result into the "yes"/"no"
string contract. The former xfail(strict=True) + AttributeError pin are removed;
the tests below assert the corrected behavior on both boolean arms.
"""
import asyncio
from unittest.mock import AsyncMock, patch

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
# ask_yes_no  — delegates to the dispatcher's ask_confirmation (bool -> str)
# =========================================================================== #
def test_ask_yes_no_returns_yes_when_confirmed():
    with patch.object( ci._dispatcher, "ask_confirmation", new=AsyncMock( return_value=True ) ) as m:
        result = _run( ci.ask_yes_no( "Proceed?", default="no" ) )
    m.assert_awaited_once()
    assert result == "yes"


def test_ask_yes_no_returns_no_when_declined():
    with patch.object( ci._dispatcher, "ask_confirmation", new=AsyncMock( return_value=False ) ):
        result = _run( ci.ask_yes_no( "Proceed?", default="no" ) )
    assert result == "no"


def test_ask_yes_no_sets_identity_and_forwards_args():
    with patch.object( ci._dispatcher, "ask_confirmation", new=AsyncMock( return_value=True ) ) as m:
        _run( ci.ask_yes_no(
            "Q", default="yes", abstract="ctx", session_name="my-session", job_id="job-1"
        ) )
    # identity copied onto the dispatcher before dispatch (mirrors notify_progress)
    assert ci._dispatcher.sender_id    == ci.SENDER_ID
    assert ci._dispatcher.session_name == "my-session"
    # supported args forwarded to ask_confirmation
    kwargs = m.await_args[ 1 ]
    assert kwargs[ "question" ] == "Q"
    assert kwargs[ "default" ]  == "yes"
    assert kwargs[ "abstract" ] == "ctx"
    assert kwargs[ "job_id" ]   == "job-1"


def test_ask_yes_no_falls_back_to_module_session_name():
    with patch.object( ci, "SESSION_NAME", "module-session" ), \
         patch.object( ci._dispatcher, "ask_confirmation", new=AsyncMock( return_value=False ) ):
        _run( ci.ask_yes_no( "Q" ) )
    assert ci._dispatcher.session_name == "module-session"
