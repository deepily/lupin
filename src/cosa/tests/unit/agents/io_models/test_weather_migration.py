#!/usr/bin/env python3
"""
Comprehensive test suite for WeatherAgent Pydantic XML migration.

This test suite validates the Phase 7 migration of WeatherAgent from baseline 
util_xml.py parsing to structured Pydantic WeatherResponse models.

The WeatherAgent migration is unique because the XML parsing happens in the 
RawOutputFormatter stage, not in the main agent. The WeatherAgent uses web search 
via LupinSearch, and the formatter processes the LLM response containing weather data.

Tests cover:
- WeatherResponse model validation
- Factory integration with weather-specific routing
- RawOutputFormatter integration with factory parsing
- Field mapping and type conversion (rephrased-answer → rephrased_answer)
- Weather-specific utility methods (temperature detection, forecast detection)
"""

from typing import Dict, Any

from cosa.agents.io_models.xml_models import WeatherResponse
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
from cosa.agents.raw_output_formatter import RawOutputFormatter
from cosa.config.configuration_manager import ConfigurationManager


class TestWeatherResponse:
    """Test suite for WeatherResponse Pydantic model."""
    
    def test_weather_response_creation( self ):
        """Test basic WeatherResponse model creation and validation."""
        
        # Valid creation
        response = WeatherResponse(
            rephrased_answer="It's currently 75 degrees in Washington, DC."
        )
        
        assert response.rephrased_answer == "It's currently 75 degrees in Washington, DC."
        assert response.is_temperature_response() == True
        assert response.is_forecast_response() == False
    
    def test_weather_response_validation( self ):
        """Test WeatherResponse field validation."""
        
        # Test empty rephrased_answer validation
        try:
            WeatherResponse( rephrased_answer="" )
            assert False, "Should have raised validation error for empty rephrased_answer"
        except ValueError:
            pass  # Expected
            
        try:
            WeatherResponse( rephrased_answer="   " )  # Whitespace only
            assert False, "Should have raised validation error for whitespace-only rephrased_answer"
        except ValueError:
            pass  # Expected
    
    def test_weather_response_from_xml( self ):
        """Test WeatherResponse.from_xml() parsing."""
        
        xml_response = '''<response>
            <rephrased-answer>There's a 30% chance of rain in New York today.</rephrased-answer>
        </response>'''
        
        response = WeatherResponse.from_xml( xml_response )
        
        assert response.rephrased_answer == "There's a 30% chance of rain in New York today."
        assert response.is_temperature_response() == False
        assert response.is_forecast_response() == True
    
    def test_weather_xml_tag_alias( self ):
        """Test XML tag aliases (rephrased-answer → rephrased_answer)."""
        
        xml_with_hyphens = '''<response>
            <rephrased-answer>Winter temperatures average 45 degrees in DC.</rephrased-answer>
        </response>'''
        
        response = WeatherResponse.from_xml( xml_with_hyphens )
        
        # Verify field mapping works correctly
        assert response.rephrased_answer == "Winter temperatures average 45 degrees in DC."
        
        # Verify model_dump() uses Python field names
        dumped = response.model_dump()
        assert "rephrased_answer" in dumped
        assert "rephrased-answer" not in dumped
    
    def test_weather_utility_methods( self ):
        """Test WeatherResponse utility methods for content classification."""
        
        # Test temperature detection
        temp_responses = [
            "It's 72 degrees today",
            "The temperature is 80°F",
            "Current temperature: 25°C",
            "Degrees are dropping"
        ]
        
        for temp_text in temp_responses:
            response = WeatherResponse( rephrased_answer=temp_text )
            assert response.is_temperature_response() == True, f"Failed to detect temperature in: {temp_text}"
        
        # Test forecast detection
        forecast_responses = [
            "It will rain tomorrow",
            "Sunny skies today",
            "30% chance of snow",
            "Cloudy with a chance of rain",
            "Tomorrow's forecast shows clear weather"
        ]
        
        for forecast_text in forecast_responses:
            response = WeatherResponse( rephrased_answer=forecast_text )
            assert response.is_forecast_response() == True, f"Failed to detect forecast in: {forecast_text}"
        
        # Test mixed responses
        mixed_response = WeatherResponse( rephrased_answer="It's 70 degrees with a chance of rain today" )
        assert mixed_response.is_temperature_response() == True
        assert mixed_response.is_forecast_response() == True
    
    def test_weather_special_characters( self ):
        """Test WeatherResponse with special characters and formatting."""
        
        xml_with_special_chars = '''<response>
            <rephrased-answer>It's 75°F with 80% humidity & light winds.</rephrased-answer>
        </response>'''
        
        response = WeatherResponse.from_xml( xml_with_special_chars )
        
        assert response.rephrased_answer == "It's 75°F with 80% humidity & light winds."
        assert response.is_temperature_response() == True


