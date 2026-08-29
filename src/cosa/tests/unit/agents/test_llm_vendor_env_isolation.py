#!/usr/bin/env python3
"""
Cross-client env-isolation tests for the LLM vendor auth/env lane.

INTENT (integration seam, NOT a repeat of the unit suites):
    test_llm_client_factory.py boundary-STUBS ChatClient, so it structurally
    cannot observe what ChatClient.__init__ writes to os.environ. test_chat_client.py
    exercises ChatClient in isolation, so it cannot observe the FACTORY choosing
    to hand every vendor's key/url to ChatClient. This file wires the REAL factory
    to the REAL ChatClient (only pydantic-ai Agent / ModelSettings / TokenCounter
    are boundary-mocked) and asserts the process-global env-var contract ACROSS
    the two units — the exact place the two bugs hide:

      - 7f361ccf (P1): google-gla env-var name (GOOGLE_API_KEY vs hardcoded GEMINI_API_KEY)
      - e515a5c5 (P2): ChatClient sets OPENAI_API_KEY/OPENAI_BASE_URL for EVERY vendor

THE HAZARD THIS FILE EXISTS FOR: OPENAI_API_KEY / OPENAI_BASE_URL are PROCESS-GLOBAL.
A test that passes alone can pass only because a sibling already set the var; a fix
that looks green in isolation can still leak across clients built later in the SAME
process. Every test below isolates os.environ to a per-test copy AND asserts the
cross-client case explicitly: build vendor A, then vendor B, prove B did not inherit
A's credential/endpoint.

ZERO API spend, ZERO network — Agent is a scripted fake; get_api_key is stubbed.
Venue: :7999-eligible (unit-tier mechanics, no persistent write, no vendor call).
"""
import os

import pytest

import cosa.agents.llm_client_factory as factory_mod
from   cosa.agents.llm_client_factory import LlmClientFactory
import cosa.agents.chat_client        as chat_mod


# =========================================================================== #
# Test doubles
# =========================================================================== #
class _FakeConfigMgr:
    """Scripted ConfigurationManager: get() over a values dict (INI overrides)."""
    def __init__( self, values=None, **kw ):
        self._values = values or {}
    def exists( self, key ):
        return key in self._values
    def get( self, key, default=None, return_type=None, silent=False ):
        return self._values.get( key, default )


class _FakeAgent:
    """Scripted stand-in for pydantic_ai.Agent — records nothing, calls nothing."""
    def __init__( self, model_name, model_settings=None ):
        self.model_name = model_name


class _FakeTokenCounter:
    def __init__( self, *a, **k ):
        pass


# =========================================================================== #
# Fixtures
# =========================================================================== #
@pytest.fixture( autouse=True )
def _isolate_and_mock( monkeypatch ):
    """
    Isolate os.environ per test (writes never leak) + reset the factory singleton
    + boundary-mock ONLY the network edge of ChatClient. ChatClient itself is REAL.
    """
    monkeypatch.setattr( LlmClientFactory, "_instance", None )
    monkeypatch.setattr( os, "environ", dict( os.environ ) )
    # Boundary-mock the network edge inside chat_client — ChatClient stays real.
    monkeypatch.setattr( chat_mod, "Agent", _FakeAgent )
    monkeypatch.setattr( chat_mod, "ModelSettings", lambda **k: ( "settings", k ) )
    monkeypatch.setattr( chat_mod, "TokenCounter", _FakeTokenCounter )
    # Stub the key lookup so no real key file is read.
    monkeypatch.setattr( factory_mod.du, "get_api_key", lambda name: f"key-for-{name}" )


@pytest.fixture
def make_factory( monkeypatch ):
    def _build( values=None, **kw ):
        cm = _FakeConfigMgr( values=values )
        monkeypatch.setattr( factory_mod, "ConfigurationManager", lambda **k: cm )
        return LlmClientFactory( **kw )
    return _build


GEMINI_URL = "https://generativelanguage.googleapis.com/v1"


# =========================================================================== #
# P2 (e515a5c5) — ChatClient must not set OPENAI_* for a non-OpenAI vendor
# =========================================================================== #
def test_google_gla_client_does_not_leak_gemini_key_into_openai_env( make_factory ):
    """
    Building a google-gla client must NOT write OPENAI_API_KEY / OPENAI_BASE_URL.
    RED at HEAD: ChatClient.__init__ sets both unconditionally, so OPENAI_API_KEY
    becomes the Gemini key and OPENAI_BASE_URL the Google endpoint.
    """
    f = make_factory()
    os.environ.pop( "OPENAI_API_KEY",  None )
    os.environ.pop( "OPENAI_BASE_URL", None )
    os.environ.pop( "GEMINI_API_KEY",  None )
    os.environ.pop( "GOOGLE_API_KEY",  None )

    f._get_vendor_specific_client( "google-gla:gemini-2.0-flash-lite" )

    assert os.environ.get( "OPENAI_BASE_URL" ) != GEMINI_URL, \
        "google-gla leaked the Google endpoint into OPENAI_BASE_URL"
    assert "OPENAI_API_KEY" not in os.environ, \
        "google-gla leaked a credential into OPENAI_API_KEY"


