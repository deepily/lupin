"""
Duplicate check status router: backlog, drain rate, tokens and the projected zero date.

    GET /api/duplicate-check/status       the whole snapshot as JSON
    GET /api/duplicate-check/job-summary  the fleet's job-summary/1 record
    GET /app/duplicate-check              the same numbers as one small page

All three read the run history (runs.jsonl) of the daily duplicate check and nothing else. They hold only counts, so they need no sign-in.
"""
import datetime

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import cosa.utils.util as cu
from lupin_mcp import duplicate_check_history as history
from lupin_mcp import duplicate_check_status as status

router = APIRouter( tags=[ "duplicate-check" ] )


def runs_folder():
    """Ensures: returns the folder holding the check's runs, under the project root."""
    return status.folder_of( cu.get_project_root() )


def now():
    """Ensures: returns the present time as a timezone-aware datetime."""
    return datetime.datetime.now().astimezone()


@router.get( "/api/duplicate-check/status" )
def get_status():
    """Ensures: returns status.snapshot of the run history as of now."""
    return status.snapshot( runs_folder(), now() )


@router.get( "/api/duplicate-check/job-summary" )
def get_job_summary():
    """Ensures: returns the job-summary/1 record of the run history as of now."""
    return status.job_summary( history.read_lines( runs_folder() ), now() )


@router.get( "/app/duplicate-check", include_in_schema=False )
def get_page():
    """Ensures: returns the status page as text/html that browsers revalidate each load."""
    return HTMLResponse( status.render_html( status.snapshot( runs_folder(), now() ) ), headers={ "Cache-Control": "no-cache" } )
