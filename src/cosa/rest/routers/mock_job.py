"""
Mock job endpoints, retired.

`POST /api/mock-job/submit` answers 410 and names `/api/v2/submit`. What it did is not
gone. The command `agent router go to mock job` (cosa.agents.test_harness.mock_submit)
reproduces both of its modes. One mode is the zero-cost MockAgenticJob. The other is the
RuntimeArgumentExpeditor test, which builds a dry-run job of the command a voice command
matches. Four suites called the old door: the 12-scenario proxy suite, the swe-team proxy
suite, the expeditor mock-job smoke and the CJ Flow pause/schedule e2e. They now reach the
command through the v2 door.

`GET /api/mock-job/health` stays. Three of those suites probe it before they run, and it
queues nothing, so it is not one of the queue doors.

The old handler and its request and response models are deleted rather than left
unreachable under a raise. Recover them from git with
`git log -S submit_mock_job -- src/cosa/rest/routers/mock_job.py`.
"""

from fastapi import APIRouter

from cosa.rest.routers._retired_doors import gone, tombstone_description

router = APIRouter( prefix="/api/mock-job", tags=[ "testing" ] )


@router.post(
    "/submit",
    deprecated  = True,
    status_code = 410,
    summary     = "GONE — use /api/v2/submit",
    description = tombstone_description( "/api/mock-job/submit" )
)
async def submit_mock_job():
    """
    Refuse this retired door with 410 Gone.

    Ensures:
        - never returns; raises HTTPException( 410 ) naming /api/v2/submit and the
          remove-by date
    """
    gone( "/api/mock-job/submit" )


@router.get(
    "/health",
    summary     = "Mock job health check",
    description = "Return availability status of the mock job endpoint."
)
async def mock_job_health():
    """
    Health check for mock job endpoint.

    Returns availability status.
    """
    return {
        "status"    : "ok",
        "available" : True,
        "description": "Mock job endpoint for testing queue UI without inference costs"
    }
