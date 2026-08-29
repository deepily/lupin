#!/usr/bin/env python3
"""
Comprehensive test suite for IterativeDebuggingAgent Pydantic XML migration.

This test suite validates the Phase 6 migration of IterativeDebuggingAgent from baseline 
util_xml.py parsing to structured Pydantic IterativeDebuggingResponse models.

Tests cover:
- IterativeDebuggingMinimalistResponse model validation
- IterativeDebuggingFullResponse model validation  
- Factory integration with dynamic model selection
- Field mapping and type conversion for both modes
- XML tag compatibility (line-number → line_number, one-line-of-code → one_line_of_code)
- Graceful fallback mechanisms for dual-mode operation
"""

from typing import Dict, Any
import pytest
import os
import tempfile
from unittest.mock import patch

from cosa.agents.io_models.xml_models import IterativeDebuggingMinimalistResponse, IterativeDebuggingFullResponse
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
from cosa.agents.io_models.utils.xml_parser_factory import XmlParserFactory
from cosa.agents.iterative_debugging_agent import IterativeDebuggingAgent
from cosa.config.configuration_manager import ConfigurationManager
from cosa.utils import util as du


class TestIterativeDebuggingMinimalistResponse:
    """Test suite for IterativeDebuggingMinimalistResponse Pydantic model."""
    
    def test_minimalist_response_creation( self ):
        """Test basic IterativeDebuggingMinimalistResponse model creation and validation."""
        
        # Valid creation
        response = IterativeDebuggingMinimalistResponse(
            thoughts="The variable 'resut' should be 'result'",
            line_number=3,
            one_line_of_code="result = calculate_sum(a, b)",
            success="True"
        )
        
        assert response.thoughts == "The variable 'resut' should be 'result'"
        assert response.line_number == 3
        assert response.one_line_of_code == "result = calculate_sum(a, b)"
        assert response.success == "True"
        assert response.is_successful() == True
    
    def test_minimalist_response_validation( self ):
        """Test IterativeDebuggingMinimalistResponse field validation."""
        
        # Test line_number validation
        try:
            IterativeDebuggingMinimalistResponse(
                thoughts="test",
                line_number=0,  # Should fail
                one_line_of_code="test",
                success="True"
            )
            assert False, "Should have raised validation error for line_number=0"
        except ValueError:
            pass  # Expected
            
        # Test success validation
        try:
            IterativeDebuggingMinimalistResponse(
                thoughts="test",
                line_number=1,
                one_line_of_code="test",
                success="Maybe"  # Should fail
            )
            assert False, "Should have raised validation error for invalid success value"
        except ValueError:
            pass  # Expected
    
    def test_minimalist_response_from_xml( self ):
        """Test IterativeDebuggingMinimalistResponse.from_xml() parsing."""
        
        xml_response = '''<response>
            <thoughts>Missing import statement on line 1</thoughts>
            <line-number>1</line-number>
            <one-line-of-code>import math</one-line-of-code>
            <success>True</success>
        </response>'''
        
        response = IterativeDebuggingMinimalistResponse.from_xml( xml_response )
        
        assert response.thoughts == "Missing import statement on line 1"
        assert response.line_number == 1
        assert response.one_line_of_code == "import math"
        assert response.success == "True"
        assert response.is_successful() == True
    
    def test_minimalist_xml_tag_aliases( self ):
        """Test XML tag aliases (line-number → line_number, one-line-of-code → one_line_of_code)."""
        
        xml_with_hyphens = '''<response>
            <thoughts>Fix the variable declaration</thoughts>
            <line-number>5</line-number>
            <one-line-of-code>correct_variable = True</one-line-of-code>
            <success>False</success>
        </response>'''
        
        response = IterativeDebuggingMinimalistResponse.from_xml( xml_with_hyphens )
        
        # Verify field mapping works correctly
        assert response.line_number == 5
        assert response.one_line_of_code == "correct_variable = True"
        assert response.is_successful() == False
        
        # Verify model_dump() uses Python field names
        dumped = response.model_dump()
        assert "line_number" in dumped
        assert "one_line_of_code" in dumped
        assert "line-number" not in dumped
        assert "one-line-of-code" not in dumped