class TestWeatherFactoryIntegration:
    """Test suite for WeatherAgent integration with XmlParserFactory."""
    
    def setup_method( self ):
        """Set up test environment."""
        self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self.factory = XmlParserFactory( self.config_mgr )
    
    def test_factory_strategy_selection( self ):
        """
        Factory maps the weather command to its Pydantic model.

        ( Repaired 2026-05-31: get_parser_strategy()/get_strategy_name() were REMOVED in the
        Session-116 Pydantic-only refactor — see xml_parser_factory.py header. The current
        contract is the command→model map on the single PydanticXmlParser. )
        """
        parser = self.factory._parser
        assert parser.agent_model_map[ "agent router go to weather" ] is WeatherResponse
    
    def test_factory_weather_parsing( self ):
        """Test factory parsing of weather XML responses."""
        
        xml_response = '''<response>
            <rephrased-answer>The current temperature in Boston is 68 degrees.</rephrased-answer>
        </response>'''
        
        result = self.factory.parse_agent_response(
            xml_response,
            "agent router go to weather",
            [ "rephrased-answer" ]
        )
        
        assert isinstance( result, dict )
        assert result[ "rephrased_answer" ] == "The current temperature in Boston is 68 degrees."  # Python field name
    
    def test_factory_temperature_response_parsing( self ):
        """Test factory parsing of temperature-focused responses."""
        
        xml_response = '''<response>
            <rephrased-answer>It's currently 82 degrees in Miami.</rephrased-answer>
        </response>'''
        
        result = self.factory.parse_agent_response(
            xml_response,
            "agent router go to weather",
            [ "rephrased-answer" ]
        )
        
        assert result[ "rephrased_answer" ] == "It's currently 82 degrees in Miami."
    
    def test_factory_forecast_response_parsing( self ):
        """Test factory parsing of forecast-focused responses."""
        
        xml_response = '''<response>
            <rephrased-answer>There's a 70% chance of thunderstorms this afternoon.</rephrased-answer>
        </response>'''
        
        result = self.factory.parse_agent_response(
            xml_response,
            "agent router go to weather",
            [ "rephrased-answer" ]
        )
        
        assert "thunderstorms" in result[ "rephrased_answer" ]
        assert "70%" in result[ "rephrased_answer" ]
    
    def test_factory_error_handling( self ):
        """Test factory handling of malformed weather responses."""
        
        xml_invalid = '''<response>
            <rephrased-answer></rephrased-answer>
        </response>'''
        
        # Should raise validation error for empty response
        try:
            self.factory.parse_agent_response(
                xml_invalid,
                "agent router go to weather",
                [ "rephrased-answer" ]
            )
            assert False, "Should have raised validation error for empty rephrased-answer"
        except Exception:
            pass  # Expected validation error


