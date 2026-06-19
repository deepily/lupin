"""
Unit tests for the test-suite submission router ( cosa.rest.routers.test_suite ).

Covers the single POST endpoint /api/test-suite/submit and its todo-queue
dependency in full isolation:
- get_todo_queue() dependency resolution against lupin_app.main
- submit_test_suite() happy path (queued response + job tracking + push)
- 400 paths (missing uid, missing email)
- 500 paths (factory returns None, queue push raises)
- every optional-field branch (pytest_args, auto_fix_on_failure, env_vars,
  websocket_id fallback, scheduled_at pass-through)

Zero external dependencies: the agentic-job factory, the user job tracker,
and the todo queue are all mocked. No API spend, no real queue, no FastAPI
TestClient — the async endpoint coroutine is driven directly via asyncio.run.
"""

import sys
import types
import asyncio
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

import cosa.rest.routers.test_suite as M
from cosa.rest.routers.test_suite import (
    router,
    get_todo_queue,
    submit_test_suite,
    TestSuiteSubmitRequest,
    TestSuiteSubmitResponse,
)


def _make_job( id_hash="ts-abc12345", last_question_asked="run integration,e2e" ):
    """Build a mock agentic job with the attributes the endpoint touches."""
    job                     = Mock()
    job.id_hash             = id_hash
    job.last_question_asked = last_question_asked
    return job


def _valid_user():
    """A token-shaped user dict with both required fields present."""
    return { "uid": "user-12345678", "email": "tester@example.com" }


class TestGetTodoQueueDependency( unittest.TestCase ):
    """
    Cover get_todo_queue() — it imports lupin_app.main lazily and returns
    its jobs_todo_queue attribute.

    Requires:
        - lupin_app.main importable (real or injected stub)

    Ensures:
        - the module-level jobs_todo_queue is returned unchanged
    """

    def test_get_todo_queue_returns_main_module_queue( self ):
        sentinel_queue            = Mock( name="jobs_todo_queue" )
        fake_main                 = types.ModuleType( "lupin_app.main" )
        fake_main.jobs_todo_queue = sentinel_queue
        fake_pkg                  = types.ModuleType( "lupin_app" )

        with patch.dict( sys.modules, { "lupin_app": fake_pkg, "lupin_app.main": fake_main } ):
            result = get_todo_queue()

        self.assertIs( result, sentinel_queue )


class TestSubmitTestSuiteEndpoint( unittest.TestCase ):
    """
    Comprehensive coverage of the submit_test_suite() coroutine.

    Requires:
        - create_agentic_job and user_job_tracker patched at module scope

    Ensures:
        - happy path returns a queued TestSuiteSubmitResponse
        - validation + failure paths raise the correct HTTPException codes
        - every optional request field branch is exercised
    """

    def setUp( self ):
        self.todo_queue                   = Mock( name="todo_queue" )
        self.todo_queue.size.return_value = 3

    def _run( self, request_body, user=None ):
        """Drive the async endpoint synchronously."""
        if user is None:
            user = _valid_user()
        return asyncio.run(
            submit_test_suite( request_body=request_body, current_user=user, todo_queue=self.todo_queue )
        )

    def _patched( self, job="default", scoped_id="ts-scoped" ):
        """
        Context-manager pair patching the two module-level collaborators.

        Using explicit patch.object (not stacked @patch decorators) keeps each
        test hermetic and immune to decorator arg-injection ordering, which
        otherwise cross-binds the two mocks under pytest run ordering.
        """
        factory_cm = patch.object( M, "create_agentic_job" )
        tracker_cm = patch.object( M, "user_job_tracker" )
        mock_factory = factory_cm.start()
        mock_tracker = tracker_cm.start()
        self.addCleanup( factory_cm.stop )
        self.addCleanup( tracker_cm.stop )
        if job == "default":
            job = _make_job()
        mock_factory.return_value                     = job
        mock_tracker.register_scoped_job.return_value = scoped_id
        return mock_factory, mock_tracker

    def test_router_is_apirouter_with_tag( self ):
        """The module exposes a configured APIRouter (cheap import/structure guard)."""
        self.assertIn( "test-suite", router.tags )

    def test_happy_path_minimal_request( self ):
        mock_factory, _ = self._patched( scoped_id="ts-scoped-01" )

        response = self._run( TestSuiteSubmitRequest() )

        self.assertIsInstance( response, TestSuiteSubmitResponse )
        self.assertEqual( response.status, "queued" )
        self.assertEqual( response.job_id, "ts-scoped-01" )
        self.assertEqual( response.queue_position, 3 )
        self.assertIn( "Test suite job queued", response.message )
        # default websocket fallback → session id derived from uid prefix
        _, kwargs = mock_factory.call_args
        self.assertEqual( kwargs[ "session_id" ], "api-user-123" )
        self.todo_queue.push.assert_called_once()

    def test_all_optional_fields_populate_args_dict( self ):
        mock_factory, _ = self._patched( scoped_id="ts-scoped-02" )

        request = TestSuiteSubmitRequest(
            test_types          = "integration",
            pytest_args         = "-v -k test_auth",
            dry_run             = True,
            websocket_id        = "ws-session-9",
            scheduled_at        = "2026-06-01T03:00:00",
            auto_fix_on_failure = True,
            env_vars            = { "TFE_RESUME_E2E_LIVE": "1" },
        )
        response = self._run( request )

        self.assertEqual( response.status, "queued" )
        _, kwargs = mock_factory.call_args
        args_dict = kwargs[ "args_dict" ]
        self.assertEqual( args_dict[ "pytest_args" ], "-v -k test_auth" )
        self.assertEqual( args_dict[ "auto_fix_on_failure" ], True )
        self.assertEqual( args_dict[ "env_vars" ], { "TFE_RESUME_E2E_LIVE": "1" } )
        # explicit websocket_id wins over the uid fallback
        self.assertEqual( kwargs[ "session_id" ], "ws-session-9" )
        # scheduled_at passed through onto the job
        self.assertEqual( mock_factory.return_value.scheduled_at, "2026-06-01T03:00:00" )

    def test_auto_fix_on_failure_false_is_included( self ):
        # False is not None → the branch must still add the key
        mock_factory, _ = self._patched( scoped_id="ts-scoped-03" )

        self._run( TestSuiteSubmitRequest( auto_fix_on_failure=False ) )

        _, kwargs = mock_factory.call_args
        self.assertEqual( kwargs[ "args_dict" ][ "auto_fix_on_failure" ], False )

    def test_missing_uid_raises_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            self._run( TestSuiteSubmitRequest(), user={ "email": "tester@example.com" } )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "User ID", ctx.exception.detail )

    def test_missing_email_raises_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            self._run( TestSuiteSubmitRequest(), user={ "uid": "user-12345678" } )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "email", ctx.exception.detail )

    def test_factory_returns_none_raises_500( self ):
        self._patched( job=None )
        with self.assertRaises( HTTPException ) as ctx:
            self._run( TestSuiteSubmitRequest() )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "Failed to submit test suite job", ctx.exception.detail )

    def test_queue_push_failure_raises_500( self ):
        self._patched( scoped_id="ts-scoped-04" )
        self.todo_queue.push.side_effect = RuntimeError( "queue down" )

        with self.assertRaises( HTTPException ) as ctx:
            self._run( TestSuiteSubmitRequest() )
        self.assertEqual( ctx.exception.status_code, 500 )
        self.assertIn( "queue down", ctx.exception.detail )


if __name__ == "__main__":
    unittest.main()
