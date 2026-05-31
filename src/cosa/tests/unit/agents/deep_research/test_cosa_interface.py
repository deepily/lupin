"""
Unit tests for cosa.agents.deep_research.cosa_interface.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, deep_research SDK/network
tier). This module is the async voice-interface wrapper: it owns sender-id resolution,
per-task ContextVar dispatch isolation, and four thin async wrappers that copy the
module-global identity onto the shared AgentNotificationDispatcher then await it.

Boundary-mocked: the shared `_dispatcher` is replaced with a MagicMock whose async
methods are AsyncMock, so ZERO real notifications / network / voice I/O fire. The
ContextVar tests use a known-baseline-then-reset pattern so they are independent of
the vars' module defaults and leave no cross-test residue.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import cosa.agents.deep_research.cosa_interface as ci
from cosa.agents.utils.agent_notification_dispatcher import (
    ctx_sender_id, ctx_target_user, ctx_session_name,
)


class TestGetSenderId( unittest.TestCase ):
    """`_get_sender_id` has two arms keyed on the `suffix` parameter."""

    def test_no_suffix_calls_build_with_no_args( self ):
        mock_disp = MagicMock()
        mock_disp.build_sender_id.return_value = "deep.research@x#base"
        with patch.object( ci, "_dispatcher", mock_disp ):
            result = ci._get_sender_id()
        self.assertEqual( result, "deep.research@x#base" )
        mock_disp.build_sender_id.assert_called_once_with()

    def test_with_suffix_forwards_suffix_kwarg( self ):
        mock_disp = MagicMock()
        mock_disp.build_sender_id.return_value = "deep.research@x#abc123"
        with patch.object( ci, "_dispatcher", mock_disp ):
            result = ci._get_sender_id( suffix="abc123" )
        self.assertEqual( result, "deep.research@x#abc123" )
        mock_disp.build_sender_id.assert_called_once_with( suffix="abc123" )


class TestSetDispatchContext( unittest.TestCase ):
    """Each of the three values has an independent `if x is not None` arm."""

    def test_all_three_set_returns_three_tokens( self ):
        tokens = ci.set_dispatch_context(
            sender_id="sid", target_user="user@x", session_name="My Session",
        )
        try:
            self.assertEqual( set( tokens.keys() ), { "sender_id", "target_user", "session_name" } )
            self.assertEqual( ctx_sender_id.get(), "sid" )
            self.assertEqual( ctx_target_user.get(), "user@x" )
            self.assertEqual( ctx_session_name.get(), "My Session" )
        finally:
            ci.reset_dispatch_context( tokens )

    def test_partial_set_only_provided_var( self ):
        tokens = ci.set_dispatch_context( target_user="only-user@x" )
        try:
            self.assertEqual( set( tokens.keys() ), { "target_user" } )
            self.assertEqual( ctx_target_user.get(), "only-user@x" )
        finally:
            ci.reset_dispatch_context( tokens )

    def test_none_provided_returns_empty_tokens( self ):
        tokens = ci.set_dispatch_context()
        self.assertEqual( tokens, { } )


class TestResetDispatchContext( unittest.TestCase ):
    """Reset restores each ContextVar to its prior value; missing keys are skipped."""

    def test_reset_restores_baseline( self ):
        t0_sid  = ctx_sender_id.set( "baseline-sid" )
        t0_user = ctx_target_user.set( "baseline-user" )
        t0_name = ctx_session_name.set( "baseline-name" )
        try:
            tokens = ci.set_dispatch_context(
                sender_id="new-sid", target_user="new-user", session_name="new-name",
            )
            self.assertEqual( ctx_sender_id.get(), "new-sid" )
            ci.reset_dispatch_context( tokens )
            self.assertEqual( ctx_sender_id.get(), "baseline-sid" )
            self.assertEqual( ctx_target_user.get(), "baseline-user" )
            self.assertEqual( ctx_session_name.get(), "baseline-name" )
        finally:
            ctx_sender_id.reset( t0_sid )
            ctx_target_user.reset( t0_user )
            ctx_session_name.reset( t0_name )

    def test_reset_with_missing_keys_is_noop( self ):
        # An empty tokens dict skips every branch and must not raise.
        ci.reset_dispatch_context( { } )

    def test_reset_with_subset_of_keys( self ):
        t0_sid = ctx_sender_id.set( "before" )
        try:
            tokens = ci.set_dispatch_context( sender_id="after" )
            # tokens has only "sender_id"; reset must touch only that var.
            ci.reset_dispatch_context( tokens )
            self.assertEqual( ctx_sender_id.get(), "before" )
        finally:
            ctx_sender_id.reset( t0_sid )


class TestAsyncWrappers( unittest.IsolatedAsyncioTestCase ):
    """The four async wrappers stamp module-global identity onto the dispatcher,
    then await the matching dispatcher coroutine and return its result."""

    def setUp( self ):
        self.mock_disp = MagicMock()
        self.mock_disp.notify_progress  = AsyncMock( return_value=None )
        self.mock_disp.ask_confirmation = AsyncMock( return_value=True )
        self.mock_disp.get_feedback     = AsyncMock( return_value="user said this" )
        self.mock_disp.present_choices  = AsyncMock( return_value={ "answers": { "h": "A" } } )

    async def test_notify_progress_stamps_identity_and_forwards( self ):
        with patch.object( ci, "_dispatcher", self.mock_disp ), \
             patch.object( ci, "SENDER_ID", "the-sender" ), \
             patch.object( ci, "SESSION_NAME", "the-session" ), \
             patch.object( ci, "TARGET_USER", "the-user@x" ):
            await ci.notify_progress(
                "hello", priority="high", abstract="abs",
                session_name="ses", job_id="dr-1", queue_name="q",
                progress_group_id="pg-deadbeef",
            )
        # All three identity globals copied onto the shared dispatcher.
        self.assertEqual( self.mock_disp.sender_id, "the-sender" )
        self.assertEqual( self.mock_disp.session_name, "the-session" )
        self.assertEqual( self.mock_disp.target_user, "the-user@x" )
        self.mock_disp.notify_progress.assert_awaited_once_with(
            "hello", priority="high", abstract="abs",
            session_name="ses", job_id="dr-1",
            queue_name="q", progress_group_id="pg-deadbeef",
        )

    async def test_ask_confirmation_returns_dispatcher_result( self ):
        with patch.object( ci, "_dispatcher", self.mock_disp ), \
             patch.object( ci, "SENDER_ID", "the-sender" ), \
             patch.object( ci, "TARGET_USER", "the-user@x" ):
            result = await ci.ask_confirmation(
                "ok?", default="yes", timeout=42, abstract="abs", job_id="dr-2",
            )
        self.assertIs( result, True )
        self.assertEqual( self.mock_disp.sender_id, "the-sender" )
        self.assertEqual( self.mock_disp.target_user, "the-user@x" )
        self.mock_disp.ask_confirmation.assert_awaited_once_with(
            "ok?", default="yes", timeout=42, abstract="abs", job_id="dr-2",
        )

    async def test_get_feedback_returns_dispatcher_result( self ):
        with patch.object( ci, "_dispatcher", self.mock_disp ), \
             patch.object( ci, "SENDER_ID", "the-sender" ), \
             patch.object( ci, "TARGET_USER", "the-user@x" ):
            result = await ci.get_feedback( "speak", timeout=99, job_id="dr-3" )
        self.assertEqual( result, "user said this" )
        self.mock_disp.get_feedback.assert_awaited_once_with(
            "speak", timeout=99, job_id="dr-3",
        )

    async def test_present_choices_returns_dispatcher_result( self ):
        questions = [ { "question": "pick", "options": [ { "label": "A" } ] } ]
        with patch.object( ci, "_dispatcher", self.mock_disp ), \
             patch.object( ci, "SENDER_ID", "the-sender" ), \
             patch.object( ci, "TARGET_USER", "the-user@x" ):
            result = await ci.present_choices(
                questions, timeout=15, title="T", abstract="abs", job_id="dr-4",
            )
        self.assertEqual( result, { "answers": { "h": "A" } } )
        self.mock_disp.present_choices.assert_awaited_once_with(
            questions, timeout=15, title="T", abstract="abs", job_id="dr-4",
        )


if __name__ == "__main__":
    unittest.main()
