"""
The fire-and-forget notifier's retry logic — row `e2099400` (coverage frame ramp).

WHY THIS MODULE. `notify_user_async.py` sat at 34% with 103 statements
uncovered — the lowest-covered live module in `lupin_cli` — and what is
uncovered is the part that decides how long every fire-and-forget notification
takes to give up. It entered the denominator on 2026-08-13 when the frame was
widened past `cosa`, and nothing had been written for it since.

THE BEHAVIOUR MOST WORTH PINNING is one somebody deliberately special-cased,
with the reasoning written into the source: **a `progress` notification does not
retry on `user_not_available`.** Progress notifications are persisted to the DB
unconditionally and the user sees them in history, so retrying a disconnected
user is wasted wall-clock that inflates dispatch latency by roughly 30-40
seconds in test environments where nobody has a live UI. Every *other* type does
retry, because a live recipient is the point.

⇒ That is an optimisation with an easy failure mode: delete the `is_progress`
term and nothing breaks, nothing errors, no test goes red — the fleet just gets
slower everywhere, in a way nobody would attribute to this line. So it is
tested from BOTH sides: progress must not retry, and a non-progress type of the
same shape must.

ALSO PINNED, and each for a specific reason:

· **The idempotency key is generated ONCE, before the retry loop.** If it moved
  inside the loop, every retry would present a fresh key and the server's
  de-duplication would stop working — turning "the user was slow to connect"
  into three copies of the same notification.

· **Retryable HTTP statuses discriminate.** 429/502/503/504 retry; 400 and 500
  do not. A version that retried everything would hide a real 400 behind a
  30-second delay before reporting it.

· **`Retry-After` is honoured but capped at 5s.** An uncapped honour lets a
  server pin a hook for as long as it likes.

· **Every failure path returns a response rather than raising.** The docstring
  promises "No exceptions raised (all handled internally)", and the caller is a
  hook with nowhere to put an exception.

⚠️ NOTHING HERE SLEEPS OR TOUCHES THE NETWORK. `requests.post` and `time.sleep`
are both patched at the names this module imported them under, so the patches
bind and the suite runs in milliseconds rather than the ~9s the real intervals
would cost.

See: row e2099400
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from lupin_cli.notifications.notify_user_async import (
    calculate_retry_intervals,
    notify_user_async,
    validate_environment,
)
from lupin_cli.notifications.notification_models import (
    AsyncNotificationRequest,
    NotificationType,
)


MODULE = "lupin_cli.notifications.notify_user_async"


# ---------------------------------------------------------------------------
# calculate_retry_intervals — pure, and the source of every wall-clock cost
# ---------------------------------------------------------------------------

class TestRetryIntervals:

    def test_short_timeouts_use_the_aggressive_pattern( self ):
        """Short timeouts exist to catch the 5-10s WebSocket auth window, so
        the early retries must be dense rather than backed off."""
        assert calculate_retry_intervals( 10 ) == [ 1, 1, 2, 2, 3 ]

    def test_long_timeouts_back_off_exponentially( self ):
        intervals = calculate_retry_intervals( 30 )
        assert intervals[ :3 ] == [ 1, 2, 4 ]

    def test_the_backoff_is_capped_at_five_seconds( self ):
        """Uncapped doubling reaches 64s inside a 60s budget — one interval
        would consume the entire timeout."""
        assert max( calculate_retry_intervals( 60 ) ) == 5

    def test_the_boundary_at_ten_actually_switches_pattern( self ):
        """10 and 11 take different branches. Without this, a boundary moved by
        one would go unnoticed."""
        assert calculate_retry_intervals( 10 ) != calculate_retry_intervals( 11 )

    @pytest.mark.parametrize( "timeout", [ 3, 5, 10, 11, 30, 60, 120 ] )
    def test_the_intervals_always_leave_room_for_the_final_request( self, timeout ):
        """THE INVARIANT the docstring states: total interval time must stay
        under timeout - 0.5, or the last attempt never gets to run."""
        total = sum( calculate_retry_intervals( timeout ) )
        assert total < timeout - 0.5, (
            f"intervals for timeout={timeout} sum to {total}, leaving no room "
            "for the final request"
        )

    def test_a_tiny_timeout_yields_no_retries_rather_than_a_negative_budget( self ):
        assert calculate_retry_intervals( 1 ) == []


# ---------------------------------------------------------------------------
# The retry loop
# ---------------------------------------------------------------------------

def _request( **kw ):
    kw.setdefault( "message", "test notification" )
    kw.setdefault( "target_user", "test@example.com" )
    return AsyncNotificationRequest( **kw )


def _response( status_code=200, payload=None, headers=None, text="" ):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload if payload is not None else { "status": "queued" }
    r.headers = headers or {}
    r.text = text
    return r


def _fire( request, responses, **kw ):
    """Drive notify_user_async with a scripted sequence of transport outcomes.

    `responses` entries are either a response object or an exception instance
    to raise. time.sleep is patched so the suite does not actually wait."""
    with patch( f"{MODULE}.requests.post", side_effect=responses ) as post, \
         patch( f"{MODULE}.time.sleep" ) as sleep:
        result = notify_user_async( request, server_url="http://localhost:7999", **kw )
    return result, post, sleep


class TestTheHappyPath:

    def test_a_queued_response_succeeds_on_the_first_attempt( self ):
        result, post, sleep = _fire( _request(), [ _response() ] )
        assert result.success is True
        assert result.status  == "queued"
        assert post.call_count == 1
        sleep.assert_not_called()

    def test_the_response_fields_are_carried_through( self ):
        result, _, _ = _fire( _request(), [ _response( payload={
            "status": "queued", "message": "ok",
            "target_system_id": "sys-1", "connection_count": 2,
        } ) ] )
        assert result.message          == "ok"
        assert result.target_system_id == "sys-1"
        assert result.connection_count == 2


class TestProgressDoesNotRetry:
    """The deliberate optimisation, tested from both sides.

    Deleting the `is_progress` term breaks nothing loudly — it just makes every
    progress notification pay N x retry_intervals of wall clock. Only the
    contrast between these two tests catches that."""

    def test_a_progress_notification_gives_up_immediately_on_user_not_available( self ):
        request = _request( notification_type=NotificationType.PROGRESS )
        result, post, _ = _fire( request, [ _response( payload={ "status": "user_not_available" } ) ] )
        assert post.call_count == 1, (
            f"progress notification retried {post.call_count} times; it is persisted to "
            "the DB unconditionally, so retrying a disconnected user is pure latency"
        )
        assert result.success is True

    def test_a_non_progress_notification_of_the_same_shape_DOES_retry( self ):
        """THE CONTROL. Without this, a build that never retried anything would
        satisfy the test above."""
        request = _request( notification_type=NotificationType.TASK, timeout=10 )
        unavailable = [ _response( payload={ "status": "user_not_available" } ) ] * 12
        _, post, _ = _fire( request, unavailable )
        assert post.call_count > 1, (
            "a task notification did not retry on user_not_available — the retry "
            "loop is not doing anything for the types that need a live recipient"
        )

    def test_the_two_types_genuinely_behave_differently( self ):
        """Stated as its own assertion rather than left implied across two
        tests: notification_type is the only input that changed."""
        unavailable = [ _response( payload={ "status": "user_not_available" } ) ] * 12
        _, progress_post, _ = _fire( _request( notification_type=NotificationType.PROGRESS, timeout=10 ), unavailable )
        _, task_post, _     = _fire( _request( notification_type=NotificationType.TASK,     timeout=10 ), unavailable )
        assert progress_post.call_count < task_post.call_count


class TestIdempotency:

    def test_the_key_is_generated_once_and_reused_across_every_retry( self ):
        """If the key moved inside the loop, a slow-to-connect user would
        receive one notification per attempt instead of one in total."""
        request = _request( notification_type=NotificationType.TASK, timeout=10 )
        unavailable = [ _response( payload={ "status": "user_not_available" } ) ] * 12
        _, post, _ = _fire( request, unavailable )

        keys = { call.kwargs[ "params" ].get( "idempotency_key" ) for call in post.call_args_list }
        assert len( post.call_args_list ) > 1, "precondition: this test needs more than one attempt"
        assert len( keys ) == 1, f"retries presented {len(keys)} different idempotency keys: {keys}"
        assert next( iter( keys ) ) is not None

    def test_a_caller_supplied_key_is_not_overwritten( self ):
        request = _request( idempotency_key="caller-owns-this" )
        _, post, _ = _fire( request, [ _response() ] )
        assert post.call_args_list[ 0 ].kwargs[ "params" ][ "idempotency_key" ] == "caller-owns-this"


class TestHttpErrorsDiscriminate:

    @pytest.mark.parametrize( "code", [ 429, 502, 503, 504 ] )
    def test_transient_statuses_are_retried( self, code ):
        request = _request( timeout=10 )
        _, post, _ = _fire( request, [ _response( status_code=code ) ] * 12 )
        assert post.call_count > 1, f"HTTP {code} should have been retried"

    @pytest.mark.parametrize( "code", [ 400, 401, 404, 500 ] )
    def test_non_transient_statuses_fail_immediately( self, code ):
        """THE CONTRAST. Retrying a 400 buries a real client error behind
        thirty seconds of delay before anyone is told about it."""
        request = _request( timeout=10 )
        result, post, _ = _fire( request, [ _response( status_code=code, text="nope" ) ] * 12 )
        assert post.call_count == 1, f"HTTP {code} was retried and should not have been"
        assert result.success is False
        assert result.status  == "error"
        assert str( code ) in result.message

    def test_an_empty_error_body_still_produces_a_readable_message( self ):
        result, _, _ = _fire( _request(), [ _response( status_code=400, text="" ) ] )
        assert "No error message" in result.message

    def test_retry_after_is_honoured_but_capped_at_five_seconds( self ):
        """An uncapped honour lets a server pin a hook for as long as it likes."""
        request = _request( timeout=30 )
        responses = [ _response( status_code=503, headers={ "Retry-After": "600" } ) ] * 12
        _, _, sleep = _fire( request, responses )
        assert sleep.call_args_list, "precondition: a retry should have slept"
        assert max( c.args[ 0 ] for c in sleep.call_args_list ) <= 5

    def test_a_non_numeric_retry_after_is_ignored_rather_than_crashing( self ):
        request = _request( timeout=10 )
        responses = [ _response( status_code=503, headers={ "Retry-After": "in a while" } ) ] * 12
        result, _, _ = _fire( request, responses )
        assert result.success is False


class TestTransportFailuresNeverRaise:
    """The docstring promises "No exceptions raised (all handled internally)".
    The caller is a hook with nowhere to put one."""

    def test_a_connection_error_retries_then_reports_connection_error( self ):
        request = _request( timeout=10 )
        result, post, _ = _fire( request, [ requests.exceptions.ConnectionError( "refused" ) ] * 12 )
        assert post.call_count > 1
        assert result.success is False
        assert result.status  == "connection_error"

    def test_a_timeout_retries_then_reports_timeout( self ):
        request = _request( timeout=10 )
        result, post, _ = _fire( request, [ requests.exceptions.Timeout( "slow" ) ] * 12 )
        assert post.call_count > 1
        assert result.status == "timeout"

    def test_a_generic_request_exception_fails_immediately_without_retrying( self ):
        result, post, _ = _fire( _request( timeout=10 ), [ requests.exceptions.RequestException( "bad url" ) ] * 12 )
        assert post.call_count == 1
        assert result.status == "error"
        assert "bad url" in result.message

    def test_an_unexpected_exception_is_caught_too( self ):
        """The last net. A ValueError from json() must not escape into a hook."""
        result, post, _ = _fire( _request( timeout=10 ), [ RuntimeError( "something odd" ) ] * 12 )
        assert post.call_count == 1
        assert result.status == "error"
        assert "something odd" in result.message

    def test_a_recoverable_failure_followed_by_success_returns_success( self ):
        """Proves the retry loop actually re-enters rather than merely counting."""
        request = _request( timeout=10 )
        result, post, _ = _fire( request, [ requests.exceptions.ConnectionError( "refused" ), _response() ] )
        assert post.call_count == 2
        assert result.success is True


# ---------------------------------------------------------------------------
# validate_environment
# ---------------------------------------------------------------------------

class TestValidateEnvironment:

    def test_a_well_formed_url_passes( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_APP_SERVER_URL", "http://localhost:7999" )
        assert validate_environment() is True

    @pytest.mark.parametrize( "bad", [ "localhost:7999", "ftp://x", "" ] )
    def test_a_url_without_an_http_scheme_fails( self, monkeypatch, bad ):
        monkeypatch.setenv( "LUPIN_APP_SERVER_URL", bad )
        assert validate_environment() is False

    def test_a_scheme_with_no_host_fails( self, monkeypatch ):
        """Passes the startswith check and is still unusable — which is why the
        netloc check exists separately."""
        monkeypatch.setenv( "LUPIN_APP_SERVER_URL", "http://" )
        assert validate_environment() is False
