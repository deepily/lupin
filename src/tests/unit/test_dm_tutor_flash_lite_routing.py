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
from unittest.mock import patch, MagicMock

import pytest

from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.gemini_vertex_client import GeminiVertexClient
from cosa.agents.chat_client import ChatClient
from cosa.agents.completion_client import CompletionClient
from cosa.config.configuration_manager import ConfigurationManager

import cosa.utils.util as du

SPEC_KEY = "dm_tutor/flash_lite"

# The block the GCP VM actually runs under: both cloud compose files set
# config_block_id=Lupin:+Testing-GCS (docker-compose.cloud-gpu.yml:185,
# docker-compose.cloud-test.yml:111). The key itself is written in
# [Lupin: Development] and reaches the VM only by inheritance — exactly the kind
# of thing that reads as obviously true and is worth asserting anyway.
VM_BLOCK_ID = "Lupin:+Testing-GCS"
VM_CLI_ARGS = ( "config_path=/src/conf/lupin-app.ini "
                "splainer_path=/src/conf/lupin-app-splainer.ini "
                f"config_block_id={VM_BLOCK_ID}" )


@pytest.fixture
def real_factory():
    """A factory over the REAL ConfigurationManager. Reset the singleton first so a
    mocked factory from another test module cannot leak in, and reset it after so
    this real instance does not leak out."""
    LlmClientFactory._instance = None
    factory = LlmClientFactory()
    yield factory
    LlmClientFactory._instance = None


@pytest.fixture
def vm_block_factory( monkeypatch ):
    """A factory over the REAL config loaded under the VM's OWN block id. Both
    singletons are reset going in and coming out, and monkeypatch restores the
    original LUPIN_CONFIG_MGR_CLI_ARGS, so no later test inherits a Testing-GCS
    configuration manager."""
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", VM_CLI_ARGS )
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
    LlmClientFactory._instance = None
    factory = LlmClientFactory()
    yield factory
    LlmClientFactory._instance = None
    monkeypatch.undo()
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )


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


def test_flash_lite_resolves_under_the_gcp_vm_config_block( vm_block_factory ):
    """Row ae43a37c part 1: the VM runs [Lupin: Testing-GCS], and the key is written in
    [Lupin: Development]. Inheritance is what carries it across — so assert the shipped
    key resolves to a real GeminiVertexClient under the VM's OWN block, not the dev one.
    Repointing Testing-GCS's inherits= line reds this."""
    client = vm_block_factory.get_client( SPEC_KEY )
    assert isinstance( client, GeminiVertexClient )
    assert client.model_name == "gemini-3.1-flash-lite"
    assert client.location   == "global"


def test_configured_temperature_and_seed_reach_generate_content_under_the_vm_block( vm_block_factory ):
    """Row ae43a37c part 2, the whole chain in one assertion: shipped INI -> factory ->
    client -> the GenerateContentConfig object actually handed to the SDK. Reading the
    config file proves nothing about the call; this inspects the call's own argument.
    google.genai.Client is mocked, so there is no network and no spend."""
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = MagicMock( text="OK" )
    with patch( "google.genai.Client", return_value=fake_client ):
        vm_block_factory.get_client( SPEC_KEY ).run( "hi" )
    _, kwargs = fake_client.models.generate_content.call_args
    cfg = kwargs[ "config" ]
    assert cfg is not None
    assert cfg.temperature       == 0.0                # turned down, and it arrives
    assert cfg.seed              == 20260817           # pinned for low-variance re-runs
    assert cfg.max_output_tokens == 4096               # mapped from max_tokens


