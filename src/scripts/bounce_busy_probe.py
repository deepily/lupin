#!/usr/bin/env python3
"""
Running-job probe for bounce-dev-server.sh.

GETs the unauthenticated GET /api/busy on :7999 and turns the two integers it returns
into an exit code the bounce script reads:

    0  — idle: no job running (inflight_agentic_jobs == 0 and run_queue_size == 0).
         Safe to bounce.
   10  — busy: a job is running (either count > 0). The script refuses the bounce
         unless --force, because a restart would destroy that work.
   20  — unreachable or malformed: could not get a clean two-integer answer.
         Causes: connection refused, timeout, non-200, bad JSON, missing / non-int field. The script
         fails open and proceeds. A broken probe must never block recovery of a wedged
         server, which is the state that makes the probe unreachable.

Trigger is "or": either count > 0 is a live job. The run queue is delete-on-done
(a finished job is removed the instant it completes). Stuck jobs are swept by the
dead-queue watchdog, so neither count is non-zero on an idle box. The guard does not
fire spuriously, which would just train people to reflex --force. Both counts are
printed either way, so the human always sees the depth.

This is a separate helper (like bounce_dev_warn.py) so the guard's script test
can stub it to each exit code without a live server.

Env:
    BOUNCE_BUSY_URL — override the probe URL (default http://localhost:7999/api/busy).
                      The bounce script does not set it; tests do.
"""
import json
import os
import sys
import urllib.request

EXIT_IDLE        = 0
EXIT_BUSY        = 10
EXIT_UNREACHABLE = 20

DEFAULT_URL = "http://localhost:7999/api/busy"


def classify( inflight, run_size ):
    """
    Or-trigger: a job is running if either count is positive.

    Requires:
        - inflight, run_size are ints

    Ensures:
        - returns EXIT_BUSY if inflight > 0 or run_size > 0, else EXIT_IDLE
    """
    return EXIT_BUSY if ( inflight > 0 or run_size > 0 ) else EXIT_IDLE


def probe( url, timeout=3 ):
    """
    Fetch /api/busy and return the exit code the bounce script reads.

    Requires:
        - url points at a GET /api/busy returning {"inflight_agentic_jobs": int,
          "run_queue_size": int}

    Ensures:
        - returns EXIT_BUSY / EXIT_IDLE per classify() on a clean two-int answer
        - returns EXIT_UNREACHABLE on any failure to obtain that answer (network error,
          non-200, bad JSON, missing / non-int field) — reporting the ambiguity
          rather than guessing idle; the script turns that into fail-open
        - prints a one-line human summary to stderr in every case
    """
    try:
        with urllib.request.urlopen( url, timeout=timeout ) as r:
            data = json.loads( r.read().decode() )
        inflight = int( data[ "inflight_agentic_jobs" ] )
        run_size = int( data[ "run_queue_size" ] )
    except Exception as e:
        print( f"[busy-probe] UNREACHABLE ({type( e ).__name__}: {e}) — failing OPEN", file=sys.stderr )
        return EXIT_UNREACHABLE

    code  = classify( inflight, run_size )
    state = "BUSY" if code == EXIT_BUSY else "idle"
    print( f"[busy-probe] {state}: inflight_agentic_jobs={inflight} run_queue_size={run_size}", file=sys.stderr )
    return code


def main():
    return probe( os.environ.get( "BOUNCE_BUSY_URL", DEFAULT_URL ) )


if __name__ == "__main__":
    sys.exit( main() )
