#!/usr/bin/env python3
"""
ping_throttle.prune_window: the one rolling-window prune.

Every caller that keeps what happened in the last N seconds goes through it.
So the boundary, the future-dated entry and the junk stamp are pinned here once.

Venue: :7999-eligible / local, pure.
"""
import datetime
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter import ping_throttle as pt

NOW = datetime.datetime( 2026, 11, 11, 12, 0, 0, tzinfo=datetime.timezone.utc )


def _ago( seconds ):
    """Return the aware datetime that is `seconds` before the test time; negative is the future."""
    return NOW - datetime.timedelta( seconds=seconds )


def test_keeps_entries_inside_the_window_and_drops_older_ones_in_input_order():
    entries = [ _ago( 10 ), _ago( 500 ), _ago( 60 ) ]
    assert pt.prune_window( entries, NOW, 100 ) == [ _ago( 10 ), _ago( 60 ) ]


def test_an_entry_exactly_one_window_old_is_kept_unless_strict():
    entries = [ _ago( 100 ), _ago( 99 ), _ago( 101 ) ]
    assert pt.prune_window( entries, NOW, 100 ) == [ _ago( 100 ), _ago( 99 ) ]
    assert pt.prune_window( entries, NOW, 100, strict=True ) == [ _ago( 99 ) ]


def test_a_future_entry_is_kept_by_default_and_dropped_with_drop_future():
    entries = [ _ago( -30 ), _ago( 5 ) ]
    assert pt.prune_window( entries, NOW, 100 ) == entries
    assert pt.prune_window( entries, NOW, 100, drop_future=True ) == [ _ago( 5 ) ]


def test_plain_numbers_work_like_datetimes():
    assert pt.prune_window( [ 1000.0, 950.0, 880.0 ], 1000.0, 100 ) == [ 1000.0, 950.0 ]
    assert pt.prune_window( [ 900.0 ], 1000.0, 100 ) == [ 900.0 ]
    assert pt.prune_window( [ 900.0 ], 1000.0, 100, strict=True ) == []


def test_stamp_reads_the_time_out_of_an_entry_and_the_entry_is_what_comes_back():
    rows = [ { "at": 990.0, "n": 1 }, { "at": 100.0, "n": 2 }, ( "tuple", 995.0 ) ]
    got  = pt.prune_window( rows[ :2 ], 1000.0, 50, stamp=lambda r: r[ "at" ] )
    assert got == [ { "at": 990.0, "n": 1 } ]
    assert got[ 0 ] is rows[ 0 ]
    assert pt.prune_window( rows[ 2: ], 1000.0, 50, stamp=lambda r: r[ 1 ] ) == [ ( "tuple", 995.0 ) ]


def test_an_unusable_stamp_is_dropped_never_raised():
    junk = [ None, "not a time", _ago( 5 ), 12 ]
    assert pt.prune_window( junk, NOW, 100 ) == [ _ago( 5 ) ]
    rows = [ { "at": None }, { "at": _ago( 5 ) } ]
    assert pt.prune_window( rows, NOW, 100, stamp=lambda r: r[ "at" ] ) == [ { "at": _ago( 5 ) } ]
    assert pt.prune_window( [ object() ], NOW, 100, stamp=lambda r: r.missing ) == []


def test_none_and_empty_entries_give_an_empty_list():
    assert pt.prune_window( None, NOW, 100 ) == []
    assert pt.prune_window( [], NOW, 100 ) == []
    assert pt.prune_window( iter( [] ), NOW, 100 ) == []


def test_it_accepts_any_iterable_and_returns_a_new_list():
    source = ( _ago( s ) for s in ( 1, 2, 3 ) )
    got    = pt.prune_window( source, NOW, 100 )
    assert got == [ _ago( 1 ), _ago( 2 ), _ago( 3 ) ] and isinstance( got, list )


def test_in_window_is_the_future_dropping_form_of_the_same_prune():
    entries = [ _ago( 10 ), _ago( -10 ), _ago( 100 ), _ago( 101 ), "junk", None ]
    assert pt.in_window( entries, NOW, 100 ) == [ _ago( 10 ), _ago( 100 ) ]
    assert pt.in_window( None, NOW, 100 ) == []


def test_the_web_search_rate_limiter_drops_records_older_than_its_window_and_keeps_the_rest():
    from collections import deque
    from cosa.agents.deep_research.rate_limiter import TokenRecord, WebSearchRateLimiter
    limiter          = WebSearchRateLimiter( tokens_per_minute=100, window_seconds=60.0 )
    limiter._records = deque( [ TokenRecord( timestamp=t, tokens=1, call_type="web_search" ) for t in ( 900.0, 939.0, 940.0, 999.0 ) ] )
    limiter._cleanup_old_records( 1000.0 )
    assert [ r.timestamp for r in limiter._records ] == [ 940.0, 999.0 ]
    assert isinstance( limiter._records, deque )


def test_the_arbiter_drops_a_ping_exactly_one_window_old_and_the_restart_tracker_keeps_a_rise_that_old():
    from collections import deque
    from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
    from lupin_arbiter_app.health_watcher import RestartLoopTracker
    class _Quiet:
        def now_iso( self ): return NOW.isoformat()
        def monotonic( self ): return 0.0
    job = ArbiterConsumerJob( commons=object(), poll_seconds=5, manager_recipient="Mgr", clock=_Quiet(), ping_cap_window_seconds=3600 )
    job._recent_pings = [ _ago( 3600 ), _ago( 3599 ) ]
    job._prune_recent_pings( NOW )
    assert job._recent_pings == [ _ago( 3599 ) ]
    tracker       = RestartLoopTracker( window_seconds=3600, threshold=3 )
    tracker.rises = deque( [ _ago( 3600 ), _ago( 3601 ) ] )
    tracker._prune( NOW )
    assert list( tracker.rises ) == [ _ago( 3600 ) ]