# ──────────────────────────────────────────────────────────────────────────────────────
# Row 65073e81 — the ROUTING KEY, not the spec key.
#
# Everything above proves `dm_tutor/flash_lite` EXISTS and builds the right client. None
# of it asks the question that actually broke: which spec key does the tutor CHOOSE when
# it runs on the VM? That is a different key — `llm spec key for dm tutor rewrite` — and
# on 2026-09-25 it read `dm_tutor/phi_4`, inherited from [Lupin: Development], which is
# `vllm://192.168.1.21:3001`. The GCP VM has no route to a 192.168/16 address, so every
# fired DM died in the client, `rewrite_dm` returned None as designed, and the raw body
# was delivered under `tutor_outcome="model_failed"`.
#
# WHY THE SUITE DID NOT CATCH IT. The four tests above all name the spec key by hand.
# A test that hard-codes the key it wants can never notice that production picks a
# different one — so the gap was not thin coverage of the routing logic, it was that
# nothing asked the config which key the tutor would use.
#
# :7999-safe throughout: the factory's vertex arm is lazy and the vllm arm is a URL
# string. No network, no spend, no ADC needed.
# ──────────────────────────────────────────────────────────────────────────────────────

import configparser
import ipaddress
import re
from urllib.parse import urlparse

ROUTING_KEY = "llm spec key for dm tutor rewrite"

# The :8000 test container. It has NO credential of any kind — measured 2026-08-18 and
# recorded in src/rnd/v0.2.0/2026.08.18-phi4-vs-flash-lite-host-rerun.md § Venue, where
# both local containers failed DefaultCredentialsError on an identical live probe. So
# pointing THIS block at Vertex would not fix a silent failure, it would swap one for
# another.
TEST_BLOCK_ID  = "Lupin:+Testing"
TEST_CLI_ARGS  = ( "config_path=/src/conf/lupin-app.ini "
                   "splainer_path=/src/conf/lupin-app-splainer.ini "
                   f"config_block_id={TEST_BLOCK_ID}" )


def _config_under( monkeypatch, cli_args ):
    """Load the REAL shipped INI under one block id, resetting the singleton both ways so
    no other module inherits this manager. No config-seam mock: the shipped key IS the
    subject, exactly as in the fixtures above."""
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", cli_args )
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )


@pytest.fixture
def vm_config( monkeypatch ):
    """The real config under the VM's own block id."""
    cm = _config_under( monkeypatch, VM_CLI_ARGS )
    yield cm
    monkeypatch.undo()
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )


@pytest.fixture
def test_block_config( monkeypatch ):
    """The real config under [Lupin: Testing] — the :8000 container's block."""
    cm = _config_under( monkeypatch, TEST_CLI_ARGS )
    yield cm
    monkeypatch.undo()
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )


def _hosts_in( spec_url ):
    """Every hostname/IP literal in a spec URL. `vllm://192.168.1.21:3001@model` is not a
    URL the stdlib parses as one — the @-suffix is a model id, not userinfo — so the host
    is taken from the text between the scheme and the first @ or /."""
    body = re.sub( r"^[a-z0-9+.-]+://", "", spec_url, flags=re.IGNORECASE )
    body = re.split( r"[@/]", body )[ 0 ]
    return [ h for h in [ body.split( ":" )[ 0 ] ] if h ]


def _is_private_address( host ):
    """True when `host` is an IP literal in a range no GCP VM can route to. The PREDICATE,
    deliberately, not an enumeration of the one address that bit us: any RFC1918 address,
    any loopback, any link-local. `192.168.1.21` is today's answer; a peer moving the vLLM
    box to 10.0.0.5 tomorrow must redden this too."""
    try:
        ip = ipaddress.ip_address( host )
    except ValueError:
        return False                                   # a DNS name — resolvable or not, not our claim
    return ip.is_private or ip.is_loopback or ip.is_link_local


