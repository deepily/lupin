"""
Bug Fix Expediter job submission endpoint for CJ Flow queue integration.

Provides endpoint for submitting bug fix expediter jobs to the
queue system for asynchronous execution.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from cosa.rest.auth import get_current_user
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.agentic_job_factory import create_agentic_job

router = APIRouter( tags=[ "bug-fix-expediter" ] )


# =============================================================================
# Pydantic Models
# =============================================================================

class BugFixExpediterSubmitRequest( BaseModel ):
    """Request body for submitting a Bug Fix Expediter job."""
    dead_job_id   : str             = Field( ..., min_length=1, description="The id_hash of the failed/interrupted job to fix" )
    extra_context : Optional[ str ] = Field( None, description="Additional context about the failure" )
    dry_run       : bool            = Field( False, description="Simulate execution without making changes" )
    websocket_id  : Optional[ str ] = Field( None, description="WebSocket session ID for notifications" )
    scheduled_at  : Optional[ str ] = Field( None, description="ISO datetime for deferred execution (None = immediate)" )
    monopolize    : bool            = Field( False, description="Run exclusively, block all other jobs until complete" )


class BugFixExpediterSubmitResponse( BaseModel ):
    """Response body for Bug Fix Expediter job submission."""
    status         : str = Field( ..., description="Job status (queued)" )
    job_id         : str = Field( ..., description="Unique job identifier (bfe-{uuid8})" )
    queue_position : int = Field( ..., description="Position in the todo queue" )
    message        : str = Field( ..., description="Human-readable confirmation message" )


# =============================================================================
# Dependencies
# =============================================================================

def get_todo_queue():
    """Get the todo queue from the FastAPI app module."""
    import fastapi_app.main as main_module
    return main_module.jobs_todo_queue


# =============================================================================
# Endpoint
# =============================================================================

@router.post(
    "/api/bug-fix-expediter/submit",
    response_model = BugFixExpediterSubmitResponse,
    summary        = "Submit bug fix expediter job",
    description    = "Submit a bug fix expediter job to diagnose and fix a failed job via CJ Flow."
)
async def submit_bug_fix(
    request_body: BugFixExpediterSubmitRequest,
    current_user: dict = Depends( get_current_user ),
    todo_queue = Depends( get_todo_queue )
):
    """
    Submit a Bug Fix Expediter job to run in the background.

    Requires:
        - Authenticated user (current_user from token)
        - Valid dead_job_id referencing a failed/interrupted job

    Ensures:
        - BugFixExpediterJob created with unique ID
        - Job pushed to todo queue
        - Returns job_id for tracking
    """
    user_id    = current_user.get( "uid" )
    user_email = current_user.get( "email" )

    if not user_id:
        raise HTTPException( status_code=400, detail="User ID not found in authentication token" )
    if not user_email:
        raise HTTPException( status_code=400, detail="User email not found in authentication token" )

    session_id = request_body.websocket_id or f"api-{user_id[ :8 ]}"

    try:
        args_dict = { "dead_job_id": request_body.dead_job_id }
        if request_body.extra_context:
            args_dict[ "extra_context" ] = request_body.extra_context
        if request_body.dry_run:
            args_dict[ "dry_run" ] = True

        job = create_agentic_job(
            command    = "agent router go to bug fix expediter",
            args_dict  = args_dict,
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id
        )

        if job is None:
            raise HTTPException( status_code=500, detail="Failed to create Bug Fix Expediter job" )

        if request_body.scheduled_at: job.scheduled_at = request_body.scheduled_at
        if request_body.monopolize:   job.monopolize   = request_body.monopolize

        job.id_hash = user_job_tracker.register_scoped_job( job.id_hash, user_id, session_id )

        todo_queue.push( job )

        queue_position = todo_queue.size()

        return BugFixExpediterSubmitResponse(
            status         = "queued",
            job_id         = job.id_hash,
            queue_position = queue_position,
            message        = f"Bug Fix Expediter job queued: {job.last_question_asked}"
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code = 500,
            detail      = f"Failed to submit Bug Fix Expediter job: {str( e )}"
        )
