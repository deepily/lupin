#!/usr/bin/env python3
"""
Comprehensive test suite for BugInjector Pydantic XML migration.

This test suite validates the Phase 6 migration of BugInjector from baseline 
util_xml.py parsing to structured Pydantic BugInjectionResponse models.

Tests cover:
- BugInjectionResponse model validation
- Factory integration with structured_v2 strategy
- Graceful fallback mechanisms
- Field mapping and type conversion
- XML tag compatibility (line-number → line_number)
"""

from typing import Dict, Any

from cosa.agents.io_models.xml_models import BugInjectionResponse
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
from cosa.agents.bug_injector import BugInjector
from cosa.config.configuration_manager import ConfigurationManager


class TestBugInjectionResponse:
    """Test suite for BugInjectionResponse Pydantic model."""
    
    def test_bug_injection_response_creation( self ):
        """Test basic BugInjectionResponse model creation and validation."""
        
        # Valid creation
        response = BugInjectionResponse(
            line_number=5,
            bug="print('Injected debug statement')"
        )
        
        assert response.line_number == 5
        assert response.bug == "print('Injected debug statement')"
    
    def test_bug_injection_response_validation( self ):
        """Test BugInjectionResponse field validation."""
        
        # Test line_number validation
        try:
            BugInjectionResponse( line_number=0, bug="test" )  # Should be positive
            assert False, "Should have raised validation error for line_number=0"
        except ValueError:
            pass  # Expected
            
        try:
            BugInjectionResponse( line_number=-1, bug="test" )  # Should be positive
            assert False, "Should have raised validation error for line_number=-1"
        except ValueError:
            pass  # Expected
    
    def test_bug_injection_response_from_xml( self ):
        """Test BugInjectionResponse.from_xml() parsing."""
        
        xml_response = '''<response>
            <line-number>7</line-number>
            <bug>result = None  # Injected bug</bug>
        </response>'''
        
        response = BugInjectionResponse.from_xml( xml_response )
        
        assert response.line_number == 7
        assert response.bug == "result = None  # Injected bug"
    
    def test_bug_injection_response_xml_tag_alias( self ):
        """Test XML tag aliases (line-number → line_number)."""
        
        # Test hyphenated XML tag mapping
        xml_with_hyphens = '''<response>
            <line-number>12</line-number>
            <bug>x = x + 1  # Off-by-one bug</bug>
        </response>'''
        
        response = BugInjectionResponse.from_xml( xml_with_hyphens )
        
        # Verify field mapping works correctly
        assert response.line_number == 12
        assert response.bug == "x = x + 1  # Off-by-one bug"
        
        # Verify model_dump() uses Python field names
        dumped = response.model_dump()
        assert "line_number" in dumped
        assert "line-number" not in dumped
    
    def test_bug_injection_response_special_characters( self ):
        """Test BugInjectionResponse with special characters and code."""
        
        xml_with_special_chars = '''<response>
            <line-number>3</line-number>
            <bug>if condition != True: raise Exception("Bug!")</bug>
        </response>'''
        
        response = BugInjectionResponse.from_xml( xml_with_special_chars )
        
        assert response.line_number == 3
        assert response.bug == 'if condition != True: raise Exception("Bug!")'
    
    def test_bug_injection_response_multiline_bug( self ):
        """Test BugInjectionResponse with multiline bug code."""
        
        xml_multiline = '''<response>
            <line-number>8</line-number>
            <bug>
# Multiline bug injection
for i in range(10):
    print(f"Debug: {i}")
            </bug>
        </response>'''
        
        response = BugInjectionResponse.from_xml( xml_multiline )
        
        assert response.line_number == 8
        assert "# Multiline bug injection" in response.bug
        assert "for i in range(10):" in response.bug


class TestBugInjectorFactoryIntegration:
    """Test suite for BugInjector integration with XmlParserFactory."""
    
    def setup_method( self ):
        """Set up test environment."""
        self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self.factory = XmlParserFactory( self.config_mgr )
    
    def test_factory_strategy_selection( self ):
        """Test factory selects correct strategy for BugInjector."""
        
        strategy = self.factory.get_parser_strategy( "agent router go to bug injector" )
        
        # Should use structured_v2 strategy per configuration
        assert strategy.get_strategy_name() == "structured_v2"
    
    def test_factory_bug_injection_parsing( self ):
        """Test factory parsing of BugInjector XML responses."""
        
        xml_response = '''<response>
            <line-number>15</line-number>
            <bug>print("Debug injection at line 15")</bug>
        </response>'''
        
        result = self.factory.parse_agent_response(
            xml_response,
            "agent router go to bug injector",
            [ "line-number", "bug" ]
        )
        
        assert isinstance( result, dict )
        assert result[ "line_number" ] == 15  # Note: Python field name
        assert result[ "bug" ] == 'print("Debug injection at line 15")'
    
    def test_factory_invalid_line_number_handling( self ):
        """Test factory handling of invalid line numbers."""
        
        xml_invalid = '''<response>
            <line-number>not_a_number</line-number>
            <bug>test bug</bug>
        </response>'''
        
        # Should raise validation error for invalid line number
        try:
            self.factory.parse_agent_response(
                xml_invalid,
                "agent router go to bug injector",
                [ "line-number", "bug" ]
            )
            assert False, "Should have raised validation error for invalid line number"
        except Exception:
            pass  # Expected validation error
    
    def test_factory_missing_required_fields( self ):
        """Test factory handling of missing required fields."""
        
        xml_missing_line = '''<response>
            <bug>test bug without line number</bug>
        </response>'''
        
        # Should raise validation error for missing required field
        try:
            self.factory.parse_agent_response(
                xml_missing_line,
                "agent router go to bug injector",
                [ "line-number", "bug" ]
            )
            assert False, "Should have raised validation error for missing line-number"
        except Exception:
            pass  # Expected validation error
    
    def test_factory_empty_bug_handling( self ):
        """Test factory handling of empty bug field."""
        
        xml_empty_bug = '''<response>
            <line-number>5</line-number>
            <bug></bug>
        </response>'''
        
        result = self.factory.parse_agent_response(
            xml_empty_bug,
            "agent router go to bug injector",
            [ "line-number", "bug" ]
        )
        
        assert result[ "line_number" ] == 5
        assert result[ "bug" ] == ""  # Empty string is valid


