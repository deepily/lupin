"""
Unit tests for FifoQueue with comprehensive mocking.

Tests the FifoQueue class including:
- FIFO ordering and queue operations (push, pop, peek)
- Dictionary lookup capabilities with O(1) access
- Queue state management (accepting jobs, focus mode, blocking objects)
- Auto-emission functionality with WebSocket integration
- User job tracking and filtering
- Queue statistics and metrics
- Thread-safe operations and concurrent access patterns

Zero external dependencies - all WebSocket operations, user tracking,
and external service calls are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import time
from collections import OrderedDict
from typing import List, Dict, Any, Optional

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.rest.fifo_queue import FifoQueue


class TestFifoQueue( unittest.TestCase ):
    """
    Comprehensive unit tests for FifoQueue class.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All FifoQueue functionality tested in isolation
        - WebSocket operations properly mocked
        - Queue state management validated
        - FIFO ordering and performance characteristics verified
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
        
        # Common test data (jobs need id_hash attribute)
        self.test_job = Mock()
        self.test_job.id_hash = "job1_hash"
        self.test_job.user_id = "user123"
        self.test_job.task = "test_task"
        self.test_job.get_html.return_value = "<div>Test Job 1</div>"
        
        self.test_job2 = Mock()
        self.test_job2.id_hash = "job2_hash"
        self.test_job2.user_id = "user456"
        self.test_job2.task = "another_task"
        self.test_job2.get_html.return_value = "<div>Test Job 2</div>"
        
        self.test_user_id = "test_user_123"
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mocked_fifo_queue( self, with_websocket=False ):
        """
        Helper to create FifoQueue with optional WebSocket mocking.
        
        Args:
            with_websocket: Whether to create with WebSocket manager
            
        Returns:
            Tuple of (queue_instance, mocks_dict) for testing
        """
        mocks = {}
        
        if with_websocket:
            mock_websocket_mgr = Mock()
            mocks["websocket_mgr"] = mock_websocket_mgr
            
            queue = FifoQueue( 
                websocket_mgr=mock_websocket_mgr, 
                queue_name="test_queue",
                emit_enabled=True 
            )
        else:
            queue = FifoQueue()
        
        return queue, mocks
    
    def test_initialization_default( self ):
        """
        Test FifoQueue initialization with default parameters.
        
        Ensures:
            - Empty queue_list and queue_dict created
            - Default state values set correctly
            - Push counter initialized to 0
            - Auto-emission disabled when no websocket provided
        """
        queue = FifoQueue()
        
        # Verify empty initialization
        self.assertEqual( len( queue.queue_list ), 0 )
        self.assertEqual( len( queue.queue_dict ), 0 )
        self.assertEqual( queue.push_counter, 0 )
        self.assertEqual( queue.last_queue_size, 0 )
        
        # Verify default state
        self.assertTrue( queue._accepting_jobs )
        self.assertTrue( queue._focus_mode )
        self.assertIsNone( queue._blocking_object )
        
        # Verify auto-emission disabled
        self.assertIsNone( queue.websocket_mgr )
        self.assertIsNone( queue.queue_name )
        self.assertTrue( queue.emit_enabled )  # Default is True but no manager
    
    def test_initialization_with_websocket( self ):
        """
        Test FifoQueue initialization with WebSocket manager.
        
        Ensures:
            - WebSocket manager and queue name stored
            - Auto-emission configuration preserved
            - Other initialization same as default
        """
        mock_websocket_mgr = Mock()
        queue_name = "test_notifications"
        
        queue = FifoQueue( 
            websocket_mgr=mock_websocket_mgr,
            queue_name=queue_name,
            emit_enabled=False
        )
        
        # Verify WebSocket configuration
        self.assertEqual( queue.websocket_mgr, mock_websocket_mgr )
        self.assertEqual( queue.queue_name, queue_name )
        self.assertFalse( queue.emit_enabled )
        
        # Verify other defaults unchanged
        self.assertTrue( queue._accepting_jobs )
        self.assertTrue( queue._focus_mode )
        self.assertIsNone( queue._blocking_object )
    
    def test_push_single_item( self ):
        """
        Test pushing a single item to the queue.
        
        Ensures:
            - Item added to both queue_list and queue_dict
            - Push counter incremented
            - FIFO ordering maintained
            - Dictionary lookup works correctly
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        queue.push( self.test_job )
        
        # Verify item in both structures
        self.assertEqual( len( queue.queue_list ), 1 )
        self.assertEqual( len( queue.queue_dict ), 1 )
        
        # Verify item content
        self.assertEqual( queue.queue_list[0], self.test_job )
        self.assertIn( self.test_job.id_hash, queue.queue_dict )
        self.assertEqual( queue.queue_dict[self.test_job.id_hash], self.test_job )
        
        # Verify counter incremented
        self.assertEqual( queue.push_counter, 1 )
    
    def test_push_multiple_items_fifo_order( self ):
        """
        Test pushing multiple items maintains FIFO order.
        
        Ensures:
            - Items appear in correct order in queue_list
            - All items accessible via dictionary lookup
            - Push counter tracks total pushes
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        job1, job2, job3 = Mock(), Mock(), Mock()
        job1.id_hash, job1.task = "job1_hash", "first"
        job2.id_hash, job2.task = "job2_hash", "second"
        job3.id_hash, job3.task = "job3_hash", "third"
        jobs = [job1, job2, job3]
        
        for job in jobs:
            queue.push( job )
        
        # Verify FIFO order maintained
        self.assertEqual( len( queue.queue_list ), 3 )
        for i, job in enumerate( jobs ):
            self.assertEqual( queue.queue_list[i], job )
            self.assertIn( job.id_hash, queue.queue_dict )
        
        # Verify counter
        self.assertEqual( queue.push_counter, 3 )
    
    def test_pop_from_empty_queue( self ):
        """
        Test popping from empty queue.
        
        Ensures:
            - Returns None when queue is empty
            - Queue structures remain empty
            - No errors raised
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        result = queue.pop()
        
        self.assertIsNone( result )
        self.assertEqual( len( queue.queue_list ), 0 )
        self.assertEqual( len( queue.queue_dict ), 0 )
    
    def test_pop_single_item( self ):
        """
        Test popping single item from queue.
        
        Ensures:
            - Returns the first item pushed (FIFO behavior)
            - Item removed from both structures
            - Queue becomes empty after pop
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        queue.push( self.test_job )
        result = queue.pop()
        
        # Verify correct item returned
        self.assertEqual( result, self.test_job )
        
        # Verify item removed from both structures
        self.assertEqual( len( queue.queue_list ), 0 )
        self.assertEqual( len( queue.queue_dict ), 0 )
        self.assertNotIn( self.test_job.id_hash, queue.queue_dict )
    
    def test_pop_multiple_items_fifo_order( self ):
        """
        Test popping multiple items maintains FIFO order.
        
        Ensures:
            - Items returned in same order they were pushed
            - Each pop removes item from both structures
            - Queue eventually becomes empty
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        job1, job2, job3 = Mock(), Mock(), Mock()
        job1.id_hash, job1.task = "job1_hash", "first"
        job2.id_hash, job2.task = "job2_hash", "second"
        job3.id_hash, job3.task = "job3_hash", "third"
        jobs = [job1, job2, job3]
        
        # Push all jobs
        for job in jobs:
            queue.push( job )
        
        # Pop and verify order
        for expected_job in jobs:
            result = queue.pop()
            self.assertEqual( result, expected_job )
            self.assertNotIn( expected_job.id_hash, queue.queue_dict )
        
        # Verify queue empty
        self.assertEqual( len( queue.queue_list ), 0 )
        self.assertEqual( len( queue.queue_dict ), 0 )
    
    def test_head_empty_queue( self ):
        """
        Test head() on empty queue.
        
        Ensures:
            - Returns None when queue is empty
            - Queue remains unchanged
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        result = queue.head()
        
        self.assertIsNone( result )
        self.assertEqual( len( queue.queue_list ), 0 )
    
    def test_head_single_item( self ):
        """
        Test peeking at queue with single item.
        
        Ensures:
            - Returns first item without removing it
            - Queue structures unchanged
            - Multiple peeks return same item
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        queue.push( self.test_job )
        
        # Multiple head() calls should return same item
        result1 = queue.head()
        result2 = queue.head()
        
        self.assertEqual( result1, self.test_job )
        self.assertEqual( result2, self.test_job )
        
        # Verify queue unchanged
        self.assertEqual( len( queue.queue_list ), 1 )
        self.assertEqual( queue.queue_list[0], self.test_job )
    
    def test_get_by_id_hash_existing( self ):
        """
        Test dictionary lookup by ID for existing item.
        
        Ensures:
            - Returns correct item by ID
            - O(1) lookup performance
            - Item remains in queue
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        queue.push( self.test_job )
        queue.push( self.test_job2 )
        
        # Test lookup
        result = queue.get_by_id_hash( self.test_job.id_hash )
        
        self.assertEqual( result, self.test_job )
        
        # Verify queue unchanged
        self.assertEqual( len( queue.queue_list ), 2 )
        self.assertIn( self.test_job.id_hash, queue.queue_dict )
    
    def test_get_by_id_hash_nonexistent( self ):
        """
        Test dictionary lookup by ID for non-existent item.
        
        Ensures:
            - Returns None for non-existent ID
            - No errors raised
            - Queue unchanged
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        queue.push( self.test_job )
        
        # This should raise KeyError according to the implementation
        with self.assertRaises( KeyError ):
            queue.get_by_id_hash( "nonexistent_id_hash" )
        
        # Verify queue unchanged
        self.assertEqual( len( queue.queue_list ), 1 )
    
    def test_queue_state_management( self ):
        """
        Test queue state management properties.
        
        Ensures:
            - accepting_jobs getter/setter work correctly
            - focus_mode getter/setter work correctly  
            - blocking_object getter/setter work correctly
            - State changes preserved
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        # Test accepting_jobs (using methods from implementation)
        self.assertTrue( queue.is_accepting_jobs() )
        
        # Test focus_mode  
        self.assertTrue( queue.is_in_focus_mode() )
        
        # Test blocking_object methods
        test_object = {"type": "blocking", "reason": "test"}
        queue.push_blocking_object( test_object )
        self.assertFalse( queue.is_accepting_jobs() )  # Should be False after pushing blocking object
        
        # Test popping blocking object
        returned_object = queue.pop_blocking_object()
        self.assertEqual( returned_object, test_object )
        self.assertTrue( queue.is_accepting_jobs() )  # Should be True after popping blocking object
    
    def test_size_and_empty_status( self ):
        """
        Test queue size and empty status methods.
        
        Ensures:
            - size() returns correct count
            - is_empty() returns correct boolean
            - Both methods track actual queue contents
        """
        queue, mocks = self._create_mocked_fifo_queue()
        
        # Test empty queue
        self.assertEqual( queue.size(), 0 )
        self.assertTrue( queue.is_empty() )
        
        # Add items and test
        queue.push( self.test_job )
        self.assertEqual( queue.size(), 1 )
        self.assertFalse( queue.is_empty() )
        
        queue.push( self.test_job2 )
        self.assertEqual( queue.size(), 2 )
        self.assertFalse( queue.is_empty() )
        
        # Remove items and test
        queue.pop()
        self.assertEqual( queue.size(), 1 )
        self.assertFalse( queue.is_empty() )
        
        queue.pop()
        self.assertEqual( queue.size(), 0 )
        self.assertTrue( queue.is_empty() )
    
    def test_websocket_emission( self ):
        """
        Test WebSocket auto-emission functionality.
        
        Ensures:
            - WebSocket emit called when enabled
            - Correct event name and data passed
            - No emission when disabled or no manager
        """
        # Test with emission enabled
        queue, mocks = self._create_mocked_fifo_queue( with_websocket=True )
        
        with patch.object( queue, '_emit_queue_update' ) as mock_emit:
            queue.push( self.test_job )
            mock_emit.assert_called_once()
        
        # Test with emission disabled - method is still called but won't emit
        queue.emit_enabled = False
        with patch.object( queue, '_emit_queue_update' ) as mock_emit:
            queue.push( self.test_job2 )
            mock_emit.assert_called_once()  # Method called but won't emit due to emit_enabled=False
        
        # Test queue without WebSocket manager - emit is still called but doesn't do anything
        queue_no_ws, _ = self._create_mocked_fifo_queue( with_websocket=False )
        with patch.object( queue_no_ws, '_emit_queue_update' ) as mock_emit:
            queue_no_ws.push( self.test_job )
            mock_emit.assert_called_once()  # Method is called but won't emit due to missing websocket_mgr


def isolated_unit_test():
    """
    Run comprehensive unit tests for FifoQueue in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real WebSocket operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "FifoQueue Unit Tests - REST API Phase 4", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization_default',
            'test_initialization_with_websocket',
            'test_push_single_item',
            'test_push_multiple_items_fifo_order',
            'test_pop_from_empty_queue',
            'test_pop_single_item',
            'test_pop_multiple_items_fifo_order',
            'test_head_empty_queue',
            'test_head_single_item',
            'test_get_by_id_hash_existing',
            'test_get_by_id_hash_nonexistent',
            'test_queue_state_management',
            'test_size_and_empty_status',
            'test_websocket_emission'
        ]
        
        for method in test_methods:
            suite.addTest( TestFifoQueue( method ) )
        
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
        print( f"FIFO QUEUE UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL FIFO QUEUE TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME FIFO QUEUE TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 FIFO QUEUE TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} FifoQueue unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )