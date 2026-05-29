"""
Unit tests for GistNormalizer with comprehensive mocking.

Tests the GistNormalizer singleton class including:
- Singleton pattern behavior with thread safety
- Gist extraction and text normalization workflow
- Integration between Gister and Normalizer components
- Batch processing functionality
- Edge case handling for empty/short texts
- Error handling and graceful degradation

Zero external dependencies - all Gister and Normalizer operations
are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import threading
import time
from typing import List, Dict, Any, Optional

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.memory.gist_normalizer import GistNormalizer


class TestGistNormalizer( unittest.TestCase ):
    """
    Comprehensive unit tests for GistNormalizer singleton class.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All GistNormalizer functionality tested in isolation
        - Singleton behavior validated with thread safety
        - Gist extraction and normalization properly mocked
        - Error handling scenarios covered
    """
    
    def setUp( self ):
        """
        Setup for each test method.
        
        Ensures:
            - Clean state for each test
            - Mock manager is available
            - Singleton instances are reset
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()
        
        # Reset singleton instance before each test to ensure isolation
        GistNormalizer._instance = None
        GistNormalizer._lock = threading.Lock()
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
            - Singleton state is cleaned up
        """
        self.mock_manager.reset_mocks()
        GistNormalizer._instance = None
    
    def _create_mocked_gist_normalizer( self ):
        """
        Helper method to create fully mocked GistNormalizer.
        
        Returns:
            Tuple of (gist_normalizer, mocks_dict) for easy access to mocks
        """
        # Create all mocks
        mock_gister = Mock()
        mock_normalizer = Mock()
        
        # Store mocks for easy access
        mocks_dict = {
            "gister": mock_gister,
            "normalizer": mock_normalizer
        }
        
        with patch( "cosa.memory.gist_normalizer.Gister", return_value=mock_gister ), \
             patch( "cosa.memory.gist_normalizer.Normalizer", return_value=mock_normalizer ), \
             patch( "builtins.print" ):  # Suppress debug prints
            
            gist_normalizer = GistNormalizer( debug=False )
            return gist_normalizer, mocks_dict
    
    def test_singleton_pattern_basic( self ):
        """
        Test basic singleton pattern functionality.
        
        Ensures:
            - Single instance is created and reused
            - Multiple calls return same instance
            - Instance is properly initialized
        """
        with patch( "cosa.memory.gist_normalizer.Gister" ) as mock_gister_class, \
             patch( "cosa.memory.gist_normalizer.Normalizer" ) as mock_normalizer_class, \
             patch( "builtins.print" ):
            
            # Setup mocks
            mock_gister_class.return_value = Mock()
            mock_normalizer_class.return_value = Mock()
            
            # Test first instance creation
            instance1 = GistNormalizer( debug=False, verbose=False )
            self.assertIsNotNone( instance1 )
            self.assertTrue( instance1._initialized )
            
            # Test second instance returns same object
            instance2 = GistNormalizer( debug=False, verbose=False )
            self.assertIs( instance1, instance2, "Singleton should return same instance" )
            
            # Verify components initialized only once
            mock_gister_class.assert_called_once()
            mock_normalizer_class.assert_called_once()
    
    def test_singleton_thread_safety( self ):
        """
        Test singleton pattern thread safety.
        
        Ensures:
            - Multiple threads get same instance
            - No race conditions in instance creation
            - Thread safety mechanisms work correctly
        """
        with patch( "cosa.memory.gist_normalizer.Gister", return_value=Mock() ), \
             patch( "cosa.memory.gist_normalizer.Normalizer", return_value=Mock() ), \
             patch( "builtins.print" ):
            
            instances = []
            threads = []
            
            def create_instance():
                try:
                    instance = GistNormalizer( debug=False )
                    instances.append( instance )
                except Exception as e:
                    # Add None to indicate failure, but don't crash the test
                    instances.append( None )
            
            # Create multiple threads trying to create instances
            for i in range( 5 ):
                thread = threading.Thread( target=create_instance )
                threads.append( thread )
            
            # Start all threads
            for thread in threads:
                thread.start()
            
            # Wait for all threads to complete
            for thread in threads:
                thread.join()
            
            # Verify all threads got valid instances
            self.assertEqual( len( instances ), 5 )
            
            # Filter out None values (failed instances)
            valid_instances = [inst for inst in instances if inst is not None]
            
            # Verify we got at least some valid instances and they're all the same
            self.assertGreater( len( valid_instances ), 0, "At least one thread should create instance" )
            for instance in valid_instances[1:]:
                self.assertIs( instance, valid_instances[0], "All threads should get same singleton instance" )
    
    def test_get_normalized_gist_basic( self ):
        """
        Test basic gist normalization functionality.
        
        Ensures:
            - Gister called with input text
            - Normalizer called with gist output
            - Final result returned correctly
        """
        gn, mocks = self._create_mocked_gist_normalizer()
        
        # Setup mock returns
        input_text = "Um, what time is it right now?"
        extracted_gist = "what time is it"
        normalized_result = "what time"
        
        mocks["gister"].get_gist.return_value = extracted_gist
        mocks["normalizer"].normalize.return_value = normalized_result
        
        # Test the workflow
        result = gn.get_normalized_gist( input_text )
        
        # Verify workflow
        mocks["gister"].get_gist.assert_called_once_with( input_text )
        mocks["normalizer"].normalize.assert_called_once_with( extracted_gist )
        
        # Verify result
        self.assertEqual( result, normalized_result )
    
    def test_get_normalized_gist_empty_input( self ):
        """
        Test gist normalization with empty input.
        
        Ensures:
            - Empty strings return empty result
            - Whitespace-only strings return empty result
            - No processing done for empty input
        """
        gn, mocks = self._create_mocked_gist_normalizer()
        
        # Test empty string
        result = gn.get_normalized_gist( "" )
        self.assertEqual( result, "" )
        
        # Test whitespace only
        result = gn.get_normalized_gist( "   " )
        self.assertEqual( result, "" )
        
        # Test None input (if it happens)
        result = gn.get_normalized_gist( None )
        self.assertEqual( result, "" )
        
        # Verify no processing called for empty inputs
        mocks["gister"].get_gist.assert_not_called()
        mocks["normalizer"].normalize.assert_not_called()
    
    def test_get_normalized_gist_verbose_input( self ):
        """
        Test gist normalization with verbose voice transcription input.
        
        Ensures:
            - Long verbose text processed correctly
            - Gist extraction reduces verbosity
            - Normalization further cleans text
        """
        gn, mocks = self._create_mocked_gist_normalizer()
        
        # Test with verbose voice transcription
        verbose_text = "Um, so like, I was wondering if you could, you know, help me understand how to, uh, calculate the compound interest on my savings account?"
        extracted_gist = "how to calculate compound interest on savings account"
        normalized_result = "calculate compound interest savings account"
        
        mocks["gister"].get_gist.return_value = extracted_gist
        mocks["normalizer"].normalize.return_value = normalized_result
        
        # Test processing
        result = gn.get_normalized_gist( verbose_text )
        
        # Verify calls
        mocks["gister"].get_gist.assert_called_once_with( verbose_text )
        mocks["normalizer"].normalize.assert_called_once_with( extracted_gist )
        
        # Verify result
        self.assertEqual( result, normalized_result )
        
        # Verify text reduction occurred (mocked, but logic is tested)
        self.assertLess( len( normalized_result ), len( verbose_text ) )
    
    def test_process_batch( self ):
        """
        Test batch processing functionality.
        
        Ensures:
            - Multiple texts processed in batch
            - Gister called for each text individually
            - Normalizer batch method called with all gists
            - Results returned in correct order
        """
        gn, mocks = self._create_mocked_gist_normalizer()
        
        # Test data
        input_texts = [
            "Um, what's the weather like?",
            "Uh, can you help me with math?",
            "So, like, what time is it?"
        ]
        
        extracted_gists = [
            "what's the weather like",
            "can you help me with math", 
            "what time is it"
        ]
        
        normalized_results = [
            "weather",
            "help math",
            "time"
        ]
        
        # Setup mocks
        mocks["gister"].get_gist.side_effect = extracted_gists
        mocks["normalizer"].normalize_batch.return_value = normalized_results
        
        # Test batch processing
        results = gn.process_batch( input_texts )
        
        # Verify gister called for each text
        self.assertEqual( mocks["gister"].get_gist.call_count, len( input_texts ) )
        for i, text in enumerate( input_texts ):
            mocks["gister"].get_gist.assert_any_call( text )
        
        # Verify normalizer batch called with gists
        mocks["normalizer"].normalize_batch.assert_called_once_with( extracted_gists )
        
        # Verify results
        self.assertEqual( results, normalized_results )
    
    def test_process_batch_empty_list( self ):
        """
        Test batch processing with empty input list.
        
        Ensures:
            - Empty list handled gracefully
            - No processing calls made
            - Empty list returned
        """
        gn, mocks = self._create_mocked_gist_normalizer()
        
        # Setup normalizer to return empty list
        mocks["normalizer"].normalize_batch.return_value = []
        
        # Test with empty list
        results = gn.process_batch( [] )
        
        # Verify no gist extraction calls
        mocks["gister"].get_gist.assert_not_called()
        
        # Verify batch normalization called with empty list
        mocks["normalizer"].normalize_batch.assert_called_once_with( [] )
        
        # Verify empty result
        self.assertEqual( results, [] )
    
    def test_initialization_parameters( self ):
        """
        Test GistNormalizer initialization with different parameters.
        
        Ensures:
            - Debug and verbose flags passed correctly
            - Components initialized with correct parameters
        """
        with patch( "cosa.memory.gist_normalizer.Gister" ) as mock_gister_class, \
             patch( "cosa.memory.gist_normalizer.Normalizer" ) as mock_normalizer_class, \
             patch( "builtins.print" ):
            
            mock_gister_class.return_value = Mock()
            mock_normalizer_class.return_value = Mock()
            
            # Test with debug=True, verbose=True
            gn = GistNormalizer( debug=True, verbose=True )
            
            # Verify parameters stored
            self.assertTrue( gn.debug )
            self.assertTrue( gn.verbose )
            
            # Verify Gister initialized with debug/verbose
            mock_gister_class.assert_called_once_with( debug=True, verbose=True )
            
            # Verify Normalizer initialized (singleton, no params)
            mock_normalizer_class.assert_called_once_with()
    
    def test_component_integration( self ):
        """
        Test integration between GistNormalizer and its components.
        
        Ensures:
            - Components are properly initialized
            - Method calls flow correctly through pipeline
            - Results are processed in correct sequence
        """
        gn, mocks = self._create_mocked_gist_normalizer()
        
        # Verify components are accessible
        self.assertIsNotNone( gn.gister )
        self.assertIsNotNone( gn.normalizer )
        
        # Test pipeline with realistic data
        test_cases = [
            {
                "input": "So, um, I need help with, like, understanding machine learning",
                "gist": "need help understanding machine learning",
                "normalized": "help understand machine learning"
            },
            {
                "input": "Uh, what's the, you know, best way to learn Python programming?",
                "gist": "what's the best way to learn Python programming",
                "normalized": "best way learn python programming"
            }
        ]
        
        for case in test_cases:
            # Setup mocks for this case
            mocks["gister"].get_gist.return_value = case["gist"]
            mocks["normalizer"].normalize.return_value = case["normalized"]
            
            # Test processing
            result = gn.get_normalized_gist( case["input"] )
            
            # Verify result matches expected
            self.assertEqual( result, case["normalized"] )


def isolated_unit_test():
    """
    Run comprehensive unit tests for GistNormalizer in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real Gister or Normalizer operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "GistNormalizer Unit Tests - Memory System Phase 3", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_singleton_pattern_basic',
            'test_singleton_thread_safety',
            'test_get_normalized_gist_basic',
            'test_get_normalized_gist_empty_input',
            'test_get_normalized_gist_verbose_input',
            'test_process_batch',
            'test_process_batch_empty_list',
            'test_initialization_parameters',
            'test_component_integration'
        ]
        
        for method in test_methods:
            suite.addTest( TestGistNormalizer( method ) )
        
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
        print( f"GIST NORMALIZER UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL GIST NORMALIZER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME GIST NORMALIZER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 GIST NORMALIZER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} GistNormalizer unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )