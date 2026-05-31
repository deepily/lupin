#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.cosa_interface

Thin async wrappers over a shared AgentNotificationDispatcher. The dispatcher
is replaced with a mock so no real notification dispatch occurs.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.presentation_generator import cosa_interface as ci


def _run( coro ):
    return asyncio.run( coro )


def _mock_dispatcher():
    d = MagicMock()
    d.build_sender_id = MagicMock( side_effect=lambda suffix=None: f"presentation.gen@x#{suffix or 'cli'}" )
    d.notify_progress  = AsyncMock( return_value=None )
    d.ask_confirmation = AsyncMock( return_value=True )
    d.get_feedback     = AsyncMock( return_value="feedback" )
    d.present_choices  = AsyncMock( return_value={ "answers": { "H": "A" } } )
    return d


class TestGetSenderId:
    def test_with_suffix( self ):
        d = _mock_dispatcher()
        with patch.object( ci, "_dispatcher", d ):
            assert ci._get_sender_id( "abc" ) == "presentation.gen@x#abc"
            d.build_sender_id.assert_called_with( suffix="abc" )

    def test_without_suffix( self ):
        d = _mock_dispatcher()
        with patch.object( ci, "_dispatcher", d ):
            assert ci._get_sender_id() == "presentation.gen@x#cli"


class TestWrappers:
    def test_notify_progress( self ):
        d = _mock_dispatcher()
        with patch.object( ci, "_dispatcher", d ):
            _run( ci.notify_progress( "msg", priority="high", abstract="a", job_id="j" ) )
        d.notify_progress.assert_awaited_once()
        assert d.sender_id == ci.SENDER_ID

    def test_ask_confirmation( self ):
        d = _mock_dispatcher()
        with patch.object( ci, "_dispatcher", d ):
            out = _run( ci.ask_confirmation( "ok?", default="yes", timeout=30 ) )
        assert out is True
        d.ask_confirmation.assert_awaited_once()

    def test_get_feedback( self ):
        d = _mock_dispatcher()
        with patch.object( ci, "_dispatcher", d ):
            out = _run( ci.get_feedback( "tell me", timeout=10 ) )
        assert out == "feedback"
        d.get_feedback.assert_awaited_once()

    def test_present_choices( self ):
        d = _mock_dispatcher()
        with patch.object( ci, "_dispatcher", d ):
            out = _run( ci.present_choices( [ { "q": "x" } ], timeout=20, title="T" ) )
        assert out == { "answers": { "H": "A" } }
        d.present_choices.assert_awaited_once()


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
