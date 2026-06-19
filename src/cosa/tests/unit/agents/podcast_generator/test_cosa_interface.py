#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.cosa_interface

Target: the async notification wrappers that bind module-level identity
(SENDER_ID / SESSION_NAME / TARGET_USER) onto a shared
AgentNotificationDispatcher and delegate. The dispatcher is mocked so NO real
notification dispatch / network occurs.

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

import cosa.agents.podcast_generator.cosa_interface as ci


def _run( coro ):
    return asyncio.run( coro )


class TestAgentTypeConstant:
    """AGENT_TYPE pins the podcast.gen identity used to build sender ids."""

    def test_agent_type( self ):
        assert ci.AGENT_TYPE == "podcast.gen"
        assert ci._dispatcher.agent_type == "podcast.gen"


class TestGetSenderId:
    """
    _get_sender_id resolves through the dispatcher, with an optional suffix.

    Ensures:
        - no suffix -> dispatcher.build_sender_id() (default suffix)
        - suffix given -> dispatcher.build_sender_id(suffix=...)
    """

    def test_default_suffix_path( self ):
        with patch.object( ci._dispatcher, "build_sender_id", return_value="sid-default" ) as b:
            assert ci._get_sender_id() == "sid-default"
        b.assert_called_once_with()

    def test_explicit_suffix_path( self ):
        with patch.object( ci._dispatcher, "build_sender_id", return_value="sid-suffixed" ) as b:
            assert ci._get_sender_id( suffix="pg-abc123" ) == "sid-suffixed"
        b.assert_called_once_with( suffix="pg-abc123" )


class TestNotifyProgress:
    """
    notify_progress binds identity onto the dispatcher then delegates.

    Ensures sender_id/session_name/target_user are applied from module globals
    and all keyword args pass through verbatim.
    """

    def test_binds_identity_and_delegates( self ):
        disp = MagicMock()
        disp.notify_progress = AsyncMock()
        with patch.object( ci, "_dispatcher", disp ), \
             patch.object( ci, "SENDER_ID", "S" ), \
             patch.object( ci, "SESSION_NAME", "sess" ), \
             patch.object( ci, "TARGET_USER", "u@test.com" ):
            _run( ci.notify_progress(
                "hello", priority="high", abstract="A",
                session_name="override", job_id="pg-1",
                queue_name="run", progress_group_id="pg-xyz",
            ) )
        assert disp.sender_id    == "S"
        assert disp.session_name == "sess"
        assert disp.target_user  == "u@test.com"
        disp.notify_progress.assert_awaited_once_with(
            "hello", priority="high", abstract="A",
            session_name="override", job_id="pg-1",
            queue_name="run", progress_group_id="pg-xyz",
        )


class TestAskConfirmation:
    """ask_confirmation binds sender/target then delegates, returning the bool."""

    def test_delegates_and_returns_bool( self ):
        disp = MagicMock()
        disp.ask_confirmation = AsyncMock( return_value=True )
        with patch.object( ci, "_dispatcher", disp ), \
             patch.object( ci, "SENDER_ID", "S" ), \
             patch.object( ci, "TARGET_USER", "u@test.com" ):
            out = _run( ci.ask_confirmation( "ok?", default="yes", timeout=12, abstract="A", job_id="pg-1" ) )
        assert out is True
        assert disp.sender_id   == "S"
        assert disp.target_user == "u@test.com"
        disp.ask_confirmation.assert_awaited_once_with(
            "ok?", default="yes", timeout=12, abstract="A", job_id="pg-1"
        )


class TestGetFeedback:
    """get_feedback binds sender/target then delegates, returning the response."""

    def test_delegates_and_returns_response( self ):
        disp = MagicMock()
        disp.get_feedback = AsyncMock( return_value="user said this" )
        with patch.object( ci, "_dispatcher", disp ), \
             patch.object( ci, "SENDER_ID", "S" ), \
             patch.object( ci, "TARGET_USER", "u@test.com" ):
            out = _run( ci.get_feedback( "tell me", timeout=99, job_id="pg-1" ) )
        assert out == "user said this"
        disp.get_feedback.assert_awaited_once_with( "tell me", timeout=99, job_id="pg-1" )


class TestPresentChoices:
    """present_choices binds sender/target then delegates, returning selections."""

    def test_delegates_and_returns_dict( self ):
        disp = MagicMock()
        disp.present_choices = AsyncMock( return_value={ "answers": { "h": "A" } } )
        questions = [ { "question": "Which?", "options": [ { "label": "A" } ] } ]
        with patch.object( ci, "_dispatcher", disp ), \
             patch.object( ci, "SENDER_ID", "S" ), \
             patch.object( ci, "TARGET_USER", "u@test.com" ):
            out = _run( ci.present_choices( questions, timeout=30, title="T", abstract="A", job_id="pg-1" ) )
        assert out == { "answers": { "h": "A" } }
        disp.present_choices.assert_awaited_once_with(
            questions, timeout=30, title="T", abstract="A", job_id="pg-1"
        )
