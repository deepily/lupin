#!/usr/bin/env python3
"""
The VM's agent router model is one it can reach.

[Lupin: Testing-GCS] inherits deepily/ministral_8b_2410_ft_lora from Development, which is
vllm://192.168.1.21:3000. That is a home-LAN address, so a typed /api/v2/ask on the VM hung inside
get_routing_command. These tests read the shipped INI under each block id and ask which
spec the router will pick. No config seam is mocked, and nothing touches the network: the Vertex client is lazy.
"""
import configparser

import pytest

import cosa.utils.util as du
from cosa.agents.chat_client import ChatClient
from cosa.agents.completion_client import CompletionClient
from cosa.agents.gemini_vertex_client import GeminiVertexClient
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.config.configuration_manager import ConfigurationManager

ROUTER_KEY = "llm spec key for agent router"
LAN_ROUTER = "deepily/ministral_8b_2410_ft_lora"


def _reset_config():
    """Drop both singletons so no other module inherits this block's manager."""
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
    LlmClientFactory._instance = None


@pytest.fixture
def config_under( monkeypatch ):
    """Load the real INI under a named block id, and restore the singletons afterwards."""
    def load( block_id ):
        monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS",
                            "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini "
                            f"config_block_id={block_id}" )
        _reset_config()
        return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    yield load
    monkeypatch.undo()
    _reset_config()


def test_the_vm_block_picks_a_vertex_router_spec( config_under ):
    """Under Testing-GCS the router key names a vertex:// spec, not the LAN LoRA."""
    config   = config_under( "Lupin:+Testing-GCS" )
    spec_key = config.get( ROUTER_KEY, default=None )
    spec_url = config.get( spec_key, default=None )

    assert spec_key != LAN_ROUTER
    assert spec_url is not None, f"the chosen router spec key {spec_key!r} must itself be defined"
    assert spec_url.startswith( "vertex://" )


def test_the_vm_router_spec_builds_a_vertex_client( config_under ):
    """The chosen key goes through the factory and comes out as the Vertex client."""
    config = config_under( "Lupin:+Testing-GCS" )
    client = LlmClientFactory().get_client( config.get( ROUTER_KEY, default=None ) )

    assert isinstance( client, GeminiVertexClient )
    assert not isinstance( client, ( ChatClient, CompletionClient ) )
    assert client._client is None


def test_the_override_sits_in_the_vm_block_itself():
    """The override is in the VM block's own section; Development keeps the LoRA."""
    parser = configparser.ConfigParser( interpolation=None )
    parser.read( du.get_project_root() + "/src/conf/lupin-app.ini" )

    assert ROUTER_KEY in parser[ "Lupin: Testing-GCS" ]
    assert parser[ "Lupin: Development" ][ ROUTER_KEY ].strip() == LAN_ROUTER


@pytest.mark.parametrize( "block_id", [ "Lupin:+Development", "Lupin:+Testing" ] )
def test_dev_and_the_local_test_block_keep_the_lan_router( config_under, block_id ):
    """Dev and the :8000 block keep the LAN LoRA, because :8000 has no ADC."""
    config = config_under( block_id )

    assert config.get( ROUTER_KEY, default=None ) == LAN_ROUTER


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
