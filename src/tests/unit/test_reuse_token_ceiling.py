"""
The token ceiling of one live run: reserve first, then settle on reported usage.

Plan 10.6. The ceiling counts input and output tokens together. Every test sends through
jev_transport.send_with_meta with a stand-in post function, so a refused attempt shows as zero calls.
"""
import json
import math
import threading

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_tools as rt

ENV  = { jt.KEY_VARIABLE: "test-key" }
BODY = { "model": rt.JEV_MODEL, "state": { "need": "read a feed" }, "questions": { "q_a": { "type": "choice" } } }


def reply( tokens_in=100, tokens_out=40 ):
    usage = {} if tokens_in is None else { "usage": { "input_tokens": tokens_in, "output_tokens": tokens_out } }
    return ( 200, json.dumps( { "answers": {}, **usage } ) )


class Post:
    """A post function that answers from a script and counts its calls."""

    def __init__( self, *script ):
        self.script, self.calls, self.lock = list( script ), 0, threading.Lock()

    def __call__( self, url, headers, body, timeout ):
        with self.lock:
            self.calls += 1
            return self.script.pop( 0 ) if len( self.script ) > 1 else self.script[ 0 ]


def send( budget, post, body=BODY, entries=1 ):
    """Send one request as the packed sender does: open, post, then close or fail."""
    budget.open_request( body, entries )
    try:
        text, meta = jt.send_with_meta( json.dumps( body ).encode( "utf-8" ), post, lambda s: None, ENV, budget, lambda: 0.5 )
    except Exception:
        budget.fail_request()
        raise
    budget.close_request( rt.usage_of( json.loads( text ) ) )
    return text


def input_reserve( body ): return math.ceil( 1.5 * len( rt.canonical( body ) ) / 4 )


def test_the_reserve_is_one_and_a_half_times_the_input_estimate_plus_sixty_output_tokens_an_entry():
    assert rc.reserve_tokens( BODY, 1 ) == input_reserve( BODY ) + 60
    assert rc.reserve_tokens( BODY, 200 ) == input_reserve( BODY ) + 12_000


def test_the_reserve_for_one_known_body_is_95_tokens():
    """The body is 91 characters: 91 x 1.5 / 4 rounds up to 35, plus 60 for one entry."""
    assert len( rt.canonical( BODY ) ) == 91
    assert rc.reserve_tokens( BODY, 1 ) == 95


def test_a_pack_of_200_reserves_11940_output_tokens_more_than_a_pack_of_1():
    assert rc.reserve_tokens( BODY, 200 ) - rc.reserve_tokens( BODY, 1 ) == 199 * 60


def test_a_send_that_would_cross_the_ceiling_is_refused_with_zero_http_calls():
    budget, post = rc.TokenBudget( 10, rc.reserve_tokens( BODY, 1 ) - 1 ), Post( reply() )
    with pytest.raises( jt.JevBudgetSpent ):
        send( budget, post )
    assert post.calls == 0 and budget.ceiling_refusals == 1 and budget.used == 0


def test_a_send_that_fits_on_input_but_not_on_output_is_refused():
    ceiling = input_reserve( BODY ) + 59
    budget, post = rc.TokenBudget( 10, ceiling ), Post( reply() )
    with pytest.raises( jt.JevBudgetSpent ):
        send( budget, post )
    assert post.calls == 0


def test_the_reported_usage_replaces_the_reserve_and_is_input_plus_output():
    budget = rc.TokenBudget( 10, 1_000_000 )
    send( budget, Post( reply( 100, 40 ) ) )
    assert budget.spent_tokens == 140 and budget.reserved_tokens == 0


def test_a_response_with_no_usage_keeps_its_reserve_as_spent():
    budget = rc.TokenBudget( 10, 1_000_000 )
    send( budget, Post( reply( None ) ) )
    assert budget.spent_tokens == rc.reserve_tokens( BODY, 1 ) and budget.reserved_tokens == 0


def test_an_attempt_that_got_no_answer_is_charged_at_its_input_estimate_and_the_retry_reserves_again():
    budget = rc.TokenBudget( 10, 1_000_000 )
    send( budget, Post( ( 429, "" ), reply( 100, 40 ) ) )
    assert budget.spent_tokens == input_reserve( BODY ) + 140 and budget.reserved_tokens == 0 and budget.used == 2


def test_a_failed_request_is_charged_at_its_input_estimate_not_released():
    budget = rc.TokenBudget( 10, 1_000_000 )
    with pytest.raises( jt.JevCallError ):
        send( budget, Post( ( 500, "" ) ) )
    assert budget.spent_tokens == input_reserve( BODY ) and budget.reserved_tokens == 0


def test_the_attempt_cap_still_stops_a_run_when_the_token_ceiling_is_not_reached():
    budget, post = rc.TokenBudget( 1, 1_000_000 ), Post( ( 429, "" ) )
    with pytest.raises( jt.JevBudgetSpent ):
        send( budget, post )
    assert post.calls == 1 and budget.reserved_tokens == 0 and budget.ceiling_refusals == 0


def test_spend_past_the_ceiling_refuses_every_later_send():
    budget = rc.TokenBudget( 10, rc.reserve_tokens( BODY, 1 ) + 10 )
    send( budget, Post( reply( 5_000, 40 ) ) )
    post = Post( reply() )
    with pytest.raises( jt.JevBudgetSpent ):
        send( budget, post )
    assert post.calls == 0 and budget.ceiling_refusals == 1


def test_eight_workers_in_flight_never_hold_more_than_the_ceiling():
    one      = rc.reserve_tokens( BODY, 1 )
    budget   = rc.TokenBudget( 100, one * 3 )
    gate, at = threading.Event(), threading.Barrier( 8 )
    peak, lock, calls, refused = [ 0 ], threading.Lock(), [ 0 ], [ 0 ]

    def post( url, headers, body, timeout ):
        with lock:
            calls[ 0 ] += 1
            peak[ 0 ] = max( peak[ 0 ], budget.reserved_tokens )
        gate.wait( 5 )
        return reply( 10, 10 )

    def worker():
        at.wait( 5 )
        try: send( budget, post )
        except jt.JevBudgetSpent:
            with lock: refused[ 0 ] += 1

    threads = [ threading.Thread( target=worker ) for _ in range( 8 ) ]
    for t in threads: t.start()
    while refused[ 0 ] < 5: threading.Event().wait( 0.01 )
    gate.set()
    for t in threads: t.join( 5 )
    assert calls[ 0 ] == 3 and refused[ 0 ] == 5 and peak[ 0 ] <= one * 3 and budget.ceiling_refusals == 5


def test_an_invalid_ceiling_or_attempt_limit_is_refused():
    for bad in ( 0, -1, 1.5, True, None ):
        with pytest.raises( ValueError ):
            rc.TokenBudget( 10, bad )
    with pytest.raises( ValueError ):
        rc.TokenBudget( 0, 100 )


def test_take_without_an_open_request_is_refused_not_guessed():
    budget = rc.TokenBudget( 10, 1_000_000 )
    with pytest.raises( RuntimeError, match="open_request" ):
        budget.take()
