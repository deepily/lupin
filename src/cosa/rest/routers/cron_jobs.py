"""
Scheduled-job switches: list each cron job's switch, and let an administrator flip it.

    GET /api/cron-jobs                   one row per registry job, the switch read fresh from the INI file
    PUT /api/cron-jobs/{job}/enabled     flip one switch (administrator login only)

A flip edits `cron job <job> enabled` in lupin-app.ini, which the job reads at its next start.
It does not stop a run already in progress. After a flip every connected client gets the
`cron_job_switch_changed` WebSocket event.
"""
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

import cosa.utils.util as cu
from cosa.rest import cron_job_switches as switches
from cosa.rest import job_registry as jr
from cosa.rest.auth_middleware import get_current_user_optional, require_admin
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers.arbiter import _refuse_api_key_only
from lupin_mcp import fleet_cap_ini_io

router = APIRouter( prefix="/api", tags=[ "cron-jobs" ] )

refuse_api_key_switch_flipper = _refuse_api_key_only( "Only an administrator may flip a scheduled job's switch.", "refuse_api_key_switch_flipper" )


class CronJobSwitchIn( BaseModel ):
    """
    Body for PUT /api/cron-jobs/{job}/enabled.

    `on` is a bare JSON boolean. Any other field, and any other type, is a 422.
    """

    model_config = ConfigDict( extra="forbid" )
    on : StrictBool = Field( description="True lets the job run, false makes its next start exit without work." )


def _registry_jobs() -> list:
    """
    The registry's jobs.

    Ensures:
        - returns the `jobs` list of the registry under the Lupin root
        - 500 with the cause when the registry is unreadable or invalid
    """
    try:
        return jr.load_registry( cu.get_project_root() )[ "jobs" ]
    except ( OSError, ValueError ) as error:
        raise HTTPException( status_code=500, detail=f"job registry unusable: {error}" )


async def _announce( row: Dict[ str, Any ] ) -> None:
    """
    Tell every connected client the switch flipped, and never fail the flip because of it.

    Requires:
        - the flip is already written to the file

    Ensures:
        - emits `cron_job_switch_changed` with the row to every connected client
        - a failure is printed and swallowed
    """
    try:
        import lupin_app.main as main_module
        await main_module.websocket_manager.emit_to_all( switches.EVENT_NAME, row )
    except Exception as error:
        print( f"[CRON-JOBS] switch event failed: {type( error ).__name__}: {error}", flush=True )


@router.get(
    "/cron-jobs",
    summary     = "Every scheduled job with its on/off switch",
    description = "One row per registry job: job, title, schedule, key, enabled (read fresh from "
                  "the configuration file; null when the file does not say), last_changed_by and "
                  "last_changed_at. caller_is_admin is true only for an administrator login, so a "
                  "client can show the switches read-only to everyone else."
)
async def get_cron_jobs(
    _user : Annotated[ str, Depends( require_api_key_or_jwt ) ],
    login : Annotated[ Optional[ Dict ], Depends( get_current_user_optional ) ] = None
):
    """
    List the switches.

    Requires:
        - the caller is authenticated (API key or login)

    Ensures:
        - returns { jobs, caller_is_admin }, one job row per registry job, in registry order
        - caller_is_admin is false for an API key alone
        - 500 with the cause when the registry is unusable
    """
    is_admin = login is not None and "admin" in login.get( "roles", [] )
    return { "jobs": switches.build_rows( _registry_jobs() ), "caller_is_admin": is_admin }


@router.put(
    "/cron-jobs/{job}/enabled",
    summary     = "Admin: turn one scheduled job on or off",
    description = "Body { on: bool }. Writes `cron job <job> enabled` to the configuration file "
                  "and returns the row re-read from the file. Administrator login only: an "
                  "API-key caller or a non-admin login is refused with 403 and nothing is written. "
                  "An unknown job is a 404."
)
async def put_cron_job_enabled(
    job      : str,
    body     : CronJobSwitchIn,
    _no_key  : Annotated[ None, Depends( refuse_api_key_switch_flipper ) ],
    user     : Annotated[ Dict, Depends( require_admin ) ]
):
    """
    Flip one switch and report what the file now says.

    Requires:
        - an administrator login (403 for an API key alone or a non-admin user)
        - body.on is a bare boolean (422 otherwise)

    Ensures:
        - 404 for a job the registry does not list, writing nothing
        - 409 naming the job when it does not read its switch (`honoured` false), writing nothing
        - the attribution record is written first and the configuration file second
        - a key the file lacks, or defines twice, answers 409 with the writer's message, writing nothing
        - an OS error answers 500 naming the cause, and nothing is announced
        - on success every connected client is told, and a failed announcement does not fail the flip
        - returns the row read back from the file
    """
    entries = _registry_jobs()
    entry   = next( ( e for e in entries if e[ "job" ] == job ), None )
    if entry is None:
        raise HTTPException( status_code=404, detail=f"no scheduled job named {job!r}" )
    if not switches.is_honoured( entry ):
        raise HTTPException( status_code=409, detail=f"{job!r} does not read its switch yet, so a flip would change nothing; nothing was written" )
    who = user.get( "email" ) or user.get( "uid" ) or "unknown"
    try:
        switches.write_switch( job, body.on, who )
    except ( fleet_cap_ini_io.KeyNotFound, fleet_cap_ini_io.KeyDefinedTwice ) as refusal:
        raise HTTPException( status_code=409, detail=str( refusal ) )
    except OSError as failure:
        raise HTTPException(
            status_code = 500,
            detail      = f"The switch for {job!r} could not be written: {failure}. "
                          f"Read GET /api/cron-jobs to see what the file says now."
        )
    row = switches.build_row( entry, switches.read_attribution() )
    await _announce( row )
    return row
