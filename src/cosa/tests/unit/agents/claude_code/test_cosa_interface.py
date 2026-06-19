"""
Unit tests for cosa.agents.claude_code.cosa_interface.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, claude_code lane). Async
voice-interface wrappers for ClaudeCodeJob: _get_sender_id + two thin async wrappers
(notify_progress, ask_confirmation) that stamp module-global identity onto the shared
AgentNotificationDispatcher then await it. The dispatcher is replaced with a MagicMock
whose async methods are AsyncMock → ZERO real notifications / network / voice. Same
shape as the deep_research cosa_interface tier.

Must run via run-sdk-cov.sh (claude_code package import pulls job.py → SDK chain).
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import cosa.agents.claude_code.cosa_interface as ci


class TestGetSenderId( unittest.TestCase ):

    def test_delegates_to_dispatcher_build( self ):
        mock_disp = MagicMock()
        mock_disp.build_sender_id.return_value = "claude.code.job@x#s"
        with patch.object( ci, "_dispatcher", mock_disp ):
            result = ci._get_sender_id()
        self.assertEqual( result, "claude.code.job@x#s" )
        mock_disp.build_sender_id.assert_called_once_with()


class TestAsyncWrappers( unittest.IsolatedAsyncioTestCase ):

    def setUp( self ):
        self.mock_disp = MagicMock()
        self.mock_disp.notify_progress  = AsyncMock( return_value=None )
        self.mock_disp.ask_confirmation = AsyncMock( return_value=True )

    async def test_notify_progress_stamps_identity_and_forwards( self ):
        with patch.object( ci, "_dispatcher", self.mock_disp ), \
             patch.object( ci, "SENDER_ID", "the-sender" ), \
             patch.object( ci, "TARGET_USER", "u@x.com" ):
            await ci.notify_progress(
                "hi", priority="high", abstract="abs",
                session_name="ses", job_id="cc-1", queue_name="run",
            )
        self.assertEqual( self.mock_disp.sender_id, "the-sender" )
        self.assertEqual( self.mock_disp.target_user, "u@x.com" )
        self.mock_disp.notify_progress.assert_awaited_once_with(
            "hi", priority="high", abstract="abs",
            session_name="ses", job_id="cc-1", queue_name="run",
        )

    async def test_ask_confirmation_returns_dispatcher_result( self ):
        with patch.object( ci, "_dispatcher", self.mock_disp ), \
             patch.object( ci, "SENDER_ID", "the-sender" ), \
             patch.object( ci, "TARGET_USER", "u@x.com" ):
            result = await ci.ask_confirmation(
                "ok?", default="yes", timeout=42, abstract="abs", job_id="cc-2",
            )
        self.assertIs( result, True )
        self.assertEqual( self.mock_disp.sender_id, "the-sender" )
        self.assertEqual( self.mock_disp.target_user, "u@x.com" )
        self.mock_disp.ask_confirmation.assert_awaited_once_with(
            "ok?", default="yes", timeout=42, abstract="abs", job_id="cc-2",
        )


if __name__ == "__main__":
    unittest.main()
