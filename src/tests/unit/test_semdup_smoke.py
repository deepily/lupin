"""Unit tests for semdup.smoke: timed backend, percentiles, failure rates, record file."""
import asyncio
import json

import pytest

from cosa.repo.semdup import smoke

META = { "date": "2026-10-25", "host": "box", "repo_sha": "abc", "config_sha": "def" }


class Stub:
    """A backend that returns a reply or raises, with names the wrapper copies."""

    name               = "max-plan"
    server_label       = "label-1"
    temperature_record = "unsettable:bounded-cc"

    def __init__( self, fail=False ):
        self.fail = fail
        self.seen = None

    async def complete( self, model, system_prompt, user_prompt ):
        self.seen = ( model, system_prompt, user_prompt )
        if self.fail: raise RuntimeError( "transport down" )
        return "reply"


def ticks( *values ):
    """Return a clock that gives the values in order."""
    it = iter( values )
    return lambda: next( it )


def rows( seconds, ok=True ):
    """Build call rows from a list of seconds."""
    return [ { "seconds": s, "ok": ok } for s in seconds ]


# ---- TimedBackend ------------------------------------------------------------------------------------------------

def test_the_wrapper_copies_the_names_passes_the_arguments_through_and_times_a_returned_call():
    stub = Stub()
    wrap = smoke.TimedBackend( stub, clock=ticks( 10.0, 12.5 ) )
    assert ( wrap.name, wrap.server_label, wrap.temperature_record ) == ( "max-plan", "label-1", "unsettable:bounded-cc" )
    assert asyncio.run( wrap.complete( "m", "s", "u" ) ) == "reply" and stub.seen == ( "m", "s", "u" )
    assert wrap.calls == [ { "seconds": 2.5, "ok": True } ]


def test_a_call_that_raises_is_timed_marked_not_ok_and_still_raises():
    wrap = smoke.TimedBackend( Stub( fail=True ), clock=ticks( 1.0, 4.0 ) )
    with pytest.raises( RuntimeError, match="transport down" ): asyncio.run( wrap.complete( "m", "s", "u" ) )
    assert wrap.calls == [ { "seconds": 3.0, "ok": False } ]


class Gate:
    """A backend whose calls wait on an event the test sets, so the test controls the overlap."""

    name               = "gate"
    server_label       = "label-g"
    temperature_record = "unsettable:bounded-cc"

    def __init__( self, fail=False ):
        self.fail  = fail
        self.event = None

    async def complete( self, model, system_prompt, user_prompt ):
        await self.event.wait()
        if self.fail: raise RuntimeError( "transport down" )
        return "reply"


def run_overlapping( wrap, count ):
    """Start count calls together, open the gate once all wait, and return the results."""
    async def go():
        wrap.backend.event = asyncio.Event()
        tasks = [ asyncio.ensure_future( wrap.complete( "m", "s", "u" ) ) for _ in range( count ) ]
        await asyncio.sleep( 0 )
        wrap.backend.event.set()
        return await asyncio.gather( *tasks, return_exceptions=True )
    return asyncio.run( go() )


def test_the_peak_in_flight_is_the_most_calls_seen_running_at_once_and_not_a_setting():
    overlap = smoke.TimedBackend( Gate() )
    run_overlapping( overlap, 3 )
    assert overlap.peak_in_flight == 3 and overlap.in_flight == 0 and len( overlap.calls ) == 3
    serial = smoke.TimedBackend( Gate() )
    for _ in range( 3 ): run_overlapping( serial, 1 )
    assert serial.peak_in_flight == 1 and serial.in_flight == 0 and len( serial.calls ) == 3


def test_a_call_that_raises_leaves_nothing_in_flight_and_the_peak_stays():
    wrap    = smoke.TimedBackend( Gate( fail=True ) )
    results = run_overlapping( wrap, 2 )
    assert all( isinstance( r, RuntimeError ) for r in results )
    assert wrap.in_flight == 0 and wrap.peak_in_flight == 2 and [ c[ "ok" ] for c in wrap.calls ] == [ False, False ]


# ---- percentile --------------------------------------------------------------------------------------------------

def test_the_percentile_is_the_nearest_rank_of_the_sorted_values():
    assert smoke.percentile( list( range( 20, 0, -1 ) ), 0.95 ) == 19
    assert smoke.percentile( list( range( 1, 11 ) ), 0.95 ) == 10
    assert smoke.percentile( [ 7 ], 0.95 ) == 7


# ---- build_record ------------------------------------------------------------------------------------------------

def test_the_record_holds_min_median_and_p95_of_every_call_and_the_meta_unchanged():
    record = smoke.build_record( META, rows( [ 5, 20, 1, 13, 7, 2, 19, 3, 11, 4, 18, 6, 16, 8, 9, 10, 12, 14, 15, 17 ] ), 20, 0, 2, 2000, 3 )
    assert record[ "seconds" ] == { "min": 1, "median": 10.5, "p95": 19 } and record[ "calls" ] == 20 and record[ "definitions" ] == 20
    assert all( record[ k ] == v for k, v in META.items() ) and record[ "peak_in_flight" ] == 2


