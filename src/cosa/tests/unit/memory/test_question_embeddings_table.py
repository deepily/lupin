"""
Unit tests for QuestionEmbeddingsTable with comprehensive mocking.

Tests the QuestionEmbeddingsTable class including:
- Database connection and table initialization
- Question existence checking with SQL injection protection
- Embedding storage and retrieval operations
- Error handling for database failures
- Integration with EmbeddingManager for missing embeddings
- ConfigurationManager integration for database paths

Zero external dependencies - all database operations, file system operations,
and external service calls are mocked for isolated testing.
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
from cosa.memory.question_embeddings_table import QuestionEmbeddingsTable


class TestQuestionEmbeddingsTable( unittest.TestCase ):
    """
    Comprehensive unit tests for QuestionEmbeddingsTable class.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All QuestionEmbeddingsTable functionality tested in isolation
        - Database operations properly mocked
        - SQL injection protection validated
        - Error handling tested
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
        self.test_question = "What is 2+2?"
        self.test_embedding = [0.1] * 1536
        self.test_database_path = "/test/db/path"
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mocked_question_embeddings_table( self ):
        """
        Helper to create fully mocked QuestionEmbeddingsTable.
        
        Returns:
            Tuple of (table_instance, mocks_dict) for testing
        """
        # Create mock objects
        mock_config_mgr = Mock()
        mock_embedding_mgr = Mock()
        mock_db = Mock()
        mock_table = Mock()
        
        # Setup mock behaviors
        mock_config_mgr.get.return_value = "/test/db"
        mock_embedding_mgr.generate_embedding.return_value = self.test_embedding
        mock_db.open_table.return_value = mock_table
        mock_table.count_rows.return_value = 100
        
        mocks = {
            "config_mgr": mock_config_mgr,
            "embedding_mgr": mock_embedding_mgr,
            "db": mock_db,
            "table": mock_table
        }
        
        with patch( "cosa.memory.question_embeddings_table.ConfigurationManager", return_value=mock_config_mgr ), \
             patch( "cosa.memory.question_embeddings_table.EmbeddingManager", return_value=mock_embedding_mgr ), \
             patch( "cosa.memory.question_embeddings_table.lancedb.connect", return_value=mock_db ), \
             patch( "cosa.memory.question_embeddings_table.du.get_project_root", return_value="/project/root" ), \
             patch( "builtins.print" ):
            
            table = QuestionEmbeddingsTable( debug=False, verbose=False )
        
        return table, mocks
    
    def test_initialization( self ):
        """
        Test QuestionEmbeddingsTable initialization.
        
        Ensures:
            - ConfigurationManager created with correct environment variable
            - EmbeddingManager created with debug flags
            - Database connection established
            - Table opened and row count printed
        """
        mock_config_mgr = Mock()
        mock_embedding_mgr = Mock()
        mock_db = Mock()
        mock_table = Mock()
        
        mock_config_mgr.get.return_value = "/test/db"
        mock_db.open_table.return_value = mock_table
        mock_table.count_rows.return_value = 42
        
        with patch( "cosa.memory.question_embeddings_table.ConfigurationManager", return_value=mock_config_mgr ) as mock_config_class, \
             patch( "cosa.memory.question_embeddings_table.EmbeddingManager", return_value=mock_embedding_mgr ) as mock_embedding_class, \
             patch( "cosa.memory.question_embeddings_table.lancedb.connect", return_value=mock_db ) as mock_lancedb, \
             patch( "cosa.memory.question_embeddings_table.du.get_project_root", return_value="/project/root" ), \
             patch( "builtins.print" ) as mock_print:
            
            # Test initialization
            table = QuestionEmbeddingsTable( debug=True, verbose=True )
            
            # Verify initialization calls
            mock_config_class.assert_called_once_with( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            mock_embedding_class.assert_called_once_with( debug=True, verbose=True )
            mock_config_mgr.get.assert_called_once_with( "path to database wo root" )
            mock_lancedb.assert_called_once_with( "/project/root/test/db" )
            mock_db.open_table.assert_called_once_with( "question_embeddings_tbl" )
            mock_table.count_rows.assert_called_once()
            
            # Verify attributes
            self.assertTrue( table.debug )
            self.assertTrue( table.verbose )
    
    def test_has_question_exists( self ):
        """
        Test has() method when question exists in table.
        
        Ensures:
            - SQL query properly formatted
            - Single quotes escaped for SQL injection protection
            - Returns True when question found
            - Search limited to 1 result for efficiency
        """
        table, mocks = self._create_mocked_question_embeddings_table()
        
        # Mock search chain for existing question
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = [{"question": self.test_question}]
        
        mocks["table"].search.return_value = mock_search
        
        with patch( "cosa.memory.question_embeddings_table.du.print_banner" ):
            result = table.has( self.test_question )
        
        # Verify result
        self.assertTrue( result )
        
        # Verify query chain
        mocks["table"].search.assert_called_once()
        mock_search.where.assert_called_once_with( f"question = '{self.test_question}'" )
        mock_where.limit.assert_called_once_with( 1 )
        mock_limit.select.assert_called_once_with( ["question"] )
        mock_select.to_list.assert_called_once()
    
    def test_has_question_not_exists( self ):
        """
        Test has() method when question does not exist in table.
        
        Ensures:
            - Returns False when no results found
            - Empty list handled correctly
        """
        table, mocks = self._create_mocked_question_embeddings_table()
        
        # Mock search chain for non-existing question
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = []  # No results
        
        mocks["table"].search.return_value = mock_search
        
        with patch( "cosa.memory.question_embeddings_table.du.print_banner" ):
            result = table.has( "Non-existent question" )
        
        # Verify result
        self.assertFalse( result )
    
    def test_has_sql_injection_protection( self ):
        """
        Test SQL injection protection in has() method.
        
        Ensures:
            - Single quotes properly escaped by doubling
            - Malicious SQL input safely handled
        """
        table, mocks = self._create_mocked_question_embeddings_table()
        
        # Mock search chain
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = []
        
        mocks["table"].search.return_value = mock_search
        
        # Test with single quotes that need escaping
        malicious_question = "What's your name'; DROP TABLE users; --"
        
        with patch( "cosa.memory.question_embeddings_table.du.print_banner" ):
            table.has( malicious_question )
        
        # Verify quotes were escaped (single quotes doubled)
        expected_escaped = "What''s your name''; DROP TABLE users; --"
        mock_search.where.assert_called_once_with( f"question = '{expected_escaped}'" )
    
    def test_get_embedding_from_table( self ):
        """
        Test get_embedding() when embedding exists in table.
        
        Ensures:
            - Returns embedding from table
            - Does not generate new embedding
            - SQL injection protection applied
        """
        table, mocks = self._create_mocked_question_embeddings_table()
        
        # Mock search chain for existing embedding
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = [{"embedding": self.test_embedding}]
        
        mocks["table"].search.return_value = mock_search
        
        result = table.get_embedding( self.test_question )
        
        # Verify result
        self.assertEqual( result, self.test_embedding )
        
        # Verify no new embedding generated
        mocks["embedding_mgr"].generate_embedding.assert_not_called()
        
        # Verify query structure
        mock_search.where.assert_called_once_with( f"question = '{self.test_question}'" )
        mock_limit.select.assert_called_once_with( ["embedding"] )
    
    def test_get_embedding_generate_new( self ):
        """
        Test get_embedding() when embedding not in table.
        
        Ensures:
            - Generates new embedding when not found
            - Returns generated embedding
            - Does not add to table automatically
        """
        table, mocks = self._create_mocked_question_embeddings_table()
        
        # Mock search chain for non-existing embedding
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = []  # No results
        
        mocks["table"].search.return_value = mock_search
        
        result = table.get_embedding( self.test_question )
        
        # Verify result
        self.assertEqual( result, self.test_embedding )
        
        # Verify new embedding generated
        mocks["embedding_mgr"].generate_embedding.assert_called_once_with( 
            self.test_question, 
            normalize_for_cache=True 
        )
    
    def test_get_embedding_database_error( self ):
        """
        Test get_embedding() error handling for database failures.
        
        Ensures:
            - Database exceptions caught gracefully
            - Falls back to generating new embedding
            - Error logged appropriately
        """
        table, mocks = self._create_mocked_question_embeddings_table()
        
        # Mock search to throw exception
        mocks["table"].search.side_effect = Exception( "Database connection failed" )
        
        with patch( "cosa.memory.question_embeddings_table.du.print_stack_trace" ) as mock_print_trace:
            result = table.get_embedding( self.test_question )
        
        # Verify fallback to generation
        self.assertEqual( result, self.test_embedding )
        mocks["embedding_mgr"].generate_embedding.assert_called_once_with( 
            self.test_question, 
            normalize_for_cache=True 
        )
        
        # Verify error logged
        mock_print_trace.assert_called_once()
    
    def test_add_embedding_success( self ):
        """
        Test add_embedding() successful operation.
        
        Ensures:
            - Embedding added to table with correct format
            - Row structure matches expected schema
            - Database add operation called
        """
        table, mocks = self._create_mocked_question_embeddings_table()
        
        table.add_embedding( self.test_question, self.test_embedding )
        
        # Verify add called with correct format
        expected_row = [{"question": self.test_question, "embedding": self.test_embedding}]
        mocks["table"].add.assert_called_once_with( expected_row )
    
    def test_add_embedding_database_error( self ):
        """
        Test add_embedding() error handling for database failures.
        
        Ensures:
            - Database exceptions caught gracefully
            - Error logged with stack trace
            - Method continues without crashing
        """
        table, mocks = self._create_mocked_question_embeddings_table()
        
        # Mock add to throw exception
        mocks["table"].add.side_effect = Exception( "Database write failed" )
        
        with patch( "cosa.memory.question_embeddings_table.du.print_stack_trace" ) as mock_print_trace:
            # Should not raise exception
            table.add_embedding( self.test_question, self.test_embedding )
        
        # Verify error logged
        mock_print_trace.assert_called_once()
        args, kwargs = mock_print_trace.call_args
        # Arguments are: exception, explanation, caller
        self.assertEqual( kwargs["explanation"], "add() failed" )
        self.assertEqual( kwargs["caller"], "QuestionEmbeddingsTable.add_embedding()" )
    
    def test_debug_timing( self ):
        """
        Test debug timing functionality.
        
        Ensures:
            - Stopwatch used when debug=True
            - Timing information displayed
            - Performance tracking works correctly
        """
        table, mocks = self._create_mocked_question_embeddings_table()
        table.debug = True  # Enable debug mode
        
        # Mock search chain
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = []
        
        mocks["table"].search.return_value = mock_search
        
        with patch( "cosa.memory.question_embeddings_table.Stopwatch" ) as mock_stopwatch_class, \
             patch( "cosa.memory.question_embeddings_table.du.print_banner" ):
            
            mock_stopwatch = Mock()
            mock_stopwatch_class.return_value = mock_stopwatch
            
            table.has( self.test_question )
            
            # Verify stopwatch used
            mock_stopwatch_class.assert_called_once_with( msg=f"has( '{self.test_question}' )" )
            mock_stopwatch.print.assert_called_once_with( "Done!", use_millis=True )


def isolated_unit_test():
    """
    Run comprehensive unit tests for QuestionEmbeddingsTable in complete isolation.
    
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
        du.print_banner( "QuestionEmbeddingsTable Unit Tests - Memory System Phase 3", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization',
            'test_has_question_exists',
            'test_has_question_not_exists',
            'test_has_sql_injection_protection',
            'test_get_embedding_from_table',
            'test_get_embedding_generate_new',
            'test_get_embedding_database_error',
            'test_add_embedding_success',
            'test_add_embedding_database_error',
            'test_debug_timing'
        ]
        
        for method in test_methods:
            suite.addTest( TestQuestionEmbeddingsTable( method ) )
        
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
        print( f"QUESTION EMBEDDINGS TABLE UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL QUESTION EMBEDDINGS TABLE TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME QUESTION EMBEDDINGS TABLE TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 QUESTION EMBEDDINGS TABLE TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} QuestionEmbeddingsTable unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )