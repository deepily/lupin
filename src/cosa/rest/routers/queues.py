"""
Queue management endpoints.

Provides REST API endpoints for managing COSA job queues including
pushing jobs to todo queue, retrieving queue contents with user filtering,
and resetting all queues.

Generated on: 2025-01-24
"""

import asyncio

from fastapi import APIRouter, Query, HTTPException, Depends, Request, Body
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Dict, Any, Optional, Literal

from pydantic import BaseModel

import cosa.utils.util as cu

from cosa.rest.routers._retired_doors import gone, tombstone_description

# Import dependencies
from cosa.rest.auth import get_current_user
from cosa.rest.queue_auth import authorize_queue_filter
from cosa.rest.auth_middleware import is_admin
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState
from cosa.rest.queue_util import emit_job_state_transition

router = APIRouter(prefix="/api", tags=["queues"])

# Global dependencies (temporary access via main module)
def get_todo_queue():
    """
    Dependency to get todo queue from main module.
    
    Requires:
        - lupin_app.main module is available
        - main_module has jobs_todo_queue attribute
        
    Ensures:
        - Returns the todo queue instance
        - Provides access to job queue management
        
    Raises:
        - ImportError if main module not available
        - AttributeError if todo queue not found
    """
    import lupin_app.main as main_module
    return main_module.jobs_todo_queue

def get_running_queue():
    """
    Dependency to get running queue from main module.
    
    Requires:
        - lupin_app.main module is available
        - main_module has jobs_run_queue attribute
        
    Ensures:
        - Returns the running queue instance
        - Provides access to active job tracking
        
    Raises:
        - ImportError if main module not available
        - AttributeError if running queue not found
    """
    import lupin_app.main as main_module
    return main_module.jobs_run_queue

def get_done_queue():
    """
    Dependency to get done queue from main module.
    
    Requires:
        - lupin_app.main module is available
        - main_module has jobs_done_queue attribute
        
    Ensures:
        - Returns the done queue instance
        - Provides access to completed job tracking
        
    Raises:
        - ImportError if main module not available
        - AttributeError if done queue not found
    """
    import lupin_app.main as main_module
    return main_module.jobs_done_queue

def get_dead_queue():
    """
    Dependency to get dead queue from main module.
    
    Requires:
        - lupin_app.main module is available
        - main_module has jobs_dead_queue attribute
        
    Ensures:
        - Returns the dead queue instance
        - Provides access to failed job tracking
        
    Raises:
        - ImportError if main module not available
        - AttributeError if dead queue not found
    """
    import lupin_app.main as main_module
    return main_module.jobs_dead_queue

def get_notification_queue():
    """
    Dependency to get notification queue from main module.
    
    Requires:
        - lupin_app.main module is available
        - main_module has jobs_notification_queue attribute
        
    Ensures:
        - Returns the notification queue instance
        - Provides access to notification management
        
    Raises:
        - ImportError if main module not available
        - AttributeError if notification queue not found
    """
    import lupin_app.main as main_module
    return main_module.jobs_notification_queue

def _count_interactions_for_jobs( job_ids ):
    """
    Bulk-count non-hidden notifications grouped by job_id for the supplied list.

    Used by the done- and dead-bucket handlers to populate `has_interactions`
    accurately (replacing the old `bool(job.session_id)` proxy that gave false
    positives whenever a job had a session but no notifications).

    Single batched query against the indexed notifications.job_id column.

    Requires:
        - job_ids: list of job_id strings (may be empty)

    Ensures:
        - Returns dict mapping each input job_id to its non-hidden notification count
        - Empty input returns {} without issuing a query
        - Returns {} on database failure (logged) — caller treats as all-zero counts
    """
    if not job_ids:
        return {}

    try:
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.notification_repository import NotificationRepository

        with get_db() as session:
            repo = NotificationRepository( session )
            return repo.count_by_job_ids( job_ids )
    except Exception as e:
        print( f"[WARN] _count_interactions_for_jobs failed: {e}" )
        return {}


# ── TOMBSTONE — /api/push ──
#   GONE. Work now enters through /api/v2/ask. REMOVE BY 2026-12-31.
#   What was here: a handler that took a bare question and handed it to push_job.
#   Why that was bad: eighteen doors into one queue meant eighteen places a guard
#   would have to be installed, and the read guard could not cover them all. Rick,
#   2026-08-21: ONE entry point, and it is v2.
#   The body is DELETED rather than left unreachable below a raise: unreachable code
#   is code nobody can test and everybody must still read. Recover it from git if any
#   of its handling turns out to be worth carrying into /api/v2/ask.
@router.post(
    "/push",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/ask",
    description = tombstone_description( "/api/push" )
)
async def push():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/ask
          and the REMOVE BY 2026-12-31 date
    """
    gone( "/api/push" )


# ── TOMBSTONE — /api/push-agentic ──
#
#   What was here: the unattended, service-to-service twin of /api/push. The caller
#   supplied a routing_command and a fully-specified args dict, and it went straight to
#   the queue with no expeditor, no LORA parsing and no interactive Q&A — deliberately,
#   because an unattended submitter cannot answer a question.
#
#   WHY THIS ONE IS THE EASIEST OF THE NINE, AND WHY THAT IS WORTH SAYING. Every other
#   retired door named its own command and had to be told which one it was. This door
#   already took the command as a parameter, which is exactly the shape of
#   /api/v2/submit — a command string, an args dict, and the queue directives beside
#   them. It was not a door that needed converting; it was /api/v2/submit with a
#   different name and a worse contract.
#
#     POST /api/v2/submit
#     { "command": "agent router go to deep research",
#       "args"   : { "query": "..." },
#       "question": "...", "websocket_id": "...",
#       "scheduled_at": null, "monopolize": false }
#
#   The renames a caller has to make, stated so nobody has to diff two schemas:
#   `routing_command` becomes `command`, and `websocket_id` — required here — is
#   optional there. `args`, `question`, `scheduled_at` and `monopolize` keep their names
#   and their meanings, and `parent_id_hash` is available now where it was not before.
#
#   The 400s this door raised by hand are not lost, they are Pydantic's now: a missing
#   or non-string command, a non-object args, a body that is not a JSON object. It
#   validated those itself because it read the raw request; SubmitRequest is a model.
#
#   WARNING: `todo_queue.push_job_agentic` HAS NO PRODUCTION CALLER AFTER THIS COMMIT —
#   this door was its only one. That is the same state `push_job` reached at the end of
#   the cutover, and it is recorded here rather than acted on: pinning it as dead is its
#   own piece of work, the way 6c was for push_job, and the method's own coverage still
#   stands under the unit suite.
#
#   The body is DELETED rather than left unreachable below a raise: unreachable code is
#   code nobody can test and everybody must still read.
@router.post(
    "/push-agentic",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/submit",
    description = tombstone_description( "/api/push-agentic" )
)
async def push_agentic():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit
          and the REMOVE BY 2026-12-31 date
    """
    gone( "/api/push-agentic" )


@router.get(
    "/queue/pool-status",
    summary     = "CJ Flow agentic-pool state",
    description = "Returns inflight/pending counts and max workers for the agentic ThreadPoolExecutor. Phase 2 (v0.1.7 CJ Flow async multi-lane)."
)
async def get_pool_status(
    current_user: dict = Depends( get_current_user ),
    running_queue = Depends( get_running_queue )
):
    """
    Return CJ Flow agentic-pool state.

    Requires:
        - Authenticated user (Depends(get_current_user))
        - running_queue initialized at server startup

    Ensures:
        - Returns dict with keys inflight_agentic_jobs, max_agentic_workers, pending_in_pool
        - Phase 2 semantics: inflight = submitted-but-not-done (running + pending);
          pending = queued inside pool's internal queue, not yet picked up by a worker;
          UI "running" count = inflight - pending
    """
    return running_queue.get_pool_status()


