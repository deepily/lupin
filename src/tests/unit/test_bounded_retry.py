"""
The shared bounded-retry primitive, tested at the level of the promises callers rely on.

ROW 3598c1d3. This module exists because seven hand-rolled retry loops disagreed on
everything except their shape, and one call that needed retrying — the Kagi FastGPT
search behind the weather agent — had none at all.

🔴 THE LOAD-BEARING TEST IN THIS FILE is test_an_exhausted_retry_reraises_THE_SAME_EXCEPTION_OBJECT.
Mr. Radio's ruling on that row made a retry conditional on not losing the final failure:
after N spent attempts the user-visible message must still carry the status line, or the
next occurrence goes back to being undiagnosable — the one thing the row had achieved.
A docstring promising that is a comment with a green tick; this asserts it on the object.

Venue: :7999-eligible. Sleep and the clock are injected, so the whole file is sub-second
with no real waiting, no network and no spend.
"""

import asyncio
import os
import sys

import pytest

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SRC = os.path.join( _LUPIN_ROOT, "src" )
    if _SRC not in sys.path:
        sys.path.insert( 0, _SRC )

from cosa.utils.bounded_retry import (                                  # noqa: E402
    RetryPolicy, next_backoff, retry_call, retry_call_async, _maybe_await
)


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────

class _Recorder:
    """Collects the delays slept and the on_retry hooks fired, so timing is asserted not guessed."""
    def __init__( self ):
        self.slept  = []
        self.hooks  = []
    def sleep( self, delay ):
        self.slept.append( delay )
    def hook( self, attempt, outcome, delay ):
        self.hooks.append( ( attempt, outcome, delay ) )


class _FakeClock:
    """A monotonic clock that only moves when the test says so."""
    def __init__( self, start=0.0 ):
        self.t = start
    def __call__( self ):
        return self.t
    def advance( self, seconds ):
        self.t += seconds


def _failing_then( failures, error, value="ok" ):
    """A callable that raises `error` the first `failures` times, then returns `value`."""
    state = { "n": 0 }
    def _fn():
        state[ "n" ] += 1
        if state[ "n" ] <= failures: raise error
        return value
    _fn.calls = state
    return _fn


# ──────────────────────────────────────────────────────────────────────────────
# next_backoff
# ──────────────────────────────────────────────────────────────────────────────

def test_next_backoff_grows_and_then_stops_growing():
    """Exponential until the ceiling, flat after — a long budget must not become one huge sleep."""
    assert next_backoff( 1.0, multiplier=2.0, maximum=30.0 ) == 2.0
    assert next_backoff( 20.0, multiplier=2.0, maximum=30.0 ) == 30.0      # capped
    assert next_backoff( 5.0, multiplier=1.0, maximum=30.0 ) == 5.0        # a flat policy stays flat


# ──────────────────────────────────────────────────────────────────────────────
# RetryPolicy — validation
# ──────────────────────────────────────────────────────────────────────────────

def test_a_policy_with_NO_bound_is_refused_at_construction():
    """
    The name of the module is the contract. A retry with neither an attempt count nor a
    deadline is an infinite loop, and it should be rejected where it is written — not
    discovered at 3am by the thing it is wrapped around.
    """
    with pytest.raises( ValueError, match="needs a bound" ):
        RetryPolicy( max_attempts=None, deadline_seconds=None )


@pytest.mark.parametrize( "kwargs, match", [
    ( { "max_attempts": 0 },                       "max_attempts must be >= 1" ),
    ( { "initial_backoff": -1.0 },                 "non-negative" ),
    ( { "max_backoff": -1.0 },                     "non-negative" ),
    ( { "backoff_multiplier": 0.5 },               "backoff_multiplier must be >= 1.0" ),
    ( { "deadline_seconds": -1.0 },                "deadline_seconds must be non-negative" ),
] )
def test_out_of_range_policy_fields_are_refused( kwargs, match ):
    """Each numeric field is validated where it is set, so a nonsense policy never reaches a loop."""
    with pytest.raises( ValueError, match=match ):
        RetryPolicy( **kwargs )


def test_a_valid_policy_stores_its_fields_verbatim():
    """No silent clamping: a bound the caller did not choose is a bound they cannot reason about."""
    policy = RetryPolicy( max_attempts=5, initial_backoff=0.25, backoff_multiplier=3.0,
                          max_backoff=9.0, deadline_seconds=12.0 )
    assert ( policy.max_attempts, policy.initial_backoff, policy.backoff_multiplier ) == ( 5, 0.25, 3.0 )
    assert ( policy.max_backoff, policy.deadline_seconds ) == ( 9.0, 12.0 )


# ──────────────────────────────────────────────────────────────────────────────
# RetryPolicy — the two "is this worth another go?" questions
# ──────────────────────────────────────────────────────────────────────────────

def test_an_exception_outside_retry_on_is_not_retryable():
    policy = RetryPolicy( retry_on=( ValueError, ) )
    assert policy.error_is_retryable( ValueError( "yes" ) ) is True
    assert policy.error_is_retryable( TypeError( "no" ) )   is False


def test_retry_if_error_narrows_retry_on_further():
    """
    The real use: an HTTPError is retryable when it carries a 503 and not when it carries a 401.
    Type alone cannot express that, which is why the predicate exists.
    """
    policy = RetryPolicy( retry_on=( ValueError, ),
                          retry_if_error=lambda e: "503" in str( e ) )
    assert policy.error_is_retryable( ValueError( "503 Server Error" ) )     is True
    assert policy.error_is_retryable( ValueError( "401 Unauthorized" ) )     is False


def test_a_returned_value_is_only_retryable_when_a_predicate_says_so():
    """By default a call that returned is a call that succeeded — the embedding path opts out."""
    assert RetryPolicy().result_is_retryable( "anything" ) is False
    policy = RetryPolicy( retry_if_result=lambda r: r == "503" )
    assert policy.result_is_retryable( "503" ) is True
    assert policy.result_is_retryable( "200" ) is False


# ──────────────────────────────────────────────────────────────────────────────
# retry_call — the sync path
# ──────────────────────────────────────────────────────────────────────────────

def test_a_call_that_works_first_time_pays_NOTHING_for_the_guard():
    """The common path must not acquire a cost. Zero sleeps, one call, defaults all the way."""
    rec   = _Recorder()
    calls = { "n": 0 }
    def _fn():
        calls[ "n" ] += 1
        return "summary"

    assert retry_call( _fn, sleep=rec.sleep ) == "summary"
    assert calls[ "n" ] == 1
    assert rec.slept == []


def test_the_defaults_are_usable_with_no_policy_no_sleep_and_no_clock():
    """
    Covers the zero-argument call shape. A success needs no sleep and no clock, so this
    exercises the default wiring without waiting on a real one.
    """
    assert retry_call( lambda: 42 ) == 42


def test_a_NON_retryable_error_is_raised_immediately_without_waiting():
    """
    A 401 is a standing answer. Sleeping three times before delivering it burns the user's
    wait and changes nothing — so the type filter has to short-circuit before any delay.
    """
    rec = _Recorder()
    with pytest.raises( TypeError ):
        retry_call( lambda: ( _ for _ in () ).throw( TypeError( "not eligible" ) ),
                    policy=RetryPolicy( max_attempts=5, retry_on=( ValueError, ) ),
                    sleep=rec.sleep, on_retry=rec.hook )
    assert rec.slept == []
    assert rec.hooks == []


def test_a_transient_failure_recovers_and_the_caller_never_sees_it():
    """The whole point: one blip, one wait, the real answer — not a refusal."""
    rec    = _Recorder()
    fn     = _failing_then( 1, ValueError( "503 Server Error" ), value="72 degrees" )
    result = retry_call( fn, policy=RetryPolicy( max_attempts=3, initial_backoff=1.0 ),
                         sleep=rec.sleep, on_retry=rec.hook )

    assert result == "72 degrees"
    assert fn.calls[ "n" ] == 2
    assert rec.slept == [ 1.0 ]
    assert rec.hooks[ 0 ][ 0 ] == 1                                  # attempt number is 1-based
    assert isinstance( rec.hooks[ 0 ][ 1 ], ValueError )             # the hook sees the failure
    assert rec.hooks[ 0 ][ 2 ] == 1.0                                # and the wait it is about to take


