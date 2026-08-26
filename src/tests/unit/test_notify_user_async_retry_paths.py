"""
The async send's retry loop and its idempotency key — row `e2099400`.

WHY THIS BLOCK. Lines 149, 172, 189-194, 209, 225, 246, 261 and 273 were dark:
the idempotency-key generation, the four distinct retry-and-give-up routes, and
the debug reporting that is the only visibility any of them have.

🔴 THE PROPERTY THAT MATTERS MOST IS THAT THE IDEMPOTENCY KEY IS GENERATED ONCE.
It is minted before the retry loop and carried on every attempt, so a
notification that got through and then looked like a failure is de-duplicated
server-side. Move that generation inside the loop — a one-line change that reads
as a tidy-up — and every retry becomes a NEW notification: the user is told the
same thing up to six times, and the code still looks correct. Two tests hold it.

THE SECOND: **a progress notification is never retried on `user_not_available`.**
Fire-and-forget progress is persisted unconditionally and the user sees it in
their history when they connect, so retrying is pure latency — measured at
30-40 seconds in a test environment where nobody has a live UI. The exemption is
one boolean, and a test that only used the default notification type would never
touch it.

WHAT ELSE IS PINNED:

· **Which failures retry and which do not.** `user_not_available`, a 429/502/
  503/504, a connection error and a timeout all retry; any other HTTP status and
  any other exception fail immediately. Retrying a 400 would just spend the
  budget arriving at the same answer.

· **`Retry-After` is honoured but capped at 5 seconds.** A server asking for 300
  would otherwise hang the hook that sent it.

· **The last attempt returns the failure rather than continuing.** Each of the
  four retry routes has its own `is_last_attempt` branch, and each is driven to
  exhaustion separately — a single-route test would not notice three of them.

· **The retry schedule is bounded by the timeout**, with short budgets getting
  the aggressive pattern and long ones exponential-with-a-cap.

⚠️ `time.sleep` is patched throughout. The real schedule spends up to 9 seconds
per call and the unit tier is the one that has to stay fast enough to run
constantly.

See: row e2099400
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from lupin_cli.notifications.notify_user_async import (
    calculate_retry_intervals,
    notify_user_async,
)
from lupin_cli.notifications.notification_models import (
    AsyncNotificationRequest,
    NotificationType,
)


MODULE = "lupin_cli.notifications.notify_user_async"


def _request( **overrides ):
    base = dict( message="build finished", target_user="someone@example.com", timeout=30 )
    base.update( overrides )
    return AsyncNotificationRequest( **base )


def _reply( status_code=200, payload=None, headers=None, text="" ):
    r = MagicMock( status_code=status_code, headers=headers or {}, text=text )
    r.json.return_value = payload if payload is not None else { "status": "queued" }
    return r


def _send( replies, request=None, **kwargs ):
    """Drive notify_user_async with a scripted sequence of transport results."""
    with patch( f"{MODULE}.get_api_config", side_effect=RuntimeError( "no config" ) ), \
         patch( f"{MODULE}.time.sleep" ), \
         patch( f"{MODULE}.requests.post", side_effect=replies ) as post:
        result = notify_user_async( request or _request(),
                                    server_url="http://localhost:7999", **kwargs )
    return result, post


class TestTheIdempotencyKeyIsMintedOnce:

    def test_every_attempt_carries_the_same_key( self ):
        """Minted BEFORE the loop. Moved inside it — a one-line change that
        reads as a tidy-up — every retry becomes a new notification and the user
        is told the same thing up to six times."""
        replies = [ _reply( payload={ "status": "user_not_available" } ) ] * 3 \
                  + [ _reply( payload={ "status": "queued" } ) ]
        _, post = _send( replies )
        keys = [ call.kwargs[ "params" ][ "idempotency_key" ] for call in post.call_args_list ]
        assert len( keys ) > 1
        assert len( set( keys ) ) == 1

    def test_a_key_is_present_even_on_a_single_attempt( self ):
        _, post = _send( [ _reply() ] )
        assert post.call_args.kwargs[ "params" ][ "idempotency_key" ]

    def test_a_caller_supplied_key_is_not_replaced( self ):
        """The caller may be de-duplicating across processes, not just retries."""
        _, post = _send( [ _reply() ], request=_request( idempotency_key="caller-key" ) )
        assert post.call_args.kwargs[ "params" ][ "idempotency_key" ] == "caller-key"

    def test_two_separate_calls_get_different_keys( self ):
        """The control — a key that never changed would de-duplicate genuinely
        distinct notifications into one."""
        _, first  = _send( [ _reply() ] )
        _, second = _send( [ _reply() ] )
        assert first.call_args.kwargs[ "params" ][ "idempotency_key" ] != \
               second.call_args.kwargs[ "params" ][ "idempotency_key" ]


class TestUserNotAvailableRetries:

    def test_it_retries_until_the_user_connects( self ):
        replies = [ _reply( payload={ "status": "user_not_available" } ),
                    _reply( payload={ "status": "queued" } ) ]
        result, post = _send( replies )
        assert result.success is True
        assert result.status  == "queued"
        assert post.call_count == 2

    def test_a_progress_notification_is_never_retried_for_availability( self ):
        """Progress is persisted unconditionally and shows up in history when
        the user connects; retrying is 30-40 seconds of pure latency."""
        result, post = _send( [ _reply( payload={ "status": "user_not_available" } ) ],
                              request=_request( notification_type=NotificationType.PROGRESS ) )
        assert post.call_count == 1
        assert result.status == "user_not_available"

    def test_a_non_progress_notification_is_retried_on_the_same_reply( self ):
        """THE CONTROL for the exemption above — same server reply, different
        notification type, different behaviour."""
        replies = [ _reply( payload={ "status": "user_not_available" } ),
                    _reply( payload={ "status": "queued" } ) ]
        _, post = _send( replies, request=_request( notification_type=NotificationType.TASK ) )
        assert post.call_count == 2

    def test_the_last_attempt_returns_the_unavailable_status_rather_than_looping( self ):
        replies = [ _reply( payload={ "status": "user_not_available" } ) ] * 12
        result, _ = _send( replies )
        assert result.status == "user_not_available"


class TestHttpErrorHandling:

    @pytest.mark.parametrize( "code", [ 429, 502, 503, 504 ] )
    def test_a_transient_status_is_retried( self, code ):
        result, post = _send( [ _reply( status_code=code ), _reply() ] )
        assert post.call_count == 2
        assert result.success is True

    @pytest.mark.parametrize( "code", [ 400, 401, 403, 404, 500 ] )
    def test_a_non_transient_status_fails_immediately( self, code ):
        """Retrying a 400 spends the whole budget arriving at the same answer."""
        result, post = _send( [ _reply( status_code=code, text="nope" ) ] )
        assert post.call_count == 1
        assert result.success is False
        assert f"HTTP {code}" in result.message

    def test_the_error_body_is_carried_into_the_message( self ):
        result, _ = _send( [ _reply( status_code=422, text="target_user missing" ) ] )
        assert "target_user missing" in result.message

    def test_an_empty_error_body_gets_a_placeholder( self ):
        result, _ = _send( [ _reply( status_code=500, text="" ) ] )
        assert "No error message" in result.message

    def test_a_retry_after_header_is_honoured( self ):
        with patch( f"{MODULE}.get_api_config", side_effect=RuntimeError( "x" ) ), \
             patch( f"{MODULE}.time.sleep" ) as sleep, \
             patch( f"{MODULE}.requests.post",
                    side_effect=[ _reply( status_code=503, headers={ "Retry-After": "3" } ),
                                  _reply() ] ):
            notify_user_async( _request(), server_url="http://localhost:7999" )
        assert 3 in [ c.args[ 0 ] for c in sleep.call_args_list ]

    def test_retry_after_is_capped_at_five_seconds( self ):
        """A server asking for 300 would otherwise hang the hook that sent it."""
        with patch( f"{MODULE}.get_api_config", side_effect=RuntimeError( "x" ) ), \
             patch( f"{MODULE}.time.sleep" ) as sleep, \
             patch( f"{MODULE}.requests.post",
                    side_effect=[ _reply( status_code=503, headers={ "Retry-After": "300" } ),
                                  _reply() ] ):
            notify_user_async( _request(), server_url="http://localhost:7999" )
        assert max( c.args[ 0 ] for c in sleep.call_args_list ) <= 5

    def test_a_non_numeric_retry_after_is_ignored_rather_than_crashing( self ):
        result, _ = _send( [ _reply( status_code=503, headers={ "Retry-After": "soon" } ),
                             _reply() ] )
        assert result.success is True


class TestTransportFailures:

    def test_a_connection_error_retries_then_reports_it( self ):
        result, post = _send( [ requests.exceptions.ConnectionError() ] * 12 )
        assert post.call_count > 1
        assert result.status == "connection_error"
        assert result.success is False

    def test_a_connection_error_that_clears_succeeds( self ):
        result, post = _send( [ requests.exceptions.ConnectionError(), _reply() ] )
        assert result.success is True
        assert post.call_count == 2

    def test_a_timeout_retries_then_reports_it( self ):
        result, post = _send( [ requests.exceptions.Timeout() ] * 12 )
        assert post.call_count > 1
        assert result.status == "timeout"

    def test_a_timeout_that_clears_succeeds( self ):
        result, _ = _send( [ requests.exceptions.Timeout(), _reply() ] )
        assert result.success is True

    def test_a_generic_request_exception_fails_without_retrying( self ):
        """Not transient — retrying spends the budget for nothing."""
        result, post = _send( [ requests.exceptions.RequestException( "bad url" ) ] )
        assert post.call_count == 1
        assert result.success is False
        assert "Request error" in result.message

    def test_an_unexpected_exception_fails_without_retrying( self ):
        result, post = _send( [ RuntimeError( "something else entirely" ) ] )
        assert post.call_count == 1
        assert "Unexpected error" in result.message

    def test_the_four_failure_routes_report_four_different_statuses( self ):
        """The control. Each has its own is_last_attempt branch; a single-route
        test would not notice three of them collapsing into one."""
        conn, _    = _send( [ requests.exceptions.ConnectionError() ] * 12 )
        timeout, _ = _send( [ requests.exceptions.Timeout() ] * 12 )
        http, _    = _send( [ _reply( status_code=400 ) ] )
        unavail, _ = _send( [ _reply( payload={ "status": "user_not_available" } ) ] * 12 )
        assert len( { conn.status, timeout.status, http.status, unavail.status } ) == 4


class TestDebugMustNotChangeTheOutcome:
    """🔴 FOUND BY THESE TESTS, not by reading — a real defect, now fixed.

    `--debug` used to turn a SUCCESSFUL send into a reported transport failure
    whenever config loading had fallen back. The debug line interpolated
    `api_key[:20]` with no guard while guarding the other half of the same
    f-string, so a None key raised TypeError; the catch-all below reported it as
    `Unexpected error: 'NoneType' object is not subscriptable`. And because that
    print sits BEFORE `requests.post`, the notification was never sent at all —
    the diagnostic flag suppressed the thing it was meant to diagnose.

    These two tests are the regression, and they are written as an equivalence
    rather than as a string check on purpose: the rule is that debug changes
    what is PRINTED and nothing else."""

    def test_debug_does_not_change_the_result_on_the_config_fallback_path( self ):
        quiet,   _ = _send( [ _reply() ] )
        verbose, _ = _send( [ _reply() ], debug=True )
        assert ( quiet.success, quiet.status ) == ( verbose.success, verbose.status )
        assert verbose.success is True

    def test_a_missing_api_key_is_reported_as_the_word_none( self, capsys ):
        """The specific line that raised. It must render, not explode."""
        _send( [ _reply() ], debug=True )
        assert "API key: None" in capsys.readouterr().err


class TestDebugReporting:
    """The only visibility any of these routes has."""

    def test_debug_narrates_the_retries_on_stderr( self, capsys ):
        _send( [ _reply( payload={ "status": "user_not_available" } ), _reply() ], debug=True )
        err = capsys.readouterr().err
        assert "user_not_available" in err
        assert "Attempt" in err

    def test_debug_is_silent_by_default( self, capsys ):
        _send( [ _reply() ] )
        assert capsys.readouterr().err == ""

    def test_debug_reports_a_config_fallback( self, capsys ):
        _send( [ _reply() ], debug=True )
        assert "Config loading failed" in capsys.readouterr().err


class TestTheRetrySchedule:

    def test_a_short_budget_gets_the_aggressive_pattern( self ):
        assert calculate_retry_intervals( 10 ) == [ 1, 1, 2, 2, 3 ][ :len(
            calculate_retry_intervals( 10 ) ) ]
        assert sum( calculate_retry_intervals( 10 ) ) < 10

    def test_a_long_budget_backs_off_exponentially_with_a_cap( self ):
        intervals = calculate_retry_intervals( 60 )
        assert intervals[ :3 ] == [ 1, 2, 4 ]
        assert max( intervals ) == 5

    def test_the_schedule_always_fits_inside_the_budget( self ):
        for budget in ( 1, 2, 5, 10, 11, 30, 60, 300 ):
            assert sum( calculate_retry_intervals( budget ) ) < budget - 0.5

    def test_a_budget_too_small_for_any_retry_yields_no_retries( self ):
        assert calculate_retry_intervals( 1 ) == []
