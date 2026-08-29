"""
The retired Deep Research to Presentation submission door.

This module used to submit chained research→presentation jobs to the CJ Flow queue. It now
holds a single tombstone: the route stays registered and answers 410 Gone naming
`/api/v2/submit`, which is where that work enters now.

The request and response models went with the handler, and so did the todo-queue
dependency. A Pydantic model no route reads is a shape a caller can still find and
reasonably believe in.

What a caller sends instead:

    POST /api/v2/submit
    {
        "command": "agent router go to research to presentation",
        "args": { "query": "State of AI safety in 2026", "budget": 3.00, "target_duration_minutes": 15 }
    }
"""

import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cosa.rest.routers._retired_doors import RETIRED_DOORS, gone, refusal_detail, tombstone_description
import cosa.utils.util as cu


router = APIRouter(
    prefix="/api/deep-research-to-presentation",
    tags=[ "deep-research-to-presentation" ]
)


# ═══════════════════════════════════════════════════════════════════════════════
# Job Submission Endpoint — retired
#
# The request and response models went with the handler, and so did the todo-queue
# dependency. A Pydantic model no route reads is a shape a caller can still find and
# reasonably believe in, and a queue handle in a module whose only POST is a tombstone
# reads as a door that was disabled rather than retired.
# ═══════════════════════════════════════════════════════════════════════════════

# ── TOMBSTONE — /api/deep-research-to-presentation/submit ──
#
#
# WHAT THE CALLER DOES INSTEAD. This door named its own command and put the caller's
# scheduling and lineage fields on the job by hand. `/api/v2/submit` takes the command as
# a string and the same arguments as `args`, and carries `scheduled_at`, `monopolize` and
# `parent_id_hash` as its own top-level fields:
#
#     POST /api/v2/submit
#     { "command": "agent router go to research to presentation",
#       "args"   : { "query": "...", "budget": 3.0, "target_duration_minutes": 15 },
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
    # The router carries a prefix, so the decorator takes the tail while the two
    # tombstone helpers take the full path the table is keyed on — a decorator given
    # the full path here would mount it TWICE-prefixed and the door would answer 404,
    # which is the one thing a tombstone must never do.
    "/submit",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/submit",
    description = tombstone_description( "/api/deep-research-to-presentation/submit" )
)
async def submit_research_to_presentation():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit and the
          REMOVE BY 2026-12-31 date
    """
    gone( "/api/deep-research-to-presentation/submit" )


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

        # Test 3: the door is a tombstone, mounted at the path the table names
        #
        # The model tests that used to sit here went with the models. What matters now is
        # that the route resolves to exactly the path RETIRED_DOORS is keyed on: the
        # router carries a prefix, so a decorator handed the full path would mount it
        # twice-prefixed and the door would answer 404 — the one answer a tombstone must
        # never give.
        print( "Testing the retired route..." )
        paths = [ r.path for r in router.routes ]
        assert paths == [ "/api/deep-research-to-presentation/submit" ], paths
        assert "/api/deep-research-to-presentation/submit" in RETIRED_DOORS
        assert RETIRED_DOORS[ "/api/deep-research-to-presentation/submit" ] == "/api/v2/submit"
        print( f"✓ Routes: {paths} -> {RETIRED_DOORS[ '/api/deep-research-to-presentation/submit' ]}" )

        # Test 4: the refusal names its replacement and its removal date
        print( "Testing the refusal..." )
        detail = refusal_detail( "/api/deep-research-to-presentation/submit" )
        assert "/api/v2/submit" in detail
        assert "REMOVE BY" in detail
        print( f"✓ {detail}" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
