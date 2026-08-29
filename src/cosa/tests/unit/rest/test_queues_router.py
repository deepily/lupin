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
from fastapi import HTTPException

from cosa.rest.routers.queues import router, push, get_queue, reset_queues
from cosa.rest.routers.queues import get_todo_queue, get_running_queue, get_done_queue, get_dead_queue, get_notification_queue


def _patch_fastapi_main( mock_main ):
    """
    Robustly patch `lupin_app.main` for direct-call unit tests.

    `import lupin_app.main as m` binds m via getattr(sys.modules['lupin_app'],
    'main'), NOT sys.modules['lupin_app.main']. Once the REAL lupin_app
    package is cached by an earlier test, patching only the submodule entry is
    silently ignored (passes in isolation, fails under full-suite ordering).
    Overriding BOTH the package object and the submodule entry makes the import
    resolve to mock_main regardless of prior import state.
    """
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


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

    def _make_mock_job( self, id_hash="job1", user_id="test_user_123" ):
        """
        Build a non-agentic mock job exposing the unified-interface attributes
        the live get_queue handler reads when building *_jobs_metadata for the
        todo/run/done/dead buckets.

        Live contract: get_queue no longer returns HTML strings — it builds a
        structured metadata dict per job from these attributes. isinstance(job,
        AgenticJobBase) is False for a plain Mock, so the agentic-only artifact
        fields collapse to None (exercising the non-agentic branch).

        Returns:
            Mock job with concrete (JSON-serializable) attribute values.
        """
        from cosa.rest.job_state import JobState
        job = Mock()
        job.id_hash               = id_hash
        job.last_question_asked   = "What is 2 + 2?"
        job.answer                = "4"
        job.answer_conversational = "It's 4."
        job.run_date              = "2025-08-05T11:00:00"
        job.created_date          = "2025-08-05T10:00:00"
        job.user_id               = user_id
        job.user_email            = "test@example.com"
        job.session_id            = "happy-elephant"
        job.job_type              = "agent router go to math"
        job.state                 = JobState.COMPLETED
        job.started_at            = None
        job.completed_at          = None
        job.error                 = None
        job.scheduled_at          = None
        job.monopolize            = False
        job.is_cache_hit          = False
        return job


    def test_push_endpoint_is_gone( self ):
        """
        `POST /api/push` retired 2026-08-21 — Rick: ONE entry point, and it is v2.

        This was the happy-path test: it drove `push( request, current_user, todo_queue )`,
        asserted `push_job` was called with the four-argument signature, and pinned the
        `{status: "queued", websocket_id, user_id, job_id, result}` response shape. None
        of that exists now; the handler takes no arguments and raises 410. The queued
        response shape is worth naming as it goes, because it is what every caller of
        this door was written against and `/api/v2/ask` does NOT return it — `ask` answers
        the question synchronously and returns an `AskResponse`, so a caller cutting over
        changes how it reads the result, not just where it posts.
        """
        async def run_test():
            with self.assertRaises( HTTPException ) as ctx:
                await push()
            self.assertEqual( ctx.exception.status_code, 410 )
            self.assertIn( "/api/v2/ask", ctx.exception.detail )
            self.assertIn( "REMOVE BY",   ctx.exception.detail )

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
            # Live contract: get_queue authorizes the filter (regular user, no
            # filter → own jobs), fetches via queue.get_jobs_for_user(uid), and
            # returns structured "<queue>_jobs_metadata" (HTML output retired).
            mock_todo_queue = self._create_mock_queue()
            mock_todo_queue.get_jobs_for_user.return_value = [
                self._make_mock_job( id_hash="job1" ),
                self._make_mock_job( id_hash="job2" )
            ]
            mock_running_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_done_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_dead_queue = self._create_mock_queue( size=0, html_jobs=[] )

            result = await get_queue(
                queue_name="todo",
                current_user=self.test_user,
                user_filter=None,   # direct-call: Query() default is a FieldInfo, not None
                todo_queue=mock_todo_queue,
                running_queue=mock_running_queue,
                done_queue=mock_done_queue,
                dead_queue=mock_dead_queue
            )

            # Regular user, no filter → scoped to own jobs
            mock_todo_queue.get_jobs_for_user.assert_called_once_with( self.test_user["uid"] )

            # Live structured response
            self.assertIn( "todo_jobs_metadata", result )
            metadata = result["todo_jobs_metadata"]
            self.assertEqual( len( metadata ), 2 )
            self.assertEqual( result["filtered_by"], self.test_user["uid"] )
            self.assertEqual( result["total_jobs"], 2 )
            self.assertFalse( result["is_admin_view"] )
            for job_data in metadata:
                self.assertEqual( job_data["user_id"], self.test_user["uid"] )
                self.assertIn( "question_text", job_data )
                self.assertIn( "status", job_data )

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
            # Live contract: run bucket uses ascending order (no reverse) and the
            # same get_jobs_for_user → run_jobs_metadata structured path.
            mock_todo_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_running_queue = self._create_mock_queue()
            mock_running_queue.get_jobs_for_user.return_value = [
                self._make_mock_job( id_hash="run1" ),
                self._make_mock_job( id_hash="run2" )
            ]
            mock_done_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_dead_queue = self._create_mock_queue( size=0, html_jobs=[] )

            result = await get_queue(
                queue_name="run",
                current_user=self.test_user,
                user_filter=None,   # direct-call: Query() default is a FieldInfo, not None
                todo_queue=mock_todo_queue,
                running_queue=mock_running_queue,
                done_queue=mock_done_queue,
                dead_queue=mock_dead_queue
            )

            mock_running_queue.get_jobs_for_user.assert_called_once_with( self.test_user["uid"] )

            self.assertIn( "run_jobs_metadata", result )
            metadata = result["run_jobs_metadata"]
            self.assertEqual( len( metadata ), 2 )
            self.assertEqual( result["filtered_by"], self.test_user["uid"] )
            self.assertEqual( result["total_jobs"], 2 )
            for job_data in metadata:
                self.assertEqual( job_data["user_id"], self.test_user["uid"] )

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
            # Live contract: the done bucket builds rich metadata and bulk-counts
            # notifications via _count_interactions_for_jobs (a DB call) — patched
            # to {} here to keep the test boundary-isolated (zero DB).
            mock_todo_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_running_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_done_queue = self._create_mock_queue()
            mock_done_queue.get_jobs_for_user.return_value = [
                self._make_mock_job( id_hash="done1" ),
                self._make_mock_job( id_hash="done2" )
            ]
            mock_dead_queue = self._create_mock_queue( size=0, html_jobs=[] )

            with patch( 'cosa.rest.routers.queues._count_interactions_for_jobs', return_value={} ) as mock_counts:
                result = await get_queue(
                    queue_name="done",
                    current_user=self.test_user,
                    user_filter=None,
                    todo_queue=mock_todo_queue,
                    running_queue=mock_running_queue,
                    done_queue=mock_done_queue,
                    dead_queue=mock_dead_queue
                )

            mock_done_queue.get_jobs_for_user.assert_called_once_with( self.test_user["uid"] )
            mock_counts.assert_called_once()

            self.assertIn( "done_jobs_metadata", result )
            metadata = result["done_jobs_metadata"]
            self.assertEqual( len( metadata ), 2 )
            self.assertEqual( result["filtered_by"], self.test_user["uid"] )
            self.assertEqual( result["total_jobs"], 2 )
            for job_data in metadata:
                self.assertEqual( job_data["user_id"], self.test_user["uid"] )
                # Non-agentic job → agentic-only artifact fields collapse to None
                self.assertIsNone( job_data["report_path"] )
                self.assertFalse( job_data["has_interactions"] )  # empty counts

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
            # Live contract: the dead bucket mirrors the done bucket — rich
            # metadata + _count_interactions_for_jobs (DB) patched to {}.
            mock_todo_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_running_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_done_queue = self._create_mock_queue( size=0, html_jobs=[] )
            mock_dead_queue = self._create_mock_queue()
            mock_dead_queue.get_jobs_for_user.return_value = [
                self._make_mock_job( id_hash="dead1" ),
                self._make_mock_job( id_hash="dead2" )
            ]

            with patch( 'cosa.rest.routers.queues._count_interactions_for_jobs', return_value={} ) as mock_counts:
                result = await get_queue(
                    queue_name="dead",
                    current_user=self.test_user,
                    user_filter=None,
                    todo_queue=mock_todo_queue,
                    running_queue=mock_running_queue,
                    done_queue=mock_done_queue,
                    dead_queue=mock_dead_queue
                )

            mock_dead_queue.get_jobs_for_user.assert_called_once_with( self.test_user["uid"] )
            mock_counts.assert_called_once()

            self.assertIn( "dead_jobs_metadata", result )
            metadata = result["dead_jobs_metadata"]
            self.assertEqual( len( metadata ), 2 )
            self.assertEqual( result["filtered_by"], self.test_user["uid"] )
            self.assertEqual( result["total_jobs"], 2 )
            for job_data in metadata:
                self.assertEqual( job_data["user_id"], self.test_user["uid"] )
                # Dead bucket surfaces partial artifacts; non-agentic → plan_path None
                self.assertIsNone( job_data["plan_path"] )

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
                    user_filter=None,
                    todo_queue=mock_todo_queue,
                    running_queue=mock_running_queue,
                    done_queue=mock_done_queue,
                    dead_queue=mock_dead_queue
                )
            
            # Verify HTTPException details
            self.assertEqual( context.exception.status_code, 400 )
            self.assertIn( "Invalid queue name: invalid_queue", str( context.exception.detail ) )
        
        asyncio.run( run_test() )
    
    def test_get_queue_cross_user_filter_forbidden( self ):
        """
        Test get_queue rejects a regular user filtering for ANOTHER user's jobs.

        Live contract (queue_auth.authorize_queue_filter, commit 98ab965
        "Production Authentication System"): a non-admin user passing a
        user_filter that is neither None nor their own uid gets HTTP 403. This
        is an INTENTIONAL per-user authorization contract, not a regression —
        it is documented in the authorization matrix in queue_auth.py.

        Ensures:
            - Regular user + cross-user filter → HTTPException 403
            - The queue is never consulted (authorization fails first)
        """
        async def run_test():
            from fastapi import HTTPException

            mock_todo_queue = self._create_mock_queue()
            mock_running_queue = self._create_mock_queue()
            mock_done_queue = self._create_mock_queue()
            mock_dead_queue = self._create_mock_queue()

            with self.assertRaises( HTTPException ) as context:
                await get_queue(
                    queue_name="todo",
                    current_user=self.test_user,          # no "admin" role
                    user_filter="some_other_user_id",     # cross-user request
                    todo_queue=mock_todo_queue,
                    running_queue=mock_running_queue,
                    done_queue=mock_done_queue,
                    dead_queue=mock_dead_queue
                )

            self.assertEqual( context.exception.status_code, 403 )
            self.assertIn( "Cannot access other users' jobs", str( context.exception.detail ) )
            # Authorization fails before any queue read
            mock_todo_queue.get_jobs_for_user.assert_not_called()

        asyncio.run( run_test() )

    def test_get_queue_matching_user_filter_allowed( self ):
        """
        Test get_queue allows a regular user filtering for THEIR OWN uid.

        Live contract: a non-admin passing user_filter == own uid is authorized
        (the matching-user arm of the documented matrix) and is_admin_view is
        True only because user_filter is not None (admin status is still False).

        Ensures:
            - Regular user + own-uid filter → 200 with own jobs
            - get_jobs_for_user called with the user's own uid
        """
        async def run_test():
            mock_todo_queue = self._create_mock_queue()
            mock_todo_queue.get_jobs_for_user.return_value = [ self._make_mock_job() ]
            mock_running_queue = self._create_mock_queue()
            mock_done_queue = self._create_mock_queue()
            mock_dead_queue = self._create_mock_queue()

            result = await get_queue(
                queue_name="todo",
                current_user=self.test_user,
                user_filter=self.test_user["uid"],   # own uid — allowed
                todo_queue=mock_todo_queue,
                running_queue=mock_running_queue,
                done_queue=mock_done_queue,
                dead_queue=mock_dead_queue
            )

            mock_todo_queue.get_jobs_for_user.assert_called_once_with( self.test_user["uid"] )
            self.assertEqual( result["filtered_by"], self.test_user["uid"] )
            # user_filter is not None but user is not admin → is_admin_view False
            self.assertFalse( result["is_admin_view"] )

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
            
            # Live contract: reset_queues stamps cu.get_current_datetime_iso()
            # (cu = cosa.utils.util), not datetime.now().isoformat().
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ), \
                 patch( 'builtins.print' ) as mock_print:

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
            - All dependency functions can import lupin_app.main
            - Dependencies return correct queue attributes
            - Import errors are properly handled
        """
        # Test get_todo_queue dependency
        mock_main = Mock()
        mock_main.jobs_todo_queue = "mock_todo_queue"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_todo_queue(), "mock_todo_queue" )

        # Test get_running_queue dependency
        mock_main = Mock()
        mock_main.jobs_run_queue = "mock_running_queue"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_running_queue(), "mock_running_queue" )

        # Test get_done_queue dependency
        mock_main = Mock()
        mock_main.jobs_done_queue = "mock_done_queue"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_done_queue(), "mock_done_queue" )

        # Test get_dead_queue dependency
        mock_main = Mock()
        mock_main.jobs_dead_queue = "mock_dead_queue"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_dead_queue(), "mock_dead_queue" )

        # Test get_notification_queue dependency
        mock_main = Mock()
        mock_main.jobs_notification_queue = "mock_notification_queue"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_notification_queue(), "mock_notification_queue" )
    
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
            mock_queue.get_jobs_for_user.return_value = [ self._make_mock_job() ]
            mock_queue.push_job.return_value = { "job_id": "h", "message": "ok" }

            # The push endpoint is a 410 tombstone (retired 2026-08-21), so it is
            # awaited for its refusal rather than its result. It stays in this test
            # because "is it async" is still a live question about it — a tombstone
            # defined with `def` instead of `async def` would break the route just as
            # surely as a live handler would.
            with self.assertRaises( HTTPException ):
                await push()

            # Test get_queue endpoint async pattern (structured metadata)
            result = await get_queue(
                queue_name="todo",
                current_user=self.test_user,
                user_filter=None,
                todo_queue=mock_queue,
                running_queue=mock_queue,
                done_queue=mock_queue,
                dead_queue=mock_queue
            )
            self.assertIsInstance( result, dict )

            # Test reset_queues endpoint async pattern
            with patch( 'cosa.utils.util.get_current_datetime_iso', return_value=self.test_timestamp ):
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