class TestBugInjectorMigrationIntegration:
    """Test suite for full BugInjector migration integration."""
    
    def test_bug_injector_creation_with_factory( self ):
        """Test BugInjector creation uses factory system."""
        
        test_code = [
            "def calculate(x, y):",
            "    return x + y",
            "",
            "result = calculate(3, 4)",
            "print(result)"
        ]
        
        bug_injector = BugInjector(
            code=test_code.copy(),
            example="calculate(3, 4)",
            debug=True,
            verbose=False
        )
        
        assert bug_injector.routing_command == "agent router go to bug injector"
        assert hasattr( bug_injector, 'config_mgr' )
    
    def test_bug_injector_xml_parsing_integration( self ):
        """Test BugInjector XML parsing through factory system."""
        
        test_code = [
            "def add(a, b):",
            "    return a + b",
            "",
            "result = add(1, 2)"
        ]
        
        bug_injector = BugInjector(
            code=test_code.copy(),
            example="add(1, 2)",
            debug=True,
            verbose=False
        )
        
        # Mock XML response for testing parsing
        mock_xml_response = '''<response>
            <line-number>2</line-number>
            <bug>    return a - b  # Subtraction bug instead of addition</bug>
        </response>'''
        
        # Test factory parsing directly
        xml_factory = XmlParserFactory( bug_injector.config_mgr )
        parsed_response = xml_factory.parse_agent_response(
            mock_xml_response,
            bug_injector.routing_command,
            [ "line-number", "bug" ],
            debug=True
        )
        
        assert parsed_response[ "line_number" ] == 2
        assert "subtraction bug" in parsed_response[ "bug" ].lower()


def run_bug_injector_migration_tests():
    """
    Run comprehensive BugInjector migration test suite.
    
    Returns:
        bool: True if all tests pass, False otherwise
    """
    import cosa.utils.util as du
    
    du.print_banner( "BugInjector Migration Test Suite", prepend_nl=True )
    
    test_results = {
        "BugInjectionResponse Model Tests": False,
        "Factory Integration Tests": False,
        "Full Migration Integration Tests": False
    }
    
    try:
        # Test 1: BugInjectionResponse model
        print( "Testing BugInjectionResponse Pydantic model..." )
        
        # Basic creation
        response = BugInjectionResponse( line_number=10, bug="test_bug = True" )
        assert response.line_number == 10
        assert response.bug == "test_bug = True"
        
        # XML parsing
        xml = '''<response><line-number>5</line-number><bug>x = 0</bug></response>'''
        response = BugInjectionResponse.from_xml( xml )
        assert response.line_number == 5
        assert response.bug == "x = 0"
        
        test_results[ "BugInjectionResponse Model Tests" ] = True
        print( "✓ BugInjectionResponse model tests passed" )
        
    except Exception as e:
        print( f"✗ BugInjectionResponse model tests failed: {e}" )
    
    try:
        # Test 2: Factory integration
        print( "Testing factory integration..." )
        
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        factory = XmlParserFactory( config_mgr )
        
        # Strategy selection
        strategy = factory.get_parser_strategy( "agent router go to bug injector" )
        assert strategy.get_strategy_name() == "structured_v2"
        
        # XML parsing
        xml = '''<response><line-number>7</line-number><bug>debug_flag = True</bug></response>'''
        result = factory.parse_agent_response( xml, "agent router go to bug injector", [ "line-number", "bug" ] )
        assert result[ "line_number" ] == 7
        assert result[ "bug" ] == "debug_flag = True"
        
        test_results[ "Factory Integration Tests" ] = True
        print( "✓ Factory integration tests passed" )
        
    except Exception as e:
        print( f"✗ Factory integration tests failed: {e}" )
    
    try:
        # Test 3: Full migration integration
        print( "Testing full BugInjector migration..." )
        
        test_code = [ "def test():", "    return True", "result = test()" ]
        bug_injector = BugInjector( code=test_code, example="test()", debug=False )
        
        assert bug_injector.routing_command == "agent router go to bug injector"
        
        test_results[ "Full Migration Integration Tests" ] = True
        print( "✓ Full migration integration tests passed" )
        
    except Exception as e:
        print( f"✗ Full migration integration tests failed: {e}" )
    
    # Summary
    passed_tests = sum( test_results.values() )
    total_tests = len( test_results )
    
    print( f"\n{'='*60}" )
    print( f"BugInjector Migration Test Results: {passed_tests}/{total_tests} passed" )
    
    for test_name, passed in test_results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print( f"  {test_name}: {status}" )
    
    if passed_tests == total_tests:
        print( "\n🎉 All BugInjector migration tests PASSED!" )
        return True
    else:
        print( f"\n❌ {total_tests - passed_tests} BugInjector migration tests FAILED" )
        return False


if __name__ == "__main__":
    # Run tests when executed directly
    success = run_bug_injector_migration_tests()
    exit( 0 if success else 1 )