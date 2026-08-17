#!/usr/bin/env python3
"""
Unit tests for cosa/agents/llm_client_factory.py (LlmClientFactory + AgentWrapper).

Supersedes the legacy infra-framework test (which skipped at collection). All
external dependencies are boundary-mocked at the llm_client_factory module:
    - ConfigurationManager → _FakeConfigMgr (scripted exists()/get())
    - ChatClient / CompletionClient → record-only stubs (no real Agent/LlmCompletion)
    - du.get_api_key → fixed fake key
    - asyncio.get_event_loop (AgentWrapper tests only) → controlled loop
The singleton (_instance) is reset before each test. os.environ is isolated to a
per-test copy so API-key writes never leak. ZERO API spend, ZERO network.
"""
import asyncio
import os

import pytest

import cosa.agents.llm_client_factory as factory_mod
from cosa.agents.llm_client_factory import LlmClientFactory


# =========================================================================== #
# Test doubles
# =========================================================================== #
class _FakeConfigMgr:
    """Scripted ConfigurationManager: exists() + get() over a values dict."""
    def __init__( self, exists_keys=None, values=None, **kw ):
        self._exists = set( exists_keys or [] )
        self._values = values or {}
    def exists( self, key ):
        return key in self._exists
    def get( self, key, default=None, return_type=None, silent=False ):
        return self._values.get( key, default )


class _StubChat:
    instances = []
    def __init__( self, **kwargs ):
        self.kwargs = kwargs
        _StubChat.instances.append( self )


class _StubCompletion:
    instances = []
    def __init__( self, **kwargs ):
        self.kwargs = kwargs
        _StubCompletion.instances.append( self )


@pytest.fixture( autouse=True )
def _reset_singleton( monkeypatch ):
    """Reset the factory singleton + isolate env + stub clients/config/api-key."""
    monkeypatch.setattr( LlmClientFactory, "_instance", None )
    monkeypatch.setattr( os, "environ", dict( os.environ ) )
    _StubChat.instances       = []
    _StubCompletion.instances = []
    monkeypatch.setattr( factory_mod, "ChatClient", _StubChat )
    monkeypatch.setattr( factory_mod, "CompletionClient", _StubCompletion )
    monkeypatch.setattr( factory_mod.du, "get_api_key", lambda name: f"key-for-{name}" )


@pytest.fixture
def make_factory( monkeypatch ):
    def _build( exists_keys=None, values=None, **kw ):
        cm = _FakeConfigMgr( exists_keys=exists_keys, values=values )
        monkeypatch.setattr( factory_mod, "ConfigurationManager", lambda **k: cm )
        return LlmClientFactory( **kw )
    return _build


# =========================================================================== #
# singleton  /  __new__  /  __init__
# =========================================================================== #
def test_singleton_returns_same_instance( make_factory ):
    """Repeated construction returns the same singleton object."""
    f1 = make_factory()
    f2 = LlmClientFactory()
    assert f1 is f2


def test_init_runs_only_once( make_factory ):
    """__init__ is a no-op on the already-initialized singleton."""
    f1 = make_factory()
    original_cfg = f1.config_mgr
    LlmClientFactory( debug=True )                            # second init → early return
    assert f1.config_mgr is original_cfg


def test_init_loads_vendor_config( make_factory ):
    """__init__ populates vendor URL + default-param maps (env-var NAME lives in VENDOR_CONFIG)."""
    f = make_factory()
    assert f.VENDOR_URLS[ "openai" ] == "https://api.openai.com/v1"
    assert f.VENDOR_CONFIG[ "openai" ][ "env_var" ] == "OPENAI_API_KEY"
    assert f.CLIENT_DEFAULT_PARAMS[ "temperature" ] == "0.7"


# =========================================================================== #
# _load_vendor_urls override path
# =========================================================================== #
def test_vendor_urls_honor_ini_overrides( make_factory ):
    """INI values override the hardcoded vendor URL defaults (URL is a per-deployment axis)."""
    f = make_factory( values={ "llm vendor url openai": "http://override/v1" } )
    assert f.VENDOR_URLS[ "openai" ] == "http://override/v1"


