"""
Mock job endpoints — RETIRED (rows 432511fd / a3c59f2d, Rick 2026-09-29).

`POST /api/mock-job/submit` (door 14) answers 410 and names `/api/v2/submit`. What it did is
not gone: the command `agent router go to mock job` (cosa.agents.test_harness.mock_submit)
reproduces both of its modes — the zero-cost MockAgenticJob, and the RuntimeArgumentExpeditor
test that builds a dry-run job of the command a voice command matches — and the four suites
that called the door (the 12-scenario proxy suite, the swe-team proxy suite, the expeditor
mock-job smoke and the CJ Flow pause/schedule e2e) now reach it through the v2 door.

`GET /api/mock-job/health` stays: three of those suites probe it before they run, and it
queues nothing, so it is not one of the queue doors.

The old handler and its request/response models are DELETED rather than left unreachable
under a raise; recover them from git (`git log -S submit_mock_job -- src/cosa/rest/routers/mock_job.py`).
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
          REMOVE BY 2026-12-31 date
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
