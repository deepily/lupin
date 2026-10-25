"""The live smoke record: seconds per call, failure rates and the peak calls in flight."""
import json
import math
import pathlib
import statistics
import time
from fractions import Fraction

FAILURE_BAR   = Fraction( 5, 100 )
SMOKE_FOLDER  = ( "semdup", "smoke" )
META_KEYS     = ( "date", "host", "repo_sha", "config_sha" )


class TimedBackend:
    """Wrap a judge backend, time each call it makes and count how many are in flight at once."""

    def __init__( self, backend, clock=time.monotonic ):
        """
        Wrap a backend.

        Requires:
            - backend has name, server_label, temperature_record and an async complete( model, system, user )
            - clock is a callable giving seconds as a number

        Ensures:
            - name, server_label and temperature_record equal the wrapped backend's
            - calls is an empty list that complete fills, one row { seconds, ok } per call
            - in_flight and peak_in_flight are 0
        """
        self.backend            = backend
        self.clock              = clock
        self.name               = backend.name
        self.server_label       = backend.server_label
        self.temperature_record = backend.temperature_record
        self.calls              = []
        self.in_flight          = 0
        self.peak_in_flight     = 0

    async def complete( self, model, system_prompt, user_prompt ):
        """
        Make the wrapped call and record how long it took.

        Requires:
            - the arguments are as the wrapped backend's complete takes them

        Ensures:
            - returns the wrapped reply unchanged
            - one row is appended to calls: ok is True when the call returned, False when it raised
            - peak_in_flight is at least the number of calls that were running at once, this one included
            - in_flight is back to what it was before the call, whether it returned or raised

        Raises:
            - whatever the wrapped call raises, after its row is recorded
        """
        start = self.clock()
        self.in_flight     += 1
        self.peak_in_flight = max( self.peak_in_flight, self.in_flight )
        try:
            reply = await self.backend.complete( model, system_prompt, user_prompt )
        except Exception:
            self.calls.append( { "seconds": self.clock() - start, "ok": False } )
            raise
        finally:
            self.in_flight -= 1
        self.calls.append( { "seconds": self.clock() - start, "ok": True } )
        return reply


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


def build_record( meta, calls, definitions, unjudged, peak_in_flight, client_calls, window_hours ):
    """
    Build the smoke record from the timed calls of one run.

    Requires:
        - meta holds exactly date, host, repo_sha and config_sha
        - calls is the list TimedBackend.calls holds, with at least one row
        - definitions is the number of definitions judged and unjudged is the number whose reply could not be read
        - peak_in_flight is TimedBackend.peak_in_flight: the most calls seen running at once, observed and not the setting asked for
        - client_calls is the number of calls one client needs, and window_hours the hours a night's run may take; both are set by the caller

    Ensures:
        - seconds holds min, median and p95 of every call, whether it returned or raised
        - raised_rate is the calls that raised over all calls, and unjudged_rate the unjudged definitions over the definitions, each as a fraction string and a number
        - reopen_backend is True when either rate is above 5%
        - projection holds the hours client_calls would take at the median and the peak in flight, and whether they fit window_hours

    Raises:
        - ValueError if meta has other keys, calls is empty, definitions is below 1, unjudged is outside 0 to definitions, or peak_in_flight, client_calls or window_hours is below 1
    """
    if set( meta ) != set( META_KEYS ): raise ValueError( f"meta must hold exactly {list( META_KEYS )}, got {sorted( meta )}" )
    if not calls: raise ValueError( "no call was timed" )
    if definitions < 1 or not 0 <= unjudged <= definitions: raise ValueError( f"unjudged must be between 0 and definitions ({definitions}), got {unjudged}" )
    for name, value in ( ( "peak_in_flight", peak_in_flight ), ( "client_calls", client_calls ), ( "window_hours", window_hours ) ):
        if value < 1: raise ValueError( f"{name} must be 1 or more, got {value}" )
    seconds = [ c[ "seconds" ] for c in calls ]
    raised  = sum( 1 for c in calls if not c[ "ok" ] )
    rates   = { "raised_rate": Fraction( raised, len( calls ) ), "unjudged_rate": Fraction( unjudged, definitions ) }
    median  = statistics.median( seconds )
    hours   = client_calls * median / peak_in_flight / 3600
    return { **meta, "calls": len( calls ), "definitions": definitions, "raised": raised, "unjudged": unjudged, "peak_in_flight": peak_in_flight,
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