class TestIterativeDebuggingFullResponse:
    """Test suite for IterativeDebuggingFullResponse Pydantic model."""
    
    def test_full_response_creation( self ):
        """Test basic IterativeDebuggingFullResponse model creation and validation."""
        
        response = IterativeDebuggingFullResponse(
            thoughts="The function has incorrect logic in the calculation",
            code=["import math", "def calculate_area(r):", "    return math.pi * r * r"],
            example="area = calculate_area(5)",
            returns="float",
            explanation="Fixed by using math.pi instead of hardcoded 3.14"
        )
        
        assert "incorrect logic" in response.thoughts
        assert len( response.code ) == 3
        assert response.example == "area = calculate_area(5)"
        assert response.returns == "float"
        assert response.has_imports() == True
        assert response.get_function_name() == "calculate_area"
    
    def test_full_response_from_xml( self ):
        """Test IterativeDebuggingFullResponse.from_xml() parsing."""
        
        xml_response = '''<response>
            <thoughts>Function missing error handling and type checking</thoughts>
            <code>
                <line>def safe_divide(a, b):</line>
                <line>    if b == 0:</line>
                <line>        return None</line>
                <line>    return a / b</line>
            </code>
            <example>result = safe_divide(10, 2)</example>
            <returns>float or None</returns>
            <explanation>Added zero division check to prevent runtime errors</explanation>
        </response>'''
        
        response = IterativeDebuggingFullResponse.from_xml( xml_response )
        
        assert "error handling" in response.thoughts
        assert len( response.code ) == 4
        assert "safe_divide" in response.example
        assert "float or None" in response.returns
        assert "zero division check" in response.explanation
        assert response.get_function_name() == "safe_divide"
    
    def test_full_response_complex_code( self ):
        """Test IterativeDebuggingFullResponse with complex code structures."""
        
        xml_complex = '''<response>
            <thoughts>Multiple issues: missing imports, incorrect algorithm, no error handling</thoughts>
            <code>
                <line>import math</line>
                <line>import sys</line>
                <line></line>
                <line>def improved_calculation(values):</line>
                <line>    if not values:</line>
                <line>        return 0</line>
                <line>    return sum(math.sqrt(x) for x in values if x >= 0)</line>
            </code>
            <example>result = improved_calculation([1, 4, 9, 16])</example>
            <returns>float</returns>
            <explanation>Added input validation, proper imports, and handled negative values</explanation>
        </response>'''
        
        response = IterativeDebuggingFullResponse.from_xml( xml_complex )
        
        assert len( response.code ) == 7
        assert response.has_imports() == True
        assert "" in response.code  # Empty line preserved
        assert response.get_function_name() == "improved_calculation"
        
        # Test utility methods
        code_string = response.get_code_as_string()
        assert "import math" in code_string
        assert "def improved_calculation" in code_string


