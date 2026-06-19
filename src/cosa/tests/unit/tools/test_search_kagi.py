"""
Unit tests for Kagi search integration with comprehensive HTTP API mocking.

Tests the KagiSearch class including:
- Initialization with API key management
- FastGPT search functionality with query processing
- URL summarization with various summary engines
- Response data structure validation
- Error handling for API failures and network issues
- Debug and verbose output modes
- Stopwatch timing integration
- API key validation and security

Zero external dependencies - all Kagi API operations, HTTP requests,
and third-party integrations are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import time
from typing import Dict, Any, Optional
import sys
import os

# Import test infrastructure
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.tools.search_kagi import KagiSearch


class TestKagiSearch( unittest.TestCase ):
    """
    Comprehensive unit tests for Kagi search integration.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All Kagi API operations tested in isolation
        - HTTP client operations properly mocked
        - API key management and security validated
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
        self.test_query = "What is the weather in Washington DC?"
        self.test_url = "https://example.com/article"
        self.test_api_key = "test_kagi_api_key_123"
        
        # Mock Kagi API responses
        self.mock_fastgpt_response = {
            "meta": {
                "id": "test_request_id",
                "node": "test_node",
                "ms": 1500
            },
            "data": {
                "output": "The current weather in Washington DC is partly cloudy with a temperature of 72°F.",
                "tokens": 125,
                "references": [
                    {
                        "title": "Weather.com - Washington DC",
                        "snippet": "Current conditions for Washington DC",
                        "url": "https://weather.com/washington-dc"
                    }
                ]
            }
        }
        
        self.mock_summary_response = {
            "meta": {
                "id": "summary_request_id",
                "node": "test_node", 
                "ms": 800
            },
            "data": {
                "output": "This article discusses weather patterns in Washington DC during summer months.",
                "tokens": 85
            }
        }
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mock_kagi_client( self ):
        """
        Helper to create mock KagiClient with standard methods.
        
        Returns:
            Mock KagiClient object with fastgpt and summarize methods
        """
        mock_client = Mock()
        mock_client.fastgpt.return_value = self.mock_fastgpt_response
        mock_client.summarize.return_value = self.mock_summary_response
        
        return mock_client
    
    def test_initialization_with_query( self ):
        """
        Test KagiSearch initialization with query parameter.
        
        Ensures:
            - Creates instance with query and API key
            - Retrieves API key from utilities
            - Initializes KagiClient with correct key
            - Sets debug and verbose flags correctly
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ) as mock_client_class:
            
            mock_get_key.return_value = self.test_api_key
            mock_client_instance = self._create_mock_kagi_client()
            mock_client_class.return_value = mock_client_instance
            
            kagi = KagiSearch( 
                query=self.test_query, 
                debug=True, 
                verbose=True 
            )
            
            # Verify initialization parameters
            self.assertEqual( kagi.query, self.test_query )
            self.assertIsNone( kagi.url )
            self.assertTrue( kagi.debug )
            self.assertTrue( kagi.verbose )
            self.assertEqual( kagi._key, self.test_api_key )
            
            # Verify API key retrieval
            mock_get_key.assert_called_with( "kagi" )
            
            # Verify KagiClient initialization
            mock_client_class.assert_called_with( self.test_api_key )
            self.assertEqual( kagi._kagi, mock_client_instance )
    
    def test_initialization_with_url( self ):
        """
        Test KagiSearch initialization with URL parameter.
        
        Ensures:
            - Creates instance with URL for summarization
            - Sets query to None when URL provided
            - Handles default debug/verbose flags
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ) as mock_client_class:
            
            mock_get_key.return_value = self.test_api_key
            mock_client_instance = self._create_mock_kagi_client()
            mock_client_class.return_value = mock_client_instance
            
            kagi = KagiSearch( url=self.test_url )
            
            # Verify initialization parameters
            self.assertIsNone( kagi.query )
            self.assertEqual( kagi.url, self.test_url )
            self.assertFalse( kagi.debug )
            self.assertFalse( kagi.verbose )
    
    def test_initialization_api_key_error( self ):
        """
        Test KagiSearch initialization when API key is not found.
        
        Ensures:
            - Raises KeyError when API key retrieval fails
            - Error propagated from du.get_api_key
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key:
            mock_get_key.side_effect = KeyError( "API key 'kagi' not found" )
            
            with self.assertRaises( KeyError ):
                KagiSearch( query=self.test_query )
    
    def test_search_fastgpt_success( self ):
        """
        Test successful FastGPT search operation.
        
        Ensures:
            - Calls KagiClient.fastgpt with correct query
            - Returns complete response structure
            - Includes timing with Stopwatch
            - Processes meta and data sections correctly
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ) as mock_client_class, \
             patch( 'cosa.tools.search_kagi.Stopwatch' ) as mock_stopwatch_class:
            
            mock_get_key.return_value = self.test_api_key
            mock_client_instance = self._create_mock_kagi_client()
            mock_client_class.return_value = mock_client_instance
            
            mock_stopwatch = Mock()
            mock_stopwatch_class.return_value = mock_stopwatch
            
            kagi = KagiSearch( query=self.test_query )
            result = kagi.search_fastgpt()
            
            # Verify Kagi API call
            mock_client_instance.fastgpt.assert_called_once_with( query=self.test_query )
            
            # Verify response structure
            self.assertEqual( result, self.mock_fastgpt_response )
            self.assertIn( "meta", result )
            self.assertIn( "data", result )
            self.assertIn( "output", result["data"] )
            self.assertIn( "references", result["data"] )
            
            # Verify timing
            mock_stopwatch_class.assert_called_once_with( f"Kagi FastGPT query: [{self.test_query}]" )
            mock_stopwatch.print.assert_called_once_with( "Done!", use_millis=True )
    
    def test_search_fastgpt_api_error( self ):
        """
        Test FastGPT search with API error.
        
        Ensures:
            - Propagates KagiAPI exceptions
            - Does not suppress API errors
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ) as mock_client_class, \
             patch( 'cosa.tools.search_kagi.Stopwatch' ):
            
            mock_get_key.return_value = self.test_api_key
            mock_client_instance = Mock()
            mock_client_instance.fastgpt.side_effect = Exception( "API rate limit exceeded" )
            mock_client_class.return_value = mock_client_instance
            
            kagi = KagiSearch( query=self.test_query )
            
            with self.assertRaises( Exception ) as context:
                kagi.search_fastgpt()
            
            self.assertIn( "API rate limit exceeded", str( context.exception ) )
    
    def test_get_summary_success( self ):
        """
        Test successful URL summarization operation.
        
        Ensures:
            - Calls KagiClient.summarize with correct parameters
            - Uses 'agnes' engine and 'summary' type
            - Returns complete summary response
            - Includes debug output when enabled
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ) as mock_client_class, \
             patch( 'cosa.tools.search_kagi.Stopwatch' ) as mock_stopwatch_class, \
             patch( 'builtins.print' ) as mock_print:
            
            mock_get_key.return_value = self.test_api_key
            mock_client_instance = self._create_mock_kagi_client()
            mock_client_class.return_value = mock_client_instance
            
            mock_stopwatch = Mock()
            mock_stopwatch_class.return_value = mock_stopwatch
            
            kagi = KagiSearch( url=self.test_url, debug=True )
            result = kagi.get_summary()
            
            # Verify Kagi API call
            mock_client_instance.summarize.assert_called_once_with( 
                url=self.test_url, 
                engine="agnes", 
                summary_type="summary" 
            )
            
            # Verify response structure
            self.assertEqual( result, self.mock_summary_response )
            self.assertIn( "meta", result )
            self.assertIn( "data", result )
            self.assertIn( "output", result["data"] )
            
            # Verify timing
            mock_stopwatch_class.assert_called_once_with( "Kagi: Summarize" )
            mock_stopwatch.print.assert_called_once_with( "Done!", use_millis=True )
            
            # Verify debug output
            mock_print.assert_called_with( f"Kagi: Summarize: URL: [{self.test_url}]" )
    
    def test_get_summary_without_debug( self ):
        """
        Test URL summarization without debug output.
        
        Ensures:
            - No debug print statements when debug=False
            - API calls still function correctly
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ) as mock_client_class, \
             patch( 'cosa.tools.search_kagi.Stopwatch' ), \
             patch( 'builtins.print' ) as mock_print:
            
            mock_get_key.return_value = self.test_api_key
            mock_client_instance = self._create_mock_kagi_client()
            mock_client_class.return_value = mock_client_instance
            
            kagi = KagiSearch( url=self.test_url, debug=False )
            result = kagi.get_summary()
            
            # Verify API call succeeded
            self.assertEqual( result, self.mock_summary_response )
            
            # Verify no debug output
            mock_print.assert_not_called()
    
    def test_get_summary_api_error( self ):
        """
        Test URL summarization with API error.
        
        Ensures:
            - Propagates summarization API exceptions
            - Does not suppress API errors
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ) as mock_client_class, \
             patch( 'cosa.tools.search_kagi.Stopwatch' ):
            
            mock_get_key.return_value = self.test_api_key
            mock_client_instance = Mock()
            mock_client_instance.summarize.side_effect = Exception( "Invalid URL format" )
            mock_client_class.return_value = mock_client_instance
            
            kagi = KagiSearch( url=self.test_url )
            
            with self.assertRaises( Exception ) as context:
                kagi.get_summary()
            
            self.assertIn( "Invalid URL format", str( context.exception ) )
    
    def test_api_key_retrieval_called_twice( self ):
        """
        Test that API key is retrieved twice during initialization.
        
        Ensures:
            - du.get_api_key called for both _key and KagiClient init
            - Both calls use "kagi" as key identifier
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ):
            
            mock_get_key.return_value = self.test_api_key
            
            KagiSearch( query=self.test_query )
            
            # Verify both API key retrievals
            expected_calls = [call( "kagi" ), call( "kagi" )]
            mock_get_key.assert_has_calls( expected_calls )
            self.assertEqual( mock_get_key.call_count, 2 )
    
    def test_stopwatch_integration( self ):
        """
        Test Stopwatch timing integration.
        
        Ensures:
            - Stopwatch created with descriptive messages
            - Timer print called with consistent format
            - Both search and summary operations timed
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ) as mock_client_class, \
             patch( 'cosa.tools.search_kagi.Stopwatch' ) as mock_stopwatch_class:
            
            mock_get_key.return_value = self.test_api_key
            mock_client_instance = self._create_mock_kagi_client()
            mock_client_class.return_value = mock_client_instance
            
            mock_stopwatch = Mock()
            mock_stopwatch_class.return_value = mock_stopwatch
            
            # Test FastGPT timing
            kagi = KagiSearch( query=self.test_query )
            kagi.search_fastgpt()
            
            mock_stopwatch_class.assert_called_with( f"Kagi FastGPT query: [{self.test_query}]" )
            mock_stopwatch.print.assert_called_with( "Done!", use_millis=True )
            
            # Reset and test summary timing
            mock_stopwatch_class.reset_mock()
            mock_stopwatch.reset_mock()
            
            kagi_summary = KagiSearch( url=self.test_url )
            kagi_summary.get_summary()
            
            mock_stopwatch_class.assert_called_with( "Kagi: Summarize" )
            mock_stopwatch.print.assert_called_with( "Done!", use_millis=True )
    
    def test_response_data_structure_validation( self ):
        """
        Test validation of Kagi API response data structures.
        
        Ensures:
            - FastGPT responses have required meta/data structure
            - Summary responses have correct format
            - References array is properly structured
            - Token counts are included where expected
        """
        with patch( 'cosa.tools.search_kagi.du.get_api_key' ) as mock_get_key, \
             patch( 'cosa.tools.search_kagi.KagiClient' ) as mock_client_class, \
             patch( 'cosa.tools.search_kagi.Stopwatch' ):
            
            mock_get_key.return_value = self.test_api_key
            mock_client_instance = self._create_mock_kagi_client()
            mock_client_class.return_value = mock_client_instance
            
            kagi = KagiSearch( query=self.test_query )
            
            # Test FastGPT response structure
            fastgpt_result = kagi.search_fastgpt()
            
            # Verify top-level structure
            self.assertIsInstance( fastgpt_result, dict )
            self.assertIn( "meta", fastgpt_result )
            self.assertIn( "data", fastgpt_result )
            
            # Verify meta section
            meta = fastgpt_result["meta"]
            self.assertIn( "id", meta )
            self.assertIn( "node", meta )
            self.assertIn( "ms", meta )
            
            # Verify data section
            data = fastgpt_result["data"]
            self.assertIn( "output", data )
            self.assertIn( "tokens", data )
            self.assertIn( "references", data )
            
            # Verify references structure
            references = data["references"]
            self.assertIsInstance( references, list )
            if references:
                ref = references[0]
                self.assertIn( "title", ref )
                self.assertIn( "snippet", ref )
                self.assertIn( "url", ref )
            
            # Test summary response structure
            kagi_summary = KagiSearch( url=self.test_url )
            summary_result = kagi_summary.get_summary()
            
            self.assertIsInstance( summary_result, dict )
            self.assertIn( "meta", summary_result )
            self.assertIn( "data", summary_result )
            self.assertIn( "output", summary_result["data"] )


def isolated_unit_test():
    """
    Run comprehensive unit tests for Kagi search integration in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real HTTP requests or API calls
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "Kagi Search Integration Unit Tests - External Phase 5", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization_with_query',
            'test_initialization_with_url', 
            'test_initialization_api_key_error',
            'test_search_fastgpt_success',
            'test_search_fastgpt_api_error',
            'test_get_summary_success',
            'test_get_summary_without_debug',
            'test_get_summary_api_error',
            'test_api_key_retrieval_called_twice',
            'test_stopwatch_integration',
            'test_response_data_structure_validation'
        ]
        
        for method in test_methods:
            suite.addTest( TestKagiSearch( method ) )
        
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
        print( f"KAGI SEARCH INTEGRATION UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL KAGI SEARCH TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME KAGI SEARCH TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 KAGI SEARCH TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Kagi search integration unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )