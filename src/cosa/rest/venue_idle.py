"""
Is a Lupin test venue actually free? (row e6b8fe56)

THE DEFECT THIS REPLACES
    Every procedure that "verified :8000 idle" read `/api/queue/pool-status` and
    concluded idle from `monopolize_id` being null. MEASURED 2026-08-25 by driving
    the real `RunningFifoQueue.get_pool_status()` against real queues:

        state                                    monopolize_id   OLD VERDICT
        2 jobs QUEUED in todo, none started      null            "IDLE"   <- wrong
        + 1 job RUNNING INLINE on the consumer   null            "IDLE"   <- wrong
        + 1 job SCHEDULED for the future         null            "IDLE"   <- wrong
        + 1 job RUNNING in the shared pool       null            "IDLE"   <- wrong
        + a MONOPOLIZER holding the slot         "mono-1"        "BUSY"

    `monopolize_id` moves for exactly ONE condition: a monopolize-flagged job that
    has already STARTED. Queued work, inline consumer-thread work (row 99b09840) and
    ordinary shared-pool work are all invisible to it. The field is honest about what
    it measures; it was being asked a question it cannot answer.

WHAT IDLE MEANS HERE
    A venue is free iff NOTHING IS RUNNING and NOTHING IS WAITING, on every lane:
    the run FIFO, the ingress todo FIFO, the shared agentic pool, and the dedicated
    monopolize slot.

THE RULE THAT MATTERS MOST: UNKNOWN IS NOT IDLE
    A signal that could not be read yields UNKNOWN, never IDLE. The original defect
    is precisely "a signal that did not move was read as proof of absence", so a
    check that answers IDLE while missing an input reproduces the bug one level up.
    A container that predates `todo_queue_size` therefore reports UNKNOWN -- visibly
    unable to answer -- rather than confidently wrong.

WHY NOT /api/get-queue/{todo,run}
    They are USER-FILTERED. Measured 2026-08-25 with the gate account: the default
    read is scoped to the caller, and `?user_filter=*` returns 403 because that
    account is not an admin. A peer's queued job is invisible through that door, so
    it can add evidence of work but can never prove its absence. `/api/busy` reads
    the queue objects directly, is unfiltered, and needs no credential.

Stdlib only, and no `cosa` imports, so the gate rig can run it on the host with
plain `python3` and nothing but PYTHONPATH=src:

    PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000

Exit codes are the branch a caller reads: 0 IDLE, 1 BUSY, 2 UNKNOWN.
"""

import json
import sys
import urllib.request

IDLE    = "IDLE"
BUSY    = "BUSY"
UNKNOWN = "UNKNOWN"

EXIT_IDLE    = 0
EXIT_BUSY    = 1
EXIT_UNKNOWN = 2

_EXIT_FOR = { IDLE: EXIT_IDLE, BUSY: EXIT_BUSY, UNKNOWN: EXIT_UNKNOWN }

# Counts: any value > 0 means the venue is occupied.
COUNT_SIGNALS = ( "run_queue_size", "todo_queue_size", "inflight_agentic_jobs" )

# Flags: True means the venue is occupied.
FLAG_SIGNALS  = ( "monopolize_inflight", )

# Every signal is REQUIRED. A missing one is the UNKNOWN arm, not a free pass --
# see "UNKNOWN IS NOT IDLE" above.
REQUIRED_SIGNALS = COUNT_SIGNALS + FLAG_SIGNALS

DEFAULT_PORT = "8000"


def decide( signals ):
    """
    Turn a bag of observed signals into a venue verdict.

    Requires:
        - signals is a dict mapping signal name -> observed value, where a value of
          None means "could not be read"

    Ensures:
        - returns ( verdict, reasons ) with verdict in { IDLE, BUSY, UNKNOWN }
        - BUSY wins over UNKNOWN: proven occupancy is already a decision, and a
          caller that knows to stay off the venue gains nothing from ambiguity
        - UNKNOWN whenever any REQUIRED_SIGNALS entry is missing or None and nothing
          proved occupancy
        - IDLE only when every required signal was read AND every one is zero / False
        - reasons is a non-empty list of human-readable strings in every arm

    Raises:
        - None
    """
    busy_reasons    = []
    unknown_reasons = []

    for name in COUNT_SIGNALS:
        value = signals.get( name )
        if value is None:
            unknown_reasons.append( f"{name} could not be read" )
        elif value > 0:
            busy_reasons.append( f"{name}={value}" )

    for name in FLAG_SIGNALS:
        value = signals.get( name )
        if value is None:
            unknown_reasons.append( f"{name} could not be read" )
        elif value:
            busy_reasons.append( f"{name}=True (holder: {signals.get( 'monopolize_id' )})" )

    if busy_reasons:
        return BUSY, busy_reasons
    if unknown_reasons:
        return UNKNOWN, unknown_reasons
    return IDLE, [ "every lane reported empty: " + ", ".join( REQUIRED_SIGNALS ) ]


def read_signals( port=DEFAULT_PORT, timeout=10, opener=None ):
    """
    Fetch the unfiltered occupancy signals from GET /api/busy.

    Requires:
        - port is the venue's port as a string or int
        - opener, when supplied, behaves like urllib.request.urlopen (test seam)

    Ensures:
        - returns a dict carrying every REQUIRED_SIGNALS key, each either the
          observed value or None when it was absent or unreadable
        - a transport failure, non-JSON body, or missing field yields Nones rather
          than an exception -- the UNKNOWN arm exists to carry exactly that
        - never raises on a server that is down, old, or answering nonsense

    Raises:
        - None
    """
    fetch   = opener or urllib.request.urlopen
    url     = f"http://localhost:{port}/api/busy"
    signals = { name: None for name in REQUIRED_SIGNALS }
    signals[ "monopolize_id" ] = None
    signals[ "error" ]         = None

    try:
        with fetch( url, timeout=timeout ) as resp:
            payload = json.loads( resp.read().decode() )
    except Exception as e:                    # every failure is UNKNOWN, never a raise
        signals[ "error" ] = f"{type( e ).__name__}: {e}"
        return signals

    for name in COUNT_SIGNALS:
        if name in payload:
            signals[ name ] = int( payload[ name ] )
    for name in FLAG_SIGNALS:
        if name in payload:
            signals[ name ] = bool( payload[ name ] )
    signals[ "monopolize_id" ] = payload.get( "monopolize_id" )
    return signals


def format_report( port, signals, verdict, reasons ):
    """
    Render the verdict a human reads before deciding to recreate a container.

    Requires:
        - verdict is one of IDLE / BUSY / UNKNOWN
        - reasons is a non-empty list of strings

    Ensures:
        - returns a multi-line string naming the port, the verdict, every reason,
          and the observed value of every required signal
        - states the UNKNOWN arm's meaning inline, so a reader who has never seen
          this output does not have to guess whether it is safe

    Raises:
        - None
    """
    lines = [ f":{port} -- {verdict}" ]
    for reason in reasons:
        lines.append( f"  . {reason}" )
    lines.append( "  signals: " + ", ".join(
        f"{name}={signals.get( name )!r}" for name in REQUIRED_SIGNALS
    ) )
    if signals.get( "error" ):
        lines.append( f"  read failed: {signals[ 'error' ]}" )
    if verdict == UNKNOWN:
        lines.append( "  UNKNOWN IS NOT IDLE -- do not recreate, do not submit." )
        missing = [ n for n in REQUIRED_SIGNALS if signals.get( n ) is None ]
        if missing == [ "todo_queue_size" ]:
            lines.append( "  Everything else read clean and ONLY the todo depth is missing, which "
                          "means this container predates row e6b8fe56. It cannot tell you whether "
                          "work is WAITING -- the exact hole this check exists to close. BOUNCE "
                          "the venue so it serves the field (a code pickup is a bounce; "
                          "--force-recreate is for mount/env changes and is not what this needs), "
                          "or confirm with the fleet before you act. Do not read this as idle." )
    return "\n".join( lines )


def check( port=DEFAULT_PORT, timeout=10, opener=None ):
    """
    Read the venue and decide, in one call.

    Requires:
        - port names a reachable Lupin venue, or does not -- an unreachable venue is
          a legitimate UNKNOWN, not an error

    Ensures:
        - returns ( verdict, report_text, signals )

    Raises:
        - None
    """
    signals          = read_signals( port=port, timeout=timeout, opener=opener )
    verdict, reasons = decide( signals )
    return verdict, format_report( port, signals, verdict, reasons ), signals


def main( argv=None ):
    """
    CLI entry point: print the report, return the exit code a caller can branch on.

    Requires:
        - argv is the argument list without the program name, or None for sys.argv

    Ensures:
        - prints the report to stdout
        - returns EXIT_IDLE (0) / EXIT_BUSY (1) / EXIT_UNKNOWN (2)
        - an unrecognised argument is ignored rather than fatal, so this can never be
          the reason a gate step fails to produce a reading

    Raises:
        - None
    """
    args = list( sys.argv[ 1: ] if argv is None else argv )
    port = DEFAULT_PORT
    i    = 0
    while i < len( args ):
        if args[ i ] == "--port" and i + 1 < len( args ):
            port = args[ i + 1 ]
            i += 2
        else:
            i += 1

    verdict, report, _ = check( port=port )
    print( report )
    return _EXIT_FOR[ verdict ]


if __name__ == "__main__":
    sys.exit( main() )
