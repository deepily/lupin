"""
Unit tests for the Claude Code queue submission router
(`cosa.rest.routers.claude_code_queue`).

Covers:
- Pydantic models `ClaudeCodeQueueRequest` / `ClaudeCodeQueueResponse`
  (defaults + explicit values).
- DI accessors `get_todo_queue` (dual-key `lupin_app.main` patch) and
  `get_user_job_tracker`.
- `submit_claude_code_to_queue` endpoint — canonical + deprecated-alias paths,
  missing-uid / missing-email / invalid-task_type 400s, websocket_id default
  fallback, scheduled_at + monopolize pass-through arcs, success response, and
  the factory-failure 500.

Boundary-mocked — `create_agentic_job`, the todo queue, and the user-job tracker
are all faked. No real queue push, no real Claude Code / SDK invocation, ZERO
LLM/API spend. Auth bypassed by passing `current_user` directly.

Run via `run-sdk-cov.sh` (the module imports `agentic_job_factory` which
transitively pulls in `claude_agent_sdk`).
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

import cosa.rest.routers.claude_code_queue as ccq
from cosa.rest.routers.claude_code_queue import (
    ClaudeCodeQueueRequest,
    ClaudeCodeQueueResponse,
    get_todo_queue,
    get_user_job_tracker,
    submit_claude_code_to_queue,
)

from fastapi import HTTPException

P = "cosa.rest.routers.claude_code_queue"


def _patch_fastapi_main( mock_main ):
    pkg = MagicMock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


# ── Pydantic models ─────────────────────────────────────────────────────────────


class TestModels( unittest.TestCase ):

    def test_request_defaults( self ):
        req = ClaudeCodeQueueRequest( prompt="do it" )
        self.assertEqual( req.project, "lupin" )
        self.assertEqual( req.task_type, "BOUNDED" )
        self.assertEqual( req.max_turns, 50 )
        self.assertFalse( req.dry_run )
        self.assertIsNone( req.websocket_id )
        self.assertIsNone( req.scheduled_at )
        self.assertFalse( req.monopolize )

    def test_request_explicit( self ):
        req = ClaudeCodeQueueRequest(
            prompt="x", project="cosa", task_type="INTERACTIVE", max_turns=200,
            websocket_id="ws1", dry_run=True, scheduled_at="2026-03-31T02:00:00",
            monopolize=True,
        )
        self.assertEqual( req.project, "cosa" )
        self.assertEqual( req.task_type, "INTERACTIVE" )
        self.assertTrue( req.monopolize )

    def test_response( self ):
        resp = ClaudeCodeQueueResponse( status="queued", job_id="cc-a1b2c3d4", queue_position=3, message="ok" )
        self.assertEqual( resp.job_id, "cc-a1b2c3d4" )
        self.assertEqual( resp.queue_position, 3 )


# ── DI accessors ────────────────────────────────────────────────────────────────


class TestDependencyAccessors( unittest.TestCase ):

    def test_get_todo_queue( self ):
        m = MagicMock(); m.jobs_todo_queue = "TODOQ"
        with _patch_fastapi_main( m ):
            self.assertEqual( get_todo_queue(), "TODOQ" )

    def test_get_user_job_tracker( self ):
        sentinel = object()
        with patch( "cosa.rest.queue_extensions.user_job_tracker", sentinel ):
            self.assertIs( get_user_job_tracker(), sentinel )


# ── submit_claude_code_to_queue ─────────────────────────────────────────────────


class TestSubmitClaudeCodeToQueue( unittest.IsolatedAsyncioTestCase ):

    def _request( self, path="/api/claude-code/submit" ):
        req = MagicMock()
        req.url.path = path
        return req

    def _job( self ):
        job = MagicMock()
        job.id_hash = "cc-deadbeef"
        job.last_question_asked = "Run the tests"
        return job

    def _deps( self, *, job=None ):
        todo_queue = MagicMock()
        todo_queue.size.return_value = 2
        tracker = MagicMock()
        tracker.register_scoped_job.return_value = "cc-scoped01"
        factory = MagicMock( return_value=job or self._job() )
        return todo_queue, tracker, factory

    async def _call( self, body, *, path="/api/claude-code/submit",
                     current_user=None, todo_queue=None, tracker=None, factory=None ):
        current_user = current_user if current_user is not None else { "uid": "user-12345678", "email": "a@b.com" }
        tq, trk, fac = self._deps()
        todo_queue = todo_queue or tq
        tracker    = tracker or trk
        factory    = factory or fac
        with patch( f"{P}.create_agentic_job", factory ):
            return await submit_claude_code_to_queue(
                request_body=body, request=self._request( path ),
                current_user=current_user, todo_queue=todo_queue, user_job_tracker=tracker,
            ), factory, todo_queue, tracker

    async def test_success_canonical_with_schedule_and_monopolize( self ):
        body = ClaudeCodeQueueRequest(
            prompt="p", websocket_id="ws-1", scheduled_at="2026-03-31T02:00:00", monopolize=True,
        )
        job = self._job()
        resp, factory, tq, trk = await self._call( body, factory=MagicMock( return_value=job ) )
        self.assertEqual( resp.status, "queued" )
        self.assertEqual( resp.job_id, "cc-scoped01" )
        self.assertEqual( resp.queue_position, 2 )
        # scheduled_at + monopolize were passed through onto the job.
        self.assertEqual( job.scheduled_at, "2026-03-31T02:00:00" )
        self.assertTrue( job.monopolize )
        # factory got the canonical session_id from websocket_id.
        _, kwargs = factory.call_args
        self.assertEqual( kwargs[ "session_id" ], "ws-1" )
        tq.push.assert_called_once_with( job )

    async def test_success_alias_path_defaults_session_id( self ):
        # Deprecated alias path (prints deprecation), no websocket_id → default
        # session id derived from uid, no scheduled_at / monopolize.
        body = ClaudeCodeQueueRequest( prompt="p" )
        job  = self._job()
        resp, factory, tq, trk = await self._call(
            body, path="/api/claude-code/queue/submit", factory=MagicMock( return_value=job ),
        )
        self.assertEqual( resp.status, "queued" )
        _, kwargs = factory.call_args
        self.assertEqual( kwargs[ "session_id" ], "api-user-123" )  # api-{uid[:8]}

    async def test_missing_uid_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( ClaudeCodeQueueRequest( prompt="p" ), current_user={ "email": "a@b.com" } )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_missing_email_400( self ):
        with self.assertRaises( HTTPException ) as c:
            await self._call( ClaudeCodeQueueRequest( prompt="p" ), current_user={ "uid": "u-1" } )
        self.assertEqual( c.exception.status_code, 400 )

    async def test_invalid_task_type_400( self ):
        body = ClaudeCodeQueueRequest( prompt="p", task_type="bogus" )
        with self.assertRaises( HTTPException ) as c:
            await self._call( body )
        self.assertEqual( c.exception.status_code, 400 )
        self.assertIn( "Invalid task_type", c.exception.detail )

    async def test_task_type_lowercased_accepted( self ):
        # "interactive" → upper() → INTERACTIVE (valid).
        body = ClaudeCodeQueueRequest( prompt="p", task_type="interactive" )
        resp, factory, tq, trk = await self._call( body )
        self.assertEqual( resp.status, "queued" )
        _, kwargs = factory.call_args
        self.assertEqual( kwargs[ "args_dict" ][ "task_type" ], "INTERACTIVE" )

    async def test_factory_failure_500( self ):
        body = ClaudeCodeQueueRequest( prompt="p" )
        factory = MagicMock( side_effect=RuntimeError( "factory boom" ) )
        with self.assertRaises( HTTPException ) as c:
            await self._call( body, factory=factory )
        self.assertEqual( c.exception.status_code, 500 )
        self.assertIn( "Failed to submit", c.exception.detail )


if __name__ == "__main__":
    unittest.main()