class TestRawOutputFormatterMigration:
    """Test suite for RawOutputFormatter integration with factory parsing."""
    
    def test_formatter_factory_integration( self ):
        """
        The formatter parses its LLM's answer through the XML parser FACTORY and
        returns what the factory extracted.

        HOW THIS IS CHECKED, AND WHY IT CHANGED (row 122f07a1). This test used to
        read RawOutputFormatter's source and assert four words appeared in it
        ("XmlParserFactory", "xml_parser_factory", "parse_agent_response",
        "rephrased_answer") — and it did so INSIDE a `try` whose `except Exception`
        swallowed the result. AssertionError is an Exception, so all four could
        fail and the test still passed: it could not go red for any reason at all.
        Both defects are gone. This builds the formatter with its config, template,
        and LLM stubbed, runs it, and reads what comes back.
        """
        from unittest.mock import MagicMock, patch
        import cosa.agents.raw_output_formatter as rof_mod

        # The one thing under test: the factory's extracted value must be the
        # value the formatter returns.
        parser = MagicMock()
        parser.parse_agent_response.return_value = {
            "rephrased_answer": "It's 65 degrees and partly cloudy in Seattle."
        }

        llm = MagicMock()
        llm.run.return_value = "<response><rephrased-answer>ignored</rephrased-answer></response>"

        config = MagicMock()
        config.get.side_effect = lambda key, *a, **kw: (
            "/src/conf/prompts/formatter.txt" if key.startswith( "formatter template" ) else "spec-formatter"
        )

        with patch.object( rof_mod, "ConfigurationManager", return_value=config ), \
             patch.object( rof_mod, "XmlParserFactory", return_value=parser ) as factory_cls, \
             patch.object( rof_mod, "LlmClientFactory" ) as llm_factory, \
             patch.object( rof_mod.du, "get_file_as_string", return_value="TEMPLATE {question}" ), \
             patch.object( rof_mod.du, "get_project_root", return_value="/proj" ):
            llm_factory.return_value.get_client.return_value = llm

            formatter = rof_mod.RawOutputFormatter(
                question        = "what's the weather in Seattle",
                raw_output      = "<weather>65F partly cloudy</weather>",
                routing_command = "agent router go to weather",
            )
            output = formatter.run_formatter()

        # 1. The factory is the parser it built — not a hand-rolled one.
        factory_cls.assert_called_once_with( config )
        assert formatter.xml_parser_factory is parser

        # 2. It asked the factory to parse the LLM's answer, under the FORMATTER
        #    routing command, for the rephrased-answer tag.
        parser.parse_agent_response.assert_called_once()
        call = parser.parse_agent_response.call_args
        assert call.args[ 0 ] == llm.run.return_value, "the formatter parsed something other than its LLM's answer"
        assert call.args[ 1 ] == "formatter for agent router go to weather", (
            f"the formatter must parse under its OWN routing command, not the agent's; "
            f"got {call.args[ 1 ]!r}"
        )
        assert call.args[ 2 ] == [ "rephrased-answer" ]

        # 3. What the factory extracted is what the caller gets.
        assert output == "It's 65 degrees and partly cloudy in Seattle."

    def test_a_missing_rephrased_answer_yields_empty_not_a_crash( self ):
        """The formatter's documented fallback when the tag is absent.

        RED ON REVERT: drop the default from the `.get( "rephrased_answer", "" )`
        and this raises KeyError instead of returning "".
        """
        from unittest.mock import MagicMock, patch
        import cosa.agents.raw_output_formatter as rof_mod

        parser = MagicMock()
        parser.parse_agent_response.return_value = { }      # the tag never arrived

        config = MagicMock()
        config.get.side_effect = lambda key, *a, **kw: (
            "/src/conf/prompts/formatter.txt" if key.startswith( "formatter template" ) else "spec-formatter"
        )

        with patch.object( rof_mod, "ConfigurationManager", return_value=config ), \
             patch.object( rof_mod, "XmlParserFactory", return_value=parser ), \
             patch.object( rof_mod, "LlmClientFactory" ), \
             patch.object( rof_mod.du, "get_file_as_string", return_value="TEMPLATE" ), \
             patch.object( rof_mod.du, "get_project_root", return_value="/proj" ):
            formatter = rof_mod.RawOutputFormatter(
                question        = "q",
                raw_output      = "r",
                routing_command = "agent router go to weather",
            )
            assert formatter.run_formatter() == ""

    def test_formatter_xml_parsing_logic( self ):
        """The factory extracts the rephrased answer from a real formatter response.

        HOW THIS CHANGED (row 122f07a1): the assertion used to sit inside a `try`
        with `except Exception: assert False, ...` underneath. The inner assert
        raised AssertionError, the handler caught it, and the `assert False` raised
        a SECOND AssertionError that nothing caught — so the test could fail, but
        only ever with "Formatter parsing logic failed", never naming what the
        parser actually returned. The try is gone; a wrong value now reports itself.
        """
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        factory    = XmlParserFactory( config_mgr )

        mock_response = (
            "<response>"
            "<rephrased-answer>It's 65 degrees and partly cloudy in Seattle.</rephrased-answer>"
            "</response>"
        )

        parsed_response = factory.parse_agent_response(
            mock_response,
            "agent router go to weather",
            [ "rephrased-answer" ]
        )

        assert parsed_response.get( "rephrased_answer", "" ) == \
            "It's 65 degrees and partly cloudy in Seattle.", (
                f"the factory did not extract the rephrased answer; it returned "
                f"{parsed_response!r}"
            )


