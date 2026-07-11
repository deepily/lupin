"""
Unit tests for the SWE Team router (`cosa.rest.routers.swe_team`).

Covers:
- `get_todo_queue` — pulls jobs_todo_queue off `lupin_app.main` (dual-key patched).
- `submit_swe_team_task` — missing-uid 400, missing-email 400, session-id fallback,
  success (minimal + every optional arm: dry_run / lead_model / worker_model /
  budget / timeout / trust_mode / scheduled_at / monopolize / provided websocket_id),
  factory-None 500 (re-raised through `except HTTPException`), and push-failure 500.

Zero external dependencies — create_agentic_job, user_job_tracker, and the todo
queue are all boundary-mocked. No real jobs, no LLM, no queue, no network. Auth is
bypassed by passing current_user explicitly.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import asyncio
import sys
import time

from fastapi import HTTPException

from cosa.rest.routers.swe_team import (
    get_todo_queue,
    submit_swe_team_task,
    SweTeamSubmitRequest,
    SweTeamSubmitResponse,
)


def _patch_fastapi_main( mock_main ):
    """Dual-key patch for `lupin_app.main` (Gotcha 1)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _job( id_hash="init_hash", last_q="ship the feature" ):
    """A SweTeamJob stand-in with the attributes the endpoint reads."""
    job = MagicMock()
    job.id_hash             = id_hash
    job.last_question_asked = last_q
    return job


class TestGetTodoQueue( unittest.TestCase ):
    """
    Ensures:
        - get_todo_queue returns main_module.jobs_todo_queue
    """

    def test_returns_main_module_todo_queue( self ):
        """Ensures: dependency reads jobs_todo_queue off lupin_app.main."""
        mock_main = MagicMock()
        mock_main.jobs_todo_queue = "Q"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_todo_queue(), "Q" )


class TestSubmitSweTeamTask( unittest.TestCase ):
    """
    Unit tests for `submit_swe_team_task`.

    Requires:
        - create_agentic_job + user_job_tracker boundary-mocked

    Ensures:
        - validations (400s), session fallback, success arms, factory-None 500,
          push-failure 500
    """

    def setUp( self ):
        """Ensures: a default authenticated user + mocked queue per test."""
        self.user  = { "uid": "user_1234567890", "email": "u@test.com" }
        self.queue = MagicMock()

    def _call( self, body ):
        return asyncio.run( submit_swe_team_task(
            request_body = body,
            current_user = self.user,
            todo_queue   = self.queue,
        ) )

    def test_missing_uid_400( self ):
        """Ensures: a token without uid raises 400."""
        self.user = { "email": "u@test.com" }
        with self.assertRaises( HTTPException ) as ctx:
            self._call( SweTeamSubmitRequest( task="do the thing" ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "User ID not found", ctx.exception.detail )

    def test_missing_email_400( self ):
        """Ensures: a token without email raises 400."""
        self.user = { "uid": "user_1234567890" }
        with self.assertRaises( HTTPException ) as ctx:
            self._call( SweTeamSubmitRequest( task="do the thing" ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "User email not found", ctx.exception.detail )

    def test_success_minimal_session_fallback( self ):
        """Ensures: minimal body queues a job; websocket_id None → api-<uid8> session fallback."""
        self.queue.size.return_value = 4
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "swe-scoped"
        with patch( "cosa.rest.routers.swe_team.create_agentic_job",
                    return_value=_job() ) as m_create, \
             patch( "cosa.rest.routers.swe_team.user_job_tracker", tracker ):
            result = self._call( SweTeamSubmitRequest( task="build a parser" ) )

        self.assertIsInstance( result, SweTeamSubmitResponse )
        self.assertEqual( result.status, "queued" )
        self.assertEqual( result.job_id, "swe-scoped" )
        self.assertEqual( result.queue_position, 4 )
        self.assertIn( "SWE Team job queued", result.message )
        _, kwargs = m_create.call_args
        self.assertEqual( kwargs[ "session_id" ], "api-user_123" )
        self.assertEqual( kwargs[ "args_dict" ], { "task": "build a parser" } )
        self.queue.push.assert_called_once()

    def test_success_all_optional_arms( self ):
        """Ensures: dry_run + lead/worker model + budget + timeout + trust_mode + websocket_id + scheduling thread through."""
        self.queue.size.return_value = 8
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "swe-2"
        job = _job()
        body = SweTeamSubmitRequest(
            task         = "refactor module",
            dry_run      = True,
            websocket_id = "ws-abc",
            lead_model   = "claude-opus-4-8",
            worker_model = "claude-sonnet-4-6",
            budget       = 5.0,
            timeout      = 30,
            trust_mode   = "active",
            scheduled_at = "2026-01-01T00:00:00",
            monopolize   = True,
        )
        with patch( "cosa.rest.routers.swe_team.create_agentic_job",
                    return_value=job ) as m_create, \
             patch( "cosa.rest.routers.swe_team.user_job_tracker", tracker ):
            result = self._call( body )

        self.assertEqual( result.status, "queued" )
        self.assertEqual( result.job_id, "swe-2" )
        _, kwargs = m_create.call_args
        ad = kwargs[ "args_dict" ]
        self.assertEqual( kwargs[ "session_id" ], "ws-abc" )              # provided websocket_id used
        self.assertTrue( ad[ "dry_run" ] )
        self.assertEqual( ad[ "lead_model" ], "claude-opus-4-8" )
        self.assertEqual( ad[ "worker_model" ], "claude-sonnet-4-6" )
        self.assertEqual( ad[ "budget" ], "5.0" )
        self.assertEqual( ad[ "timeout" ], "30" )
        self.assertEqual( ad[ "trust_mode" ], "active" )
        self.assertEqual( job.scheduled_at, "2026-01-01T00:00:00" )
        self.assertTrue( job.monopolize )

    def test_parent_id_hash_stamps_lineage( self ):
        """bug 3a14292b: parent_id_hash threads onto job.spawned_by_id_hash so the
        consumer's Gate B admits this child through the monopoly intake hold."""
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "swe-lin"
        job = _job()
        with patch( "cosa.rest.routers.swe_team.create_agentic_job", return_value=job ), \
             patch( "cosa.rest.routers.swe_team.user_job_tracker", tracker ):
            self._call( SweTeamSubmitRequest( task="child task", parent_id_hash="ts-parent" ) )
        self.assertEqual( job.spawned_by_id_hash, "ts-parent" )

    def test_factory_none_500( self ):
        """Ensures: create_agentic_job None → 500 (re-raised cleanly through except HTTPException)."""
        with patch( "cosa.rest.routers.swe_team.create_agentic_job", return_value=None ), \
             patch( "cosa.rest.routers.swe_team.user_job_tracker", MagicMock() ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( SweTeamSubmitRequest( task="t" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Failed to create SWE Team job", ctx.exception.detail )
        self.queue.push.assert_not_called()

    def test_push_failure_500( self ):
        """Ensures: an exception during job push maps to 500 via the generic except."""
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "h"
        self.queue.push.side_effect = RuntimeError( "queue down" )
        with patch( "cosa.rest.routers.swe_team.create_agentic_job", return_value=_job() ), \
             patch( "cosa.rest.routers.swe_team.user_job_tracker", tracker ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( SweTeamSubmitRequest( task="t" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Failed to submit SWE Team job", ctx.exception.detail )


def isolated_unit_test():
    """
    Run the SWE Team router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in ( TestGetTodoQueue, TestSubmitSweTeamTask ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL SWE-TEAM ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME SWE-TEAM ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str( e )}"
        du.print_banner( f"💥 SWE-TEAM ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} SWE-Team router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
