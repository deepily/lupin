#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.api_client

PresentationAPIClient (Anthropic SDK wrapper). Boundaries mocked: AsyncAnthropic
(no real client), self._client.messages.create (AsyncMock), asyncio.sleep,
cu.get_api_key. No real Claude calls / network / retries-with-delay.
"""

import os
import types as pytypes
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import anthropic
import pytest

from cosa.agents.presentation_generator import api_client as acmod
from cosa.agents.presentation_generator.api_client import (
    PresentationAPIClient,
    APIResponse,
    CostEstimate,
    ENV_VAR_NAME,
)


def _run( coro ):
    return asyncio.run( coro )


def _client( api_key="K", debug=False ):
    with patch.object( acmod, "AsyncAnthropic" ):
        return PresentationAPIClient( api_key=api_key, debug=debug )


def _usage( inp=100, out=50 ):
    u = MagicMock()
    u.input_tokens = inp
    u.output_tokens = out
    return u


# ===========================================================================
# CostEstimate
# ===========================================================================
class TestCostEstimate:
    def test_opus_pricing( self ):
        c = CostEstimate()
        c.add_usage( "claude-opus-4-6", 1_000_000, 1_000_000 )
        assert c.total_api_calls == 1
        assert c.estimated_cost_usd == pytest.approx( 15.0 + 75.0 )

    def test_haiku_pricing( self ):
        c = CostEstimate()
        c.add_usage( "claude-haiku-4-5", 1_000_000, 0 )
        assert c.estimated_cost_usd == pytest.approx( 0.80 )

    def test_sonnet_default_pricing( self ):
        c = CostEstimate()
        c.add_usage( "claude-sonnet-4-6", 1_000_000, 0 )
        assert c.estimated_cost_usd == pytest.approx( 3.0 )

    def test_summary( self ):
        c = CostEstimate()
        c.add_usage( "claude-opus-4-6", 100, 50 )
        s = c.get_summary()
        assert "API Calls: 1" in s


# ===========================================================================
# APIResponse
# ===========================================================================
class TestAPIResponse:
    def test_dataclass( self ):
        r = APIResponse( content="c", model="m", input_tokens=1, output_tokens=2, stop_reason="end_turn" )
        assert r.content == "c"
        assert r.raw_response is None


# ===========================================================================
# __init__ / key resolution
# ===========================================================================
class TestInit:
    def test_anthropic_unavailable_raises( self ):
        with patch.object( acmod, "ANTHROPIC_AVAILABLE", False ):
            with pytest.raises( ImportError, match="anthropic SDK not installed" ):
                PresentationAPIClient( api_key="K" )

    def test_param_key_debug( self, capsys ):
        with patch.object( acmod, "AsyncAnthropic" ):
            c = PresentationAPIClient( api_key="PARAM", debug=True )
        assert c.key_source == "parameter"
        assert "API key source: parameter" in capsys.readouterr().out

    def test_env_key( self ):
        with patch.object( acmod, "AsyncAnthropic" ), \
             patch.dict( os.environ, { ENV_VAR_NAME: "ENVKEY" } ):
            c = PresentationAPIClient()
        assert c.key_source == "environment"
        assert c.api_key == "ENVKEY"

    def test_file_key( self ):
        with patch.object( acmod, "AsyncAnthropic" ), \
             patch.dict( os.environ, {}, clear=False ), \
             patch( "cosa.utils.util.get_api_key", return_value="FILEKEY" ):
            os.environ.pop( ENV_VAR_NAME, None )
            c = PresentationAPIClient()
        assert c.key_source == "local file"
        assert c.api_key == "FILEKEY"

    def test_no_key_raises( self ):
        with patch.object( acmod, "AsyncAnthropic" ), \
             patch( "cosa.utils.util.get_api_key", return_value=None ):
            os.environ.pop( ENV_VAR_NAME, None )
            with pytest.raises( ValueError, match="Anthropic API key not found" ):
                PresentationAPIClient()

    def test_file_key_load_exception_debug( self, capsys ):
        with patch.object( acmod, "AsyncAnthropic" ), \
             patch( "cosa.utils.util.get_api_key", side_effect=RuntimeError( "no file" ) ):
            os.environ.pop( ENV_VAR_NAME, None )
            with pytest.raises( ValueError ):
                PresentationAPIClient( debug=True )
        assert "Could not load local key file" in capsys.readouterr().out

    def test_file_key_load_exception_no_debug_silent( self, capsys ):
        with patch.object( acmod, "AsyncAnthropic" ), \
             patch( "cosa.utils.util.get_api_key", side_effect=RuntimeError( "no file" ) ):
            os.environ.pop( ENV_VAR_NAME, None )
            with pytest.raises( ValueError ):
                PresentationAPIClient( debug=False )
        assert "Could not load local key file" not in capsys.readouterr().out


# ===========================================================================
# public call_for_* delegate to _call_api
# ===========================================================================
class TestPublicCalls:
    @pytest.mark.parametrize( "method,call_type", [
        ( "call_for_analysis", "narrative_analysis" ),
        ( "call_for_outline", "outline_generation" ),
        ( "call_for_elaboration", "elaboration" ),
        ( "call_for_mermaid", "mermaid" ),
        ( "call_for_matplotlib", "matplotlib" ),
        ( "call_for_d2", "d2" ),
    ] )
    def test_delegates_with_call_type( self, method, call_type ):
        c = _client()
        with patch.object( c, "_call_api", new=AsyncMock( return_value="RESP" ) ) as m:
            out = _run( getattr( c, method )( "sys", "user" ) )
        assert out == "RESP"
        assert m.await_args.kwargs[ "call_type" ] == call_type


# ===========================================================================
# call_with_json_output
# ===========================================================================
class TestJsonOutput:
    def test_parse_json_fence( self ):
        c = _client()
        resp = APIResponse( content='```json\n{"a": 1}\n```', model="m", input_tokens=1, output_tokens=1, stop_reason="end" )
        with patch.object( c, "_call_api", new=AsyncMock( return_value=resp ) ):
            out = _run( c.call_with_json_output( "sys", "user" ) )
        assert out == { "a": 1 }

    def test_parse_bare_fence( self ):
        c = _client()
        resp = APIResponse( content='```\n{"b": 2}\n```', model="m", input_tokens=1, output_tokens=1, stop_reason="end" )
        with patch.object( c, "_call_api", new=AsyncMock( return_value=resp ) ):
            assert _run( c.call_with_json_output( "sys", "user" ) ) == { "b": 2 }

    def test_invalid_json_raises( self ):
        c = _client()
        resp = APIResponse( content="not json {", model="m", input_tokens=1, output_tokens=1, stop_reason="end" )
        with patch.object( c, "_call_api", new=AsyncMock( return_value=resp ) ):
            with pytest.raises( ValueError, match="not valid JSON" ):
                _run( c.call_with_json_output( "sys", "user" ) )


# ===========================================================================
# _call_api
# ===========================================================================
class TestCallApi:
    def _response( self ):
        text_block    = pytypes.SimpleNamespace( text="Hello " )
        notext_block  = object()   # no .text attr → hasattr False
        text_block2   = pytypes.SimpleNamespace( text="World" )
        resp = MagicMock()
        resp.content = [ text_block, notext_block, text_block2 ]
        resp.usage = _usage( 200, 80 )
        resp.stop_reason = "end_turn"
        return resp

    def test_assembles_content_and_tracks_cost_debug( self, capsys ):
        c = _client( debug=True )
        with patch.object( c, "_call_with_retry", new=AsyncMock( return_value=self._response() ) ):
            out = _run( c._call_api( model="claude-opus-4-6", system_prompt="sys",
                                     user_message="u", call_type="t" ) )
        assert out.content == "Hello World"   # non-text block skipped
        assert out.input_tokens == 200
        assert c.cost_estimate.total_api_calls == 1
        printed = capsys.readouterr().out
        assert "Calling claude-opus-4-6 for t" in printed
        assert "Response: 200 in, 80 out" in printed

    def test_no_system_prompt_omits_system( self ):
        c = _client()
        captured = {}
        async def fake_retry( kwargs ):
            captured.update( kwargs )
            return self._response()
        with patch.object( c, "_call_with_retry", new=fake_retry ):
            _run( c._call_api( model="m", system_prompt="", user_message="u" ) )
        assert "system" not in captured


# ===========================================================================
# _call_with_retry
# ===========================================================================
class TestRetry:
    def _rate_error( self ):
        return anthropic.RateLimitError.__new__( anthropic.RateLimitError )

    def _status_error( self, code ):
        e = anthropic.APIStatusError.__new__( anthropic.APIStatusError )
        e.status_code = code
        return e

    def test_success_first_try( self ):
        c = _client()
        c._client.messages.create = AsyncMock( return_value="OK" )
        assert _run( c._call_with_retry( { "x": 1 } ) ) == "OK"

    def test_rate_limit_then_success( self ):
        c = _client()
        c._client.messages.create = AsyncMock( side_effect=[ self._rate_error(), "OK" ] )
        with patch.object( acmod.asyncio, "sleep", new=AsyncMock() ):
            assert _run( c._call_with_retry( { "x": 1 } ) ) == "OK"

    def test_server_error_then_success( self ):
        c = _client()
        c._client.messages.create = AsyncMock( side_effect=[ self._status_error( 503 ), "OK" ] )
        with patch.object( acmod.asyncio, "sleep", new=AsyncMock() ):
            assert _run( c._call_with_retry( { "x": 1 } ) ) == "OK"

    def test_client_error_4xx_raises_immediately( self ):
        c = _client()
        err = self._status_error( 400 )
        c._client.messages.create = AsyncMock( side_effect=err )
        with pytest.raises( anthropic.APIStatusError ):
            _run( c._call_with_retry( { "x": 1 } ) )

    def test_rate_limit_exhausts_raises( self ):
        c = _client()
        c._client.messages.create = AsyncMock( side_effect=self._rate_error() )
        with patch.object( acmod.asyncio, "sleep", new=AsyncMock() ):
            with pytest.raises( anthropic.RateLimitError ):
                _run( c._call_with_retry( { "x": 1 }, max_retries=2 ) )

    def test_server_error_exhausts_raises( self ):
        c = _client()
        c._client.messages.create = AsyncMock( side_effect=self._status_error( 503 ) )
        with patch.object( acmod.asyncio, "sleep", new=AsyncMock() ):
            with pytest.raises( anthropic.APIStatusError ):
                _run( c._call_with_retry( { "x": 1 }, max_retries=2 ) )

    def test_generic_error_then_success( self ):
        c = _client()
        c._client.messages.create = AsyncMock( side_effect=[ ValueError( "x" ), "OK" ] )
        with patch.object( acmod.asyncio, "sleep", new=AsyncMock() ):
            assert _run( c._call_with_retry( { "x": 1 } ) ) == "OK"

    def test_exhausts_retries_raises_last( self ):
        c = _client()
        c._client.messages.create = AsyncMock( side_effect=ValueError( "always" ) )
        with patch.object( acmod.asyncio, "sleep", new=AsyncMock() ):
            with pytest.raises( ValueError, match="always" ):
                _run( c._call_with_retry( { "x": 1 }, max_retries=2 ) )


# ===========================================================================
# utility
# ===========================================================================
class TestUtility:
    def test_get_cost_summary( self ):
        c = _client()
        assert "API Calls:" in c.get_cost_summary()

    def test_close_calls_client_close( self ):
        c = _client()
        c._client.close = AsyncMock()
        _run( c.close() )
        c._client.close.assert_awaited_once()

    def test_close_no_close_method( self ):
        c = _client()
        # _client is a MagicMock → hasattr close True; force a plain object w/o close
        c._client = object()
        _run( c.close() )   # should not raise


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