@router.get(
    "/get-queue/{queue_name}",
    summary     = "Get queue contents",
    description = "Retrieve jobs from a named queue (todo/run/done/dead) with role-based user filtering."
)
async def get_queue(
    queue_name: str,
    current_user: dict = Depends(get_current_user),
    user_filter: Optional[str] = Query(
        None,
        description="User filter: omit for self, '*' for all (admin), or specific user_id (admin)",
        example="ricardo_felipe_ruiz_6bdc"
    ),
    todo_queue = Depends(get_todo_queue),
    running_queue = Depends(get_running_queue),
    done_queue = Depends(get_done_queue),
    dead_queue = Depends(get_dead_queue)
):
    """
    Retrieve jobs from queue with role-based user filtering.

    **PHASE 1 IMPLEMENTATION:** User-filtered queue views with role-based access control

    Authorization Rules:
    - Regular users: Can ONLY query their own jobs (user_filter ignored or must match self)
    - Admin users: Can query own, specific user's, or all users' jobs

    Query Parameters:
        - user_filter: Optional[str]
            - None (omit): Current user's jobs (default for all users)
            - "*": ALL users' jobs (admin only)
            - "user_id_xyz": Specific user's jobs (admin only)

    Requires:
        - queue_name is one of: 'todo', 'run', 'done', 'dead'
        - current_user is authenticated with valid token containing uid
        - All queue objects (todo, running, done, dead) are initialized

    Ensures:
        - Retrieves jobs from specified queue filtered by user
        - Applies appropriate sorting (descending for todo/done/dead, ascending for run)
        - Returns queue-specific job arrays in expected format
        - Raises 400 for invalid queue names
        - Raises 403 if regular user attempts admin operations

    Raises:
        - HTTPException 400: Invalid queue_name parameter
        - HTTPException 403: Unauthorized user filter access
        - HTTPException 401: Authentication fails

    Args:
        queue_name: The queue to retrieve ('todo'|'run'|'done'|'dead')
        current_user: Authenticated user info from token
        user_filter: Optional filter (None=self, "*"=all, or user_id)
        todo_queue: Todo queue dependency
        running_queue: Running queue dependency
        done_queue: Done queue dependency
        dead_queue: Dead queue dependency

    Returns:
        dict: Queue data with job arrays, metadata, and filtering info
    """

    # Step 1: Authorize the filter request
    try:
        authorized_filter = authorize_queue_filter(
            current_user=current_user,
            filter_user_id=user_filter
        )
    except HTTPException:
        raise  # Re-raise authorization failures

    # Step 2: Map queue name to queue object
    queue_map = {
        "todo": todo_queue,
        "run": running_queue,
        "done": done_queue,
        "dead": dead_queue
    }

    if queue_name not in queue_map:
        raise HTTPException(status_code=400, detail=f"Invalid queue name: {queue_name}")

    queue = queue_map[queue_name]

    # Step 3: Retrieve jobs based on authorized filter
    if authorized_filter == "*":
        # Admin requesting ALL users' jobs
        jobs = queue.get_all_jobs()
    elif authorized_filter.startswith( "!" ):
        # Admin requesting all jobs EXCEPT their own ("!user_id" sentinel)
        jobs = queue.get_jobs_excluding_user( authorized_filter[ 1: ] )
    else:
        # Specific user's jobs (could be self or other for admin)
        jobs = queue.get_jobs_for_user( authorized_filter )

    # Step 4: Apply queue-specific sorting
    descending = queue_name in ["todo", "done", "dead"]
    if descending:
        jobs.reverse()

    # Step 5: Handle done queue special case (metadata + HTML)
    if queue_name == "done":
        # Bulk-count notifications for accurate has_interactions per job (single
        # batched query against the indexed notifications.job_id column —
        # replaces the bool(job.session_id) proxy that gave false positives).
        notif_counts = _count_interactions_for_jobs( [ j.id_hash for j in jobs ] )

        # Extract structured job data from SolutionSnapshot or AgenticJobBase objects
        structured_jobs = []
        for job in jobs:
            # Phase 3: Explicit type check replaces duck typing hasattr() checks
            is_agentic_job = isinstance( job, AgenticJobBase )

            # Generate job metadata using unified interface properties
            # All job types now have: job_type, question, last_question_asked, answer,
            # answer_conversational, run_date, created_date, session_id
            job_data = {
                "job_id"          : job.id_hash,
                "question_text"   : job.last_question_asked,
                "response_text"   : job.answer_conversational or job.answer,
                "timestamp"       : job.run_date or job.created_date,
                "user_id"         : authorized_filter,
                "user_email"      : job.user_email,
                "session_id"      : job.session_id,  # For job-notification correlation
                "agent_type"      : job.job_type,  # Unified property replaces getattr() chain
                "has_interactions": notif_counts.get( job.id_hash, 0 ) > 0,  # Real count from notifications table
                "has_audio_cache" : False,  # Will be determined by frontend cache check
                "is_cache_hit"    : job.is_cache_hit,  # For Time Saved Dashboard
                # Phase 7: Agentic job artifacts for enhanced done cards
                "report_path"               : job.artifacts.get( 'report_path' ) if is_agentic_job else None,
                "remediation_snapshot_path" : job.artifacts.get( 'remediation_snapshot_path' ) if is_agentic_job else None,
                "yaml_path"                : job.artifacts.get( 'yaml_path' ) if is_agentic_job else None,
                "pptx_path"                : job.artifacts.get( 'pptx_path' ) if is_agentic_job else None,
                "abstract"        : job.artifacts.get( 'abstract' ) if is_agentic_job else None,
                "cost_summary"    : job.cost_summary if is_agentic_job else None,
                "started_at"      : job.started_at,
                "completed_at"    : job.completed_at,
                "status"          : job.state.value if hasattr( job.state, 'value' ) else str( job.state ),
                "error"           : job.error,
                "scheduled_at"    : getattr( job, 'scheduled_at', None ),
                "monopolize"      : getattr( job, 'monopolize', False ),
                "paused"          : job.state == JobState.PAUSED,
            }

            # Calculate duration for agentic jobs
            if is_agentic_job and job_data[ "started_at" ] and job_data[ "completed_at" ]:
                try:
                    start = datetime.fromisoformat( job_data[ "started_at" ] )
                    end   = datetime.fromisoformat( job_data[ "completed_at" ] )
                    job_data[ "duration_seconds" ] = ( end - start ).total_seconds()
                except Exception:
                    job_data[ "duration_seconds" ] = None
            else:
                job_data[ "duration_seconds" ] = None

            structured_jobs.append( job_data )

        # Return structured metadata (HTML field deprecated - frontend uses metadata exclusively)
        return {
            f"{queue_name}_jobs_metadata": structured_jobs,
            "filtered_by": authorized_filter,
            "is_admin_view": is_admin( current_user ) and ( user_filter is not None ),
            "total_jobs": len( structured_jobs )
        }

    # Step 5b: Handle dead queue — surface partial artifacts from failed-
    # before-completion runs so users can recover diagnoses/plans that the
    # job computed before dying. Previously fell through to the generic
    # todo/run branch which only returned basic fields; dead TFE/BFE jobs
    # that wrote a Phase 2 plan had no way to surface it to the UI.
    # See: src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md (Fix 8b)
    if queue_name == "dead":
        # Same bulk-count pattern as done bucket — accurate has_interactions
        notif_counts = _count_interactions_for_jobs( [ j.id_hash for j in jobs ] )

        structured_jobs = []
        for job in jobs:
            is_agentic_job = isinstance( job, AgenticJobBase )
            job_data = {
                "job_id"          : job.id_hash,
                "question_text"   : job.last_question_asked,
                "timestamp"       : job.run_date or job.created_date,
                "user_id"         : authorized_filter,
                "user_email"      : job.user_email,
                "session_id"      : job.session_id,
                "agent_type"      : job.job_type,
                "status"          : job.state.value if hasattr( job.state, 'value' ) else str( job.state ),
                "started_at"      : job.started_at,
                "completed_at"    : job.completed_at,
                "error"           : job.error,
                "is_cache_hit"    : False,
                "has_interactions": notif_counts.get( job.id_hash, 0 ) > 0,
                "scheduled_at"    : getattr( job, 'scheduled_at', None ),
                "monopolize"      : getattr( job, 'monopolize', False ),
                "paused"          : job.state == JobState.PAUSED,
                # Partial artifacts from failed-before-completion runs.
                # Agents that died mid-pipeline may have populated any of these.
                "plan_path"                : job.artifacts.get( 'plan_path' )                if is_agentic_job else None,
                "remediation_snapshot_path": job.artifacts.get( 'remediation_snapshot_path' ) if is_agentic_job else None,
                "report_path"              : job.artifacts.get( 'report_path' )              if is_agentic_job else None,
                "yaml_path"                : job.artifacts.get( 'yaml_path' )                if is_agentic_job else None,
                "cost_summary"             : job.cost_summary                                 if is_agentic_job else None,
            }
            # Calculate duration for agentic jobs when both timestamps exist
            if is_agentic_job and job_data[ "started_at" ] and job_data[ "completed_at" ]:
                try:
                    start = datetime.fromisoformat( job_data[ "started_at" ] )
                    end   = datetime.fromisoformat( job_data[ "completed_at" ] )
                    job_data[ "duration_seconds" ] = ( end - start ).total_seconds()
                except Exception:
                    job_data[ "duration_seconds" ] = None
            else:
                job_data[ "duration_seconds" ] = None

            structured_jobs.append( job_data )

        return {
            f"{queue_name}_jobs_metadata": structured_jobs,
            "filtered_by" : authorized_filter,
            "is_admin_view": is_admin( current_user ) and ( user_filter is not None ),
            "total_jobs"  : len( structured_jobs ),
        }

    # Step 6: Handle todo/run queues with metadata (Phase 7)
    # Using unified interface properties - all job types now have consistent attributes
    structured_jobs = []
    for job in jobs:
        job_data = {
            "job_id"       : job.id_hash,
            "question_text": job.last_question_asked,
            "timestamp"    : job.run_date or job.created_date,
            "user_id"      : authorized_filter,
            "user_email"   : job.user_email,
            "session_id"   : job.session_id,
            "agent_type"   : job.job_type,  # Unified property replaces getattr() chain
            "status"       : job.state.value if hasattr( job.state, 'value' ) else str( job.state ),
            "started_at"   : job.started_at,
            "error"        : job.error,
            "scheduled_at" : getattr( job, 'scheduled_at', None ),
            "monopolize"   : getattr( job, 'monopolize', False ),
            "paused"       : job.state == JobState.PAUSED,
        }
        structured_jobs.append( job_data )

    # Return structured metadata (HTML field deprecated - frontend uses metadata exclusively)
    is_admin_override = is_admin( current_user ) and ( user_filter is not None )

    return {
        f"{queue_name}_jobs_metadata": structured_jobs,
        "filtered_by": authorized_filter,
        "is_admin_view": is_admin_override,
        "total_jobs": len( structured_jobs )
    }

