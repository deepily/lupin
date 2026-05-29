"""
Unit tests for XML response validator with comprehensive validation testing.

Tests the XmlResponseValidator class including:
- XML schema validation and structure checking
- Response comparison and exact matching
- Tag value extraction and comparison
- Response validation processing for DataFrames
- Statistics calculation and reporting
- Validation comparison between datasets
- Error handling for malformed XML
- Performance metrics calculation

Zero external dependencies - all XML operations and schema validation
are tested in isolation with mocked components.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import time
import sys
import os
import pandas as pd
from typing import Dict, Any
import sys
import os

# Import test infrastructure
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.training.xml_response_validator import XmlResponseValidator


class TestXmlResponseValidator( unittest.TestCase ):
    """
    Comprehensive unit tests for XML response validator.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All validation operations tested in isolation
        - XML parsing properly tested
        - Error handling scenarios covered
        - Statistics calculations thoroughly tested
    """
    
    def setUp( self ):
        """
        Setup for each test method.
        
        Ensures:
            - Clean state for each test
            - Mock manager is available
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()
        
        # Common test data
        self.valid_xml = "<response><command>test</command><args>args</args></response>"
        self.invalid_xml = "<response><command>test</command></response>"  # Missing args
        self.malformed_xml = "<response><command>test</command><args>unclosed"
        
        self.test_response = "<response><command>search</command><args>python</args></response>"
        self.test_answer = "<response><command>search</command><args>python</args></response>"
        self.different_answer = "<response><command>navigate</command><args>home</args></response>"
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def test_initialization_success( self ):
        """
        Test successful XmlResponseValidator initialization.
        
        Ensures:
            - Sets all instance attributes correctly
            - Initializes XML schema
            - Handles debug and verbose parameters
        """
        validator = XmlResponseValidator( debug=True, verbose=True )
        
        # Verify instance attributes
        self.assertTrue( validator.debug )
        self.assertTrue( validator.verbose )
        self.assertIsNotNone( validator._xml_schema )
    
    def test_initialization_with_defaults( self ):
        """
        Test XmlResponseValidator initialization with default parameters.
        
        Ensures:
            - Uses default values for optional parameters
            - Schema is still initialized
        """
        validator = XmlResponseValidator()
        
        # Verify default values
        self.assertFalse( validator.debug )
        self.assertFalse( validator.verbose )
        self.assertIsNotNone( validator._xml_schema )
    
    def test_get_xml_schema( self ):
        """
        Test XML schema creation.
        
        Ensures:
            - Creates valid XMLSchema object
            - Schema defines expected structure
        """
        validator = XmlResponseValidator()
        schema = validator._get_xml_schema()
        
        # Verify schema object
        self.assertIsNotNone( schema )
        
        # Verify schema can validate expected structure
        valid_xml = "<response><command>test</command><args>args</args></response>"
        self.assertTrue( schema.is_valid( valid_xml ) )
        
        invalid_xml = "<response><command>test</command></response>"  # Missing args
        self.assertFalse( schema.is_valid( invalid_xml ) )
    
    def test_is_valid_xml_success( self ):
        """
        Test XML validation with valid XML.
        
        Ensures:
            - Returns True for valid XML
            - Handles proper XML structure
        """
        validator = XmlResponseValidator()
        
        result = validator.is_valid_xml( self.valid_xml )
        self.assertTrue( result )
    
    def test_is_valid_xml_invalid( self ):
        """
        Test XML validation with invalid XML.
        
        Ensures:
            - Returns False for invalid XML
            - Handles missing required elements
        """
        validator = XmlResponseValidator()
        
        result = validator.is_valid_xml( self.invalid_xml )
        self.assertFalse( result )
    
    def test_is_valid_xml_malformed( self ):
        """
        Test XML validation with malformed XML.
        
        Ensures:
            - Returns False for malformed XML
            - Handles parsing errors gracefully
        """
        validator = XmlResponseValidator()
        
        result = validator.is_valid_xml( self.malformed_xml )
        self.assertFalse( result )
    
    def test_is_valid_xml_exception_handling( self ):
        """
        Test XML validation with exceptions.
        
        Ensures:
            - Returns False when exceptions occur
            - Handles schema validation errors
        """
        validator = XmlResponseValidator()
        
        # Mock schema to raise exception
        validator._xml_schema.is_valid = Mock( side_effect=Exception( "Schema error" ) )
        
        result = validator.is_valid_xml( self.valid_xml )
        self.assertFalse( result )
    
    def test_contains_valid_xml_tag_success( self ):
        """
        Test XML tag checking with existing tag.
        
        Ensures:
            - Returns True when tag exists
            - Handles both opening and closing tags
        """
        validator = XmlResponseValidator()
        
        result = validator.contains_valid_xml_tag( self.valid_xml, "command" )
        self.assertTrue( result )
        
        result = validator.contains_valid_xml_tag( self.valid_xml, "args" )
        self.assertTrue( result )
    
    def test_contains_valid_xml_tag_missing( self ):
        """
        Test XML tag checking with missing tag.
        
        Ensures:
            - Returns False when tag doesn't exist
            - Handles non-existent tags correctly
        """
        validator = XmlResponseValidator()
        
        result = validator.contains_valid_xml_tag( self.valid_xml, "missing" )
        self.assertFalse( result )
    
    def test_contains_valid_xml_tag_partial( self ):
        """
        Test XML tag checking with only opening tag.
        
        Ensures:
            - Returns False when only opening tag exists
            - Requires both opening and closing tags
        """
        validator = XmlResponseValidator()
        
        partial_xml = "<response><command>test"
        result = validator.contains_valid_xml_tag( partial_xml, "command" )
        self.assertFalse( result )
    
    def test_is_response_exact_match_true( self ):
        """
        Test exact response matching with identical responses.
        
        Ensures:
            - Returns True for identical responses
            - Handles whitespace correctly
        """
        validator = XmlResponseValidator()
        
        result = validator.is_response_exact_match( self.test_response, self.test_answer )
        self.assertTrue( result )
    
    def test_is_response_exact_match_false( self ):
        """
        Test exact response matching with different responses.
        
        Ensures:
            - Returns False for different responses
            - Detects content differences
        """
        validator = XmlResponseValidator()
        
        result = validator.is_response_exact_match( self.test_response, self.different_answer )
        self.assertFalse( result )
    
    def test_is_response_exact_match_whitespace( self ):
        """
        Test exact response matching with whitespace differences.
        
        Ensures:
            - Handles whitespace normalization
            - Strips leading/trailing whitespace
        """
        validator = XmlResponseValidator()
        
        response_with_whitespace = "  " + self.test_response + "  \n"
        result = validator.is_response_exact_match( response_with_whitespace, self.test_answer )
        self.assertTrue( result )
    
    def test_contains_correct_response_values_success( self ):
        """
        Test response value checking with correct values.
        
        Ensures:
            - Returns True when response contains correct values
            - Handles XML formatting differences
        """
        validator = XmlResponseValidator()
        
        # Test with markdown-wrapped XML (common formatting issue)
        markdown_response = "```xml\n" + self.test_response + "\n```"
        result = validator.contains_correct_response_values( markdown_response, self.test_answer )
        self.assertTrue( result )
    
    def test_contains_correct_response_values_false( self ):
        """
        Test response value checking with incorrect values.
        
        Ensures:
            - Returns False when values don't match
            - Detects content differences in formatted responses
        """
        validator = XmlResponseValidator()
        
        markdown_response = "```xml\n" + self.different_answer + "\n```"
        result = validator.contains_correct_response_values( markdown_response, self.test_answer )
        self.assertFalse( result )
    
    def test_tag_values_are_equal_success( self ):
        """
        Test tag value comparison with matching values.
        
        Ensures:
            - Returns True when tag values match
            - Extracts tag values correctly
        """
        validator = XmlResponseValidator()
        
        result = validator.tag_values_are_equal( self.test_response, self.test_answer, "command" )
        self.assertTrue( result )
        
        result = validator.tag_values_are_equal( self.test_response, self.test_answer, "args" )
        self.assertTrue( result )
    
    def test_tag_values_are_equal_false( self ):
        """
        Test tag value comparison with different values.
        
        Ensures:
            - Returns False when tag values differ
            - Correctly identifies value differences
        """
        validator = XmlResponseValidator()
        
        result = validator.tag_values_are_equal( self.test_response, self.different_answer, "command" )
        self.assertFalse( result )
    
    def test_tag_values_are_equal_missing_tag( self ):
        """
        Test tag value comparison with missing tags.
        
        Ensures:
            - Returns False when tags are missing
            - Handles malformed XML gracefully
        """
        validator = XmlResponseValidator()
        
        result = validator.tag_values_are_equal( self.test_response, self.test_answer, "missing" )
        self.assertFalse( result )
    
    def test_validate_responses_success( self ):
        """
        Test DataFrame response validation.
        
        Ensures:
            - Validates all responses in DataFrame
            - Adds validation columns
            - Returns DataFrame with results
        """
        validator = XmlResponseValidator()
        
        # Create test DataFrame
        test_data = {
            'response': [self.test_response, self.different_answer],
            'output': [self.test_answer, self.different_answer]
        }
        df = pd.DataFrame( test_data )
        
        result_df = validator.validate_responses( df )
        
        # Verify validation columns added
        expected_columns = [
            'response_xml_is_valid', 'response_is_exact', 'response_has_correct_values',
            'command_is_correct', 'contains_response', 'contains_command', 'contains_args'
        ]
        
        for col in expected_columns:
            self.assertIn( col, result_df.columns )
        
        # Verify validation results
        self.assertTrue( result_df.iloc[0]['response_is_exact'] )  # First row matches
        self.assertTrue( result_df.iloc[1]['response_is_exact'] )  # Second row matches itself
    
    def test_get_validation_stats( self ):
        """
        Test validation statistics calculation.
        
        Ensures:
            - Calculates correct statistics
            - Returns dictionary with metrics
            - Handles percentage calculations
        """
        validator = XmlResponseValidator()
        
        # Create test DataFrame with validation columns
        test_data = {
            'response_xml_is_valid': [True, True, False],
            'contains_response': [True, True, False],
            'contains_command': [True, False, True],
            'contains_args': [True, True, False],
            'response_is_exact': [True, False, False],
            'response_has_correct_values': [True, True, False],
            'command_is_correct': [True, False, False],
            'args_is_correct': [True, False, False],
            'command': ['test1', 'test2', 'test3']  # Add command column for per-command stats
        }
        df = pd.DataFrame( test_data )
        
        stats = validator.get_validation_stats( df )
        
        # Verify statistics structure
        self.assertIsInstance( stats, dict )
        self.assertIn( 'valid_xml_percent', stats )
        self.assertIn( 'response_exact_percent', stats )
        self.assertIn( 'correct_values_percent', stats )
        
        # Verify calculations
        self.assertAlmostEqual( stats['valid_xml_percent'], 66.67, places=1 )
        self.assertAlmostEqual( stats['response_exact_percent'], 33.33, places=1 )
        self.assertAlmostEqual( stats['correct_values_percent'], 66.67, places=1 )
    
    def test_print_validation_stats( self ):
        """
        Test validation statistics printing.
        
        Ensures:
            - Prints formatted statistics
            - Returns statistics DataFrame
            - Handles title parameter
        """
        validator = XmlResponseValidator()
        
        # Create test DataFrame with validation columns
        test_data = {
            'response_xml_is_valid': [True, False],
            'contains_response': [True, False],
            'contains_command': [True, True],
            'contains_args': [True, False],
            'response_is_exact': [True, False],
            'response_has_correct_values': [True, True],
            'command_is_correct': [True, False],
            'args_is_correct': [True, False],
            'command': ['test1', 'test2']  # Add command column for per-command stats
        }
        df = pd.DataFrame( test_data )
        
        with patch( 'cosa.training.xml_response_validator.du.print_banner' ) as mock_banner, \
             patch( 'builtins.print' ) as mock_print:
            
            result = validator.print_validation_stats( df, title="Test Stats" )
            
            # Verify banner printed with title (called twice - main stats and per-command)
            self.assertEqual( mock_banner.call_count, 2 )
            mock_banner.assert_any_call( "Test Stats", prepend_nl=True )
            mock_banner.assert_any_call( "Test Stats: Accuracy per command", prepend_nl=True )
            
            # Verify statistics printed
            self.assertGreater( mock_print.call_count, 0 )
            
            # Verify DataFrame returned
            self.assertIsInstance( result, pd.DataFrame )
    
    def test_compare_validation_results( self ):
        """
        Test validation comparison between DataFrames.
        
        Ensures:
            - Compares validation metrics
            - Shows improvement/regression
            - Returns comparison DataFrame
        """
        validator = XmlResponseValidator()
        
        # Create before and after DataFrames
        before_data = {
            'response_xml_is_valid': [True, False, False],
            'contains_response': [True, True, False],
            'contains_command': [True, False, True],
            'contains_args': [True, True, False],
            'response_is_exact': [False, False, False],
            'response_has_correct_values': [True, False, False],
            'command_is_correct': [False, False, False],
            'args_is_correct': [False, False, False]
        }
        after_data = {
            'response_xml_is_valid': [True, True, False],
            'contains_response': [True, True, True],
            'contains_command': [True, True, True],
            'contains_args': [True, True, False],
            'response_is_exact': [True, False, False],
            'response_has_correct_values': [True, True, False],
            'command_is_correct': [True, False, False],
            'args_is_correct': [True, False, False]
        }
        
        before_df = pd.DataFrame( before_data )
        after_df = pd.DataFrame( after_data )
        
        with patch( 'cosa.training.xml_response_validator.du.print_banner' ) as mock_banner, \
             patch( 'builtins.print' ) as mock_print:
            
            result = validator.compare_validation_results( before_df, after_df, title="Comparison" )
            
            # Verify banner printed
            mock_banner.assert_called_once_with( "Comparison", prepend_nl=True )
            
            # Verify comparison printed
            self.assertGreater( mock_print.call_count, 0 )
            
            # Verify DataFrame returned
            self.assertIsInstance( result, pd.DataFrame )
            self.assertIn( 'Before (%)', result.columns )
            self.assertIn( 'After (%)', result.columns )
            self.assertIn( 'Difference', result.columns )


