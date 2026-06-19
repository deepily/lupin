"""
Unit tests for cosa.agents.bug_injector.BugInjector.

BugInjector is an AgentBase subclass that asks an LLM to introduce a bug at a chosen
line. These tests stub AgentBase.__init__ (seeding prompt_template / model / config)
and mock the LLM + XML-parser boundary so no LLM/network runs:

- __init__        — super delegation, prompt_response_dict seeding, prompt build
- _get_prompt     — numbered-source formatting into the template
- run_prompt       — LLM call + parse, then the line-number validation ladder:
                     invalid(-1) / out-of-bounds / zero / valid-injection, plus the
                     debug-on and debug-off trace arms
- restore_from_serialized_state — always NotImplementedError

Created 2026-05-31 (CoSA coverage campaign, remaining agents lane — Tiffany 💍). New file.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from cosa.agents.bug_injector import BugInjector
from cosa.agents.agent_base import AgentBase


def _fake_agent_base_init( self_inner, *args, **kwargs ):
    """AgentBase.__init__ stub seeding the attributes BugInjector relies on."""
    self_inner.prompt_template = "PROMPT:\n{code_with_line_numbers}"
    self_inner.model_name      = "model_x"
    self_inner.config_mgr      = Mock()
    self_inner.routing_command = kwargs.get( "routing_command", "agent router go to bug injector" )
    self_inner.debug           = kwargs.get( "debug", False )
    self_inner.verbose         = kwargs.get( "verbose", False )


class TestBugInjector( unittest.TestCase ):
    """
    Comprehensive unit tests for BugInjector.

    Ensures:
        - Construction seeds the code dict + builds the numbered prompt
        - run_prompt injects on a valid line and rejects every invalid line case
        - The unimplemented restore hook fails loudly
    """

    def _make_injector( self, code=None, debug=False, verbose=False ):
        """Construct a BugInjector with AgentBase.__init__ stubbed."""
        if code is None:
            code = [ "def f():", "    x = 1", "    return x" ]
        with patch.object( AgentBase, "__init__", _fake_agent_base_init ):
            injector = BugInjector( code=code, example="solution = f()", debug=debug, verbose=verbose )
        return injector

    def _run_prompt( self, injector, line_number, bug, response="<xml/>" ):
        """Invoke run_prompt with the LLM + XML-parser boundaries mocked."""
        with patch( "cosa.agents.bug_injector.LlmClientFactory" ) as MockFactory, \
             patch( "cosa.agents.bug_injector.XmlParserFactory" ) as MockXml:
            MockFactory.return_value.get_client.return_value.run.return_value = response
            MockXml.return_value.parse_agent_response.return_value = { "line_number": line_number, "bug": bug }
            buf = io.StringIO()
            with redirect_stdout( buf ):
                result = injector.run_prompt()
        return result

    # ------------------------------------------------------------------ #
    # __init__ / _get_prompt                                              #
    # ------------------------------------------------------------------ #

    def test_init_seeds_code_and_builds_prompt( self ):
        """
        Test construction stores the code/example and builds a numbered prompt.

        Ensures:
            - prompt_response_dict carries the provided code + example
            - The prompt embeds the (line-numbered) source
        """
        injector = self._make_injector( code=[ "a = 1", "b = 2" ] )

        self.assertEqual( injector.prompt_response_dict[ "code" ], [ "a = 1", "b = 2" ] )
        self.assertEqual( injector.prompt_response_dict[ "example" ], "solution = f()" )
        self.assertIn( "PROMPT:", injector.prompt )
        self.assertIn( "a = 1", injector.prompt )

    # ------------------------------------------------------------------ #
    # run_prompt — validation ladder                                      #
    # ------------------------------------------------------------------ #

    def test_run_prompt_valid_injection_debug( self ):
        """
        Test a valid line number injects the bug (debug on → before/after traces).

        Ensures:
            - A blank line is prepended so 1-based line numbers align
            - The bug replaces the targeted line
        """
        injector = self._make_injector( code=[ "a", "b", "c" ], debug=True, verbose=True )

        result = self._run_prompt( injector, line_number="2", bug="BUG!" )

        self.assertEqual( result[ "code" ], [ "", "a", "BUG!", "c" ] )

    def test_run_prompt_valid_injection_no_debug( self ):
        """
        Test the valid-injection path with debug off (covers the debug-off arms).

        Ensures:
            - Injection still occurs without any debug tracing
        """
        injector = self._make_injector( code=[ "a", "b", "c" ], debug=False )

        result = self._run_prompt( injector, line_number="1", bug="OOPS" )

        self.assertEqual( result[ "code" ], [ "", "OOPS", "b", "c" ] )

    def test_run_prompt_invalid_minus_one_leaves_code( self ):
        """
        Test a -1 line number is rejected and the code is left unchanged.

        Ensures:
            - The invalid-response branch fires; code is untouched
        """
        injector = self._make_injector( code=[ "a", "b" ], debug=True )

        result = self._run_prompt( injector, line_number="-1", bug="x" )

        self.assertEqual( result[ "code" ], [ "a", "b" ] )

    def test_run_prompt_out_of_bounds_leaves_code( self ):
        """
        Test an out-of-bounds line number is rejected.

        Ensures:
            - line_number > len(code) → rejected; code unchanged
        """
        injector = self._make_injector( code=[ "a", "b" ] )

        result = self._run_prompt( injector, line_number="99", bug="x" )

        self.assertEqual( result[ "code" ], [ "a", "b" ] )

    def test_run_prompt_zero_line_number_leaves_code( self ):
        """
        Test a zero line number is rejected (line numbers are 1-based).

        Ensures:
            - line_number == 0 → rejected; code unchanged
        """
        injector = self._make_injector( code=[ "a", "b" ] )

        result = self._run_prompt( injector, line_number="0", bug="x" )

        self.assertEqual( result[ "code" ], [ "a", "b" ] )

    # ------------------------------------------------------------------ #
    # restore_from_serialized_state                                       #
    # ------------------------------------------------------------------ #

    def test_restore_from_serialized_state_raises( self ):
        """
        Test restore_from_serialized_state is explicitly unimplemented.

        Ensures:
            - Calling it raises NotImplementedError
        """
        injector = self._make_injector()

        with self.assertRaises( NotImplementedError ):
            injector.restore_from_serialized_state( "/tmp/state.json" )


if __name__ == "__main__":
    unittest.main()
