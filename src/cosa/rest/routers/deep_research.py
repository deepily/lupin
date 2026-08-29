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
from cosa.rest.routers._retired_doors import gone, tombstone_description

# Import GCS utilities
try:
    from cosa.utils.util_gcs import read_text_from_gcs, GCS_AVAILABLE
except ImportError:
    GCS_AVAILABLE = False
    read_text_from_gcs = None

router = APIRouter( tags=[ "deep-research" ] )


# ═══════════════════════════════════════════════════════════════════════════════
# Job Submission Endpoint — retired
#
# The request and response models went with the handler, and so did the todo-queue
# dependency. A Pydantic model no route reads is a shape a caller can still find and
# reasonably believe in, and a queue handle in a module whose only POST is a tombstone
# reads as a door that was disabled rather than retired.
# ═══════════════════════════════════════════════════════════════════════════════

# ── TOMBSTONE — /api/deep-research/submit ──
#
# THE REPORT AND HEALTH ROUTES BELOW SURVIVE. They read a finished report and answer a
# health check; neither puts work on the queue, so neither is a door in the sense this
# retirement is about.
#
# WHAT THE CALLER DOES INSTEAD. This door named its own command and put the caller's
# scheduling and lineage fields on the job by hand. `/api/v2/submit` takes the command as
# a string and the same arguments as `args`, and carries `scheduled_at`, `monopolize` and
# `parent_id_hash` as its own top-level fields:
#
#     POST /api/v2/submit
#     { "command": "agent router go to deep research",
#       "args"   : { "query": "...", "budget": 3.0, "dry_run": false },
#       "scheduled_at": "...", "monopolize": false, "parent_id_hash": null }
#
# NOTHING THIS DOOR DID IS LOST, and each piece is worth naming because "the new door does
# it too" is the claim a tombstone rests on: the job is built by the same
# `create_agentic_job` this handler called; the id is scoped through the same
# `user_job_tracker.register_scoped_job`, in the queued executor (executor.py:197) rather
# than here; the scheduling fields and the lineage stamp land on the job in the factory;
# and the 400s for a token with no uid or email are the 401s `submit` already raises.
#
# The one thing that genuinely does not come back is `queue_position`. `AskResponse` has no
# such field and is not being widened for it — a job card learns its place from the queue
# websocket events, which is where a position that changes as the queue moves belongs
# anyway, rather than from a number frozen at the instant of submission.
#
# The body is DELETED rather than left unreachable under a raise: unreachable code is code
# nobody can test and everybody must still read. Recover it from git if any of its handling
# turns out to be worth carrying into the flow.
@router.post(
    "/api/deep-research/submit",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/submit",
    description = tombstone_description( "/api/deep-research/submit" )
)
async def submit_research():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit and the
          REMOVE BY 2026-12-31 date
    """
    gone( "/api/deep-research/submit" )


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
