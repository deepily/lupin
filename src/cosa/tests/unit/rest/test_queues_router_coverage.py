"""
Supplemental coverage tests for cosa.rest.routers.queues.

Companion to test_queues_router.py (left untouched). This file CLOSES the
coverage gap on the endpoints the original suite did not reach: push validation
branches + 500, push_agentic, pool-status, get_queue admin/exclude + agentic
done/dead duration arms, get_job_interactions, send_job_message, cancel_job,
delete_all_queue_jobs, delete_queue_job, the job-history family, retry, pause /
resume, and the two checkpoint-resume endpoints.

Boundary-isolated: every DB / job-persistence / websocket / factory collaborator
is mocked. Zero GPU/DB/net/LLM. Run BOTH files together for measurement:

    PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python \
      -m pytest src/cosa/tests/unit/rest/test_queues_router.py \
                src/cosa/tests/unit/rest/test_queues_router_coverage.py \
      --cov=cosa.rest.routers.queues --cov-branch --cov-report=term-missing \
      -p no:cacheprovider -q
"""

import sys
import os
import time
import unittest
from datetime import datetime
from unittest.mock import Mock, MagicMock, AsyncMock, patch

# G1 — dual-key lupin_app.main patch (see test_queues_router.py for rationale)
def _patch_fastapi_main( mock_main ):
    """
    Patch BOTH sys.modules["lupin_app"] (a Mock carrying a .main attr) and
    sys.modules["lupin_app.main"] so `import lupin_app.main as m` resolves
    to mock_main regardless of prior import state (single-key patches pass in
    isolation but fail under full-suite ordering).
    """
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


from fastapi import HTTPException

import cosa.rest.routers.queues as Q
from cosa.rest.routers.queues import (
    _count_interactions_for_jobs,
    push, push_agentic, get_pool_status, get_queue, reset_queues,
    get_job_interactions, send_job_message, cancel_job,
    delete_all_queue_jobs, delete_queue_job,
    get_job_history, get_job_history_detail,
    delete_all_job_history, delete_job_history_endpoint,
    retry_job_history, pause_job, resume_job,
    resume_stalled_job, resume_tfe_smart,
    ResumeFromCheckpointRequest, TFEResumeFromRequest,
)
from cosa.rest.job_state import JobState
from cosa.agents.agentic_job_base import AgenticJobBase


# ---------------------------------------------------------------------------
# A fully-controlled stand-in that isinstance()-passes as an AgenticJobBase.
# ABC virtual-subclass registration — far simpler than satisfying the real
# abstract constructor, and lets us set instance attrs freely (spec=AgenticJobBase
# would reject the instance-only attrs the handler reads).
# ---------------------------------------------------------------------------
class _FakeAgenticJob:
    pass

AgenticJobBase.register( _FakeAgenticJob )


def _async_json_request( value=None, exc=None ):
    """Build a Mock FastAPI Request whose .json() resolves to value or raises exc."""
    req = Mock()
    if exc is not None:
        req.json = AsyncMock( side_effect=exc )
    else:
        req.json = AsyncMock( return_value=value )
    return req


def _ctx_db( mock_db ):
    """Return a MagicMock get_db replacement whose context-manager yields mock_db."""
    gd = MagicMock()
    gd.return_value.__enter__.return_value = mock_db
    return gd


class TestCountInteractions( unittest.TestCase ):
    """
    Coverage for _count_interactions_for_jobs.

    Ensures:
        - empty input short-circuits to {} (no query)
        - populated input returns the repo's batched count dict
        - a DB failure is swallowed and returns {} (logged)
    """

    def test_empty_input_returns_empty_no_query( self ):
        self.assertEqual( _count_interactions_for_jobs( [] ), {} )

    def test_populated_returns_repo_counts( self ):
        mock_db   = Mock()
        mock_repo = Mock()
        mock_repo.count_by_job_ids.return_value = { "j1": 2, "j2": 0 }
        with patch( "cosa.rest.db.database.get_db", _ctx_db( mock_db ) ), \
             patch( "cosa.rest.db.repositories.notification_repository.NotificationRepository", return_value=mock_repo ):
            out = _count_interactions_for_jobs( [ "j1", "j2" ] )
        self.assertEqual( out, { "j1": 2, "j2": 0 } )
        mock_repo.count_by_job_ids.assert_called_once_with( [ "j1", "j2" ] )

    def test_db_failure_returns_empty( self ):
        with patch( "cosa.rest.db.database.get_db", side_effect=Exception( "boom" ) ), \
             patch( "builtins.print" ):
            out = _count_interactions_for_jobs( [ "j1" ] )
        self.assertEqual( out, {} )


class TestPushIsRetired( unittest.IsolatedAsyncioTestCase ):
    """
    `POST /api/push` is a 410 tombstone as of 2026-08-21 — Rick: ONE entry point, and it
    is v2. This class used to cover the handler's validation and failure branches; the
    handler is deleted, so those branches no longer exist to cover.

    WHAT WENT AWAY WITH IT, named so it is not mistaken for coverage nobody wanted. The
    old door hand-validated its body and answered 400 for: unparseable JSON, a body that
    is not an object, a missing/blank/non-string `question`, and a missing/blank/
    non-string `websocket_id`. It answered 500 when `push_job` raised, and tolerated a
    non-dict result. `/api/v2/ask` replaces the validation with a Pydantic model
    (`AskRequest`), which rejects a bad body with 422 rather than 400 and treats
    `websocket_id` as optional — so the shapes are NOT equivalent, they are different by
    design. The 400-vs-422 change is visible to every caller and belongs in the cutover
    notes, not in a silent deletion.
    """

    async def test_the_door_is_gone_and_says_where_to_go( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await push()
        self.assertEqual( ctx.exception.status_code, 410 )
        self.assertIn( "/api/v2/ask", ctx.exception.detail )
        self.assertIn( "REMOVE BY",   ctx.exception.detail )

    async def test_it_refuses_before_touching_the_queue( self ):
        """
        The tombstone takes no queue dependency at all, which is the point: a refusal
        that still resolved `get_todo_queue` would keep a dead door coupled to live
        infrastructure. `push()` accepting zero arguments is the proof — this call would
        raise TypeError, not 410, if a dependency came back.
        """
        with self.assertRaises( HTTPException ) as ctx:
            await push()
        self.assertEqual( ctx.exception.status_code, 410 )


class TestPushAgenticIsRetired( unittest.IsolatedAsyncioTestCase ):
    """
    WHAT USED TO BE HERE: nine tests over the handler's hand-rolled validation — invalid
    JSON, a body that was not an object, a missing or non-string routing_command, blanks
    after stripping, a non-object args, the success shape, the construction 500 and the
    unknown-command 400.

    Those 400s are not lost, they moved: this door read the raw request and validated it
    by hand, and `/api/v2/submit` takes a Pydantic model, so the same bad bodies now come
    back as 422s from the model rather than 400s from a handler. That is a REAL change
    visible to every caller — 400 becomes 422, and `websocket_id` goes from required to
    optional — and it belongs in the cutover notes rather than in a silent deletion.
    """

    async def test_the_door_is_gone_and_says_where_to_go( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await push_agentic()
        self.assertEqual( ctx.exception.status_code, 410 )
        self.assertIn( "/api/v2/submit", ctx.exception.detail )
        self.assertIn( "REMOVE BY",      ctx.exception.detail )

    async def test_it_names_submit_and_not_ask( self ):
        """
        This door is submit-shaped in the most literal way of any of the ten — it already
        took the command as a parameter. Pointing it at `ask` would send an unattended,
        service-to-service caller to the door whose whole job is to ask questions back.
        """
        from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_SUBMIT, V2_ASK
        self.assertEqual( RETIRED_DOORS[ "/api/push-agentic" ], V2_SUBMIT )
        self.assertNotEqual( RETIRED_DOORS[ "/api/push-agentic" ], V2_ASK )

    async def test_it_refuses_before_touching_the_queue( self ):
        """
        The tombstone takes no queue dependency at all, which is the point: a refusal that
        still resolved `get_todo_queue` would keep a dead door coupled to live
        infrastructure. `push_agentic()` accepting zero arguments is the proof — this call
        would raise TypeError, not 410, if a dependency came back.
        """
        with self.assertRaises( HTTPException ) as ctx:
            await push_agentic()
        self.assertEqual( ctx.exception.status_code, 410 )


class TestPoolStatus( unittest.IsolatedAsyncioTestCase ):
    """Coverage for GET /api/queue/pool-status."""

    async def test_returns_pool_status( self ):
        rq = Mock()
        rq.get_pool_status.return_value = { "inflight_agentic_jobs": 2, "max_agentic_workers": 3, "pending_in_pool": 0 }
        out = await get_pool_status(
            current_user={ "uid": "u1", "email": "e", "roles": [ "user" ] },
            running_queue=rq )
        self.assertEqual( out[ "inflight_agentic_jobs" ], 2 )


def _make_agentic_done_job( id_hash="ag1", good_dates=True ):
    """Build a _FakeAgenticJob with the attrs get_queue's done/dead arms read."""
    job = _FakeAgenticJob()
    job.id_hash               = id_hash
    job.last_question_asked   = "Q?"
    job.answer                = "A"
    job.answer_conversational = "A convo"
    job.run_date              = "2025-08-05T11:00:00"
    job.created_date          = "2025-08-05T10:00:00"
    job.user_email            = "u1@x.com"
    job.session_id            = "sess"
    job.job_type              = "deep_research"
    job.is_cache_hit          = False
    job.state                 = JobState.COMPLETED
    job.error                 = None
    job.scheduled_at          = None
    job.monopolize            = False
    job.cost_summary          = { "usd": 0.0 }
    job.artifacts             = { "report_path": "/r", "plan_path": "/p" }
    if good_dates:
        job.started_at   = "2025-08-05T10:00:00"
        job.completed_at = "2025-08-05T10:05:00"
    else:
        job.started_at   = "not-a-date"
        job.completed_at = "also-bad"
    return job


class TestGetQueueExtra( unittest.IsolatedAsyncioTestCase ):
    """
    Coverage for get_queue admin filter arms (*, !self) and the agentic
    done/dead duration calculation success + except branches.
    """

    def setUp( self ):
        self.admin = { "uid": "admin1", "email": "a@x.com", "roles": [ "admin" ] }

    async def test_admin_wildcard_uses_get_all_jobs( self ):
        tq = Mock(); tq.get_all_jobs.return_value = []
        out = await get_queue( queue_name="todo", current_user=self.admin, user_filter="*",
                               todo_queue=tq, running_queue=Mock(), done_queue=Mock(), dead_queue=Mock() )
        tq.get_all_jobs.assert_called_once()
        self.assertEqual( out[ "filtered_by" ], "*" )
        self.assertTrue( out[ "is_admin_view" ] )

    async def test_admin_exclude_self_uses_excluding_user( self ):
        tq = Mock(); tq.get_jobs_excluding_user.return_value = []
        out = await get_queue( queue_name="todo", current_user=self.admin, user_filter="!self",
                               todo_queue=tq, running_queue=Mock(), done_queue=Mock(), dead_queue=Mock() )
        tq.get_jobs_excluding_user.assert_called_once_with( "admin1" )
        self.assertEqual( out[ "filtered_by" ], "!admin1" )

    async def test_done_agentic_duration_success_and_except( self ):
        dq = Mock()
        dq.get_jobs_for_user.return_value = [
            _make_agentic_done_job( "ag_good", good_dates=True ),
            _make_agentic_done_job( "ag_bad", good_dates=False ),
        ]
        with patch.object( Q, "_count_interactions_for_jobs", return_value={ "ag_good": 1 } ):
            out = await get_queue( queue_name="done", current_user=self.admin, user_filter=self.admin[ "uid" ],
                                   todo_queue=Mock(), running_queue=Mock(), done_queue=dq, dead_queue=Mock() )
        md = { j[ "job_id" ]: j for j in out[ "done_jobs_metadata" ] }
        self.assertEqual( md[ "ag_good" ][ "duration_seconds" ], 300.0 )
        self.assertIsNone( md[ "ag_bad" ][ "duration_seconds" ] )       # except arm
        self.assertEqual( md[ "ag_good" ][ "report_path" ], "/r" )      # agentic artifact surfaced
        self.assertTrue( md[ "ag_good" ][ "has_interactions" ] )

    async def test_dead_agentic_duration_success_and_except( self ):
        dq = Mock()
        dq.get_jobs_for_user.return_value = [
            _make_agentic_done_job( "dead_good", good_dates=True ),
            _make_agentic_done_job( "dead_bad", good_dates=False ),
        ]
        with patch.object( Q, "_count_interactions_for_jobs", return_value={} ):
            out = await get_queue( queue_name="dead", current_user=self.admin, user_filter=self.admin[ "uid" ],
                                   todo_queue=Mock(), running_queue=Mock(), done_queue=Mock(), dead_queue=dq )
        md = { j[ "job_id" ]: j for j in out[ "dead_jobs_metadata" ] }
        self.assertEqual( md[ "dead_good" ][ "duration_seconds" ], 300.0 )
        self.assertIsNone( md[ "dead_bad" ][ "duration_seconds" ] )
        self.assertEqual( md[ "dead_good" ][ "plan_path" ], "/p" )


class TestGetJobInteractions( unittest.IsolatedAsyncioTestCase ):
    """Coverage for GET /api/get-job-interactions/{job_id}."""

    def setUp( self ):
        self.user  = { "uid": "u1", "email": "u1@x.com", "roles": [ "user" ] }
        self.admin = { "uid": "admin1", "email": "a@x.com", "roles": [ "admin" ] }

    def _mem_job( self, uid="u1" ):
        job = Mock()
        job.id_hash               = "job1"
        job.user_id               = uid
        job.session_id            = "sess"
        job.last_question_asked   = "Q?"
        job.answer                = "A"
        job.answer_conversational = "A convo"
        job.job_type              = "math"
        job.run_date              = "2025-08-05T11:00:00"
        job.created_date          = "2025-08-05T10:00:00"
        return job

    def _notif( self, pgid=None, nid="1" ):
        n = Mock()
        n.progress_group_id  = pgid
        n.id                 = nid
        n.type               = "progress"
        n.message            = "hello"
        n.created_at         = datetime( 2025, 8, 5, 12, 0, 0 )
        n.response_requested = False
        n.response_value     = None
        n.priority           = "low"
        n.abstract           = None
        return n

    async def test_in_memory_found_with_dedup( self ):
        # Lead with a non-matching snapshot so the inner scan loop iterates past
        # it (covers the id_hash-mismatch continue arm) before matching job1.
        other = self._mem_job(); other.id_hash = "other-job"
        rq = Mock(); rq.get_all_jobs.return_value = [ other, self._mem_job() ]
        empty = Mock(); empty.get_all_jobs.return_value = []
        mock_db = Mock()
        # two notifs share a progress group (dedup → 1 kept), one ungrouped
        notifs = [ self._notif( "g1", "1" ), self._notif( "g1", "2" ), self._notif( None, "3" ) ]
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = notifs
        with patch( "cosa.rest.db.database.get_db", _ctx_db( mock_db ) ), \
             patch( "cosa.rest.postgres_models.Notification", Mock() ), \
             patch( "builtins.print" ):
            out = await get_job_interactions( job_id="job1", current_user=self.user,
                                              todo_queue=empty, running_queue=rq, done_queue=empty )
        self.assertEqual( out[ "job_id" ], "job1" )
        self.assertEqual( out[ "interaction_count" ], 2 )    # g1 deduped + ungrouped

    async def test_db_fallback_found_isoformat( self ):
        empty = Mock(); empty.get_all_jobs.return_value = []
        db_job = {
            "user_id"      : "u1",
            "session_id"   : "sess",
            "question_text": "Q?",
            "job_type"     : "math",
            "metadata_json": { "answer_conversational": "A convo" },
            "created_at"   : datetime( 2025, 8, 5, 10, 0, 0 ),
        }
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value=db_job ), \
             patch( "cosa.rest.db.database.get_db", _ctx_db( mock_db ) ), \
             patch( "cosa.rest.postgres_models.Notification", Mock() ), \
             patch( "builtins.print" ):
            out = await get_job_interactions( job_id="job1", current_user=self.user,
                                              todo_queue=empty, running_queue=empty, done_queue=empty )
        self.assertEqual( out[ "session_id" ], "sess" )
        self.assertEqual( out[ "job_metadata" ][ "run_date" ], "2025-08-05T10:00:00" )

    async def test_db_fallback_created_at_plain_string( self ):
        empty = Mock(); empty.get_all_jobs.return_value = []
        db_job = { "user_id": "u1", "session_id": None, "question_text": "Q",
                   "job_type": "x", "metadata_json": None, "created_at": "raw-string" }
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value=db_job ), \
             patch( "cosa.rest.db.database.get_db", _ctx_db( mock_db ) ), \
             patch( "cosa.rest.postgres_models.Notification", Mock() ), \
             patch( "builtins.print" ):
            out = await get_job_interactions( job_id="job1", current_user=self.user,
                                              todo_queue=empty, running_queue=empty, done_queue=empty )
        self.assertEqual( out[ "job_metadata" ][ "created_date" ], "raw-string" )

    async def test_not_found_404( self ):
        empty = Mock(); empty.get_all_jobs.return_value = []
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value=None ), \
             patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_job_interactions( job_id="nope", current_user=self.user,
                                            todo_queue=empty, running_queue=empty, done_queue=empty )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_unauthorized_403( self ):
        rq = Mock(); rq.get_all_jobs.return_value = [ self._mem_job( uid="other" ) ]
        empty = Mock(); empty.get_all_jobs.return_value = []
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_job_interactions( job_id="job1", current_user=self.user,
                                            todo_queue=empty, running_queue=rq, done_queue=empty )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_notification_query_exception_swallowed( self ):
        rq = Mock(); rq.get_all_jobs.return_value = [ self._mem_job() ]
        empty = Mock(); empty.get_all_jobs.return_value = []
        with patch( "cosa.rest.db.database.get_db", side_effect=Exception( "db gone" ) ), \
             patch( "cosa.rest.postgres_models.Notification", Mock() ), \
             patch( "builtins.print" ):
            out = await get_job_interactions( job_id="job1", current_user=self.user,
                                              todo_queue=empty, running_queue=rq, done_queue=empty )
        # query failed → interactions stays the empty default
        self.assertEqual( out[ "interaction_count" ], 0 )


class TestSendJobMessage( unittest.IsolatedAsyncioTestCase ):
    """Coverage for POST /api/jobs/{job_id}/message."""

    def setUp( self ):
        self.user = { "uid": "u1", "email": "u1@x.com", "roles": [ "user" ] }

    def _running_with( self, job ):
        rq = Mock(); rq.get_by_id_hash.return_value = job
        return rq

    async def test_invalid_json_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await send_job_message( job_id="j", request=_async_json_request( exc=ValueError( "x" ) ),
                                    current_user=self.user, running_queue=Mock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_empty_message_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await send_job_message( job_id="j", request=_async_json_request( value={ "message": "  " } ),
                                    current_user=self.user, running_queue=Mock() )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "cannot be empty", ctx.exception.detail )

    async def test_bad_priority_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await send_job_message( job_id="j", request=_async_json_request( value={ "message": "hi", "priority": "loud" } ),
                                    current_user=self.user, running_queue=Mock() )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "Priority must be", ctx.exception.detail )

    async def test_job_not_found_404( self ):
        rq = Mock(); rq.get_by_id_hash.side_effect = KeyError( "nope" )
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await send_job_message( job_id="j", request=_async_json_request( value={ "message": "hi" } ),
                                        current_user=self.user, running_queue=rq )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_not_owner_403( self ):
        job = Mock(); job.user_id = "other"
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await send_job_message( job_id="j", request=_async_json_request( value={ "message": "hi" } ),
                                        current_user=self.user, running_queue=self._running_with( job ) )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_user_not_found_404( self ):
        job = Mock(); job.user_id = "u1"
        mock_db = Mock()
        user_repo = Mock(); user_repo.get_by_email.return_value = None
        with patch( "cosa.rest.db.database.get_db", _ctx_db( mock_db ) ), \
             patch( "cosa.rest.db.repositories.user_repository.UserRepository", return_value=user_repo ), \
             patch( "cosa.rest.db.repositories.notification_repository.NotificationRepository", Mock() ), \
             patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await send_job_message( job_id="j", request=_async_json_request( value={ "message": "hi" } ),
                                        current_user=self.user, running_queue=self._running_with( job ) )
        self.assertEqual( ctx.exception.status_code, 404 )
        self.assertIn( "User not found", ctx.exception.detail )

    async def test_notification_create_exception_500( self ):
        job = Mock(); job.user_id = "u1"
        mock_db = Mock()
        user_repo = Mock(); user_repo.get_by_email.return_value = Mock( id="uid-db" )
        notif_repo = Mock(); notif_repo.create_notification.side_effect = Exception( "insert fail" )
        with patch( "cosa.rest.db.database.get_db", _ctx_db( mock_db ) ), \
             patch( "cosa.rest.db.repositories.user_repository.UserRepository", return_value=user_repo ), \
             patch( "cosa.rest.db.repositories.notification_repository.NotificationRepository", return_value=notif_repo ), \
             patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await send_job_message( job_id="j", request=_async_json_request( value={ "message": "hi" } ),
                                        current_user=self.user, running_queue=self._running_with( job ) )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success_with_ws_and_echo( self ):
        job = Mock(); job.user_id = "u1"
        mock_db = Mock()
        user_repo = Mock(); user_repo.get_by_email.return_value = Mock( id="uid-db" )
        notif_repo = Mock()
        notif_repo.create_notification.return_value = Mock( id="notif-1" )
        mock_main = Mock(); mock_main.websocket_manager = Mock()
        with patch( "cosa.rest.db.database.get_db", _ctx_db( mock_db ) ), \
             patch( "cosa.rest.db.repositories.user_repository.UserRepository", return_value=user_repo ), \
             patch( "cosa.rest.db.repositories.notification_repository.NotificationRepository", return_value=notif_repo ), \
             _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="2025-08-05T12:00:00" ), \
             patch( "builtins.print" ):
            out = await send_job_message( job_id="j", request=_async_json_request( value={ "message": "hi", "priority": "urgent" } ),
                                          current_user=self.user, running_queue=self._running_with( job ) )
        self.assertEqual( out[ "status" ], "delivered" )
        self.assertEqual( out[ "notification_id" ], "notif-1" )
        mock_main.websocket_manager.emit_to_user_or_listener_sync.assert_called_once()
        mock_main.websocket_manager.emit_to_user_sync.assert_called_once()

    async def test_success_echo_persist_failure_nonfatal( self ):
        job = Mock(); job.user_id = "u1"
        mock_db = Mock()
        user_repo = Mock(); user_repo.get_by_email.return_value = Mock( id="uid-db" )
        notif_repo = Mock()
        # first create_notification ok (the user message), second (echo) raises
        notif_repo.create_notification.side_effect = [ Mock( id="notif-1" ), Exception( "echo fail" ) ]
        mock_main = Mock(); mock_main.websocket_manager = Mock()
        with patch( "cosa.rest.db.database.get_db", _ctx_db( mock_db ) ), \
             patch( "cosa.rest.db.repositories.user_repository.UserRepository", return_value=user_repo ), \
             patch( "cosa.rest.db.repositories.notification_repository.NotificationRepository", return_value=notif_repo ), \
             _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="2025-08-05T12:00:00" ), \
             patch( "builtins.print" ):
            out = await send_job_message( job_id="j", request=_async_json_request( value={ "message": "hi" } ),
                                          current_user=self.user, running_queue=self._running_with( job ) )
        self.assertEqual( out[ "status" ], "delivered" )   # echo failure non-fatal

    async def test_success_ws_emission_failure_nonfatal( self ):
        job = Mock(); job.user_id = "u1"
        mock_db = Mock()
        user_repo = Mock(); user_repo.get_by_email.return_value = Mock( id="uid-db" )
        notif_repo = Mock(); notif_repo.create_notification.return_value = Mock( id="notif-1" )
        mock_main = Mock()
        ws = Mock(); ws.emit_to_user_or_listener_sync.side_effect = Exception( "ws down" )
        mock_main.websocket_manager = ws
        with patch( "cosa.rest.db.database.get_db", _ctx_db( mock_db ) ), \
             patch( "cosa.rest.db.repositories.user_repository.UserRepository", return_value=user_repo ), \
             patch( "cosa.rest.db.repositories.notification_repository.NotificationRepository", return_value=notif_repo ), \
             _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="2025-08-05T12:00:00" ), \
             patch( "builtins.print" ):
            out = await send_job_message( job_id="j", request=_async_json_request( value={ "message": "hi" } ),
                                          current_user=self.user, running_queue=self._running_with( job ) )
        self.assertEqual( out[ "status" ], "delivered" )   # ws failure non-fatal


