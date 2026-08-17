#!/usr/bin/env python3
"""
Unit tests for cosa/agents/chat_client.py (ChatClient).

Supersedes the legacy infra-framework test (which skipped at collection). All
external dependencies are boundary-mocked at the chat_client module:
    - pydantic_ai Agent      → _FakeAgent (scripted async run / run_stream)
    - ModelSettings          → permissive stub
    - TokenCounter           → _FakeTokenCounter (fixed counts)
os.environ is isolated to a per-test copy so API-key writes never leak.
ZERO API spend, ZERO network.
"""
import asyncio
import os

import pytest

import cosa.agents.chat_client as chat_mod
from cosa.agents.chat_client import ChatClient
from cosa.agents.base_llm_client import LlmClientInterface


# =========================================================================== #
# Test doubles
# =========================================================================== #
class _FakeRunResult:
    def __init__( self, output ): self.output = output


class _FakeStreamResult:
    def __init__( self, chunks ): self._chunks = chunks
    async def __aenter__( self ): return self
    async def __aexit__( self, *exc ): return False
    async def stream_text( self, delta=False ):
        for c in self._chunks:
            yield c


class _FakeAgent:
    """Scripted stand-in for pydantic_ai.Agent."""
    run_output    = "the response"
    stream_chunks = [ "a", "b", "c" ]
    def __init__( self, model_name, model_settings=None ):
        self.model_name     = model_name
        self.model_settings = model_settings
    async def run( self, prompt, model_settings=None ):
        return _FakeRunResult( type( self ).run_output )
    def run_stream( self, prompt, model_settings=None ):
        return _FakeStreamResult( type( self ).stream_chunks )


class _FakeTokenCounter:
    def __init__( self, model_tokenizer_map=None ):
        self.model_tokenizer_map = model_tokenizer_map
    def count_tokens( self, model_name, text ):
        return len( ( text or "" ).split() )


@pytest.fixture( autouse=True )
def _isolate_env( monkeypatch ):
    """Copy os.environ so the client's API-key/base-url writes don't leak."""
    monkeypatch.setattr( os, "environ", dict( os.environ ) )


@pytest.fixture( autouse=True )
def _patch_deps( monkeypatch ):
    """Boundary-mock Agent / ModelSettings / TokenCounter in the module."""
    monkeypatch.setattr( chat_mod, "Agent", _FakeAgent )
    monkeypatch.setattr( chat_mod, "ModelSettings", lambda **k: ( "settings", k ) )
    monkeypatch.setattr( chat_mod, "TokenCounter", _FakeTokenCounter )
    _FakeAgent.run_output    = "the response"
    _FakeAgent.stream_chunks = [ "a", "b", "c" ]


def _make( **kw ):
    kw.setdefault( "model_name", "openai:gpt-4" )
    return ChatClient( **kw )


# =========================================================================== #
# __init__
# =========================================================================== #
def test_init_sets_env_and_attrs():
    """set_openai_env=True + api_key + base_url populate env; attrs + Agent are configured."""
    c = _make( api_key="sk-test", base_url="http://host/v1", set_openai_env=True, temperature=0.5 )
    assert os.environ[ "OPENAI_API_KEY" ] == "sk-test"
    assert os.environ[ "OPENAI_BASE_URL" ] == "http://host/v1"
    assert c.model_name == "openai:gpt-4"
    assert c.generation_args == { "temperature": 0.5 }
    assert isinstance( c, LlmClientInterface )
    assert isinstance( c.model, _FakeAgent )


def test_init_without_api_key_or_base_url_skips_env():
    """No api_key/base_url → those env vars are not written by the client."""
    os.environ.pop( "OPENAI_BASE_URL", None )
    _make()
    assert "OPENAI_BASE_URL" not in os.environ


def test_init_gates_openai_env_on_flag():
    """Without set_openai_env, api_key/base_url do NOT touch the OpenAI env vars.

    Regression for e515a5c5: constructing a non-OpenAI-protocol arm (e.g. google-gla)
    must not clobber OPENAI_API_KEY/OPENAI_BASE_URL process-global with another
    vendor's credential.
    """
    os.environ.pop( "OPENAI_API_KEY", None )
    os.environ.pop( "OPENAI_BASE_URL", None )
    _make( api_key="gemini-key", base_url="https://generativelanguage.googleapis.com/v1" )
    assert "OPENAI_API_KEY"  not in os.environ
    assert "OPENAI_BASE_URL" not in os.environ


def test_init_sets_openai_env_when_flag_true():
    """set_openai_env=True → api_key/base_url populate the OpenAI-compat env vars."""
    c = _make( api_key="sk-test", base_url="http://host/v1", set_openai_env=True )
    assert os.environ[ "OPENAI_API_KEY" ]  == "sk-test"
    assert os.environ[ "OPENAI_BASE_URL" ] == "http://host/v1"


def test_init_set_openai_env_true_but_no_creds():
    """set_openai_env=True with no api_key/base_url writes nothing (inner guards false)."""
    os.environ.pop( "OPENAI_API_KEY", None )
    os.environ.pop( "OPENAI_BASE_URL", None )
    _make( set_openai_env=True )
    assert "OPENAI_API_KEY"  not in os.environ
    assert "OPENAI_BASE_URL" not in os.environ


def test_init_debug_banner_runs( capsys ):
    """debug=True prints the init banner."""
    _make( debug=True )
    assert "ChatClient" in capsys.readouterr().out


# =========================================================================== #
# run_async — non-streaming
# =========================================================================== #
def test_run_async_non_stream_returns_output():
    """Non-streaming run returns the agent output."""
    c = _make()
    assert asyncio.run( c.run_async( "hello" ) ) == "the response"


def test_run_async_non_stream_prints_metadata_when_debug_verbose( capsys ):
    """debug+verbose prints the perf-metadata summary."""
    c = _make( debug=True, verbose=True )
    asyncio.run( c.run_async( "hello world" ) )
    assert "Chat Summary" in capsys.readouterr().out


def test_run_async_non_stream_no_metadata_when_quiet( capsys ):
    """Without debug+verbose, no metadata summary is printed."""
    c = _make()
    asyncio.run( c.run_async( "hello" ) )
    assert "Chat Summary" not in capsys.readouterr().out


# =========================================================================== #
# run_async — streaming  /  _stream_async
# =========================================================================== #
def test_run_async_stream_verbose_prints_chunks( capsys ):
    """stream + debug+verbose streams chunks and the streaming banner."""
    _FakeAgent.stream_chunks = [ "x", "y", "z" ]
    c = _make( debug=True, verbose=True )
    out = asyncio.run( c.run_async( "prompt", stream=True ) )
    assert out == "xyz"
    captured = capsys.readouterr().out
    assert "Streaming from chat model" in captured
    assert "xyz" in captured.replace( "\n", "" )              # chunks echoed


def test_stream_async_quiet_dot_progress_with_newline( capsys ):
    """Quiet streaming uses dot-progress; 128th chunk triggers a newline."""
    _FakeAgent.stream_chunks = [ "." ] * 130                  # >128 → hits counter%128==0
    c = _make( debug=False )                                  # quiet → else branch
    out = asyncio.run( c.run_async( "prompt", stream=True ) )
    assert out == "." * 130
    assert "." in capsys.readouterr().out


# =========================================================================== #
# run — sync + async context dispatch
# =========================================================================== #
def test_run_sync_context():
    """In a plain sync context, run() spins a fresh loop and returns output."""
    c = _make()
    assert c.run( "hello" ) == "the response"


def test_run_inside_running_loop_uses_threadpool():
    """Called from within a running loop, run() offloads to a worker thread."""
    c = _make()
    async def _driver():
        return c.run( "hello" )                               # must detect loop → threadpool
    assert asyncio.run( _driver() ) == "the response"