# =========================================================================== #
# get_client — config-key path
# =========================================================================== #
def test_get_client_unknown_key_delegates_to_vendor( make_factory, capsys ):
    """A key absent from config routes to the vendor-specific path."""
    f = make_factory()                                       # no exists keys
    client = f.get_client( "groq:llama-3.3-70b" )
    assert isinstance( client, _StubChat )
    assert "not found in config_mgr" in capsys.readouterr().out


def test_get_client_config_vllm_completion_mode( make_factory ):
    """A vllm:// spec with a completion prompt_format builds a CompletionClient."""
    f = make_factory(
        exists_keys=[ "mymodel" ],
        values={
            "mymodel"        : "vllm://192.168.1.21:3001@Qwen/Qwen3-4B",
            "mymodel_params" : { "prompt_format": "instruction_completion", "stream": False },
            "model tokenizer map" : {},
            "prompt format default" : "json_message",
        },
    )
    client = f.get_client( "mymodel", debug=True, verbose=True )
    assert isinstance( client, _StubCompletion )
    assert client.kwargs[ "base_url" ] == "http://192.168.1.21:3001/v1/completions"
    assert client.kwargs[ "model_name" ] == "Qwen/Qwen3-4B"


def test_get_client_config_vllm_chat_mode( make_factory ):
    """A vllm:// spec with a chat prompt_format builds a ChatClient with /v1."""
    f = make_factory(
        exists_keys=[ "mymodel" ],
        values={
            "mymodel"        : "vllm://host:3001@some-model",
            "mymodel_params" : { "prompt_format": "json_message" },
        },
    )
    client = f.get_client( "mymodel" )
    assert isinstance( client, _StubChat )
    assert client.kwargs[ "base_url" ] == "http://host:3001/v1"


def test_get_client_config_plain_chat_model( make_factory ):
    """A non-vllm spec builds a ChatClient using the raw model spec."""
    f = make_factory(
        exists_keys=[ "mymodel" ],
        values={ "mymodel": "openai:gpt-4o", "mymodel_params": {} },
    )
    client = f.get_client( "mymodel" )
    assert isinstance( client, _StubChat )
    assert client.kwargs[ "model_name" ] == "openai:gpt-4o"


# =========================================================================== #
# _parse_model_descriptor
# =========================================================================== #
def test_parse_descriptor_colon( make_factory ):
    """'vendor:model' splits on the colon, lowercasing the vendor."""
    f = make_factory()
    assert f._parse_model_descriptor( "Groq:Llama-3" ) == ( "groq", "Llama-3" )


def test_parse_descriptor_legacy_deepily_prefix( make_factory ):
    """'llm_deepily_*' maps to the deepily vendor."""
    f = make_factory()
    assert f._parse_model_descriptor( "llm_deepily_foo" ) == ( "deepily", "llm_deepily_foo" )


def test_parse_descriptor_slash_unknown_vendor_defaults_vllm( make_factory ):
    """A slash whose left side is not a vendor → vLLM, no warning."""
    f = make_factory()
    assert f._parse_model_descriptor( "Qwen/Qwen3-4B" ) == ( "vllm", "Qwen/Qwen3-4B" )


def test_parse_descriptor_slash_known_vendor_warns( make_factory, capsys ):
    """A slash whose left side IS a vendor → vLLM + a deprecation warning."""
    f = make_factory()
    result = f._parse_model_descriptor( "openai/gpt-4" )
    assert result == ( "vllm", "openai/gpt-4" )
    assert "DEPRECATION WARNING" in capsys.readouterr().out


def test_parse_descriptor_plain_defaults_vllm( make_factory ):
    """A bare name (no colon, no slash) defaults to vLLM."""
    f = make_factory()
    assert f._parse_model_descriptor( "plainmodel" ) == ( "vllm", "plainmodel" )


# =========================================================================== #
# _get_vendor_specific_client
# =========================================================================== #
def test_vendor_client_unsupported_raises( make_factory ):
    """An unknown vendor raises ValueError."""
    f = make_factory()
    with pytest.raises( ValueError, match="Unsupported vendor" ):
        f._get_vendor_specific_client( "nope:model" )


def test_vendor_client_chat_env_key_from_environment( make_factory ):
    """A chat vendor whose env-var is trusted (nobody else writes it) uses the env value."""
    f = make_factory()
    os.environ[ "ANTHROPIC_API_KEY" ] = "env-key"
    client = f._get_vendor_specific_client( "anthropic:claude-3", debug=True )
    assert isinstance( client, _StubChat )
    assert client.kwargs[ "model_name" ] == "anthropic:claude-3"
    assert client.kwargs[ "api_key" ] == "env-key"


