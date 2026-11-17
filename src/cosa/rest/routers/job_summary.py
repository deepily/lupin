"""
Background-job reporting: one endpoint for every job, and Run now.

    GET  /api/jobs/summary        every registered job with its health, computed by the reader
    POST /api/jobs/{job}/run      start one run of a job now (Rick's login only)

The page computes nothing about health. Design: planning-is-prompting src/rnd/2026.11.07-background-job-reporting-format.md.
"""
import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

import cosa.rest.job_service as svc
import cosa.utils.util as cu
from cosa.rest.middleware.api_key_auth import authenticated_account_email, require_api_key_or_jwt
from cosa.rest.task_priority_firewall import caller_is_operator

router = APIRouter( prefix="/api/jobs", tags=[ "jobs" ] )


def live_deps():
    """
    Build the real inputs for this server.

    Ensures:
        - returns the Lupin root, the reuse-review data folder and the live inputs; tests replace this function
    """
    from cosa.rest.routers.reuse_candidates import data_root         # the container derives a wrong folder without LUPIN_REUSE_REVIEW_DATA_ROOT; data_root honours it
    root = cu.get_project_root()
    data = data_root()
    return root, data, svc.LiveDeps( root, data )


def clock():
    """
    Read the current local time.

    Ensures:
        - returns an aware datetime; tests replace this function with a fixed one
    """
    return datetime.datetime.now().astimezone()


@router.get( "/summary", summary="Health of every background job", description="One entry per registered job: state, reasons, debts, schedule, evidence. Health is computed here, never by the page." )
def jobs_summary(
    _user: Annotated[ str, Depends( require_api_key_or_jwt ) ],
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
):
    """
    Answer with the whole accordion.

    Requires:
        - the caller is authenticated (API key or login)

    Ensures:
        - returns the jobs-summary/1 document with caller_is_operator, true only for the operator login (the rule Run now enforces)
        - 500 with the cause when the registry is unreadable or invalid
    """
    root, data, deps = live_deps()
    try:
        got = svc.build_response( root, data, clock(), deps )
    except ( OSError, ValueError ) as error:
        raise HTTPException( status_code=500, detail=f"job registry unusable: {error}" )
    return { **got, "caller_is_operator": caller_is_operator( account_email ) }


@router.post( "/{job}/run", summary="Run one job now", description="Starts one run outside the schedule, with trigger hand. Refused while the job's run lock is held. Rick's login only." )
def run_job_now(
    job: str,
    target: Optional[ str ] = None,
    _user: Annotated[ str, Depends( require_api_key_or_jwt ) ] = None,
    account_email: Annotated[ str | None, Depends( authenticated_account_email ) ] = None,
):
    """
    Start a run of one job.

    Requires:
        - the caller is logged in as the operator; an API-key caller has no login and is refused

    Ensures:
        - 403 for any other caller, before the registry is read
        - otherwise the status and body of job_service.run_now: 200 started, 404 unknown job, 409 lock held, 422 not runnable
    """
    if not caller_is_operator( account_email ): raise HTTPException( status_code=403, detail="Run now is for the operator login only." )
    root, data, deps = live_deps()
    status, body = svc.run_now( root, data, job, target, deps, clock() )
    return JSONResponse( status_code=status, content=body )
