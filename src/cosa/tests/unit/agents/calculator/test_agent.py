"""
Unit tests for cosa.agents.calculator.agent.CalculatorAgent.

CalculatorAgent is an AgentBase subclass that extracts a CalcIntent via LLM, dispatches
to deterministic calc_operations, and falls back to MathAgent for anything it can't
parse. Tests stub AgentBase.__init__ and mock every collaborator (LLM client, intent
extraction/parse, dispatch, voice formatter, find_category/resolve_alias, MathAgent) —
no LLM / network / real agent work.

Covers: __init__, run_prompt (raw on/off), run_prompt_with_fallback (success + failure),
run_code (fallback / unsupported / empty-units / unknown-units / valid-dispatch /
dispatch-error / dispatch-exception), _delegate_to_math_agent, do_all (delegated vs not),
run_formatter, restore_from_serialized_state.

Created 2026-05-31 (CoSA coverage campaign, calculator package — Tiffany 💍). New file.
"""

import unittest
from unittest.mock import Mock, patch

from cosa.agents.calculator.agent import CalculatorAgent
from cosa.agents.agent_base import AgentBase, CodeGenerationFailedException


def _seed_init( self_inner, *args, **kwargs ):
    """AgentBase.__init__ stub seeding what CalculatorAgent relies on."""
    self_inner.prompt_template     = "Q={query}"
    self_inner.model_name          = "model_x"
    self_inner.question            = kwargs.get( "question", "" )
    self_inner.last_question_asked = kwargs.get( "last_question_asked" ) or kwargs.get( "question" ) or "what is 10 km in miles"
    self_inner.debug               = kwargs.get( "debug", False )
    self_inner.verbose             = kwargs.get( "verbose", False )
    self_inner.user_id             = kwargs.get( "user_id", "" )
    self_inner.user_email          = kwargs.get( "user_email", "" )
    self_inner.session_id          = kwargs.get( "session_id", "" )


class TestCalculatorAgent( unittest.TestCase ):
    """Comprehensive unit tests for CalculatorAgent."""

    def _make_agent( self, debug=False ):
        """Construct a CalculatorAgent with AgentBase.__init__ stubbed."""
        with patch.object( AgentBase, "__init__", _seed_init ):
            return CalculatorAgent( question="what is 10 km in miles", debug=debug )

    # ------------------------------------------------------------------ #
    # __init__                                                            #
    # ------------------------------------------------------------------ #

    def test_init_builds_prompt_and_flags( self ):
        """Test construction builds the prompt and initializes intent/flags."""
        agent = self._make_agent( debug=True )

        self.assertEqual( agent.prompt, "Q=what is 10 km in miles" )
        self.assertIsNone( agent.calc_intent )
        self.assertFalse( agent._fallback_to_math )
        self.assertFalse( agent._delegated_to_math )

    # ------------------------------------------------------------------ #
    # run_prompt / run_prompt_with_fallback                               #
    # ------------------------------------------------------------------ #

    def test_run_prompt_parses_intent( self ):
        """Test run_prompt extracts + parses the intent and sets the response dict."""
        agent = self._make_agent( debug=True )
        intent = Mock( operation="convert", confidence="0.9" )

        with patch( "cosa.agents.calculator.agent.LlmClientFactory" ) as MockFactory, \
             patch( "cosa.agents.calculator.agent.extract_calc_intent_xml", return_value="<calc_intent/>" ), \
             patch( "cosa.agents.calculator.agent.CalcIntent" ) as MockCalc:
            MockFactory.return_value.get_client.return_value.run.return_value = "<raw/>"
            MockCalc.from_xml.return_value = intent
            result = agent.run_prompt( include_raw_response=True )

        self.assertIs( agent.calc_intent, intent )
        self.assertEqual( result[ "operation" ], "convert" )
        self.assertEqual( result[ "raw_response" ], "<raw/>" )

    def test_run_prompt_without_raw_response( self ):
        """Test run_prompt omits the raw response when not requested."""
        agent = self._make_agent()
        intent = Mock( operation="mortgage", confidence="0.8" )

        with patch( "cosa.agents.calculator.agent.LlmClientFactory" ) as MockFactory, \
             patch( "cosa.agents.calculator.agent.extract_calc_intent_xml", return_value="<calc_intent/>" ), \
             patch( "cosa.agents.calculator.agent.CalcIntent" ) as MockCalc:
            MockFactory.return_value.get_client.return_value.run.return_value = "<raw/>"
            MockCalc.from_xml.return_value = intent
            result = agent.run_prompt()

        self.assertIsNone( result[ "raw_response" ] )

    def test_run_prompt_with_fallback_success( self ):
        """Test the fallback wrapper returns the parsed dict on success."""
        agent = self._make_agent()
        agent.run_prompt = Mock( return_value={ "operation": "convert" } )

        result = agent.run_prompt_with_fallback()

        self.assertEqual( result, { "operation": "convert" } )
        self.assertFalse( agent._fallback_to_math )

    def test_run_prompt_with_fallback_failure_sets_flag( self ):
        """Test the fallback wrapper traps extraction failure and flags MathAgent."""
        agent = self._make_agent( debug=True )
        agent.run_prompt = Mock( side_effect=ValueError( "no intent" ) )

        result = agent.run_prompt_with_fallback()

        self.assertIsNone( result )
        self.assertTrue( agent._fallback_to_math )
        self.assertIsNone( agent.calc_intent )

    # ------------------------------------------------------------------ #
    # run_code (dispatch + fallback branches)                             #
    # ------------------------------------------------------------------ #

    def test_run_code_fallback_delegates( self ):
        """Test run_code delegates to MathAgent when the fallback flag is set."""
        agent = self._make_agent()
        agent._fallback_to_math   = True
        agent._delegate_to_math_agent = Mock( return_value={ "return_code": 0 } )

        self.assertEqual( agent.run_code()[ "return_code" ], 0 )
        agent._delegate_to_math_agent.assert_called_once()

    def test_run_code_unsupported_delegates( self ):
        """Test an 'unsupported' intent delegates to MathAgent."""
        agent = self._make_agent( debug=True )
        agent.calc_intent = Mock( operation="unsupported" )
        agent._delegate_to_math_agent = Mock( return_value={ "return_code": 0 } )

        agent.run_code()
        agent._delegate_to_math_agent.assert_called_once()

    def test_run_code_convert_empty_units_delegates( self ):
        """Test a convert intent with empty units delegates to MathAgent."""
        agent = self._make_agent( debug=True )
        agent.calc_intent = Mock( operation="convert", from_unit="", to_unit="" )
        agent._delegate_to_math_agent = Mock( return_value={ "return_code": 0 } )

        agent.run_code()
        agent._delegate_to_math_agent.assert_called_once()

    def test_run_code_convert_unknown_units_delegates( self ):
        """Test a convert intent with unrecognized units delegates to MathAgent."""
        agent = self._make_agent( debug=True )
        agent.calc_intent = Mock( operation="convert", from_unit="zorp", to_unit="meter" )
        agent._delegate_to_math_agent = Mock( return_value={ "return_code": 0 } )

        with patch( "cosa.agents.calculator.agent.resolve_alias", side_effect=lambda u: u ), \
             patch( "cosa.agents.calculator.agent.find_category", return_value=( None, None ) ):
            agent.run_code()

        agent._delegate_to_math_agent.assert_called_once()

    def test_run_code_valid_dispatch_success( self ):
        """Test a valid convert intent dispatches and stores the result."""
        agent = self._make_agent()
        agent.calc_intent = Mock( operation="convert", from_unit="km", to_unit="mile" )

        with patch( "cosa.agents.calculator.agent.resolve_alias", side_effect=lambda u: u ), \
             patch( "cosa.agents.calculator.agent.find_category", return_value=( {}, "length" ) ), \
             patch( "cosa.agents.calculator.agent.dispatch", return_value={ "status": "ok", "result": 6.21 } ):
            result = agent.run_code()

        self.assertEqual( result[ "return_code" ], 0 )
        self.assertEqual( result[ "output" ][ "result" ], 6.21 )
        self.assertIsNone( agent.error )

    def test_run_code_dispatch_error_raises( self ):
        """Test a dispatch error-status result raises CodeGenerationFailedException."""
        agent = self._make_agent( debug=True )
        agent.calc_intent = Mock( operation="mortgage" )

        with patch( "cosa.agents.calculator.agent.dispatch", return_value={ "status": "error", "message": "bad" } ):
            with self.assertRaises( CodeGenerationFailedException ):
                agent.run_code()

    def test_run_code_dispatch_exception_raises( self ):
        """Test a dispatch exception is wrapped in CodeGenerationFailedException."""
        agent = self._make_agent( debug=True )
        agent.calc_intent = Mock( operation="mortgage" )

        with patch( "cosa.agents.calculator.agent.dispatch", side_effect=RuntimeError( "boom" ) ):
            with self.assertRaises( CodeGenerationFailedException ):
                agent.run_code()

    # ------------------------------------------------------------------ #
    # _delegate_to_math_agent                                             #
    # ------------------------------------------------------------------ #

    def test_delegate_to_math_agent_copies_results( self ):
        """
        Test delegation runs MathAgent and copies its results back.

        Ensures:
            - answer_conversational / answer / dicts are copied; _delegated flag set
        """
        agent = self._make_agent( debug=True )

        math = Mock()
        math.answer_conversational = "Math says 4"
        math.answer                = "4"
        math.code_response_dict    = { "return_code": 0, "output": "4" }
        math.prompt_response_dict  = { "code": [ "x" ] }

        with patch( "cosa.agents.calculator.agent.MathAgent", return_value=math ):
            result = agent._delegate_to_math_agent()

        self.assertTrue( agent._delegated_to_math )
        self.assertEqual( agent.answer_conversational, "Math says 4" )
        self.assertEqual( result, { "return_code": 0, "output": "4" } )
        math.do_all.assert_called_once()

    # ------------------------------------------------------------------ #
    # do_all                                                              #
    # ------------------------------------------------------------------ #

    def test_do_all_runs_formatter_when_not_delegated( self ):
        """Test do_all runs the formatter when MathAgent did not handle the pipeline."""
        agent = self._make_agent()
        agent.run_prompt_with_fallback = Mock()
        agent.run_code                 = Mock()
        agent.run_formatter            = Mock( side_effect=lambda: setattr( agent, "answer_conversational", "voiced" ) )
        agent._delegated_to_math       = False

        result = agent.do_all()

        agent.run_formatter.assert_called_once()
        self.assertEqual( result, "voiced" )

    def test_do_all_skips_formatter_when_delegated( self ):
        """Test do_all skips the formatter when MathAgent already produced the answer."""
        agent = self._make_agent()
        agent.run_prompt_with_fallback = Mock()
        agent.run_code                 = Mock()
        agent.run_formatter            = Mock()
        agent._delegated_to_math       = True
        agent.answer_conversational    = "delegated answer"

        result = agent.do_all()

        agent.run_formatter.assert_not_called()
        self.assertEqual( result, "delegated answer" )

    # ------------------------------------------------------------------ #
    # run_formatter / restore                                             #
    # ------------------------------------------------------------------ #

    def test_run_formatter_uses_voice_formatter( self ):
        """Test run_formatter formats the result for voice and sets both answer fields."""
        agent = self._make_agent( debug=True )
        agent.code_response_dict = { "output": { "status": "ok", "result": 6.21 } }
        agent.calc_intent        = Mock( operation="convert" )

        with patch( "cosa.agents.calculator.agent.format_result_for_voice", return_value="10 km is 6.21 miles" ):
            result = agent.run_formatter()

        self.assertEqual( result, "10 km is 6.21 miles" )
        self.assertEqual( agent.answer, "10 km is 6.21 miles" )

    def test_restore_from_serialized_state_raises( self ):
        """Test restore_from_serialized_state is explicitly unimplemented."""
        agent = self._make_agent()
        with self.assertRaises( NotImplementedError ):
            agent.restore_from_serialized_state( "/tmp/state.json" )


if __name__ == "__main__":
    unittest.main()
