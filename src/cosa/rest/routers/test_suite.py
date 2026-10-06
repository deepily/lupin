"""
Test suite submission, retired.

`POST /api/test-suite/submit` answers 410 and names `/api/v2/submit`. A test-suite job is
now submitted as the command `agent router go to test suite`.

Example:
    POST /api/v2/submit
    { "command": "agent router go to test suite",
      "args": { "test_types": "e2e_a,e2e_b", "pytest_args": "-v", "dry_run": false,
                "auto_fix_on_failure": false, "env_vars": { "TFE_X": "1" } },
      "scheduled_at": "2026-09-30T11:00:00-04:00" }

What differs for a caller: the reply is a v2 `AskResponse` with `status: "waiting"`, a
`job_id` and a `queue_position`. The `queue_position` is the todo queue's size right after
the push, the number the old door returned. A refused submit is HTTP 200 with
`status: "failed"` and the cause in `error`, not the 400 the old door answered. A refused
submit means an unknown suite name or malformed or contradictory pytest_args. The job
itself forces `monopolize`. `cosa.agents.test_suite.v2_client` builds the body and reads
the reply.

The handler and its models are deleted rather than left unreachable under a raise.
Recover them from git with `git log -S submit_test_suite -- src/cosa/rest/routers/test_suite.py`.
"""

from fastapi import APIRouter

from cosa.rest.routers._retired_doors import gone, tombstone_description

router = APIRouter( tags=[ "test-suite" ] )


@router.post(
    "/api/test-suite/submit",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/submit",
    description = tombstone_description( "/api/test-suite/submit" )
)
async def submit_test_suite():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit and the
          `REMOVE BY` text built from the `REMOVE_BY` constant
    """
    gone( "/api/test-suite/submit" )