class TestIterativeDebuggingFactoryIntegration:
    """Test suite for IterativeDebuggingAgent integration with XmlParserFactory."""
    
    def setup_method( self ):
        """Set up test environment."""
        self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self.factory = XmlParserFactory( self.config_mgr )
    
    def test_factory_dynamic_model_selection( self ):
        """
        The factory's Pydantic parser dynamically selects the debugging model from XML tag names.

        ( Repaired 2026-05-31: get_parser_strategy()/get_strategy_name() were REMOVED in the
        Session-116 refactor; the dynamic-selection logic now lives on the single PydanticXmlParser
        accessed via factory._parser. The meaningful assertion — tag-driven model selection — is
        preserved against the current API. )
        """
        parser = self.factory._parser

        # minimalist-mode tags → minimalist model
        minimalist_tags = [ "thoughts", "line-number", "one-line-of-code", "success" ]
        assert parser._get_debugging_model( minimalist_tags ) is IterativeDebuggingMinimalistResponse

        # full-mode tags → full model
        full_tags = [ "thoughts", "code", "example", "returns", "explanation" ]
        assert parser._get_debugging_model( full_tags ) is IterativeDebuggingFullResponse
    
    def test_factory_minimalist_debugging_parsing( self ):
        """Test factory parsing of minimalist debugging XML responses."""
        
        xml_response = '''<response>
            <thoughts>Variable typo on line 2</thoughts>
            <line-number>2</line-number>
            <one-line-of-code>result = calculate_total(items)</one-line-of-code>
            <success>True</success>
        </response>'''
        
        result = self.factory.parse_agent_response(
            xml_response,
            "agent router go to debugger",
            [ "thoughts", "line-number", "one-line-of-code", "success" ]
        )
        
        assert isinstance( result, dict )
        assert result[ "line_number" ] == 2  # Note: Python field name
        assert result[ "one_line_of_code" ] == "result = calculate_total(items)"
        assert result[ "success" ] == "True"
    
    def test_factory_full_debugging_parsing( self ):
        """Test factory parsing of full debugging XML responses."""
        
        xml_response = '''<response>
            <thoughts>Complete rewrite needed for better error handling</thoughts>
            <code>
                <line>try:</line>
                <line>    result = risky_operation()</line>
                <line>except Exception as e:</line>
                <line>    print(f"Error: {e}")</line>
                <line>    result = None</line>
            </code>
            <example>safe_result = handle_operation()</example>
            <returns>any or None</returns>
            <explanation>Wrapped risky operation in try-except block for safety</explanation>
        </response>'''
        
        result = self.factory.parse_agent_response(
            xml_response,
            "agent router go to debugger",
            [ "thoughts", "code", "example", "returns", "explanation" ]
        )
        
        assert isinstance( result, dict )
        assert len( result[ "code" ] ) == 5
        assert "try:" in result[ "code" ]
        assert "risky operation" in result[ "explanation" ]
    
    def test_factory_error_handling( self ):
        """Test factory handling of malformed debugging responses."""
        
        xml_invalid = '''<response>
            <thoughts>Invalid response test</thoughts>
            <line-number>not_a_number</line-number>
            <one-line-of-code>test code</one-line-of-code>
            <success>True</success>
        </response>'''
        
        # Should raise validation error for invalid line number
        # ROW beffcddd — this used to read:
        #     try:
        #         self.factory.parse_agent_response( ... )
        #         assert False, "Should have raised validation error for invalid line number"
        #     except Exception:
        #         pass  # Expected validation error
        # AssertionError IS an Exception, so when the parser did NOT raise, the
        # `assert False` was caught by the very handler below it and the test went
        # green. It could not fail for the reason it names. pytest.raises does what
        # the old shape was trying to say, and fails loudly when nothing is raised.
        #
        # NARROWED to XMLParsingError deliberately: `pytest.raises( Exception )` would
        # pass on a TypeError from a bad call signature or an ImportError from a moved
        # module — i.e. it would go green while proving the parser was never reached.
        with pytest.raises( XMLParsingError ):
            self.factory.parse_agent_response(
                xml_invalid,
                "agent router go to debugger",
                [ "thoughts", "line-number", "one-line-of-code", "success" ]
            )


