#!/usr/bin/env python3
"""
The Flash-Lite arm markers, asserted against the code the harness actually calls.

WHERE THE PRIMITIVE LIVES. `cosa.research.phi4_flash_lite_study.arm_markers` — one
definition, imported by both the harness and this file. It started life inside this
test module; Clayton 😎 moved it into the package because `src/tests/` is not
importable, and a second copy would have drifted. Nothing here re-implements it.

WHAT THIS FILE ADDS ON TOP OF THE PRIMITIVE:
  1. the markers hold on a client built through the REAL shipped config key
  2. the check CAN GO RED — the same check on the phi_4 arm raises
  3. the arm the TUTOR actually obtains is the arm it was pointed at, read off a spy
     around the factory rather than off a second client built alongside
  4. M4's static half — the Vertex module cannot read an API key at all
  5. M2's GENUINE read-back, which the construction-only check deliberately does not
     make: `response.model_version` off a real Vertex response

M2's LIMIT, RESTATED HERE BECAUSE IT MATTERS AT THE CALL SITE (Tiffany 💍):
`client.model_name` is the descriptor the factory was handed, so a construction-time
assertion on it compares our input to itself. A green from `check_arm_markers` reads
as "this arm is wired to Vertex", never as "flash-lite is what answered". Only
`test_live_call_reads_the_model_id_back_from_the_service` below can say the latter,
and it costs a paid call, so it is opt-in.

VENUE. Every test here except the live one builds clients and calls nothing: no
network, no credentials, :7999-safe. Measured 2026-08-17: construction succeeds even
inside the credential-free :8000 container, so a harness that only BUILDS the client
looks healthy there and fails at the first body — that container has no ADC
(`DefaultCredentialsError`), which is a compose change, not a test change.

Placed in unit/ though it spans three units (config -> factory -> SDK): the
integration directory's conftest.py:45 is a session-scoped autouse fixture that pings
:8000, so anything living there errors whenever the test container is down — and
these assertions need no server at all.
"""
import os
import re

import pytest

from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.gemini_vertex_client import GeminiVertexClient
from cosa.research.phi4_flash_lite_study.arm_markers import (
    EXPECTED_MODEL,
    VERTEX_HOST,
    ArmNotVerified,
    assert_vertex_arm_markers,
    check_arm_markers,
    read_vertex_arm_markers,
)

FLASH_LITE_KEY = "dm_tutor/flash_lite"
PHI_4_KEY      = "dm_tutor/phi_4"


@pytest.fixture
def real_factory():
    """A factory over the REAL ConfigurationManager — the shipped INI key is the
    subject, so mocking the config seam would make every assertion here vacuous.
    Reset the singleton on both sides so a mocked factory cannot leak in or out."""
    LlmClientFactory._instance = None
    factory = LlmClientFactory()
    yield factory
    LlmClientFactory._instance = None


def test_all_four_markers_hold_on_the_real_sdk_client( real_factory ):
    """Config key -> factory -> wrapper -> google.genai client, with every marker read
    off the SDK object that would carry the call."""
    markers = assert_vertex_arm_markers( real_factory.get_client( FLASH_LITE_KEY ) )
    assert VERTEX_HOST in str( markers[ "endpoint" ] )
    assert markers[ "model_id" ] == EXPECTED_MODEL
    assert markers[ "api_key" ] is None


def test_markers_go_red_on_the_phi_4_fall_through( real_factory ):
    """Prove-it-red control. The phi_4 arm is exactly what a silent fall-through would
    hand us: a client that answers, and answers well, and is not Vertex. A check that
    cannot fail here cannot fail anywhere, and its green would mean nothing."""
    phi_4 = real_factory.get_client( PHI_4_KEY )
    assert not isinstance( phi_4, GeminiVertexClient )
    with pytest.raises( AssertionError, match=r"M1 Vertex endpoint marker" ):
        assert_vertex_arm_markers( phi_4 )


def test_the_harness_gate_refuses_a_non_vertex_arm():
    """The gate the harness calls before row 0. Pointed at the phi_4 spec key while
    told to expect Vertex, it must raise ArmNotVerified rather than pass."""
    with pytest.raises( ArmNotVerified ):
        check_arm_markers( PHI_4_KEY, expect_vertex=True )
    check_arm_markers( PHI_4_KEY,      expect_vertex=False )   # honest expectation: fine
    check_arm_markers( FLASH_LITE_KEY, expect_vertex=True )    # the real arm: fine


@pytest.mark.parametrize( "spec_key,expected_type,expect_vertex", [
    ( FLASH_LITE_KEY, "GeminiVertexClient", True  ),
    ( PHI_4_KEY,      "CompletionClient",   False ),
] )
def test_the_tutor_path_resolves_the_arm_it_was_pointed_at( monkeypatch, spec_key, expected_type, expect_vertex ):
    """The pairing seam, asserted where the study uses it.

    DmTutorAgent reads its arm ONCE at construction (agent_base.py:149 resolves
    `llm spec key for dm tutor rewrite` -> dm_tutor/phi_4) and resolves the client
    later, in run_prompt (agent_base.py:305). So a harness swaps arms by setting
    `agent.model_name` on the INSTANCE — no global config mutation, which is what
    would otherwise leak between arms and run both on one model.

    The factory is wrapped in a spy so the markers are read off THE CLIENT THE TUTOR
    OBTAINED, not off a second one built alongside it. No model is called."""
    from cosa.agents.dm_tutor.agent import DmTutorAgent
    from cosa.agents.completion_client import CompletionClient

    seen     = {}
    original = LlmClientFactory.get_client

    def spy( self, key, *args, **kwargs ):
        client      = original( self, key, *args, **kwargs )
        seen[ key ] = client
        return client

    monkeypatch.setattr( LlmClientFactory, "get_client", spy )
    monkeypatch.setattr( GeminiVertexClient, "run", lambda self, prompt, **kw: "<response></response>" )
    monkeypatch.setattr( CompletionClient,   "run", lambda self, prompt, **kw: "<response></response>" )

    agent            = DmTutorAgent( dm_body="A body long enough to construct with." )
    agent.model_name = spec_key
    agent.rewrite()                                            # fail-closed; the output is not the subject

    client = seen[ spec_key ]
    assert type( client ).__name__ == expected_type, \
        f"arm {spec_key} resolved {type( client ).__name__}, expected {expected_type}"
    if expect_vertex:
        assert_vertex_arm_markers( client )
    else:
        assert read_vertex_arm_markers( client )[ "vertexai" ] is False


def test_module_never_references_an_api_key_resolver():
    """M4's static half: `api_key is None` says a key was not PASSED; this says the
    Vertex module cannot read one at all. Source-level, so no mock can satisfy it."""
    import cosa.agents.gemini_vertex_client as mod
    source = open( mod.__file__, encoding="utf-8" ).read()
    code   = "\n".join( line for line in source.splitlines() if not line.strip().startswith( "#" ) )
    body   = code.split( '"""', 2 )[ -1 ]                      # drop the module docstring
    for banned in ( "get_api_key", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY" ):
        assert not re.search( rf"\b{banned}\b", body ), f"M4 static: module references {banned}"


@pytest.mark.skipif( os.environ.get( "RUN_VERTEX_LIVE" ) != "1",
                     reason="paid Vertex inference — opt in with RUN_VERTEX_LIVE=1 on a host with ADC" )
def test_live_call_reads_the_model_id_back_from_the_service():
    """M2's genuine form, and the ONLY assertion here that the construction-only gate
    cannot make: the id the SERVICE reports having served. A fall-through cannot forge
    `model_version` — the field comes from Vertex or the call does not return.
    Measured 2026-08-17 on the host: 'gemini-3.1-flash-lite', 11 total tokens."""
    LlmClientFactory._instance = None
    client = LlmClientFactory().get_client( FLASH_LITE_KEY )
    try:
        assert_vertex_arm_markers( client )
        response = client._get_client().models.generate_content(
            model    = client.model_name,
            contents = "Reply with the two letters OK and nothing else.",
            config   = client._build_gen_config(),
        )
        assert response.model_version == EXPECTED_MODEL, \
            f"M2 live: service served {response.model_version!r}, expected {EXPECTED_MODEL!r}"
        assert "OK" in response.text
    finally:
        LlmClientFactory._instance = None


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
