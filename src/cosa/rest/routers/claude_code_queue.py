"""
Claude Code Queue Submission Router.

Provides endpoint for submitting Claude Code tasks to CJ Flow (COSA Job Flow)
for background execution. Queued tasks run asynchronously through the queue
system with full job tracking.

This is the SOLE Claude Code submission path as of 2026-05-05; the legacy direct
dispatch endpoint cluster (`/api/claude-code/dispatch` + `/{task_id}/inject` +
`/{task_id}/interrupt` + `/{task_id}/end` + `/{task_id}/status` + `/ws/{task_id}`)
was eliminated due to four catalogued structural defects. See
`src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md`.

Endpoints:
    POST /api/claude-code/submit        - CANONICAL: submit task to CJF queue
    POST /api/claude-code/queue/submit  - DEPRECATED alias for one release cycle;
                                          identical behavior; logs deprecation
                                          warning per-request. Marked
                                          `deprecated=True` in OpenAPI schema.
                                          Remove once mobile + integration tests
                                          have migrated. See
                                          `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md` Q1.

Generated on: 2026-01-27; URL canonicalized 2026-05-11 (session 658ea35d).
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional

from cosa.rest.auth import get_current_user
from cosa.rest.agentic_job_factory import create_agentic_job

router = APIRouter( tags=[ "claude-code-queue" ] )


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════════

class ClaudeCodeQueueRequest( BaseModel ):
    """Request body for submitting a Claude Code task to the queue."""
    prompt         : str            = Field( ..., min_length=1, description="The task prompt for Claude Code" )
    project        : str            = Field( "lupin", description="Target project name (e.g., lupin, cosa)" )
    task_type      : str            = Field( "BOUNDED", description="Task type: BOUNDED or INTERACTIVE" )
    max_turns      : int            = Field( 50, ge=1, le=500, description="Maximum agentic turns" )
    websocket_id   : Optional[ str ] = Field( None, description="WebSocket session ID for notifications" )
    dry_run        : bool           = Field( False, description="If True, simulate execution without running Claude Code" )
    scheduled_at   : Optional[ str ] = Field( None, description="ISO datetime for delayed execution (e.g. 2026-03-31T02:00:00)" )
    monopolize     : bool           = Field( False, description="If True, no other jobs run concurrently with this job" )


class ClaudeCodeQueueResponse( BaseModel ):
    """Response body for Claude Code queue submission."""
    status: str = Field( ..., description="Job status (queued)" )
    job_id: str = Field( ..., description="Unique job identifier (cc-{uuid8})" )
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


def get_user_job_tracker():
    """
    Dependency to get user job tracker from main module.

    Returns:
        UserJobTracker: The user job tracker instance
    """
    from cosa.rest.queue_extensions import user_job_tracker
    return user_job_tracker


# ═══════════════════════════════════════════════════════════════════════════════
# Queue Submission Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/api/claude-code/submit",
    response_model = ClaudeCodeQueueResponse,
    summary        = "Submit Claude Code queue job",
    description    = "Submit a Claude Agent SDK task to the CJ Flow queue in BOUNDED or INTERACTIVE mode."
)
@router.post(
    "/api/claude-code/queue/submit",
    response_model = ClaudeCodeQueueResponse,
    deprecated     = True,
    summary        = "DEPRECATED: use /api/claude-code/submit",
    description    = "Alias for /api/claude-code/submit. Removed after one release cycle. See src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md Q1."
)
async def submit_claude_code_to_queue(
    request_body: ClaudeCodeQueueRequest,
    request: Request,
    current_user: dict = Depends( get_current_user ),
    todo_queue = Depends( get_todo_queue ),
    user_job_tracker = Depends( get_user_job_tracker )
):
    """
    Submit a Claude Code task to CJ Flow queue for background execution.

    This endpoint queues the task for background processing through the CJF system.
    (Direct-dispatch + per-turn WS streaming was retired 2026-05-05 — see module
    docstring above.) The job will:
    - Appear in the CJF Todo queue
    - Transition to Running queue when executed
    - Move to Done/Dead queue on completion/failure
    - Send notifications via cosa-voice with job_id for job card routing

    Requires:
        - Authenticated user (current_user from token)
        - Valid task prompt
        - Valid task type (BOUNDED or INTERACTIVE)

    Ensures:
        - ClaudeCodeJob created with unique cc-{uuid8} ID
        - Job pushed to todo queue
        - Job associated with user for filtering
        - Returns job_id for tracking

    Args:
        request_body: Task parameters (prompt, project, task_type, etc.)
        current_user: Authenticated user from token
        todo_queue: Todo queue instance
        user_job_tracker: User-job association tracker

    Returns:
        ClaudeCodeQueueResponse: Job submission confirmation with job_id

    Raises:
        HTTPException 400: Invalid request parameters
        HTTPException 500: Queue push failed
    """
    # Deprecation log for legacy alias path; mobile + smoke tests should migrate
    # to /api/claude-code/submit. Alias retires after one release cycle (Q1 FROZEN
    # 2026-05-09; see src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md).
    if request.url.path == "/api/claude-code/queue/submit":
        print( f"[DEPRECATED] /api/claude-code/queue/submit hit by {current_user.get( 'email', '<unknown>' )} — migrate to /api/claude-code/submit" )

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

    # Validate task_type
    task_type = request_body.task_type.upper()
    if task_type not in [ "BOUNDED", "INTERACTIVE" ]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type: {task_type}. Must be BOUNDED or INTERACTIVE"
        )

    # Use provided websocket_id or fall back to a default
    session_id = request_body.websocket_id or f"api-{user_id[ :8 ]}"

    try:
        # Create the ClaudeCodeJob via shared factory (same as voice path)
        job = create_agentic_job(
            command    = "agent router go to claude code",
            args_dict  = {
                "prompt"    : request_body.prompt,
                "project"   : request_body.project,
                "task_type" : task_type,
                "max_turns" : request_body.max_turns,
                "dry_run"   : request_body.dry_run
            },
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id
        )

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

        return ClaudeCodeQueueResponse(
            status         = "queued",
            job_id         = job.id_hash,
            queue_position = queue_position,
            message        = f"Claude Code job queued: {job.last_question_asked}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit Claude Code job: {str( e )}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Smoke Test
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test():
    """
    Quick smoke test for Claude Code Queue Router - validates basic functionality.
    """
    import cosa.utils.util as cu

    cu.print_banner( "Claude Code Queue Router Smoke Test", prepend_nl=True )

    try:
        # Test 1: Router exists + BOTH routes registered (canonical + deprecated alias).
        # Phase 5.3 Q8 verdict gate (2026-05-09 CC card normalization R&D).
        print( "Testing router configuration..." )
        assert router is not None
        assert "claude-code-queue" in router.tags

        registered_paths = { route.path for route in router.routes }
        assert "/api/claude-code/submit" in registered_paths, (
            f"Canonical /api/claude-code/submit not registered; got {registered_paths}"
        )
        assert "/api/claude-code/queue/submit" in registered_paths, (
            f"Deprecated alias /api/claude-code/queue/submit not registered (Q8 verdict = FALLBACK); "
            f"got {registered_paths}"
        )
        print( "✓ Router configured correctly (both canonical + deprecated alias registered — Q8 verdict = PRIMARY)" )

        # Test 2: Models work
        print( "Testing Pydantic models..." )
        req = ClaudeCodeQueueRequest(
            prompt    = "Run the tests",
            project   = "lupin",
            task_type = "BOUNDED",
            max_turns = 50
        )
        assert req.prompt == "Run the tests"
        assert req.project == "lupin"
        assert req.task_type == "BOUNDED"
        print( "✓ ClaudeCodeQueueRequest model works" )

        resp = ClaudeCodeQueueResponse(
            status         = "queued",
            job_id         = "cc-a1b2c3d4",
            queue_position = 1,
            message        = "Job queued"
        )
        assert resp.job_id == "cc-a1b2c3d4"
        assert resp.status == "queued"
        print( "✓ ClaudeCodeQueueResponse model works" )

        # Test 3: Test INTERACTIVE task type
        print( "Testing INTERACTIVE task type..." )
        req_interactive = ClaudeCodeQueueRequest(
            prompt    = "Let's refactor the auth",
            project   = "cosa",
            task_type = "INTERACTIVE",
            max_turns = 200
        )
        assert req_interactive.task_type == "INTERACTIVE"
        print( "✓ INTERACTIVE task type works" )

        # Test 4: Test default values
        print( "Testing default values..." )
        req_defaults = ClaudeCodeQueueRequest( prompt="Test prompt" )
        assert req_defaults.project == "lupin"
        assert req_defaults.task_type == "BOUNDED"
        assert req_defaults.max_turns == 50
        assert req_defaults.dry_run == False
        print( "✓ Default values work correctly" )

        # Test 5: Test dry_run flag
        print( "Testing dry_run flag..." )
        req_dry_run = ClaudeCodeQueueRequest(
            prompt  = "Test prompt",
            dry_run = True
        )
        assert req_dry_run.dry_run == True
        print( "✓ dry_run flag works correctly" )

        print( "\n✓ Smoke test completed successfully" )
        return True

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()
