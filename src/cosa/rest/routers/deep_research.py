"""
Deep Research report viewing, management, and CJ Flow job submission endpoints.

Provides endpoints for:
- Viewing research reports stored locally or in GCS
- Submitting research jobs to the queue system
- Health checks for the deep research subsystem

Generated on: 2026-01-18
"""

import os
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

import cosa.utils.util as cu
from cosa.rest.auth import get_current_user
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.agentic_job_factory import create_agentic_job

# Import GCS utilities
try:
    from cosa.utils.util_gcs import read_text_from_gcs, GCS_AVAILABLE
except ImportError:
    GCS_AVAILABLE = False
    read_text_from_gcs = None

router = APIRouter( tags=[ "deep-research" ] )


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════════

class DeepResearchSubmitRequest( BaseModel ):
    """Request body for submitting a deep research job."""
    query: str = Field( ..., min_length=1, description="The research query to investigate" )
    budget: Optional[ float ] = Field( None, ge=0, description="Maximum budget in USD (None = unlimited)" )
    websocket_id: Optional[ str ] = Field( None, description="WebSocket session ID for notifications" )
    lead_model: Optional[ str ] = Field( None, description="Model for lead agent (None = use default)" )
    dry_run: bool = Field( False, description="Simulate execution without API calls" )
    force_failure_mode: Optional[ str ] = Field( None, description="Phase 6 dry-run repair loop: 'code_bug' | 'infra_timeout' | 'rate_limit' to inject a failure at the end of dry-run" )
    audience: Optional[ str ] = Field( None, description="Target audience level: beginner, general, expert, academic" )
    audience_context: Optional[ str ] = Field( None, description="Custom audience description" )
    scheduled_at: Optional[ str ] = Field( None, description="ISO datetime for deferred execution (None = immediate)" )
    monopolize: bool = Field( False, description="Run exclusively, block all other jobs until complete" )


class DeepResearchSubmitResponse( BaseModel ):
    """Response body for deep research job submission."""
    status: str = Field( ..., description="Job status (queued)" )
    job_id: str = Field( ..., description="Unique job identifier (dr-{uuid8})" )
    queue_position: int = Field( ..., description="Position in the todo queue" )
    message: str = Field( ..., description="Human-readable confirmation message" )


# ═══════════════════════════════════════════════════════════════════════════════
# Dependencies
# ═══════════════════════════════════════════════════════════════════════════════

def get_todo_queue():
    """
    Dependency to get todo queue from main module.

    Returns:
        TodoFifoQueue: The todo queue instance
    """
    import fastapi_app.main as main_module
    return main_module.jobs_todo_queue


# ═══════════════════════════════════════════════════════════════════════════════
# Job Submission Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/api/deep-research/submit",
    response_model = DeepResearchSubmitResponse,
    summary        = "Submit deep research job",
    description    = "Create a deep research job and push to the CJ Flow todo queue."
)
async def submit_research(
    request_body: DeepResearchSubmitRequest,
    current_user: dict = Depends( get_current_user ),
    todo_queue = Depends( get_todo_queue )
):
    """
    Submit a deep research job to run in the background.

    Creates a DeepResearchJob and pushes it to the todo queue for
    asynchronous execution. The job will run through the queue system
    and send progress notifications via WebSocket.

    Requires:
        - Authenticated user (current_user from token)
        - Valid research query
        - Valid user email for report storage

    Ensures:
        - DeepResearchJob created with unique ID
        - Job pushed to todo queue
        - Returns job_id for tracking

    Args:
        request_body: Research job parameters
        current_user: Authenticated user from token
        todo_queue: Todo queue instance

    Returns:
        DeepResearchSubmitResponse: Job submission confirmation

    Raises:
        HTTPException 400: Invalid request parameters
        HTTPException 500: Queue push failed
    """
    from cosa.agents.deep_research.job import DeepResearchJob

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
        # Create the DeepResearchJob using shared factory
        args_dict = { "query": request_body.query }
        if request_body.budget is not None:
            args_dict[ "budget" ] = str( request_body.budget )
        if request_body.dry_run:
            args_dict[ "dry_run" ] = True
        if request_body.force_failure_mode:
            args_dict[ "force_failure_mode" ] = request_body.force_failure_mode
        if request_body.audience:
            args_dict[ "audience" ] = request_body.audience
        if request_body.audience_context:
            args_dict[ "audience_context" ] = request_body.audience_context

        job = create_agentic_job(
            command    = "agent router go to deep research",
            args_dict  = args_dict,
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id
        )

        if job is None:
            raise HTTPException( status_code=500, detail="Failed to create research job" )

        # Apply lead_model if specified (factory doesn't handle this)
        if request_body.lead_model:
            job.lead_model = request_body.lead_model

        # Scheduling attributes pass-through (CJ Flow timed execution + monopolize)
        if request_body.scheduled_at: job.scheduled_at = request_body.scheduled_at
        if request_body.monopolize:   job.monopolize   = request_body.monopolize

        # Atomic: scope ID + index for user filtering BEFORE push (race condition prevention)
        job.id_hash = user_job_tracker.register_scoped_job( job.id_hash, user_id, session_id )

        # Push to todo queue
        # The todo queue's push method handles WebSocket notifications
        todo_queue.push( job )

        # Get queue position (approximate - queue length after push)
        queue_position = todo_queue.size()

        return DeepResearchSubmitResponse(
            status         = "queued",
            job_id         = job.id_hash,
            queue_position = queue_position,
            message        = f"Deep research job queued: {job.last_question_asked}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit research job: {str( e )}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Report Viewing Endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/api/deep-research/report",
    response_class = PlainTextResponse,
    summary        = "Get research report",
    description    = "Retrieve a research report by local path or GCS URI as raw Markdown."
)
async def get_report(
    path: str = Query( ..., description="Local file path or GCS URI (gs://bucket/path/file.md)" )
):
    """
    Retrieve a deep research report by path.

    Supports both local filesystem paths and GCS URIs (gs://...).
    Returns the raw markdown content with appropriate content type.

    Requires:
        - path is a valid local file path or GCS URI
        - For local paths: file must exist within LUPIN_ROOT/io/deep-research/
        - For GCS paths: valid GCS credentials and read access

    Ensures:
        - Returns markdown content with text/markdown content type
        - Returns 404 if file not found
        - Returns 400 if path is outside allowed directories (security)
        - Returns 503 if GCS SDK not available for GCS paths

    Args:
        path: Local file path or GCS URI (URL-decoded automatically)

    Returns:
        PlainTextResponse: Markdown content with text/markdown content type

    Raises:
        HTTPException 400: Invalid or unsafe path
        HTTPException 404: File not found
        HTTPException 503: GCS SDK not available
    """
    # URL decode the path (FastAPI does this automatically, but be explicit)
    decoded_path = unquote( path )

    # Determine if this is a GCS or local path
    if decoded_path.startswith( "gs://" ):
        # GCS path
        if not GCS_AVAILABLE or read_text_from_gcs is None:
            raise HTTPException(
                status_code=503,
                detail="GCS SDK not available. Install with: pip install google-cloud-storage"
            )

        try:
            content = read_text_from_gcs( decoded_path, debug=False )
            return PlainTextResponse(
                content=content,
                media_type="text/markdown; charset=utf-8"
            )
        except Exception as e:
            error_msg = str( e )
            if "NotFound" in error_msg or "404" in error_msg:
                raise HTTPException(
                    status_code=404,
                    detail=f"Report not found: {decoded_path}"
                )
            raise HTTPException(
                status_code=500,
                detail=f"Error reading from GCS: {error_msg}"
            )

    else:
        # Local path
        project_root = cu.get_project_root()

        # Security: ensure path is within allowed directory
        # Allow paths in /io/deep-research/ or absolute paths within project
        allowed_base = project_root + "/io/deep-research"

        # Resolve the full path
        if decoded_path.startswith( "/" ):
            # Absolute path - check if it's within project
            full_path = decoded_path
        else:
            # Relative path - treat as relative to allowed_base
            full_path = os.path.join( allowed_base, decoded_path )

        # Normalize to prevent directory traversal
        full_path = os.path.normpath( full_path )

        # Security check: ensure path is within allowed directories
        if not full_path.startswith( allowed_base ) and not full_path.startswith( project_root + "/io/" ):
            raise HTTPException(
                status_code=400,
                detail="Invalid path: must be within project io/deep-research directory"
            )

        # Check if file exists
        if not os.path.isfile( full_path ):
            raise HTTPException(
                status_code=404,
                detail=f"Report not found: {decoded_path}"
            )

        # Read and return content
        try:
            with open( full_path, "r", encoding="utf-8" ) as f:
                content = f.read()
            return PlainTextResponse(
                content=content,
                media_type="text/markdown; charset=utf-8"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error reading file: {str( e )}"
            )


@router.get(
    "/api/deep-research/health",
    summary     = "Deep research health check",
    description = "Report GCS availability and local research directory status."
)
async def deep_research_health():
    """
    Health check for deep research endpoints.

    Returns status of GCS availability and local storage.
    """
    project_root = cu.get_project_root()
    local_path = project_root + "/io/deep-research"
    local_exists = os.path.isdir( local_path )

    return {
        "status"        : "ok",
        "gcs_available" : GCS_AVAILABLE,
        "local_storage" : {
            "path"   : local_path,
            "exists" : local_exists
        }
    }
