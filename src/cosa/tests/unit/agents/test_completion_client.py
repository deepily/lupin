#!/usr/bin/env python3
"""
Unit tests for cosa/agents/completion_client.py (CompletionClient + clean_llm_response).

Supersedes the legacy infra-framework test (which skipped at collection). All
external dependencies are boundary-mocked at the completion_client module:
    - LlmCompletion  → _FakeCompletion (sync run / async run_stream)
    - TokenCounter   → _FakeTokenCounter (fixed counts)
os.environ is isolated to a per-test copy so API-key/base-url writes never leak.
ZERO API spend, ZERO network.
"""
import asyncio
import os

import pytest

import cosa.agents.completion_client as comp_mod
from cosa.agents.completion_client import CompletionClient, clean_llm_response
from cosa.agents.base_llm_client import LlmClientInterface


# =========================================================================== #
# Test doubles
# =========================================================================== #
class _FakeStreamResult:
    def __init__( self, chunks ): self._chunks = chunks
    async def __aenter__( self ): return self
    async def __aexit__( self, *exc ): return False
    async def stream_text( self, delta=False ):
        for c in self._chunks:
            yield c


class _FakeCompletion:
    """Scripted stand-in for LlmCompletion."""
    run_output    = "plain output"
    stream_chunks = [ "a", "b" ]
    def __init__( self, base_url=None, model_name=None, api_key=None, **gen ):
        self.base_url   = base_url
        self.model_name = model_name
        self.api_key    = api_key
        self.gen        = gen
    def run( self, prompt, **gen ):
        return type( self ).run_output
    def run_stream( self, prompt, **gen ):
        return _FakeStreamResult( type( self ).stream_chunks )


class _FakeTokenCounter:
    def __init__( self, model_tokenizer_map=None ):
        self.model_tokenizer_map = model_tokenizer_map
    def count_tokens( self, model_name, text ):
        return len( ( text or "" ).split() )


@pytest.fixture( autouse=True )
def _isolate_env( monkeypatch ):
    monkeypatch.setattr( os, "environ", dict( os.environ ) )


@pytest.fixture( autouse=True )
def _patch_deps( monkeypatch ):
    monkeypatch.setattr( comp_mod, "LlmCompletion", _FakeCompletion )
    monkeypatch.setattr( comp_mod, "TokenCounter", _FakeTokenCounter )
    _FakeCompletion.run_output    = "plain output"
    _FakeCompletion.stream_chunks = [ "a", "b" ]


def _make( **kw ):
    kw.setdefault( "base_url", "http://host/v1/completions" )
    kw.setdefault( "model_name", "Qwen/Qwen3-4B" )
    return CompletionClient( **kw )


# =========================================================================== #
# clean_llm_response  (module function)
# =========================================================================== #
def test_clean_llm_response_strips_fenced_block():
    """Leading ```lang fence and trailing ``` fence are removed."""
    assert clean_llm_response( "```python\nprint(1)\n```" ) == "print(1)"


def test_clean_llm_response_strips_bare_backtick_fence():
    """A bare ``` fence (no language) is removed."""
    assert clean_llm_response( "```\nhello\n```" ) == "hello"


def test_clean_llm_response_no_fence_unchanged():
    """Plain text without fences is returned stripped, unchanged otherwise."""
    assert clean_llm_response( "  just text  " ) == "just text"


# =========================================================================== #
# __init__
# =========================================================================== #
def test_init_sets_env_and_attrs():
    """api_key sets OPENAI_API_KEY; base_url always sets OPENAI_BASE_URL; attrs stored."""
    c = _make( api_key="sk-x", prompt_format="instruction_completion", temperature=0.3 )
    assert os.environ[ "OPENAI_API_KEY" ] == "sk-x"
    assert os.environ[ "OPENAI_BASE_URL" ] == "http://host/v1/completions"
    assert c.prompt_format == "instruction_completion"
    assert c.generation_args == { "temperature": 0.3 }
    assert isinstance( c, LlmClientInterface )
    assert isinstance( c.model, _FakeCompletion )


def test_init_without_api_key_still_sets_base_url():
    """No api_key → OPENAI_API_KEY untouched, but base_url is still written."""
    os.environ.pop( "OPENAI_API_KEY", None )
    _make()
    assert os.environ[ "OPENAI_BASE_URL" ] == "http://host/v1/completions"


def test_init_debug_verbose_banner( capsys ):
    """debug+verbose prints the init banner block."""
    _make( debug=True, verbose=True )
    out = capsys.readouterr().out
    assert "CompletionClient" in out and "Base URL" in out


# =========================================================================== #
# run_async — non-streaming
# =========================================================================== #
def test_run_async_non_stream_cleans_and_returns():
    """Non-streaming run cleans the model output of fences."""
    _FakeCompletion.run_output = "```\nresult\n```"
    c = _make()
    assert asyncio.run( c.run_async( "prompt" ) ) == "result"


def test_run_async_non_stream_metadata_when_debug_verbose( capsys ):
    """debug+verbose prints the perf-metadata summary."""
    c = _make( debug=True, verbose=True )
    asyncio.run( c.run_async( "a b c" ) )
    assert "Completion Summary" in capsys.readouterr().out


def test_run_async_non_stream_quiet_no_metadata( capsys ):
    """Quiet run prints no metadata summary."""
    c = _make()
    asyncio.run( c.run_async( "prompt" ) )
    assert "Completion Summary" not in capsys.readouterr().out


# =========================================================================== #
# run_async — streaming  /  _stream_async
# =========================================================================== #
def test_run_async_stream_verbose_prints_chunks( capsys ):
    """stream + debug+verbose echoes chunks and the streaming banner; output cleaned."""
    _FakeCompletion.stream_chunks = [ "```\n", "hello", "\n```" ]
    c = _make( debug=True, verbose=True )
    out = asyncio.run( c.run_async( "prompt", stream=True ) )
    assert out == "hello"                                     # fences stripped post-stream
    assert "Streaming from completion model" in capsys.readouterr().out


def test_stream_async_quiet_dot_progress_with_newline( capsys ):
    """Quiet streaming uses dot-progress; 128th chunk triggers a newline."""
    _FakeCompletion.stream_chunks = [ "." ] * 130
    c = _make( debug=False )
    out = asyncio.run( c.run_async( "prompt", stream=True ) )
    assert out == "." * 130
    assert "." in capsys.readouterr().out


# =========================================================================== #
# run — sync + async context dispatch
# =========================================================================== #
def test_run_sync_context():
    """Plain sync context: run() spins a fresh loop and returns cleaned output."""
    _FakeCompletion.run_output = "answer"
    assert _make().run( "hello" ) == "answer"


def test_run_inside_running_loop_uses_threadpool():
    """From within a running loop, run() offloads to a worker thread."""
    _FakeCompletion.run_output = "answer"
    c = _make()
    async def _driver():
        return c.run( "hello" )
    assert asyncio.run( _driver() ) == "answer"
