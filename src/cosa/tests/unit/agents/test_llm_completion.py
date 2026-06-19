"""
Unit tests for cosa.agents.llm_completion.

LlmCompletion is an OpenAI-compatible completions client (sync `run` via requests,
async streaming via aiohttp) plus a CompletionStreamingContext async context
manager. Tests cover:

- __init__ config storage (TokenCounter mocked)
- run: non-stream success (text cleanup), error status (raise), debug-timer branch,
  stream=True → _prepare_streaming_request passthrough
- _prepare_streaming_request stub
- _stream_async: non-200 raise + the full SSE line-processing matrix (empty /
  non-data / bad-json / no-choices / empty-choices / empty-delta / yielded-delta /
  [DONE] break) over a fake aiohttp session
- run_stream returns a CompletionStreamingContext
- CompletionStreamingContext __aenter__ / __aexit__ / stream_text passthrough

All network is mocked at the boundary (requests.post, aiohttp.ClientSession) —
no real HTTP, zero spend. quick_smoke_test excluded via pyproject.

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, agents Tier-2, LLM-support lane).
"""

import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from cosa.agents.llm_completion import LlmCompletion, CompletionStreamingContext


async def _collect( agen ):
    out = []
    async for x in agen:
        out.append( x )
    return out


class _FakeResp:
    """Async-context-manager response with an async-iterable .content."""

    def __init__( self, status, lines=(), text="" ):
        self.status   = status
        self._lines   = list( lines )
        self._text    = text

    async def text( self ):
        return self._text

    @property
    def content( self ):
        return self

    def __aiter__( self ):
        self._it = iter( self._lines )
        return self

    async def __anext__( self ):
        try:
            return next( self._it )
        except StopIteration:
            raise StopAsyncIteration

    async def __aenter__( self ):
        return self

    async def __aexit__( self, *exc ):
        return False


class _FakeSession:
    """Async-context-manager session whose .post returns a (response) async CM."""

    def __init__( self, resp ):
        self._resp = resp

    def post( self, *args, **kwargs ):
        return self._resp

    async def __aenter__( self ):
        return self

    async def __aexit__( self, *exc ):
        return False


def _client( **kwargs ):
    with patch( "cosa.agents.llm_completion.TokenCounter", return_value=Mock() ):
        return LlmCompletion( **kwargs )


class TestInitAndRun( unittest.TestCase ):
    def test_init_stores_config( self ):
        with patch( "cosa.agents.llm_completion.TokenCounter", return_value=Mock() ) as mock_tc:
            client = LlmCompletion( base_url="http://h/v1", model_name="m", api_key="k", debug=True )
        self.assertEqual( client.base_url, "http://h/v1" )
        self.assertEqual( client.model_name, "m" )
        self.assertEqual( client.api_key, "k" )
        self.assertTrue( client.debug )
        mock_tc.assert_called_once()

    def test_run_success_cleans_text( self ):
        """200 → choices[0].text stripped of code fences + whitespace."""
        client = _client()
        resp = Mock()
        resp.status_code = 200
        resp.json.return_value = { "choices": [ { "text": "```\nhello world\n```  " } ] }
        with patch( "cosa.agents.llm_completion.requests.post", return_value=resp ):
            result = client.run( "hi" )
        self.assertEqual( result, "hello world" )

    def test_run_success_debug_timer( self ):
        """debug=True exercises the Stopwatch timer branches."""
        client = _client( debug=True )
        resp = Mock()
        resp.status_code = 200
        resp.json.return_value = { "choices": [ { "text": "ok" } ] }
        with patch( "cosa.agents.llm_completion.requests.post", return_value=resp ), \
             patch( "builtins.print" ):
            result = client.run( "hi" )
        self.assertEqual( result, "ok" )

    def test_run_error_status_raises( self ):
        """Non-200 → prints error and raises."""
        client = _client()
        resp = Mock()
        resp.status_code = 500
        resp.text = "server error"
        with patch( "cosa.agents.llm_completion.requests.post", return_value=resp ), \
             patch( "builtins.print" ):
            with self.assertRaises( Exception ):
                client.run( "hi" )

    def test_run_stream_returns_prepared_request( self ):
        """stream=True short-circuits to _prepare_streaming_request (returns prompt)."""
        client = _client()
        result = client.run( "my prompt", stream=True )
        self.assertEqual( result, "my prompt" )

    def test_prepare_streaming_request_returns_prompt( self ):
        client = _client()
        self.assertEqual( client._prepare_streaming_request( "p", {}, {} ), "p" )

    def test_run_kwargs_override_generation_args( self ):
        """Per-call kwargs override the instance generation_args in the request body."""
        client = _client( max_tokens=10 )
        resp = Mock()
        resp.status_code = 200
        resp.json.return_value = { "choices": [ { "text": "x" } ] }
        with patch( "cosa.agents.llm_completion.requests.post", return_value=resp ) as mock_post:
            client.run( "hi", max_tokens=99, temperature=0.5 )
        sent = json.loads( mock_post.call_args.kwargs[ "data" ] )
        self.assertEqual( sent[ "max_tokens" ], 99 )
        self.assertEqual( sent[ "temperature" ], 0.5 )