def test_delays_grow_exponentially_and_respect_the_ceiling():
    rec = _Recorder()
    fn  = _failing_then( 3, ValueError( "transient" ) )
    retry_call( fn, policy=RetryPolicy( max_attempts=4, initial_backoff=1.0,
                                        backoff_multiplier=2.0, max_backoff=3.0 ),
                sleep=rec.sleep )
    assert rec.slept == [ 1.0, 2.0, 3.0 ]                            # 4.0 would have been the cap's job


def test_an_exhausted_retry_reraises_THE_SAME_EXCEPTION_OBJECT():
    """
    🔴 THE PROPERTY THE WEATHER ROW TURNS ON. Mr. Radio's ruling (row 3598c1d3) allowed a retry
    on the condition that it does not swallow the final failure: Sam proved at 79ea2501 that the
    agent's refusal NAMES its status code, and a retry that summarised its last error would
    silently revert that. Identity, not equality — a re-wrapped copy would pass an equality
    check and still lose the traceback the next reader needs.
    """
    rec      = _Recorder()
    original = ValueError( "503 Server Error: Service Unavailable for url: https://kagi.com/api/v0/fastgpt" )
    with pytest.raises( ValueError ) as caught:
        retry_call( lambda: ( _ for _ in () ).throw( original ),
                    policy=RetryPolicy( max_attempts=3, initial_backoff=0.5 ), sleep=rec.sleep )

    assert caught.value is original                                  # unchanged, not wrapped
    assert "503" in str( caught.value )                              # the status line survives to the user
    assert rec.slept == [ 0.5, 1.0 ]                                 # waits between attempts, none after the last


def test_the_retry_hook_is_optional():
    """Covers the silent caller: no hook, same recovery."""
    rec = _Recorder()
    assert retry_call( _failing_then( 1, ValueError( "x" ) ),
                       policy=RetryPolicy( max_attempts=2 ), sleep=rec.sleep ) == "ok"
    assert rec.slept == [ 1.0 ]


def test_a_retryable_RESULT_is_retried_and_then_accepted():
    """The embedding / speech-to-text shape: the failure comes back as a value, not a raise."""
    rec      = _Recorder()
    results  = iter( [ 503, 503, 200 ] )
    policy   = RetryPolicy( max_attempts=4, initial_backoff=1.0,
                            retry_if_result=lambda r: r >= 500 )
    assert retry_call( lambda: next( results ), policy=policy, sleep=rec.sleep, on_retry=rec.hook ) == 200
    assert rec.slept == [ 1.0, 2.0 ]
    assert rec.hooks[ 0 ][ 1 ] == 503                                 # the hook is handed the rejected VALUE


def test_an_exhausted_RESULT_retry_returns_the_last_value_rather_than_inventing_an_error():
    """
    Nothing raised, so nothing may be raised. Manufacturing an exception here would hand the
    caller a failure mode their own code never produces.
    """
    rec    = _Recorder()
    policy = RetryPolicy( max_attempts=2, initial_backoff=1.0, retry_if_result=lambda r: True )
    assert retry_call( lambda: 503, policy=policy, sleep=rec.sleep ) == 503
    assert rec.slept == [ 1.0 ]


# ──────────────────────────────────────────────────────────────────────────────
# retry_call — the deadline bound
# ──────────────────────────────────────────────────────────────────────────────

def test_a_deadline_bounded_retry_stops_when_the_budget_is_spent():
    """
    auto_migrate's shape: no attempt count at all, just a wall-clock budget. The clock only
    moves when the fake sleep moves it, so the loop's arithmetic is what is under test.
    """
    rec    = _Recorder()
    clock  = _FakeClock()
    def _sleep( delay ):
        rec.slept.append( delay )
        clock.advance( delay )

    original = ValueError( "down" )
    policy   = RetryPolicy( max_attempts=None, deadline_seconds=5.0,
                            initial_backoff=2.0, backoff_multiplier=2.0 )
    with pytest.raises( ValueError ) as caught:
        retry_call( lambda: ( _ for _ in () ).throw( original ),
                    policy=policy, sleep=_sleep, now=clock )

    assert caught.value is original
    assert rec.slept == [ 2.0, 3.0 ]                                  # second wait CLIPPED to the remaining budget
    assert clock.t == 5.0                                             # and never a second past the deadline


