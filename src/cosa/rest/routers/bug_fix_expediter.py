"""
The retired Bug Fix Expediter submission door.

This module used to submit bug fix expediter jobs to the CJ Flow queue. It now holds a
single tombstone: the route stays registered and answers 410 Gone naming
`/api/v2/submit`, which is where that work enters now.

The request and response models went with the handler. They described a body nothing
accepts any more, and a Pydantic model that no route reads is a shape a caller can still
find and reasonably believe in.
"""

from fastapi import APIRouter

from cosa.rest.routers._retired_doors import gone, tombstone_description

router = APIRouter( tags=[ "bug-fix-expediter" ] )


# =============================================================================
# Endpoint — retired
# =============================================================================

# ── TOMBSTONE — /api/bug-fix-expediter/submit ──
#
# The first of the submit-shaped doors to retire, and the smallest: nothing in this repo
# posts to it, so what changed is the contract, not a call site.
#
# WHAT THE CALLER DOES INSTEAD. This door named its command itself and put the caller's
# three fields on the job by hand; `/api/v2/submit` takes the same command as a string
# and the same arguments as `args`, and carries `scheduled_at` / `monopolize` /
# `parent_id_hash` as its own top-level fields:
#
#     POST /api/v2/submit
#     { "command": "agent router go to bug fix expediter",
#       "args"   : { "dead_job_id": "...", "extra_context": "...", "dry_run": false },
#       "scheduled_at": "...", "monopolize": false }
#
# NOTHING THIS DOOR DID IS LOST, and each piece is worth naming because "the new door
# does it too" is the claim a tombstone rests on:
#   · the job is built by the same `create_agentic_job` this handler called;
#   · the id is scoped through the same `user_job_tracker.register_scoped_job`, in the
#     queued executor (executor.py:197) rather than here;
#   · the two scheduling fields and the lineage stamp land on the job in the factory;
#   · the 400s for a token with no uid or email are the 401s `submit` already raises.
#
# The body is DELETED rather than left unreachable under a raise: unreachable code is code
# nobody can test and everybody must still read. Recover it from git if any of its
# handling turns out to be worth carrying into the flow.
@router.post(
    "/api/bug-fix-expediter/submit",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/submit",
    description = tombstone_description( "/api/bug-fix-expediter/submit" )
)
async def submit_bug_fix():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit and the
          REMOVE BY 2026-12-31 date
    """
    gone( "/api/bug-fix-expediter/submit" )