def test_a_failed_call_counts_in_the_timings_as_well_as_in_the_failures():
    record = smoke.build_record( META, rows( [ 1, 2, 3 ] ) + rows( [ 100 ], ok=False ), 4, 0, 1, 10, 1 )
    assert record[ "seconds" ][ "min" ] == 1 and record[ "seconds" ][ "p95" ] == 100 and record[ "raised" ] == 1
    assert record[ "raised_rate" ] == { "fraction": "1/4", "value": 0.25 }


def test_each_rate_is_over_its_own_total_and_five_percent_exactly_does_not_reopen_the_backend():
    calls = rows( [ 1 ] * 19 ) + rows( [ 1 ], ok=False )
    at    = smoke.build_record( META, calls, 20, 1, 1, 10, 1 )
    assert at[ "raised_rate" ][ "fraction" ] == "1/20" and at[ "unjudged_rate" ] == { "fraction": "1/20", "value": 0.05 } and at[ "reopen_backend" ] is False
    over_raised   = smoke.build_record( META, rows( [ 1 ] * 18 ) + rows( [ 1, 1 ], ok=False ), 10, 0, 1, 10, 1 )
    over_unjudged = smoke.build_record( META, rows( [ 1 ] * 40 ), 20, 2, 1, 10, 1 )
    assert over_raised[ "reopen_backend" ] is True and over_unjudged[ "reopen_backend" ] is True
    assert over_unjudged[ "unjudged_rate" ][ "fraction" ] == "1/10" and over_unjudged[ "raised_rate" ][ "fraction" ] == "0/1"
    assert over_raised[ "raised_rate" ][ "fraction" ] == "1/10" and over_raised[ "unjudged_rate" ][ "fraction" ] == "0/1"


def test_the_failure_bar_sits_between_one_in_twenty_and_two_in_thirty_three_and_all_unjudged_reopens():
    below = smoke.build_record( META, rows( [ 1 ] * 20 ), 20, 1, 1, 10, 1 )
    above = smoke.build_record( META, rows( [ 1 ] * 33 ), 33, 2, 1, 10, 1 )
    every = smoke.build_record( META, rows( [ 1 ] ), 4, 4, 1, 10, 1 )
    assert below[ "reopen_backend" ] is False and above[ "reopen_backend" ] is True
    assert above[ "unjudged_rate" ] == { "fraction": "2/33", "value": 2 / 33 }
    assert every[ "reopen_backend" ] is True and every[ "unjudged_rate" ] == { "fraction": "1/1", "value": 1.0 }


def test_the_projection_is_calls_times_median_over_the_peak_in_flight_in_hours_and_fits_at_the_window_exactly():
    calls = rows( [ 9.0 ] * 19 + [ 28.0 ] )
    fits  = smoke.build_record( META, calls, 20, 0, 2, 2000, 2.5 )
    miss  = smoke.build_record( META, calls, 20, 0, 2, 2000, 2.4 )
    assert fits[ "projection" ] == { "client_calls": 2000, "window_hours": 2.5, "hours": 2.5, "fits": True } and miss[ "projection" ][ "fits" ] is False


@pytest.mark.parametrize( "meta, calls, definitions, unjudged, peak, client_calls, window, match", [
    ( { **META, "extra": 1 }, rows( [ 1 ] ), 1, 0, 1, 1, 1, "meta must hold exactly" ),
    ( { "date": "d" }, rows( [ 1 ] ), 1, 0, 1, 1, 1, "meta must hold exactly" ),
    ( META, [], 1, 0, 1, 1, 1, "no call was timed" ),
    ( META, rows( [ 1 ] ), 0, 0, 1, 1, 1, "unjudged must be between 0 and definitions" ),
    ( META, rows( [ 1 ] ), 2, 3, 1, 1, 1, "unjudged must be between 0 and definitions" ),
    ( META, rows( [ 1 ] ), 2, -1, 1, 1, 1, "unjudged must be between 0 and definitions" ),
    ( META, rows( [ 1 ] ), 1, 0, 0, 1, 1, "peak_in_flight must be 1 or more" ),
    ( META, rows( [ 1 ] ), 1, 0, 1, 0, 1, "client_calls must be 1 or more" ),
    ( META, rows( [ 1 ] ), 1, 0, 1, 1, 0, "window_hours must be 1 or more" ),
] )
def test_a_record_that_cannot_be_trusted_is_refused_by_name( meta, calls, definitions, unjudged, peak, client_calls, window, match ):
    with pytest.raises( ValueError, match=match ): smoke.build_record( meta, calls, definitions, unjudged, peak, client_calls, window )


# ---- write_record ------------------------------------------------------------------------------------------------

def test_the_record_is_written_once_under_its_date_and_never_replaced(tmp_path):
    record = smoke.build_record( META, rows( [ 1, 2 ] ), 2, 0, 1, 10, 1 )
    path   = smoke.write_record( tmp_path / "data", record )
    assert path == tmp_path / "data" / "semdup" / "smoke" / "2026-10-25.json" and json.loads( path.read_text( encoding="utf-8" ) ) == record
    with pytest.raises( FileExistsError ): smoke.write_record( tmp_path / "data", record )
    assert json.loads( path.read_text( encoding="utf-8" ) ) == record