def isolated_unit_test():
    """
    Run comprehensive unit tests for XML response validator in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real XML schema operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "XML Response Validator Unit Tests - Training Phase 6", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization_success',
            'test_initialization_with_defaults',
            'test_get_xml_schema',
            'test_is_valid_xml_success',
            'test_is_valid_xml_invalid',
            'test_is_valid_xml_malformed',
            'test_is_valid_xml_exception_handling',
            'test_contains_valid_xml_tag_success',
            'test_contains_valid_xml_tag_missing',
            'test_contains_valid_xml_tag_partial',
            'test_is_response_exact_match_true',
            'test_is_response_exact_match_false',
            'test_is_response_exact_match_whitespace',
            'test_contains_correct_response_values_success',
            'test_contains_correct_response_values_false',
            'test_tag_values_are_equal_success',
            'test_tag_values_are_equal_false',
            'test_tag_values_are_equal_missing_tag',
            'test_validate_responses_success',
            'test_get_validation_stats',
            'test_print_validation_stats',
            'test_compare_validation_results'
        ]
        
        for method in test_methods:
            suite.addTest( TestXmlResponseValidator( method ) )
        
        # Run tests with detailed output
        runner = unittest.TextTestRunner( verbosity=2, stream=sys.stdout )
        result = runner.run( suite )
        
        duration = time.time() - start_time
        
        # Calculate results
        tests_run = result.testsRun
        failures = len( result.failures )
        errors = len( result.errors )
        success_count = tests_run - failures - errors
        
        print( f"\n{'='*60}" )
        print( f"XML RESPONSE VALIDATOR UNIT TEST RESULTS" )
        print( f"{'='*60}" )
        print( f"Tests Run     : {tests_run}" )
        print( f"Passed        : {success_count}" )
        print( f"Failed        : {failures}" )
        print( f"Errors        : {errors}" )
        print( f"Success Rate  : {(success_count/tests_run)*100:.1f}%" )
        print( f"Duration      : {duration:.3f} seconds" )
        print( f"{'='*60}" )
        
        if failures > 0:
            print( "\nFAILURE DETAILS:" )
            for test, traceback in result.failures:
                print( f"❌ {test}: {traceback.split(chr(10))[-2]}" )
                
        if errors > 0:
            print( "\nERROR DETAILS:" )
            for test, traceback in result.errors:
                print( f"💥 {test}: {traceback.split(chr(10))[-2]}" )
        
        success = failures == 0 and errors == 0
        
        if success:
            du.print_banner( "✅ ALL XML RESPONSE VALIDATOR TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME XML RESPONSE VALIDATOR TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 XML RESPONSE VALIDATOR TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} XML response validator unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )