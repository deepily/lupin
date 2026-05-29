#!/usr/bin/env python3
"""
CalculatorAgent — Intent-dispatched deterministic calculations.

Connects the COSA voice pipeline to pure Python calculator operations via
LLM-based intent extraction. Overrides run_prompt(), run_code(),
run_formatter(), and do_all() for graceful MathAgent delegation on
unsupported operations.

Architecture:
    - run_prompt(): Calls LLM, extracts <calc_intent> XML, parses into CalcIntent
    - run_code(): Dispatches CalcIntent to calc_operations (pure Python, no sandbox)
    - run_formatter(): Formats result for TTS voice output (no extra LLM call)
"""

import cosa.utils.util as du

from cosa.agents.agent_base import AgentBase, CodeGenerationFailedException
from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.agents.math_agent import MathAgent

from cosa.agents.calculator.xml_models import CalcIntent
from cosa.agents.calculator.dispatcher import dispatch, format_result_for_voice, extract_calc_intent_xml
from cosa.agents.calculator.conversion_tables import resolve_alias, find_category


class CalculatorAgent( AgentBase ):
    """
    Agent for voice-driven deterministic calculations.

    Extracts intent from natural language via configured LLM, dispatches to
    pure Python calc_operations functions, and formats results for TTS.
    Handles unit conversions, price comparisons, and mortgage calculations.

    Requires:
        - Configuration keys in lupin-app.ini:
            - llm spec key for agent router go to calculator
            - prompt template for agent router go to calculator

    Ensures:
        - do_all() works unchanged with RunningFifoQueue._handle_base_agent()
        - Raises CodeGenerationFailedException if intent extraction fails
    """

    def __init__( self, question="", question_gist="", last_question_asked="",
                  push_counter=-1,
                  routing_command="agent router go to calculator",
                  user_id="ricardo_felipe_ruiz_6bdc", user_email="", session_id="",
                  debug=False, verbose=False, auto_debug=False, inject_bugs=False ):
        """
        Initialize CalculatorAgent.

        Requires:
            - Either question or last_question_asked is non-empty
            - Config keys exist for the routing_command

        Ensures:
            - self.prompt is built with the user query injected
            - self.calc_intent is None (set in run_prompt)
        """
        super().__init__(
            df_path_key          = None,
            question             = question,
            question_gist        = question_gist,
            last_question_asked  = last_question_asked,
            push_counter         = push_counter,
            routing_command      = routing_command,
            user_id              = user_id,
            user_email           = user_email,
            session_id           = session_id,
            debug                = debug,
            verbose              = verbose,
            auto_debug           = auto_debug,
            inject_bugs          = inject_bugs
        )

        # Build prompt — XML example already injected by PromptTemplateProcessor in super().__init__()
        self.prompt = self.prompt_template.format(
            query = self.last_question_asked
        )

        # CalcIntent parsed from LLM response (set in run_prompt)
        self.calc_intent          = None
        self._fallback_to_math    = False
        self._delegated_to_math   = False

        if self.debug: print( f"CalculatorAgent: prompt length={len( self.prompt )}, user={user_email}" )

    def run_prompt( self, include_raw_response=False ):
        """
        Execute prompt against configured LLM and parse response into CalcIntent.

        Overrides AgentBase.run_prompt() to use CalcIntent.from_xml() directly
        instead of the XmlParserFactory flat-dict intermediate.

        Requires:
            - self.prompt is set to a valid prompt string
            - self.model_name is configured

        Ensures:
            - self.calc_intent is set to a validated CalcIntent instance
            - self.prompt_response_dict is set for protocol compatibility
            - Returns self.prompt_response_dict
        """
        factory = LlmClientFactory()
        llm     = factory.get_client( self.model_name, debug=self.debug, verbose=self.verbose )

        if self.debug: print( f"CalculatorAgent.run_prompt: model={self.model_name}, prompt length={len( self.prompt )}" )

        raw_response = llm.run( self.prompt )

        if self.debug: print( f"CalculatorAgent.run_prompt: raw response length={len( raw_response ) if raw_response else 0}, response:\n{raw_response or '(empty)'}" )

        # Extract <calc_intent> XML and parse into CalcIntent
        xml_text         = extract_calc_intent_xml( raw_response )
        self.calc_intent = CalcIntent.from_xml( xml_text, root_tag="calc_intent" )

        if self.debug: print( f"CalculatorAgent.run_prompt: Parsed intent: operation={self.calc_intent.operation}" )

        # Set prompt_response_dict for protocol compatibility with AgentBase
        self.prompt_response_dict = {
            "operation"    : self.calc_intent.operation,
            "confidence"   : self.calc_intent.confidence,
            "raw_response" : raw_response if include_raw_response else None,
        }

        return self.prompt_response_dict

    def run_prompt_with_fallback( self, include_raw_response=False ):
        """
        Execute run_prompt() with graceful fallback to MathAgent on failure.

        Catches ValueError from extract_calc_intent_xml() or CalcIntent.from_xml()
        and sets _fallback_to_math flag instead of raising. This allows run_code()
        to delegate to MathAgent for queries the LLM couldn't parse as CalcIntent.

        Requires:
            - self.prompt is set to a valid prompt string

        Ensures:
            - On success: self.calc_intent is set, _fallback_to_math is False
            - On failure: _fallback_to_math is True, self.calc_intent is None
        """
        try:
            return self.run_prompt( include_raw_response=include_raw_response )
        except ( ValueError, Exception ) as e:
            if self.debug: print( f"CalculatorAgent: intent extraction failed, falling back to MathAgent: {e}" )
            self._fallback_to_math = True
            self.calc_intent       = None
            return None

    def run_code( self, auto_debug=None, inject_bugs=None ):
        """
        Dispatch CalcIntent to calc_operations — pure Python, no sandbox.

        Overrides AgentBase.run_code() entirely — no code generation or execution.
        Instead, dispatches the parsed CalcIntent to calc_operations functions.

        When _fallback_to_math is True, delegates the entire pipeline to MathAgent
        (which generates Python code via LLM — slower but handles anything).

        Requires:
            - self.calc_intent is set from run_prompt(), OR _fallback_to_math is True

        Ensures:
            - self.code_response_dict is set with return_code and output
            - self.error is None on success
            - Raises CodeGenerationFailedException if dispatch fails
        """
        # Fallback: delegate to MathAgent for queries we couldn't parse
        if self._fallback_to_math:
            return self._delegate_to_math_agent()

        # Guard: unsupported operation → delegate to MathAgent
        if self.calc_intent and self.calc_intent.operation.strip().lower() == "unsupported":
            if self.debug: print( "CalculatorAgent: unsupported operation detected, delegating to MathAgent" )
            return self._delegate_to_math_agent()

        # Guard: convert with empty or unrecognized units → plain arithmetic, delegate to MathAgent
        if self.calc_intent and self.calc_intent.operation == "convert":
            from_u = self.calc_intent.from_unit.strip().lower()
            to_u   = self.calc_intent.to_unit.strip().lower()
            # Empty units → plain arithmetic, delegate to MathAgent
            if not from_u or not to_u:
                if self.debug: print( "CalculatorAgent: empty units detected, falling back to MathAgent" )
                return self._delegate_to_math_agent()
            from_cat, _ = find_category( resolve_alias( from_u ) )
            to_cat, _   = find_category( resolve_alias( to_u ) )
            if from_cat is None or to_cat is None:
                if self.debug: print( f"CalculatorAgent: unknown unit(s) '{from_u}'/'{to_u}', falling back to MathAgent" )
                return self._delegate_to_math_agent()

        try:
            result = dispatch( self.calc_intent, debug=self.debug )

            if result.get( "status" ) == "error":
                raise ValueError( result[ "message" ] )

            self.code_response_dict = { "return_code": 0, "output": result }
            self.error              = None

        except Exception as e:

            if self.debug: print( f"Calculator dispatch failed: {e}" )

            raise CodeGenerationFailedException(
                f"Calculator dispatch failed: {e}"
            )

        return self.code_response_dict

    def _delegate_to_math_agent( self ):
        """
        Delegate the entire question to MathAgent.

        Creates a MathAgent with the same question, runs its full pipeline
        (do_all), and copies the results back to this agent.

        Requires:
            - self._fallback_to_math is True

        Ensures:
            - self.answer_conversational, self.answer, self.code_response_dict,
              and self.prompt_response_dict are all set from MathAgent's results
            - Returns self.code_response_dict
        """
        self._delegated_to_math = True

        if self.debug: print( f"CalculatorAgent: delegating to MathAgent for: {self.last_question_asked}" )

        math_agent = MathAgent(
            question            = self.question,
            last_question_asked = self.last_question_asked,
            routing_command     = "agent router go to math",
            user_id             = getattr( self, "user_id", "" ),
            user_email          = getattr( self, "user_email", "" ),
            session_id          = getattr( self, "session_id", "" ),
            debug               = self.debug,
            verbose             = self.verbose
        )

        math_agent.do_all()

        # Copy results back
        self.answer_conversational = math_agent.answer_conversational
        self.answer                = math_agent.answer
        self.code_response_dict    = math_agent.code_response_dict
        self.prompt_response_dict  = math_agent.prompt_response_dict

        if self.debug: print( f"CalculatorAgent: MathAgent fallback result: {self.answer_conversational}" )

        return self.code_response_dict

    def do_all( self ):
        """
        Execute full agent pipeline with graceful fallback.

        Overrides AgentBase.do_all() to use run_prompt_with_fallback() instead
        of run_prompt(), and to skip run_formatter() when MathAgent already
        handled the entire pipeline via delegation.

        Requires:
            - self.prompt is set to a valid prompt string

        Ensures:
            - self.answer_conversational is set
            - Returns self.answer_conversational
        """
        self.run_prompt_with_fallback()
        self.run_code()
        if not self._delegated_to_math:
            self.run_formatter()
        return self.answer_conversational

    def run_formatter( self ):
        """
        Format calculator result for TTS voice output.

        Overrides AgentBase.run_formatter() to use format_result_for_voice()
        directly instead of the RawOutputFormatter LLM call.

        Requires:
            - self.code_response_dict contains 'output' with calc result dict
            - self.calc_intent is set with the operation

        Ensures:
            - self.answer_conversational is set to a TTS-friendly string
            - self.answer is set for QueueableJob protocol compatibility
            - Returns self.answer_conversational
        """
        result    = self.code_response_dict[ "output" ]
        operation = self.calc_intent.operation

        self.answer_conversational = format_result_for_voice( result, operation )
        self.answer                = self.answer_conversational

        if self.debug: print( f"CalculatorAgent.run_formatter: {self.answer_conversational}" )

        return self.answer_conversational

    def restore_from_serialized_state( self, file_path ):
        """
        Restore agent from serialized state.

        Requires:
            - file_path is a valid path

        Raises:
            - NotImplementedError (not implemented for Calculator agents)
        """
        raise NotImplementedError( "CalculatorAgent.restore_from_serialized_state() not implemented" )


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""

    print( "Testing CalculatorAgent module..." )
    passed = True

    try:
        # Test that the class exists and inherits properly
        assert issubclass( CalculatorAgent, AgentBase )
        print( "  ✓ CalculatorAgent inherits from AgentBase" )

        # We can't test full constructor without a running LLM server,
        # so verify the class interface
        assert hasattr( CalculatorAgent, "run_prompt" )
        assert hasattr( CalculatorAgent, "run_prompt_with_fallback" )
        assert hasattr( CalculatorAgent, "run_code" )
        assert hasattr( CalculatorAgent, "run_formatter" )
        assert hasattr( CalculatorAgent, "do_all" )
        assert hasattr( CalculatorAgent, "_delegate_to_math_agent" )
        print( "  ✓ Required override methods exist (including do_all and fallback)" )

        print( "  ○ Full agent pipeline: requires config + LLM (tested in integration)" )

        print( "✓ CalculatorAgent module smoke test PASSED" )

    except Exception as e:
        print( f"✗ CalculatorAgent module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
