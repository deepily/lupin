"""
Test Suite CJ Flow job submission endpoint.

Provides a REST endpoint for submitting test suite jobs to the queue system.
This is the key integration point for:
- Claude Code self-scheduling via curl or MCP
- External cron jobs
- Future UI scheduling controls

Generated on: 2026-03-31
"""

from typing import Dict, Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from cosa.rest.auth import get_current_user
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.agentic_job_factory import create_agentic_job
from cosa.rest.pytest_args_policy import parse_and_validate, validate_timeout_against_suite_budget
import cosa.utils.util as cu

router = APIRouter( tags=[ "test-suite" ] )


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════════

class TestSuiteSubmitRequest( BaseModel ):
    """Request body for submitting a test suite job."""
    test_types          : str             = Field( "integration,e2e", description="Comma-separated suite types: integration, e2e" )
    pytest_args         : Optional[ str ] = Field( None, description="Extra pytest arguments, shell-style (shlex) parsed — quoting is honored, e.g. '-v -k \"auth or visual\"' reaches pytest as ['-v', '-k', 'auth or visual']. Unbalanced quotes → 400 at submit." )
    dry_run             : bool            = Field( False, description=(
        "Skips the pytest subprocess — but STILL QUEUES A REAL JOB and takes the monopolize "
        "slot for 7.0 SECONDS (measured 2026-09-01, ts-e929149f). That number bounds the "
        "severity and is the first thing to know: the slot is held for seven seconds, NOT "
        "for a suite's duration, so this is a naming problem with a small blast radius — a "
        "nuisance, not a fleet stall. Do not read the detail below as 'dry_run locks the "
        "box'. Stated in three tiers, because they are not equally established and a reader "
        "deciding whether to reach for this should know which is which. "
        "(1) FROM THE CODE: the flag is read at EXECUTION time — TestSuiteJob.run_job "
        "dispatches to _execute_dry_run — never at submit, and this endpoint builds the job "
        "and pushes it to the todo queue with monopolize=True unconditionally. A dry run "
        "therefore sends its breadcrumb notifications and skips only pytest. "
        "(2) MEASURED 2026-09-01: on an idle box monopolize_inflight is True on the FIRST "
        "poll after submit and the slot is released 7.0s later (ts-e929149f, /api/busy "
        "polled twice a second); and two probes submitted back to back came back at queue "
        "positions 0 and 1 (ts-6e3dd580, ts-64cf95e5), the second later named as the "
        "monopolize holder — so a dry run demonstrably waited behind another job and then "
        "took the slot. "
        "(3) FOLLOWS FROM (1) AND (2), NOT SEPARATELY OBSERVED: on a busy box it waits in "
        "todo behind a long REAL suite the same way, so 'just checking' a submission can "
        "land minutes later inside somebody else's window. The queue is one FIFO with one "
        "monopolize slot and does not distinguish the two job kinds, but nobody has watched "
        "that variant — treat it as mechanism, not as a measurement. "
        "⇒ 7 seconds is the part you can see; the wait in front of it is the part you "
        "cannot. Not dangerous, and not free." ) )
    websocket_id        : Optional[ str ] = Field( None, description="WebSocket session ID for notifications" )
    scheduled_at        : Optional[ str ] = Field( None, description="ISO datetime for deferred execution (None = immediate)" )
    auto_fix_on_failure : Optional[ bool ] = Field( None, description="Per-run override for the TestSuiteCompletionWatchdog. None = use INI default ('test fix expediter auto fix enabled'), True = force-enable TFE auto-dispatch, False = force-disable TFE auto-dispatch for this run only." )
    env_vars            : Optional[ Dict[ str, str ] ] = Field(
        None,
        description="Extra env vars to inject into the pytest subprocess. Filtered by prefix allowlist (TFE_, BFE_, LUPIN_TEST_) on the runner side. Example: {'TFE_RESUME_E2E_LIVE': '1'}"
    )


class TestSuiteSubmitResponse( BaseModel ):
    """Response body for test suite job submission."""
    status         : str = Field( ..., description="Job status (queued)" )
    job_id         : str = Field( ..., description="Unique job identifier (ts-{uuid8})" )
    queue_position : int = Field( ..., description="Position in the todo queue" )
    message        : str = Field( ..., description="Human-readable confirmation message" )


# ═══════════════════════════════════════════════════════════════════════════════
# Dependencies
# ═══════════════════════════════════════════════════════════════════════════════

def get_todo_queue():
    """
    Dependency to get todo queue from main module.

    Returns:
        TodoFifoQueue: The todo queue instance
    """
    import lupin_app.main as main_module
    return main_module.jobs_todo_queue