class TestIterativeDebuggingAgentMigration:
    """Test suite for full IterativeDebuggingAgent migration integration."""
    
    def setup_method( self ):
        """Set up test environment with temporary code file."""
        self.project_root = du.get_project_root()
        self.test_file_path = os.path.join( self.project_root, "test_debug_integration.py" )
        
        test_code = '''def buggy_function(x, y):
    return x + z  # Bug: z is undefined
    
result = buggy_function(1, 2)
print(result)
'''
        with open( self.test_file_path, 'w' ) as f:
            f.write( test_code )
    
    def teardown_method( self ):
        """Clean up test files."""
        if os.path.exists( self.test_file_path ):
            os.remove( self.test_file_path )
    
    def test_debugging_agent_creation_with_factory( self ):
        """Test IterativeDebuggingAgent creation uses factory system."""
        
        agent = IterativeDebuggingAgent(
            error_message="NameError: name 'z' is not defined",
            path_to_code="/test_debug_integration.py",
            example="buggy_function(1, 2)",
            returns="int",
            minimalist=True,
            debug=False,
            verbose=False
        )
        
        assert agent.routing_command == "agent router go to debugger"
        assert hasattr( agent, 'xml_parser_factory' )
        assert agent.minimalist == True
        assert agent.xml_response_tag_names == [ "thoughts", "line-number", "one-line-of-code", "success" ]
    
    def test_debugging_agent_full_mode( self ):
        """Test IterativeDebuggingAgent in full mode."""
        
        agent = IterativeDebuggingAgent(
            error_message="Logic error in calculation",
            path_to_code="/test_debug_integration.py",
            example="buggy_function(1, 2)",
            returns="int",
            minimalist=False,
            debug=False,
            verbose=False
        )
        
        assert agent.minimalist == False
        assert agent.xml_response_tag_names == [ "thoughts", "code", "example", "returns", "explanation" ]
    
    def test_patch_code_accepts_both_field_naming_conventions( self ):
        """
        _patch_code_in_response_dict must handle Pydantic field names AND the
        baseline hyphenated ones, and patch the SAME line either way.

        ROW beffcddd — WHAT THIS REPLACED AND WHY. The old test read:

            try:
                agent.prompt_response_dict = { "code": [ "line1", "line2", "line3" ] }
                # We can't easily test this without mocking, but the integration
                # test validates it works
                assert True
            except Exception as e:
                assert False, f"Field compatibility test failed: {e}"

        It asserted NOTHING. `assert True` is a no-op, and the method it names was
        never called — the test only assigned a dict and declared victory. The
        handler was dead twice over: nothing inside could raise, and had it raised,
        `assert False` was itself an Exception the same handler would have caught.

        ⇒ AND THE STATED REASON DID NOT SURVIVE CHECKING. "We can't easily test this
        without mocking" — the method reads exactly two file helpers and then indexes
        a list. Two patches and it drives. Same pattern as the TFE dead-queue pair in
        row 122f07a1: a weak test sitting next to a justification nobody re-checked.
        """
        agent = IterativeDebuggingAgent(
            error_message = "Test error",
            path_to_code  = "/test_debug_integration.py",
            minimalist    = True,
            debug         = False
        )

        original = [ "def f( x, y ):", "    return x + z", "" ]
        patched  = "    return x + y  # Fixed: use y instead of z"

        import cosa.agents.iterative_debugging_agent as ida

        def _run( response_dict ):
            """Drive the method over a stubbed file and return the resulting code list."""
            with patch.object( ida.du, "get_file_as_list", return_value=list( original ) ), \
                 patch.object( ida.du, "get_file_as_source_code_with_line_numbers", return_value="" ):
                agent.prompt_response_dict = { }
                agent._patch_code_in_response_dict( response_dict )
            return agent.prompt_response_dict[ "code" ]

        # Pydantic spelling: line_number / one_line_of_code
        pydantic_result = _run( { "line_number": 2, "one_line_of_code": patched } )

        # Baseline spelling: line-number / one-line-of-code, as a STRING line number
        baseline_result = _run( { "line-number": "2", "one-line-of-code": patched } )

        assert pydantic_result[ 1 ] == patched, (
            f"the Pydantic field names did not reach the patch; line 2 is "
            f"{pydantic_result[ 1 ]!r}"
        )
        assert baseline_result == pydantic_result, (
            f"the two naming conventions patched different things — that is the "
            f"compatibility this test exists to pin.\n  pydantic={pydantic_result}\n"
            f"  baseline={baseline_result}"
        )
        # The line-number is 1-BASED on the wire and 0-based in the list; a silent
        # off-by-one would leave line 1 or line 3 rewritten instead.
        assert pydantic_result[ 0 ] == original[ 0 ], "line 1 was rewritten — off-by-one"
        assert pydantic_result[ 2 ] == original[ 2 ], "line 3 was rewritten — off-by-one"