class TestCancelJob( unittest.IsolatedAsyncioTestCase ):
    """Coverage for POST /api/jobs/{job_id}/cancel."""

    def setUp( self ):
        self.user = { "uid": "u1", "email": "e", "roles": [ "user" ] }

    async def test_not_found_404( self ):
        # Row 4b87fe61: a 404 now means BOTH queues were searched, not just running.
        rq = Mock(); rq.get_by_id_hash.side_effect = KeyError()
        tq = Mock(); tq.get_by_id_hash.side_effect = KeyError()
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_not_owner_403( self ):
        job = Mock(); job.user_id = "other"
        rq = Mock(); rq.get_by_id_hash.return_value = job
        tq = Mock(); tq.get_by_id_hash.side_effect = KeyError()
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_non_agentic_400( self ):
        # Still a 400, but the message now names the lever that does work
        # (row 4b87fe61 — an endpoint that only says what it will not do).
        job = Mock( spec=[ "user_id" ] ); job.user_id = "u1"   # plain Mock, not AgenticJobBase
        rq = Mock(); rq.get_by_id_hash.return_value = job
        tq = Mock(); tq.get_by_id_hash.side_effect = KeyError()
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "does not support graceful cancellation", ctx.exception.detail )
        self.assertIn( "DELETE /api/queue/run/j", ctx.exception.detail )

    async def test_success( self ):
        job = _FakeAgenticJob(); job.user_id = "u1"; job.request_cancel = Mock()
        rq = Mock(); rq.get_by_id_hash.return_value = job
        tq = Mock(); tq.get_by_id_hash.side_effect = KeyError()
        with patch( "builtins.print" ):
            out = await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )
        self.assertEqual( out[ "status" ], "cancel_requested" )
        self.assertEqual( out[ "queue" ], "run" )
        job.request_cancel.assert_called_once()