# ═══════════════════════════════════════════════════════════════════════════════
# Job Submission Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/api/test-suite/submit",
    response_model = TestSuiteSubmitResponse,
    summary        = "Submit test suite job",
    description    = "Create a test suite job and push to the CJ Flow todo queue. Always runs with monopolize=True."
)
async def submit_test_suite(
    request_body: TestSuiteSubmitRequest,
    current_user: dict = Depends( get_current_user ),
    todo_queue = Depends( get_todo_queue )
):
    """
    Submit a test suite job to run in the background.

    Creates a TestSuiteJob and pushes it to the todo queue for
    asynchronous execution. The job always runs with monopolize=True
    since test scripts hot-swap the database config.

    Requires:
        - Authenticated user (current_user from token)

    Ensures:
        - TestSuiteJob created with unique ID
        - Job pushed to todo queue with monopolize=True
        - Returns job_id for tracking

    Args:
        request_body: Test suite job parameters
        current_user: Authenticated user from token
        todo_queue: Todo queue instance

    Returns:
        TestSuiteSubmitResponse: Job submission confirmation

    Raises:
        HTTPException 400: Invalid request parameters
        HTTPException 500: Queue push failed

    PREFLIGHT NOTE (2026-05-01 post-mortem, Phase 7 / Cluster C):
    Bind-mount drift in the test container can produce HTTP 404s for
    fixture files that exist on the host but not inside the running
    container (e.g. the 2026-04-30 22:15-EDT failure of
    test_presentation_render_only_smoke). The canonical safeguard is
    `src/scripts/preflight-test-container.sh`, which CANNOT be invoked
    from this endpoint because the FastAPI server runs INSIDE the test
    container and the docker daemon is not reachable from there. Until
    a server-side surrogate (e.g. a /api/preflight endpoint that checks
    fixture presence + bind-mount paths from within the container)
    lands, callers MUST run preflight on the host BEFORE submitting an
    `all` or live-smoke schedule:

        $LUPIN_ROOT/src/scripts/preflight-test-container.sh

    Exit code 0 = safe to schedule; 1 = bind-mount drift detected.
    Tracked as a follow-up bug in `bug-fix-queue.md`.
    """
    # Get user ID and email from token
    user_id    = current_user.get( "uid" )
    user_email = current_user.get( "email" )

    if not user_id:
        raise HTTPException( status_code=400, detail="User ID not found in authentication token" )

    if not user_email:
        raise HTTPException( status_code=400, detail="User email not found in authentication token" )

    # (Shape-B, bug fe375cf6: the pool_max==1 monopolize belt that used to fire here
    # was removed — the monopolizer now runs on a dedicated executor OUTSIDE the shared
    # pool, so a width-1 pool no longer hard-deadlocks. The in-process pool_max=1
    # deadlock-safety test is the replacing regression guard.)

    # Use provided websocket_id or fall back to a default
    session_id = request_body.websocket_id or f"api-{user_id[ :8 ]}"

    try:
        # Refuse a bad pytest_args string AT THE DOOR (row 60f04102). This is the
        # usability half — the authoritative gate is in TestSuiteJob.__init__,
        # which every execution path runs through including persistence rehydration
        # and side-channel resubmits. Both call the same function so they cannot
        # drift apart. PytestArgsRejected subclasses ValueError, so it lands in the
        # 400 handler below alongside the pre-existing unbalanced-quote case.
        if request_body.pytest_args:
            tokens = parse_and_validate( request_body.pytest_args, cu.get_project_root() )
            # The per-test-timeout / suite-budget contradiction, refused AT THE DOOR
            # (row 64677f38). The authoritative copy is in TestSuiteJob.__init__; this
            # one exists so the submitter gets a 400 naming both numbers instead of
            # discovering the clash hours into a run. Imported here rather than at
            # module scope: job.py already imports this router's policy module, and
            # the budgets live with the runner that enforces them.
            from cosa.agents.test_suite.job import SUITE_TIMEOUTS_SECONDS, SUITE_TIMEOUT_DEFAULT_SECONDS
            validate_timeout_against_suite_budget(
                tokens, request_body.test_types, SUITE_TIMEOUTS_SECONDS, SUITE_TIMEOUT_DEFAULT_SECONDS )

        # Build args dict for factory
        args_dict = {
            "test_types" : request_body.test_types,
            "dry_run"    : request_body.dry_run,
        }
        if request_body.pytest_args:
            args_dict[ "pytest_args" ] = request_body.pytest_args
        if request_body.auto_fix_on_failure is not None:
            args_dict[ "auto_fix_on_failure" ] = request_body.auto_fix_on_failure
        if request_body.env_vars:
            args_dict[ "env_vars" ] = request_body.env_vars

        job = create_agentic_job(
            command    = "agent router go to test suite",
            args_dict  = args_dict,
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id
        )

        if job is None:
            raise HTTPException( status_code=500, detail="Failed to create test suite job" )

        # Scheduling: scheduled_at pass-through (monopolize is always True from constructor)
        if request_body.scheduled_at:
            job.scheduled_at = request_body.scheduled_at

        # Atomic: scope ID + index for user filtering BEFORE push
        job.id_hash = user_job_tracker.register_scoped_job( job.id_hash, user_id, session_id )

        # Push to todo queue
        todo_queue.push( job )

        queue_position = todo_queue.size()

        return TestSuiteSubmitResponse(
            status         = "queued",
            job_id         = job.id_hash,
            queue_position = queue_position,
            message        = f"Test suite job queued: {job.last_question_asked}"
        )

    except ValueError as e:
        # Malformed submission input (e.g. unbalanced quotes in pytest_args) —
        # client error, surfaced loudly at submit time, never a silent
        # zero-test run.
        raise HTTPException(
            status_code=400,
            detail=f"Invalid test suite submission: {str( e )}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit test suite job: {str( e )}"
        )
