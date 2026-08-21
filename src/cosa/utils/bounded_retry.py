"""
One bounded-retry primitive for the whole codebase, in a sync and an async flavour.

WHY THIS EXISTS (row 3598c1d3, 2026-08-20). At least six independent hand-rolled
retry loops live in this tree — podcast TTS, embedding fallbacks, speech-to-text,
two DM judges, the notification-proxy verifier — plus a deadline-based one in
``cosa.rest.db.auto_migrate``. They agree on the shape and disagree on every
detail: some bound by attempt count and some by wall-clock deadline, some back
off exponentially and some linearly, some retry on a raised exception and some on
a returned 5xx response, some report each retry to the user and some are silent.
Nothing shared them, so a caller with no retry at all — ``KagiSearch.search_fastgpt``
— turned one momentary upstream blip into a user-visible weather failure.

The union of those behaviours is what this module implements, deliberately:

    · bound by ATTEMPT COUNT, by WALL-CLOCK DEADLINE, or by both (first one wins)
    · exponential backoff with a configurable multiplier and a hard ceiling
    · retry on a raised exception (filtered by TYPE and, optionally, by a
      predicate — e.g. "an HTTP 503 but never an HTTP 401")
    · retry on a RETURNED value (e.g. a ``requests.Response`` carrying a 5xx),
      which is how the embedding and speech-to-text paths are shaped
    · an ``on_retry`` hook per attempt, so a caller can tell the user it is
      retrying without owning the loop

🔴 THE ONE PROPERTY CALLERS DEPEND ON: an exhausted retry RE-RAISES THE LAST
EXCEPTION UNCHANGED. It is never wrapped, never replaced with a summary, never
swallowed into a return value. A retry that hides the final failure would make
the next occurrence undiagnosable, which is the opposite of why the failing call
was wrapped in the first place (see ``src/tests/unit/test_weather_agent_search_failure.py``,
where the user-visible refusal is asserted to NAME its status code).

Testability is a first-class requirement, not an afterthought: ``sleep`` and
``now`` are injectable, so every branch here is exercised with zero real waiting
and no clock.
"""

import asyncio
import inspect
import time as _time

from typing import Any, Callable, Optional


def next_backoff( current: float, multiplier: float=2.0, maximum: float=30.0 ) -> float:
    """
    Grow a retry delay by a multiplier, capped.

    Requires:
        - current is a non-negative number
        - multiplier is a number >= 1.0
        - maximum is a non-negative number

    Ensures:
        - returns min( current * multiplier, maximum )
        - never returns more than maximum, so a long budget cannot turn into one
          enormous sleep that overshoots the deadline in a single step

    Raises:
        - None
    """
    return min( current * multiplier, maximum )


