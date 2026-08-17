#!/usr/bin/env python3
"""
Landing test for the dm_tutor/flash_lite spec-key routing (bug 4107afe2).

Guards a SILENT failure. Before the key existed, get_client( "dm_tutor/flash_lite" )
did NOT raise — it fell through and returned a CompletionClient, which answers, and
answers well. Tiffany proved the correct routing with an ad-hoc probe that ran once
and vanished; nothing in the suite asserted that the key EXISTS in the shipped config.

WHY THIS IS NOT A DUPLICATE. The routing LOGIC is already covered at
src/cosa/tests/unit/agents/test_llm_client_factory.py:405 — but that test injects the
key through the make_factory fixture, so deleting dm_tutor/flash_lite from lupin-app.ini
tomorrow leaves it green. The genuine gap is a test that reads the REAL
ConfigurationManager with NO mocks on the config seam — that seam (the shipped INI key)
is exactly what breaks silently, so mocking it makes the test vacuous.

Key-free construction (no api_key on the genai client) is already covered by
test_gemini_vertex_client.py::test_run_uses_vertex_mode_with_no_api_key, so it is NOT
re-asserted here. OPENAI_* isolation on the vertex routing path is covered nowhere, so
Tiffany's second hardening assertion is folded in below.

:7999-safe: the genai client is lazy (c._client stays None), so no network, no spend.
"""
import os
from unittest.mock import patch

import pytest

from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.gemini_vertex_client import GeminiVertexClient
from cosa.agents.chat_client import ChatClient
from cosa.agents.completion_client import CompletionClient

SPEC_KEY = "dm_tutor/flash_lite"


@pytest.fixture
def real_factory():
    """A factory over the REAL ConfigurationManager. Reset the singleton first so a
    mocked factory from another test module cannot leak in, and reset it after so
    this real instance does not leak out."""
    LlmClientFactory._instance = None
    factory = LlmClientFactory()
    yield factory
    LlmClientFactory._instance = None


def test_flash_lite_key_ships_and_routes_to_gemini_vertex_client( real_factory ):
    """The deliverable: the REAL config key resolves to a CONCRETE GeminiVertexClient
    and NOT a silent fall-through Chat/CompletionClient. No config-seam mock — the
    shipped lupin-app.ini key is the subject. Deleting or repointing the key reds this
    (proven red 2026-08-17: repointing to a vllm:// spec yields a ChatClient, so the
    isinstance-GeminiVertexClient assertion fails)."""
    client = real_factory.get_client( SPEC_KEY )
    assert isinstance( client, GeminiVertexClient )                    # the type that must win
    assert not isinstance( client, ( ChatClient, CompletionClient ) )  # never the silent fall-through
    assert client.model_name == "gemini-3.1-flash-lite"
    assert client.location   == "global"                              # location recorded, not defaulted
    assert client._client is None                                     # lazy — no network, :7999-safe


def test_flash_lite_routing_does_not_touch_openai_env( real_factory ):
    """Tiffany's hardening 2 (uncovered elsewhere for the vertex path): pre-poison
    OPENAI_* and assert the routing path neither mutates them (the process-global
    leak other vendors carry) nor produces a client holding an api_key — Vertex is
    ADC-only. The vertex:// arm lives in the config-key-exists branch and never enters
    the vendor api-key block, so this must hold by construction."""
    poison = "POISON-would-break-if-used"
    with patch.dict( os.environ, { "OPENAI_API_KEY": poison, "OPENAI_BASE_URL": poison } ):
        client = real_factory.get_client( SPEC_KEY )
        assert os.environ[ "OPENAI_API_KEY" ]  == poison              # not mutated
        assert os.environ[ "OPENAI_BASE_URL" ] == poison              # not mutated
    assert isinstance( client, GeminiVertexClient )
    assert not hasattr( client, "api_key" )                          # ADC-only, no key surface


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
