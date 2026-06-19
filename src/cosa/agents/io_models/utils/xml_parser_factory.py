#!/usr/bin/env python3
"""
XML Parser Factory for CoSA Agents

This module provides a factory for creating Pydantic-based XML parsing strategies.
All XML parsing uses strongly-typed Pydantic models for validation and type safety.

NOTE: Legacy baseline and hybrid strategies have been REMOVED as of Session 116.
      Use only Pydantic XML models for all agent responses.
"""

from typing import Dict, Any, Optional

from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel
from cosa.agents.io_models.xml_models import (
    ReceptionistResponse, SimpleResponse, CommandResponse,
    YesNoResponse, CodeResponse, CalendarResponse, CodeBrainstormResponse, BugInjectionResponse,
    IterativeDebuggingMinimalistResponse, IterativeDebuggingFullResponse, WeatherResponse,
    FormatterResponse
)


class PydanticXmlParser:
    """
    Modern Pydantic-based XML parsing strategy.
    
    This strategy uses strongly-typed Pydantic models for XML parsing,
    providing validation, type safety, and structured data access.
    """
    
    def __init__( self ):
        """
        Initialize Pydantic XML parsing strategy.
        
        Requires:
            - XML models are properly imported and available
            
        Ensures:
            - Agent routing command to model mapping is established
            - All supported agent types have corresponding Pydantic models
            
        Raises:
            - ImportError if required Pydantic models cannot be imported
        """
        # Map agent routing commands to their corresponding Pydantic models
        self.agent_model_map = {
            # Agent code generation schemas
            "agent router go to receptionist": ReceptionistResponse,
            "agent router go to todo": CodeResponse,
            "agent router go to calendar": CalendarResponse,
            "agent router go to datetime": CodeBrainstormResponse,
            "agent router go to math": CodeBrainstormResponse,
            "agent router go to bug injector": BugInjectionResponse,
            "agent router go to debugger": self._get_debugging_model,  # Dynamic model selection based on mode
            "agent router go to weather": WeatherResponse,  # For RawOutputFormatter weather responses (backward compat)

            # Formatter schemas (universal FormatterResponse for all agent formatters)
            "formatter for agent router go to math": FormatterResponse,
            "formatter for agent router go to calendar": FormatterResponse,
            "formatter for agent router go to datetime": FormatterResponse,
            "formatter for agent router go to receptionist": FormatterResponse,
            "formatter for agent router go to todo": FormatterResponse,
            "formatter for agent router go to weather": FormatterResponse,  # Could also use WeatherResponse

            # Future mappings will be added as more agents are migrated
        }
    
    def _get_debugging_model( self, xml_tag_names: list[str] ):
        """
        Dynamically select debugging model based on XML tag names.
        
        The IterativeDebuggingAgent has two modes:
        - Minimalist: ["thoughts", "line-number", "one-line-of-code", "success"]
        - Full: ["thoughts", "code", "example", "returns", "explanation"]
        
        Args:
            xml_tag_names: List of expected XML tags to determine mode
            
        Returns:
            Appropriate Pydantic model class for the debugging mode
        """
        if "one-line-of-code" in xml_tag_names or "success" in xml_tag_names:
            return IterativeDebuggingMinimalistResponse
        elif "code" in xml_tag_names and "explanation" in xml_tag_names:
            return IterativeDebuggingFullResponse
        else:
            # Default to minimalist if unclear
            return IterativeDebuggingMinimalistResponse
    
    def parse_xml_response( self, xml_response: str, agent_routing_command: str, xml_tag_names: list[str], debug: bool = False, verbose: bool = False ) -> Dict[str, Any]:
        """
        Parse XML response using Pydantic models with validation.
        
        Requires:
            - xml_response is valid XML matching expected model structure
            - agent_routing_command maps to a known Pydantic model
            
        Ensures:
            - Returns validated dictionary with type-safe values
            - All required fields are present and validated
            - Field types match Pydantic model specifications
            
        Raises:
            - ValueError if agent_routing_command not supported yet
            - ValidationError if XML doesn't match model requirements
            - XMLParsingError for XML parsing failures
        """
        if debug and verbose:
            print( f"PydanticXmlParsingStrategy: parsing XML for agent [{agent_routing_command}]" )
            
        # Get the appropriate Pydantic model for this agent
        model_class_or_method = self.agent_model_map.get( agent_routing_command )
        
        if model_class_or_method is None:
            raise ValueError( f"Pydantic model not yet implemented for agent: {agent_routing_command}" )
        
        # Handle dynamic model selection (for debugging agent only)
        if hasattr( model_class_or_method, '__name__' ) and model_class_or_method.__name__ == '_get_debugging_model':
            model_class = model_class_or_method( xml_tag_names )
        else:
            model_class = model_class_or_method
            
        if debug and verbose:
            print( f"  Using Pydantic model: {model_class.__name__}" )

        # Parse XML using the Pydantic model
        try:
            # Debug logging: Show XML before Pydantic parsing
            if debug and verbose:
                print( f"  XML to be parsed:" )
                print( f"  {xml_response}" )
                print()

            model_instance = model_class.from_xml( xml_response )
            result_dict = model_instance.model_dump()
            
            if debug and verbose:
                print( f"  Successfully parsed {len( result_dict )} fields" )
                
            return result_dict
            
        except Exception as e:
            if debug:
                print( f"  Pydantic parsing failed: {e}" )
            raise
    
