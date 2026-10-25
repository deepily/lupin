"""The live smoke record: seconds per call, failure rates and the measured throughput."""
import json
import math
import pathlib
import statistics
import time
from fractions import Fraction

from cosa.repo.doc_lint import model_transport

FAILURE_BAR   = Fraction( 5, 100 )
SMOKE_FOLDER  = ( "semdup", "smoke" )
META_KEYS     = ( "date", "host", "repo_sha", "config_sha" )


class TimedBackend:
    """Wrap a judge backend, time each call it makes and the run as a whole."""

    def __init__( self, backend, clock=time.monotonic ):
        """
        Wrap a backend.

        Requires:
            - backend has name, server_label, temperature_record and an async complete( model, system, user )
            - clock is a callable giving seconds as a number

        Ensures:
            - name, server_label and temperature_record equal the wrapped backend's
            - calls is an empty list that complete fills, one row { seconds, ok } per call
            - in_flight and peak_in_flight are 0, and first_start and last_end are None
        """
        self.backend            = backend
        self.clock              = clock
        self.name               = backend.name
        self.server_label       = backend.server_label
        self.temperature_record = backend.temperature_record
        self.calls              = []
        self.in_flight          = 0
        self.peak_in_flight     = 0
        self.first_start        = None
        self.last_end           = None

    async def complete( self, model, system_prompt, user_prompt ):
        """
        Make the wrapped call and record how long it took.

        Requires:
            - the arguments are as the wrapped backend's complete takes them

        Ensures:
            - returns the wrapped reply unchanged
            - one row is appended to calls: ok is True when the call returned, False when it raised
            - peak_in_flight is at least the number of calls that were waiting or running at once, this one included
            - first_start is the clock at the first call's start and last_end the clock at the latest call's end
            - in_flight is back to what it was before the call, whether it returned or raised

        Raises:
            - whatever the wrapped call raises, after its row is recorded
        """
        start = self.clock()
        if self.first_start is None: self.first_start = start
        self.in_flight     += 1
        self.peak_in_flight = max( self.peak_in_flight, self.in_flight )
        ok = False
        try:
            reply = await self.backend.complete( model, system_prompt, user_prompt )
            ok    = True
        finally:
            self.last_end   = self.clock()
            self.in_flight -= 1
            self.calls.append( { "seconds": self.last_end - start, "ok": ok } )
        return reply

    @property
    def elapsed( self ):
        """
        Return the seconds from the first call's start to the latest call's end.

        Requires:
            - none

        Ensures:
            - returns 0 when no call has finished
        """
        return 0 if self.last_end is None else self.last_end - self.first_start


def configure_cli( cli_path, cwd=None ):
    """
    Point later model calls at a Claude Code binary and return its version.

    The SDK's bundled binary (2.1.92 when this was measured) refuses the pinned model, so a live run must name the installed binary.

    Requires:
        - cli_path is the path of an executable Claude Code binary; cwd is None or an existing directory

    Ensures:
        - model_transport uses cli_path for this process from now on
        - returns the first line of the binary's --version output, for judge.ledger_binding

    Raises:
        - ValueError if cli_path is not an executable file or cwd is not a directory
    """
    model_transport.configure( cli_path=cli_path, cwd=cwd )
    return model_transport.cli_version( cli_path )


def percentile( values, share ):
    """
    Return the nearest-rank percentile of a list of numbers.

    Requires:
        - values is a non-empty list of numbers
        - share is a number above 0 and at most 1

    Ensures:
        - returns the value at rank ceil( share * n ) of the sorted list
    """
    ordered = sorted( values )
    return ordered[ math.ceil( share * len( ordered ) ) - 1 ]


def build_record( meta, calls, definitions, unjudged, peak_in_flight, elapsed, client_calls, window_hours ):
    """
    Build the smoke record from the timed calls of one run.

    Requires:
        - meta holds exactly date, host, repo_sha and config_sha
        - calls is the list TimedBackend.calls holds, with at least one row
        - definitions is the number of definitions judged and unjudged is the number whose reply could not be read
        - peak_in_flight is TimedBackend.peak_in_flight; it counts calls waiting inside a backend that serialises them, so it is information and not the concurrency
        - elapsed is TimedBackend.elapsed: the seconds the whole run took
        - client_calls is the number of calls one client needs, and window_hours the hours a night's run may take; both are set by the caller

    Ensures:
        - seconds holds min, median and p95 of every call, whether it returned or raised
        - raised_rate is the calls that raised over all calls, and unjudged_rate the unjudged definitions over the definitions, each as a fraction string and a number
        - reopen_backend is True when either rate is above 5%
        - projection holds the hours client_calls would take at the measured seconds per call (elapsed over calls), and whether they fit window_hours

    Raises:
        - ValueError if meta has other keys, calls is empty, definitions is below 1, unjudged is outside 0 to definitions, elapsed is not above 0, or peak_in_flight, client_calls or window_hours is below 1
    """
    if set( meta ) != set( META_KEYS ): raise ValueError( f"meta must hold exactly {list( META_KEYS )}, got {sorted( meta )}" )
    if not calls: raise ValueError( "no call was timed" )
    if definitions < 1 or not 0 <= unjudged <= definitions: raise ValueError( f"unjudged must be between 0 and definitions ({definitions}), got {unjudged}" )
    if elapsed <= 0: raise ValueError( f"elapsed must be above 0, got {elapsed}" )
    for name, value in ( ( "peak_in_flight", peak_in_flight ), ( "client_calls", client_calls ), ( "window_hours", window_hours ) ):
        if value < 1: raise ValueError( f"{name} must be 1 or more, got {value}" )
    seconds = [ c[ "seconds" ] for c in calls ]
    raised  = sum( 1 for c in calls if not c[ "ok" ] )
    rates   = { "raised_rate": Fraction( raised, len( calls ) ), "unjudged_rate": Fraction( unjudged, definitions ) }
    median  = statistics.median( seconds )
    hours   = client_calls * elapsed / len( calls ) / 3600
    return { **meta, "calls": len( calls ), "definitions": definitions, "raised": raised, "unjudged": unjudged, "peak_in_flight": peak_in_flight, "elapsed": elapsed,
             "seconds": { "min": min( seconds ), "median": median, "p95": percentile( seconds, 0.95 ) },
             **{ name: { "fraction": f"{r.numerator}/{r.denominator}", "value": float( r ) } for name, r in rates.items() },
             "reopen_backend": any( r > FAILURE_BAR for r in rates.values() ),
             "projection": { "client_calls": client_calls, "window_hours": window_hours, "hours": hours, "fits": hours <= window_hours } }


def write_record( data_dir, record ):
    """
    Write the record to <data>/semdup/smoke/<date>.json once.

    Requires:
        - record came from build_record

    Ensures:
        - returns the path written
        - the folder is made when missing

    Raises:
        - FileExistsError if a record for that date exists, because a measurement is never replaced
    """
    folder = pathlib.Path( data_dir ).joinpath( *SMOKE_FOLDER )
    folder.mkdir( parents=True, exist_ok=True )
    path = folder / f"{record[ 'date' ]}.json"
    with open( path, "x", encoding="utf-8" ) as f: json.dump( record, f, indent=2, sort_keys=True )
    return path
