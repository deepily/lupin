"""
Unit tests for cosa.agents.bug_fix_expediter.cosa_interface.

cosa_interface wraps a shared AgentNotificationDispatcher behind four async
voice primitives (notify_progress / ask_confirmation / get_feedback /
present_choices) plus a _get_sender_id helper. Each wrapper copies the module
globals SENDER_ID / SESSION_NAME / TARGET_USER onto the dispatcher, then awaits
the matching dispatcher coroutine and returns its result.

Tests mock the module-level _dispatcher at the boundary (AsyncMock coroutines)
— no real notification I/O, no network. quick_smoke_test + __main__ excluded
via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.bug_fix_expediter.cosa_interface as ci


def _run( coro ):
    return asyncio.run( coro )


def _fake_dispatcher():
    fake = MagicMock()
    fake.build_sender_id    = MagicMock( return_value="bug.fix.expediter@proj.deepily.ai#sfx" )
    fake.notify_progress    = AsyncMock( return_value=None )
    fake.ask_confirmation   = AsyncMock( return_value=True )
    fake.get_feedback       = AsyncMock( return_value="user said go" )
    fake.present_choices    = AsyncMock( return_value={ "answers": { "h": "a" } } )
    return fake


class TestGetSenderId( unittest.TestCase ):
    """_get_sender_id with and without an explicit suffix."""

    def test_with_suffix_passes_suffix_through( self ):
        fake = _fake_dispatcher()
        with patch.object( ci, "_dispatcher", fake ):
            result = ci._get_sender_id( suffix="dr-job::u1" )
        self.assertEqual( result, "bug.fix.expediter@proj.deepily.ai#sfx" )
        fake.build_sender_id.assert_called_once_with( suffix="dr-job::u1" )

    def test_without_suffix_uses_default( self ):
        fake = _fake_dispatcher()
        with patch.object( ci, "_dispatcher", fake ):
            result = ci._get_sender_id()
        self.assertEqual( result, "bug.fix.expediter@proj.deepily.ai#sfx" )
        fake.build_sender_id.assert_called_once_with()


class TestNotifyProgress( unittest.TestCase ):

    def test_forwards_all_kwargs_and_copies_identity( self ):
        fake = _fake_dispatcher()
        with patch.object( ci, "_dispatcher", fake ), \
             patch.object( ci, "SENDER_ID",   "SID" ), \
             patch.object( ci, "SESSION_NAME", "SESS" ), \
             patch.object( ci, "TARGET_USER",  "alice@x.com" ):
            out = _run( ci.notify_progress(
                "hello", priority="high", abstract="abs",
                session_name="ovr", job_id="dr-1", queue_name="q",
                progress_group_id="pg-1",
            ) )
        self.assertIsNone( out )                       # fire-and-forget
        self.assertEqual( fake.sender_id,    "SID" )
        self.assertEqual( fake.session_name, "SESS" )
        self.assertEqual( fake.target_user,  "alice@x.com" )
        fake.notify_progress.assert_awaited_once_with(
            "hello", priority="high", abstract="abs",
            session_name="ovr", job_id="dr-1",
            queue_name="q", progress_group_id="pg-1",
        )


class TestAskConfirmation( unittest.TestCase ):

    def test_returns_dispatcher_result_and_forwards( self ):
        fake = _fake_dispatcher()
        with patch.object( ci, "_dispatcher", fake ), \
             patch.object( ci, "SENDER_ID",  "SID" ), \
             patch.object( ci, "TARGET_USER", "bob@x.com" ):
            out = _run( ci.ask_confirmation(
                "ok?", default="yes", timeout=30, abstract="a", job_id="j", priority="urgent",
            ) )
        self.assertTrue( out )
        self.assertEqual( fake.sender_id,   "SID" )
        self.assertEqual( fake.target_user, "bob@x.com" )
        fake.ask_confirmation.assert_awaited_once_with(
            "ok?", default="yes", timeout=30, abstract="a", job_id="j", priority="urgent",
        )


class TestGetFeedback( unittest.TestCase ):

    def test_returns_transcribed_text_and_forwards( self ):
        fake = _fake_dispatcher()
        with patch.object( ci, "_dispatcher", fake ), \
             patch.object( ci, "SENDER_ID",  "SID" ), \
             patch.object( ci, "TARGET_USER", "carol@x.com" ):
            out = _run( ci.get_feedback(
                "speak", timeout=300, job_id="j", priority="medium", response_default="def",
            ) )
        self.assertEqual( out, "user said go" )
        self.assertEqual( fake.sender_id,   "SID" )
        self.assertEqual( fake.target_user, "carol@x.com" )
        fake.get_feedback.assert_awaited_once_with(
            "speak", timeout=300, job_id="j", priority="medium", response_default="def",
        )


class TestPresentChoices( unittest.TestCase ):

    def test_returns_answers_and_forwards( self ):
        fake = _fake_dispatcher()
        with patch.object( ci, "_dispatcher", fake ), \
             patch.object( ci, "SENDER_ID",  "SID" ), \
             patch.object( ci, "TARGET_USER", "dan@x.com" ):
            questions = [ { "header": "h", "options": [ "a", "b" ] } ]
            out = _run( ci.present_choices(
                questions, timeout=120, title="T", abstract="a",
                job_id="j", priority="high", response_default="{}",
            ) )
        self.assertEqual( out, { "answers": { "h": "a" } } )
        self.assertEqual( fake.sender_id,   "SID" )
        self.assertEqual( fake.target_user, "dan@x.com" )
        fake.present_choices.assert_awaited_once_with(
            questions, timeout=120, title="T", abstract="a",
            job_id="j", priority="high", response_default="{}",
        )


class TestModuleConstants( unittest.TestCase ):
    """The real module-level dispatcher is wired for the BFE agent type."""

    def test_agent_type_and_sender_prefix( self ):
        self.assertEqual( ci.AGENT_TYPE, "bug.fix.expediter" )
        self.assertEqual( ci._dispatcher.agent_type, "bug.fix.expediter" )
        self.assertIn( "bug.fix.expediter@", ci.SENDER_ID )


if __name__ == "__main__":
    unittest.main()