@router.post(
    "/reset-queues",
    summary     = "Reset all queues",
    description = "Clear all five queues (todo, run, done, dead, notification) and return items-cleared summary."
)
async def reset_queues(
    current_user: dict = Depends(get_current_user),
    todo_queue = Depends(get_todo_queue),
    running_queue = Depends(get_running_queue),
    done_queue = Depends(get_done_queue),
    dead_queue = Depends(get_dead_queue),
    notification_queue = Depends(get_notification_queue)
):
    """
    Reset all queues by clearing their contents.
    
    Requires:
        - User must be authenticated with valid token
        - All queue instances must be available
        
    Ensures:
        - All queues are emptied
        - WebSocket notifications are sent for queue updates
        - Returns summary of reset operation
        
    Returns:
        dict: Summary of queues reset with counts and timestamp
    """
    user_id = current_user["uid"]
    print( f"[API] /api/reset-queues called by user: {user_id}" )
    
    # Get initial counts for reporting
    initial_counts = {
        "todo": todo_queue.size(),
        "run": running_queue.size(),
        "done": done_queue.size(),
        "dead": dead_queue.size(),
        "notification": notification_queue.size()
    }
    
    try:
        # Clear all queues (they will automatically emit updates)
        todo_queue.clear()
        running_queue.clear()
        done_queue.clear()
        dead_queue.clear()
        notification_queue.clear()
        
        result = {
            "status": "success",
            "message": "All queues have been reset",
            "user_id": user_id,
            "timestamp": cu.get_current_datetime_iso(),
            "queues_reset": {
                "todo": f"cleared {initial_counts['todo']} items",
                "run": f"cleared {initial_counts['run']} items", 
                "done": f"cleared {initial_counts['done']} items",
                "dead": f"cleared {initial_counts['dead']} items",
                "notification": f"cleared {initial_counts['notification']} items"
            },
            "total_items_cleared": sum( initial_counts.values() )
        }
        
        print( f"[API] Successfully reset all queues - cleared {result['total_items_cleared']} total items" )
        return result
        
    except Exception as e:
        print( f"[ERROR] Failed to reset queues: {e}" )
        raise HTTPException( status_code=500, detail=f"Failed to reset queues: {str(e)}" )


@router.get(
    "/get-job-interactions/{job_id}",
    summary     = "Get job interactions",
    description = "Retrieve notification interaction history for a job with progress deduplication."
)
async def get_job_interactions(
    job_id: str,
    current_user: dict = Depends( get_current_user ),
    todo_queue    = Depends( get_todo_queue ),
    running_queue = Depends( get_running_queue ),
    done_queue    = Depends( get_done_queue )
):
    """
    Get notification interaction history for a completed job.

    Requires:
        - job_id is a valid job identifier
        - current_user is authenticated
        - Job belongs to current user OR user is admin

    Ensures:
        - Returns job metadata + interaction history
        - Interactions ordered newest-first
        - Returns empty interactions list if job has no session_id

    Returns:
        dict: {job_id, session_id, job_metadata, interactions: [...]}
    """
    from datetime import timezone, timedelta
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.notification_repository import NotificationRepository
    from cosa.rest.db.repositories.user_repository import UserRepository
    from cosa.rest.postgres_models import Notification

    print( f"[API] /api/get-job-interactions/{job_id} called by user: {current_user['uid']}" )

    # Find job across all queues (running, done, todo) by compound ID
    job = None
    for queue in [ running_queue, done_queue, todo_queue ]:
        for snapshot in queue.get_all_jobs():
            if snapshot.id_hash == job_id:
                job = snapshot
                break
        if job:
            break

    # DB fallback when job not found in in-memory queues
    db_job = None
    if not job:
        from cosa.rest.job_persistence import get_job_by_id_hash
        db_job = get_job_by_id_hash( job_id )
        if not db_job:
            print( f"[API] Job not found in any queue or DB: {job_id}" )
            raise HTTPException( status_code=404, detail=f"Job not found: {job_id}" )
        print( f"[API] Job {job_id} found in DB (not in memory)" )

    # Authorization check — db_job is a dict, job is an object
    if job:
        job_owner = job.user_id
    else:
        job_owner = db_job.get( "user_id" )
    if job_owner and job_owner != current_user["uid"] and not is_admin( current_user ):
        print( f"[API] Unauthorized access to job {job_id} by {current_user['uid']}" )
        raise HTTPException( status_code=403, detail="Not authorized to view this job" )

    # Build response from in-memory job or DB fallback
    if job:
        response = {
            "job_id"       : job_id,
            "session_id"   : job.session_id,
            "job_metadata" : {
                "question"    : job.last_question_asked,
                "answer"      : job.answer_conversational or job.answer,
                "agent_type"  : job.job_type,
                "run_date"    : job.run_date,
                "created_date": job.created_date
            },
            "interactions"      : [],
            "interaction_count" : 0
        }
    else:
        metadata   = db_job.get( "metadata_json" ) or {}
        created_at = db_job.get( "created_at" )
        response = {
            "job_id"       : job_id,
            "session_id"   : db_job.get( "session_id" ),
            "job_metadata" : {
                "question"    : db_job.get( "question_text" ),
                "answer"      : metadata.get( "answer_conversational" ) or metadata.get( "response_text" ),
                "agent_type"  : db_job.get( "job_type" ),
                "run_date"    : created_at.isoformat() if hasattr( created_at, "isoformat" ) else created_at,
                "created_date": created_at.isoformat() if hasattr( created_at, "isoformat" ) else created_at
            },
            "interactions"      : [],
            "interaction_count" : 0
        }

    # Query notifications by job_id (direct lookup - much simpler than time-window)
    try:
        with get_db() as db:
            print( f"[API] Querying notifications for job_id={job_id}" )

            notifications = db.query( Notification ).filter(
                Notification.job_id == job_id
            ).order_by( Notification.created_at.desc() ).all()

            # Deduplicate progress groups: keep only latest per progress_group_id
            # Notifications are ordered newest-first, so first occurrence is latest
            seen_groups = set()
            deduped     = []
            for n in notifications:
                if n.progress_group_id:
                    if n.progress_group_id in seen_groups:
                        continue
                    seen_groups.add( n.progress_group_id )
                deduped.append( n )

            response["interactions"] = [
                {
                    "id"                 : str( n.id ),
                    "type"               : n.type,
                    "message"            : n.message,
                    "timestamp"          : n.created_at.isoformat(),
                    "response_requested" : n.response_requested,
                    "response_value"     : n.response_value,
                    "priority"           : n.priority,
                    "abstract"           : n.abstract
                }
                for n in deduped
            ]
            response["interaction_count"] = len( deduped )

            print( f"[API] Found {len( notifications )} interactions for job {job_id}" )

    except Exception as e:
        print( f"[API] Error querying notifications: {e}" )
        # Return empty interactions rather than failing
        pass

    return response


