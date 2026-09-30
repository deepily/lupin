"""
Test suite submission -- RETIRED (row a3c59f2d, Rick 2026-09-29).

`POST /api/test-suite/submit` (door 18) answers 410 and names `/api/v2/submit`. A test-suite
job is now submitted as the command `agent router go to test suite`:

    POST /api/v2/submit
    { "command": "agent router go to test suite",
      "args": { "test_types": "e2e_a,e2e_b", "pytest_args": "-v", "dry_run": false,
                "auto_fix_on_failure": false, "env_vars": { "TFE_X": "1" } },
      "scheduled_at": "2026-09-30T11:00:00-04:00" }

What differs for a caller: the reply is a v2 `AskResponse` (`status: "waiting"`, `job_id`,
`queue_position` -- the todo queue's size right after the push, the number this door returned);
a refused submit (unknown suite name, malformed or contradictory pytest_args) is HTTP 200 with
`status: "failed"` and the cause in `error`, NOT the 400 this door answered. `monopolize` is
forced by the job itself. `cosa.agents.test_suite.v2_client` builds the body and reads the reply.

The handler and its models are DELETED rather than left unreachable under a raise; recover
them from git (`git log -S submit_test_suite -- src/cosa/rest/routers/test_suite.py`).
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
          REMOVE BY 2026-12-31 date
    """
    gone( "/api/test-suite/submit" )