class XmlParserFactory:
    """
    Factory for creating Pydantic-based XML parsers.

    This factory provides centralized access to XML parsing using strongly-typed
    Pydantic models. All XML parsing uses the PydanticXmlParser class.

    NOTE: Legacy baseline and hybrid strategies have been REMOVED.
          Only Pydantic parsing is supported.
    """

    def __init__( self, config_mgr: Optional[ConfigurationManager] = None ):
        """
        Initialize XML parser factory.

        Requires:
            - None (configuration is optional)

        Ensures:
            - Factory is initialized with Pydantic parser
            - Parser is cached for reuse

        Raises:
            - None
        """
        self.config_mgr = config_mgr or ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._parser = PydanticXmlParser()
        self.debug_mode = self.config_mgr.get( "xml parsing migration debug mode", default=False, return_type="boolean" )

        if self.debug_mode:
            print( "XmlParserFactory initialized with Pydantic-only parsing" )

    def parse_agent_response( self, xml_response: str, agent_routing_command: str, xml_tag_names: list[str], debug: bool = False, verbose: bool = False ) -> Dict[str, Any]:
        """
        Parse agent XML response using Pydantic models.

        This is the main entry point for agent XML parsing.

        Requires:
            - xml_response is valid XML string
            - agent_routing_command identifies the agent type
            - xml_tag_names contains expected XML tags to extract

        Ensures:
            - Returns parsed dictionary with expected field structure
            - Uses Pydantic model for type-safe parsing

        Raises:
            - XMLParsingError for parsing failures
            - ValidationError for Pydantic model validation failures
            - ValueError if agent_routing_command has no Pydantic model
        """
        if debug or self.debug_mode:
            print( f"Parsing XML response using Pydantic parser" )

        return self._parser.parse_xml_response(
            xml_response, agent_routing_command, xml_tag_names, debug=debug, verbose=verbose
        )


def quick_smoke_test() -> bool:
    """
    Quick smoke test for XmlParserFactory.

    Tests factory initialization and Pydantic-based parsing.

    Returns:
        True if all tests pass
    """
    print( "Testing XmlParserFactory..." )

    try:
        # Test 1: Factory initialization
        print( "  - Testing factory initialization..." )
        factory = XmlParserFactory()
        print( "    ✓ Factory created successfully" )

        # Test 2: Basic XML parsing with receptionist (implemented model)
        print( "  - Testing Pydantic XML parsing..." )
        test_xml = '''<response>
            <thoughts>Testing the parser factory</thoughts>
            <category>benign</category>
            <answer>Factory test successful</answer>
        </response>'''

        result = factory.parse_agent_response(
            test_xml,
            "agent router go to receptionist",
            [ "thoughts", "category", "answer" ]
        )
        assert "thoughts" in result and "category" in result and "answer" in result
        print( "    ✓ Pydantic parsing works" )

        # Test 3: Verify field values
        print( "  - Testing field extraction..." )
        assert result[ "thoughts" ] == "Testing the parser factory"
        assert result[ "category" ] == "benign"
        assert result[ "answer" ] == "Factory test successful"
        print( "    ✓ Field values extracted correctly" )

        # Test 4: Test formatter parsing
        print( "  - Testing formatter response parsing..." )
        formatter_xml = '''<response>
            <rephrased-answer>This is a rephrased answer</rephrased-answer>
        </response>'''

        try:
            result = factory.parse_agent_response(
                formatter_xml,
                "formatter for agent router go to math",
                [ "rephrased-answer" ]
            )
            assert "rephrased_answer" in result  # Pydantic field name
            print( "    ✓ Formatter parsing works" )
        except ValueError as e:
            if "not yet implemented" in str( e ):
                print( "    ℹ Formatter model not implemented (acceptable)" )
            else:
                raise

        # Test 5: Test error handling for unsupported agents
        print( "  - Testing error handling..." )
        try:
            factory.parse_agent_response(
                test_xml,
                "agent router go to nonexistent agent",
                [ "thoughts" ]
            )
            print( "    ✗ Expected ValueError for unsupported agent" )
            return False
        except ValueError as e:
            if "not yet implemented" in str( e ):
                print( "    ✓ Proper error for unsupported agent" )
            else:
                raise

        print( "✓ XmlParserFactory smoke test PASSED" )
        return True

    except Exception as e:
        print( f"✗ XmlParserFactory smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run smoke test when executed directly
    success = quick_smoke_test()
    exit( 0 if success else 1 )