@router.post(
    "/jobs/{job_id}/message",
    summary     = "Send message to job",
    description = "Send a user-initiated message to a running agentic job via WebSocket notification."
)
async def send_job_message(
    job_id: str,
    request: Request,
    current_user: dict = Depends( get_current_user ),
    running_queue = Depends( get_running_queue ),
):
    """
    Send a user message to a running SWE Team job.

    Creates a notification with type="user_initiated_message" targeting the
    specified job_id. The job's orchestrator notification client receives this
    via WebSocket and queues it for consumption at the next check-in point.

    Requires:
        - job_id identifies a currently running job
        - request body contains {"message": str, "priority": "normal"|"urgent"}
        - current_user is authenticated

    Ensures:
        - Notification created in database with user_initiated_message type
        - WebSocket event emitted to job owner for delivery
        - Returns notification_id on success

    Raises:
        - HTTPException 400: Missing or invalid request body
        - HTTPException 404: Job not found in running queue
        - HTTPException 403: User does not own this job

    Args:
        job_id: Target running job ID
        request: FastAPI request with JSON body
        current_user: Authenticated user info
        running_queue: Running queue dependency

    Returns:
        dict: {status, notification_id, job_id}
    """
    # Parse request body
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException( status_code=400, detail=f"Invalid JSON: {e}" )

    message_text = body.get( "message", "" ).strip()
    priority     = body.get( "priority", "normal" )

    if not message_text:
        raise HTTPException( status_code=400, detail="Message cannot be empty" )

    if priority not in ( "normal", "urgent" ):
        raise HTTPException( status_code=400, detail="Priority must be 'normal' or 'urgent'" )

    user_id = current_user[ "uid" ]

    print( f"[API] POST /api/jobs/{job_id}/message - user: {user_id}, priority: {priority}" )

    # Validate job exists and is running
    try:
        job = running_queue.get_by_id_hash( job_id )
    except KeyError:
        raise HTTPException( status_code=404, detail=f"Job not found or not running: {job_id}" )

    # Validate user owns this job
    if job.user_id != user_id and not is_admin( current_user ):
        raise HTTPException( status_code=403, detail="Not authorized to message this job" )

    # Create notification record
    try:
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.notification_repository import NotificationRepository
        from cosa.rest.db.repositories.user_repository import UserRepository

        with get_db() as db:
            user_repo = UserRepository( db )
            user = user_repo.get_by_email( current_user[ "email" ] )

            if not user:
                raise HTTPException( status_code=404, detail="User not found" )

            notif_repo = NotificationRepository( db )
            notification = notif_repo.create_notification(
                sender_id          = f"user@{current_user[ 'email' ]}",
                recipient_id       = user.id,
                message            = message_text,
                type               = "user_initiated_message",
                priority           = priority,
                response_requested = False,
                job_id             = job_id,
            )
            db.commit()

            notification_id = str( notification.id )
            user_id_db      = user.id

    except HTTPException:
        raise
    except Exception as e:
        print( f"[API] Error creating notification: {e}" )
        raise HTTPException( status_code=500, detail=f"Failed to create notification: {e}" )

    # Emit WebSocket event to deliver to orchestrator's notification client
    try:
        import lupin_app.main as main_module
        ws_manager = main_module.websocket_manager

        # Phase D migration (2026-04-27): use the canonical dispatch helper.
        # Pre-migration this site had two separate emit calls — one
        # emit_to_user_sync to deliver to the human's browser, plus a
        # cross-user emit_to_session_sync to deliver to cc-listener-{job_id}.
        # The helper unifies the pattern; both still fire when both targets
        # are reachable. CC listeners authenticate as a shared service-account
        # user_id, so they only receive cross-user delivery via the listener
        # session-id branch — that's what the helper handles internally.
        ws_manager.emit_to_user_or_listener_sync(
            user_id = user_id,
            job_id  = job_id,
            event   = "notification_queue_update",
            data    = {
                "notification": {
                    "id"                : notification_id,
                    "id_hash"           : notification_id,
                    "type"              : "user_initiated_message",
                    "notification_type" : "user_initiated_message",
                    "message"           : message_text,
                    "priority"          : priority,
                    "job_id"            : job_id,
                    "sender_id"         : f"user@{current_user[ 'email' ]}",
                    "timestamp"         : cu.get_current_datetime_iso(),
                },
            },
        )

        # Echo acknowledgment back to user as a progress notification
        # Persist to database so it appears in job interaction history
        echo_message = "📨 Your message has been queued"

        try:
            with get_db() as db2:
                notif_repo2 = NotificationRepository( db2 )
                echo_notif  = notif_repo2.create_notification(
                    sender_id          = f"swe.lead@lupin",
                    recipient_id       = user_id_db,
                    message            = echo_message,
                    type               = "progress",
                    priority           = "low",
                    response_requested = False,
                    job_id             = job_id,
                )
                db2.commit()
                echo_id = str( echo_notif.id )
        except Exception as echo_err:
            print( f"[API] Warning: Echo persistence failed (non-fatal): {echo_err}" )
            echo_id = f"echo-{notification_id}"

        echo_data = {
            "notification": {
                "id"                : echo_id,
                "id_hash"           : echo_id,
                "type"              : "progress",
                "notification_type" : "progress",
                "message"           : echo_message,
                "priority"          : "low",
                "job_id"            : job_id,
                "sender_id"         : f"swe.lead@lupin",
                "timestamp"         : cu.get_current_datetime_iso(),
            },
        }
        ws_manager.emit_to_user_sync( user_id=user_id, event="notification_queue_update", data=echo_data )

    except Exception as e:
        print( f"[API] Warning: WebSocket emission failed (message still persisted): {e}" )

    print( f"[API] User message delivered to job {job_id}: {message_text[ :80 ]}" )

    return {
        "status"          : "delivered",
        "notification_id" : notification_id,
        "job_id"          : job_id,
    }


def _emit_job_removed( user_id, job_id, queue_name ):
    """
    Tell the owner and any watching admins that a job card is gone.

    Best-effort: a websocket problem must never turn a completed queue mutation
    into a failed request, so every failure is logged and swallowed.

    Requires:
        - user_id, job_id and queue_name are strings

    Ensures:
        - Emits a job_removed event, or logs and returns on any failure
        - Never raises
    """
    try:
        import lupin_app.main as main_module
        ws_manager = main_module.websocket_manager
        if ws_manager:
            ws_manager.emit_to_user_and_admins_sync( user_id, 'job_removed', {
                'job_id'    : job_id,
                'queue'     : queue_name,
                'timestamp' : cu.get_current_datetime_iso()
            } )
    except Exception as e:
        print( f"[API] Warning: Failed to emit job_removed event: {e}" )


@router.post(
    "/jobs/{job_id}/cancel",
    summary     = "Cancel a queued or running job",
    description = "Cancel a job whether it has started or not. A job still waiting in the "
                  "todo queue is removed outright; a running agentic job is asked to stop "
                  "gracefully at its next phase boundary."
)
async def cancel_job(
    job_id: str,
    current_user: dict = Depends( get_current_user ),
    running_queue = Depends( get_running_queue ),
    todo_queue    = Depends( get_todo_queue ),
):
    """
    Cancel a job in either of the two states a caller can meaningfully cancel from.

    The running queue is consulted first, so a job that has already started is
    stopped gracefully rather than yanked out from under itself. If it has not
    started, it is removed from the todo queue — that covers every pre-running
    state, because a scheduled job sits in todo carrying a `scheduled_at` it is
    simply not yet eligible against; there is no separate scheduled queue.

    Row 4b87fe61: this endpoint used to look only in the running queue, so the
    cheapest and safest moment to cancel — before any work has been done — was the
    one moment it refused, with a 404 that read as "no such job".

    Requires:
        - current_user is authenticated
        - Job belongs to current user OR user is admin

    Ensures:
        - A queued job is removed from the todo queue and a job_removed event
          is emitted; returns status="cancelled"
        - A running agentic job has its cancel flag set and stops at its next
          checkpoint; returns status="cancel_requested"
        - A 404 says which states were searched, so it can never be mistaken for
          "the job exists but has not started"

    Raises:
        - HTTPException 404: No job with this id is queued or running
        - HTTPException 403: User does not own this job and is not admin
        - HTTPException 400: Running job type does not support graceful cancellation
        - HTTPException 409: The job was found in todo but the delete did not take

    Args:
        job_id: Target job ID
        current_user: Authenticated user info
        running_queue: Running queue dependency
        todo_queue: Todo queue dependency

    Returns:
        dict: {status, job_id, queue, message}
    """
    user_id = current_user[ "uid" ]

    print( f"[API] POST /api/jobs/{job_id}/cancel - user: {user_id}" )

    # Running first — a started job gets a graceful stop, not a yank
    try:
        job = running_queue.get_by_id_hash( job_id )
    except KeyError:
        job = None

    if job is not None:

        if job.user_id != user_id and not is_admin( current_user ):
            raise HTTPException( status_code=403, detail="Not authorized to cancel this job" )

        if not isinstance( job, AgenticJobBase ):
            raise HTTPException(
                status_code = 400,
                detail      = f"Job {job_id} is already running and its type does not support graceful "
                              f"cancellation. To stop it anyway, use DELETE /api/queue/run/{job_id} — "
                              f"that removes it immediately and loses its work."
            )

        job.request_cancel()

        print( f"[API] Cancel requested for running job {job_id} by user {user_id}" )

        return {
            "status"  : "cancel_requested",
            "job_id"  : job_id,
            "queue"   : "run",
            "message" : "Cancellation requested. Job will stop at next checkpoint.",
        }

    # Not started yet — the cheap case, and the one this endpoint used to refuse
    try:
        job = todo_queue.get_by_id_hash( job_id )
    except KeyError:
        raise HTTPException(
            status_code = 404,
            detail      = f"No job with id {job_id} is queued or running. It may have already "
                          f"finished, or the id may be wrong."
        )

    if job.user_id != user_id and not is_admin( current_user ):
        raise HTTPException( status_code=403, detail="Not authorized to cancel this job" )

    if not todo_queue.delete_by_id_hash( job_id ):
        raise HTTPException(
            status_code = 409,
            detail      = f"Job {job_id} was queued a moment ago but could not be removed — it has "
                          f"most likely just started. Retry the cancel."
        )

    _emit_job_removed( user_id, job_id, "todo" )

    print( f"[API] Queued job {job_id} cancelled before starting, by user {user_id}" )

    return {
        "status"  : "cancelled",
        "job_id"  : job_id,
        "queue"   : "todo",
        "message" : "Job removed from the queue before it started. No work was lost.",
    }


@router.delete(
    "/queue/{queue_name}/all",
    summary     = "Delete all jobs from a queue",
    description = "Bulk remove all jobs from todo, run, done, or dead queue. "
                  "Admins clear the entire queue; regular users delete only their own jobs."
)
async def delete_all_queue_jobs(
    queue_name: str,
    current_user: dict = Depends( get_current_user ),
    running_queue      = Depends( get_running_queue ),
    done_queue         = Depends( get_done_queue ),
    dead_queue         = Depends( get_dead_queue ),
    todo_queue         = Depends( get_todo_queue ),
):
    """
    Bulk delete all jobs from an in-memory queue.

    For running jobs, signals cancellation on each before removal.
    Admins get a full queue.clear(); regular users get per-job deletion
    scoped to their own user_id (same auth model as single-job delete).

    Route-order note: this literal-path handler is declared BEFORE the
    parameterized `/queue/{queue_name}/{job_id}` sibling so FastAPI matches
    `/queue/done/all` here rather than binding `job_id="all"` and returning 404.

    Requires:
        - queue_name is one of: 'todo', 'run', 'done', 'dead'
        - current_user is authenticated

    Ensures:
        - All matching jobs removed from queue
        - Running jobs receive cancel signal before removal
        - Returns { status, queue_name, items_deleted, timestamp }

    Raises:
        - HTTPException 400: Invalid queue name
    """
    user_id = current_user[ "uid" ]

    queue_map = {
        "todo" : todo_queue,
        "run"  : running_queue,
        "done" : done_queue,
        "dead" : dead_queue
    }
    if queue_name not in queue_map:
        raise HTTPException( status_code=400, detail=f"Invalid queue name: {queue_name}. Must be 'todo', 'run', 'done', or 'dead'." )

    queue = queue_map[ queue_name ]

    print( f"[API] DELETE /api/queue/{queue_name}/all - user: {user_id}, admin: {is_admin( current_user )}" )

    if is_admin( current_user ):
        count = queue.size()
        queue.clear()
        items_deleted = count
    else:
        jobs = queue.get_jobs_for_user( user_id )
        items_deleted = 0
        for job in jobs:
            if queue_name == "run" and isinstance( job, AgenticJobBase ):
                job.request_cancel()
            deleted = queue.delete_by_id_hash( job.id_hash )
            if deleted:
                items_deleted += 1

    print( f"[API] Deleted {items_deleted} jobs from {queue_name} queue by user {user_id}" )

    return {
        "status"        : "deleted",
        "queue_name"    : queue_name,
        "items_deleted" : items_deleted,
        "timestamp"     : cu.get_current_datetime_iso()
    }


@router.delete(
    "/queue/{queue_name}/{job_id}",
    summary     = "Remove job from queue",
    description = "Forcefully remove a job from todo, run, done, or dead queue."
)
async def delete_queue_job(
    queue_name: str,
    job_id: str,
    current_user: dict = Depends( get_current_user ),
    running_queue = Depends( get_running_queue ),
    done_queue    = Depends( get_done_queue ),
    dead_queue    = Depends( get_dead_queue ),
    todo_queue    = Depends( get_todo_queue ),
):
    """
    Forcefully remove a job from an in-memory queue.

    For running jobs, also signals cancellation so the execution thread stops.
    For todo jobs, the underlying TodoFifoQueue.delete_by_id_hash wakes the
    consumer via condition.notify so it recalculates eligibility.
    Emits a job_removed WebSocket event so other connected clients update.

    Requires:
        - queue_name is one of: 'todo', 'run', 'done', 'dead'
        - job_id identifies an existing job in the specified queue
        - current_user is authenticated
        - Job belongs to current user OR user is admin

    Ensures:
        - Job is removed from the specified queue
        - Running jobs receive cancel signal before removal
        - WebSocket event emitted for UI synchronization
        - Returns confirmation with job_id and queue name

    Raises:
        - HTTPException 400: Invalid queue name
        - HTTPException 404: Job not found in specified queue
        - HTTPException 403: User does not own this job and is not admin

    Args:
        queue_name: Target queue ('todo', 'run', 'done', 'dead')
        job_id: Target job ID
        current_user: Authenticated user info
        running_queue: Running queue dependency
        done_queue: Done queue dependency
        dead_queue: Dead queue dependency
        todo_queue: Todo queue dependency

    Returns:
        dict: {status, job_id, queue}
    """
    user_id = current_user[ "uid" ]

    # Validate queue name
    queue_map = {
        "todo" : todo_queue,
        "run"  : running_queue,
        "done" : done_queue,
        "dead" : dead_queue
    }
    if queue_name not in queue_map:
        raise HTTPException( status_code=400, detail=f"Invalid queue name for deletion: {queue_name}. Must be 'todo', 'run', 'done', or 'dead'." )

    queue = queue_map[ queue_name ]

    print( f"[API] DELETE /api/queue/{queue_name}/{job_id} - user: {user_id}" )

    # Validate job exists
    try:
        job = queue.get_by_id_hash( job_id )
    except KeyError:
        raise HTTPException( status_code=404, detail=f"Job not found in {queue_name} queue: {job_id}" )

    # Validate ownership (user or admin)
    if job.user_id != user_id and not is_admin( current_user ):
        raise HTTPException( status_code=403, detail="Not authorized to remove this job" )

    # For running jobs: signal cancellation before removal
    if queue_name == "run" and isinstance( job, AgenticJobBase ):
        job.request_cancel()
        print( f"[API] Cancel signaled for running job {job_id} before removal" )

    # Remove from queue
    deleted = queue.delete_by_id_hash( job_id )
    if not deleted:
        raise HTTPException( status_code=404, detail=f"Failed to delete job {job_id} from {queue_name} queue" )

    # Emit WebSocket event for UI synchronization (canonical dual-emit:
    # owner + watching admins, deduplicated). See
    # WebSocketManager.emit_to_user_and_admins_sync for the rationale.
    _emit_job_removed( user_id, job_id, queue_name )

    print( f"[API] Job {job_id} removed from {queue_name} queue by user {user_id}" )

    return {
        "status" : "deleted",
        "job_id" : job_id,
        "queue"  : queue_name
    }


# ===========================================================================
# Job History (CJ Flow Persistence)
# ===========================================================================


@router.get(
    "/job-history",
    summary     = "Query job history",
    description = "Paginated history of agentic jobs from PostgreSQL persistence. "
                  "Admin sees all jobs; regular users see only their own. A `user_filter` "
                  "a regular user is not entitled to is REFUSED with 403, never ignored."
)
async def get_job_history(
    current_user: dict      = Depends( get_current_user ),
    status: Optional[str]   = Query( None, description="Filter by status: pending, running, completed, failed, interrupted" ),
    job_type: Optional[str] = Query( None, description="Filter by job type: deep_research, podcast, claude_code, swe_team, research_to_podcast" ),
    limit: int              = Query( 20, ge=1, le=100, description="Results per page (max 100)" ),
    offset: int             = Query( 0, ge=0, description="Pagination offset" ),
    days: Optional[int]     = Query( None, ge=1, le=365, description="Time window in days (e.g. 7, 14, 30). None = all time." ),
    exclude_ids: Optional[str] = Query( None, description="Comma-separated job IDs to exclude (for live queue deduplication)" ),
    user_filter: Optional[str] = Query(
        None,
        description="User filter: omit for the default view, '*' for all users (admin), or a specific user_id (admin). Same vocabulary and same 403 as /api/get-queue/{queue_name}.",
        example="ricardo_felipe_ruiz_6bdc"
    )
):
    """
    Query paginated job history with optional filters.

    🔴 WHY `user_filter` EXISTS HERE AT ALL (bug e205a3b1). It did not, and FastAPI
    DROPS an unknown query parameter silently — so `?user_filter=*` came back 200 with
    the caller's OWN rows and `filtered_by` still pinned to their uid. The sibling
    endpoint `/api/get-queue/{queue_name}` refuses the same request with a 403 naming
    the admin rule. Same permission model, two ways of saying no: one honest, one that
    hands the caller a partial view they believe is complete.

    MEASURED on 2026-08-17: two seats read the same `:8000` queue and got opposite
    answers — one saw two scheduled jobs, one saw none — because the rows belonged to
    a different account and nothing said so. The widening flag was passed and ignored.
    Accept-and-ignore is what turned a wrong flag into a confident wrong answer.

    Requires:
        - Authenticated user (Bearer token)

    Ensures:
        - Admin users see all jobs by default (user_id=None filter)
        - Regular users see only their own jobs by default
        - A `user_filter` the caller is not entitled to raises 403 — NEVER a silently
          narrowed 200
        - Results are paginated and sorted by created_at DESC
        - exclude_ids supports the overlay model: frontend passes live Done/Dead job IDs
          so they are excluded from history results (no duplicates)
        - Returns { jobs: [...], total: N, filtered_by: str, limit: N, offset: N }

    Raises:
        - HTTPException 403: caller is not entitled to the requested user_filter
        - HTTPException 400: '!self' — authorized for admins on the queue endpoint, but
          this store filters by user equality and cannot express exclusion. Refused
          loudly rather than answered with the wrong rows.
    """
    from cosa.rest.job_persistence import query_job_history

    if user_filter is None:
        # Unchanged default: admin sees all, regular user sees own only.
        user_id = None if is_admin( current_user ) else current_user[ "uid" ]
    else:
        # Raises 403 for a filter this caller is not entitled to — the whole point.
        authorized_filter = authorize_queue_filter(
            current_user   = current_user,
            filter_user_id = user_filter
        )

        if authorized_filter == "*":
            user_id = None
        elif authorized_filter.startswith( "!" ):
            # `query_job_history` filters on user_id EQUALITY; there is no exclusion
            # arm to hand "!uid" to, and passing it through would match no rows and
            # read as "no such jobs" — the exact failure this endpoint just got fixed
            # for. Refuse instead of answering wrongly.
            raise HTTPException(
                status_code = 400,
                detail      = "The '!self' filter is not supported by job history, which filters by user equality. Use '*' for all users."
            )
        else:
            user_id = authorized_filter

    # Parse comma-separated exclude_ids into a list
    exclude_list = [ eid.strip() for eid in exclude_ids.split( "," ) if eid.strip() ] if exclude_ids else None

    result = query_job_history(
        user_id     = user_id,
        status      = status,
        job_type    = job_type,
        limit       = limit,
        offset      = offset,
        days        = days,
        exclude_ids = exclude_list
    )

    return {
        "jobs"        : result[ "jobs" ],
        "total"       : result[ "total" ],
        "filtered_by" : user_id or "all",
        "limit"       : limit,
        "offset"      : offset
    }


@router.get(
    "/job-history/{job_id}",
    summary     = "Get job detail",
    description = "Retrieve a single job's full history record by ID hash."
)
async def get_job_history_detail(
    job_id: str,
    current_user: dict = Depends( get_current_user )
):
    """
    Get a single job's persistence record.

    Requires:
        - Authenticated user (Bearer token)
        - job_id is a valid id_hash string

    Ensures:
        - Returns full job dict if found and authorized
        - 404 if job not found
        - 403 if regular user accessing another user's job
    """
    from cosa.rest.job_persistence import get_job_by_id_hash

    job = get_job_by_id_hash( job_id )

    if job is None:
        raise HTTPException( status_code=404, detail=f"Job not found: {job_id}" )

    # Authorization: regular users can only see their own jobs
    if not is_admin( current_user ) and job.get( "user_id" ) != current_user[ "uid" ]:
        raise HTTPException( status_code=403, detail="Not authorized to view this job" )

    return job


@router.delete(
    "/job-history/all",
    summary     = "Bulk delete job history",
    description = "Delete all job history records matching the given time window. "
                  "Admins delete across all users; regular users delete only their own records."
)
async def delete_all_job_history(
    current_user: dict    = Depends( get_current_user ),
    days: Optional[str]   = Query( None, description="Time window: 1, 7, 14, 30, or 'all'. Defaults to 'all'." )
):
    """
    Bulk delete job history from PostgreSQL.

    Route-order note: this literal-path handler is declared BEFORE the
    parameterized `/job-history/{job_id}` sibling so FastAPI matches
    `/job-history/all` here rather than binding `job_id="all"` and returning 404.

    Requires:
        - Authenticated user (Bearer token)
        - days is None, 'all', or a numeric string matching 1/7/14/30

    Ensures:
        - Deletes all matching history rows for the user (or all users if admin)
        - Returns { status, items_deleted, days_filter, timestamp }

    Raises:
        - HTTPException 400: Invalid days parameter
    """
    from cosa.rest.job_persistence import delete_job_history_bulk

    user_id = None if is_admin( current_user ) else current_user[ "uid" ]

    days_int = None
    days_label = "all"
    if days and days != "all":
        try:
            days_int   = int( days )
            days_label = str( days_int )
        except ValueError:
            raise HTTPException( status_code=400, detail=f"Invalid days parameter: {days}. Use a number or 'all'." )

    print( f"[API] DELETE /api/job-history/all - user: {current_user['uid']}, days: {days_label}" )

    items_deleted = delete_job_history_bulk( user_id=user_id, days=days_int )

    print( f"[API] Deleted {items_deleted} history records (days={days_label}) for user {current_user['uid']}" )

    return {
        "status"        : "deleted",
        "items_deleted" : items_deleted,
        "days_filter"   : days_label,
        "timestamp"     : cu.get_current_datetime_iso()
    }


@router.delete(
    "/job-history/{job_id}",
    summary     = "Delete job from history",
    description = "Hard delete a job history record. Admin or job owner only."
)
async def delete_job_history_endpoint(
    job_id: str,
    current_user: dict = Depends( get_current_user )
):
    """
    Delete a single job from PostgreSQL persistence.

    Requires:
        - Authenticated user (Bearer token)
        - job_id is a valid id_hash string
        - User must be admin or the job's owner

    Ensures:
        - Returns { status: "deleted", job_id: str } on success
        - 404 if job not found
        - 403 if regular user deleting another user's job
    """
    from cosa.rest.job_persistence import get_job_by_id_hash, delete_job_history

    job = get_job_by_id_hash( job_id )

    if job is None:
        raise HTTPException( status_code=404, detail=f"Job not found: {job_id}" )

    # Authorization: regular users can only delete their own jobs
    if not is_admin( current_user ) and job.get( "user_id" ) != current_user[ "uid" ]:
        raise HTTPException( status_code=403, detail="Not authorized to delete this job" )

    deleted = delete_job_history( job_id )

    if not deleted:
        raise HTTPException( status_code=500, detail="Failed to delete job from history" )

    return { "status": "deleted", "job_id": job_id }


# ── TOMBSTONE — /api/job-history/{job_id}/retry ──
#   GONE. Work now enters through /api/v2/ask. REMOVE BY 2026-12-31.
#   What was here: a queue door wearing a job-history URL. It read `question_text` off
#   the stored row and called push_job with it — its own comment said "the same pattern
#   as POST /api/push". The client sent only a websocket_id, so the CALLER now has to
#   hold the question: notifications.js already did (it shows it in the confirm dialog),
#   and JobsPaneRenderer.ts reads it off the hydrated history row's meta.
#   Why that was bad: eighteen doors into one queue meant eighteen places a guard
#   would have to be installed, and the read guard could not cover them all. Rick,
#   2026-08-21: ONE entry point, and it is v2.
#   The body is DELETED rather than left unreachable below a raise: unreachable code
#   is code nobody can test and everybody must still read. Recover it from git if any
#   of its handling turns out to be worth carrying into /api/v2/ask.
@router.post(
    "/job-history/{job_id}/retry",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/ask",
    description = tombstone_description( "/api/job-history/{job_id}/retry" )
)
async def retry_job_history():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/ask
          and the REMOVE BY 2026-12-31 date
    """
    gone( "/api/job-history/{job_id}/retry" )


# =============================================================================
# CJ Flow: Job Pause/Resume (Todo Queue Only)
# =============================================================================


@router.patch(
    "/queue/todo/{job_id}/pause",
    summary     = "Pause a todo queue job",
    description = "Set paused=True on a todo queue job. Consumer skips it until resumed."
)
async def pause_job(
    job_id: str,
    current_user: dict = Depends( get_current_user ),
    todo_queue         = Depends( get_todo_queue ),
):
    """
    Pause a job in the todo queue.

    A paused job remains in the queue but is skipped by the consumer during
    eligibility checks. Resume the job to make it eligible again.

    Requires:
        - job_id identifies a job currently in the todo queue
        - current_user is authenticated
        - Job belongs to current user OR user is admin

    Ensures:
        - Job's paused flag is set to True
        - Returns confirmation

    Raises:
        - HTTPException 404: Job not found in todo queue
        - HTTPException 403: User does not own this job
    """
    user_id = current_user[ "uid" ]

    print( f"[API] PATCH /api/queue/todo/{job_id}/pause - user: {user_id}" )

    try:
        job = todo_queue.get_by_id_hash( job_id )
    except KeyError:
        raise HTTPException( status_code=404, detail=f"Job not found in todo queue: {job_id}" )

    if job.user_id != user_id and not is_admin( current_user ):
        raise HTTPException( status_code=403, detail="Not authorized to pause this job" )

    job.state = JobState.PAUSED

    # Emit WebSocket event for UI update (state transition: queued/scheduled → paused).
    # Canonical dual-emit so admin viewers also see the pause badge appear.
    try:
        import lupin_app.main as main_module
        ws_manager = main_module.websocket_manager
        ws_manager.emit_to_user_and_admins_sync(
            user_id = user_id,
            event   = "job_state_transition",
            data    = {
                "job_id"     : job_id,
                "from_state" : JobState.QUEUED.value,
                "to_state"   : JobState.PAUSED.value,
                "timestamp"  : cu.get_current_datetime_iso(),
            },
        )
    except Exception as e:
        print( f"[API] Warning: WebSocket emission failed for pause transition: {e}" )

    # Durably record the pause so a container bounce restores it PAUSED, not active
    # (row 2817b0f5). No-op for non-agentic jobs absent from job_history.
    from cosa.rest.job_persistence import persist_job_paused_state
    persist_job_paused_state( job_id, True )

    print( f"[API] Job paused: {job_id} by user {user_id}" )

    return {
        "status"  : "paused",
        "job_id"  : job_id,
        "message" : "Job paused. Consumer will skip it until resumed."
    }


@router.patch(
    "/queue/todo/{job_id}/resume",
    summary     = "Resume a paused todo queue job",
    description = "Set paused=False and notify consumer to recalculate eligibility."
)
async def resume_job(
    job_id: str,
    current_user: dict = Depends( get_current_user ),
    todo_queue         = Depends( get_todo_queue ),
):
    """
    Resume a paused job in the todo queue.

    Clears the paused flag and notifies the consumer thread to recalculate
    eligibility. If the job's scheduled_at has already passed, it becomes
    immediately eligible.

    Requires:
        - job_id identifies a paused job in the todo queue
        - current_user is authenticated
        - Job belongs to current user OR user is admin

    Ensures:
        - Job's paused flag is set to False
        - Consumer thread is notified to recalculate
        - Returns confirmation

    Raises:
        - HTTPException 404: Job not found in todo queue
        - HTTPException 403: User does not own this job
    """
    user_id = current_user[ "uid" ]

    print( f"[API] PATCH /api/queue/todo/{job_id}/resume - user: {user_id}" )

    try:
        job = todo_queue.get_by_id_hash( job_id )
    except KeyError:
        raise HTTPException( status_code=404, detail=f"Job not found in todo queue: {job_id}" )

    if job.user_id != user_id and not is_admin( current_user ):
        raise HTTPException( status_code=403, detail="Not authorized to resume this job" )

    job.state = JobState.QUEUED

    # Emit WebSocket event for UI update (state transition: paused → queued).
    # Canonical dual-emit so admin viewers also see the pause badge clear.
    try:
        import lupin_app.main as main_module
        ws_manager = main_module.websocket_manager
        ws_manager.emit_to_user_and_admins_sync(
            user_id = user_id,
            event   = "job_state_transition",
            data    = {
                "job_id"     : job_id,
                "from_state" : JobState.PAUSED.value,
                "to_state"   : JobState.QUEUED.value,
                "timestamp"  : cu.get_current_datetime_iso(),
            },
        )
    except Exception as e:
        print( f"[API] Warning: WebSocket emission failed for resume transition: {e}" )

    # Clear the durable pause flag so a later restore does not re-hold a resumed job
    # (row 2817b0f5). No-op for non-agentic jobs absent from job_history.
    from cosa.rest.job_persistence import persist_job_paused_state
    persist_job_paused_state( job_id, False )

    # Notify consumer to recalculate eligibility (may wake from timed sleep)
    with todo_queue.condition:
        todo_queue.condition.notify()

    print( f"[API] Job resumed: {job_id} by user {user_id}" )

    return {
        "status"  : "resumed",
        "job_id"  : job_id,
        "message" : "Job resumed. Consumer will process it when eligible."
    }


# ---------------------------------------------------------------------------
# Checkpoint-resume: reconstruct a stalled job from its checkpoint
# (Session 9056c113)
# ---------------------------------------------------------------------------

class ResumeFromCheckpointRequest( BaseModel ):
    """Optional per-resume model + thinking-effort overrides.

    All fields optional. Old clients may POST with no body — `request` is then
    an empty model and no overrides apply. New clients may POST:
    ``{"lead_model_override": "claude-opus-4-7", "thinking_effort": "xhigh"}``
    to steer a specific resume without touching INI defaults.
    """
    lead_model_override   : Optional[ str ] = None
    worker_model_override : Optional[ str ] = None
    thinking_effort       : Optional[ Literal[ "low", "medium", "high", "xhigh", "max" ] ] = None


@router.post(
    "/jobs/{id_hash}/resume-from-checkpoint",
    summary     = "Resume a stalled job from its saved checkpoint",
    description = "Reconstructs a stalled (voice-gate-timeout) job from its "
                  "checkpoint in job_history, pushes to todo queue. Optional "
                  "body may specify per-resume model + thinking-effort overrides.",
)
async def resume_stalled_job(
    id_hash      : str,
    request      : ResumeFromCheckpointRequest = Body( default_factory=ResumeFromCheckpointRequest ),
    current_user = Depends( get_current_user ),
    todo_queue   = Depends( get_todo_queue ),
):
    """
    Resume a stalled job from its checkpoint.

    Requires:
        - id_hash references a stalled job with checkpoint data in job_history

    Ensures:
        - New job reconstructed with checkpoint loaded on orchestrator
        - Pushed to todo queue for consumer pickup
        - Returns the new job ID and resume phase info
    """
    from cosa.rest.agentic_job_factory import resume_job

    overrides = request.model_dump( exclude_none=True ) if request else {}
    job = resume_job( id_hash, config_mgr=None, args_overrides=overrides or None )
    if job is None:
        raise HTTPException(
            status_code = 404,
            detail      = f"Job {id_hash} not found, not stalled, or has no checkpoint"
        )

    # Push to todo queue
    todo_queue.push( job )

    resume_info = job._resume_checkpoint
    print(
        f"[API] POST /api/jobs/{id_hash}/resume-from-checkpoint - "
        f"new job: {job.id_hash}, "
        f"resume from phase {resume_info.get( 'phase_name', '?' )}"
        + ( f", overrides: {overrides}" if overrides else "" )
    )

    return {
        "status"           : "resumed",
        "resumed_job_id"   : job.id_hash,
        "original_job_id"  : id_hash,
        "resume_from_phase": resume_info.get( "phase_ordinal" ),
        "phase_name"       : resume_info.get( "phase_name" ),
        "resume_count"     : resume_info.get( "resume_count", 1 ),
    }


# ---------------------------------------------------------------------------
# Smart TFE resume: dispatch free-form input (job ID or plan path) to resume
# (Session 9056c113 continued — Phase D4b file-path resume)
# ---------------------------------------------------------------------------


class TFEResumeFromRequest( BaseModel ):
    """Request body for smart TFE resume-from endpoint.

    The resume_from field accepts any of:
    - TFE job ID: "tfe-7c25082a" or "tfe-7c25082a::user@example.com"
    - Plan doc path: "io/swe-team/plans/.../c1-plan.md"
    - Checkpoint JSON path (future): "io/checkpoints/.../checkpoint.json"
    - Natural language description (Phase 2, not yet implemented)

    Optional overrides (all default None, SDK/INI default applies):
    - lead_model_override / worker_model_override: per-resume model swap
    - thinking_effort: extended-thinking level for this resume
    """
    resume_from           : str
    lead_model_override   : Optional[ str ] = None
    worker_model_override : Optional[ str ] = None
    thinking_effort       : Optional[ Literal[ "low", "medium", "high", "xhigh", "max" ] ] = None


@router.post(
    "/test-fix-expediter/resume-from",
    summary     = "Smart TFE resume — auto-detect job ID or plan path",
    description = "Accepts free-form input (job ID, plan doc path, or description) "
                  "and resolves to a stalled TFE job, then resumes from checkpoint.",
)
async def resume_tfe_smart(
    request: TFEResumeFromRequest,
    current_user = Depends( get_current_user ),
    todo_queue   = Depends( get_todo_queue ),
):
    """
    Smart resume: auto-detect input type and dispatch.

    Requires:
        - request.resume_from is a non-empty string
        - current_user is authenticated

    Ensures:
        - 200 with status=resumed if auto-resolved to a single stalled job
        - 200 with status=ambiguous + candidates if multiple matches (Phase 2)
        - 404 if no match found
    """
    from cosa.agents.test_fix_expediter.resume_resolver import resolve_resume_target
    from cosa.rest.agentic_job_factory import resume_job

    user_email = current_user.get( "email" ) or current_user.get( "user_email" )
    if not user_email:
        raise HTTPException( status_code=400, detail="Authenticated user has no email" )

    target = resolve_resume_target( request.resume_from, user_email )

    if target.source_type == "not_found":
        raise HTTPException( status_code=404, detail=target.diagnostic )

    # Multi-match disambiguation (Phase 2 — LLM fuzzy matcher)
    if target.job_id is None and target.candidates:
        return {
            "status"     : "ambiguous",
            "candidates" : target.candidates,
            "diagnostic" : target.diagnostic,
        }

    # Single match — delegate to existing resume_job() factory
    overrides = {
        "lead_model_override"   : request.lead_model_override,
        "worker_model_override" : request.worker_model_override,
        "thinking_effort"       : request.thinking_effort,
    }
    overrides = { k: v for k, v in overrides.items() if v is not None }
    job = resume_job( target.job_id, config_mgr=None, args_overrides=overrides or None )
    if job is None:
        raise HTTPException(
            status_code = 404,
            detail      = f"Job {target.job_id} resolved but cannot be resumed "
                          f"(may have been already resumed or cleared)"
        )

    todo_queue.push( job )

    resume_info = job._resume_checkpoint
    print(
        f"[API] POST /api/test-fix-expediter/resume-from - "
        f"input: '{request.resume_from[:60]}', "
        f"source_type: {target.source_type}, "
        f"resolved: {target.job_id}, "
        f"new job: {job.id_hash}, "
        f"resume from phase {resume_info.get( 'phase_name', '?' )}"
    )

    return {
        "status"           : "resumed",
        "source_type"      : target.source_type,
        "matched_path"     : target.matched_path,
        "confidence"       : target.confidence,
        "resumed_job_id"   : job.id_hash,
        "original_job_id"  : target.job_id,
        "resume_from_phase": resume_info.get( "phase_ordinal" ),
        "phase_name"       : resume_info.get( "phase_name" ),
        "resume_count"     : resume_info.get( "resume_count", 1 ),
        "diagnostic"       : target.diagnostic,
    }