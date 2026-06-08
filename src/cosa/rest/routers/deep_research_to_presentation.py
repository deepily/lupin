"""
Deep Research to Presentation API router for CJ Flow queue-based chained workflows.

Submits research queries that automatically generate a presentation after
research completion. Combines Deep Research → Presentation Generation pipeline.

Endpoints:
    POST /api/deep-research-to-presentation/submit - Submit chained research→presentation job

Example:
    POST /api/deep-research-to-presentation/submit
    {
        "query": "State of AI safety in 2026",
        "budget": 3.00,
        "target_duration_minutes": 15,
        "theme": "default"
    }
"""

import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cosa.rest.auth import get_current_user
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.agentic_job_factory import create_agentic_job
from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob
import cosa.utils.util as cu


router = APIRouter(
    prefix="/api/deep-research-to-presentation",
    tags=[ "deep-research-to-presentation" ]
)


# ═══════════════════════════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════════════════════════

class ResearchToPresentationSubmitRequest( BaseModel ):
    """
    Request body for research→presentation submission.

    Mirrors DeepResearchSubmitRequest with additional presentation parameters.
    """
    query                   : str = Field( ..., description="Research topic/question to investigate" )
    budget                  : Optional[ float ] = Field( None, description="Maximum budget in USD for Deep Research" )
    target_duration_minutes : Optional[ int ]   = Field( None, description="Target presentation duration in minutes" )
    theme                   : Optional[ str ]   = Field( None, description="Presentation theme name" )
    audience                : Optional[ str ]   = Field( None, description="Target audience level" )
    audience_context        : Optional[ str ]   = Field( None, description="Custom audience description" )
    lead_model              : Optional[ str ]   = Field( None, description="Override DR lead model (e.g. claude-haiku-4-5 for testing)" )
    dry_run                 : bool              = Field( False, description="Simulate execution without API calls" )


class ResearchToPresentationSubmitResponse( BaseModel ):
    """Response for successful job submission."""
    job_id         : str = Field( ..., description="Unique job identifier (rx-xxxxx format)" )
    queue_position : int = Field( ..., description="Position in the todo queue" )
    message        : str = Field( ..., description="Human-readable confirmation message" )


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


# ═══════════════════════════════════════════════════════════════════════════════
# Job Submission Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/submit",
    response_model=ResearchToPresentationSubmitResponse,
    summary="Submit research→presentation chained job",
    description="Submit a deep research job that automatically generates a presentation upon completion."
)
async def submit_research_to_presentation(
    request: ResearchToPresentationSubmitRequest,
    current_user: dict = Depends( get_current_user ),
    todo_queue = Depends( get_todo_queue )
):
    """
    Submit a deep research→presentation chained job.

    Creates a DeepResearchToPresentationJob and pushes it to the todo queue.
    The job runs the full pipeline:
    1. Deep Research: Web search, synthesis, report generation
    2. Presentation Generation: Narrative analysis, slide outline, Marp rendering

    Requires:
        - Authenticated user (current_user from token)
        - Valid research query (non-empty)
        - Valid user email for artifact storage

    Ensures:
        - Job created with rx- prefix
        - Job added to queue with user/session context
        - Returns job_id and queue_position

    Args:
        request: ResearchToPresentationSubmitRequest with query and options
        current_user: Authenticated user from JWT token
        todo_queue: Todo queue instance for job submission

    Returns:
        ResearchToPresentationSubmitResponse with job_id and queue_position

    Raises:
        HTTPException 400: If query is empty
        HTTPException 401: If not authenticated
    """
    user_email = current_user.get( "email" )
    user_id    = current_user.get( "uid", user_email )
    session_id = current_user.get( "session_id", "unknown" )
    debug      = current_user.get( "debug", False )

    # Validate query
    query = request.query.strip()
    if not query:
        raise HTTPException( status_code=400, detail="Query cannot be empty" )

    if debug:
        print( f"[submit_research_to_presentation] Query: {query[ :60 ]}..." )
        print( f"[submit_research_to_presentation] Budget: ${request.budget}" if request.budget else "[submit_research_to_presentation] Budget: unlimited" )

    # Create the chained job using shared factory
    args_dict = { "query": query }
    if request.budget is not None:
        args_dict[ "budget" ] = str( request.budget )
    if request.target_duration_minutes is not None:
        args_dict[ "target_duration_minutes" ] = str( request.target_duration_minutes )
    if request.theme is not None:
        args_dict[ "theme" ] = request.theme
    if request.audience is not None:
        args_dict[ "audience" ] = request.audience
    if request.audience_context is not None:
        args_dict[ "audience_context" ] = request.audience_context
    if request.lead_model:
        args_dict[ "lead_model" ] = request.lead_model
    if request.dry_run:
        args_dict[ "dry_run" ] = True

    job = create_agentic_job(
        command    = "agent router go to research to presentation",
        args_dict  = args_dict,
        user_id    = user_id,
        user_email = user_email,
        session_id = session_id,
        debug      = debug
    )

    if job is None:
        raise HTTPException( status_code=500, detail="Failed to create research-to-presentation job" )

    # Atomic: scope ID + index for user filtering BEFORE push (race condition prevention)
    job.id_hash = user_job_tracker.register_scoped_job( job.id_hash, user_id, session_id )

    # Push to todo queue
    todo_queue.push( job )

    # Get queue position (approximate - queue length after push)
    queue_position = todo_queue.size()

    return ResearchToPresentationSubmitResponse(
        job_id         = job.id_hash,
        queue_position = queue_position,
        message        = f"Research→Presentation job '{query[ :40 ]}...' added to queue at position {queue_position}"
    )


def quick_smoke_test():
    """
    Quick smoke test for deep_research_to_presentation router.
    """
    cu.print_banner( "Deep Research to Presentation Router Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.rest.routers.deep_research_to_presentation import router
        print( "✓ Module imported successfully" )

        # Test 2: Router configuration
        print( "Testing router configuration..." )
        assert router.prefix == "/api/deep-research-to-presentation"
        assert "deep-research-to-presentation" in router.tags
        print( f"✓ Router prefix: {router.prefix}" )

        # Test 3: Request model
        print( "Testing request model..." )
        req = ResearchToPresentationSubmitRequest(
            query                   = "test research topic",
            budget                  = 3.00,
            target_duration_minutes = 15,
            theme                   = "default"
        )
        assert req.query == "test research topic"
        assert req.budget == 3.00
        assert req.target_duration_minutes == 15
        assert req.theme == "default"
        print( "✓ Request model works correctly" )

        # Test 4: Response model
        print( "Testing response model..." )
        resp = ResearchToPresentationSubmitResponse(
            job_id         = "rx-abc123",
            queue_position = 1,
            message        = "Job added to queue"
        )
        assert resp.job_id == "rx-abc123"
        assert resp.queue_position == 1
        print( "✓ Response model works correctly" )

        # Test 5: Route exists
        print( "Testing route registration..." )
        routes = [ r.path for r in router.routes ]
        assert any( "/submit" in route for route in routes )
        print( f"✓ Routes: {routes}" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
