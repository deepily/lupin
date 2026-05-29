"""
Unit tests for queue management router endpoints with comprehensive mocking.

Tests the queue management router endpoints including:
- Queue job pushing with user authentication and WebSocket routing
- Queue retrieval with user filtering (todo, run, done, dead)
- Queue reset operations across all queue types
- Dependency injection for multiple queue instances
- Error handling for invalid queue names and operations
- FastAPI response formats and status codes

Zero external dependencies - all FastAPI operations, queue management,
authentication, and queue operations are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call, AsyncMock
import time
from datetime import datetime
from typing import Dict, Any, List
import asyncio

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.rest.routers.queues import router, push, get_queue, reset_queues
from cosa.rest.routers.queues import get_todo_queue, get_running_queue, get_done_queue, get_dead_queue, get_notification_queue


class TestQueuesRouter( unittest.TestCase ):
    """
    Comprehensive unit tests for queue management router endpoints.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All queue management endpoints tested in isolation
        - FastAPI dependencies properly mocked
        - Queue operations and user filtering validated
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
        self.test_user = {
            "uid": "test_user_123",
            "email": "test@example.com",
            "name": "Test User"
        }
        self.test_websocket_id = "happy-elephant"
        self.test_question = "What is 2 + 2?"
        self.test_timestamp = "2025-08-05T12:00:00.000000"
        
        # Mock queue data
        self.test_html_jobs = [
            "<li id='job1'>Job 1 Content</li>",
            "<li id='job2'>Job 2 Content</li>",
            "<li id='job3'>Job 3 Content</li>"
        ]
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mock_queue( self, size=3, html_jobs=None ):
        """
        Helper to create mock queue with standard methods.
        
        Args:
            size: Queue size to return
            html_jobs: HTML job list to return
            
        Returns:
            Mock queue object with expected methods
        """
        if html_jobs is None:
            html_jobs = self.test_html_jobs
            
        mock_queue = Mock()
        mock_queue.size.return_value = size
        mock_queue.get_html_list.return_value = html_jobs
        mock_queue.push_job.return_value = { "id_hash": "generated_hash", "status": "queued" }
        mock_queue.clear.return_value = None
        
        return mock_queue
    
    def test_push_endpoint_success( self ):
        """
        Test queue job push endpoint success case.
        
        Ensures:
            - Question added to todo queue with proper metadata
            - WebSocket ID and user ID properly associated
            - Returns status confirmation with routing info
            - Logs push operation for debugging
        """
        async def run_test():
            mock_todo_queue = self._create_mock_queue()
            
            with patch( 'builtins.print' ) as mock_print:
                result = await push( 
                    question=self.test_question,
                    websocket_id=self.test_websocket_id,
                    current_user=self.test_user,
                    todo_queue=mock_todo_queue
                )
                
                # Verify queue push called with correct parameters
                mock_todo_queue.push_job.assert_called_once_with( 
                    self.test_question, 
                    self.test_websocket_id, 
                    self.test_user["uid"] 
                )
                
                # Verify logging
                expected_log = f"[API] /api/push called - question: '{self.test_question}', websocket_id: {self.test_websocket_id}, user_id: {self.test_user['uid']}"
                mock_print.assert_called_once_with( expected_log )
                
                # Verify response format
                self.assertEqual( result["status"], "queued" )
                self.assertEqual( result["websocket_id"], self.test_websocket_id )
                self.assertEqual( result["user_id"], self.test_user["uid"] )
                self.assertIn( "result", result )
                self.assertEqual( result["result"]["id_hash"], "generated_hash" )
        
        asyncio.run( run_test() )
    
    def test_get_queue_todo_endpoint( self ):
        """
        Test get queue endpoint for todo queue.
        
        Ensures:
            - Retrieves todo queue with user filtering
            - Applies descending sort order for todo queue
            - Returns jobs with user context added
            - Response format matches expected structure
        """
        async def run_test():
            mock_todo_queue = self._create_mock_queue()
            mock_running_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_done_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_dead_queue = self._create_mock_queue( size=0, html_jobs=[] )
            
            result = await get_queue(
                queue_name="todo",
                current_user=self.test_user,
                todo_queue=mock_todo_queue,
                running_queue=mock_running_queue,
                done_queue=mock_done_queue,
                dead_queue=mock_dead_queue
            )
            
            # Verify todo queue called with descending order
            mock_todo_queue.get_html_list.assert_called_once_with( descending=True )
            
            # Verify response structure
            self.assertIn( "todo_jobs", result )
            todo_jobs = result["todo_jobs"]
            
            # Verify user context added to jobs
            for job in todo_jobs:
                self.assertIn( f"[user: {self.test_user['uid']}]", job )
            
            # Verify job count matches
            self.assertEqual( len( todo_jobs ), len( self.test_html_jobs ) )
        
        asyncio.run( run_test() )
    
    def test_get_queue_running_endpoint( self ):
        """
        Test get queue endpoint for running queue.
        
        Ensures:
            - Retrieves running queue with user filtering
            - Uses default (ascending) sort order for run queue
            - Returns jobs with user context added
            - Response format matches expected structure
        """
        async def run_test():
            mock_todo_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_running_queue = self._create_mock_queue()
            mock_done_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_dead_queue = self._create_mock_queue( size=0, html_jobs=[] )
            
            result = await get_queue(
                queue_name="run",
                current_user=self.test_user,
                todo_queue=mock_todo_queue,
                running_queue=mock_running_queue,
                done_queue=mock_done_queue,
                dead_queue=mock_dead_queue
            )
            
            # Verify running queue called without descending (default ascending)
            mock_running_queue.get_html_list.assert_called_once_with()
            
            # Verify response structure
            self.assertIn( "run_jobs", result )
            run_jobs = result["run_jobs"]
            
            # Verify user context added to jobs
            for job in run_jobs:
                self.assertIn( f"[user: {self.test_user['uid']}]", job )
            
            # Verify job count matches
            self.assertEqual( len( run_jobs ), len( self.test_html_jobs ) )
        
        asyncio.run( run_test() )
    
    def test_get_queue_done_endpoint( self ):
        """
        Test get queue endpoint for done queue.
        
        Ensures:
            - Retrieves done queue with user filtering
            - Applies descending sort order for done queue
            - Returns jobs with user context added
            - Response format matches expected structure
        """
        async def run_test():
            mock_todo_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_running_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_done_queue = self._create_mock_queue()
            mock_dead_queue = self._create_mock_queue( size=0, html_jobs=[] )
            
            result = await get_queue(
                queue_name="done",
                current_user=self.test_user,
                todo_queue=mock_todo_queue,
                running_queue=mock_running_queue,
                done_queue=mock_done_queue,
                dead_queue=mock_dead_queue
            )
            
            # Verify done queue called with descending order
            mock_done_queue.get_html_list.assert_called_once_with( descending=True )
            
            # Verify response structure
            self.assertIn( "done_jobs", result )
            done_jobs = result["done_jobs"]
            
            # Verify user context added to jobs
            for job in done_jobs:
                self.assertIn( f"[user: {self.test_user['uid']}]", job )
            
            # Verify job count matches
            self.assertEqual( len( done_jobs ), len( self.test_html_jobs ) )
        
        asyncio.run( run_test() )
    
    def test_get_queue_dead_endpoint( self ):
        """
        Test get queue endpoint for dead queue.
        
        Ensures:
            - Retrieves dead queue with user filtering
            - Applies descending sort order for dead queue
            - Returns jobs with user context added
            - Response format matches expected structure
        """
        async def run_test():
            mock_todo_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_running_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_done_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_dead_queue = self._create_mock_queue()
            
            result = await get_queue(
                queue_name="dead",
                current_user=self.test_user,
                todo_queue=mock_todo_queue,
                running_queue=mock_running_queue,
                done_queue=mock_done_queue,
                dead_queue=mock_dead_queue
            )
            
            # Verify dead queue called with descending order
            mock_dead_queue.get_html_list.assert_called_once_with( descending=True )
            
            # Verify response structure
            self.assertIn( "dead_jobs", result )
            dead_jobs = result["dead_jobs"]
            
            # Verify user context added to jobs
            for job in dead_jobs:
                self.assertIn( f"[user: {self.test_user['uid']}]", job )
            
            # Verify job count matches
            self.assertEqual( len( dead_jobs ), len( self.test_html_jobs ) )
        
        asyncio.run( run_test() )
    
    def test_get_queue_invalid_name( self ):
        """
        Test get queue endpoint with invalid queue name.
        
        Ensures:
            - Raises HTTPException for invalid queue names
            - Returns 400 status code
            - Includes descriptive error message
        """
        async def run_test():
            from fastapi import HTTPException
            
            mock_todo_queue = self._create_mock_queue()
            mock_running_queue = self._create_mock_queue()
            mock_done_queue = self._create_mock_queue()
            mock_dead_queue = self._create_mock_queue()
            
            with self.assertRaises( HTTPException ) as context:
                await get_queue(
                    queue_name="invalid_queue",
                    current_user=self.test_user,
                    todo_queue=mock_todo_queue,
                    running_queue=mock_running_queue,
                    done_queue=mock_done_queue,
                    dead_queue=mock_dead_queue
                )
            
            # Verify HTTPException details
            self.assertEqual( context.exception.status_code, 400 )
            self.assertIn( "Invalid queue name: invalid_queue", str( context.exception.detail ) )
        
        asyncio.run( run_test() )
    
    def test_reset_queues_success( self ):
        """
        Test queue reset endpoint success case.
        
        Ensures:
            - All queues are cleared
            - Initial counts captured for reporting
            - Returns comprehensive reset summary
            - Logs reset operation
        """
        async def run_test():
            # Create mock queues with different sizes
            mock_todo_queue = self._create_mock_queue( size=5 )
            mock_running_queue = self._create_mock_queue( size=2 )
            mock_done_queue = self._create_mock_queue( size=10 )
            mock_dead_queue = self._create_mock_queue( size=1 )
            mock_notification_queue = self._create_mock_queue( size=3 )
            
            with patch( 'cosa.rest.routers.queues.datetime' ) as mock_datetime, \
                 patch( 'builtins.print' ) as mock_print:
                
                mock_now = Mock()
                mock_now.isoformat.return_value = self.test_timestamp
                mock_datetime.now.return_value = mock_now
                
                result = await reset_queues(
                    current_user=self.test_user,
                    todo_queue=mock_todo_queue,
                    running_queue=mock_running_queue,
                    done_queue=mock_done_queue,
                    dead_queue=mock_dead_queue,
                    notification_queue=mock_notification_queue
                )
                
                # Verify all queues had their size checked
                mock_todo_queue.size.assert_called_once()
                mock_running_queue.size.assert_called_once()
                mock_done_queue.size.assert_called_once()
                mock_dead_queue.size.assert_called_once()
                mock_notification_queue.size.assert_called_once()
                
                # Verify all queues were cleared
                mock_todo_queue.clear.assert_called_once()
                mock_running_queue.clear.assert_called_once()
                mock_done_queue.clear.assert_called_once()
                mock_dead_queue.clear.assert_called_once()
                mock_notification_queue.clear.assert_called_once()
                
                # Verify response structure
                self.assertEqual( result["status"], "success" )
                self.assertEqual( result["message"], "All queues have been reset" )
                self.assertEqual( result["user_id"], self.test_user["uid"] )
                self.assertEqual( result["timestamp"], self.test_timestamp )
                self.assertEqual( result["total_items_cleared"], 21 )  # 5+2+10+1+3
                
                # Verify queue reset details
                queues_reset = result["queues_reset"]
                self.assertEqual( queues_reset["todo"], "cleared 5 items" )
                self.assertEqual( queues_reset["run"], "cleared 2 items" )
                self.assertEqual( queues_reset["done"], "cleared 10 items" )
                self.assertEqual( queues_reset["dead"], "cleared 1 items" )
                self.assertEqual( queues_reset["notification"], "cleared 3 items" )
                
                # Verify logging calls
                self.assertEqual( mock_print.call_count, 2 )
                mock_print.assert_any_call( f"[API] /api/reset-queues called by user: {self.test_user['uid']}" )
                mock_print.assert_any_call( "[API] Successfully reset all queues - cleared 21 total items" )
        
        asyncio.run( run_test() )
    
    def test_reset_queues_error_handling( self ):
        """
        Test queue reset endpoint error handling.
        
        Ensures:
            - Catches exceptions during queue clearing
            - Returns HTTPException with 500 status
            - Includes error details in response
            - Logs error for debugging
        """
        async def run_test():
            from fastapi import HTTPException
            
            # Create mock queues with one that raises exception
            mock_todo_queue = self._create_mock_queue()
            mock_running_queue = self._create_mock_queue()
            mock_done_queue = Mock()
            mock_done_queue.size.return_value = 5
            mock_done_queue.clear.side_effect = Exception( "Queue clearing failed" )
            mock_dead_queue = self._create_mock_queue()
            mock_notification_queue = self._create_mock_queue()
            
            with patch( 'builtins.print' ) as mock_print:
                with self.assertRaises( HTTPException ) as context:
                    await reset_queues(
                        current_user=self.test_user,
                        todo_queue=mock_todo_queue,
                        running_queue=mock_running_queue,
                        done_queue=mock_done_queue,
                        dead_queue=mock_dead_queue,
                        notification_queue=mock_notification_queue
                    )
                
                # Verify HTTPException details
                self.assertEqual( context.exception.status_code, 500 )
                self.assertIn( "Failed to reset queues: Queue clearing failed", str( context.exception.detail ) )
                
                # Verify error logging
                mock_print.assert_any_call( "[ERROR] Failed to reset queues: Queue clearing failed" )
        
        asyncio.run( run_test() )
    
    def test_dependency_functions( self ):
        """
        Test queue dependency functions for proper module imports.
        
        Ensures:
            - All dependency functions can import fastapi_app.main
            - Dependencies return correct queue attributes
            - Import errors are properly handled
        """
        # Test get_todo_queue dependency
        with patch.dict( 'sys.modules', { 'fastapi_app.main': Mock() } ) as mock_modules:
            mock_main = mock_modules['fastapi_app.main']
            mock_main.jobs_todo_queue = "mock_todo_queue"
            
            result = get_todo_queue()
            self.assertEqual( result, "mock_todo_queue" )
        
        # Test get_running_queue dependency
        with patch.dict( 'sys.modules', { 'fastapi_app.main': Mock() } ) as mock_modules:
            mock_main = mock_modules['fastapi_app.main']
            mock_main.jobs_run_queue = "mock_running_queue"
            
            result = get_running_queue()
            self.assertEqual( result, "mock_running_queue" )
        
        # Test get_done_queue dependency
        with patch.dict( 'sys.modules', { 'fastapi_app.main': Mock() } ) as mock_modules:
            mock_main = mock_modules['fastapi_app.main']
            mock_main.jobs_done_queue = "mock_done_queue"
            
            result = get_done_queue()
            self.assertEqual( result, "mock_done_queue" )
        
        # Test get_dead_queue dependency
        with patch.dict( 'sys.modules', { 'fastapi_app.main': Mock() } ) as mock_modules:
            mock_main = mock_modules['fastapi_app.main']
            mock_main.jobs_dead_queue = "mock_dead_queue"
            
            result = get_dead_queue()
            self.assertEqual( result, "mock_dead_queue" )
        
        # Test get_notification_queue dependency
        with patch.dict( 'sys.modules', { 'fastapi_app.main': Mock() } ) as mock_modules:
            mock_main = mock_modules['fastapi_app.main']
            mock_main.jobs_notification_queue = "mock_notification_queue"
            
            result = get_notification_queue()
            self.assertEqual( result, "mock_notification_queue" )
    
    def test_router_configuration( self ):
        """
        Test router configuration and metadata.
        
        Ensures:
            - Router has correct prefix and tags
            - Router is properly configured for FastAPI
            - Router object is accessible for app integration
        """
        # Verify router is configured
        self.assertIsNotNone( router )
        
        # Verify router has correct prefix and tags
        self.assertEqual( router.prefix, "/api" )
        self.assertIn( "queues", router.tags )
        
        # Verify router is an APIRouter instance
        from fastapi import APIRouter
        self.assertIsInstance( router, APIRouter )
    
    def test_async_endpoint_patterns( self ):
        """
        Test async endpoint patterns for FastAPI compatibility.
        
        Ensures:
            - All endpoints are properly defined as async
            - Endpoints can be called in async context
            - Return values are dictionaries suitable for JSON serialization
        """
        async def run_test():
            mock_queue = self._create_mock_queue()
            
            # Test push endpoint async pattern
            result = await push(
                question=self.test_question,
                websocket_id=self.test_websocket_id,
                current_user=self.test_user,
                todo_queue=mock_queue
            )
            self.assertIsInstance( result, dict )
            
            # Test get_queue endpoint async pattern
            result = await get_queue(
                queue_name="todo",
                current_user=self.test_user,
                todo_queue=mock_queue,
                running_queue=mock_queue,
                done_queue=mock_queue,
                dead_queue=mock_queue
            )
            self.assertIsInstance( result, dict )
            
            # Test reset_queues endpoint async pattern
            with patch( 'cosa.rest.routers.queues.datetime' ) as mock_datetime:
                mock_now = Mock()
                mock_now.isoformat.return_value = self.test_timestamp
                mock_datetime.now.return_value = mock_now
                
                result = await reset_queues(
                    current_user=self.test_user,
                    todo_queue=mock_queue,
                    running_queue=mock_queue,
                    done_queue=mock_queue,
                    dead_queue=mock_queue,
                    notification_queue=mock_queue
                )
                self.assertIsInstance( result, dict )
            
            # All return values should be JSON serializable
            import json
            for endpoint_result in [result]:
                json.dumps( endpoint_result )  # Should not raise exception
        
        asyncio.run( run_test() )


def isolated_unit_test():
    """
    Run comprehensive unit tests for queue management router in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real FastAPI or queue operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "Queue Management Router Unit Tests - REST API Phase 4", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_push_endpoint_success',
            'test_get_queue_todo_endpoint',
            'test_get_queue_running_endpoint',
            'test_get_queue_done_endpoint',
            'test_get_queue_dead_endpoint',
            'test_get_queue_invalid_name',
            'test_reset_queues_success',
            'test_reset_queues_error_handling',
            'test_dependency_functions',
            'test_router_configuration',
            'test_async_endpoint_patterns'
        ]
        
        for method in test_methods:
            suite.addTest( TestQueuesRouter( method ) )
        
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
        print( f"QUEUE MANAGEMENT ROUTER UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL QUEUE MANAGEMENT ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME QUEUE MANAGEMENT ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 QUEUE MANAGEMENT ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Queue management router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )