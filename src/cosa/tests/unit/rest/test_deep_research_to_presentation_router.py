"""
Unit tests for the Deep-Research→Presentation router
(`cosa.rest.routers.deep_research_to_presentation`).

Covers:
- `get_todo_queue` — pulls jobs_todo_queue off `lupin_app.main` (dual-key patched).
- `submit_research_to_presentation` — empty-query 400, the debug-print arms (both
  the budget-set and budget-unlimited ternary branches), every args_dict arm
  (budget / target_duration_minutes / theme / audience / audience_context /
  lead_model / dry_run), factory-None 500, and the non-debug all-defaults path.

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

from cosa.rest.routers.deep_research_to_presentation import (
    get_todo_queue,
    submit_research_to_presentation,
    ResearchToPresentationSubmitRequest,
    ResearchToPresentationSubmitResponse,
)


def _patch_fastapi_main( mock_main ):
    """Dual-key patch for `lupin_app.main` (Gotcha 1)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _job( id_hash="init_hash" ):
    """A DeepResearchToPresentationJob stand-in."""
    job = MagicMock()
    job.id_hash = id_hash
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


class TestSubmitResearchToPresentation( unittest.TestCase ):
    """
    Unit tests for `submit_research_to_presentation`.

    Requires:
        - create_agentic_job + user_job_tracker boundary-mocked

    Ensures:
        - empty-query 400, debug arms, args arms, factory-None 500
    """

    def setUp( self ):
        """Ensures: a default authenticated user + mocked queue per test."""
        self.user  = { "uid": "user_1234567890", "email": "u@test.com", "session_id": "sess-1" }
        self.queue = MagicMock()

    def _call( self, body ):
        return asyncio.run( submit_research_to_presentation(
            request = body,
            current_user = self.user,
            todo_queue   = self.queue,
        ) )

    def _patches( self, job, scoped="scoped-hash" ):
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = scoped
        return (
            patch( "cosa.rest.routers.deep_research_to_presentation.create_agentic_job", return_value=job ),
            patch( "cosa.rest.routers.deep_research_to_presentation.user_job_tracker", tracker ),
        )

    def test_empty_query_400( self ):
        """Ensures: a whitespace-only query raises 400 after strip."""
        with self.assertRaises( HTTPException ) as ctx:
            self._call( ResearchToPresentationSubmitRequest( query="   " ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "Query cannot be empty", ctx.exception.detail )

    def test_success_full_debug_budget_set( self ):
        """Ensures: debug + budget-set + every presentation arm thread through."""
        self.user[ "debug" ] = True
        self.queue.size.return_value = 9
        job = _job()
        p_create, p_tracker = self._patches( job, scoped="rx-1" )
        body = ResearchToPresentationSubmitRequest(
            query                   = "  the topic  ",
            budget                  = 2.5,
            target_duration_minutes = 15,
            theme                   = "default",
            audience                = "general",
            audience_context        = "execs",
            lead_model              = "claude-haiku-4-5",
            dry_run                 = True,
        )
        with p_create as m_create, p_tracker:
            result = self._call( body )

        self.assertIsInstance( result, ResearchToPresentationSubmitResponse )
        self.assertEqual( result.job_id, "rx-1" )
        self.assertEqual( result.queue_position, 9 )
        _, kwargs = m_create.call_args
        ad = kwargs[ "args_dict" ]
        self.assertEqual( ad[ "query" ], "the topic" )                    # stripped
        self.assertEqual( ad[ "budget" ], "2.5" )
        self.assertEqual( ad[ "target_duration_minutes" ], "15" )
        self.assertEqual( ad[ "theme" ], "default" )
        self.assertEqual( ad[ "audience" ], "general" )
        self.assertEqual( ad[ "audience_context" ], "execs" )
        self.assertEqual( ad[ "lead_model" ], "claude-haiku-4-5" )
        self.assertTrue( ad[ "dry_run" ] )
        self.queue.push.assert_called_once()

    def test_success_debug_budget_unlimited( self ):
        """Ensures: debug-print 'unlimited' ternary arm (budget None) is exercised."""
        self.user[ "debug" ] = True
        self.queue.size.return_value = 1
        job = _job()
        p_create, p_tracker = self._patches( job )
        body = ResearchToPresentationSubmitRequest( query="topic", budget=None, theme="dark" )
        with p_create as m_create, p_tracker:
            result = self._call( body )

        self.assertEqual( result.queue_position, 1 )
        _, kwargs = m_create.call_args
        self.assertNotIn( "budget", kwargs[ "args_dict" ] )               # budget None → omitted
        self.assertEqual( kwargs[ "args_dict" ][ "theme" ], "dark" )

    def test_success_no_debug_all_defaults( self ):
        """Ensures: debug-off path + all-optional-None arms."""
        self.queue.size.return_value = 2
        job = _job()
        p_create, p_tracker = self._patches( job )
        body = ResearchToPresentationSubmitRequest( query="bare topic" )
        with p_create as m_create, p_tracker:
            result = self._call( body )

        self.assertEqual( result.queue_position, 2 )
        _, kwargs = m_create.call_args
        self.assertEqual( kwargs[ "args_dict" ], { "query": "bare topic" } )

    def test_factory_none_500( self ):
        """Ensures: create_agentic_job None → 500."""
        with patch( "cosa.rest.routers.deep_research_to_presentation.create_agentic_job", return_value=None ), \
             patch( "cosa.rest.routers.deep_research_to_presentation.user_job_tracker", MagicMock() ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( ResearchToPresentationSubmitRequest( query="topic" ) )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Failed to create research-to-presentation job", ctx.exception.detail )


def isolated_unit_test():
    """
    Run the deep-research-to-presentation router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in ( TestGetTodoQueue, TestSubmitResearchToPresentation ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL DR-TO-PRESENTATION ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME DR-TO-PRESENTATION ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str( e )}"
        du.print_banner( f"💥 DR-TO-PRESENTATION ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} DR-to-presentation router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
