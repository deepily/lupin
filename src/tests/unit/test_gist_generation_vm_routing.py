#!/usr/bin/env python3
"""
The VM's gist model is one it can reach.

[Lupin: Testing-GCS] inherits kaitchup/phi_4_14b from Development, which is vllm://192.168.1.21:3001.
That is a home-LAN address. A connect from lupin-rest-cloud-gpu timed out after 8 s. So every
gist-cache miss on the VM waited on a host with no route. These tests read the shipped INI under the
VM's block id and ask which spec the Gister will pick. No config seam is mocked.

Nothing here touches the network: the Vertex client is lazy, so no ADC and no spend.
"""
import configparser
import ipaddress
import re

import pytest

import cosa.utils.util as du
from cosa.agents.chat_client import ChatClient
from cosa.agents.completion_client import CompletionClient
from cosa.agents.gemini_vertex_client import GeminiVertexClient
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.config.configuration_manager import ConfigurationManager

GIST_KEY = "llm spec key for gist generation"


def _cli_args( block_id ):
    """The config arguments the compose files hand a container running under one block."""
    return ( "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini "
             f"config_block_id={block_id}" )


def _reset_config():
    """Drop both singletons so no other module inherits this block's manager."""
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
    LlmClientFactory._instance = None


@pytest.fixture
def config_under( monkeypatch ):
    """Load the real INI under a named block id, and restore the singletons afterwards."""
    def load( block_id ):
        monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", _cli_args( block_id ) )
        _reset_config()
        return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    yield load
    monkeypatch.undo()
    _reset_config()


def _host_of( spec_url ):
    """The host literal between the scheme and the first @ or /, minus any port."""
    body = re.sub( r"^[a-z0-9+.-]+://", "", spec_url, flags=re.IGNORECASE )
    return re.split( r"[@/]", body )[ 0 ].split( ":" )[ 0 ]


def _is_unroutable( host ):
    """True for an IP literal no GCP VM can reach: private, loopback or link-local."""
    try:
        ip = ipaddress.ip_address( host )
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def test_the_vm_block_picks_a_gist_spec_the_vm_can_reach( config_under ):
    """Under Testing-GCS the gist key names a vertex:// spec, not the LAN vLLM box."""
    config   = config_under( "Lupin:+Testing-GCS" )
    spec_key = config.get( GIST_KEY, default=None )
    spec_url = config.get( spec_key, default=None )

    assert spec_url is not None, f"the chosen gist spec key {spec_key!r} must itself be defined"
    assert spec_url.startswith( "vertex://" )
    assert not _is_unroutable( _host_of( spec_url ) )


def test_the_vm_gist_spec_builds_a_vertex_client( config_under ):
    """The key the config chose goes through the factory and comes out as the Vertex client."""
    config = config_under( "Lupin:+Testing-GCS" )
    client = LlmClientFactory().get_client( config.get( GIST_KEY, default=None ) )

    assert isinstance( client, GeminiVertexClient )
    assert not isinstance( client, ( ChatClient, CompletionClient ) )
    assert client._client is None


def test_the_override_sits_in_the_vm_block_itself():
    """The override is in the VM block's own section, not inherited.

    Moving it up into Development would repoint dev and :8000, which cannot reach Vertex.
    """
    parser = configparser.ConfigParser( interpolation=None )
    parser.read( du.get_project_root() + "/src/conf/lupin-app.ini" )

    assert GIST_KEY in parser[ "Lupin: Testing-GCS" ]
    assert GIST_KEY not in parser[ "Lupin: Development" ] or parser[ "Lupin: Development" ][ GIST_KEY ].strip() == "kaitchup/phi_4_14b"


@pytest.mark.parametrize( "block_id", [ "Lupin:+Development", "Lupin:+Testing" ] )
def test_dev_and_the_local_test_block_keep_the_lan_model( config_under, block_id ):
    """Dev and the :8000 block keep the LAN model, because :8000 has no ADC."""
    config   = config_under( block_id )
    spec_url = config.get( config.get( GIST_KEY, default=None ), default=None )

    assert spec_url.startswith( "vllm://" )


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
