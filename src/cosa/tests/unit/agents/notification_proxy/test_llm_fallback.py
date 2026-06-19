#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.strategies.llm_fallback.

LLMFallbackStrategy talks to the Anthropic SDK. Here get_anthropic_api_key
is ALWAYS patched (the firewalled key is NEVER read) and AsyncAnthropic is
mocked → zero network, zero API spend. Async respond() is driven with
asyncio.run (no pytest-asyncio dependency).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.notification_proxy.strategies.llm_fallback as fb
from cosa.agents.notification_proxy.strategies.llm_fallback import LLMFallbackStrategy


def _strategy_with_key( anthropic_raises=False, debug=False ):
    """Build a strategy with a fake API key + mocked AsyncAnthropic client."""
    fake_client = MagicMock()
    anthropic_mod = MagicMock()
    if anthropic_raises:
        anthropic_mod.AsyncAnthropic.side_effect = RuntimeError( "sdk boom" )
    else:
        anthropic_mod.AsyncAnthropic.return_value = fake_client

    with patch.object( fb, "get_anthropic_api_key", return_value="test-key" ), \
         patch.dict( "sys.modules", { "anthropic": anthropic_mod } ):
        s = LLMFallbackStrategy( debug=debug )
    return s, fake_client


def _strategy_no_key( debug=False ):
    with patch.object( fb, "get_anthropic_api_key", return_value=None ):
        return LLMFallbackStrategy( debug=debug )


def _make_fake_response( answer_text="the answer" ):
    """
    Build a fake Anthropic messages.create response.

    Ensures:
        - .content has one block WITH .text (covers the hasattr-True arm) and
          one block WITHOUT .text (covers the hasattr-False arm)
        - .usage exposes input_tokens / output_tokens for the debug print
    """
    block_with_text      = MagicMock()
    block_with_text.text = answer_text
    block_no_text        = MagicMock( spec=[] )   # no .text attribute
    resp                 = MagicMock()
    resp.content         = [ block_with_text, block_no_text ]
    resp.usage           = MagicMock( input_tokens=10, output_tokens=5 )
    return resp


class TestInit:

    def test_available_with_key( self ):
        s, _ = _strategy_with_key( debug=True )
        assert s.available is True

    def test_unavailable_without_key( self ):
        s = _strategy_no_key( debug=True )
        assert s.available is False

    def test_sdk_init_failure_sets_unavailable( self ):
        s, _ = _strategy_with_key( anthropic_raises=True, debug=True )
        assert s.available is False


class TestCanHandle:

    def test_handles_when_available_and_requested( self ):
        s, _ = _strategy_with_key()
        assert s.can_handle( { "response_requested": True } )

    def test_rejects_when_not_requested( self ):
        s, _ = _strategy_with_key()
        assert not s.can_handle( { "response_requested": False } )

    def test_rejects_when_unavailable( self ):
        s = _strategy_no_key()
        assert not s.can_handle( { "response_requested": True } )


class TestBuildPrompt:

    def test_all_sections_present_open_ended( self ):
        s = _strategy_no_key()
        p = s._build_prompt( "what topic?", "Agent: Deep Research", "open_ended", "Missing: query" )
        assert "automated test agent" in p
        assert "Title: Missing: query" in p
        assert "what topic?" in p
        assert "Deep Research" in p
        assert "brief, direct answer" in p

    def test_yes_no_format_hint( self ):
        s = _strategy_no_key()
        assert "'yes' or 'no'" in s._build_prompt( "ok?", "", "yes_no", "" )

    def test_multiple_choice_format_hint( self ):
        s = _strategy_no_key()
        assert "option labels" in s._build_prompt( "pick", "", "multiple_choice", "" )

    def test_no_title_no_abstract_other_type( self ):
        """Empty title + empty abstract + unknown response_type → no optional sections."""
        s = _strategy_no_key()
        p = s._build_prompt( "q", "", "other", "" )
        assert "Title:" not in p
        assert "Context:" not in p


class TestRespond:

    def test_respond_returns_answer( self ):
        s, client = _strategy_with_key( debug=True )
        client.messages.create = AsyncMock( return_value=_make_fake_response( "academic" ) )
        out = asyncio.run( s.respond( { "message": "audience?", "response_type": "open_ended" } ) )
        assert out == "academic"

    def test_respond_empty_answer_returns_none( self ):
        s, client = _strategy_with_key()
        client.messages.create = AsyncMock( return_value=_make_fake_response( "   " ) )
        out = asyncio.run( s.respond( { "message": "q" } ) )
        assert out is None

    def test_respond_unavailable_returns_none( self ):
        s = _strategy_no_key()
        out = asyncio.run( s.respond( { "message": "q" } ) )
        assert out is None

    def test_respond_api_error_returns_none( self ):
        s, client = _strategy_with_key( debug=True )
        client.messages.create = AsyncMock( side_effect=RuntimeError( "api down" ) )
        out = asyncio.run( s.respond( { "message": "q", "title": "T", "abstract": "A" } ) )
        assert out is None
