"""
SWE Team job submission endpoint for CJ Flow queue integration.

Provides endpoint for submitting SWE Team engineering tasks to the
queue system for asynchronous execution.

Generated on: 2026-02-16
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from cosa.rest.auth import get_current_user
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.agentic_job_factory import create_agentic_job

router = APIRouter( tags=[ "swe-team" ] )


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════════

class SweTeamSubmitRequest( BaseModel ):
    """Request body for submitting a SWE Team job."""
    task          : str            = Field( ..., min_length=1, description="The engineering task to accomplish" )
    dry_run       : bool           = Field( False, description="Simulate execution without API calls" )
    websocket_id  : Optional[ str ] = Field( None, description="WebSocket session ID for notifications" )
    lead_model    : Optional[ str ] = Field( None, description="Model for lead agent (None = use default)" )
    worker_model  : Optional[ str ] = Field( None, description="Model for worker agents (None = use default)" )
    budget        : Optional[ float ] = Field( None, ge=0, description="Maximum budget in USD (None = use default)" )
    timeout       : Optional[ int ]   = Field( None, gt=0, description="Wall-clock timeout in seconds (None = use default)" )
    trust_mode    : Optional[ str ] = Field( None, description="Trust mode: disabled, shadow, suggest, active (None = use server default)" )
    scheduled_at  : Optional[ str ] = Field( None, description="ISO datetime for deferred execution (None = immediate)" )
    monopolize    : bool            = Field( False, description="Run exclusively, block all other jobs until complete" )


class SweTeamSubmitResponse( BaseModel ):
    """Response body for SWE Team job submission."""
    status         : str = Field( ..., description="Job status (queued)" )
    job_id         : str = Field( ..., description="Unique job identifier (swe-{uuid8})" )
    queue_position : int = Field( ..., description="Position in the todo queue" )
    message        : str = Field( ..., description="Human-readable confirmation message" )


# ═══════════════════════════════════════════════════════════════════════════════
# Dependencies
# ═══════════════════════════════════════════════════════════════════════════════

def get_todo_queue():
    """
    Dependency to get todo queue from main module.

    Returns:
        TodoFifoQueue: The todo queue instance
    """
    import lupin_app.main as main_module
    return main_module.jobs_todo_queue


# ═══════════════════════════════════════════════════════════════════════════════
# Job Submission Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/api/swe-team/submit",
    response_model = SweTeamSubmitResponse,
    summary        = "Submit SWE team task",
    description    = "Submit an engineering task to the SWE Team for async execution via CJ Flow."
)
async def submit_swe_team_task(
    request_body: SweTeamSubmitRequest,
    current_user: dict = Depends( get_current_user ),
    todo_queue = Depends( get_todo_queue )
):
    """
    Submit a SWE Team engineering task to run in the background.

    Creates a SweTeamJob and pushes it to the todo queue for
    asynchronous execution. The job will run through the queue system
    and send progress notifications via WebSocket.

    Requires:
        - Authenticated user (current_user from token)
        - Valid task description

    Ensures:
        - SweTeamJob created with unique ID
        - Job pushed to todo queue
        - Returns job_id for tracking

    Args:
        request_body: SWE Team job parameters
        current_user: Authenticated user from token
        todo_queue: Todo queue instance

    Returns:
        SweTeamSubmitResponse: Job submission confirmation

    Raises:
        HTTPException 400: Invalid request parameters
        HTTPException 500: Queue push failed
    """
    # Get user ID and email from token (canonical source - don't trust client)
    user_id    = current_user.get( "uid" )
    user_email = current_user.get( "email" )

    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="User ID not found in authentication token"
        )

    if not user_email:
        raise HTTPException(
            status_code=400,
            detail="User email not found in authentication token"
        )

    # Use provided websocket_id or fall back to a default
    session_id = request_body.websocket_id or f"api-{user_id[ :8 ]}"

    try:
        # Build args_dict from request body
        args_dict = { "task": request_body.task }
        if request_body.dry_run:
            args_dict[ "dry_run" ] = True
        if request_body.lead_model:
            args_dict[ "lead_model" ] = request_body.lead_model
        if request_body.worker_model:
            args_dict[ "worker_model" ] = request_body.worker_model
        if request_body.budget is not None:
            args_dict[ "budget" ] = str( request_body.budget )
        if request_body.timeout is not None:
            args_dict[ "timeout" ] = str( request_body.timeout )
        if request_body.trust_mode:
            args_dict[ "trust_mode" ] = request_body.trust_mode

        job = create_agentic_job(
            command    = "agent router go to swe team",
            args_dict  = args_dict,
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id
        )

        if job is None:
            raise HTTPException( status_code=500, detail="Failed to create SWE Team job" )

        # Scheduling attributes pass-through (CJ Flow timed execution + monopolize)
        if request_body.scheduled_at: job.scheduled_at = request_body.scheduled_at
        if request_body.monopolize:   job.monopolize   = request_body.monopolize

        # Atomic: scope ID + index for user filtering BEFORE push (race condition prevention)
        job.id_hash = user_job_tracker.register_scoped_job( job.id_hash, user_id, session_id )

        # Push to todo queue
        todo_queue.push( job )

        # Get queue position (approximate - queue length after push)
        queue_position = todo_queue.size()

        return SweTeamSubmitResponse(
            status         = "queued",
            job_id         = job.id_hash,
            queue_position = queue_position,
            message        = f"SWE Team job queued: {job.last_question_asked}"
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit SWE Team job: {str( e )}"
        )
