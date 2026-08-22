"""
Unit tests for the mock-job router (`cosa.rest.routers.mock_job`).

Covers:
- `get_todo_queue` — pulls jobs_todo_queue off `lupin_app.main` (dual-key patched).
- `submit_mock_job` — bearer extraction (present/absent), expeditor delegation,
  range validation (400s), missing-uid 400, session-id fallback, success (both
  will_fail arms + scheduled_at/monopolize pass-through), and push-failure 500.
- `_handle_expeditor_test` — keyword match + partial-match chain (all 5 elif arms),
  no-match 400, cancelled (args None), dry-run success, factory-failed, and the
  force_failure_mode message/config arms.
- `mock_job_health`.

Zero external dependencies — MockAgenticJob, the expeditor + agent registry,
create_agentic_job, ConfigurationManager, user_job_tracker, asyncio.to_thread, and
uuid are all boundary-mocked. No real jobs, no LLM, no queue. Auth bypassed by
passing current_user explicitly.
"""

import unittest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
import asyncio
import sys
import time

from fastapi import HTTPException

from cosa.rest.routers.mock_job import (
    get_todo_queue,
    submit_mock_job,
    _handle_expeditor_test,
    mock_job_health,
    MockJobSubmitRequest,
    MockJobSubmitResponse,
)


