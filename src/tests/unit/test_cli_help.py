#!/usr/bin/env python3
"""
Unit tests for cli_help.py — the registry-generated --help surface (design §4,
phase 3). Covers build_parser (required + optional arms) and run_help_for_module
(found → --help exits 0, found → valid args returns, unknown module → raises).

Run: PYTHONPATH=src src/cosa/.venv/bin/python -m pytest \
     src/tests/unit/test_cli_help.py -v
"""

import argparse
import unittest

from cosa.agents.runtime_argument_expeditor.cli_help import build_parser, run_help_for_module


class TestBuildParser( unittest.TestCase ):

    def test_build_parser_names_required_and_optional_args( self ):
        # deep research declares required 'query' and optional mapped args (budget,
        # audience, …) — exercises both the required=True and required=False arms.
        parser = build_parser( "agent router go to deep research" )
        self.assertIsInstance( parser, argparse.ArgumentParser )
        help_text = parser.format_help().lower()
        self.assertIn( "query", help_text )       # the declared required arg is named
        self.assertIn( "usage", help_text )


class TestRunHelpForModule( unittest.TestCase ):

    def test_help_flag_exits_zero( self ):
        with self.assertRaises( SystemExit ) as ctx:
            run_help_for_module( "cosa.agents.claude_code", [ "--help" ] )
        self.assertEqual( ctx.exception.code, 0 )

    def test_valid_args_returns_without_raising( self ):
        # A satisfied required arg parses cleanly and returns (covers the return arm).
        self.assertIsNone( run_help_for_module( "cosa.agents.claude_code", [ "--prompt", "do a thing" ] ) )

    def test_unknown_module_raises_systemexit( self ):
        with self.assertRaises( SystemExit ):
            run_help_for_module( "cosa.agents.__no_such_package__" )


if __name__ == "__main__":
    unittest.main()