def test_a_deadline_already_passed_raises_without_sleeping_at_all():
    rec    = _Recorder()
    clock  = _FakeClock()
    policy = RetryPolicy( max_attempts=None, deadline_seconds=0.0, initial_backoff=1.0 )
    with pytest.raises( ValueError ):
        retry_call( lambda: ( _ for _ in () ).throw( ValueError( "down" ) ),
                    policy=policy, sleep=rec.sleep, now=clock )
    assert rec.slept == []


# ──────────────────────────────────────────────────────────────────────────────
# retry_call_async — same contract, awaited
# ──────────────────────────────────────────────────────────────────────────────

def test_async_recovers_from_a_transient_failure_with_an_ASYNC_retry_hook():
    """
    The podcast TTS shape: the per-attempt notification is a coroutine. A helper that only
    accepted plain callbacks would not have covered its most demanding existing caller.
    """
    rec    = _Recorder()
    state  = { "n": 0 }

    async def _fn():
        state[ "n" ] += 1
        if state[ "n" ] == 1: raise ValueError( "segment 3 timed out" )
        return "pcm-bytes"

    async def _hook( attempt, outcome, delay ):
        rec.hooks.append( ( attempt, outcome, delay ) )

    async def _sleep( delay ):
        rec.slept.append( delay )

    result = asyncio.run( retry_call_async( _fn, policy=RetryPolicy( max_attempts=3, initial_backoff=1.0 ),
                                            on_retry=_hook, sleep=_sleep ) )
    assert result == "pcm-bytes"
    assert rec.slept == [ 1.0 ]
    assert rec.hooks[ 0 ][ 0 ] == 1


def test_async_accepts_a_PLAIN_retry_hook_too():
    """A sync hook and a sync sleep must work unchanged — awaiting is opt-in, not a tax."""
    rec = _Recorder()
    async def _fn():
        raise ValueError( "429 Too Many Requests" )

    with pytest.raises( ValueError, match="429" ):
        asyncio.run( retry_call_async( _fn, policy=RetryPolicy( max_attempts=2, initial_backoff=0.5 ),
                                       on_retry=rec.hook, sleep=rec.sleep ) )
    assert rec.slept == [ 0.5 ]
    assert len( rec.hooks ) == 1


def test_async_succeeds_first_time_with_every_default():
    async def _fn():
        return "immediate"
    assert asyncio.run( retry_call_async( _fn ) ) == "immediate"


def test_async_raises_a_non_retryable_error_immediately():
    rec = _Recorder()
    async def _fn():
        raise TypeError( "not eligible" )
    with pytest.raises( TypeError ):
        asyncio.run( retry_call_async( _fn, policy=RetryPolicy( max_attempts=5, retry_on=( ValueError, ) ),
                                       sleep=rec.sleep ) )
    assert rec.slept == []


def test_async_retries_a_retryable_RESULT_and_then_accepts_it():
    rec     = _Recorder()
    results = iter( [ 503, 200 ] )
    async def _fn():
        return next( results )
    policy = RetryPolicy( max_attempts=3, initial_backoff=1.0, retry_if_result=lambda r: r >= 500 )
    assert asyncio.run( retry_call_async( _fn, policy=policy, sleep=rec.sleep ) ) == 200
    assert rec.slept == [ 1.0 ]


def test_async_returns_the_last_value_when_a_RESULT_retry_is_exhausted():
    rec = _Recorder()
    async def _fn():
        return 503
    policy = RetryPolicy( max_attempts=2, initial_backoff=1.0, retry_if_result=lambda r: True )
    assert asyncio.run( retry_call_async( _fn, policy=policy, sleep=rec.sleep, on_retry=rec.hook ) ) == 503
    assert rec.slept  == [ 1.0 ]
    assert len( rec.hooks ) == 1


def test_async_deadline_bound_stops_on_time():
    rec   = _Recorder()
    clock = _FakeClock()
    def _sleep( delay ):
        rec.slept.append( delay )
        clock.advance( delay )
    async def _fn():
        raise ValueError( "down" )
    policy = RetryPolicy( max_attempts=None, deadline_seconds=3.0, initial_backoff=2.0 )
    with pytest.raises( ValueError ):
        asyncio.run( retry_call_async( _fn, policy=policy, sleep=_sleep, now=clock ) )
    assert rec.slept == [ 2.0, 1.0 ]


def test_maybe_await_passes_a_plain_value_straight_through():
    assert asyncio.run( _maybe_await( "plain" ) ) == "plain"