def run_weather_migration_tests():
    """
    Run comprehensive WeatherAgent migration test suite.
    
    Returns:
        bool: True if all tests pass, False otherwise
    """
    import cosa.utils.util as du
    
    du.print_banner( "WeatherAgent Migration Test Suite", prepend_nl=True )
    
    test_results = {
        "WeatherResponse Model Tests": False,
        "Factory Integration Tests": False,
        "RawOutputFormatter Integration Tests": False,
        "Weather Utility Methods Tests": False
    }
    
    try:
        # Test 1: WeatherResponse model
        print( "Testing WeatherResponse Pydantic model..." )
        
        # Basic creation
        response = WeatherResponse(
            rephrased_answer="It's currently 78 degrees in Los Angeles."
        )
        assert response.rephrased_answer == "It's currently 78 degrees in Los Angeles."
        assert response.is_temperature_response() == True
        
        # XML parsing
        xml = '''<response><rephrased-answer>Rain expected tomorrow</rephrased-answer></response>'''
        response = WeatherResponse.from_xml( xml )
        assert response.rephrased_answer == "Rain expected tomorrow"
        assert response.is_forecast_response() == True
        
        test_results[ "WeatherResponse Model Tests" ] = True
        print( "✓ WeatherResponse model tests passed" )
        
    except Exception as e:
        print( f"✗ WeatherResponse model tests failed: {e}" )
    
    try:
        # Test 2: Factory integration
        print( "Testing factory integration..." )
        
        from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        factory = XmlParserFactory( config_mgr )
        
        # Strategy selection
        strategy = factory.get_parser_strategy( "agent router go to weather" )
        assert strategy.get_strategy_name() == "structured_v2"
        
        # XML parsing
        xml = '''<response><rephrased-answer>Sunny and 85 degrees</rephrased-answer></response>'''
        result = factory.parse_agent_response( xml, "agent router go to weather", [ "rephrased-answer" ] )
        assert result[ "rephrased_answer" ] == "Sunny and 85 degrees"
        
        test_results[ "Factory Integration Tests" ] = True
        print( "✓ Factory integration tests passed" )
        
    except Exception as e:
        print( f"✗ Factory integration tests failed: {e}" )
    
    try:
        # Test 3: RawOutputFormatter integration
        print( "Testing RawOutputFormatter integration..." )
        
        # Test the integration without requiring LLM calls
        from cosa.agents.raw_output_formatter import RawOutputFormatter
        from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
        
        # Verify integration components
        assert RawOutputFormatter is not None
        assert XmlParserFactory is not None
        
        # Test parsing logic directly
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        factory = XmlParserFactory( config_mgr )
        
        mock_xml = '''<response><rephrased-answer>Test weather response</rephrased-answer></response>'''
        result = factory.parse_agent_response( mock_xml, "agent router go to weather", [ "rephrased-answer" ] )
        assert result[ "rephrased_answer" ] == "Test weather response"
        
        test_results[ "RawOutputFormatter Integration Tests" ] = True
        print( "✓ RawOutputFormatter integration tests passed" )
        
    except Exception as e:
        print( f"✗ RawOutputFormatter integration tests failed: {e}" )
    
    try:
        # Test 4: Weather utility methods
        print( "Testing weather utility methods..." )
        
        # Temperature detection
        temp_response = WeatherResponse( rephrased_answer="The temperature is 72 degrees" )
        assert temp_response.is_temperature_response() == True
        
        # Forecast detection
        forecast_response = WeatherResponse( rephrased_answer="Expect rain this evening" )
        assert forecast_response.is_forecast_response() == True
        
        # Mixed response
        mixed_response = WeatherResponse( rephrased_answer="It's 68 degrees with cloudy skies today" )
        assert mixed_response.is_temperature_response() == True
        assert mixed_response.is_forecast_response() == True
        
        test_results[ "Weather Utility Methods Tests" ] = True
        print( "✓ Weather utility methods tests passed" )
        
    except Exception as e:
        print( f"✗ Weather utility methods tests failed: {e}" )
    
    # Summary
    passed_tests = sum( test_results.values() )
    total_tests = len( test_results )
    
    print( f"\n{'='*70}" )
    print( f"WeatherAgent Migration Test Results: {passed_tests}/{total_tests} passed" )
    
    for test_name, passed in test_results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print( f"  {test_name}: {status}" )
    
    if passed_tests == total_tests:
        print( "\n🎉 All WeatherAgent migration tests PASSED!" )
        return True
    else:
        print( f"\n❌ {total_tests - passed_tests} WeatherAgent migration tests FAILED" )
        return False


if __name__ == "__main__":
    # Run tests when executed directly
    success = run_weather_migration_tests()
    exit( 0 if success else 1 )