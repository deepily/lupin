#!/usr/bin/env python3
"""
persona_normalization.dm_topic_for: the one DM-topic form.

The two gateways, the MCP DM layer and the stop hook all take their topic from it.

Venue: :7999-eligible / local, pure.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_gateway import LupinArbiterGateway
from cosa.agents.heartbeat_poker_commons_gateway import LupinCommonsGateway
from lupin_mcp.cosa_voice_mcp import _derive_dm_topic
from lupin_mcp.persona_normalization import dm_topic_for, persona_slug

CASES = [
    ( "tiberius",       "dm-tiberius" ),
    ( "  Tiberius  ",   "dm-tiberius" ),
    ( "Mr Radio",       "dm-mr_radio" ),
    ( "mr radio",       "dm-mr_radio" ),
    ( "Mr. Radio",      "dm-mr_radio" ),
    ( "María",          "dm-maria" ),
    ( "jean-luc",       "dm-jean_luc" ),
    ( "中文",            "dm-" ),
    ( None,             "dm-" ),
]


@pytest.mark.parametrize( "name, topic", CASES )
def test_the_topic_is_dm_dash_the_underscore_slug( name, topic ):
    assert dm_topic_for( name ) == topic
    assert dm_topic_for( name ) == f"dm-{persona_slug( name, sep='_' )}"


@pytest.mark.parametrize( "name, topic", CASES )
def test_every_caller_gets_the_same_topic( name, topic ):
    assert LupinArbiterGateway.dm_topic_for( name ) == topic
    assert LupinCommonsGateway.dm_topic_for( name ) == topic
    assert _derive_dm_topic( name ) == topic


def test_the_callers_hold_no_second_definition():
    assert LupinArbiterGateway.dm_topic_for is dm_topic_for
    assert LupinCommonsGateway.dm_topic_for is dm_topic_for
    assert _derive_dm_topic is dm_topic_for