class TestCancelJobReachesQueuedJobs( unittest.IsolatedAsyncioTestCase ):
    """
    Falsification suite for row 4b87fe61: cancel must reach a job that has not
    started yet.

    Before the fix, cancel_job looked the job up in the RUNNING queue only, so a
    queued job — the cheap, no-work-lost moment you most want to cancel at — came
    back 404 "Job not found or not running". A caller who believed that 404 would
    then watch the job start anyway.
    """

    def setUp( self ):
        self.user  = { "uid": "u1", "email": "e", "roles": [ "user" ] }
        self.admin = { "uid": "admin", "email": "a", "roles": [ "admin" ] }

    def _queues( self, todo_job=None, running_job=None ):
        """Build (running_queue, todo_queue) mocks; a None job means KeyError."""
        rq = Mock()
        tq = Mock()
        if running_job is None:
            rq.get_by_id_hash.side_effect = KeyError()
        else:
            rq.get_by_id_hash.return_value = running_job
        if todo_job is None:
            tq.get_by_id_hash.side_effect = KeyError()
        else:
            tq.get_by_id_hash.return_value = todo_job
            tq.delete_by_id_hash.return_value = True
        return rq, tq

    async def test_queued_job_is_cancelled_not_404( self ):
        """A job waiting in todo is cancelled, and the todo queue really loses it."""
        job = _FakeAgenticJob(); job.user_id = "u1"
        rq, tq = self._queues( todo_job=job )

        mock_main = Mock(); mock_main.websocket_manager = Mock()
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="2025-08-05T12:00:00" ), \
             patch( "builtins.print" ):
            out = await cancel_job( job_id="ts-3fc47888", current_user=self.user,
                                    running_queue=rq, todo_queue=tq )

        self.assertEqual( out[ "status" ], "cancelled" )
        self.assertEqual( out[ "queue" ], "todo" )
        tq.delete_by_id_hash.assert_called_once_with( "ts-3fc47888" )

    async def test_queued_non_agentic_job_is_also_cancelled( self ):
        """The agentic-only restriction is a RUNNING-queue rule, not a queued-job rule."""
        job = Mock( spec=[ "user_id" ] ); job.user_id = "u1"   # deliberately not agentic
        rq, tq = self._queues( todo_job=job )

        mock_main = Mock(); mock_main.websocket_manager = Mock()
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="2025-08-05T12:00:00" ), \
             patch( "builtins.print" ):
            out = await cancel_job( job_id="j", current_user=self.user,
                                    running_queue=rq, todo_queue=tq )

        self.assertEqual( out[ "status" ], "cancelled" )

    async def test_cancelling_a_queued_job_emits_job_removed( self ):
        """The UI must learn the card is gone, same as the delete path does."""
        job = _FakeAgenticJob(); job.user_id = "u1"
        rq, tq = self._queues( todo_job=job )

        mock_main = Mock(); mock_main.websocket_manager = Mock()
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="2025-08-05T12:00:00" ), \
             patch( "builtins.print" ):
            await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )

        mock_main.websocket_manager.emit_to_user_and_admins_sync.assert_called_once()
        args = mock_main.websocket_manager.emit_to_user_and_admins_sync.call_args[ 0 ]
        self.assertEqual( args[ 1 ], "job_removed" )
        self.assertEqual( args[ 2 ][ "queue" ], "todo" )

    async def test_websocket_failure_does_not_fail_the_cancel( self ):
        """A broken websocket must not turn a successful cancel into an error."""
        job = _FakeAgenticJob(); job.user_id = "u1"
        rq, tq = self._queues( todo_job=job )

        mock_main = Mock()
        mock_main.websocket_manager.emit_to_user_and_admins_sync.side_effect = RuntimeError( "boom" )
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="2025-08-05T12:00:00" ), \
             patch( "builtins.print" ):
            out = await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )

        self.assertEqual( out[ "status" ], "cancelled" )

    async def test_queued_job_owned_by_someone_else_is_403( self ):
        """Ownership is checked on the queued path too, not just the running one."""
        job = _FakeAgenticJob(); job.user_id = "someone_else"
        rq, tq = self._queues( todo_job=job )

        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_admin_may_cancel_another_users_queued_job( self ):
        """Admins keep the same override they have on every other job verb."""
        job = _FakeAgenticJob(); job.user_id = "someone_else"
        rq, tq = self._queues( todo_job=job )

        mock_main = Mock(); mock_main.websocket_manager = Mock()
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="2025-08-05T12:00:00" ), \
             patch( "builtins.print" ):
            out = await cancel_job( job_id="j", current_user=self.admin, running_queue=rq, todo_queue=tq )
        self.assertEqual( out[ "status" ], "cancelled" )

    async def test_running_job_still_wins_over_a_stale_todo_entry( self ):
        """If the job is running, cancel it gracefully — do not delete it from todo."""
        running = _FakeAgenticJob(); running.user_id = "u1"; running.request_cancel = Mock()
        todo    = _FakeAgenticJob(); todo.user_id = "u1"
        rq, tq  = self._queues( todo_job=todo, running_job=running )

        with patch( "builtins.print" ):
            out = await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )

        self.assertEqual( out[ "status" ], "cancel_requested" )
        running.request_cancel.assert_called_once()
        tq.delete_by_id_hash.assert_not_called()

    async def test_unknown_job_404_does_not_claim_it_is_merely_not_running( self ):
        """The 404 must not imply 'exists but idle' when nothing was found at all."""
        rq, tq = self._queues()

        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await cancel_job( job_id="typo", current_user=self.user, running_queue=rq, todo_queue=tq )

        self.assertEqual( ctx.exception.status_code, 404 )
        detail = ctx.exception.detail
        self.assertIn( "queued", detail )
        self.assertIn( "running", detail )
        self.assertNotEqual( detail, "Job not found or not running: typo" )

    async def test_delete_failure_on_the_queued_path_is_reported( self ):
        """A delete that reports no-op must not be dressed up as a successful cancel."""
        job = _FakeAgenticJob(); job.user_id = "u1"
        rq, tq = self._queues( todo_job=job )
        tq.delete_by_id_hash.return_value = False

        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 409 )

    async def test_running_non_agentic_400_names_the_working_lever( self ):
        """The 400 must say what to do instead, not just what it will not do."""
        job = Mock( spec=[ "user_id" ] ); job.user_id = "u1"
        rq, tq = self._queues( running_job=job )

        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await cancel_job( job_id="j", current_user=self.user, running_queue=rq, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertIn( "/api/queue/run/", ctx.exception.detail )


class TestDeleteAllQueueJobs( unittest.IsolatedAsyncioTestCase ):
    """Coverage for DELETE /api/queue/{queue_name}/all."""

    async def test_invalid_name_400( self ):
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_all_queue_jobs( queue_name="bogus",
                                             current_user={ "uid": "u1", "roles": [ "user" ] },
                                             running_queue=Mock(), done_queue=Mock(),
                                             dead_queue=Mock(), todo_queue=Mock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_admin_clears_whole_queue( self ):
        dq = Mock(); dq.size.return_value = 7
        with patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await delete_all_queue_jobs( queue_name="done",
                                               current_user={ "uid": "admin1", "roles": [ "admin" ] },
                                               running_queue=Mock(), done_queue=dq,
                                               dead_queue=Mock(), todo_queue=Mock() )
        dq.clear.assert_called_once()
        self.assertEqual( out[ "items_deleted" ], 7 )

    async def test_regular_user_per_job_delete_run_agentic_cancel( self ):
        ag = _FakeAgenticJob(); ag.id_hash = "a1"; ag.request_cancel = Mock()
        rq = Mock()
        rq.get_jobs_for_user.return_value = [ ag ]
        rq.delete_by_id_hash.return_value = True
        with patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await delete_all_queue_jobs( queue_name="run",
                                               current_user={ "uid": "u1", "roles": [ "user" ] },
                                               running_queue=rq, done_queue=Mock(),
                                               dead_queue=Mock(), todo_queue=Mock() )
        ag.request_cancel.assert_called_once()
        self.assertEqual( out[ "items_deleted" ], 1 )

    async def test_regular_user_delete_returns_false_not_counted( self ):
        job = Mock(); job.id_hash = "j1"
        tq = Mock()
        tq.get_jobs_for_user.return_value = [ job ]
        tq.delete_by_id_hash.return_value = False
        with patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await delete_all_queue_jobs( queue_name="todo",
                                               current_user={ "uid": "u1", "roles": [ "user" ] },
                                               running_queue=Mock(), done_queue=Mock(),
                                               dead_queue=Mock(), todo_queue=tq )
        self.assertEqual( out[ "items_deleted" ], 0 )


class TestDeleteQueueJob( unittest.IsolatedAsyncioTestCase ):
    """Coverage for DELETE /api/queue/{queue_name}/{job_id}."""

    def setUp( self ):
        self.user = { "uid": "u1", "email": "e", "roles": [ "user" ] }

    async def test_invalid_name_400( self ):
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_queue_job( queue_name="bogus", job_id="j", current_user=self.user,
                                        running_queue=Mock(), done_queue=Mock(), dead_queue=Mock(), todo_queue=Mock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_not_found_404( self ):
        tq = Mock(); tq.get_by_id_hash.side_effect = KeyError()
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_queue_job( queue_name="todo", job_id="j", current_user=self.user,
                                        running_queue=Mock(), done_queue=Mock(), dead_queue=Mock(), todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_not_owner_403( self ):
        job = Mock(); job.user_id = "other"
        tq = Mock(); tq.get_by_id_hash.return_value = job
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_queue_job( queue_name="todo", job_id="j", current_user=self.user,
                                        running_queue=Mock(), done_queue=Mock(), dead_queue=Mock(), todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_delete_returns_false_404( self ):
        job = Mock(); job.user_id = "u1"
        tq = Mock(); tq.get_by_id_hash.return_value = job; tq.delete_by_id_hash.return_value = False
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_queue_job( queue_name="todo", job_id="j", current_user=self.user,
                                        running_queue=Mock(), done_queue=Mock(), dead_queue=Mock(), todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_run_agentic_cancel_and_ws_emit_success( self ):
        ag = _FakeAgenticJob(); ag.user_id = "u1"; ag.request_cancel = Mock()
        rq = Mock(); rq.get_by_id_hash.return_value = ag; rq.delete_by_id_hash.return_value = True
        mock_main = Mock(); mock_main.websocket_manager = Mock()
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await delete_queue_job( queue_name="run", job_id="j", current_user=self.user,
                                          running_queue=rq, done_queue=Mock(), dead_queue=Mock(), todo_queue=Mock() )
        ag.request_cancel.assert_called_once()
        mock_main.websocket_manager.emit_to_user_and_admins_sync.assert_called_once()
        self.assertEqual( out[ "status" ], "deleted" )

    async def test_ws_manager_none_skips_emit( self ):
        job = Mock(); job.user_id = "u1"
        tq = Mock(); tq.get_by_id_hash.return_value = job; tq.delete_by_id_hash.return_value = True
        mock_main = Mock(); mock_main.websocket_manager = None
        with _patch_fastapi_main( mock_main ), patch( "builtins.print" ):
            out = await delete_queue_job( queue_name="todo", job_id="j", current_user=self.user,
                                          running_queue=Mock(), done_queue=Mock(), dead_queue=Mock(), todo_queue=tq )
        self.assertEqual( out[ "status" ], "deleted" )

    async def test_ws_emit_exception_warned( self ):
        job = Mock(); job.user_id = "u1"
        tq = Mock(); tq.get_by_id_hash.return_value = job; tq.delete_by_id_hash.return_value = True
        mock_main = Mock()
        ws = Mock(); ws.emit_to_user_and_admins_sync.side_effect = Exception( "ws down" )
        mock_main.websocket_manager = ws
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await delete_queue_job( queue_name="todo", job_id="j", current_user=self.user,
                                          running_queue=Mock(), done_queue=Mock(), dead_queue=Mock(), todo_queue=tq )
        self.assertEqual( out[ "status" ], "deleted" )   # emit failure swallowed


class TestJobHistory( unittest.IsolatedAsyncioTestCase ):
    """Coverage for the /api/job-history family."""

    def setUp( self ):
        self.user  = { "uid": "u1", "email": "e", "roles": [ "user" ] }
        self.admin = { "uid": "admin1", "email": "a", "roles": [ "admin" ] }

    async def test_get_history_regular_user_with_exclude_ids( self ):
        with patch( "cosa.rest.job_persistence.query_job_history",
                    return_value={ "jobs": [ { "id": 1 } ], "total": 1 } ) as qh:
            # user_filter MUST be passed explicitly — see the guard test in this class.
            # Calling the endpoint directly bypasses FastAPI, so an omitted
            # Query-defaulted parameter arrives as the Query OBJECT, not None.
            out = await get_job_history( current_user=self.user, status="failed", job_type="deep_research",
                                         limit=10, offset=0, days=7, exclude_ids=" a , b ,, ",
                                         user_filter=None )
        # regular user → filtered to own uid; exclude_ids parsed to ["a","b"]
        _, kwargs = qh.call_args
        self.assertEqual( kwargs[ "user_id" ], "u1" )
        self.assertEqual( kwargs[ "exclude_ids" ], [ "a", "b" ] )
        self.assertEqual( out[ "filtered_by" ], "u1" )

    async def test_get_history_admin_no_exclude( self ):
        with patch( "cosa.rest.job_persistence.query_job_history",
                    return_value={ "jobs": [], "total": 0 } ) as qh:
            out = await get_job_history( current_user=self.admin, status=None, job_type=None,
                                         limit=20, offset=0, days=None, exclude_ids=None,
                                         user_filter=None )
        _, kwargs = qh.call_args
        self.assertIsNone( kwargs[ "user_id" ] )       # admin → all
        self.assertIsNone( kwargs[ "exclude_ids" ] )
        self.assertEqual( out[ "filtered_by" ], "all" )

    def test_every_query_defaulted_param_is_known_to_the_direct_call_tests( self ):
        """
        THE GUARD FOR THE NEXT PARAMETER (row 8145f3e1).

        Every test in this class calls `get_job_history` DIRECTLY, which skips FastAPI's
        dependency resolution entirely. A parameter declared `= Query( None )` therefore
        arrives as the Query OBJECT unless the test passes it, and `Query(None) is None`
        is False — so the endpoint takes the "a filter was supplied" branch and behaves
        as though the caller asked for something.

        That is exactly how these tests broke: e205a3b1 added `user_filter`, the two
        direct-call tests did not pass it, and the sentinel flowed into string code
        (`'Query' object has no attribute 'startswith'`) and into the permission check
        (a 403 where the test expected rows). ONE root cause, two unrelated-looking
        symptoms — which is why it first read as two separate bugs.

        Adding another `Query`-defaulted parameter would do it again, silently, to
        whichever direct call forgot it. This set is the tripwire: extend it
        deliberately, and update every direct call in this class in the same edit.
        """
        import inspect
        from fastapi.params import Query as QueryParam

        query_defaulted = {
            name for name, param in inspect.signature( get_job_history ).parameters.items()
            if isinstance( param.default, QueryParam )
        }

        self.assertEqual(
            query_defaulted,
            { "status", "job_type", "limit", "offset", "days", "exclude_ids", "user_filter" },
            "get_job_history's Query-defaulted parameters changed. Every direct call in "
            "this class must pass the new one explicitly, or it receives the Query object "
            "instead of the default value. Update the calls, then update this set."
        )

    async def test_get_detail_not_found_404( self ):
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_job_history_detail( job_id="j", current_user=self.user )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_get_detail_unauthorized_403( self ):
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value={ "user_id": "other" } ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_job_history_detail( job_id="j", current_user=self.user )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_get_detail_success( self ):
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value={ "user_id": "u1", "x": 1 } ):
            out = await get_job_history_detail( job_id="j", current_user=self.user )
        self.assertEqual( out[ "x" ], 1 )

    async def test_delete_all_history_invalid_days_400( self ):
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_all_job_history( current_user=self.user, days="seven" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_delete_all_history_numeric_days( self ):
        with patch( "cosa.rest.job_persistence.delete_job_history_bulk", return_value=4 ) as db, \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await delete_all_job_history( current_user=self.user, days="7" )
        _, kwargs = db.call_args
        self.assertEqual( kwargs[ "days" ], 7 )
        self.assertEqual( out[ "items_deleted" ], 4 )
        self.assertEqual( out[ "days_filter" ], "7" )

    async def test_delete_all_history_all_admin( self ):
        with patch( "cosa.rest.job_persistence.delete_job_history_bulk", return_value=9 ) as db, \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await delete_all_job_history( current_user=self.admin, days=None )
        _, kwargs = db.call_args
        self.assertIsNone( kwargs[ "user_id" ] )   # admin
        self.assertIsNone( kwargs[ "days" ] )
        self.assertEqual( out[ "days_filter" ], "all" )

    async def test_delete_one_not_found_404( self ):
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value=None ), \
             patch( "cosa.rest.job_persistence.delete_job_history", Mock() ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_job_history_endpoint( job_id="j", current_user=self.user )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_delete_one_unauthorized_403( self ):
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value={ "user_id": "other" } ), \
             patch( "cosa.rest.job_persistence.delete_job_history", Mock() ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_job_history_endpoint( job_id="j", current_user=self.user )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_delete_one_delete_fails_500( self ):
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value={ "user_id": "u1" } ), \
             patch( "cosa.rest.job_persistence.delete_job_history", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                await delete_job_history_endpoint( job_id="j", current_user=self.user )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_delete_one_success( self ):
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value={ "user_id": "u1" } ), \
             patch( "cosa.rest.job_persistence.delete_job_history", return_value=True ):
            out = await delete_job_history_endpoint( job_id="j", current_user=self.user )
        self.assertEqual( out[ "status" ], "deleted" )


class TestRetryJobHistoryIsRetired( unittest.IsolatedAsyncioTestCase ):
    """
    `POST /api/job-history/{job_id}/retry` is a 410 tombstone as of 2026-08-21. It was a
    queue door wearing a job-history URL: it read `question_text` off a stored row and
    called `push_job` with it — its own comment said "the same pattern as POST /api/push".

    WHAT WENT AWAY WITH IT. The old handler answered 404 for an unknown job, 403 when the
    caller neither owned the job nor was an admin, and 400 for a job whose status was not
    retryable or a body with no `websocket_id`. The 403 DISSOLVES rather than moves:
    `/api/v2/ask` asks a question as the calling user, so there is no other user's row to
    be authorised against. The 404 and the status check do NOT dissolve — a client now
    re-asks the stored question itself, so nothing checks that the job existed or was in
    a retryable state. `notifications.js` already holds the question text
    (`retryHistoryJob( jobId, questionText )` shows it in the confirm dialog), but
    `JobsPaneRenderer.ts` does not — it has only the id hash, so the multiplexer's retry
    button needs the question on the card before it can cut over. Named here because a
    caller left without a path is not a caller that has been migrated.
    """

    async def test_the_door_is_gone_and_says_where_to_go( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await retry_job_history()
        self.assertEqual( ctx.exception.status_code, 410 )
        self.assertIn( "/api/v2/ask", ctx.exception.detail )
        self.assertIn( "REMOVE BY",   ctx.exception.detail )

    async def test_it_refuses_without_reading_the_job_row( self ):
        """
        No lookup, no auth check, no queue — a tombstone must not keep the dead door
        wired to job_persistence. The handler takes NO arguments, not even the `job_id`
        the route still declares, because it has nothing to look the job up for; that
        zero-argument signature is what this call proves. Restore any dependency and this
        raises TypeError instead of a clean 410.
        """
        with self.assertRaises( HTTPException ) as ctx:
            await retry_job_history()
        self.assertEqual( ctx.exception.status_code, 410 )


class TestPauseResume( unittest.IsolatedAsyncioTestCase ):
    """Coverage for PATCH pause / resume todo-queue endpoints."""

    def setUp( self ):
        self.user = { "uid": "u1", "email": "e", "roles": [ "user" ] }

    async def test_pause_not_found_404( self ):
        tq = Mock(); tq.get_by_id_hash.side_effect = KeyError()
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await pause_job( job_id="j", current_user=self.user, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_pause_not_owner_403( self ):
        job = Mock(); job.user_id = "other"
        tq = Mock(); tq.get_by_id_hash.return_value = job
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await pause_job( job_id="j", current_user=self.user, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_pause_success_with_ws( self ):
        job = Mock(); job.user_id = "u1"
        tq = Mock(); tq.get_by_id_hash.return_value = job
        mock_main = Mock(); mock_main.websocket_manager = Mock()
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await pause_job( job_id="j", current_user=self.user, todo_queue=tq )
        self.assertEqual( out[ "status" ], "paused" )
        self.assertEqual( job.state, JobState.PAUSED )
        mock_main.websocket_manager.emit_to_user_and_admins_sync.assert_called_once()

    async def test_pause_ws_exception_swallowed( self ):
        job = Mock(); job.user_id = "u1"
        tq = Mock(); tq.get_by_id_hash.return_value = job
        mock_main = Mock()
        ws = Mock(); ws.emit_to_user_and_admins_sync.side_effect = Exception( "ws" )
        mock_main.websocket_manager = ws
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await pause_job( job_id="j", current_user=self.user, todo_queue=tq )
        self.assertEqual( out[ "status" ], "paused" )

    async def test_resume_not_found_404( self ):
        tq = Mock(); tq.get_by_id_hash.side_effect = KeyError()
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await resume_job( job_id="j", current_user=self.user, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_resume_not_owner_403( self ):
        job = Mock(); job.user_id = "other"
        tq = Mock(); tq.get_by_id_hash.return_value = job
        with patch( "builtins.print" ):
            with self.assertRaises( HTTPException ) as ctx:
                await resume_job( job_id="j", current_user=self.user, todo_queue=tq )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_resume_success_with_ws_and_notify( self ):
        job = Mock(); job.user_id = "u1"
        tq = MagicMock()
        tq.get_by_id_hash.return_value = job
        mock_main = Mock(); mock_main.websocket_manager = Mock()
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await resume_job( job_id="j", current_user=self.user, todo_queue=tq )
        self.assertEqual( out[ "status" ], "resumed" )
        self.assertEqual( job.state, JobState.QUEUED )
        tq.condition.notify.assert_called_once()

    async def test_resume_ws_exception_swallowed( self ):
        job = Mock(); job.user_id = "u1"
        tq = MagicMock(); tq.get_by_id_hash.return_value = job
        mock_main = Mock()
        ws = Mock(); ws.emit_to_user_and_admins_sync.side_effect = Exception( "ws" )
        mock_main.websocket_manager = ws
        with _patch_fastapi_main( mock_main ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value="t" ), patch( "builtins.print" ):
            out = await resume_job( job_id="j", current_user=self.user, todo_queue=tq )
        self.assertEqual( out[ "status" ], "resumed" )


class TestResumeFromCheckpoint( unittest.IsolatedAsyncioTestCase ):
    """Coverage for POST /api/jobs/{id_hash}/resume-from-checkpoint."""

    async def test_not_resumable_404( self ):
        with patch( "cosa.rest.agentic_job_factory.resume_job", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await resume_stalled_job( id_hash="h", request=ResumeFromCheckpointRequest(),
                                          current_user={ "uid": "u1", "email": "e" }, todo_queue=Mock() )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_success_with_overrides( self ):
        job = Mock()
        job.id_hash = "new-h"
        job._resume_checkpoint = { "phase_ordinal": 2, "phase_name": "plan", "resume_count": 3 }
        tq = Mock()
        with patch( "cosa.rest.agentic_job_factory.resume_job", return_value=job ) as rj, \
             patch( "builtins.print" ):
            req = ResumeFromCheckpointRequest( thinking_effort="high" )
            out = await resume_stalled_job( id_hash="h", request=req,
                                            current_user={ "uid": "u1", "email": "e" }, todo_queue=tq )
        tq.push.assert_called_once_with( job )
        self.assertEqual( out[ "status" ], "resumed" )
        self.assertEqual( out[ "resume_from_phase" ], 2 )
        # overrides forwarded (exclude_none → only thinking_effort)
        _, kwargs = rj.call_args
        self.assertEqual( kwargs[ "args_overrides" ], { "thinking_effort": "high" } )


class TestResumeTfeSmart( unittest.IsolatedAsyncioTestCase ):
    """Coverage for POST /api/test-fix-expediter/resume-from."""

    def _target( self, **kw ):
        t = Mock()
        t.source_type = kw.get( "source_type", "job_id" )
        t.job_id      = kw.get( "job_id", "tfe-1" )
        t.candidates  = kw.get( "candidates", None )
        t.diagnostic  = kw.get( "diagnostic", "ok" )
        t.matched_path = kw.get( "matched_path", "/p" )
        t.confidence   = kw.get( "confidence", 0.9 )
        return t

    async def test_no_email_400( self ):
        with self.assertRaises( HTTPException ) as ctx:
            await resume_tfe_smart( request=TFEResumeFromRequest( resume_from="x" ),
                                    current_user={ "uid": "u1" }, todo_queue=Mock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_not_found_404( self ):
        with patch( "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target",
                    return_value=self._target( source_type="not_found", job_id=None, diagnostic="no match" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await resume_tfe_smart( request=TFEResumeFromRequest( resume_from="x" ),
                                        current_user={ "uid": "u1", "email": "e@x.com" }, todo_queue=Mock() )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_ambiguous_returns_candidates( self ):
        tgt = self._target( job_id=None, candidates=[ "a", "b" ], diagnostic="multi" )
        with patch( "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target", return_value=tgt ):
            out = await resume_tfe_smart( request=TFEResumeFromRequest( resume_from="x" ),
                                          current_user={ "uid": "u1", "email": "e@x.com" }, todo_queue=Mock() )
        self.assertEqual( out[ "status" ], "ambiguous" )
        self.assertEqual( out[ "candidates" ], [ "a", "b" ] )

    async def test_resume_job_none_404( self ):
        tgt = self._target()
        with patch( "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target", return_value=tgt ), \
             patch( "cosa.rest.agentic_job_factory.resume_job", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await resume_tfe_smart( request=TFEResumeFromRequest( resume_from="x" ),
                                        current_user={ "uid": "u1", "email": "e@x.com" }, todo_queue=Mock() )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_success_with_user_email_key( self ):
        tgt = self._target()
        job = Mock(); job.id_hash = "new-h"
        job._resume_checkpoint = { "phase_ordinal": 1, "phase_name": "p", "resume_count": 1 }
        tq = Mock()
        with patch( "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target", return_value=tgt ), \
             patch( "cosa.rest.agentic_job_factory.resume_job", return_value=job ), \
             patch( "builtins.print" ):
            # current_user lacks "email" but has "user_email" → second .get() arm
            out = await resume_tfe_smart(
                request=TFEResumeFromRequest( resume_from="tfe-1", lead_model_override="claude-opus-4-7" ),
                current_user={ "uid": "u1", "user_email": "e@x.com" }, todo_queue=tq )
        tq.push.assert_called_once_with( job )
        self.assertEqual( out[ "status" ], "resumed" )
        self.assertEqual( out[ "resumed_job_id" ], "new-h" )


def isolated_unit_test():
    """
    Run the supplemental queues-router coverage suite in isolation.

    Ensures:
        - All external collaborators mocked (zero DB/net/LLM/GPU)
        - Deterministic, fast execution

    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    du.print_banner( "Queues Router — Supplemental Coverage Tests", prepend_nl=True )

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in (
        TestCountInteractions, TestPushValidation, TestPushAgentic, TestPoolStatus,
        TestGetQueueExtra, TestGetJobInteractions, TestSendJobMessage, TestCancelJob,
        TestDeleteAllQueueJobs, TestDeleteQueueJob, TestJobHistory, TestRetryJobHistory,
        TestPauseResume, TestResumeFromCheckpoint, TestResumeTfeSmart,
    ):
        suite.addTests( loader.loadTestsFromTestCase( cls ) )

    runner = unittest.TextTestRunner( verbosity=2, stream=sys.stdout )
    result = runner.run( suite )
    duration = time.time() - start_time

    success = result.wasSuccessful()
    msg = ( f"All {result.testsRun} tests passed in {duration:.3f}s" if success
            else f"{len( result.failures )} failures, {len( result.errors )} errors of {result.testsRun}" )
    du.print_banner( ( "✅ " if success else "❌ " ) + msg, prepend_nl=True )
    return success, duration, msg


if __name__ == "__main__":
    ok, dur, message = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} queues coverage suite in {dur:.3f}s: {message}" )
