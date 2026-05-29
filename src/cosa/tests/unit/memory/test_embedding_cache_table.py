"""
Unit tests for EmbeddingCacheTable with comprehensive mocking.

Tests the EmbeddingCacheTable class including:
- Database connection and table creation
- Embedding caching and retrieval operations
- Cache hit/miss scenarios
- Error handling for database operations
- Table schema validation and FTS indexing

Zero external dependencies - all database operations and configuration
management are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import time
from typing import List, Dict, Any, Optional

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.memory.embedding_cache_table import EmbeddingCacheTable


class TestEmbeddingCacheTable( unittest.TestCase ):
    """
    Comprehensive unit tests for EmbeddingCacheTable class.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All EmbeddingCacheTable functionality tested in isolation
        - Database operations properly mocked
        - Configuration management mocked
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
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mocked_cache_table( self, config_values=None, existing_tables=None ):
        """
        Helper method to create fully mocked EmbeddingCacheTable.
        
        Args:
            config_values: Dictionary of config values to return
            existing_tables: List of existing table names in database
            
        Returns:
            Tuple of (cache_table, mocks_dict) for easy access to mocks
        """
        if config_values is None:
            config_values = {"path to database wo root": "/test/db"}
        
        if existing_tables is None:
            existing_tables = []
        
        # Create all mocks
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None: config_values.get( key, default )
        
        mock_db = Mock()
        mock_db.table_names.return_value = existing_tables
        
        mock_table = Mock()
        mock_table.count_rows.return_value = 42
        
        # Store mocks for easy access
        mocks_dict = {
            "config": mock_config,
            "db": mock_db,
            "table": mock_table
        }
        
        with patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
             patch( "cosa.memory.embedding_cache_table.ConfigurationManager", return_value=mock_config ), \
             patch( "lancedb.connect", return_value=mock_db ), \
             patch( "builtins.print" ):  # Suppress print statements
            
            # Setup table creation/opening behavior
            if "embedding_cache_tbl" in existing_tables:
                mock_db.open_table.return_value = mock_table
            else:
                mock_db.create_table.return_value = mock_table
            
            cache_table = EmbeddingCacheTable( debug=False )
            return cache_table, mocks_dict
    
    def test_initialization_with_existing_table( self ):
        """
        Test EmbeddingCacheTable initialization when table already exists.
        
        Ensures:
            - Database connection established
            - Existing table opened correctly
            - Row count displayed
        """
        cache_table, mocks = self._create_mocked_cache_table(
            config_values={"path to database wo root": "/test/db"},  
            existing_tables=["embedding_cache_tbl"]
        )
        
        # Verify database connection
        mocks["config"].get.assert_called_with( "path to database wo root" )
        
        # Verify table opened (not created)
        mocks["db"].open_table.assert_called_once_with( "embedding_cache_tbl" )
        mocks["db"].create_table.assert_not_called()
        
        # Verify row count queried
        mocks["table"].count_rows.assert_called()
    
    def test_initialization_with_new_table( self ):
        """
        Test EmbeddingCacheTable initialization when table doesn't exist.
        
        Ensures:
            - Database connection established
            - New table created with proper schema
            - FTS index created
        """
        cache_table, mocks = self._create_mocked_cache_table(
            config_values={"path to database wo root": "/test/db"},
            existing_tables=[]  # No existing tables
        )
        
        # Verify database connection  
        mocks["config"].get.assert_called_with( "path to database wo root" )
        
        # Verify table created (not opened)
        mocks["db"].create_table.assert_called()
        mocks["db"].open_table.assert_not_called()
        
        # Verify FTS index created
        mocks["table"].create_fts_index.assert_called_once_with( "normalized_text", replace=True )
    
    def test_has_cached_embedding_found( self ):
        """
        Test has_cached_embedding when embedding exists in cache.
        
        Ensures:
            - SQL query executed with proper escaping
            - Returns True when embedding found
            - Query limited to 1 result for efficiency
        """
        cache_table, mocks = self._create_mocked_cache_table()
        
        # Setup mock search chain
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        mock_to_list = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = [{"normalized_text": "test text"}]  # Found
        
        mocks["table"].search.return_value = mock_search
        
        # Test cache hit
        result = cache_table.has_cached_embedding( "test text" )
        
        # Verify method chain called
        mocks["table"].search.assert_called_once()
        mock_search.where.assert_called_once_with( "normalized_text = 'test text'" )
        mock_where.limit.assert_called_once_with( 1 )
        mock_limit.select.assert_called_once_with( ["normalized_text"] )
        mock_select.to_list.assert_called_once()
        
        # Verify result
        self.assertTrue( result )
    
    def test_has_cached_embedding_not_found( self ):
        """
        Test has_cached_embedding when embedding doesn't exist in cache.
        
        Ensures:
            - SQL query executed correctly
            - Returns False when no results found
        """
        cache_table, mocks = self._create_mocked_cache_table()
        
        # Setup mock search chain for cache miss
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        mock_to_list = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = []  # Not found
        
        mocks["table"].search.return_value = mock_search
        
        # Test cache miss
        result = cache_table.has_cached_embedding( "missing text" )
        
        # Verify query executed
        mocks["table"].search.assert_called_once()
        mock_search.where.assert_called_once_with( "normalized_text = 'missing text'" )
        
        # Verify result
        self.assertFalse( result )
    
    def test_has_cached_embedding_sql_injection_protection( self ):
        """
        Test has_cached_embedding with potentially problematic input.
        
        Ensures:
            - Single quotes are escaped properly
            - SQL injection attempts are neutralized
        """
        cache_table, mocks = self._create_mocked_cache_table()
        
        # Setup mock search chain
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        mock_to_list = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = []
        
        mocks["table"].search.return_value = mock_search
        
        # Test with single quotes that need escaping
        test_text = "what's the time?"
        cache_table.has_cached_embedding( test_text )
        
        # Verify single quotes were escaped (doubled)
        expected_escaped = "normalized_text = 'what''s the time?'"
        mock_search.where.assert_called_once_with( expected_escaped )
    
    def test_get_cached_embedding_found( self ):
        """
        Test get_cached_embedding when embedding exists in cache.
        
        Ensures:
            - Returns the cached embedding
            - Query selects embedding field only
            - Proper data extraction from results
        """
        cache_table, mocks = self._create_mocked_cache_table()
        
        # Setup mock search chain
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        mock_to_list = Mock()
        
        test_embedding = [0.1, 0.2, 0.3] * 512  # 1536 dimensions
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = [{"embedding": test_embedding}]
        
        mocks["table"].search.return_value = mock_search
        
        # Test retrieval
        result = cache_table.get_cached_embedding( "test text" )
        
        # Verify query
        mocks["table"].search.assert_called_once()
        mock_search.where.assert_called_once_with( "normalized_text = 'test text'" )
        mock_where.limit.assert_called_once_with( 1 )
        mock_limit.select.assert_called_once_with( ["embedding"] )
        
        # Verify result
        self.assertEqual( result, test_embedding )
    
    def test_get_cached_embedding_not_found( self ):
        """
        Test get_cached_embedding when embedding doesn't exist in cache.
        
        Ensures:
            - Returns None when no results found
            - Query executed correctly
        """
        cache_table, mocks = self._create_mocked_cache_table()
        
        # Setup mock search chain for cache miss
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        mock_to_list = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = []  # Empty result
        
        mocks["table"].search.return_value = mock_search
        
        # Test cache miss
        result = cache_table.get_cached_embedding( "missing text" )
        
        # Verify query executed
        mocks["table"].search.assert_called_once()
        
        # Verify result is None
        self.assertIsNone( result )
    
    def test_cache_embedding( self ):
        """
        Test cache_embedding functionality.
        
        Ensures:
            - Embedding added to table with correct format
            - Row data structured properly
        """
        cache_table, mocks = self._create_mocked_cache_table()
        
        # Test data
        test_text = "hello world"
        test_embedding = [0.5] * 1536
        
        # Test caching
        cache_table.cache_embedding( test_text, test_embedding )
        
        # Verify add called with correct data structure
        expected_row = [{"normalized_text": test_text, "embedding": test_embedding}]
        mocks["table"].add.assert_called_once_with( expected_row )
    
    def test_cache_embedding_error_handling( self ):
        """
        Test cache_embedding error handling.
        
        Ensures:
            - Exceptions are caught and handled gracefully
            - Method doesn't crash on database errors
        """
        cache_table, mocks = self._create_mocked_cache_table()
        
        # Setup table.add to raise an exception
        mocks["table"].add.side_effect = Exception( "Database error" )
        
        # Test that caching doesn't crash on error
        test_text = "error test"
        test_embedding = [0.1] * 1536
        
        # Should not raise exception
        try:
            cache_table.cache_embedding( test_text, test_embedding )
            # If we get here, error was handled gracefully
            self.assertTrue( True )
        except Exception:
            self.fail( "cache_embedding should handle exceptions gracefully" )
    
    def test_database_error_handling( self ):
        """
        Test error handling for database operations.
        
        Ensures:
            - Search errors are handled gracefully
            - Methods return appropriate defaults on error
        """
        cache_table, mocks = self._create_mocked_cache_table()
        
        # Setup search to raise an exception
        mocks["table"].search.side_effect = Exception( "Database connection failed" )
        
        # Test has_cached_embedding error handling
        result = cache_table.has_cached_embedding( "test text" )
        self.assertFalse( result, "Should return False on database error" )
        
        # Test get_cached_embedding error handling  
        result = cache_table.get_cached_embedding( "test text" )
        self.assertIsNone( result, "Should return None on database error" )


def isolated_unit_test():
    """
    Run comprehensive unit tests for EmbeddingCacheTable in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real database operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "EmbeddingCacheTable Unit Tests - Memory System Phase 3", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization_with_existing_table',
            'test_initialization_with_new_table',
            'test_has_cached_embedding_found',
            'test_has_cached_embedding_not_found',
            'test_has_cached_embedding_sql_injection_protection',
            'test_get_cached_embedding_found',
            'test_get_cached_embedding_not_found',
            'test_cache_embedding',
            'test_cache_embedding_error_handling',
            'test_database_error_handling'
        ]
        
        for method in test_methods:
            suite.addTest( TestEmbeddingCacheTable( method ) )
        
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
        print( f"EMBEDDING CACHE TABLE UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL EMBEDDING CACHE TABLE TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME EMBEDDING CACHE TABLE TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 EMBEDDING CACHE TABLE TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} EmbeddingCacheTable unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )