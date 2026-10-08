"""
The Jev transport retries a server failure, a 408, a timeout or a reset, up to four sends.

Cheech's rulings on the live transport set one cap. A 5xx, a 408,
a timeout or a reset is retried with the wait a 429 gets. One request is sent at most four times whatever
mix of 429, 529 and these it meets. A 422 is never retried. Doors, clocks and sleeps are scripted.
"""
import urllib.error

import pytest

from cosa.repo.doc_lint import jev_transport as jt

ENV  = { jt.KEY_VARIABLE: "k" }
BASE = jt.BACKOFF_SECONDS


def door( replies, calls ):
    """Ensures: returns a door that plays the replies in order and repeats the last."""
    queue = list( replies )
    def post( url, headers, body, timeout ):
        calls.append( 1 )
        item = queue.pop( 0 ) if len( queue ) > 1 else queue[ 0 ]
        if isinstance( item, BaseException ): raise item
        return item
    return post


def send( replies, **kw ):
    """Ensures: returns ( outcome, calls, sleeps ); outcome is the result or the error."""
    calls, sleeps = [], []
    kw.setdefault( "random_fn", lambda: 0.5 )                                    # jitter factor exactly 1
    kw.setdefault( "transient", True )
    try:
        out = jt.send_with_meta( b"{}", post_fn=door( replies, calls ), sleep_fn=sleeps.append, environ=ENV, **kw )
    except Exception as e:
        out = e
    return out, calls, sleeps


@pytest.mark.parametrize( "status", [ 500, 502, 503, 504, 408 ] )
def test_a_server_failure_or_408_is_retried_and_the_next_answer_is_used( status ):
    out, calls, sleeps = send( [ ( status, "x" ), ( 200, "ok" ) ] )
    assert out[ 0 ] == "ok" and out[ 1 ][ "attempts" ] == 2 and len( calls ) == 2 and sleeps == [ BASE ]


@pytest.mark.parametrize( "error", [ TimeoutError( "timed out" ), urllib.error.URLError( TimeoutError( "timed out" ) ),
                                     ConnectionResetError( "reset" ), urllib.error.URLError( ConnectionResetError( "reset" ) ) ] )
def test_a_timeout_or_a_reset_is_retried( error ):
    out, calls, sleeps = send( [ error, ( 200, "ok" ) ] )
    assert out[ 0 ] == "ok" and out[ 1 ][ "attempts" ] == 2 and sleeps == [ BASE ]


def test_the_retry_wait_doubles_with_each_attempt_and_honours_a_retry_after():
    out, calls, sleeps = send( [ ( 503, "x", { "Retry-After": "5" } ), ( 502, "x" ), ( 200, "ok" ) ] )
    assert sleeps == [ 5.0, BASE * 2 ] and out[ 1 ][ "retry_after" ] == 5.0


def test_a_429_then_a_500_then_a_200_is_three_sends():
    out, calls, sleeps = send( [ ( 429, "x" ), ( 500, "x" ), ( 200, "ok" ) ] )
    assert out[ 0 ] == "ok" and out[ 1 ][ "attempts" ] == 3 and len( calls ) == 3 and sleeps == [ BASE, BASE * 2 ]


def test_a_request_that_fails_four_times_in_any_mix_is_sent_four_times_and_no_more():
    out, calls, sleeps = send( [ ( 429, "x" ), ( 500, "x" ), TimeoutError( "timed out" ), ( 502, "x" ), ( 200, "never reached" ) ] )
    assert isinstance( out, jt.JevCallError ) and len( calls ) == jt.MAX_ATTEMPTS == 4
    assert len( sleeps ) == 3                                                    # the last failure does not sleep


@pytest.mark.parametrize( "reply", [ ( 500, "x" ), ( 429, "x" ), ( 529, "x" ), TimeoutError( "t" ), ConnectionResetError( "r" ) ] )
def test_the_cap_is_four_sends_for_each_cause_alone( reply ):
    out, calls, sleeps = send( [ reply ] )
    assert isinstance( out, jt.JevCallError ) and len( calls ) == 4


def test_the_final_failure_carries_the_last_http_status_so_a_5xx_is_told_from_a_timeout():
    out, _, _ = send( [ ( 502, "x" ) ] )
    assert out.status == 502
    out, _, _ = send( [ TimeoutError( "t" ) ] )
    assert out.status is None


@pytest.mark.parametrize( "status", [ 401, 403, 422 ] )
def test_a_refusal_is_never_retried( status ):
    out, calls, sleeps = send( [ ( status, "x" ), ( 200, "ok" ) ] )
    assert isinstance( out, jt.JevConfigError ) and out.status == status and len( calls ) == 1 and sleeps == []


@pytest.mark.parametrize( "status", [ 400, 404, 409 ] )
def test_a_client_error_that_is_not_a_refusal_is_not_retried( status ):
    out, calls, sleeps = send( [ ( status, "x" ), ( 200, "ok" ) ] )
    assert isinstance( out, jt.JevCallError ) and len( calls ) == 1 and sleeps == []


def test_a_422_after_a_retry_stops_at_once():
    out, calls, sleeps = send( [ ( 500, "x" ), ( 422, "x" ), ( 200, "ok" ) ] )
    assert isinstance( out, jt.JevConfigError ) and out.status == 422 and len( calls ) == 2


def test_every_attempt_takes_one_from_the_budget_and_a_spent_budget_stops_the_retries():
    budget = jt.CallBudget( 10 )
    out, calls, _ = send( [ ( 500, "x" ), ( 502, "x" ), ( 200, "ok" ) ], budget=budget )
    assert out[ 1 ][ "attempts" ] == 3 and budget.used == 3
    budget = jt.CallBudget( 2 )
    out, calls, _ = send( [ ( 500, "x" ) ], budget=budget )
    assert isinstance( out, jt.JevBudgetSpent ) and len( calls ) == 2 and budget.used == 2


def test_a_timeout_error_message_does_not_carry_the_key():
    out, _, _ = send( [ TimeoutError( "timed out" ) ] )
    assert jt.JevCallError is type( out ) and "k" != str( out ) and ENV[ jt.KEY_VARIABLE ] + "x" not in str( out )


def test_a_timeout_waits_the_same_doubling_and_jittered_backoff_as_a_status():
    out, calls, sleeps = send( [ TimeoutError( "t" ), TimeoutError( "t" ), TimeoutError( "t" ), ( 200, "ok" ) ] )
    assert out[ 1 ][ "attempts" ] == 4 and sleeps == [ BASE, BASE * 2, BASE * 4 ]
    out, calls, sleeps = send( [ TimeoutError( "t" ), ( 200, "ok" ) ], random_fn=lambda: 0.0 )
    assert sleeps == [ BASE * ( 1 - jt.JITTER ) ]
    out, calls, sleeps = send( [ TimeoutError( "t" ), ( 200, "ok" ) ], random_fn=lambda: 1.0 )
    assert sleeps == [ BASE * ( 1 + jt.JITTER ) ]


def test_the_final_status_is_that_of_the_last_attempt_whatever_came_before():
    out, calls, _ = send( [ TimeoutError( "t" ), ( 503, "x" ), TimeoutError( "t" ), ( 503, "x" ) ] )
    assert isinstance( out, jt.JevCallError ) and out.status == 503 and len( calls ) == 4
    out, calls, _ = send( [ ( 503, "x" ), ( 503, "x" ), ( 503, "x" ), TimeoutError( "t" ) ] )
    assert isinstance( out, jt.JevCallError ) and out.status is None and len( calls ) == 4


@pytest.mark.parametrize( "status", [ 400, 404, 409, 501 ] )
def test_a_status_outside_the_retry_set_carries_itself_and_is_sent_once( status ):
    out, calls, sleeps = send( [ ( status, "x" ) ] )
    assert isinstance( out, jt.JevCallError ) and out.status == status and len( calls ) == 1 and sleeps == []