def run_iterative_debugging_migration_tests():
    """
    Run comprehensive IterativeDebuggingAgent migration test suite.
    
    Returns:
        bool: True if all tests pass, False otherwise
    """
    import cosa.utils.util as du
    
    du.print_banner( "IterativeDebuggingAgent Migration Test Suite", prepend_nl=True )
    
    test_results = {
        "IterativeDebuggingMinimalistResponse Model Tests": False,
        "IterativeDebuggingFullResponse Model Tests": False,
        "Factory Integration Tests": False,
        "Full Migration Integration Tests": False
    }
    
    try:
        # Test 1: Minimalist response model
        print( "Testing IterativeDebuggingMinimalistResponse Pydantic model..." )
        
        # Basic creation
        response = IterativeDebuggingMinimalistResponse(
            thoughts="Variable typo needs fixing",
            line_number=3,
            one_line_of_code="corrected_variable = value",
            success="True"
        )
        assert response.line_number == 3
        assert response.is_successful() == True
        
        # XML parsing
        xml = '''<response><thoughts>Test</thoughts><line-number>1</line-number><one-line-of-code>test</one-line-of-code><success>False</success></response>'''
        response = IterativeDebuggingMinimalistResponse.from_xml( xml )
        assert response.line_number == 1
        assert response.is_successful() == False
        
        test_results[ "IterativeDebuggingMinimalistResponse Model Tests" ] = True
        print( "✓ IterativeDebuggingMinimalistResponse model tests passed" )
        
    except Exception as e:
        print( f"✗ IterativeDebuggingMinimalistResponse model tests failed: {e}" )
    
    try:
        # Test 2: Full response model
        print( "Testing IterativeDebuggingFullResponse Pydantic model..." )
        
        # Basic creation
        response = IterativeDebuggingFullResponse(
            thoughts="Complete refactor needed",
            code=["import os", "def test():", "    return True"],
            example="result = test()",
            returns="bool",
            explanation="Fixed logic errors"
        )
        assert len( response.code ) == 3
        assert response.get_function_name() == "test"
        
        test_results[ "IterativeDebuggingFullResponse Model Tests" ] = True
        print( "✓ IterativeDebuggingFullResponse model tests passed" )
        
    except Exception as e:
        print( f"✗ IterativeDebuggingFullResponse model tests failed: {e}" )
    
    try:
        # Test 3: Factory integration
        print( "Testing factory integration..." )
        
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        factory = XmlParserFactory( config_mgr )
        
        # Test minimalist parsing
        xml_min = '''<response><thoughts>Test</thoughts><line-number>1</line-number><one-line-of-code>fixed</one-line-of-code><success>True</success></response>'''
        result = factory.parse_agent_response(
            xml_min, "agent router go to debugger", 
            [ "thoughts", "line-number", "one-line-of-code", "success" ]
        )
        assert result[ "line_number" ] == 1
        assert result[ "success" ] == "True"
        
        # Test full parsing
        xml_full = '''<response><thoughts>Test</thoughts><code><line>test</line></code><example>test()</example><returns>None</returns><explanation>Test</explanation></response>'''
        result = factory.parse_agent_response(
            xml_full, "agent router go to debugger",
            [ "thoughts", "code", "example", "returns", "explanation" ]
        )
        assert len( result[ "code" ] ) == 1
        
        test_results[ "Factory Integration Tests" ] = True
        print( "✓ Factory integration tests passed" )
        
    except Exception as e:
        print( f"✗ Factory integration tests failed: {e}" )
    
    try:
        # Test 4: Full agent integration
        print( "Testing full IterativeDebuggingAgent migration..." )
        
        # Create temporary test file
        project_root = du.get_project_root()
        test_file = os.path.join( project_root, "temp_debug_test.py" )
        
        with open( test_file, 'w' ) as f:
            f.write( "def test():\n    return undefined_var\n" )
        
        try:
            agent = IterativeDebuggingAgent(
                error_message="NameError: name 'undefined_var' is not defined",
                path_to_code="/temp_debug_test.py",
                minimalist=True,
                debug=False
            )
            
            assert agent.routing_command == "agent router go to debugger"
            assert hasattr( agent, 'xml_parser_factory' )
            
        finally:
            if os.path.exists( test_file ):
                os.remove( test_file )
        
        test_results[ "Full Migration Integration Tests" ] = True
        print( "✓ Full migration integration tests passed" )
        
    except Exception as e:
        print( f"✗ Full migration integration tests failed: {e}" )
    
    # Summary
    passed_tests = sum( test_results.values() )
    total_tests = len( test_results )
    
    print( f"\n{'='*70}" )
    print( f"IterativeDebuggingAgent Migration Test Results: {passed_tests}/{total_tests} passed" )
    
    for test_name, passed in test_results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print( f"  {test_name}: {status}" )
    
    if passed_tests == total_tests:
        print( "\n🎉 All IterativeDebuggingAgent migration tests PASSED!" )
        return True
    else:
        print( f"\n❌ {total_tests - passed_tests} IterativeDebuggingAgent migration tests FAILED" )
        return False


if __name__ == "__main__":
    # Run tests when executed directly
    success = run_iterative_debugging_migration_tests()
    exit( 0 if success else 1 )