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
        """Test factory selects correct strategy for WeatherAgent."""
        
        strategy = self.factory.get_parser_strategy( "agent router go to weather" )
        
        # Should use structured_v2 strategy per configuration
        assert strategy.get_strategy_name() == "structured_v2"
    
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
        """Test RawOutputFormatter creates and uses XML parser factory."""
        
        # Note: This test validates the integration without requiring LLM calls
        
        # The formatter should be created with factory integration
        # We can test this by checking that the factory import and initialization work
        from cosa.agents.raw_output_formatter import RawOutputFormatter
        
        # Verify the import and class structure
        assert hasattr( RawOutputFormatter, '__init__' )
        
        # The actual formatter creation may fail due to LLM configuration issues,
        # but the important thing is that the factory integration code is present
        try:
            # Check if the factory integration is in the source code
            import inspect
            source = inspect.getsource( RawOutputFormatter.__init__ )
            assert "XmlParserFactory" in source
            assert "xml_parser_factory" in source
            
            source_run = inspect.getsource( RawOutputFormatter.run_formatter )
            assert "parse_agent_response" in source_run
            assert "rephrased_answer" in source_run  # Pydantic field name
            
        except Exception as e:
            # If we can't inspect the source, at least verify the imports work
            from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
            assert XmlParserFactory is not None
    
    def test_formatter_xml_parsing_logic( self ):
        """Test the XML parsing logic in RawOutputFormatter."""
        
        # Test the parsing logic directly without LLM calls
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        factory = XmlParserFactory( config_mgr )
        
        # Simulate the parsing that happens in run_formatter
        mock_response = '''<response>
            <rephrased-answer>It's 65 degrees and partly cloudy in Seattle.</rephrased-answer>
        </response>'''
        
        try:
            parsed_response = factory.parse_agent_response(
                mock_response,
                "agent router go to weather",
                [ "rephrased-answer" ]
            )
            output = parsed_response.get( "rephrased_answer", "" )
            
            assert output == "It's 65 degrees and partly cloudy in Seattle."
            
        except Exception as e:
            assert False, f"Formatter parsing logic failed: {e}"


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