class RetryPolicy:
    """
    The bound and the shape of a retry, separated from the thing being retried.

    A policy is inert data: it decides how many attempts, how long to wait
    between them, and what counts as worth retrying. It never performs a call —
    ``retry_call`` and ``retry_call_async`` do that.
    """

    def __init__(
        self,
        max_attempts      : Optional[int]=3,
        initial_backoff   : float=1.0,
        backoff_multiplier: float=2.0,
        max_backoff       : float=30.0,
        deadline_seconds  : Optional[float]=None,
        retry_on          : tuple=( Exception, ),
        retry_if_error    : Optional[Callable[[BaseException], bool]]=None,
        retry_if_result   : Optional[Callable[[Any], bool]]=None
    ) -> None:
        """
        Build a retry policy.

        Requires:
            - at least one of max_attempts / deadline_seconds is not None. A
              retry with NEITHER bound is an infinite loop wearing a helper's
              clothes, so it is rejected at construction rather than at 3am
            - max_attempts, when given, is >= 1
            - initial_backoff, max_backoff and deadline_seconds (when given) are
              non-negative
            - backoff_multiplier is >= 1.0
            - retry_on is a tuple of exception classes

        Ensures:
            - stores the policy verbatim; no value is silently clamped, because a
              clamped bound is a bound the caller did not choose

        Raises:
            - ValueError if the policy is unbounded, or any numeric field is out
              of range

        Args:
            max_attempts      : total attempts including the first (None = bound by deadline only)
            initial_backoff   : seconds to wait after the first failure
            backoff_multiplier: factor applied to the delay after each failure
            max_backoff       : ceiling on any single delay, in seconds
            deadline_seconds  : total wall-clock budget (None = bound by attempts only)
            retry_on          : exception classes eligible for retry
            retry_if_error    : optional predicate narrowing retry_on further,
                                e.g. "an HTTPError, but only for a 5xx status"
            retry_if_result   : optional predicate that retries a RETURNED value,
                                e.g. a requests.Response whose status is 503
        """
        if max_attempts is None and deadline_seconds is None:
            raise ValueError( "RetryPolicy needs a bound: set max_attempts, deadline_seconds, or both" )
        if max_attempts is not None and max_attempts < 1:
            raise ValueError( f"max_attempts must be >= 1, got {max_attempts}" )
        if initial_backoff < 0 or max_backoff < 0:
            raise ValueError( f"backoff seconds must be non-negative, got initial={initial_backoff}, max={max_backoff}" )
        if backoff_multiplier < 1.0:
            raise ValueError( f"backoff_multiplier must be >= 1.0, got {backoff_multiplier}" )
        if deadline_seconds is not None and deadline_seconds < 0:
            raise ValueError( f"deadline_seconds must be non-negative, got {deadline_seconds}" )

        self.max_attempts       = max_attempts
        self.initial_backoff    = initial_backoff
        self.backoff_multiplier = backoff_multiplier
        self.max_backoff        = max_backoff
        self.deadline_seconds   = deadline_seconds
        self.retry_on           = retry_on
        self.retry_if_error     = retry_if_error
        self.retry_if_result    = retry_if_result

    def error_is_retryable( self, error: BaseException ) -> bool:
        """
        Decide whether a raised exception is worth another attempt.

        Requires:
            - error is an exception instance

        Ensures:
            - returns False when error is not an instance of retry_on — a
              non-retryable error is re-raised immediately, spending no delay
            - otherwise returns retry_if_error( error ) when that predicate is
              set, and True when it is not

        Raises:
            - whatever retry_if_error raises (a broken predicate must not be
              silently read as "do not retry")
        """
        if not isinstance( error, self.retry_on ): return False
        if self.retry_if_error is None:            return True
        return bool( self.retry_if_error( error ) )

    def result_is_retryable( self, result: Any ) -> bool:
        """
        Decide whether a RETURNED value is worth another attempt.

        Requires:
            - None

        Ensures:
            - returns False when retry_if_result is unset (the default: a call
              that returned is a call that succeeded)
            - otherwise returns retry_if_result( result )

        Raises:
            - whatever retry_if_result raises
        """
        if self.retry_if_result is None: return False
        return bool( self.retry_if_result( result ) )


def _delay_before_next_attempt( policy: RetryPolicy, attempt: int, backoff: float,
                                deadline: Optional[float], now: Callable[[], float] ) -> Optional[float]:
    """
    How long to wait before attempt N+1, or None when the budget is spent.

    Requires:
        - attempt is the 1-based number of the attempt that just failed
        - backoff is the currently-scheduled delay in seconds
        - deadline is a monotonic timestamp, or None when unbounded by time

    Ensures:
        - returns None when the attempt bound is reached, or the deadline has
          passed — the two ways a bounded retry ends
        - otherwise returns a delay that never runs past the deadline

    Raises:
        - None
    """
    if policy.max_attempts is not None and attempt >= policy.max_attempts: return None
    if deadline is None:                                                   return backoff

    remaining = deadline - now()
    if remaining <= 0: return None
    return min( backoff, remaining )


def retry_call( fn: Callable[[], Any], policy: Optional[RetryPolicy]=None,
                on_retry: Optional[Callable[[int, Any, float], None]]=None,
                sleep: Optional[Callable[[float], None]]=None,
                now: Optional[Callable[[], float]]=None ) -> Any:
    """
    Call ``fn`` until it succeeds or the policy's bound is spent (synchronous).

    Requires:
        - fn is a zero-argument callable
        - policy is a RetryPolicy, or None for the default 3-attempt policy

    Ensures:
        - returns fn's value on the first attempt the policy accepts
        - a call that succeeds immediately costs ZERO sleeps — the common path
          pays nothing for this guard
        - re-raises a non-retryable exception IMMEDIATELY, without waiting
        - 🔴 re-raises the LAST exception UNCHANGED when the bound is spent, so
          the caller still sees the real error (status line included) and not a
          wrapper
        - when the bound is spent on a retry_if_result retry, returns the last
          result — a value-triggered retry never invents an exception
        - calls on_retry( attempt, outcome, delay ) before each wait, where
          outcome is the exception raised or the result rejected

    Raises:
        - the last exception raised by fn, unchanged

    Args:
        fn      : the zero-argument callable to attempt
        policy  : the bound and backoff shape
        on_retry: optional per-retry hook (attempt, outcome, delay)
        sleep   : injectable sleep, for tests
        now     : injectable monotonic clock, for tests
    """
    policy = policy or RetryPolicy()
    sleep  = sleep  or _time.sleep
    now    = now    or _time.monotonic

    deadline = None if policy.deadline_seconds is None else now() + policy.deadline_seconds
    backoff  = policy.initial_backoff
    attempt  = 0

    while True:
        attempt += 1
        try:
            result = fn()
        except Exception as error:
            if not policy.error_is_retryable( error ): raise
            delay = _delay_before_next_attempt( policy, attempt, backoff, deadline, now )
            if delay is None: raise
            if on_retry: on_retry( attempt, error, delay )
            sleep( delay )
            backoff = next_backoff( backoff, policy.backoff_multiplier, policy.max_backoff )
            continue

        if not policy.result_is_retryable( result ): return result
        delay = _delay_before_next_attempt( policy, attempt, backoff, deadline, now )
        if delay is None: return result
        if on_retry: on_retry( attempt, result, delay )
        sleep( delay )
        backoff = next_backoff( backoff, policy.backoff_multiplier, policy.max_backoff )