def test_the_vm_block_routes_the_tutor_to_flash_lite_and_not_to_an_unroutable_box( vm_config ):
    """🔴 THE DELIVERABLE of row 65073e81. Ask the config which spec key the tutor will
    CHOOSE under the VM's block, then assert the endpoint that key names is one the VM can
    actually reach.

    Reverting the [Lupin: Testing-GCS] override reds this on the last two assertions
    (proven red 2026-09-25: the key resolves to dm_tutor/phi_4 -> vllm://192.168.1.21:3001,
    so the vertex:// assertion fails and the private-address assertion fails)."""
    spec_key = vm_config.get( ROUTING_KEY, default=None )
    assert spec_key is not None, f"{ROUTING_KEY!r} must resolve under {VM_BLOCK_ID}"

    spec_url = vm_config.get( spec_key, default=None )
    assert spec_url is not None, f"the chosen spec key {spec_key!r} must itself be defined"

    assert spec_url.startswith( "vertex://" )          # ADC over the public internet, reachable from the VM
    assert "flash-lite" in spec_url                    # the arm Rick ruled for, 2026-09-25
    assert not spec_url.startswith( "vllm://" )        # the LAN-only scheme that broke it

    for host in _hosts_in( spec_url ):
        assert not _is_private_address( host ), (
            f"{VM_BLOCK_ID} routes the tutor to {host!r}, which no GCP VM can reach — "
            f"this is the 65073e81 failure returning" )


def test_the_vm_block_resolves_the_routing_key_to_the_same_client_the_spec_tests_pin( vm_block_factory, vm_config ):
    """The two halves joined. The tests above pin `dm_tutor/flash_lite` -> GeminiVertexClient
    by naming the key; this one takes the key the CONFIG chose and puts it through the same
    factory, so the chain is config -> routing key -> spec key -> concrete client with no
    hand-written link in the middle."""
    client = vm_block_factory.get_client( vm_config.get( ROUTING_KEY, default=None ) )
    assert isinstance( client, GeminiVertexClient )
    assert not isinstance( client, ( ChatClient, CompletionClient ) )
    assert client.model_name == "gemini-3.1-flash-lite"
    assert client._client is None                      # lazy — no network, no ADC, no spend


def test_the_override_is_written_in_the_vm_block_itself_and_not_inherited():
    """The override must live in [Lupin: Testing-GCS]'s OWN section. Reads the raw INI with
    configparser — inheritance is exactly what this test must NOT see through.

    WHY THIS IS WORTH A TEST. The natural tidy-up is to move the key up into
    [Lupin: Development] so it is written once. That would repoint the dev box and the :8000
    container at Vertex as well, and NEITHER has a credential (measured 2026-08-18), so the
    tidy-up trades one silent failure for another in two more places. The scope IS the fix."""
    parser = configparser.ConfigParser( interpolation=None )
    parser.read( du.get_project_root() + "/src/conf/lupin-app.ini" )

    own = parser[ "Lupin: Testing-GCS" ]
    assert ROUTING_KEY in own, (
        f"{ROUTING_KEY!r} is not in [Lupin: Testing-GCS]'s own section — if it was moved to a "
        f"parent block, the dev box and the :8000 container now point at Vertex without ADC" )
    assert own[ ROUTING_KEY ].strip() == "dm_tutor/flash_lite"


def test_the_local_test_block_is_not_repointed_at_vertex_because_it_has_no_adc( test_block_config ):
    """[Lupin: Testing] is the :8000 container, which holds no credential — both local
    containers failed an identical live Flash-Lite probe with DefaultCredentialsError on
    2026-08-18. Its tutor key must therefore NOT be a vertex:// spec: the LAN vLLM box is
    reachable from that container's host and Vertex is not, so phi_4 is the correct answer
    there and this override must not spread to it."""
    spec_key = test_block_config.get( ROUTING_KEY, default=None )
    spec_url = test_block_config.get( spec_key, default=None )
    assert spec_url is not None
    assert not spec_url.startswith( "vertex://" ), (
        "[Lupin: Testing] now routes the tutor to Vertex, but the :8000 container has no ADC — "
        "that is a silent model_failed, not a fix" )


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
