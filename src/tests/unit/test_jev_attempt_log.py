"""
The transport keeps a log of every attempt, and the sweeps hand the logs on.

Each attempt is recorded with its status, or "timeout" or "connection" when no response came, and the
request ids its response carried. A failed request keeps its log on the error, so a 5xx can be told from
a timeout. The counts of 429, 529, timeouts and resets come from those logs. Doors are scripted.
"""
import urllib.error

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_422_breaker import Door, ctx_over, entries, env, no_jev_key       # noqa: F401  fixtures
from tests.unit.test_reuse_pack_send import ENTRIES, NEED
from tests.unit.test_reuse_tools import N
from tests.unit.test_reuse_transport_telemetry import ENV


def door( replies ):
    """Ensures: returns a door that plays the replies in order and repeats the last."""
    queue = list( replies )
    def post( url, headers, body, timeout ):
        item = queue.pop( 0 ) if len( queue ) > 1 else queue[ 0 ]
        if isinstance( item, BaseException ): raise item
        return item
    return post


def send( replies, **kw ):
    """Ensures: returns the result or the error of a transient send over the scripted door."""
    kw.setdefault( "transient", True )
    try:
        return jt.send_with_meta( b"{}", post_fn=door( replies ), sleep_fn=lambda s: None, environ=ENV, random_fn=lambda: 0.5, **kw )
    except Exception as e:
        return e


def test_a_success_after_a_retry_logs_both_attempts_with_their_request_ids():
    out = send( [ ( 429, "x", { "X-Request-Id": "a" } ), ( 200, "ok", { "request-id": "b", "Content-Type": "json" } ) ] )
    assert out[ 1 ][ "attempt_log" ] == [ { "status": 429, "request_ids": { "X-Request-Id": "a" } },
                                          { "status": 200, "request_ids": { "request-id": "b" } } ]


def test_a_response_with_no_headers_logs_no_request_ids():
    assert send( [ ( 200, "ok" ) ] )[ 1 ][ "attempt_log" ] == [ { "status": 200, "request_ids": {} } ]


@pytest.mark.parametrize( "error, kind", [ ( TimeoutError( "t" ), "timeout" ), ( urllib.error.URLError( TimeoutError( "t" ) ), "timeout" ),
                                           ( ConnectionResetError( "r" ), "connection" ), ( urllib.error.URLError( ConnectionResetError( "r" ) ), "connection" ) ] )
def test_a_timeout_or_a_reset_is_logged_by_kind( error, kind ):
    out = send( [ error, ( 200, "ok" ) ] )
    assert [ a[ "status" ] for a in out[ 1 ][ "attempt_log" ] ] == [ kind, 200 ]


def test_a_failed_request_keeps_the_whole_log_on_its_error():
    out = send( [ ( 503, "x" ), TimeoutError( "t" ), ( 502, "x" ), ( 503, "x" ) ] )
    assert isinstance( out, jt.JevCallError ) and [ a[ "status" ] for a in out.attempt_log ] == [ 503, "timeout", 502, 503 ]


def test_a_refusal_and_a_one_shot_error_keep_their_log():
    refused = send( [ ( 429, "x" ), ( 422, "x", { "request-id": "r" } ) ] )
    assert isinstance( refused, jt.JevConfigError ) and refused.attempt_log == [ { "status": 429, "request_ids": {} }, { "status": 422, "request_ids": { "request-id": "r" } } ]
    other = send( [ ( 404, "x" ) ] )
    assert isinstance( other, jt.JevCallError ) and other.attempt_log == [ { "status": 404, "request_ids": {} } ]


def test_the_default_policy_logs_the_one_attempt_that_raised():
    out = send( [ TimeoutError( "t" ) ], transient=False )
    assert isinstance( out, jt.JevCallError ) and out.attempt_log == [ { "status": "timeout", "request_ids": {} } ]


def test_no_key_means_no_attempt_and_an_empty_log():
    with pytest.raises( jt.JevConfigError ) as caught:
        jt.send_with_meta( b"{}", post_fn=door( [ ( 200, "ok" ) ] ), environ={} )
    assert caught.value.attempt_log == []


def test_the_client_version_is_recorded_in_meta_and_is_a_stable_text():
    out = send( [ ( 200, "ok" ) ] )
    assert out[ 1 ][ "client_version" ] == jt.CLIENT_VERSION and jt.CLIENT_VERSION.startswith( "jev_transport/py" )


def test_the_counts_come_from_the_logs():
    logs = [ [ { "status": 429, "request_ids": {} }, { "status": 529, "request_ids": { "request-id": "a" } }, { "status": 200, "request_ids": { "request-id": "b" } } ],
             [ { "status": "timeout", "request_ids": {} }, { "status": 503, "request_ids": {} }, { "status": "connection", "request_ids": {} }, { "status": 429, "request_ids": {} } ] ]
    assert rt.attempt_counts( logs ) == { "requests": 2, "attempts": 7, "n429": 2, "n529": 1, "timeouts": 1, "resets": 1, "server_errors": 1, "request_ids": 2 }
    assert rt.attempt_counts( [] ) == { "requests": 0, "attempts": 0, "n429": 0, "n529": 0, "timeouts": 0, "resets": 0, "server_errors": 0, "request_ids": 0 }


def test_the_plain_sweep_returns_one_log_per_live_request_failures_included( env ):      # noqa: F811
    d   = Door( [ 429, 200 ] )
    ctx = ctx_over( env, d )
    sw  = rt.sweep( ctx, N( "q" ), entries( 2 ) )
    assert len( sw[ "attempt_logs" ] ) == len( sw[ "answers" ] ) + len( sw[ "failed" ] ) and all( isinstance( log, list ) and log for log in sw[ "attempt_logs" ] )


def test_a_failed_pack_row_keeps_the_http_status_and_the_log():
    transport = rt.LiveJevTransport( post_fn=door( [ ( 503, "x" ) ] ), sleep_fn=lambda s: None, environ=ENV, random_fn=lambda: 0.5,
                                     budget=rc.TokenBudget( 10, 1_000_000 ), transient=True )
    out = rp.send_pack( transport, NEED, ENTRIES[ :2 ], budget=transport.budget )
    row = out[ "rows" ][ 0 ]
    assert row[ "status" ] == "failed" and row[ "http_status" ] == 503 and [ a[ "status" ] for a in row[ "attempt_log" ] ] == [ 503 ] * 4


def test_an_answered_pack_row_and_the_sweep_carry_the_log():
    class Meta:
        def post_with_meta( self, body ):
            answers = { rp.question_key( e[ "id" ] ): { "probabilities": { "reuse": 0.7, "extend": 0.2, "unrelated": 0.1 } } for e in ENTRIES[ :2 ] }
            return { "answers": answers, "model": body[ "model" ] }, { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 1,
                                                                        "attempt_log": [ { "status": 200, "request_ids": { "request-id": "z" } } ] }
    out = rp.send_pack( Meta(), NEED, ENTRIES[ :2 ] )
    assert out[ "rows" ][ 0 ][ "attempt_log" ] == [ { "status": 200, "request_ids": { "request-id": "z" } } ]
