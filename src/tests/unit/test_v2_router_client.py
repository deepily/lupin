#!/usr/bin/env python3
"""
CJ Flow v2 — RouterClient unit tests (plan §1; risk 8). Unit A, second commit.

EXECUTOR: AI — pure import + mocked seams; no live router, no inference, no server.

Coverage: exercises all of `src/cosa/rest/v2/router_client.py` — __init__ (builds
the LlmClientFactory, holds config/debug/verbose) and route() (delegates to the
module-level get_routing_command and returns its result verbatim). Asserts 100%
lines + branches of router_client.py under
  --cov=cosa.rest.v2.router_client --cov-branch --cov-report=term-missing

The delegation guard (test_route_delegates...) is the risk-8 property in test form:
routing goes through the decoupled module-level function with the client's OWN
config + factory — never by constructing a TodoFifoQueue.

Run: PYTHONPATH=src src/cosa/.venv/bin/python -m pytest \
     src/tests/unit/test_v2_router_client.py -v
"""

import unittest
from unittest.mock import MagicMock, patch

import cosa.rest.v2.router_client as rc_mod
from cosa.rest.v2.router_client import RouterClient


def _mk( debug=False, verbose=False ):
    """Build a RouterClient with LlmClientFactory mocked; return (client, cfg, Factory)."""
    cfg = MagicMock()
    with patch.object( rc_mod, "LlmClientFactory", MagicMock() ) as factory:
        client = RouterClient( cfg, debug=debug, verbose=verbose )
    return client, cfg, factory


class TestRouterClientInit( unittest.TestCase ):

    def test_builds_factory_and_holds_config( self ):
        client, cfg, factory = _mk( debug=True, verbose=True )
        self.assertIs( client.config_mgr, cfg )
        self.assertTrue( client.debug )
        self.assertTrue( client.verbose )
        factory.assert_called_once_with( debug=True, verbose=True )
        self.assertIs( client.llm_factory, factory.return_value )

    def test_defaults_quiet( self ):
        client, _cfg, factory = _mk()
        self.assertFalse( client.debug )
        self.assertFalse( client.verbose )
        factory.assert_called_once_with( debug=False, verbose=False )


class TestRouterClientRoute( unittest.TestCase ):

    def test_route_delegates_with_own_config_and_factory( self ):
        client, cfg, _factory = _mk( debug=True, verbose=False )
        with patch.object( rc_mod, "get_routing_command",
                           return_value=( "agent router go to math", "2+2" ) ) as g:
            out = client.route( "what is 2+2" )
        self.assertEqual( out, ( "agent router go to math", "2+2" ) )
        # risk-8 guard: routes via the module-level function with the client's OWN
        # config + factory, never by constructing a TodoFifoQueue.
        g.assert_called_once_with( "what is 2+2", cfg, client.llm_factory,
                                   debug=True, verbose=False )

    def test_route_passes_unknown_through( self ):
        client, _cfg, _factory = _mk()
        with patch.object( rc_mod, "get_routing_command", return_value=( "unknown", "" ) ):
            self.assertEqual( client.route( "gibberish" ), ( "unknown", "" ) )


if __name__ == "__main__":
    unittest.main()