def test_anthropic_client_does_not_leak_into_openai_env( make_factory ):
    """
    anthropic has no set_openai_env flag → building it must not touch OPENAI_*.
    RED at HEAD for the same unconditional-write reason.
    """
    f = make_factory()
    os.environ.pop( "OPENAI_API_KEY",  None )
    os.environ.pop( "ANTHROPIC_API_KEY", None )

    f._get_vendor_specific_client( "anthropic:claude-3-5-sonnet" )

    assert "OPENAI_API_KEY" not in os.environ, \
        "anthropic leaked a credential into OPENAI_API_KEY"


def test_prebuilt_openai_key_survives_a_later_google_gla_client( make_factory ):
    """
    THE CROSS-CLIENT BLAST RADIUS, stated as a test.
    An OpenAI client is built first (OPENAI_API_KEY = its own key). A google-gla
    client is built LATER in the same process. The Gemini client must NOT clobber
    the standing OpenAI credential.
    RED at HEAD: google-gla's ChatClient overwrites OPENAI_API_KEY with the Gemini key.
    """
    f = make_factory()
    # Simulate an earlier openai client having established the process credential.
    os.environ[ "OPENAI_API_KEY" ]  = "real-openai-key"
    os.environ[ "OPENAI_BASE_URL" ] = "https://api.openai.com/v1"

    f._get_vendor_specific_client( "google-gla:gemini-2.0-flash-lite" )

    assert os.environ[ "OPENAI_API_KEY" ] == "real-openai-key", \
        "a later google-gla client clobbered an earlier openai client's OPENAI_API_KEY"
    assert os.environ[ "OPENAI_BASE_URL" ] == "https://api.openai.com/v1", \
        "a later google-gla client clobbered an earlier openai client's OPENAI_BASE_URL"


# =========================================================================== #
# Positive control — OpenAI-compatible vendors SHOULD still mirror OPENAI_*
# (guards against the fix over-correcting; GREEN now and after)
# =========================================================================== #
def test_groq_still_sets_openai_env_compat( make_factory ):
    """
    groq is OpenAI-compatible (set_openai_env=True) — it MUST still mirror
    OPENAI_API_KEY / OPENAI_BASE_URL. This guards the fix from disabling the
    legitimate compatibility path. The factory itself sets these (not ChatClient),
    so it is green today; it must stay green after the P2 fix.
    """
    f = make_factory()
    os.environ.pop( "GROQ_API_KEY",   None )
    os.environ.pop( "OPENAI_API_KEY", None )

    f._get_vendor_specific_client( "groq:llama-3.1-8b-instant" )

    assert os.environ[ "OPENAI_API_KEY" ]  == "key-for-groq"
    assert os.environ[ "OPENAI_BASE_URL" ] == f.VENDOR_URLS[ "groq" ]


def test_openai_client_after_groq_keeps_its_own_base_url( make_factory ):
    """
    ORDER-DEPENDENT CROSS-CLIENT LEAK — ENDPOINT half (bug 1944766c).
    groq is OpenAI-compatible (set_openai_env=True) → building it points
    OPENAI_BASE_URL at the groq endpoint. openai is THE OpenAI vendor but its
    VENDOR_CONFIG carries NO set_openai_env flag, so after the e515a5c5 gating the
    openai path never (re)sets OPENAI_BASE_URL. Build groq then openai and the
    openai client is left pointed at groq's endpoint.

    pydantic-ai's OpenAIProvider reads OPENAI_BASE_URL EAGERLY in __init__
    (openai.py), so the openai Agent freezes whatever endpoint is in env at its OWN
    construction — a later client cannot repoint it. The observable proxy here
    (final os.environ, no writer after openai) equals what the Agent captured.

    RED at HEAD; GREEN once openai gets set_openai_env=True (probe-verified: the
    openai Agent then captures https://api.openai.com/v1). The flag is the complete
    fix for THIS (endpoint) assertion.
    """
    f = make_factory()
    os.environ.pop( "OPENAI_API_KEY",  None )
    os.environ.pop( "OPENAI_BASE_URL", None )
    os.environ.pop( "GROQ_API_KEY",    None )

    f._get_vendor_specific_client( "groq:llama-3.1-8b-instant" )   # sets OPENAI_BASE_URL = groq url
    f._get_vendor_specific_client( "openai:gpt-4o" )               # must reclaim its OWN endpoint

    assert os.environ[ "OPENAI_BASE_URL" ] == f.VENDOR_URLS[ "openai" ], \
        "openai client inherited groq's stale OPENAI_BASE_URL — order-dependent cross-client leak"


def test_openai_client_after_groq_does_not_inherit_groq_key( make_factory ):
    """
    ORDER-DEPENDENT CROSS-CLIENT LEAK — CREDENTIAL half (bug 1944766c).
    The set_openai_env flag fixes the endpoint but NOT the key: probe-verified that
    with the flag applied, the openai Agent still captures groq's key. The key is
    resolved incorrectly UPSTREAM of the flag — the factory's `if env_var in
    os.environ` branch (llm_client_factory.py:457) reads the compat-mirrored
    OPENAI_API_KEY (groq's key) back as openai's own credential, because
    OPENAI_API_KEY doubles as groq's compat-mirror var AND openai's real key var.

    RED until the upstream key-resolution fix lands; goes GREEN when openai resolves
    its own key (e.g. du.get_api_key("openai")) rather than trusting a possibly
    compat-polluted OPENAI_API_KEY.
    """
    f = make_factory()
    os.environ.pop( "OPENAI_API_KEY",  None )
    os.environ.pop( "OPENAI_BASE_URL", None )
    os.environ.pop( "GROQ_API_KEY",    None )

    f._get_vendor_specific_client( "groq:llama-3.1-8b-instant" )
    f._get_vendor_specific_client( "openai:gpt-4o" )

    assert os.environ[ "OPENAI_API_KEY" ] == "key-for-openai", \
        "openai client inherited groq's stale OPENAI_API_KEY instead of its own credential (flag does not fix this)"


def test_vllm_chat_path_keeps_openai_base_url( make_factory ):
    """
    The vLLM CHAT path (get_client → vllm:// with a chat prompt_format) builds an
    'openai:'-prefixed ChatClient with api_key='EMPTY' and set_openai_env=True
    (llm_client_factory.py:201-210). A local vLLM speaks the OpenAI protocol, so
    OPENAI_BASE_URL MUST point at our own box for pydantic-ai to resolve the model.
    This is the second positive control: the P2 gating must NOT disable this path.
    Green today; must stay green after the fix.
    """
    f = make_factory( values={
        "mymodel"        : "vllm://host:3001@some-local-model",
        "mymodel_params" : { "prompt_format": "json_message" },   # chat mode (not completion)
    } )
    os.environ.pop( "OPENAI_BASE_URL", None )
    os.environ.pop( "OPENAI_API_KEY",  None )

    f.get_client( "mymodel" )

    assert os.environ[ "OPENAI_BASE_URL" ] == "http://host:3001/v1", \
        "the P2 gating broke the vLLM chat path — OPENAI_BASE_URL no longer points at the local box"
    assert os.environ[ "OPENAI_API_KEY" ] == "EMPTY", \
        "the vLLM chat path lost its required placeholder OPENAI_API_KEY"


# =========================================================================== #
# P1 (7f361ccf) — the INI env-var-name map must actually gate the call
# =========================================================================== #
def test_google_gla_ends_up_with_the_provider_consumed_key_var( make_factory ):
    """
    P1 (7f361ccf), verified against the SHIPPED fix. The env-var NAME for a vendor
    is a PROVIDER CONSTANT (pydantic-ai's google-gla provider hardcodes
    GEMINI_API_KEY, google_gla.py:42), not a config axis — so the fix resolves it
    from VENDOR_CONFIG, not from any operator-tunable INI knob. This test asserts
    the OBSERVABLE end-state, not the read mechanism: building google-gla with no
    override must leave GEMINI_API_KEY set (the var the real call consumes) and must
    NOT write GOOGLE_API_KEY (the separate GoogleProvider var the google-gla
    provider never reads). Mechanism-agnostic → green whether the dead INI map is
    read or deleted.
    """
    f = make_factory()
    os.environ.pop( "GOOGLE_API_KEY", None )
    os.environ.pop( "GEMINI_API_KEY", None )

    f._get_vendor_specific_client( "google-gla:gemini-2.0-flash-lite" )

    assert os.environ.get( "GEMINI_API_KEY" ) == "key-for-gemini", \
        "google-gla ended up without the GEMINI_API_KEY that pydantic-ai consumes — the real call would be uncredentialed"
    assert "GOOGLE_API_KEY" not in os.environ, \
        "google-gla wrote GOOGLE_API_KEY (the GoogleProvider var), which the google-gla provider never reads"


def test_misconfigured_google_gla_fails_loudly_naming_gemini_api_key():
    """
    The SAFETY NET behind the P1 fix: if google-gla is ever misconfigured so
    GEMINI_API_KEY is absent (e.g. an operator points the INI at GOOGLE_API_KEY
    again, or the key file is missing), pydantic-ai's real google-gla provider must
    fail LOUDLY with a UserError that NAMES GEMINI_API_KEY — never a silent
    misfire. This pins the provider-side contract the vendor-env fix relies on; if
    pydantic-ai ever changed to fail silently, the fix's diagnosability vanishes.

    Uses the REAL GoogleGLAProvider (no mock) in a clean env. The error fires at
    provider construction (api-key resolution), so ZERO network / ZERO API spend.
    """
    from pydantic_ai.exceptions        import UserError
    from pydantic_ai.providers.google_gla import GoogleGLAProvider

    os.environ.pop( "GEMINI_API_KEY", None )
    os.environ.pop( "GOOGLE_API_KEY", None )   # prove GOOGLE_API_KEY does NOT satisfy google-gla

    with pytest.raises( UserError ) as exc_info:
        GoogleGLAProvider()

    assert "GEMINI_API_KEY" in str( exc_info.value ), \
        "google-gla misconfig did not fail loudly naming GEMINI_API_KEY — the diagnostic is gone"


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
