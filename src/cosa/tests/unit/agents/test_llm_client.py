#!/usr/bin/env python3
"""
Unit tests for cosa.agents.llm_client.LlmClient

From-scratch suite (no prior coverage). Every external boundary is mocked:
pydantic_ai Agent + ModelSettings, LlmCompletion, TokenCounter, and the
run_stream async-context-manager (yielding an async stream_text generator).
NO real LLM / network / token-model load / spend.

Covers the corrected post-02232a9 behavior:
  - bug #6: _print_metadata + _format_duration are live and called under
    debug+verbose (the "📊 Stream Summary" banner) — including the
    duration=None "N/A" branch and the tokens/sec inf branch (duration 0/None).
  - bug #7: _stream_async counter inits before the loop; the counter % 128
    newline cadence is driven with >=128 chunks.

quick_smoke_test() and the __main__ guard are coverage-excluded by repo config.
"""

import os
import asyncio
import contextlib
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

import cosa.agents.llm_client as lc
from cosa.agents.llm_client import LlmClient


def _run( coro ):
    return asyncio.run( coro )


# ----------------------------------------------------------------------------
# Fake streaming context manager (mirrors pydantic_ai run_stream())
# ----------------------------------------------------------------------------
class _FakeStreamResult:
    def __init__( self, chunks ):
        self._chunks = chunks

    async def stream_text( self, delta=False ):
        for c in self._chunks:
            yield c


class _FakeStreamCM:
    def __init__( self, chunks ):
        self._result = _FakeStreamResult( chunks )

    async def __aenter__( self ):
        return self._result

    async def __aexit__( self, *a ):
        return False


@contextlib.contextmanager
def _patched_module():
    """Patch the four LlmClient external dependencies at the module boundary."""
    with patch.object( lc, "Agent", MagicMock() ) as agent, \
         patch.object( lc, "LlmCompletion", MagicMock() ) as completion, \
         patch.object( lc, "TokenCounter", MagicMock() ) as tok_ctor, \
         patch.object( lc, "ModelSettings", MagicMock() ) as settings:
        # token_counter.count_tokens(model_name, text) -> fixed int
        tok_ctor.return_value.count_tokens = MagicMock( return_value=7 )
        yield { "Agent": agent, "LlmCompletion": completion, "TokenCounter": tok_ctor, "ModelSettings": settings }


def _client( **kw ):
    """Build an LlmClient with all boundaries patched; returns (client, mocks)."""
    defaults = dict( base_url="http://x/v1", model_name="m", api_key="K" )
    defaults.update( kw )
    cm = _patched_module()
    mocks = cm.__enter__()
    client = LlmClient( **defaults )
    # keep the patch active for the lifetime of the test via the client attr
    client._test_patch = cm
    client._test_mocks = mocks
    return client, mocks


# ----------------------------------------------------------------------------
# get_model
# ----------------------------------------------------------------------------
class TestGetModel:
    """
    get_model builds a 'prefix/mnt' identifier and requires '//' to be present.

    Ensures the happy path (absolute mount point yields '//'), a custom prefix,
    and the ValueError guard when '//' is absent.
    """

    def test_absolute_mount_point_yields_double_slash( self ):
        assert LlmClient.get_model( "/mnt/point" ) == "deepily//mnt/point"

    def test_custom_prefix( self ):
        assert LlmClient.get_model( "/mnt/x", prefix="foo" ) == "foo//mnt/x"

    def test_missing_double_slash_raises( self ):
        with pytest.raises( ValueError, match="not in 'prefix//mnt/point' format" ):
            LlmClient.get_model( "relative-name" )


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
class TestInit:
    """
    LlmClient.__init__ env setup + model selection.

    Ensures: OPENAI_* env vars set (api_key fallback to EMPTY); chat mode builds
    an Agent via ModelSettings; completion mode builds an LlmCompletion (with the
    debug banner branch); TokenCounter + generation_args stored.
    """

    def test_chat_mode_builds_agent( self ):
        with _patched_module() as m:
            c = LlmClient( base_url="http://h/v1", model_name="mymodel", api_key="K", temperature=0.5 )
        assert c.completion_mode is False
        assert c.model is m[ "Agent" ].return_value
        # ModelSettings built from generation_args; Agent built with openai:-prefixed name
        m[ "ModelSettings" ].assert_called_once_with( temperature=0.5 )
        assert m[ "Agent" ].call_args.args[ 0 ] == "openai:mymodel"
        assert c.generation_args == { "temperature": 0.5 }
        assert os.environ[ "OPENAI_API_KEY" ]  == "K"
        assert os.environ[ "OPENAI_BASE_URL" ] == "http://h/v1"

    def test_api_key_none_falls_back_to_empty( self ):
        with _patched_module():
            LlmClient( base_url="http://h/v1", model_name="m", api_key=None )
        assert os.environ[ "OPENAI_API_KEY" ] == "EMPTY"

    def test_completion_mode_debug_builds_llmcompletion( self, capsys ):
        with _patched_module() as m:
            c = LlmClient( base_url="http://h/v1", model_name="m", completion_mode=True,
                           prompt_format="alpaca", debug=True )
        assert c.completion_mode is True
        assert c.model is m[ "LlmCompletion" ].return_value
        out = capsys.readouterr().out
        assert "alpaca" in out                          # debug banner prints prompt_format

    def test_completion_mode_no_debug( self ):
        with _patched_module() as m:
            c = LlmClient( base_url="http://h/v1", model_name="m", completion_mode=True, debug=False )
        m[ "LlmCompletion" ].assert_called_once()
        assert c.model is m[ "LlmCompletion" ].return_value


