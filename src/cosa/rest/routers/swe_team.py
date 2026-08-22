"""
The retired SWE Team submission door.

This module used to build and queue SWE Team engineering jobs. It now holds a single
tombstone: the route stays registered and answers 410 Gone naming `/api/v2/submit`, which
is where that work enters now.

The request and response models went with the handler, and so did the todo-queue
dependency. A Pydantic model no route reads is a shape a caller can still find and
reasonably believe in.

⚠️ THIS ROUTER CARRIES NO PREFIX, which is why the decorator below takes the FULL path
while the prefixed routers in this directory take only the tail. Copying the tail form
here would mount the door at `/submit` and the real path would answer 404 — the one answer
a tombstone must never give.

What a caller sends instead:

    POST /api/v2/submit
    {
        "command": "agent router go to swe team",
        "args": { "task": "add retries to the upload path", "dry_run": true, "budget": 5.0 }
    }
"""

from fastapi import APIRouter

from cosa.rest.routers._retired_doors import gone, tombstone_description
import cosa.utils.util as cu

router = APIRouter( tags=[ "swe-team" ] )


# ═══════════════════════════════════════════════════════════════════════════════
# Job Submission Endpoint — retired
# ═══════════════════════════════════════════════════════════════════════════════

# ── TOMBSTONE — /api/swe-team/submit ──
#
# WHAT THE CALLER DOES INSTEAD. This door named its own command and put the caller's
# scheduling and lineage fields on the job by hand. `/api/v2/submit` takes the command as a
# string and the same arguments as `args`, and carries `scheduled_at`, `monopolize` and
# `parent_id_hash` as its own top-level fields:
#
#     POST /api/v2/submit
#     { "command": "agent router go to swe team",
#       "args"   : { "task": "...", "dry_run": true, "budget": 5.0, "timeout": 3600 },
#       "scheduled_at": null, "monopolize": false, "parent_id_hash": null }
#
# THE LINEAGE FIELD MATTERS MORE HERE THAN ANYWHERE ELSE, so it is worth being explicit
# that it survives. A monopolizing test-suite sweep exports its own id_hash to its child
# pytests as LUPIN_TEST_MONOPOLIZE_PARENT_ID (test_suite/job.py), and a swe-team dry-run
# spawned by one of those pytests echoes it back so the consumer's Gate B admits the child
# THROUGH the monopoly intake hold instead of starving it 900s (bugs 3a14292b / 5ed4f187).
# `/api/v2/submit` carries `parent_id_hash` as a top-level field and stamps it in the
# factory, so the sweep keeps working — and it is now the only lineage-aware door left.
#
# NOTHING ELSE THIS DOOR DID IS LOST EITHER: the job is built by the same
# `create_agentic_job` this handler called; the id is scoped through the same
# `user_job_tracker.register_scoped_job`, in the queued executor rather than here; and the
# 400s for a token with no uid or email are the 401s `submit` already raises.
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
    # FULL path, because this router has no prefix — see the module docstring.
    "/api/swe-team/submit",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/submit",
    description = tombstone_description( "/api/swe-team/submit" )
)
async def submit_swe_team_task():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit and the
          REMOVE BY 2026-12-31 date
    """
    gone( "/api/swe-team/submit" )


def quick_smoke_test():
    """Quick smoke test for swe_team router."""
    cu.print_banner( "SWE Team Router Smoke Test", prepend_nl=True )

    try:
        print( "Testing module import..." )
        from cosa.rest.routers.swe_team import router
        print( "  PASS" )

        # The door is a tombstone, mounted ONCE at the path the table is keyed on. This
        # router has NO prefix, so the decorator carries the full path; the tail form used
        # by its prefixed neighbours would mount it at /submit and the real path would
        # answer 404 — the one answer a tombstone must never give.
        print( "Testing the retired route..." )
        from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_SUBMIT
        paths = { route.path for route in router.routes }
        assert paths == { "/api/swe-team/submit" }, f"mounted at {paths}"
        assert RETIRED_DOORS[ "/api/swe-team/submit" ] == V2_SUBMIT
        print( "  PASS" )

        print( "\nAll SWE Team Router smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
