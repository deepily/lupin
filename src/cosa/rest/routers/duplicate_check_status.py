"""
Duplicate check status router: backlog, drain rate, tokens and the projected zero date.

    GET /api/duplicate-check/status       the whole snapshot as JSON
    GET /api/duplicate-check/job-summary  the fleet's job-summary/1 record
    GET /app/duplicate-check              the same numbers as one small page

All three read the run history (runs.jsonl) of the daily duplicate check and nothing else. They hold only counts, so they need no sign-in.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import cosa.utils.util as cu
from cosa.rest.routers import job_summary
from lupin_mcp import duplicate_check_history as history
from lupin_mcp import duplicate_check_status as status

router = APIRouter( tags=[ "duplicate-check" ] )


def runs_folder():
    """Ensures: returns the folder holding the check's runs, under the project root."""
    return status.folder_of( cu.get_project_root() )


def installed_crontab():
    """
    Read the installed crontab the way the job cards do.

    Ensures:
        - returns ( text, zone ): the text of crontab -l or the host's fresh snapshot of it, and the host's tzinfo when the text came from the snapshot, else None
        - returns ( None, None ) when neither answers, so the page says its schedule is unknown
    """
    _root, _data, deps = job_summary.live_deps()
    return deps.crontab_text(), deps.host_zone()


def snapshot_now():
    """
    Work out the snapshot as of now, with the installed schedule.

    Ensures:
        - returns status.snapshot over the run history, given the crontab text from installed_crontab
        - the time is in the zone the crontab's hours are written in, so a host snapshot read in a UTC container still lines up
    """
    text, zone = installed_crontab()
    moment     = job_summary.clock()
    return status.snapshot( runs_folder(), moment if zone is None else moment.astimezone( zone ), text )


@router.get( "/api/duplicate-check/status" )
def get_status():
    """Ensures: returns status.snapshot of the run history as of now."""
    return snapshot_now()


@router.get( "/api/duplicate-check/job-summary" )
def get_job_summary():
    """Ensures: returns the job-summary/1 record of the run history as of now."""
    return status.job_summary( history.read_lines( runs_folder() ), job_summary.clock() )


@router.get( "/app/duplicate-check", include_in_schema=False )
def get_page():
    """Ensures: returns the status page as text/html that browsers revalidate each load."""
    return HTMLResponse( status.render_html( snapshot_now() ), headers={ "Cache-Control": "no-cache" } )
