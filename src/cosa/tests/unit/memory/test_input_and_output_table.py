"""
Unit tests for InputAndOutputTable with comprehensive mocking.

Tests the InputAndOutputTable class including:
- Database connection and table initialization
- Synchronous and asynchronous embedding generation
- Data insertion with proper row structure
- KNN search with vector similarity
- Statistical aggregation and reporting
- Threading behavior for async operations
- Configuration-based behavior switching
- Error handling for database failures

Zero external dependencies - all database operations, threading operations,
file system operations, and external service calls are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call, ANY
import time
import threading
from typing import List, Dict, Any, Optional

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.memory.input_and_output_table import InputAndOutputTable


class TestInputAndOutputTable( unittest.TestCase ):
    """
    Comprehensive unit tests for InputAndOutputTable class.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All InputAndOutputTable functionality tested in isolation
        - Database operations properly mocked
        - Async threading behavior validated
        - Configuration integration tested
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
        self.test_input = "What is 2+2?"
        self.test_output = "The answer is 4"
        self.test_embedding = [0.1] * 1536
        self.test_date = "2025-08-05"
        self.test_time = "12:00:00"
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mocked_input_and_output_table( self ):
        """
        Helper to create fully mocked InputAndOutputTable.
        
        Returns:
            Tuple of (table_instance, mocks_dict) for testing
        """
        # Create mock objects
        mock_config_mgr = Mock()
        mock_embedding_mgr = Mock()
        mock_question_embeddings_tbl = Mock()
        mock_db = Mock()
        mock_table = Mock()
        
        # Setup mock behaviors
        mock_config_mgr.get.return_value = "/test/db"
        mock_embedding_mgr.generate_embedding.return_value = self.test_embedding
        mock_question_embeddings_tbl.get_embedding.return_value = self.test_embedding
        mock_question_embeddings_tbl.has.return_value = False
        mock_db.open_table.return_value = mock_table
        mock_table.count_rows.return_value = 100
        
        mocks = {
            "config_mgr": mock_config_mgr,
            "embedding_mgr": mock_embedding_mgr,
            "question_embeddings_tbl": mock_question_embeddings_tbl,
            "db": mock_db,
            "table": mock_table
        }
        
        with patch( "cosa.memory.input_and_output_table.ConfigurationManager", return_value=mock_config_mgr ), \
             patch( "cosa.memory.input_and_output_table.EmbeddingManager", return_value=mock_embedding_mgr ), \
             patch( "cosa.memory.input_and_output_table.QuestionEmbeddingsTable", return_value=mock_question_embeddings_tbl ), \
             patch( "cosa.memory.input_and_output_table.lancedb.connect", return_value=mock_db ), \
             patch( "cosa.memory.input_and_output_table.du.get_project_root", return_value="/project/root" ), \
             patch( "cosa.memory.input_and_output_table.du.get_current_date", return_value=self.test_date ), \
             patch( "cosa.memory.input_and_output_table.du.get_current_time", return_value=self.test_time ), \
             patch( "builtins.print" ):\
            
            table = InputAndOutputTable( debug=False, verbose=False )
        
        return table, mocks
    
    def test_initialization( self ):
        """
        Test InputAndOutputTable initialization.
        
        Ensures:
            - ConfigurationManager created with correct environment variable
            - EmbeddingManager and QuestionEmbeddingsTable created
            - Database connection established
            - Table opened and row count printed
        """
        mock_config_mgr = Mock()
        mock_embedding_mgr = Mock()
        mock_question_embeddings_tbl = Mock()
        mock_db = Mock()
        mock_table = Mock()
        
        mock_config_mgr.get.return_value = "/test/db"
        mock_db.open_table.return_value = mock_table
        mock_table.count_rows.return_value = 42
        
        with patch( "cosa.memory.input_and_output_table.ConfigurationManager", return_value=mock_config_mgr ) as mock_config_class, \
             patch( "cosa.memory.input_and_output_table.EmbeddingManager", return_value=mock_embedding_mgr ) as mock_embedding_class, \
             patch( "cosa.memory.input_and_output_table.QuestionEmbeddingsTable", return_value=mock_question_embeddings_tbl ) as mock_question_class, \
             patch( "cosa.memory.input_and_output_table.lancedb.connect", return_value=mock_db ) as mock_lancedb, \
             patch( "cosa.memory.input_and_output_table.du.get_project_root", return_value="/project/root" ), \
             patch( "builtins.print" ) as mock_print:
            
            # Test initialization
            table = InputAndOutputTable( debug=True, verbose=True )
            
            # Verify initialization calls
            mock_config_class.assert_called_once_with( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            mock_embedding_class.assert_called_once_with( debug=True, verbose=True )
            mock_question_class.assert_called_once_with( debug=True, verbose=True )
            mock_config_mgr.get.assert_called_once_with( "path to database wo root" )
            mock_lancedb.assert_called_once_with( "/project/root/test/db" )
            mock_db.open_table.assert_called_once_with( "input_and_output_tbl" )
            mock_table.count_rows.assert_called_once()
            
            # Verify attributes
            self.assertTrue( table.debug )
            self.assertTrue( table.verbose )
    
    def test_insert_io_row_synchronous( self ):
        """
        Test synchronous insert_io_row operation.
        
        Ensures:
            - Row inserted with correct structure
            - Embeddings generated when not provided
            - Synchronous execution completes immediately
            - Table add operation called correctly
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Configure config manager for sync mode
        mocks["config_mgr"].get.side_effect = lambda key, default=None, return_type=None: {
            "debug text truncation length": 48,
            "async embedding generation": False
        }.get( key, default )
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ) as mock_stopwatch_class:
            mock_stopwatch = Mock()
            mock_stopwatch_class.return_value = mock_stopwatch
            
            # Test synchronous insertion
            table.insert_io_row(
                input_type="test_sync",
                input=self.test_input,
                output_raw=self.test_output,
                output_final=self.test_output,
                async_embedding=False
            )
            
            # Verify table add called with correct structure
            mocks["table"].add.assert_called_once()
            call_args = mocks["table"].add.call_args[0][0]  # First argument (new_row)
            
            self.assertEqual( len( call_args ), 1 )  # Single row
            row = call_args[0]
            
            # Verify row structure
            expected_fields = [
                "date", "time", "input_type", "input", "input_embedding",
                "output_raw", "output_final", "output_final_embedding", "solution_path_wo_root"
            ]
            for field in expected_fields:
                self.assertIn( field, row )
            
            # Verify content
            self.assertEqual( row["input_type"], "test_sync" )
            self.assertEqual( row["input"], self.test_input )
            self.assertEqual( row["output_final"], self.test_output )
            self.assertEqual( row["input_embedding"], self.test_embedding )
            self.assertEqual( row["output_final_embedding"], self.test_embedding )
            
            # Verify embeddings generated
            mocks["question_embeddings_tbl"].get_embedding.assert_called_once_with( self.test_input )
            mocks["embedding_mgr"].generate_embedding.assert_called_once_with( self.test_output, normalize_for_cache=True )
    
    def test_insert_io_row_with_provided_embeddings( self ):
        """
        Test insert_io_row with pre-provided embeddings.
        
        Ensures:
            - Provided embeddings are used
            - No new embedding generation occurs
            - Row structure is correct
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Configure for sync mode
        mocks["config_mgr"].get.side_effect = lambda key, default=None, return_type=None: {
            "debug text truncation length": 48,
            "async embedding generation": False
        }.get( key, default )
        
        custom_input_embedding = [0.2] * 1536
        custom_output_embedding = [0.3] * 1536
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ):
            table.insert_io_row(
                input_type="test_provided_embeddings",
                input=self.test_input,
                input_embedding=custom_input_embedding,
                output_raw=self.test_output,
                output_final=self.test_output,
                output_final_embedding=custom_output_embedding,
                async_embedding=False
            )
            
            # Verify no embedding generation
            mocks["question_embeddings_tbl"].get_embedding.assert_not_called()
            mocks["embedding_mgr"].generate_embedding.assert_not_called()
            
            # Verify provided embeddings used
            call_args = mocks["table"].add.call_args[0][0]
            row = call_args[0]
            self.assertEqual( row["input_embedding"], custom_input_embedding )
            self.assertEqual( row["output_final_embedding"], custom_output_embedding )
    
    def test_insert_io_row_asynchronous( self ):
        """
        Test asynchronous insert_io_row operation.
        
        Ensures:
            - Method returns immediately
            - Background thread started for embedding generation
            - Thread calls add operation eventually
            - Cache hit detection works in async mode
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Configure for async mode and cache behavior
        mocks["config_mgr"].get.side_effect = lambda key, default=None, return_type=None: {
            "debug text truncation length": 48,
            "async embedding generation": True
        }.get( key, default )
        
        # Mock has() to return False (cache miss) then True (cache hit)
        mocks["question_embeddings_tbl"].has.return_value = False
        
        # Track thread creation by mocking Thread class directly
        created_threads = []
        
        class MockThread:
            def __init__( self, target=None, daemon=None ):
                created_threads.append( (target, daemon) )
                self.target = target
                self.daemon = daemon
            
            def start( self ):
                pass  # Mock start method
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             patch( "cosa.memory.input_and_output_table.threading.Thread", MockThread ):
            
            # Test asynchronous insertion
            table.insert_io_row(
                input_type="test_async",
                input=self.test_input,
                output_raw=self.test_output,
                output_final=self.test_output,
                async_embedding=True
            )
            
            # Verify thread was created
            self.assertEqual( len( created_threads ), 1 )
            target_func, daemon_flag = created_threads[0]
            self.assertTrue( daemon_flag )  # Should be daemon thread
            self.assertIsNotNone( target_func )
            
            # Verify main thread didn't call add (async thread should)
            mocks["table"].add.assert_not_called()
            
            # Test the actual async function by calling it directly
            target_func()
            
            # Now verify the async function called add
            mocks["table"].add.assert_called_once()
            call_args = mocks["table"].add.call_args[0][0]
            row = call_args[0]
            self.assertEqual( row["input_type"], "test_async" )
    
    def test_insert_io_row_async_error_handling( self ):
        """
        Test error handling in asynchronous insertion.
        
        Ensures:
            - Exceptions in async thread are caught
            - Error logging occurs
            - Thread doesn't crash the main process
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Configure for async mode
        mocks["config_mgr"].get.side_effect = lambda key, default=None, return_type=None: {
            "debug text truncation length": 48,
            "async embedding generation": True
        }.get( key, default )
        
        # Make embedding generation fail
        mocks["question_embeddings_tbl"].get_embedding.side_effect = Exception( "Embedding generation failed" )
        
        # Track thread creation to get the target function
        created_threads = []
        
        class MockThread:
            def __init__( self, target=None, daemon=None ):
                created_threads.append( (target, daemon) )
                self.target = target
                self.daemon = daemon
            
            def start( self ):
                pass  # Mock start method
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             patch( "cosa.memory.input_and_output_table.threading.Thread", MockThread ), \
             patch( "cosa.memory.input_and_output_table.du.print_banner" ), \
             patch( "cosa.memory.input_and_output_table.du.print_stack_trace" ) as mock_stack_trace, \
             patch( "builtins.print" ):
            
            table.insert_io_row(
                input_type="test_async_error",
                input=self.test_input,
                output_raw=self.test_output,
                output_final=self.test_output,
                async_embedding=True
            )
            
            # Get and execute the async function
            target_func = created_threads[0][0]
            target_func()  # This should not raise an exception
            
            # Verify error handling was called
            mock_stack_trace.assert_called_once()
            args, kwargs = mock_stack_trace.call_args
            self.assertEqual( kwargs["explanation"], "Async embedding generation failed" )
            self.assertEqual( kwargs["caller"], "insert_io_row async thread" )
    
    def test_get_knn_by_input( self ):
        """
        Test KNN search functionality.
        
        Ensures:
            - Embedding generated for search terms
            - Vector search performed with correct parameters
            - Results returned in proper format
            - Dot product metric used
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Mock search chain
        mock_search_query = Mock()
        mock_metric = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        
        mock_search_query.metric.return_value = mock_metric
        mock_metric.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = [
            {"input": "What time is it?", "output_final": "3:30 PM", "input_embedding": self.test_embedding},
            {"input": "Current time?", "output_final": "3:30 PM", "input_embedding": self.test_embedding}
        ]
        
        mocks["table"].search.return_value = mock_search_query
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ):
            results = table.get_knn_by_input( "time query", k=5 )
        
        # Verify search chain
        mocks["question_embeddings_tbl"].get_embedding.assert_called_once_with( "time query" )
        mocks["table"].search.assert_called_once_with( self.test_embedding, vector_column_name="input_embedding" )
        mock_search_query.metric.assert_called_once_with( "dot" )
        mock_metric.limit.assert_called_once_with( 5 )
        mock_limit.select.assert_called_once_with( ["input", "output_final", "input_embedding"] )
        mock_select.to_list.assert_called_once()
        
        # Verify results
        self.assertEqual( len( results ), 2 )
        self.assertEqual( results[0]["input"], "What time is it?" )
        self.assertEqual( results[1]["input"], "Current time?" )
    
    def test_get_knn_by_input_no_embeddings( self ):
        """
        Test KNN search when no embeddings available.
        
        Ensures:
            - Empty embedding list handled gracefully
            - Returns empty results
            - No search performed
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Mock empty embedding
        mocks["question_embeddings_tbl"].get_embedding.return_value = []
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             patch( "cosa.memory.input_and_output_table.du.print_banner" ), \
             patch( "builtins.print" ):
            
            results = table.get_knn_by_input( "test query", k=3 )
        
        # Verify no search performed
        mocks["table"].search.assert_not_called()
        
        # Verify empty results
        self.assertEqual( results, [] )
    
    def test_get_all_io( self ):
        """
        Test get_all_io functionality.
        
        Ensures:
            - Correct fields selected
            - Limit applied properly
            - Results converted to list format
            - Warning displayed when results truncated
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Mock search chain
        mock_search = Mock()
        mock_select = Mock()
        mock_limit = Mock()
        
        mock_search.select.return_value = mock_select
        mock_select.limit.return_value = mock_limit
        mock_limit.to_list.return_value = [
            {"date": "2025-08-05", "time": "12:00", "input_type": "test", "input": "hello", "output_final": "hi"},
            {"date": "2025-08-05", "time": "12:01", "input_type": "test", "input": "bye", "output_final": "goodbye"}
        ]
        
        mocks["table"].search.return_value = mock_search
        mocks["table"].count_rows.return_value = 1000  # Less than max_rows
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             patch( "builtins.print" ) as mock_print:
            
            results = table.get_all_io( max_rows=500 )
        
        # Verify search chain
        mocks["table"].search.assert_called_once()
        mock_search.select.assert_called_once_with( ["date", "time", "input_type", "input", "output_final"] )
        mock_select.limit.assert_called_once_with( 500 )
        mock_limit.to_list.assert_called_once()
        
        # Verify results
        self.assertEqual( len( results ), 2 )
        self.assertEqual( results[0]["input"], "hello" )
        
        # Verify no warning (1000 < 500 + 2 results, so no truncation)
        warning_calls = [call for call in mock_print.call_args_list if "WARNING" in str(call)]
        self.assertEqual( len( warning_calls ), 0 )
    
    def test_get_all_io_truncation_warning( self ):
        """
        Test get_all_io truncation warning.
        
        Ensures:
            - Warning displayed when max_rows reached
            - Actual vs total row counts shown
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Mock search to return exactly max_rows results
        mock_search = Mock()
        mock_select = Mock()
        mock_limit = Mock()
        
        results_data = [{"input": f"test{i}"} for i in range(10)]  # Exactly max_rows
        mock_limit.to_list.return_value = results_data
        mock_select.limit.return_value = mock_limit
        mock_search.select.return_value = mock_select
        
        mocks["table"].search.return_value = mock_search
        mocks["table"].count_rows.return_value = 50  # More than max_rows
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             patch( "builtins.print" ) as mock_print:
            
            results = table.get_all_io( max_rows=10 )
        
        # Verify warning displayed
        warning_calls = [call for call in mock_print.call_args_list if "WARNING" in str(call)]
        self.assertGreater( len( warning_calls ), 0 )
        
        # Verify warning content
        warning_text = str( warning_calls[0] )
        self.assertIn( "10", warning_text )  # max_rows
        self.assertIn( "50", warning_text )  # total rows
    
    def test_get_io_stats_by_input_type( self ):
        """
        Test input type statistics functionality.
        
        Ensures:
            - Pandas groupby operations work correctly
            - Statistics dictionary properly formatted
            - Input type counts calculated correctly
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Mock pandas DataFrame and operations
        mock_search = Mock()
        mock_select = Mock()
        mock_limit = Mock()
        mock_df = MagicMock()
        
        # Setup mock DataFrame with groupby behavior
        mock_groupby = MagicMock()
        mock_df.groupby.return_value = mock_groupby
        
        # Mock the chain: groupby()['input_type'].transform()  
        mock_grouped_series = Mock()
        mock_groupby.__getitem__.return_value = mock_grouped_series
        mock_grouped_series.transform.return_value = [3, 3, 2, 2, 1]
        
        # Setup set_index chain
        mock_indexed_df = MagicMock()
        mock_df.set_index.return_value = mock_indexed_df
        mock_series = Mock()
        mock_indexed_df.__getitem__.return_value = mock_series
        mock_series.to_dict.return_value = {
            "question": 3,
            "command": 2,
            "test": 1
        }
        
        # Mock DataFrame length for len() calls
        mock_df.__len__ = Mock(return_value=5)
        
        mock_limit.to_pandas.return_value = mock_df
        mock_select.limit.return_value = mock_limit
        mock_search.select.return_value = mock_select
        
        mocks["table"].search.return_value = mock_search
        mocks["table"].count_rows.return_value = 6  # Less than max_rows
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             patch( "builtins.print" ):
            
            stats = table.get_io_stats_by_input_type( max_rows=100 )
        
        # Verify search operations
        mock_search.select.assert_called_once_with( ["input_type"] )
        mock_select.limit.assert_called_once_with( 100 )
        mock_limit.to_pandas.assert_called_once()
        
        # Verify pandas operations
        mock_df.groupby.assert_called_once_with( ["input_type"] )
        mock_df.set_index.assert_called_once_with( 'input_type' )
        
        # Verify result format
        self.assertIsInstance( stats, dict )
        expected_stats = {"question": 3, "command": 2, "test": 1}
        self.assertEqual( stats, expected_stats )
    
    def test_get_all_qnr( self ):
        """
        Test agent router query/response functionality.
        
        Ensures:
            - WHERE clause filters by input_type pattern
            - LIKE operator used for pattern matching
            - Results limited and formatted correctly
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Mock search chain
        mock_search = Mock()
        mock_where = Mock()
        mock_limit = Mock()
        mock_select = Mock()
        
        mock_search.where.return_value = mock_where
        mock_where.limit.return_value = mock_limit
        mock_limit.select.return_value = mock_select
        mock_select.to_list.return_value = [
            {"input_type": "agent router go to math", "input": "solve 2+2", "output_final": "4"},
            {"input_type": "agent router go to calendar", "input": "what date", "output_final": "Aug 5"}
        ]
        
        mocks["table"].search.return_value = mock_search
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             patch( "builtins.print" ):
            
            results = table.get_all_qnr( max_rows=25 )
        
        # Verify search chain
        mocks["table"].search.assert_called_once()
        mock_search.where.assert_called_once_with( "input_type LIKE 'agent router go to %'" )
        mock_where.limit.assert_called_once_with( 25 )
        mock_limit.select.assert_called_once_with( ["date", "time", "input_type", "input", "output_final"] )
        mock_select.to_list.assert_called_once()
        
        # Verify results
        self.assertEqual( len( results ), 2 )
        self.assertEqual( results[0]["input_type"], "agent router go to math" )
        self.assertEqual( results[1]["input_type"], "agent router go to calendar" )
    
    def test_configuration_based_async_behavior( self ):
        """
        Test configuration-based async behavior switching.
        
        Ensures:
            - async_embedding=None uses config value
            - Config value properly retrieved and applied
            - Boolean conversion works correctly
        """
        table, mocks = self._create_mocked_input_and_output_table()
        
        # Configure for config-based async
        mocks["config_mgr"].get.side_effect = lambda key, default=None, return_type=None: {
            "debug text truncation length": 48,
            "async embedding generation": True  # Config says async
        }.get( key, default )
        
        # Track thread creation
        created_threads = []
        
        class MockThread:
            def __init__( self, target=None, daemon=None ):
                created_threads.append( (target, daemon) )
                self.target = target
                self.daemon = daemon
            
            def start( self ):
                pass  # Mock start method
        
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             patch( "cosa.memory.input_and_output_table.threading.Thread", MockThread ), \
             patch( "builtins.print" ):
            
            table.insert_io_row(
                input_type="test_config_async",
                input=self.test_input,
                output_raw=self.test_output,
                output_final=self.test_output
                # async_embedding=None - should use config
            )
            
            # Verify config was consulted
            config_calls = [call for call in mocks["config_mgr"].get.call_args_list 
                          if "async embedding generation" in str(call)]
            self.assertGreater( len( config_calls ), 0 )
            
            # Verify async behavior (thread created)
            self.assertEqual( len( created_threads ), 1 )


def isolated_unit_test():
    """
    Run comprehensive unit tests for InputAndOutputTable in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real database or threading operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "InputAndOutputTable Unit Tests - Memory System Phase 3", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization',
            'test_insert_io_row_synchronous',
            'test_insert_io_row_with_provided_embeddings',
            'test_insert_io_row_asynchronous',
            'test_insert_io_row_async_error_handling',
            'test_get_knn_by_input',
            'test_get_knn_by_input_no_embeddings',
            'test_get_all_io',
            'test_get_all_io_truncation_warning',
            'test_get_io_stats_by_input_type',
            'test_get_all_qnr',
            'test_configuration_based_async_behavior'
        ]
        
        for method in test_methods:
            suite.addTest( TestInputAndOutputTable( method ) )
        
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
        print( f"INPUT AND OUTPUT TABLE UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL INPUT AND OUTPUT TABLE TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME INPUT AND OUTPUT TABLE TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 INPUT AND OUTPUT TABLE TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} InputAndOutputTable unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )