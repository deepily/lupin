#!/usr/bin/env python3
"""
Mock pipeline tests for Calculator agent (Surface 2 of Testing Ladder).

Validates the full agent pipeline run_prompt() → run_code() → run_formatter()
with a mocked LLM — zero cost, instant feedback. No server required.

Test classes:
    - TestConvertPipelineMocked (3): Convert operation end-to-end
    - TestMortgagePipelineMocked (2): Mortgage operation end-to-end
    - TestPriceComparisonPipelineMocked (2): Price comparison end-to-end
    - TestErrorHandling (3): Graceful failures for bad LLM output
    - TestPromptConstruction (2): Real template + PromptTemplateProcessor verification
    - TestMathAgentFallback (3): Fallback to MathAgent when intent extraction fails

Run: pytest src/tests/unit/test_calculator_mock_pipeline.py -v
"""

from unittest.mock import patch, MagicMock

import pytest

import cosa.utils.util as cu
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
from cosa.agents.calculator.xml_models import CalcIntent
from cosa.agents.calculator.agent import CalculatorAgent
from cosa.agents.agent_base import CodeGenerationFailedException


# ============================================================================
# Helpers
# ============================================================================

def _create_mock_calculator_agent( question="how many miles is 10 kilometers" ):
    """
    Create a CalculatorAgent via __new__() bypass, skipping AgentBase.__init__.

    Reuses the pattern from test_crud_mock_pipeline.py.

    Requires:
        - question is a non-empty string

    Ensures:
        - Returns a fully wired agent with all attributes needed for
          run_prompt / run_code / run_formatter
    """
    agent = CalculatorAgent.__new__( CalculatorAgent )

    agent.debug                 = True
    agent.verbose               = False
    agent.last_question_asked   = question
    agent.question              = question
    agent.model_name            = "kaitchup/phi_4_14b"
    agent.routing_command       = "agent router go to calculator"
    agent.user_email            = "test@example.com"
    agent.calc_intent           = None
    agent.error                 = ""
    agent.answer                = ""
    agent.answer_conversational = None
    agent.auto_debug            = False
    agent.inject_bugs           = False
    agent.prompt_response_dict  = None
    agent.code_response_dict    = None
    agent._fallback_to_math     = False

    # Build ad-hoc prompt — sufficient for mocked-LLM tests
    intent_example = CalcIntent.get_example_for_template().to_xml( root_tag="calc_intent" )
    agent.prompt = f"Extract calc intent: {question}\n{intent_example}"

    return agent


# ============================================================================
# TestConvertPipelineMocked — Full convert pipeline: LLM → dispatch → TTS
# ============================================================================

class TestConvertPipelineMocked:
    """Mocked end-to-end convert pipeline: run_prompt → run_code → run_formatter."""

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_convert_full_pipeline( self, mock_factory_cls ):
        """Full convert pipeline: LLM extracts intent → dispatch converts → TTS formats result."""
        agent = _create_mock_calculator_agent( "how many miles is 10 kilometers" )

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<calc_intent>'
            '<operation>convert</operation>'
            '<value>10</value>'
            '<from_unit>kilometers</from_unit>'
            '<to_unit>miles</to_unit>'
            '<confidence>0.95</confidence>'
            '<raw_query>how many miles is 10 kilometers</raw_query>'
            '</calc_intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        # Step 1: run_prompt
        prompt_result = agent.run_prompt()
        assert agent.calc_intent is not None
        assert agent.calc_intent.operation == "convert"
        assert agent.calc_intent.value == "10"
        assert agent.calc_intent.from_unit == "kilometers"
        assert agent.calc_intent.to_unit == "miles"

        # Step 2: run_code
        code_result = agent.run_code()
        assert code_result[ "return_code" ] == 0
        assert code_result[ "output" ][ "status" ] == "ok"
        assert abs( code_result[ "output" ][ "result" ] - 6.2137 ) < 0.001

        # Step 3: run_formatter
        tts_result = agent.run_formatter()
        assert len( tts_result ) > 0
        assert "6.21" in tts_result
        assert "kilometers" in tts_result
        assert "miles" in tts_result
        assert agent.answer_conversational == tts_result

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_convert_temperature_pipeline( self, mock_factory_cls ):
        """Convert 72°F to Celsius through full pipeline."""
        agent = _create_mock_calculator_agent( "convert 72 fahrenheit to celsius" )

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<calc_intent>'
            '<operation>convert</operation>'
            '<value>72</value>'
            '<from_unit>fahrenheit</from_unit>'
            '<to_unit>celsius</to_unit>'
            '<confidence>0.90</confidence>'
            '</calc_intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        agent.run_prompt()
        assert agent.calc_intent.operation == "convert"

        code_result = agent.run_code()
        assert code_result[ "output" ][ "status" ] == "ok"
        assert abs( code_result[ "output" ][ "result" ] - 22.22 ) < 0.01

        tts_result = agent.run_formatter()
        # Formatter rounds to 1 decimal for values >= 10, so 22.2 not 22.22
        assert "22.2" in tts_result
        assert "Fahrenheit" in tts_result
        assert "Celsius" in tts_result

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_convert_prompt_response_dict_set( self, mock_factory_cls ):
        """Verify prompt_response_dict is set for protocol compatibility."""
        agent = _create_mock_calculator_agent()

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<calc_intent>'
            '<operation>convert</operation>'
            '<value>10</value>'
            '<from_unit>km</from_unit>'
            '<to_unit>miles</to_unit>'
            '<confidence>0.88</confidence>'
            '</calc_intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        prompt_result = agent.run_prompt()
        assert prompt_result is not None
        assert prompt_result[ "operation" ] == "convert"
        assert prompt_result[ "confidence" ] == "0.88"


