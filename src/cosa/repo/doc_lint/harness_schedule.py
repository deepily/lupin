"""
Off-peak scheduling and submission for the judge harness (plan 1, section 5).

The Max plan has rolling usage windows and the host is not up around the clock, so a batch run
is scheduled for 10 AM to 1 PM Eastern, never the dead window overnight. It is submitted through
POST /api/v2/submit with the command "agent router go to claude code", as CLAUDE.md prescribes.
"""

import datetime
import shlex
from zoneinfo import ZoneInfo

import requests

ZONE          = ZoneInfo( "America/New_York" )
WINDOW_START  = 10
WINDOW_END    = 13
COMMAND       = "agent router go to claude code"


def scheduled_at( now=None ):
    """
    Return an ISO timestamp inside the 10 AM to 1 PM Eastern window.

    Requires:
        - now is a timezone-aware datetime, or None for the current time

    Ensures:
        - inside the window, returns now
        - before the window, returns 10:00 the same day
        - after the window, returns 10:00 the next day
    """
    local = ( datetime.datetime.now( ZONE ) if now is None else now.astimezone( ZONE ) )
    if WINDOW_START <= local.hour < WINDOW_END: return local.isoformat()
    day = local.date() if local.hour < WINDOW_START else local.date() + datetime.timedelta( days=1 )
    return datetime.datetime( day.year, day.month, day.day, WINDOW_START, tzinfo=ZONE ).isoformat()


def build_submit_payload( argv, when ):
    """
    Build the /api/v2/submit body that runs one harness command as a bounded job.

    Requires:
        - argv is the runner's argument list, a fixed template that holds no pair text and no
          user text; when is an ISO timestamp

    Ensures:
        - the job is BOUNDED, so the Max plan covers it
        - scheduled_at is top level, outside the command's args
        - every argument is shell-quoted, so a path with a space or a quote stays one argument
    """
    prompt = f"Run exactly this command, wait for it to finish, and reply with its last line: {shlex.join( argv )}"
    return { "command": COMMAND, "args": { "prompt": prompt, "task_type": "BOUNDED" }, "scheduled_at": when }


def submit( payload, base_url, email, password, post=None ):
    """
    Log in and submit a payload to /api/v2/submit.

    Requires:
        - payload comes from build_submit_payload; email and password are the test credentials
        - post, when given, stands in for requests.post

    Ensures:
        - returns the parsed JSON body of the submit reply

    Raises:
        - RuntimeError if the login or the submit answers anything but 200
    """
    post  = requests.post if post is None else post
    login = post( f"{base_url}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    if login.status_code != 200: raise RuntimeError( f"login to {base_url} answered {login.status_code}" )
    token = login.json()[ "tokens" ][ "access_token" ]
    reply = post( f"{base_url}/api/v2/submit", headers={ "Authorization": f"Bearer {token}" }, json=payload, timeout=10 )
    if reply.status_code != 200: raise RuntimeError( f"submit answered {reply.status_code}: {reply.text[ :300 ]}" )
    return reply.json()