async def retry_call_async( fn: Callable[[], Any], policy: Optional[RetryPolicy]=None,
                            on_retry: Optional[Callable[[int, Any, float], Any]]=None,
                            sleep: Optional[Callable[[float], Any]]=None,
                            now: Optional[Callable[[], float]]=None ) -> Any:
    """
    Await ``fn()`` until it succeeds or the policy's bound is spent (asynchronous).

    Same contract as ``retry_call``, awaiting instead of blocking. ``on_retry``
    may be a plain function or a coroutine function — an awaitable return value
    is awaited — because the existing async caller (podcast TTS) reports each
    retry through an async notification callback.

    Requires:
        - fn is a zero-argument callable returning an awaitable
        - policy is a RetryPolicy, or None for the default 3-attempt policy

    Ensures:
        - identical bounding, backoff and re-raise semantics to retry_call
        - waits with asyncio.sleep by default, so the event loop is never blocked

    Raises:
        - the last exception raised by fn, unchanged
    """
    policy = policy or RetryPolicy()
    sleep  = sleep  or asyncio.sleep
    now    = now    or _time.monotonic

    deadline = None if policy.deadline_seconds is None else now() + policy.deadline_seconds
    backoff  = policy.initial_backoff
    attempt  = 0

    while True:
        attempt += 1
        try:
            result = await fn()
        except Exception as error:
            if not policy.error_is_retryable( error ): raise
            delay = _delay_before_next_attempt( policy, attempt, backoff, deadline, now )
            if delay is None: raise
            if on_retry: await _maybe_await( on_retry( attempt, error, delay ) )
            await _maybe_await( sleep( delay ) )
            backoff = next_backoff( backoff, policy.backoff_multiplier, policy.max_backoff )
            continue

        if not policy.result_is_retryable( result ): return result
        delay = _delay_before_next_attempt( policy, attempt, backoff, deadline, now )
        if delay is None: return result
        if on_retry: await _maybe_await( on_retry( attempt, result, delay ) )
        await _maybe_await( sleep( delay ) )
        backoff = next_backoff( backoff, policy.backoff_multiplier, policy.max_backoff )


async def _maybe_await( value: Any ) -> Any:
    """
    Await a value when it is awaitable, pass it through when it is not.

    Requires:
        - None

    Ensures:
        - lets a caller supply either a plain or an async on_retry / sleep,
          rather than forcing every hook to be a coroutine function

    Raises:
        - whatever awaiting the value raises
    """
    if inspect.isawaitable( value ): return await value
    return value


def quick_smoke_test():
    """Quick smoke test to validate bounded_retry behaviour without waiting."""
    import cosa.utils.util as du

    du.print_banner( "bounded_retry Smoke Test", prepend_nl=True )

    slept   = []
    calls   = { "n": 0 }
    def _flaky():
        calls[ "n" ] += 1
        if calls[ "n" ] < 3: raise RuntimeError( f"transient {calls[ 'n' ]}" )
        return "recovered"

    result = retry_call( _flaky, policy=RetryPolicy( max_attempts=4, initial_backoff=1.0 ),
                         sleep=slept.append )
    print( f"✓ recovered after {calls[ 'n' ]} attempts, delays={slept}" if result == "recovered"
           else f"✗ unexpected result: {result}" )

    try:
        retry_call( lambda: ( _ for _ in () ).throw( ValueError( "503 Server Error" ) ),
                    policy=RetryPolicy( max_attempts=2, initial_backoff=0.5 ), sleep=lambda s: None )
        print( "✗ exhausted retry did not raise" )
    except ValueError as e:
        print( f"✓ exhausted retry re-raised unchanged: {e}" )


if __name__ == "__main__":
    quick_smoke_test()