def _patch_fastapi_main( mock_main ):
    """Dual-key patch for `lupin_app.main` (Gotcha 1)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _request( auth=None ):
    """Build a fake Request whose headers honor .get('Authorization', '')."""
    req = MagicMock()
    req.headers = { "Authorization": auth } if auth is not None else {}
    return req


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


def _mock_job( id_hash="init_hash", will_fail=True ):
    """A MockAgenticJob stand-in with the attributes the endpoint reads."""
    job = MagicMock()
    job.id_hash            = id_hash
    job.iterations         = 5
    job.sleep_seconds      = 2.0
    job.will_fail          = will_fail
    job.fail_at_iteration  = 3
    job.last_question_asked = "mock q"
    return job


class TestSubmitMockJob( unittest.TestCase ):
    """
    Unit tests for `submit_mock_job`.

    Requires:
        - MockAgenticJob + user_job_tracker boundary-mocked

    Ensures:
        - bearer extraction, expeditor delegation, validations, success, 500
    """

    def setUp( self ):
        """Ensures: a default authenticated user + mocked queue per test."""
        self.user  = { "uid": "user_1234567890", "email": "u@test.com" }
        self.queue = MagicMock()

    def _call( self, body, request=None ):
        return asyncio.run( submit_mock_job(
            request      = request or _request(),
            request_body = body,
            current_user = self.user,
            todo_queue   = self.queue,
        ) )

    def test_delegates_to_expeditor_with_bearer( self ):
        """Ensures: a voice_command delegates to the expeditor test path with the bearer token."""
        body = MockJobSubmitRequest( voice_command="make a podcast", force_failure_mode="code_bug" )
        with patch( "cosa.rest.routers.mock_job._handle_expeditor_test",
                    new=AsyncMock( return_value="EXP" ) ) as m_exp:
            result = self._call( body, request=_request( "Bearer tok123" ) )
        self.assertEqual( result, "EXP" )
        _, kwargs = m_exp.call_args
        self.assertEqual( kwargs[ "bearer_token" ], "tok123" )
        self.assertEqual( kwargs[ "voice_command" ], "make a podcast" )
        self.assertEqual( kwargs[ "force_failure_mode" ], "code_bug" )

    def test_iterations_range_invalid_400( self ):
        """Ensures: iterations_min > iterations_max raises 400."""
        body = MockJobSubmitRequest( iterations_min=8, iterations_max=3 )
        with self.assertRaises( HTTPException ) as ctx:
            self._call( body )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "iterations_min", ctx.exception.detail )

    def test_sleep_range_invalid_400( self ):
        """Ensures: sleep_min > sleep_max raises 400."""
        body = MockJobSubmitRequest( sleep_min=5.0, sleep_max=1.0 )
        with self.assertRaises( HTTPException ) as ctx:
            self._call( body )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "sleep_min", ctx.exception.detail )

    def test_missing_uid_400( self ):
        """Ensures: a token without uid raises 400."""
        self.user = { "email": "u@test.com" }   # no uid
        body = MockJobSubmitRequest()
        with self.assertRaises( HTTPException ) as ctx:
            self._call( body )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "User ID not found", ctx.exception.detail )

    def test_success_with_websocket_id_and_will_fail( self ):
        """Ensures: success path with provided websocket_id + a failing job."""
        body = MockJobSubmitRequest( websocket_id="ws-abc", failure_probability=1.0 )
        self.queue.size.return_value = 2
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "scoped_hash"
        with patch( "cosa.agents.test_harness.mock_job.MockAgenticJob",
                    return_value=_mock_job( will_fail=True ) ), \
             patch( "cosa.rest.routers.mock_job.user_job_tracker", tracker ):
            result = self._call( body, request=_request() )  # no Authorization → bearer None

        self.assertIsInstance( result, MockJobSubmitResponse )
        self.assertEqual( result.status, "queued" )
        self.assertEqual( result.job_id, "scoped_hash" )
        self.assertEqual( result.queue_position, 2 )
        self.assertEqual( result.config[ "fail_at_iteration" ], 3 )      # will_fail True arm
        self.assertEqual( result.config[ "estimated_duration" ], "10.0s" )
        # session_id used the provided websocket_id
        _, kwargs = tracker.register_scoped_job.call_args
        self.queue.push.assert_called_once()

    def test_success_session_fallback_and_no_fail_and_scheduling( self ):
        """Ensures: websocket_id fallback + non-failing job + scheduled_at/monopolize pass-through."""
        body = MockJobSubmitRequest( scheduled_at="2026-01-01T00:00:00", monopolize=True )
        self.queue.size.return_value = 1
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "scoped2"
        job = _mock_job( will_fail=False )
        with patch( "cosa.agents.test_harness.mock_job.MockAgenticJob", return_value=job ), \
             patch( "cosa.rest.routers.mock_job.user_job_tracker", tracker ):
            result = self._call( body )

        self.assertEqual( result.status, "queued" )
        self.assertIsNone( result.config[ "fail_at_iteration" ] )        # will_fail False arm
        # scheduling attributes were threaded onto the job
        self.assertEqual( job.scheduled_at, "2026-01-01T00:00:00" )
        self.assertTrue( job.monopolize )

    def test_push_failure_raises_500( self ):
        """Ensures: an exception during job push maps to 500."""
        body = MockJobSubmitRequest()
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "h"
        self.queue.push.side_effect = RuntimeError( "queue down" )
        with patch( "cosa.agents.test_harness.mock_job.MockAgenticJob", return_value=_mock_job() ), \
             patch( "cosa.rest.routers.mock_job.user_job_tracker", tracker ):
            with self.assertRaises( HTTPException ) as ctx:
                self._call( body )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Failed to submit mock job", ctx.exception.detail )


class TestHandleExpeditorTest( unittest.TestCase ):
    """
    Unit tests for `_handle_expeditor_test`.

    Requires:
        - JOB_ARG_CONTRACTS, RuntimeArgumentExpeditor, create_agentic_job,
          ConfigurationManager, user_job_tracker, asyncio.to_thread, uuid mocked

    Ensures:
        - keyword + all partial-match arms, no-match 400, cancelled, dry-run
          success, factory-failed, and force_failure_mode arms
    """

    def setUp( self ):
        """Ensures: a default user + queue per test."""
        self.user  = { "uid": "user_1234567890", "email": "u@test.com" }
        self.queue = MagicMock()

    def _run( self, voice_command, agents, to_thread_return, job=None, force_failure_mode=None ):
        """Run _handle_expeditor_test with a controlled environment, return response."""
        expeditor = MagicMock()

        async def _to_thread( _fn, **kwargs ):
            # The endpoint hands its own ExpediteContext down; the notification status
            # comes back on it, not off the shared expeditor (row 10c60712).
            kwargs[ "context" ].notification_status = "no_response"
            return to_thread_return
        tracker = MagicMock()
        tracker.register_scoped_job.side_effect = lambda h, u, s: f"scoped-{h}"
        self.queue.size.return_value = 4

        with patch( "cosa.agents.runtime_argument_expeditor.agent_registry.JOB_ARG_CONTRACTS", agents ), \
             patch( "cosa.agents.runtime_argument_expeditor.expeditor.RuntimeArgumentExpeditor",
                    return_value=expeditor ), \
             patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=MagicMock() ), \
             patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=job ), \
             patch( "cosa.rest.routers.mock_job.user_job_tracker", tracker ), \
             patch( "cosa.rest.routers.mock_job.asyncio.to_thread", new=_to_thread ), \
             patch( "cosa.rest.routers.mock_job.uuid.uuid4",
                    return_value=MagicMock( hex="abcd1234ef99" ) ):
            return asyncio.run( _handle_expeditor_test(
                voice_command      = voice_command,
                current_user       = self.user,
                todo_queue         = self.queue,
                bearer_token       = "tok",
                force_failure_mode = force_failure_mode,
            ) )

    def test_keyword_match_dry_run_success( self ):
        """
        Ensures:
            - An JOB_ARG_CONTRACTS keyword match resolves + queues a dry-run job.
            - A non-matching key listed FIRST exercises the loop-continue arm
              (all(...) False → next iteration) before the match.
        """
        agents = {
            "agent router go to podcast generator": object(),   # keywords not all present → continue
            "agent router go to deep research"    : object(),   # matches → break
        }
        job    = MagicMock(); job.id_hash = "j1"
        result = self._run( "please run a deep research task", agents,
                            to_thread_return={ "foo": "bar", "user_id": "x" }, job=job )
        self.assertEqual( result.status, "queued" )
        self.assertEqual( result.job_id, "j1" )                       # captured before re-scope
        self.assertEqual( result.config[ "command" ], "agent router go to deep research" )
        self.assertTrue( result.config[ "dry_run" ] )
        self.queue.push.assert_called_once()

    def test_partial_match_chain( self ):
        """Ensures: every partial-match elif arm resolves to the right command."""
        job = MagicMock(); job.id_hash = "jx"
        cases = {
            "make a presentation from research" : "agent router go to research to presentation",
            "just make a presentation"          : "agent router go to presentation generator",
            "a podcast about my research"       : "agent router go to research to podcast",
            "just make a podcast"               : "agent router go to podcast generator",
            "go do some research"               : "agent router go to deep research",
        }
        for voice, expected in cases.items():
            result = self._run( voice, agents={}, to_thread_return={ "k": "v" }, job=job )
            self.assertEqual( result.config[ "command" ], expected, f"for {voice!r}" )

    def test_no_match_raises_400( self ):
        """Ensures: a command matching nothing raises 400."""
        with self.assertRaises( HTTPException ) as ctx:
            self._run( "tell me a joke", agents={}, to_thread_return={ "k": "v" } )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "Could not match", ctx.exception.detail )

    def test_cancelled_when_args_none( self ):
        """Ensures: args_dict None → cancelled response with notification status."""
        result = self._run( "go do some research", agents={}, to_thread_return=None )
        self.assertEqual( result.status, "cancelled" )
        self.assertEqual( result.job_id, "expeditor-test-cancelled" )
        self.assertEqual( result.config[ "result" ], "cancelled_or_timeout" )
        self.assertEqual( result.config[ "notification_status" ], "no_response" )

    def test_factory_failed_with_force_failure_mode( self ):
        """Ensures: create_agentic_job None → error status; force_failure_mode threaded."""
        result = self._run( "go do some research", agents={}, to_thread_return={ "k": "v" },
                            job=None, force_failure_mode="rate_limit" )
        self.assertEqual( result.status, "error" )
        self.assertEqual( result.job_id, "factory-failed" )
        self.assertEqual( result.queue_position, 0 )
        self.assertEqual( result.config[ "force_failure_mode" ], "rate_limit" )
        self.assertIn( "force_failure_mode=rate_limit", result.message )
        self.queue.push.assert_not_called()


class TestMockJobHealth( unittest.TestCase ):
    """
    Ensures:
        - health endpoint reports availability
    """

    def test_health_ok( self ):
        """Ensures: health returns status ok / available True."""
        result = asyncio.run( mock_job_health() )
        self.assertEqual( result[ "status" ], "ok" )
        self.assertTrue( result[ "available" ] )


def isolated_unit_test():
    """
    Run the mock-job router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestGetTodoQueue, TestSubmitMockJob, TestHandleExpeditorTest, TestMockJobHealth,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL MOCK-JOB ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME MOCK-JOB ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 MOCK-JOB ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Mock-job router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