# ----------------------------------------------------------------------------
# _format_duration + _print_metadata  (bug #6 corrected behavior)
# ----------------------------------------------------------------------------
class TestFormatAndMetadata:
    """
    _format_duration ms-formatting + _print_metadata summary (uncommented by the
    02232a9 fix).

    Ensures ms formatting, the "📊 Stream Summary" banner + tokens/sec line, the
    duration=None "N/A" branch, and the inf tokens/sec branch when duration is
    None or zero.
    """

    def test_format_duration_milliseconds( self ):
        c, _ = _client()
        assert c._format_duration( 1.5 )   == "1500ms"
        assert c._format_duration( 0.042 ) == "42ms"

    def test_print_metadata_with_duration( self, capsys ):
        c, _ = _client( model_name="mymodel" )
        c._print_metadata( prompt_tokens=10, completion_tokens=20, duration=2.0 )
        out = capsys.readouterr().out
        assert "📊 Stream Summary" in out
        assert "Model" in out and "mymodel" in out
        assert "Duration" in out and "2000ms" in out
        assert "Total tokens" in out and "30" in out
        assert "Tokens/sec" in out and "10.00" in out    # 20 / 2.0

    def test_print_metadata_duration_none_uses_na_and_inf( self, capsys ):
        c, _ = _client()
        c._print_metadata( prompt_tokens=5, completion_tokens=5, duration=None )
        out = capsys.readouterr().out
        assert "N/A" in out
        assert "inf" in out                              # tps -> float('inf')

    def test_print_metadata_duration_zero_uses_inf( self, capsys ):
        c, _ = _client()
        c._print_metadata( prompt_tokens=1, completion_tokens=1, duration=0.0 )
        out = capsys.readouterr().out
        assert "0ms" in out                              # 0 is not None -> formatted
        assert "inf" in out                              # duration falsy -> inf


# ----------------------------------------------------------------------------
# _stream_async  (bug #7: counter inits before loop; %128 cadence)
# ----------------------------------------------------------------------------
class TestStreamAsync:
    """
    _stream_async chunk collection across completion + Agent branches, in both
    the verbose-echo and dot-progress display modes.

    Ensures chunks join into the full response, the debug+verbose echo path
    prints raw chunks, and the dot-progress path emits a newline every 128
    chunks (the bug-#7 cadence) without resetting the counter.
    """

    def _attach_stream( self, client, chunks ):
        client.model.run_stream = MagicMock( return_value=_FakeStreamCM( chunks ) )

    def test_completion_mode_verbose_echo( self, capsys ):
        c, _ = _client( completion_mode=True, debug=True, verbose=True )
        self._attach_stream( c, [ "Hello, ", "world" ] )
        out = _run( c._stream_async( "p" ) )
        assert out == "Hello, world"
        assert "Hello, world" in capsys.readouterr().out  # echoed raw

    def test_completion_mode_dot_progress_128_newline( self, capsys ):
        c, _ = _client( completion_mode=True, debug=False, verbose=False )
        chunks = [ "x" ] * 130                            # >=128 -> newline cadence fires
        self._attach_stream( c, chunks )
        out = _run( c._stream_async( "p" ) )
        assert out == "x" * 130
        printed = capsys.readouterr().out
        assert "." in printed
        assert "\n" in printed                            # %128 newline emitted

    def test_agent_mode_verbose_echo( self, capsys ):
        c, _ = _client( completion_mode=False, debug=True, verbose=True )
        self._attach_stream( c, [ "Ans", "wer" ] )
        out = _run( c._stream_async( "p" ) )
        assert out == "Answer"
        assert "Answer" in capsys.readouterr().out

    def test_agent_mode_dot_progress( self, capsys ):
        c, _ = _client( completion_mode=False, debug=False, verbose=False )
        self._attach_stream( c, [ "a", "b", "c" ] )
        out = _run( c._stream_async( "p" ) )
        assert out == "abc"
        assert "." in capsys.readouterr().out


# ----------------------------------------------------------------------------
# run_async
# ----------------------------------------------------------------------------
class TestRunAsync:
    """
    run_async non-stream + stream paths across Agent / completion modes.

    Ensures: generation-arg merge (kwargs override generation_args); Agent
    non-stream awaits model.run and unwraps .output; completion non-stream calls
    sync model.run; the stream gate honours both the `stream` arg and a
    generation_args 'stream' default; metadata prints under debug+verbose.
    """

    def test_non_stream_agent_unwraps_output( self, capsys ):
        c, _ = _client( completion_mode=False, debug=True, verbose=True, temperature=0.9 )
        resp = MagicMock()
        resp.output = "agent-answer"
        c.model.run = AsyncMock( return_value=resp )
        out = _run( c.run_async( "prompt" ) )
        assert out == "agent-answer"
        # kwargs default to generation_args; temperature carried into ModelSettings call
        printed = capsys.readouterr().out
        assert "Updating generation arguments" in printed
        assert "📊 Stream Summary" in printed             # debug+verbose metadata

    def test_non_stream_agent_kwargs_override( self ):
        c, _ = _client( completion_mode=False )
        resp = MagicMock( output="ok" )
        c.model.run = AsyncMock( return_value=resp )
        _run( c.run_async( "prompt", temperature=0.1, max_tokens=999 ) )
        # ModelSettings built with the overridden values
        call_kwargs = c._test_mocks[ "ModelSettings" ].call_args.kwargs
        assert call_kwargs[ "temperature" ] == 0.1
        assert call_kwargs[ "max_tokens" ]  == 999

    def test_non_stream_completion_uses_sync_run( self ):
        c, _ = _client( completion_mode=True )
        c.model.run = MagicMock( return_value="completion-answer" )
        out = _run( c.run_async( "prompt" ) )
        assert out == "completion-answer"
        c.model.run.assert_called_once()

    def test_non_stream_no_debug_skips_metadata( self, capsys ):
        c, _ = _client( completion_mode=False, debug=False, verbose=False )
        c.model.run = AsyncMock( return_value=MagicMock( output="x" ) )
        _run( c.run_async( "prompt" ) )
        assert "📊 Stream Summary" not in capsys.readouterr().out

    def test_stream_path_via_arg( self, capsys ):
        c, _ = _client( completion_mode=False, debug=True, verbose=True )
        c.model.run_stream = MagicMock( return_value=_FakeStreamCM( [ "str", "eam" ] ) )
        out = _run( c.run_async( "prompt", stream=True ) )
        assert out == "stream"
        printed = capsys.readouterr().out
        assert "🔄 Streaming" in printed
        assert "📊 Stream Summary" in printed

    def test_stream_path_via_generation_args_default( self ):
        # stream arg False but generation_args carries stream=True -> stream path
        c, _ = _client( completion_mode=False, stream=True )
        c.model.run_stream = MagicMock( return_value=_FakeStreamCM( [ "z" ] ) )
        out = _run( c.run_async( "prompt", stream=False ) )
        assert out == "z"


# ----------------------------------------------------------------------------
# run (sync bridge)
# ----------------------------------------------------------------------------
class TestRunSyncBridge:
    """
    run() bridges to run_async across both sync and async call contexts.

    Ensures: no-running-loop (sync) path runs a fresh loop directly; an active
    running loop routes through the ThreadPoolExecutor worker. Both return the
    run_async result.
    """

    def test_sync_context_direct_loop( self ):
        c, _ = _client( completion_mode=False )
        c.model.run = AsyncMock( return_value=MagicMock( output="sync-answer" ) )
        # called with no running loop -> get_running_loop raises -> direct path
        assert c.run( "prompt" ) == "sync-answer"

    def test_async_context_uses_thread_executor( self ):
        c, _ = _client( completion_mode=False )
        c.model.run = AsyncMock( return_value=MagicMock( output="threaded-answer" ) )

        async def _from_async_context():
            # inside a running loop -> get_running_loop() succeeds -> executor path
            return c.run( "prompt" )

        assert _run( _from_async_context() ) == "threaded-answer"
