"""
The retired Presentation Generator submission door.

This module used to build and queue presentation jobs from a source document path. It
now holds a single tombstone: the route stays registered and answers 410 Gone naming
`/api/v2/submit`, which is where that work enters now.

The request and response models went with the handler, and so did the todo-queue and
websocket dependencies. A Pydantic model no route reads is a shape a caller can still
find and reasonably believe in.

⚠️ `validate_source_path` LEFT THIS MODULE BEFORE THE DOOR DID, and the order was not an
accident. This door was the only place a presentation source path was checked for escaping
the project root — nothing downstream repeated it. Retiring the door and moving the guard
in the same commit would have been fine; retiring it FIRST would have opened a hole for as
long as that took. The guard is now `presentation_generator/job.py::
source_path_is_inside_the_project`, raising where the file is actually opened, so it
protects every caller rather than one door.

What a caller sends instead:

    POST /api/v2/submit
    {
        "command": "agent router go to presentation generator",
        "args": { "source": "/io/deep-research/user@email/2026.01.26-topic.md",
                  "audience": "general", "target_duration_minutes": "15" }
    }
"""

from fastapi import APIRouter

from cosa.rest.routers._retired_doors import gone, tombstone_description
import cosa.utils.util as cu


router = APIRouter(
    prefix="/api/presentation-generator",
    tags=[ "presentation-generator" ]
)


# ═══════════════════════════════════════════════════════════════════════════════
# Job Submission Endpoint — retired
# ═══════════════════════════════════════════════════════════════════════════════

# ── TOMBSTONE — /api/presentation-generator/submit ──
#
# WHAT THE CALLER DOES INSTEAD. This door took a repo-relative `source_path` and a handful
# of shaping options, then put the caller's scheduling and lineage fields on the job by
# hand. `/api/v2/submit` takes the command as a string and the same arguments as `args`
# (the path arrives as `source`, which is the name the factory already reads), and carries
# `scheduled_at`, `monopolize` and `parent_id_hash` as its own top-level fields:
#
#     POST /api/v2/submit
#     { "command": "agent router go to presentation generator",
#       "args"   : { "source": "/io/deck.md", "render_only": true },
#       "scheduled_at": null, "monopolize": false, "parent_id_hash": null }
#
# NOTHING THIS DOOR DID IS LOST, and each piece is worth naming because "the new door does
# it too" is the claim a tombstone rests on. The job is built by the same
# `create_agentic_job` this handler called. The id is scoped through the same
# `user_job_tracker.register_scoped_job`, in the queued executor rather than here. The
# scheduling fields and the lineage stamp land on the job in the factory. The 403 for a
# path that escapes the project root is now a refusal to BUILD the job at all, one layer
# closer to the file. And the 404 for a missing source is the job's own existence check,
# which was always the second half of that pair.
#
# THE ONE 400 THAT DOES NOT COME BACK, deliberately: this door refused a filesystem-
# absolute path under the project root, because it would have double-rooted into a
# misleading "not found". The job now resolves both spellings to the same file
# (`resolve_source_path`), so there is nothing left to refuse — a caller who writes the
# long form gets the file rather than a lecture.
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
    description = tombstone_description( "/api/presentation-generator/submit" )
)
async def submit_presentation_job():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit and the
          REMOVE BY 2026-12-31 date
    """
    gone( "/api/presentation-generator/submit" )


def quick_smoke_test():
    """Quick smoke test for presentation_generator router."""
    cu.print_banner( "Presentation Generator Router Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.rest.routers.presentation_generator import router
        print( "  PASS" )

        # Test 2: Router configuration
        print( "Testing router configuration..." )
        assert router.prefix == "/api/presentation-generator"
        assert "presentation-generator" in router.tags
        print( f"  Prefix: {router.prefix}" )
        print( "  PASS" )

        # Test 3: the door is a tombstone, mounted at the path the table names
        #
        # The model and validate_source_path tests that used to sit here went with the
        # models and with the guard. What matters now is that the route resolves to exactly
        # the path RETIRED_DOORS is keyed on: the router carries a prefix, so a decorator
        # handed the full path would mount it twice-prefixed and the door would answer 404
        # — the one answer a tombstone must never give.
        print( "Testing the retired route..." )
        from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_SUBMIT
        paths = { route.path for route in router.routes }
        assert paths == { "/api/presentation-generator/submit" }, f"mounted at {paths}"
        assert RETIRED_DOORS[ "/api/presentation-generator/submit" ] == V2_SUBMIT
        print( "  PASS" )

        print( "\nAll Presentation Generator Router smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
