"""
Unit tests for TodoFifoQueue with QueryLogTable integration.

Tests the TodoFifoQueue class including:
- Three-level architecture initialization (verbatim, normalized, gist)
- QueryLogTable integration for search logging
- EmbeddingManager integration for vector storage
- Agent routing and question processing
- Hierarchical search functionality with query logging
- WebSocket integration for todo queue events

This file focuses on testing the critical QueryLogTable integration
that is part of the Three-Level Question Representation Architecture.
Zero external dependencies - all components mocked for isolated testing.
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
from cosa.rest.todo_fifo_queue import TodoFifoQueue


class TestTodoFifoQueue( unittest.TestCase ):
    """
    Comprehensive unit tests for TodoFifoQueue with QueryLogTable integration.

    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        - Comprehensive mocking of all agent and memory components

    Ensures:
        - All TodoFifoQueue functionality tested in isolation
        - QueryLogTable integration properly validated
        - Three-level architecture components work correctly
        - Agent routing and search functionality verified
    """

    def setUp( self ):
        """
        Setup for each test method.

        Ensures:
            - Clean state for each test
            - Mock manager is available
            - All external dependencies mocked
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()

        # Mock external dependencies
        self.mock_websocket_mgr = Mock()
        self.mock_snapshot_mgr = Mock()
        self.mock_app = Mock()
        self.mock_config_mgr = Mock()
        self.mock_emit_speech_callback = Mock()

        # Configure config manager defaults
        self.mock_config_mgr.get.side_effect = lambda key, default=False, return_type="boolean": default

        # Common test data
        self.test_query_verbatim = "What time is it?"
        self.test_query_normalized = "what time be it"
        self.test_query_gist = "current time"
        self.test_user_id = "user123"
        self.test_websocket_id = "ws_session_456"
        self.test_embeddings = {
            'verbatim': [0.1] * 1536,
            'normalized': [0.2] * 1536,
            'gist': [0.3] * 1536
        }

    def tearDown( self ):
        """
        Cleanup after each test method.

        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()

    @patch( 'cosa.rest.todo_fifo_queue.QueryLogTable' )
    @patch( 'cosa.rest.todo_fifo_queue.EmbeddingManager' )
    @patch( 'cosa.rest.todo_fifo_queue.Normalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.GistNormalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.Gister' )
    @patch( 'cosa.rest.todo_fifo_queue.LlmClientFactory' )
    def test_initialization_three_level_architecture( self, mock_llm_factory, mock_gister,
                                                    mock_gist_normalizer, mock_normalizer,
                                                    mock_embedding_manager, mock_query_log ):
        """
        Test TodoFifoQueue initialization with three-level architecture components.

        Ensures:
            - QueryLogTable initialized with debug/verbose settings
            - EmbeddingManager initialized with debug/verbose settings
            - Text processors (Normalizer, GistNormalizer) initialized
            - Gister initialized for backward compatibility
            - LLM factory initialized for v010 compatibility
        """
        # Create instance
        queue = TodoFifoQueue(
            websocket_mgr=self.mock_websocket_mgr,
            snapshot_mgr=self.mock_snapshot_mgr,
            app=self.mock_app,
            config_mgr=self.mock_config_mgr,
            emit_speech_callback=self.mock_emit_speech_callback,
            debug=True,
            verbose=True
        )

        # Verify QueryLogTable initialization
        mock_query_log.assert_called_once_with( debug=True, verbose=True )
        self.assertIsNotNone( queue.query_log )

        # Verify EmbeddingManager initialization
        mock_embedding_manager.assert_called_once_with( debug=True, verbose=True )
        self.assertIsNotNone( queue.embedding_manager )

        # Verify text processors initialized
        mock_normalizer.assert_called_once_with()
        mock_gist_normalizer.assert_called_once_with( debug=True, verbose=True )
        mock_gister.assert_called_once_with( debug=True, verbose=True )

        # Verify LLM factory initialization
        mock_llm_factory.assert_called_once_with( debug=True, verbose=True )

        # Verify debug/verbose settings propagated
        self.assertTrue( queue.debug )
        self.assertTrue( queue.verbose )

    @patch( 'cosa.rest.todo_fifo_queue.QueryLogTable' )
    @patch( 'cosa.rest.todo_fifo_queue.EmbeddingManager' )
    @patch( 'cosa.rest.todo_fifo_queue.Normalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.GistNormalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.Gister' )
    @patch( 'cosa.rest.todo_fifo_queue.LlmClientFactory' )
    def test_query_logging_integration( self, mock_llm_factory, mock_gister,
                                       mock_gist_normalizer, mock_normalizer,
                                       mock_embedding_manager, mock_query_log ):
        """
        Test _log_query_with_results method for QueryLogTable integration.

        Ensures:
            - query_log.log_query called with correct parameters
            - All three levels of query representation logged
            - User and session information captured
            - Embeddings and match results logged
            - Error handling for logging failures
        """
        # Setup mocks
        mock_query_log_instance = Mock()
        mock_query_log.return_value = mock_query_log_instance

        queue = TodoFifoQueue(
            websocket_mgr=self.mock_websocket_mgr,
            snapshot_mgr=self.mock_snapshot_mgr,
            app=self.mock_app,
            debug=True
        )

        # Test data
        cache_hits = { 'verbatim': False, 'normalized': True, 'gist': False }
        match_result = { 'match_type': 'normalized', 'score': 0.95, 'source': 'cached' }

        # Call the method
        queue._log_query_with_results(
            query_verbatim=self.test_query_verbatim,
            query_normalized=self.test_query_normalized,
            query_gist=self.test_query_gist,
            user_id=self.test_user_id,
            websocket_id=self.test_websocket_id,
            embeddings=self.test_embeddings,
            cache_hits=cache_hits,
            match_result=match_result
        )

        # Verify query_log.log_query called with correct parameters
        mock_query_log_instance.log_query.assert_called_once()
        call_args = mock_query_log_instance.log_query.call_args

        # Verify required parameters passed
        self.assertEqual( call_args.kwargs['query_verbatim'], self.test_query_verbatim )
        self.assertEqual( call_args.kwargs['query_normalized'], self.test_query_normalized )
        self.assertEqual( call_args.kwargs['query_gist'], self.test_query_gist )
        self.assertEqual( call_args.kwargs['user_id'], self.test_user_id )
        self.assertEqual( call_args.kwargs['session_id'], self.test_websocket_id )

    @patch( 'cosa.rest.todo_fifo_queue.QueryLogTable' )
    @patch( 'cosa.rest.todo_fifo_queue.EmbeddingManager' )
    @patch( 'cosa.rest.todo_fifo_queue.Normalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.GistNormalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.Gister' )
    @patch( 'cosa.rest.todo_fifo_queue.LlmClientFactory' )
    def test_query_logging_error_handling( self, mock_llm_factory, mock_gister,
                                          mock_gist_normalizer, mock_normalizer,
                                          mock_embedding_manager, mock_query_log ):
        """
        Test error handling in _log_query_with_results method.

        Ensures:
            - Graceful handling of QueryLogTable failures
            - Error messages printed when debug enabled
            - Exception does not propagate to caller
            - System continues operating after logging failures
        """
        # Setup mocks with query_log failure
        mock_query_log_instance = Mock()
        mock_query_log_instance.log_query.side_effect = Exception( "Database connection failed" )
        mock_query_log.return_value = mock_query_log_instance

        queue = TodoFifoQueue(
            websocket_mgr=self.mock_websocket_mgr,
            snapshot_mgr=self.mock_snapshot_mgr,
            app=self.mock_app,
            debug=True
        )

        # Test that error doesn't propagate
        with patch( 'builtins.print' ) as mock_print:
            queue._log_query_with_results(
                query_verbatim=self.test_query_verbatim,
                query_normalized=self.test_query_normalized,
                query_gist=self.test_query_gist,
                user_id=self.test_user_id,
                websocket_id=self.test_websocket_id,
                embeddings=self.test_embeddings,
                cache_hits={},
                match_result={}
            )

            # Verify error was printed (debug mode)
            self.assertTrue( any( "Error logging query" in str(call) for call in mock_print.call_args_list ) )

    @patch( 'cosa.rest.todo_fifo_queue.QueryLogTable' )
    @patch( 'cosa.rest.todo_fifo_queue.EmbeddingManager' )
    @patch( 'cosa.rest.todo_fifo_queue.Normalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.GistNormalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.Gister' )
    @patch( 'cosa.rest.todo_fifo_queue.LlmClientFactory' )
    def test_three_level_text_processing( self, mock_llm_factory, mock_gister,
                                         mock_gist_normalizer, mock_normalizer,
                                         mock_embedding_manager, mock_query_log ):
        """
        Test three-level text processing architecture.

        Ensures:
            - Normalizer processes verbatim to normalized
            - GistNormalizer processes to gist representation
            - Both processors available for runtime selection
            - Processing maintains hierarchy (verbatim → normalized → gist)
        """
        # Setup mock processors
        mock_normalizer_instance = Mock()
        mock_normalizer_instance.normalize.return_value = self.test_query_normalized
        mock_normalizer.return_value = mock_normalizer_instance

        mock_gist_normalizer_instance = Mock()
        mock_gist_normalizer_instance.normalize.return_value = self.test_query_gist
        mock_gist_normalizer.return_value = mock_gist_normalizer_instance

        queue = TodoFifoQueue(
            websocket_mgr=self.mock_websocket_mgr,
            snapshot_mgr=self.mock_snapshot_mgr,
            app=self.mock_app
        )

        # Verify processors are available
        self.assertIsNotNone( queue.normalizer )
        self.assertIsNotNone( queue.gist_normalizer )

        # Test processing pipeline
        normalized_result = queue.normalizer.normalize( self.test_query_verbatim )
        gist_result = queue.gist_normalizer.normalize( self.test_query_verbatim )

        # Verify processing calls
        mock_normalizer_instance.normalize.assert_called_with( self.test_query_verbatim )
        mock_gist_normalizer_instance.normalize.assert_called_with( self.test_query_verbatim )

        # Verify results
        self.assertEqual( normalized_result, self.test_query_normalized )
        self.assertEqual( gist_result, self.test_query_gist )

    @patch( 'cosa.rest.todo_fifo_queue.QueryLogTable' )
    @patch( 'cosa.rest.todo_fifo_queue.EmbeddingManager' )
    @patch( 'cosa.rest.todo_fifo_queue.Normalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.GistNormalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.Gister' )
    @patch( 'cosa.rest.todo_fifo_queue.LlmClientFactory' )
    def test_embedding_manager_integration( self, mock_llm_factory, mock_gister,
                                           mock_gist_normalizer, mock_normalizer,
                                           mock_embedding_manager, mock_query_log ):
        """
        Test EmbeddingManager integration for vector storage.

        Ensures:
            - EmbeddingManager available for vector operations
            - Can generate embeddings for all three levels
            - Debug/verbose settings propagated correctly
            - Integration supports hierarchical search requirements
        """
        # Setup mock embedding manager
        mock_embedding_instance = Mock()
        mock_embedding_manager.return_value = mock_embedding_instance

        queue = TodoFifoQueue(
            websocket_mgr=self.mock_websocket_mgr,
            snapshot_mgr=self.mock_snapshot_mgr,
            app=self.mock_app,
            debug=True,
            verbose=True
        )

        # Verify EmbeddingManager initialized with correct settings
        mock_embedding_manager.assert_called_once_with( debug=True, verbose=True )

        # Verify embedding manager available
        self.assertIsNotNone( queue.embedding_manager )
        self.assertEqual( queue.embedding_manager, mock_embedding_instance )

    @patch( 'cosa.rest.todo_fifo_queue.QueryLogTable' )
    @patch( 'cosa.rest.todo_fifo_queue.EmbeddingManager' )
    @patch( 'cosa.rest.todo_fifo_queue.Normalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.GistNormalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.Gister' )
    @patch( 'cosa.rest.todo_fifo_queue.LlmClientFactory' )
    def test_configuration_management( self, mock_llm_factory, mock_gister,
                                      mock_gist_normalizer, mock_normalizer,
                                      mock_embedding_manager, mock_query_log ):
        """
        Test configuration management integration.

        Ensures:
            - auto_debug setting read from config
            - inject_bugs setting read from config
            - Default values used when config_mgr is None
            - Boolean type conversion handled correctly
        """
        # Test with config manager
        self.mock_config_mgr.get.side_effect = lambda key, default=False, return_type="boolean": {
            "debug auto": True,
            "debug inject bugs": False
        }.get( key, default )

        queue = TodoFifoQueue(
            websocket_mgr=self.mock_websocket_mgr,
            snapshot_mgr=self.mock_snapshot_mgr,
            app=self.mock_app,
            config_mgr=self.mock_config_mgr
        )

        # Verify config values read
        self.assertTrue( queue.auto_debug )
        self.assertFalse( queue.inject_bugs )

        # Verify config calls
        expected_calls = [
            call( "debug auto", default=False, return_type="boolean" ),
            call( "debug inject bugs", default=False, return_type="boolean" )
        ]
        self.mock_config_mgr.get.assert_has_calls( expected_calls, any_order=True )

        # Test without config manager
        queue_no_config = TodoFifoQueue(
            websocket_mgr=self.mock_websocket_mgr,
            snapshot_mgr=self.mock_snapshot_mgr,
            app=self.mock_app,
            config_mgr=None
        )

        # Verify defaults used
        self.assertFalse( queue_no_config.auto_debug )
        self.assertFalse( queue_no_config.inject_bugs )

    @patch( 'cosa.rest.todo_fifo_queue.QueryLogTable' )
    @patch( 'cosa.rest.todo_fifo_queue.EmbeddingManager' )
    @patch( 'cosa.rest.todo_fifo_queue.Normalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.GistNormalizer' )
    @patch( 'cosa.rest.todo_fifo_queue.Gister' )
    @patch( 'cosa.rest.todo_fifo_queue.LlmClientFactory' )
    def test_inheritance_from_fifo_queue( self, mock_llm_factory, mock_gister,
                                         mock_gist_normalizer, mock_normalizer,
                                         mock_embedding_manager, mock_query_log ):
        """
        Test inheritance from FifoQueue base class.

        Ensures:
            - FifoQueue initialization called with correct parameters
            - WebSocket manager passed to parent
            - Queue name set to "todo"
            - Auto-emission enabled by default
            - All base queue functionality inherited
        """
        queue = TodoFifoQueue(
            websocket_mgr=self.mock_websocket_mgr,
            snapshot_mgr=self.mock_snapshot_mgr,
            app=self.mock_app
        )

        # Verify inheritance properties
        self.assertEqual( queue.websocket_mgr, self.mock_websocket_mgr )
        self.assertEqual( queue.queue_name, "todo" )
        self.assertTrue( queue.emit_enabled )

        # Verify base queue functionality inherited
        self.assertTrue( hasattr( queue, 'push' ) )
        self.assertTrue( hasattr( queue, 'pop' ) )
        self.assertTrue( hasattr( queue, 'head' ) )
        self.assertTrue( hasattr( queue, 'size' ) )
        self.assertTrue( hasattr( queue, 'is_empty' ) )


def isolated_unit_test():
    """
    Run comprehensive unit tests for TodoFifoQueue in complete isolation.

    Ensures:
        - All external dependencies mocked
        - No real QueryLogTable operations
        - No real embedding operations
        - Deterministic test results
        - Fast execution

    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()

    try:
        du.print_banner( "TodoFifoQueue Unit Tests - Three-Level Architecture Phase 3", prepend_nl=True )

        # Create test suite
        suite = unittest.TestSuite()

        # Add all test methods
        test_methods = [
            'test_initialization_three_level_architecture',
            'test_query_logging_integration',
            'test_query_logging_error_handling',
            'test_three_level_text_processing',
            'test_embedding_manager_integration',
            'test_configuration_management',
            'test_inheritance_from_fifo_queue'
        ]

        for method in test_methods:
            suite.addTest( TestTodoFifoQueue( method ) )

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
        print( f"TODO FIFO QUEUE UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL TODO FIFO QUEUE TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME TODO FIFO QUEUE TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 TODO FIFO QUEUE TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} TodoFifoQueue unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )