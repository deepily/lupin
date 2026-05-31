#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.api_client

Targets: APIResponse + CostEstimate dataclasses and PodcastAPIClient. The
Anthropic SDK is mocked at the boundary — AsyncAnthropic is patched so no real
client is built, the module-level `anthropic` exception namespace is swapped
for fakes so the retry ladder is exercised, and messages.create is an AsyncMock.
NO real API key, network call, or spend occurs.

quick_smoke_test() and __main__ are coverage-excluded.
"""

import json
import types
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

import cosa.agents.podcast_generator.api_client as ac
from cosa.agents.podcast_generator.api_client import (
    APIResponse,
    CostEstimate,
    PodcastAPIClient,
    ENV_VAR_NAME,
    KEY_FILE_NAME,
)


def _run( coro ):
    return asyncio.run( coro )


# ----------------------------------------------------------------------------
# Fakes for the anthropic exception namespace
# ----------------------------------------------------------------------------
class _FakeRateLimit( Exception ):
    pass


class _FakeAPIStatus( Exception ):
    def __init__( self, message, status_code ):
        super().__init__( message )
        self.status_code = status_code


def _fake_anthropic():
    return types.SimpleNamespace( RateLimitError=_FakeRateLimit, APIStatusError=_FakeAPIStatus )


def _fake_response( content_blocks, in_tok=100, out_tok=50, stop="end_turn" ):
    resp = MagicMock()
    resp.content = content_blocks
    resp.usage.input_tokens  = in_tok
    resp.usage.output_tokens = out_tok
    resp.stop_reason         = stop
    return resp


def _text_block( text ):
    b = MagicMock()
    b.text = text
    return b


def _make_client( **kw ):
    """Build a PodcastAPIClient with the SDK client patched out."""
    with patch.object( ac, "AsyncAnthropic", MagicMock() ):
        return PodcastAPIClient( api_key="test-key", **kw )


# ----------------------------------------------------------------------------
# CostEstimate
# ----------------------------------------------------------------------------
class TestCostEstimate:
    """
    CostEstimate accrual + summary.

    Ensures opus vs non-opus pricing branches and the formatted summary.
    """

    def test_add_usage_opus_pricing( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-opus-4-6", 1_000_000, 1_000_000 )
        # 15.0 + 75.0 = 90.0 per million-each
        assert ce.estimated_cost_usd == pytest.approx( 90.0 )
        assert ce.total_api_calls == 1

    def test_add_usage_sonnet_pricing( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-sonnet-4-6", 1_000_000, 1_000_000 )
        # 3.0 + 15.0 = 18.0
        assert ce.estimated_cost_usd == pytest.approx( 18.0 )

    def test_get_summary_format( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-opus-4-6", 1000, 500 )
        summary = ce.get_summary()
        assert "API Calls: 1" in summary
        assert "1,000 in" in summary
        assert "500 out" in summary


class TestAPIResponse:
    """APIResponse dataclass — raw_response defaults to None."""

    def test_defaults( self ):
        r = APIResponse( content="c", model="m", input_tokens=1, output_tokens=2, stop_reason="end_turn" )
        assert r.raw_response is None


# ----------------------------------------------------------------------------
# __init__ key resolution
# ----------------------------------------------------------------------------
class TestInit:
    """
    PodcastAPIClient.__init__ firewalled-key resolution + guards.

    Ensures: ImportError when SDK absent; key from parameter / env / local file;
    the local-file failure debug path; and ValueError when no key is found.
    """

    def test_import_error_when_sdk_unavailable( self ):
        with patch.object( ac, "ANTHROPIC_AVAILABLE", False ):
            with pytest.raises( ImportError, match="anthropic SDK not installed" ):
                PodcastAPIClient( api_key="x" )

    def test_key_from_parameter( self, capsys ):
        with patch.object( ac, "AsyncAnthropic", MagicMock() ):
            c = PodcastAPIClient( api_key="param-key", debug=True )
        assert c.api_key    == "param-key"
        assert c.key_source == "parameter"
        out = capsys.readouterr().out
        assert "API key source: parameter" in out
        assert "Script model:" in out

    def test_key_from_environment( self ):
        with patch.object( ac, "AsyncAnthropic", MagicMock() ), \
             patch.dict( "os.environ", { ENV_VAR_NAME: "env-key" } ):
            c = PodcastAPIClient()
        assert c.api_key    == "env-key"
        assert c.key_source == "environment"

    def test_key_from_local_file( self ):
        with patch.object( ac, "AsyncAnthropic", MagicMock() ), \
             patch.dict( "os.environ", {}, clear=True ), \
             patch( "cosa.utils.util.get_api_key", return_value="file-key" ):
            c = PodcastAPIClient()
        assert c.api_key    == "file-key"
        assert c.key_source == "local file"

    def test_local_file_failure_then_value_error_with_debug( self, capsys ):
        with patch.object( ac, "AsyncAnthropic", MagicMock() ), \
             patch.dict( "os.environ", {}, clear=True ), \
             patch( "cosa.utils.util.get_api_key", side_effect=RuntimeError( "no file" ) ):
            with pytest.raises( ValueError, match="Anthropic API key not found" ):
                PodcastAPIClient( debug=True )
        assert "Could not load local key file" in capsys.readouterr().out

    def test_local_file_failure_debug_false_no_print( self, capsys ):
        # debug=False exercises the 172->175 skip arc (no debug print in except).
        with patch.object( ac, "AsyncAnthropic", MagicMock() ), \
             patch.dict( "os.environ", {}, clear=True ), \
             patch( "cosa.utils.util.get_api_key", side_effect=RuntimeError( "no file" ) ):
            with pytest.raises( ValueError ):
                PodcastAPIClient( debug=False )
        assert "Could not load local key file" not in capsys.readouterr().out


# ----------------------------------------------------------------------------
# call_for_* delegation + call_with_json_output
# ----------------------------------------------------------------------------
class TestCallWrappers:
    """
    The public call_for_* methods delegate to _call_api with the right call_type
    + temperature; call_with_json_output parses JSON (with markdown fences) and
    raises on invalid JSON.
    """

    def test_call_for_analysis_delegates( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value="RESP" )
        out = _run( c.call_for_analysis( "sys", "msg" ) )
        assert out == "RESP"
        kwargs = c._call_api.await_args.kwargs
        assert kwargs[ "call_type" ]   == "analysis"
        assert kwargs[ "temperature" ] == 0.7

    def test_call_for_script_delegates( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value="RESP" )
        _run( c.call_for_script( "sys", "msg" ) )
        assert c._call_api.await_args.kwargs[ "call_type" ]   == "script_generation"
        assert c._call_api.await_args.kwargs[ "temperature" ] == 0.8

    def test_call_for_revision_delegates( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value="RESP" )
        _run( c.call_for_revision( "sys", "msg" ) )
        assert c._call_api.await_args.kwargs[ "call_type" ]   == "revision"
        assert c._call_api.await_args.kwargs[ "temperature" ] == 0.6

    def test_json_output_strips_json_fence( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value=APIResponse(
            content='```json\n{"a": 1}\n```', model="m", input_tokens=1, output_tokens=1, stop_reason="end_turn"
        ) )
        out = _run( c.call_with_json_output( "sys", "msg" ) )
        assert out == { "a": 1 }

    def test_json_output_strips_bare_fence( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value=APIResponse(
            content='```\n{"b": 2}\n```', model="m", input_tokens=1, output_tokens=1, stop_reason="end_turn"
        ) )
        assert _run( c.call_with_json_output( "sys", "msg" ) ) == { "b": 2 }

    def test_json_output_invalid_raises_value_error( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value=APIResponse(
            content="not json at all", model="m", input_tokens=1, output_tokens=1, stop_reason="end_turn"
        ) )
        with pytest.raises( ValueError, match="not valid JSON" ):
            _run( c.call_with_json_output( "sys", "msg" ) )


# ----------------------------------------------------------------------------
# _call_api
# ----------------------------------------------------------------------------
class TestCallApi:
    """
    _call_api content extraction + usage recording.

    Ensures system_prompt is included only when truthy, content concatenates
    only blocks with a `.text` attr, usage is recorded, and debug prints.
    """

    def test_with_system_prompt_and_mixed_blocks( self, capsys ):
        c = _make_client( debug=True )
        no_text_block = MagicMock( spec=[] )    # no .text attr
        resp = _fake_response( [ _text_block( "Hello " ), no_text_block, _text_block( "world" ) ] )
        c._call_with_retry = AsyncMock( return_value=resp )
        out = _run( c._call_api( model="claude-opus-4-6", system_prompt="SYS", user_message="hi", call_type="analysis" ) )
        assert out.content       == "Hello world"
        assert out.input_tokens  == 100
        assert out.output_tokens == 50
        # system prompt forwarded
        assert c._call_with_retry.await_args.args[ 0 ][ "system" ] == "SYS"
        assert c.cost_estimate.total_api_calls == 1
        printed = capsys.readouterr().out
        assert "Calling claude-opus-4-6 for analysis" in printed
        assert "Response: 100 in, 50 out" in printed

    def test_without_system_prompt_omits_system_key( self ):
        c = _make_client()
        c._call_with_retry = AsyncMock( return_value=_fake_response( [ _text_block( "x" ) ] ) )
        _run( c._call_api( model="m", system_prompt="", user_message="hi" ) )
        assert "system" not in c._call_with_retry.await_args.args[ 0 ]


# ----------------------------------------------------------------------------
# _call_with_retry ladder
# ----------------------------------------------------------------------------
class TestCallWithRetry:
    """
    _call_with_retry exponential-backoff ladder with faked anthropic exceptions.

    Ensures: success first try; rate-limit retry then success; rate-limit
    exhausted -> raise; 5xx retry; <500 status -> immediate raise; generic
    retry then success; generic exhausted -> raise.
    """

    def _client_with_create( self, side_effect=None, return_value=None ):
        c = _make_client()
        c._client = MagicMock()
        c._client.messages.create = AsyncMock( side_effect=side_effect, return_value=return_value )
        return c

    def test_success_first_attempt( self ):
        c = self._client_with_create( return_value="OK" )
        with patch.object( ac, "anthropic", _fake_anthropic() ):
            out = _run( c._call_with_retry( { "model": "m" } ) )
        assert out == "OK"

    def test_rate_limit_then_success( self ):
        c = self._client_with_create( side_effect=[ _FakeRateLimit( "429" ), "OK" ] )
        with patch.object( ac, "anthropic", _fake_anthropic() ), patch( "asyncio.sleep", AsyncMock() ) as slp:
            out = _run( c._call_with_retry( { "model": "m" }, max_retries=2 ) )
        assert out == "OK"
        slp.assert_awaited_once()

    def test_rate_limit_exhausted_raises( self ):
        c = self._client_with_create( side_effect=_FakeRateLimit( "429" ) )
        with patch.object( ac, "anthropic", _fake_anthropic() ), patch( "asyncio.sleep", AsyncMock() ):
            with pytest.raises( _FakeRateLimit ):
                _run( c._call_with_retry( { "model": "m" }, max_retries=1 ) )

    def test_server_error_5xx_then_success( self ):
        c = self._client_with_create( side_effect=[ _FakeAPIStatus( "boom", 503 ), "OK" ] )
        with patch.object( ac, "anthropic", _fake_anthropic() ), patch( "asyncio.sleep", AsyncMock() ) as slp:
            out = _run( c._call_with_retry( { "model": "m" }, max_retries=2 ) )
        assert out == "OK"
        slp.assert_awaited_once()

    def test_server_error_5xx_exhausted_raises( self ):
        # 5xx on every attempt: last attempt takes the `attempt < max_retries`
        # FALSE arc (no sleep), loop exhausts -> raise last_error.
        c = self._client_with_create( side_effect=_FakeAPIStatus( "boom", 500 ) )
        with patch.object( ac, "anthropic", _fake_anthropic() ), patch( "asyncio.sleep", AsyncMock() ) as slp:
            with pytest.raises( _FakeAPIStatus ):
                _run( c._call_with_retry( { "model": "m" }, max_retries=1 ) )
        slp.assert_awaited_once()                      # only the first (non-final) attempt slept

    def test_client_error_under_500_raises_immediately( self ):
        c = self._client_with_create( side_effect=_FakeAPIStatus( "bad request", 400 ) )
        with patch.object( ac, "anthropic", _fake_anthropic() ), patch( "asyncio.sleep", AsyncMock() ) as slp:
            with pytest.raises( _FakeAPIStatus ):
                _run( c._call_with_retry( { "model": "m" }, max_retries=3 ) )
        slp.assert_not_awaited()                       # 4xx is not retried

    def test_generic_exception_then_success( self ):
        c = self._client_with_create( side_effect=[ RuntimeError( "net blip" ), "OK" ] )
        with patch.object( ac, "anthropic", _fake_anthropic() ), patch( "asyncio.sleep", AsyncMock() ) as slp:
            out = _run( c._call_with_retry( { "model": "m" }, max_retries=2 ) )
        assert out == "OK"
        slp.assert_awaited_once()

    def test_generic_exception_exhausted_raises( self ):
        c = self._client_with_create( side_effect=RuntimeError( "down" ) )
        with patch.object( ac, "anthropic", _fake_anthropic() ), patch( "asyncio.sleep", AsyncMock() ):
            with pytest.raises( RuntimeError, match="down" ):
                _run( c._call_with_retry( { "model": "m" }, max_retries=1 ) )


# ----------------------------------------------------------------------------
# get_cost_summary + close
# ----------------------------------------------------------------------------
class TestSummaryAndClose:
    """get_cost_summary proxies CostEstimate; close awaits client.close when present."""

    def test_get_cost_summary( self ):
        c = _make_client()
        c.cost_estimate.add_usage( "claude-opus-4-6", 100, 50 )
        assert "API Calls: 1" in c.get_cost_summary()

    def test_close_awaits_client_close_when_present( self ):
        c = _make_client()
        c._client = MagicMock()
        c._client.close = AsyncMock()
        _run( c.close() )
        c._client.close.assert_awaited_once()

    def test_close_noop_when_no_close_method( self ):
        c = _make_client()
        c._client = MagicMock( spec=[] )               # no close attr
        _run( c.close() )                              # must not raise
