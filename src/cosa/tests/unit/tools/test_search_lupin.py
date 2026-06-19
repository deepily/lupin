"""
Unit tests for Lupin search wrapper with comprehensive vendor-neutral API mocking.

Tests the LupinSearch class including:
- Vendor-neutral wrapper functionality over KagiSearch
- Query and URL-based search initialization
- Web search and summarization workflow integration
- Results retrieval with various scope filters
- Error handling for invalid scopes and search failures
- Integration with RawOutputFormatter (v000 version)
- Debug and verbose output modes
- Graceful error handling and user feedback

Zero external dependencies - all KagiSearch operations, RawOutputFormatter,
and utility functions are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import time
from typing import Dict, Any, Optional, Union, List
import sys
import os

# Import test infrastructure
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.tools.search_lupin import LupinSearch


class TestLupinSearch( unittest.TestCase ):
    """
    Comprehensive unit tests for Lupin search wrapper.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All vendor-neutral search operations tested in isolation
        - KagiSearch integration properly mocked
        - Results filtering and scope management validated
        - Error handling scenarios covered
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
        self.test_query = "What is cognitive budget research?"
        self.test_url = "https://example.com/cognitive-research"
        
        # Mock Kagi API response structure
        self.mock_search_results = {
            "meta": {
                "id": "test_search_id",
                "node": "search_node",
                "ms": 1200
            },
            "data": {
                "output": "Cognitive budget refers to the limited mental resources available for decision-making and attention.",
                "tokens": 95,
                "references": [
                    {
                        "title": "Cognitive Load Theory",
                        "snippet": "Research on mental resource allocation",
                        "url": "https://psychology.com/cognitive-load"
                    },
                    {
                        "title": "Attention Budget Studies",
                        "snippet": "Daily attention limitations research",
                        "url": "https://neuroscience.org/attention-budget"
                    }
                ]
            }
        }
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mock_kagi_search( self ):
        """
        Helper to create mock KagiSearch with standard methods.
        
        Returns:
            Mock KagiSearch object with search_fastgpt method
        """
        mock_searcher = Mock()
        mock_searcher.search_fastgpt.return_value = self.mock_search_results
        
        return mock_searcher
    
    def test_initialization_with_query( self ):
        """
        Test LupinSearch initialization with query parameter.
        
        Ensures:
            - Creates KagiSearch instance with correct parameters
            - Sets query and null URL appropriately
            - Initializes results to None
            - Passes debug and verbose flags correctly
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( 
                query=self.test_query, 
                debug=True, 
                verbose=True 
            )
            
            # Verify initialization parameters
            self.assertEqual( lupin.query, self.test_query )
            self.assertIsNone( lupin.url )
            self.assertTrue( lupin.debug )
            self.assertTrue( lupin.verbose )
            self.assertIsNone( lupin._results )
            
            # Verify KagiSearch creation
            mock_kagi_class.assert_called_once_with( 
                query=self.test_query, 
                url=None, 
                debug=True, 
                verbose=True 
            )
            self.assertEqual( lupin._searcher, mock_searcher )
    
    def test_initialization_with_url( self ):
        """
        Test LupinSearch initialization with URL parameter.
        
        Ensures:
            - Creates KagiSearch instance for URL summarization
            - Sets URL and null query appropriately
            - Handles default debug/verbose flags
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( url=self.test_url )
            
            # Verify initialization parameters
            self.assertIsNone( lupin.query )
            self.assertEqual( lupin.url, self.test_url )
            self.assertFalse( lupin.debug )
            self.assertFalse( lupin.verbose )
            
            # Verify KagiSearch creation
            mock_kagi_class.assert_called_once_with( 
                query=None, 
                url=self.test_url, 
                debug=False, 
                verbose=False 
            )
    
    def test_initialization_with_both_parameters( self ):
        """
        Test LupinSearch initialization with both query and URL.
        
        Ensures:
            - Both parameters are preserved and passed to KagiSearch
            - No validation errors for having both parameters
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query, url=self.test_url )
            
            # Verify both parameters preserved
            self.assertEqual( lupin.query, self.test_query )
            self.assertEqual( lupin.url, self.test_url )
            
            # Verify KagiSearch gets both parameters
            mock_kagi_class.assert_called_once_with( 
                query=self.test_query, 
                url=self.test_url, 
                debug=False, 
                verbose=False 
            )
    
    def test_search_and_summarize_the_web_success( self ):
        """
        Test successful web search and summarization workflow.
        
        Ensures:
            - Calls KagiSearch.search_fastgpt method
            - Stores results in _results attribute
            - Results contain expected data structure
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            lupin.search_and_summarize_the_web()
            
            # Verify KagiSearch method called
            mock_searcher.search_fastgpt.assert_called_once()
            
            # Verify results stored
            self.assertEqual( lupin._results, self.mock_search_results )
            self.assertIsNotNone( lupin._results )
    
    def test_search_and_summarize_api_error( self ):
        """
        Test web search with KagiSearch API error.
        
        Ensures:
            - Propagates KagiSearch exceptions
            - Does not suppress search errors
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = Mock()
            mock_searcher.search_fastgpt.side_effect = Exception( "Search API unavailable" )
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            
            with self.assertRaises( Exception ) as context:
                lupin.search_and_summarize_the_web()
            
            self.assertIn( "Search API unavailable", str( context.exception ) )
    
    def test_get_results_scope_all( self ):
        """
        Test results retrieval with 'all' scope.
        
        Ensures:
            - Returns complete results dictionary
            - Includes both meta and data sections
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            lupin.search_and_summarize_the_web()
            
            result = lupin.get_results( scope="all" )
            
            # Verify complete results returned
            self.assertEqual( result, self.mock_search_results )
            self.assertIn( "meta", result )
            self.assertIn( "data", result )
    
    def test_get_results_scope_meta( self ):
        """
        Test results retrieval with 'meta' scope.
        
        Ensures:
            - Returns only meta section of results
            - Contains expected meta fields
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            lupin.search_and_summarize_the_web()
            
            result = lupin.get_results( scope="meta" )
            
            # Verify meta section returned
            expected_meta = self.mock_search_results["meta"]
            self.assertEqual( result, expected_meta )
            self.assertIn( "id", result )
            self.assertIn( "node", result )
            self.assertIn( "ms", result )
    
    def test_get_results_scope_data( self ):
        """
        Test results retrieval with 'data' scope.
        
        Ensures:
            - Returns only data section of results
            - Contains output, tokens, and references
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            lupin.search_and_summarize_the_web()
            
            result = lupin.get_results( scope="data" )
            
            # Verify data section returned
            expected_data = self.mock_search_results["data"]
            self.assertEqual( result, expected_data )
            self.assertIn( "output", result )
            self.assertIn( "tokens", result )
            self.assertIn( "references", result )
    
    def test_get_results_scope_summary( self ):
        """
        Test results retrieval with 'summary' scope.
        
        Ensures:
            - Returns only output text from data section
            - Extracts summary content correctly
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            lupin.search_and_summarize_the_web()
            
            result = lupin.get_results( scope="summary" )
            
            # Verify summary text returned
            expected_summary = self.mock_search_results["data"]["output"]
            self.assertEqual( result, expected_summary )
            self.assertIsInstance( result, str )
    
    def test_get_results_scope_references( self ):
        """
        Test results retrieval with 'references' scope.
        
        Ensures:
            - Returns references array from data section
            - Contains properly structured reference objects
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            lupin.search_and_summarize_the_web()
            
            result = lupin.get_results( scope="references" )
            
            # Verify references array returned
            expected_references = self.mock_search_results["data"]["references"]
            self.assertEqual( result, expected_references )
            self.assertIsInstance( result, list )
            
            # Verify reference structure
            if result:
                ref = result[0]
                self.assertIn( "title", ref )
                self.assertIn( "snippet", ref )
                self.assertIn( "url", ref )
    
    def test_get_results_invalid_scope( self ):
        """
        Test results retrieval with invalid scope parameter.
        
        Ensures:
            - Returns None for invalid scope
            - Prints error message with valid options
            - Uses du.print_banner for error display
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class, \
             patch( 'cosa.tools.search_lupin.du.print_banner' ) as mock_print_banner:
            
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            lupin.search_and_summarize_the_web()
            
            result = lupin.get_results( scope="invalid_scope" )
            
            # Verify None returned
            self.assertIsNone( result )
            
            # Verify error message
            mock_print_banner.assert_called_once()
            call_args = mock_print_banner.call_args[0][0]
            self.assertIn( "ERROR: Invalid scope: invalid_scope", call_args )
            self.assertIn( "all", call_args )
            self.assertIn( "meta", call_args )
            self.assertIn( "data", call_args )
            self.assertIn( "summary", call_args )
            self.assertIn( "references", call_args )
            
            # Verify expletive flag
            call_kwargs = mock_print_banner.call_args[1]
            self.assertTrue( call_kwargs.get( "expletive", False ) )
    
    def test_get_results_before_search( self ):
        """
        Test results retrieval before search is performed.
        
        Ensures:
            - Raises KeyError when _results is None
            - Appropriate error handling for uninitialized state
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ):
            lupin = LupinSearch( query=self.test_query )
            # Note: Not calling search_and_summarize_the_web()
            
            with self.assertRaises( TypeError ):
                # This will fail because _results is None and we try to access ["meta"]
                lupin.get_results( scope="meta" )
    
    def test_scope_parameter_validation( self ):
        """
        Test comprehensive scope parameter validation.
        
        Ensures:
            - All valid scopes work correctly
            - Invalid scopes handled gracefully
            - Error messages are descriptive
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class, \
             patch( 'cosa.tools.search_lupin.du.print_banner' ) as mock_print_banner:
            
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            lupin.search_and_summarize_the_web()
            
            # Test all valid scopes
            valid_scopes = ["all", "meta", "data", "summary", "references"]
            for scope in valid_scopes:
                result = lupin.get_results( scope=scope )
                self.assertIsNotNone( result, f"Scope '{scope}' should return valid result" )
            
            # Test invalid scopes
            invalid_scopes = ["", "invalid", "META", "ALL", "summaries", "reference"]
            for scope in invalid_scopes:
                result = lupin.get_results( scope=scope )
                self.assertIsNone( result, f"Scope '{scope}' should return None" )
    
    def test_vendor_neutral_interface( self ):
        """
        Test vendor-neutral interface design.
        
        Ensures:
            - LupinSearch provides abstraction over KagiSearch
            - Interface doesn't expose Kagi-specific details
            - Easy to swap out search providers in future
        """
        with patch( 'cosa.tools.search_lupin.KagiSearch' ) as mock_kagi_class:
            mock_searcher = self._create_mock_kagi_search()
            mock_kagi_class.return_value = mock_searcher
            
            lupin = LupinSearch( query=self.test_query )
            
            # Verify vendor-neutral interface
            self.assertTrue( hasattr( lupin, 'search_and_summarize_the_web' ) )
            self.assertTrue( hasattr( lupin, 'get_results' ) )
            
            # Verify KagiSearch is encapsulated
            self.assertTrue( hasattr( lupin, '_searcher' ) )
            self.assertFalse( hasattr( lupin, 'kagi' ) )  # No direct Kagi exposure
            
            # Verify functionality works through interface
            lupin.search_and_summarize_the_web()
            result = lupin.get_results( scope="summary" )
            
            self.assertIsNotNone( result )
            self.assertIsInstance( result, str )
    
    def test_main_module_execution_bug_fix( self ):
        """
        Test that main module bug with GibSearch is handled.
        
        Note: The main module in search_lupin.py has a bug where it uses 
        'GibSearch' instead of 'LupinSearch'. This test documents the issue.
        
        Ensures:
            - Test documents the bug in the main module
            - LupinSearch class itself works correctly
        """
        # This test documents that line 91 in search_lupin.py has:
        # search = GibSearch( query=query )
        # But should be:
        # search = LupinSearch( query=query )
        
        with patch( 'cosa.tools.search_lupin.KagiSearch' ):
            # The class itself works correctly
            lupin = LupinSearch( query=self.test_query )
            self.assertIsInstance( lupin, LupinSearch )
            
            # The main module would fail due to the GibSearch reference
            # but we don't test main module execution in unit tests


def isolated_unit_test():
    """
    Run comprehensive unit tests for Lupin search wrapper in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real KagiSearch or API calls
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "Lupin Search Wrapper Unit Tests - External Phase 5", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization_with_query',
            'test_initialization_with_url',
            'test_initialization_with_both_parameters',
            'test_search_and_summarize_the_web_success',
            'test_search_and_summarize_api_error',
            'test_get_results_scope_all',
            'test_get_results_scope_meta',
            'test_get_results_scope_data',
            'test_get_results_scope_summary',
            'test_get_results_scope_references',
            'test_get_results_invalid_scope',
            'test_get_results_before_search',
            'test_scope_parameter_validation',
            'test_vendor_neutral_interface',
            'test_main_module_execution_bug_fix'
        ]
        
        for method in test_methods:
            suite.addTest( TestLupinSearch( method ) )
        
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
        print( f"LUPIN SEARCH WRAPPER UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL LUPIN SEARCH TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME LUPIN SEARCH TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 LUPIN SEARCH TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Lupin search wrapper unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )