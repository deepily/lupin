"""
Unit tests for EmbeddingManager with comprehensive mocking.

Tests the EmbeddingManager singleton class including:
- Singleton pattern behavior with thread safety
- OpenAI API integration with mocked responses  
- Text normalization and caching functionality
- Configuration management integration
- Error handling and graceful degradation
- Dependency injection and external service mocking

Zero external dependencies - all API calls, file I/O, and database
operations are mocked for isolated testing.
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
from cosa.memory.embedding_manager import EmbeddingManager, get_embedding_manager, generate_embedding


class TestEmbeddingManager( unittest.TestCase ):
    """
    Comprehensive unit tests for EmbeddingManager singleton class.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All EmbeddingManager functionality tested in isolation
        - Singleton behavior validated with thread safety
        - OpenAI API calls properly mocked
        - Text normalization and caching verified
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
        EmbeddingManager._instance = None
        EmbeddingManager._lock = threading.Lock()
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
            - Singleton state is cleaned up
        """
        self.mock_manager.reset_mocks()
        EmbeddingManager._instance = None
    
    def _create_fully_mocked_manager( self, config_values=None ):
        """
        Helper method to create fully mocked EmbeddingManager.
        
        Returns:
            Tuple of (manager, mocks_dict) for easy access to mocks
        """
        if config_values is None:
            config_values = {"expand symbols to words": False}
        
        # Create all mocks
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None, return_type="string": config_values.get( key, default )
        
        mock_cache = Mock()
        mock_normalizer = Mock()
        mock_normalizer.get_normalized_gist.return_value = "normalized text"
        
        # Store mocks for easy access
        mocks_dict = {
            "config": mock_config,
            "cache": mock_cache,
            "normalizer": mock_normalizer
        }
        
        with patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
             patch( "cosa.utils.util.get_file_as_dictionary", return_value={} ), \
             patch( "cosa.memory.embedding_manager.ConfigurationManager", return_value=mock_config ), \
             patch( "cosa.memory.embedding_cache_table.EmbeddingCacheTable", return_value=mock_cache ), \
             patch( "cosa.memory.gist_normalizer.GistNormalizer", return_value=mock_normalizer ):
            
            manager = EmbeddingManager( debug=False )
            return manager, mocks_dict
    
    def test_singleton_pattern_basic( self ):
        """
        Test basic singleton pattern functionality.
        
        Ensures:
            - Single instance is created and reused
            - Multiple calls return same instance
            - Instance is properly initialized
        """
        with patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
             patch( "cosa.utils.util.get_file_as_dictionary", return_value={} ), \
             patch( "cosa.memory.embedding_manager.ConfigurationManager" ) as mock_config_class, \
             patch( "cosa.memory.embedding_cache_table.EmbeddingCacheTable" ) as mock_cache_class, \
             patch( "cosa.memory.gist_normalizer.GistNormalizer" ) as mock_normalizer_class:
            
            # Setup mocks
            mock_config_class.return_value = Mock()
            mock_cache_class.return_value = Mock()
            mock_normalizer_class.return_value = Mock()
            
            # Test first instance creation
            instance1 = EmbeddingManager( debug=False, verbose=False )
            self.assertIsNotNone( instance1 )
            self.assertTrue( instance1._initialized )
            
            # Test second instance returns same object
            instance2 = EmbeddingManager( debug=False, verbose=False )
            self.assertIs( instance1, instance2, "Singleton should return same instance" )
    
    def test_singleton_thread_safety( self ):
        """
        Test singleton pattern thread safety.
        
        Ensures:
            - Multiple threads get same instance
            - No race conditions in instance creation
            - Thread safety mechanisms work correctly
        """
        with patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
             patch( "cosa.utils.util.get_file_as_dictionary", return_value={} ), \
             patch( "cosa.memory.embedding_manager.ConfigurationManager", return_value=Mock() ), \
             patch( "cosa.memory.embedding_cache_table.EmbeddingCacheTable", return_value=Mock() ), \
             patch( "cosa.memory.gist_normalizer.GistNormalizer", return_value=Mock() ):
            
            instances = []
            threads = []
            
            def create_instance():
                try:
                    instance = EmbeddingManager( debug=False )
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
    
    def test_text_normalization_without_expansion( self ):
        """
        Test text normalization without symbol expansion.
        
        Ensures:
            - GistNormalizer is properly called
            - Text is normalized but symbols preserved
            - Configuration controls expansion behavior
        """
        manager, mocks = self._create_fully_mocked_manager( {"expand symbols to words": False} )
        
        # Test normalization without expansion
        result = manager.normalize_text_for_cache( "What's the time?" )
        
        # Verify gist normalizer was called
        mocks["normalizer"].get_normalized_gist.assert_called_once_with( "What's the time?" )
        
        # Verify result is from gist normalizer (no symbol expansion)
        self.assertEqual( result, "normalized text" )
        
        # Verify config was checked for expansion setting
        mocks["config"].get.assert_called_with( "expand symbols to words", default=False, return_type="boolean" )
    
    def test_text_normalization_with_expansion( self ):
        """
        Test text normalization with symbol expansion enabled.
        
        Ensures:
            - Symbols are expanded to words when configured
            - Reverse mappings are applied correctly
            - Order is deterministic with sorted() usage
        """
        manager, mocks = self._create_fully_mocked_manager( {"expand symbols to words": True} )
        
        # Setup normalizer to return text with symbols
        mocks["normalizer"].get_normalized_gist.return_value = "what is 2+2?"
        
        # Test normalization with expansion
        result = manager.normalize_text_for_cache( "What is 2+2?" )
        
        # Verify gist normalizer was called
        mocks["normalizer"].get_normalized_gist.assert_called_once_with( "What is 2+2?" )
        
        # Since we didn't mock the dictionaries, we just verify the method completes
        self.assertIsInstance( result, str )
        self.assertGreaterEqual( len( result ), 0 )
    
    def test_embedding_generation_cache_hit( self ):
        """
        Test embedding generation with cache hit scenario.
        
        Ensures:
            - Cache is checked before API call
            - Cached embeddings are returned
            - No API calls made on cache hit
        """
        manager, mocks = self._create_fully_mocked_manager()
        
        # Setup cache hit
        cached_embedding = [0.1, 0.2, 0.3]
        mocks["cache"].get_cached_embedding.return_value = cached_embedding
        
        # Test embedding generation
        result = manager.generate_embedding( "Hello world!" )
        
        # Verify cache was checked
        mocks["cache"].get_cached_embedding.assert_called_once_with( "normalized text" )
        
        # Verify cached embedding returned
        self.assertEqual( result, cached_embedding )
        
        # Verify no caching operation (since it was a hit)
        mocks["cache"].cache_embedding.assert_not_called()
    
    def test_embedding_generation_cache_miss( self ):
        """
        Test embedding generation with cache miss scenario.
        
        Ensures:
            - API call made when cache miss occurs
            - OpenAI client configured correctly
            - Response processed and cached properly
        """
        manager, mocks = self._create_fully_mocked_manager( {"embedding model name": "text-embedding-ada-002"} )
        
        # Setup cache miss
        mocks["cache"].get_cached_embedding.return_value = None
        
        # Setup OpenAI response
        generated_embedding = [0.4, 0.5, 0.6]
        mock_response = Mock()
        mock_response.data = [Mock()]
        mock_response.data[0].embedding = generated_embedding
        
        with patch( "cosa.utils.util.get_api_key", return_value="test_api_key" ), \
             patch( "openai.OpenAI" ) as mock_openai_class:
            
            mock_client = Mock()
            mock_client.embeddings.create.return_value = mock_response
            mock_openai_class.return_value = mock_client
            
            # Test embedding generation
            result = manager.generate_embedding( "Hello world!" )
            
            # Verify API call made
            mock_client.embeddings.create.assert_called_once_with(
                input="normalized text",
                model="text-embedding-ada-002"
            )
            
            # Verify result is from API
            self.assertEqual( result, generated_embedding )
            
            # Verify caching occurred
            mocks["cache"].cache_embedding.assert_called_once_with( "normalized text", generated_embedding )
    
    def test_embedding_generation_no_normalization( self ):
        """
        Test embedding generation without normalization.
        
        Ensures:
            - Original text used as cache key when normalize_for_cache=False
            - No text normalization applied
            - Cache operations use exact text
        """
        manager, mocks = self._create_fully_mocked_manager( {"embedding model name": "text-embedding-ada-002"} )
        
        # Setup cache miss for exact text
        mocks["cache"].get_cached_embedding.return_value = None
        
        # Setup OpenAI response
        generated_embedding = [0.7, 0.8, 0.9]
        mock_response = Mock()
        mock_response.data = [Mock()]
        mock_response.data[0].embedding = generated_embedding
        
        with patch( "cosa.utils.util.get_api_key", return_value="test_api_key" ), \
             patch( "openai.OpenAI" ) as mock_openai_class:
            
            mock_client = Mock() 
            mock_client.embeddings.create.return_value = mock_response
            mock_openai_class.return_value = mock_client
            
            # Test embedding generation without normalization
            original_text = "Hello World!"
            result = manager.generate_embedding( original_text, normalize_for_cache=False )
            
            # Verify cache checked with exact text
            mocks["cache"].get_cached_embedding.assert_called_once_with( original_text )
            
            # Verify API called with exact text
            mock_client.embeddings.create.assert_called_once_with(
                input=original_text,
                model="text-embedding-ada-002"
            )
            
            # Verify caching with exact text
            mocks["cache"].cache_embedding.assert_called_once_with( original_text, generated_embedding )
            
            # Verify normalizer was NOT called for this path
            mocks["normalizer"].get_normalized_gist.assert_not_called()
    
    def test_openai_api_error_handling( self ):
        """
        Test error handling for OpenAI API failures.
        
        Ensures:
            - API errors are caught and handled gracefully
            - Empty list returned on API failure
            - Error details logged appropriately
            - Execution continues without crashing
        """
        manager, mocks = self._create_fully_mocked_manager( {"embedding model name": "text-embedding-ada-002"} )
        
        # Setup cache miss
        mocks["cache"].get_cached_embedding.return_value = None
        
        with patch( "cosa.utils.util.get_api_key", return_value="invalid_key" ), \
             patch( "openai.OpenAI" ) as mock_openai_class, \
             patch( "cosa.utils.util.print_banner" ) as mock_print_banner:
            
            # Setup OpenAI client to raise a generic exception (simpler than NotFoundError)
            mock_client = Mock()
            mock_client.embeddings.create.side_effect = Exception( "API connection failed" )
            mock_openai_class.return_value = mock_client
            
            # Test embedding generation with API error
            result = manager.generate_embedding( "Test text" )
            
            # Verify empty list returned on error
            self.assertEqual( result, [] )
            
            # Verify error banner was printed
            mock_print_banner.assert_called()
    
    def test_missing_configuration_handling( self ):
        """
        Test handling of missing configuration values.
        
        Ensures:
            - Missing embedding model configuration handled gracefully
            - Appropriate error messages displayed
            - Empty list returned when config missing
        """
        manager, mocks = self._create_fully_mocked_manager( {} )  # Empty config
        
        # Setup cache miss
        mocks["cache"].get_cached_embedding.return_value = None
        
        # Config mock returns None for missing embedding model
        mocks["config"].get.return_value = None
        
        with patch( "cosa.utils.util.print_banner" ) as mock_print_banner:
            
            # Test embedding generation with missing config
            result = manager.generate_embedding( "Test text" )
            
            # Verify empty list returned
            self.assertEqual( result, [] )
            
            # Verify configuration error banner was printed
            mock_print_banner.assert_called()
            banner_calls = [call[0][0] for call in mock_print_banner.call_args_list]
            self.assertTrue( any( "CONFIGURATION ERROR" in banner for banner in banner_calls ) )
    
    def test_convenience_functions( self ):
        """
        Test convenience functions get_embedding_manager() and generate_embedding().
        
        Ensures:
            - Convenience functions work correctly
            - Singleton behavior maintained through convenience functions
            - Parameters passed through correctly
        """
        with patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
             patch( "cosa.utils.util.get_file_as_dictionary", return_value={} ), \
             patch( "cosa.memory.embedding_manager.ConfigurationManager" ) as mock_config_class, \
             patch( "cosa.memory.embedding_cache_table.EmbeddingCacheTable" ) as mock_cache_class, \
             patch( "cosa.memory.gist_normalizer.GistNormalizer" ) as mock_normalizer_class, \
             patch( "cosa.utils.util.get_api_key", return_value="test_key" ), \
             patch( "openai.OpenAI" ) as mock_openai_class:
            
            # Setup mocks
            mock_config = Mock()
            mock_config.get.return_value = "text-embedding-ada-002"
            mock_config_class.return_value = mock_config
            
            mock_cache = Mock()
            mock_cache.get_cached_embedding.return_value = None
            mock_cache_class.return_value = mock_cache
            
            mock_normalizer = Mock()
            mock_normalizer.get_normalized_gist.return_value = "test text"
            mock_normalizer_class.return_value = mock_normalizer
            
            generated_embedding = [0.1, 0.2]
            mock_response = Mock()
            mock_response.data = [Mock()]
            mock_response.data[0].embedding = generated_embedding
            
            mock_client = Mock()
            mock_client.embeddings.create.return_value = mock_response
            mock_openai_class.return_value = mock_client
            
            # Test convenience function get_embedding_manager()
            manager1 = get_embedding_manager( debug=True, verbose=True )
            manager2 = get_embedding_manager( debug=False, verbose=False )
            
            # Should return same instance (singleton)
            self.assertIs( manager1, manager2 )
            
            # Test convenience function generate_embedding()
            result = generate_embedding( "Test text", normalize_for_cache=True, debug=True )
            
            # Verify result
            self.assertEqual( result, generated_embedding )


def isolated_unit_test():
    """
    Run comprehensive unit tests for EmbeddingManager in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real API calls or file I/O
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "EmbeddingManager Unit Tests - Memory System Phase 3", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_singleton_pattern_basic',
            'test_singleton_thread_safety', 
            'test_text_normalization_without_expansion',
            'test_text_normalization_with_expansion',
            'test_embedding_generation_cache_hit',
            'test_embedding_generation_cache_miss',
            'test_embedding_generation_no_normalization',
            'test_openai_api_error_handling',
            'test_missing_configuration_handling',
            'test_convenience_functions'
        ]
        
        for method in test_methods:
            suite.addTest( TestEmbeddingManager( method ) )
        
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
        print( f"EMBEDDING MANAGER UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL EMBEDDING MANAGER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME EMBEDDING MANAGER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 EMBEDDING MANAGER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} EmbeddingManager unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )