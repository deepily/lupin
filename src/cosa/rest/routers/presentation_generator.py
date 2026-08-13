"""
Presentation Generator API router for CJ Flow queue-based presentation generation.

Provides a direct-path submission endpoint for creating slide decks from
source documents. Follows the Podcast Generator router pattern (simplified —
direct path mode only, no fuzzy matching for MVP).

Endpoints:
    POST /api/presentation-generator/submit - Submit presentation generation job

Example:
    POST /api/presentation-generator/submit
    {"source_path": "/io/deep-research/user@email/2026.01.26-topic.md"}
"""

import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cosa.rest.auth import get_current_user
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.agentic_job_factory import create_agentic_job
import cosa.utils.util as cu


router = APIRouter(
    prefix="/api/presentation-generator",
    tags=[ "presentation-generator" ]
)


class PresentationSubmitRequest( BaseModel ):
    """Request body for presentation generation submission."""
    source_path             : str
    target_duration_minutes : Optional[ int ] = None
    target_slide_count      : Optional[ int ] = None
    audience                : Optional[ str ] = None
    theme                   : Optional[ str ] = None
    content_model           : Optional[ str ] = Field( None, description="Override content model (e.g. claude-sonnet-4-6 for automated tests)" )
    render_only             : bool            = Field( False, description="Render-only mode: source_path must be a YAML file, skips Phases 1-5" )
    dry_run                 : bool            = False
    force_failure_mode      : Optional[ str ] = Field( None, description="Phase 6 dry-run repair loop: 'code_bug' | 'infra_timeout' | 'rate_limit' to inject a failure at the end of dry-run" )
    scheduled_at            : Optional[ str ] = Field( None, description="ISO datetime for deferred execution (None = immediate)" )
    monopolize              : bool            = Field( False, description="Run exclusively, block all other jobs until complete" )
    parent_id_hash          : Optional[ str ] = Field( None, description="Lineage token (bug 5ed4f187, mirrors 3a14292b): id_hash of a monopolize job that SPAWNED this child. When it matches the pool's active monopolizer, the consumer's Gate B (queue_consumer.py) uses this lineage to admit the child through the intake hold rather than defer it as a foreign writer. That admit-through behaviour is exercised by the swe_team monopolize sweep, NOT by this router's unit test — the unit test asserts only that the stamp lands on the job. Set by a monopolize sweep's pytest from LUPIN_TEST_MONOPOLIZE_PARENT_ID." )


class PresentationSubmitResponse( BaseModel ):
    """Response for successful job submission."""
    job_id         : str
    queue_position : int
    status         : str = "queued"


# ═══════════════════════════════════════════════════════════════════════════════
# Dependencies
# ═══════════════════════════════════════════════════════════════════════════════

def get_todo_queue():
    """
    Dependency to get todo queue from main module.

    Returns:
        RunningFifoQueue: The todo queue instance
    """
    import lupin_app.main as main_module
    return main_module.jobs_todo_queue


def get_websocket_mgr():
    """
    Dependency to get WebSocket manager from main module.

    Returns:
        WebSocketManager: The WebSocket manager instance
    """
    import lupin_app.main as main_module
    return main_module.websocket_manager


# ═══════════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════════

def validate_source_path( path: str ) -> bool:
    """
    Validate that a source path stays within the project root.

    Requires:
        - path is a non-empty string

    Ensures:
        - Returns True if the resolved path is within cu.get_project_root()
        - Returns False if the path escapes the project root

    Args:
        path: The file path to validate (absolute or project-relative)

    Returns:
        bool: True if path is safe, False otherwise
    """
    project_root = os.path.realpath( cu.get_project_root() )

    # Normalize: if relative, prepend project root
    if path.startswith( "/" ):
        full_path = cu.get_project_root() + path
    else:
        full_path = cu.get_project_root() + "/" + path

    resolved = os.path.realpath( full_path )
    return resolved.startswith( project_root + "/" ) or resolved == project_root


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/submit",
    response_model=PresentationSubmitResponse,
    summary="Submit presentation generation job",
    description="Submit a presentation generation job from a source document path."
)
async def submit_presentation_job(
    request: PresentationSubmitRequest,
    current_user: dict = Depends( get_current_user ),
    todo_queue = Depends( get_todo_queue ),
    websocket_mgr = Depends( get_websocket_mgr ),
):
    """
    Submit a presentation generation job.

    Requires:
        - Valid authentication token
        - source_path is a non-empty file path

    Ensures:
        - Returns PresentationSubmitResponse with job_id and queue_position
        - Raises 400 if source_path is empty
        - Raises 403 if path escapes project root
        - Raises 404 if source file not found
    """
    user_email = current_user.get( "email" )
    user_id    = current_user.get( "uid", user_email )
    session_id = current_user.get( "session_id", "unknown" )
    debug      = current_user.get( "debug", False )

    source_path = request.source_path.strip()

    if not source_path:
        raise HTTPException( status_code=400, detail="source_path cannot be empty" )

    # Contract: source_path is REPO-RELATIVE (e.g. "/io/..." or "/src/...") and is
    # prepended with project_root below. An absolute filesystem path under the
    # project root (e.g. "/var/lupin/src/...") would silently double-root into a
    # misleading "Source file not found" 404. Reject it LOUDLY instead so a caller
    # sending an absolute path learns the real problem.
    project_root = cu.get_project_root()
    if source_path == project_root or source_path.startswith( project_root + "/" ):
        raise HTTPException(
            status_code=400,
            detail=f"source_path must be repo-relative (e.g. /io/... or /src/...), "
                   f"not an absolute path under the project root: {source_path}"
        )

    # Security: validate path stays within project root
    if not validate_source_path( source_path ):
        raise HTTPException(
            status_code=403,
            detail="Source path escapes project root. Access denied."
        )

    # Normalize path
    if source_path.startswith( "/" ):
        full_path = cu.get_project_root() + source_path
    else:
        full_path = cu.get_project_root() + "/" + source_path

    # Validate path exists
    if not os.path.exists( full_path ):
        raise HTTPException(
            status_code=404,
            detail=f"Source file not found: {source_path}"
        )

    # Auto-detect render_only from YAML extension
    is_yaml = source_path.lower().endswith( ( ".yaml", ".yml" ) )
    render_only = request.render_only or is_yaml

    # Validate: render_only requires YAML source
    if render_only and not is_yaml:
        raise HTTPException(
            status_code=400,
            detail="render_only mode requires a .yaml or .yml source file"
        )

    # Create job using shared factory
    args_dict = { "source": full_path }
    if render_only:
        args_dict[ "render_only" ] = True
    if request.target_duration_minutes:
        args_dict[ "target_duration_minutes" ] = str( request.target_duration_minutes )
    if request.target_slide_count:
        args_dict[ "target_slide_count" ] = str( request.target_slide_count )
    if request.dry_run:
        args_dict[ "dry_run" ] = True
    if request.force_failure_mode:
        args_dict[ "force_failure_mode" ] = request.force_failure_mode
    if request.audience:
        args_dict[ "audience" ] = request.audience
    if request.theme:
        args_dict[ "theme" ] = request.theme
    if request.content_model:
        args_dict[ "content_model" ] = request.content_model

    job = create_agentic_job(
        command    = "agent router go to presentation generator",
        args_dict  = args_dict,
        user_id    = user_id,
        user_email = user_email,
        session_id = session_id,
        debug      = debug
    )

    if job is None:
        raise HTTPException( status_code=500, detail="Failed to create presentation job" )

    # Scheduling attributes pass-through (CJ Flow timed execution + monopolize)
    if request.scheduled_at: job.scheduled_at = request.scheduled_at
    if request.monopolize:   job.monopolize   = request.monopolize
    # Lineage pass-through (bug 5ed4f187, mirrors swe_team 3a14292b): stamp the
    # spawning monopolizer's id so Gate B admits this child through the monopoly
    # intake hold instead of starving it 900s as a foreign writer.
    if request.parent_id_hash: job.spawned_by_id_hash = request.parent_id_hash

    # Atomic: scope ID + index for user filtering BEFORE push
    job.id_hash = user_job_tracker.register_scoped_job( job.id_hash, user_id, session_id )

    # Push to todo queue
    todo_queue.push( job )

    # Get queue position (approximate - queue length after push)
    queue_position = todo_queue.size()

    return PresentationSubmitResponse(
        job_id         = job.id_hash,
        queue_position = queue_position,
        status         = "queued"
    )


def quick_smoke_test():
    """Quick smoke test for presentation_generator router."""
    cu.print_banner( "Presentation Generator Router Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.rest.routers.presentation_generator import router, validate_source_path
        print( "  PASS" )

        # Test 2: Router configuration
        print( "Testing router configuration..." )
        assert router.prefix == "/api/presentation-generator"
        assert "presentation-generator" in router.tags
        print( f"  Prefix: {router.prefix}" )
        print( "  PASS" )

        # Test 3: validate_source_path
        print( "Testing validate_source_path..." )
        assert validate_source_path( "/src/rnd/report.md" ) is True
        assert validate_source_path( "src/rnd/report.md" ) is True
        assert validate_source_path( "../../etc/passwd" ) is False
        print( "  PASS" )

        # Test 4: Request/Response models
        print( "Testing request/response models..." )
        req = PresentationSubmitRequest(
            source_path             = "/io/deep-research/user@test.com/topic.md",
            target_duration_minutes = 15,
            audience                = "general",
            dry_run                 = True
        )
        assert req.source_path == "/io/deep-research/user@test.com/topic.md"
        assert req.target_duration_minutes == 15

        resp = PresentationSubmitResponse(
            job_id         = "pr-abc123",
            queue_position = 1,
            status         = "queued"
        )
        assert resp.job_id == "pr-abc123"
        print( "  PASS" )

        print( "\nAll Presentation Generator Router smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