# ============================================================================
# TestMortgagePipelineMocked — Full mortgage pipeline
# ============================================================================

class TestMortgagePipelineMocked:
    """Mocked end-to-end mortgage pipeline."""

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_mortgage_full_pipeline( self, mock_factory_cls ):
        """Full mortgage pipeline: $300k at 6.5% for 30 years."""
        agent = _create_mock_calculator_agent( "monthly payment on a 300000 dollar mortgage at 6.5 percent for 30 years" )

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<calc_intent>'
            '<operation>mortgage</operation>'
            '<principal>300000</principal>'
            '<annual_rate>6.5</annual_rate>'
            '<term_years>30</term_years>'
            '<down_payment></down_payment>'
            '<confidence>0.92</confidence>'
            '</calc_intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        agent.run_prompt()
        assert agent.calc_intent.operation == "mortgage"
        assert agent.calc_intent.get_principal_float() == 300000.0

        code_result = agent.run_code()
        assert code_result[ "output" ][ "status" ] == "ok"
        assert abs( code_result[ "output" ][ "monthly_payment" ] - 1896.20 ) < 1.0

        tts_result = agent.run_formatter()
        assert "1,896" in tts_result
        assert "interest" in tts_result

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_mortgage_with_down_payment( self, mock_factory_cls ):
        """Mortgage with down payment: $500k house, $100k down."""
        agent = _create_mock_calculator_agent( "monthly payment on a 500k house with 100k down at 7 percent for 15 years" )

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<calc_intent>'
            '<operation>mortgage</operation>'
            '<principal>500000</principal>'
            '<annual_rate>7</annual_rate>'
            '<term_years>15</term_years>'
            '<down_payment>100000</down_payment>'
            '<confidence>0.88</confidence>'
            '</calc_intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        agent.run_prompt()
        code_result = agent.run_code()
        assert code_result[ "output" ][ "status" ] == "ok"
        assert code_result[ "output" ][ "loan_amount" ] == 400000.0


# ============================================================================
# TestPriceComparisonPipelineMocked — Full price comparison pipeline
# ============================================================================