def test_vendor_client_openai_ignores_shared_env_key( make_factory ):
    """openai's env var doubles as the shared compat target, so it resolves its OWN key fresh.

    Even with OPENAI_API_KEY already set process-global (e.g. a groq compat-write), openai
    must NOT adopt it — it fetches key-for-openai via du.get_api_key. Guards the api_key half
    of the cross-client leak Arnold's isolation test asserts.
    """
    f = make_factory()
    os.environ[ "OPENAI_API_KEY" ] = "leaked-from-another-vendor"
    client = f._get_vendor_specific_client( "openai:gpt-4", debug=True )
    assert client.kwargs[ "api_key" ] == "key-for-openai"          # own key, not the leaked env value
    assert os.environ[ "OPENAI_API_KEY" ] == "key-for-openai"      # and it reclaims the shared var


def test_vendor_client_chat_env_key_via_get_api_key( make_factory ):
    """A chat vendor with no env-var falls back to du.get_api_key."""
    f = make_factory()
    os.environ.pop( "ANTHROPIC_API_KEY", None )
    client = f._get_vendor_specific_client( "anthropic:claude-3", debug=True )
    assert client.kwargs[ "api_key" ] == "key-for-claude"     # from stubbed get_api_key
    assert os.environ[ "ANTHROPIC_API_KEY" ] == "key-for-claude"


def test_vendor_client_set_openai_env_compat( make_factory ):
    """A vendor with set_openai_env=True also mirrors OPENAI_API_KEY/BASE_URL."""
    f = make_factory()
    os.environ.pop( "GROQ_API_KEY", None )
    f._get_vendor_specific_client( "groq:llama-3", debug=True )
    assert os.environ[ "OPENAI_API_KEY" ] == "key-for-groq"
    assert os.environ[ "OPENAI_BASE_URL" ] == f.VENDOR_URLS[ "groq" ]


def test_vendor_client_env_var_name_from_vendor_config( make_factory ):
    """The env-var NAME comes from VENDOR_CONFIG (a provider constant), and google-gla → GEMINI_API_KEY.

    Regression for 7f361ccf (fix b): the env-var name is NOT an INI knob. google-gla's
    provider hardcodes GEMINI_API_KEY, so that is the name the factory writes.
    """
    f = make_factory()
    os.environ.pop( "GEMINI_API_KEY", None )
    client = f._get_vendor_specific_client( "google-gla:gemini-2.0", debug=True )
    assert isinstance( client, _StubChat )
    assert client.kwargs[ "api_key" ] == "key-for-gemini"
    assert os.environ[ "GEMINI_API_KEY" ] == "key-for-gemini"


def test_vendor_client_missing_key_raises_readable_error( make_factory, monkeypatch ):
    """A missing key file (du.get_api_key → None) raises a readable auth error, not TypeError.

    Regression for 7f361ccf near-miss: `os.environ[env_var] = None` raised an opaque
    TypeError. It must fail with a ValueError naming the vendor + env var + key file.
    """
    f = make_factory()
    monkeypatch.setattr( factory_mod.du, "get_api_key", lambda name: None )
    os.environ.pop( "GEMINI_API_KEY", None )
    with pytest.raises( ValueError, match="No API key for vendor 'google-gla'" ):
        f._get_vendor_specific_client( "google-gla:gemini-2.0" )


def test_vendor_client_local_vllm_completion( make_factory ):
    """A local vLLM vendor builds a CompletionClient with /completions appended."""
    f = make_factory()
    client = f._get_vendor_specific_client( "vllm:Qwen/Qwen3-4B", debug=True )
    assert isinstance( client, _StubCompletion )
    assert client.kwargs[ "base_url" ].endswith( "/completions" )
    assert client.kwargs[ "prompt_format" ] == "instruction_completion"


def test_vendor_client_nonlocal_completion_branch( make_factory, monkeypatch ):
    """A (synthetic) non-local completion vendor exercises the api_key completion branch.

    No such vendor ships in VENDOR_CONFIG today (vllm/deepily are the only completion
    vendors and both take the local branch), so we inject one to drive the otherwise
    unreachable non-local completion path — proving it constructs a CompletionClient
    with the resolved api_key.
    """
    f = make_factory()
    monkeypatch.setitem( f.VENDOR_CONFIG, "acme",
                         { "env_var": "ACME_API_KEY", "key_name": "acme", "client_type": "completion" } )
    f.VENDOR_URLS[ "acme" ] = "https://acme.example/v1"
    os.environ.pop( "ACME_API_KEY", None )
    client = f._get_vendor_specific_client( "acme:big-model", debug=True )
    assert isinstance( client, _StubCompletion )
    assert client.kwargs[ "api_key" ] == "key-for-acme"
    assert client.kwargs[ "base_url" ] == "https://acme.example/v1"


# =========================================================================== #
# AgentWrapper
# =========================================================================== #
class _WrapResult:
    def __init__( self, data ): self.data = data


class _FakeWrapAgent:
    def __init__( self, result=None, raises=None ):
        self._result = result
        self._raises = raises
    async def run( self, prompt, **kw ):
        if self._raises is not None:
            raise self._raises
        return self._result


def _patch_loop( monkeypatch, raise_get=False ):
    """Control AgentWrapper's event-loop acquisition deterministically."""
    if raise_get:
        monkeypatch.setattr( factory_mod.asyncio, "get_event_loop",
                             lambda: ( _ for _ in () ).throw( RuntimeError( "no loop" ) ) )
    else:
        loop = asyncio.new_event_loop()
        monkeypatch.setattr( factory_mod.asyncio, "get_event_loop", lambda: loop )


def test_agentwrapper_init_stores_agent():
    """AgentWrapper stores its agent + debug flag."""
    agent = _FakeWrapAgent( result="x" )
    w = LlmClientFactory.AgentWrapper( agent, debug=True )
    assert w.agent is agent and w.debug is True


def test_agentwrapper_run_returns_data_attr( monkeypatch, capsys ):
    """run() returns response.data when the response wraps it (debug echoes)."""
    _patch_loop( monkeypatch )
    w = LlmClientFactory.AgentWrapper( _FakeWrapAgent( result=_WrapResult( "wrapped" ) ), debug=True )
    assert w.run( "hi" ) == "wrapped"
    assert "AgentWrapper" in capsys.readouterr().out


def test_agentwrapper_run_returns_response_when_no_data_attr( monkeypatch ):
    """run() returns the response directly when it has no .data attribute."""
    _patch_loop( monkeypatch )
    w = LlmClientFactory.AgentWrapper( _FakeWrapAgent( result="plain" ) )
    assert w.run( "hi" ) == "plain"


def test_agentwrapper_run_creates_loop_when_none( monkeypatch ):
    """When get_event_loop raises, run() creates a fresh loop and proceeds."""
    _patch_loop( monkeypatch, raise_get=True )
    created = {}
    real_new = asyncio.new_event_loop
    def _new():
        loop = real_new(); created[ "loop" ] = loop; return loop
    monkeypatch.setattr( factory_mod.asyncio, "new_event_loop", _new )
    monkeypatch.setattr( factory_mod.asyncio, "set_event_loop", lambda loop: None )
    w = LlmClientFactory.AgentWrapper( _FakeWrapAgent( result="made-loop" ) )
    assert w.run( "hi" ) == "made-loop"
    assert "loop" in created


def test_agentwrapper_run_reraises_on_error( monkeypatch, capsys ):
    """run() prints (debug) and re-raises exceptions from the agent."""
    _patch_loop( monkeypatch )
    w = LlmClientFactory.AgentWrapper( _FakeWrapAgent( raises=ValueError( "boom" ) ), debug=True )
    with pytest.raises( ValueError, match="boom" ):
        w.run( "hi" )
    assert "Error in AgentWrapper.run" in capsys.readouterr().out


def test_agentwrapper_run_reraises_quietly_when_no_debug( monkeypatch, capsys ):
    """With debug=False, run() re-raises without printing the error (branch 377->379)."""
    _patch_loop( monkeypatch )
    w = LlmClientFactory.AgentWrapper( _FakeWrapAgent( raises=ValueError( "boom" ) ), debug=False )
    with pytest.raises( ValueError, match="boom" ):
        w.run( "hi" )
    assert "Error in AgentWrapper.run" not in capsys.readouterr().out
