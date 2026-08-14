#!/usr/bin/env python3
"""
Unit tests for the module-level `get_routing_command` function in
`cosa.rest.todo_fifo_queue`, extracted from `TodoFifoQueue._get_routing_command`
(v1 behavior-preserving refactor, store row e010d5e2).

Covers the module function directly (success, args-None, XML-parse-error,
generic-error, and the debug/verbose print branches) plus the thin shim's
delegation. NO real LLM / network / filesystem — every seam is mocked.

Run: PYTHONPATH=src src/cosa/.venv/bin/python -m pytest \
     src/cosa/tests/unit/rest/test_get_routing_command_module_fn.py -v
"""

import unittest
from unittest.mock import MagicMock, patch

import cosa.rest.todo_fifo_queue as tfq
from cosa.rest.todo_fifo_queue import get_routing_command


def _cfg( path="/src/conf/prompts/router.txt", spec="spec-router" ):
    """Build a config_mgr mock returning the router prompt path + spec key."""
    data = {
        "prompt template for agent router" : path,
        "llm spec key for agent router"    : spec,
    }
    m = MagicMock()
    m.get.side_effect = lambda key, default=None, **kw: data.get( key, default )
    return m


def _llm_factory( response ):
    """Build an llm_factory mock whose client.run returns `response`."""
    client  = MagicMock()
    client.run.return_value = response
    factory = MagicMock()
    factory.get_client.return_value = client
    return factory


class TestGetRoutingCommandModuleFn( unittest.TestCase ):

    def _run( self, response, *, debug=False, verbose=False, from_xml=None, from_xml_raises=None ):
        cfg     = _cfg()
        factory = _llm_factory( response )
        with patch.object( tfq.du, "get_file_as_string", return_value="tmpl {voice_command}" ), \
             patch.object( tfq.du, "get_project_root",   return_value="/p" ):
            if from_xml_raises is not None:
                with patch.object( tfq.CommandResponse, "from_xml", side_effect=from_xml_raises ):
                    return get_routing_command( "what is 2+2", cfg, factory, debug=debug, verbose=verbose )
            with patch.object( tfq.CommandResponse, "from_xml", return_value=from_xml ):
                return get_routing_command( "what is 2+2", cfg, factory, debug=debug, verbose=verbose )

    def test_success_debug_verbose( self ):
        parsed = MagicMock( command="agent router go to math", args="2+2" )
        cmd, args = self._run( "<xml/>", debug=True, verbose=True, from_xml=parsed )
        self.assertEqual( cmd,  "agent router go to math" )
        self.assertEqual( args, "2+2" )

    def test_success_quiet( self ):
        parsed = MagicMock( command="agent router go to weather", args="today" )
        cmd, args = self._run( "<xml/>", debug=False, verbose=False, from_xml=parsed )
        self.assertEqual( ( cmd, args ), ( "agent router go to weather", "today" ) )

    def test_args_none_coerced_to_empty_string( self ):
        parsed = MagicMock( command="agent router go to math", args=None )
        cmd, args = self._run( "<xml/>", from_xml=parsed )
        self.assertEqual( args, "" )

    def test_debug_only_not_verbose( self ):
        # debug True + verbose False exercises the `if debug and verbose` False side
        # while keeping the plain `if debug` prints active.
        parsed = MagicMock( command="c", args="a" )
        cmd, args = self._run( "<xml/>", debug=True, verbose=False, from_xml=parsed )
        self.assertEqual( ( cmd, args ), ( "c", "a" ) )

    def test_xml_parsing_error_debug( self ):
        cmd, args = self._run( "junk", debug=True, from_xml_raises=tfq.XMLParsingError( "bad xml" ) )
        self.assertEqual( ( cmd, args ), ( "unknown", "" ) )

    def test_xml_parsing_error_quiet( self ):
        cmd, args = self._run( "junk", debug=False, from_xml_raises=tfq.XMLParsingError( "bad xml" ) )
        self.assertEqual( ( cmd, args ), ( "unknown", "" ) )

    def test_generic_error_debug( self ):
        cmd, args = self._run( "junk", debug=True, from_xml_raises=RuntimeError( "boom" ) )
        self.assertEqual( ( cmd, args ), ( "unknown", "" ) )

    def test_generic_error_quiet( self ):
        cmd, args = self._run( "junk", debug=False, from_xml_raises=RuntimeError( "boom" ) )
        self.assertEqual( ( cmd, args ), ( "unknown", "" ) )

    def test_shim_delegates_with_queue_dependencies( self ):
        # The method shim must forward the queue's config/factory/debug/verbose
        # to the module function unchanged, and return its result verbatim.
        q             = MagicMock()
        q.config_mgr  = "CFG"
        q.llm_factory = "LLM"
        q.debug       = True
        q.verbose     = False
        with patch.object( tfq, "get_routing_command", return_value=( "cmd", "args" ) ) as gf:
            out = tfq.TodoFifoQueue._get_routing_command( q, "hello" )
        self.assertEqual( out, ( "cmd", "args" ) )
        gf.assert_called_once_with( "hello", "CFG", "LLM", debug=True, verbose=False )


if __name__ == "__main__":
    unittest.main()