class TestPriceComparisonPipelineMocked:
    """Mocked end-to-end price comparison pipeline."""

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_price_comparison_full_pipeline( self, mock_factory_cls ):
        """Full price comparison: 12 oz at $3.49 vs 24 oz at $5.99."""
        agent = _create_mock_calculator_agent( "compare 12 oz at 3.49 vs 24 oz at 5.99" )

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<calc_intent>'
            '<operation>compare_prices</operation>'
            '<items>[{"name": "12 oz", "price": 3.49, "quantity": 12, "unit": "oz"}, '
            '{"name": "24 oz", "price": 5.99, "quantity": 24, "unit": "oz"}]</items>'
            '<confidence>0.91</confidence>'
            '</calc_intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        agent.run_prompt()
        assert agent.calc_intent.operation == "compare_prices"

        code_result = agent.run_code()
        assert code_result[ "output" ][ "status" ] == "ok"
        assert code_result[ "output" ][ "cheapest" ] == "24 oz"

        tts_result = agent.run_formatter()
        assert "24 oz" in tts_result
        assert "cheaper" in tts_result

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_price_comparison_gallon_vs_half( self, mock_factory_cls ):
        """Gallon at $4.29 vs half gallon at $2.89."""
        agent = _create_mock_calculator_agent( "gallon of milk at 4.29 vs half gallon at 2.89" )

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<calc_intent>'
            '<operation>compare_prices</operation>'
            '<items>[{"name": "Gallon", "price": 4.29, "quantity": 1.0, "unit": "gallon"}, '
            '{"name": "Half gallon", "price": 2.89, "quantity": 0.5, "unit": "gallon"}]</items>'
            '<confidence>0.93</confidence>'
            '</calc_intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        agent.run_prompt()
        code_result = agent.run_code()
        assert code_result[ "output" ][ "cheapest" ] == "Gallon"


# ============================================================================
# TestErrorHandling — Graceful failures for bad LLM output
# ============================================================================

class TestErrorHandling:
    """Error handling for malformed LLM responses."""

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_garbage_response_no_xml( self, mock_factory_cls ):
        """LLM returns garbage (no XML) → run_prompt raises ValueError."""
        agent = _create_mock_calculator_agent()

        mock_llm = MagicMock()
        mock_llm.run.return_value = "I don't understand what you're asking. Can you be more specific?"
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        with pytest.raises( ValueError, match="No <calc_intent>" ):
            agent.run_prompt()

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_unknown_operation_raises_in_dispatch( self, mock_factory_cls ):
        """LLM returns XML with unknown operation → run_code raises CodeGenerationFailedException."""
        agent = _create_mock_calculator_agent()

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<calc_intent>'
            '<operation>factorial</operation>'
            '<value>5</value>'
            '<confidence>0.80</confidence>'
            '</calc_intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        agent.run_prompt()
        assert agent.calc_intent.operation == "factorial"

        with pytest.raises( CodeGenerationFailedException, match="Unknown calc operation" ):
            agent.run_code()

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_empty_response_raises( self, mock_factory_cls ):
        """LLM returns empty string → run_prompt raises ValueError."""
        agent = _create_mock_calculator_agent()

        mock_llm = MagicMock()
        mock_llm.run.return_value = ""
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        with pytest.raises( ValueError, match="Empty response" ):
            agent.run_prompt()


# ============================================================================
# TestPromptConstruction — Real template + PromptTemplateProcessor verification
# ============================================================================

class TestPromptConstruction:
    """Verify the real template + PromptTemplateProcessor produces a correct prompt."""

    TEMPLATE_PATH   = "/src/conf/prompts/agents/calculator.txt"
    ROUTING_COMMAND = "agent router go to calculator"

    @pytest.fixture
    def processed_prompt( self ):
        """Read real template, process through PromptTemplateProcessor, return result."""
        template_path = cu.get_project_root() + self.TEMPLATE_PATH
        with open( template_path, "r" ) as f:
            raw_template = f.read()

        processor = PromptTemplateProcessor( debug=False )
        return processor.process_template( raw_template, self.ROUTING_COMMAND )

    def test_pydantic_marker_replaced( self, processed_prompt ):
        """{{PYDANTIC_XML_EXAMPLE}} marker is replaced by PromptTemplateProcessor."""
        assert "{{PYDANTIC_XML_EXAMPLE}}" not in processed_prompt

    def test_calc_intent_xml_injected( self, processed_prompt ):
        """Processed template contains <calc_intent>...</calc_intent> XML block."""
        assert "<calc_intent>" in processed_prompt
        assert "</calc_intent>" in processed_prompt
        assert "<operation>" in processed_prompt

    def test_generic_placeholders_present( self, processed_prompt ):
        """XML example uses generic placeholders, not concrete data."""
        # The template mentions <calc_intent> in the instruction text AND in the
        # injected XML example. We want the example block — search from </stop>
        # backward to find the XML block injected by PromptTemplateProcessor.
        assert "</stop>" in processed_prompt
        stop_pos  = processed_prompt.index( "</stop>" )
        # The XML example is the <calc_intent>...</calc_intent> block just before </stop>
        xml_end   = stop_pos
        xml_start = processed_prompt.rfind( "<calc_intent>", 0, xml_end )
        xml_block = processed_prompt[ xml_start:xml_end ]

        # Placeholders should be present
        assert "[operation" in xml_block
        assert "[numeric value" in xml_block

    def test_format_substitution_works( self, processed_prompt ):
        """prompt_template.format(query=...) succeeds after processor replacement."""
        final_prompt = processed_prompt.format(
            query = "how many miles is 10 kilometers"
        )
        assert "how many miles is 10 kilometers" in final_prompt