class TestStreamAsync( unittest.TestCase ):
    def test_stream_async_non_200_raises( self ):
        client = _client()
        resp = _FakeResp( status=500, text="boom" )
        with patch( "aiohttp.ClientSession", return_value=_FakeSession( resp ) ):
            with self.assertRaises( Exception ):
                asyncio.run( _collect( client._stream_async( "p" ) ) )

    def test_stream_async_sse_line_matrix( self ):
        """Every SSE-line branch: empty / non-data / bad-json / no-choices /
        empty-choices / empty-delta / yielded-delta / [DONE] break."""
        client = _client()
        lines = [
            b"  \n",                                       # empty → continue
            b"random noise",                               # not 'data: ' → skip
            b"data: not-json{",                            # JSONDecodeError → continue
            b'data: {"nochoices": 1}',                     # 'choices' absent → skip
            b'data: {"choices": []}',                      # empty choices → skip
            b'data: {"choices": [{"text": ""}]}',          # empty delta → not yielded
            b'data: {"choices": [{"text": "hi"}]}',        # yielded
            b"data: [DONE]",                               # break
            b'data: {"choices": [{"text": "after"}]}',     # never reached (after break)
        ]
        resp = _FakeResp( status=200, lines=lines )
        with patch( "aiohttp.ClientSession", return_value=_FakeSession( resp ) ):
            chunks = asyncio.run( _collect( client._stream_async( "p" ) ) )
        self.assertEqual( chunks, [ "hi" ] )               # only the non-empty delta before [DONE]


class TestStreamingContext( unittest.TestCase ):
    def test_run_stream_returns_context( self ):
        client = _client()
        ctx = client.run_stream( "p", max_tokens=5 )
        self.assertIsInstance( ctx, CompletionStreamingContext )
        self.assertIs( ctx.client, client )
        self.assertEqual( ctx.prompt, "p" )

    def test_aenter_aexit( self ):
        client = _client()
        ctx = CompletionStreamingContext( client, "p" )

        async def _use():
            async with ctx as entered:
                return entered

        self.assertIs( asyncio.run( _use() ), ctx )

    def test_stream_text_passes_through_client_stream( self ):
        """stream_text yields whatever client._stream_async yields."""
        client = _client()

        async def _fake_stream( prompt, **kwargs ):
            for piece in ( "a", "b", "c" ):
                yield piece

        with patch.object( client, "_stream_async", _fake_stream ):
            ctx = CompletionStreamingContext( client, "p" )
            chunks = asyncio.run( _collect( ctx.stream_text() ) )
        self.assertEqual( chunks, [ "a", "b", "c" ] )


if __name__ == "__main__":
    unittest.main()