# ============================================================================
# TestMathAgentFallback — Fallback to MathAgent when intent extraction fails
# ============================================================================

class TestMathAgentFallback:
    """Verify fallback to MathAgent when CalcIntent extraction fails."""

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_fallback_flag_set_on_garbage_xml( self, mock_factory_cls ):
        """Garbage response sets _fallback_to_math flag when fallback enabled."""
        agent = _create_mock_calculator_agent( "what is the square root of 144" )

        mock_llm = MagicMock()
        mock_llm.run.return_value = "The square root of 144 is 12. Here's the Python code:\nprint(144**0.5)"
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        # run_prompt with fallback should set flag instead of raising
        agent.run_prompt_with_fallback()
        assert agent._fallback_to_math is True

    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_fallback_flag_not_set_on_valid_xml( self, mock_factory_cls ):
        """Valid XML response does NOT set fallback flag."""
        agent = _create_mock_calculator_agent( "how many miles is 10 km" )

        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<calc_intent>'
            '<operation>convert</operation>'
            '<value>10</value>'
            '<from_unit>km</from_unit>'
            '<to_unit>miles</to_unit>'
            '<confidence>0.95</confidence>'
            '</calc_intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        agent.run_prompt_with_fallback()
        assert agent._fallback_to_math is False
        assert agent.calc_intent is not None
        assert agent.calc_intent.operation == "convert"

    @patch( "cosa.agents.calculator.agent.MathAgent" )
    @patch( "cosa.agents.calculator.agent.LlmClientFactory" )
    def test_fallback_delegates_to_math_agent( self, mock_factory_cls, mock_math_cls ):
        """When fallback flag is set, run_code delegates to MathAgent."""
        agent = _create_mock_calculator_agent( "what is the integral of x squared" )
        agent._fallback_to_math   = True
        agent.user_id             = "test_user"
        agent.session_id          = "test_session"

        # Mock MathAgent instance
        mock_math_instance                       = MagicMock()
        mock_math_instance.answer_conversational = "The integral of x squared is x cubed over 3 plus a constant."
        mock_math_instance.answer                = "x^3/3 + C"
        mock_math_instance.code_response_dict    = { "return_code": 0, "output": "x^3/3 + C" }
        mock_math_cls.return_value               = mock_math_instance

        code_result = agent.run_code()
        mock_math_instance.do_all.assert_called_once()
        assert agent.answer_conversational == "The integral of x squared is x cubed over 3 plus a constant."
        assert agent.answer == "x^3/3 + C"


def quick_smoke_test():
    """Module-level smoke test: verify test classes are importable."""

    print( "Testing calculator mock pipeline module..." )
    passed = True

    try:
        assert callable( _create_mock_calculator_agent )
        agent = _create_mock_calculator_agent()
        assert agent.routing_command == "agent router go to calculator"
        assert agent._fallback_to_math is False
        print( "  ✓ _create_mock_calculator_agent helper works" )

        assert hasattr( CalculatorAgent, "run_prompt" )
        assert hasattr( CalculatorAgent, "run_code" )
        assert hasattr( CalculatorAgent, "run_formatter" )
        print( "  ✓ CalculatorAgent has required pipeline methods" )

        print( "  ○ Full pipeline tests: run via pytest (mocked LLM required)" )
        print( "✓ calculator mock pipeline module smoke test PASSED" )

    except Exception as e:
        print( f"✗ calculator mock pipeline module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
