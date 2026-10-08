"""
Sending one pack: answers read by presence, a 422 splits it, every entry accounted for.

Plan 10.3 b to d. A stand-in transport answers from a script and records each body it was sent.
"""
import threading

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt

NEED  = "read an RSS feed and return its articles"
PROBS = { "reuse": 0.7, "extend": 0.2, "unrelated": 0.1 }
ENTRIES = [ { "id": f"pkg.mod.fn{i}", "sig": "()", "doc": f"Does thing {i}.", "file": "src/pkg/mod.py" } for i in range( 8 ) ]


class Fake:
    """
    A transport that answers a body from a rule and records it.

    `refuse_over` makes any body with more questions than that raise a 422.
    `omit` leaves those entry ids unanswered. `fail` makes every post raise that exception.
    """

    def __init__( self, refuse_over=None, omit=(), fail=None, usage=( 100, 20 ), attempts=1, budget=None ):
        self.bodies, self.refuse_over, self.omit, self.fail, self.usage, self.lock = [], refuse_over, set( omit ), fail, usage, threading.Lock()
        self.attempts, self.budget = attempts, budget

    def post_with_meta( self, body ):
        if self.budget is not None:
            for _ in range( self.attempts ): self.budget.take()                  # the live transport takes one per HTTP attempt
        with self.lock: self.bodies.append( body )
        if self.fail is not None: raise self.fail
        if self.refuse_over is not None and len( body[ "questions" ] ) > self.refuse_over:
            raise jt.JevConfigError( "Jev refused the request with status 422", 422 )
        answers = {}
        for entry in ENTRIES:
            key = rp.question_key( entry[ "id" ] )
            if key in body[ "questions" ] and entry[ "id" ] not in self.omit: answers[ key ] = { "probabilities": dict( PROBS ) }
        response = { "answers": answers, "model": body[ "model" ] }
        if self.usage is not None: response[ "usage" ] = { "input_tokens": self.usage[ 0 ], "output_tokens": self.usage[ 1 ] }
        return response, { "status": 200, "attempts": self.attempts, "retry_after": None, "latency_ms": 3 }


def ids( out ): return [ a[ "id" ] for a in out[ "answers" ] ]


def test_a_pack_that_is_fully_answered_returns_every_entry_in_order_with_one_row():
    out = rp.send_pack( Fake(), NEED, ENTRIES[ :4] )
    assert ids( out ) == [ e[ "id" ] for e in ENTRIES[ :4 ] ]
    assert out[ "answers" ][ 0 ][ "probabilities" ] == PROBS
    assert out[ "failed" ] == [] and out[ "not_reached" ] == []
    row, = out[ "rows" ]
    assert row[ "status" ] == "answered" and row[ "size" ] == 4 and row[ "ids" ] == ids( out )
    assert row[ "tokens_in" ] == 100 and row[ "tokens_out" ] == 20 and row[ "split_from" ] is None and row[ "attempts" ] == 1


def test_the_row_names_the_request_by_the_hash_of_the_body_that_was_sent():
    fake = Fake()
    out  = rp.send_pack( fake, NEED, ENTRIES[ :3 ] )
    assert out[ "rows" ][ 0 ][ "request_hash" ] == rp.pack_key( fake.bodies[ 0 ] )


def test_a_422_splits_the_pack_in_half_and_resends_each_half():
    fake = Fake( refuse_over=2 )
    out  = rp.send_pack( fake, NEED, ENTRIES[ :4 ] )
    assert [ len( b[ "questions" ] ) for b in fake.bodies ] == [ 4, 2, 2 ]
    assert ids( out ) == [ e[ "id" ] for e in ENTRIES[ :4 ] ]
    parent, left, right = out[ "rows" ]
    assert [ parent[ "status" ], left[ "status" ], right[ "status" ] ] == [ "refused", "answered", "answered" ]
    assert left[ "split_from" ] == parent[ "request_hash" ] == right[ "split_from" ]
    assert left[ "ids" ] + right[ "ids" ] == parent[ "ids" ]


def test_an_odd_pack_splits_with_the_larger_half_second_and_loses_no_entry():
    fake = Fake( refuse_over=2 )
    out  = rp.send_pack( fake, NEED, ENTRIES[ :5 ] )
    assert [ len( b[ "questions" ] ) for b in fake.bodies ] == [ 5, 2, 3, 1, 2 ]
    assert ids( out ) == [ e[ "id" ] for e in ENTRIES[ :5 ] ]


def test_a_422_on_one_entry_leaves_that_entry_failed_and_the_others_answered():
    fake = Fake( refuse_over=0 )
    out  = rp.send_pack( fake, NEED, ENTRIES[ :1 ] )
    assert out[ "answers" ] == [] and out[ "failed" ] == [ ENTRIES[ 0 ][ "id" ] ]
    assert out[ "rows" ][ 0 ][ "status" ] == "refused"


def test_an_entry_with_no_answer_is_failed_not_unrelated_and_the_row_names_it():
    gone = ENTRIES[ 1 ][ "id" ]
    out  = rp.send_pack( Fake( omit=[ gone ] ), NEED, ENTRIES[ :3 ] )
    assert gone not in ids( out ) and out[ "failed" ] == [ gone ]
    assert out[ "rows" ][ 0 ][ "status" ] == "answered" and out[ "rows" ][ 0 ][ "unasked" ] == [ gone ]


def test_a_transport_failure_fails_every_entry_of_the_pack_and_records_the_attempts():
    budget = rc.TokenBudget( 10, 1_000_000 )
    fake   = Fake( fail=jt.JevCallError( "boom" ), budget=budget )
    out    = rp.send_pack( fake, NEED, ENTRIES[ :3 ], budget=budget )
    assert out[ "answers" ] == [] and out[ "failed" ] == [ e[ "id" ] for e in ENTRIES[ :3 ] ]
    row, = out[ "rows" ]
    assert row[ "status" ] == "failed" and row[ "attempts" ] == 1 and row[ "error" ] == "JevCallError"


def test_attempts_come_from_the_budget_when_there_is_one():
    budget = rc.TokenBudget( 10, 1_000_000 )
    out    = rp.send_pack( Fake( attempts=2, budget=budget ), NEED, ENTRIES[ :2 ], budget=budget )     # a first attempt that drew a 429, then the answer
    assert out[ "rows" ][ 0 ][ "attempts" ] == 2


def test_a_refused_key_fails_the_pack_and_the_row_keeps_the_status():
    fake = Fake( fail=jt.JevConfigError( "Jev refused the request with status 401", 401 ) )
    out  = rp.send_pack( fake, NEED, ENTRIES[ :2 ] )
    assert out[ "failed" ] == [ e[ "id" ] for e in ENTRIES[ :2 ] ] and len( fake.bodies ) == 1
    assert out[ "rows" ][ 0 ][ "error" ] == "JevConfigError" and out[ "rows" ][ 0 ][ "http_status" ] == 401


def test_a_budget_spent_before_any_attempt_leaves_the_pack_not_reached_with_no_http():
    budget = rc.TokenBudget( 10, 1 )                       # a ceiling of one token refuses the first attempt
    fake   = Fake( budget=budget )
    out    = rp.send_pack( fake, NEED, ENTRIES[ :3 ], budget=budget )
    assert fake.bodies == []
    assert out[ "not_reached" ] == [ e[ "id" ] for e in ENTRIES[ :3 ] ] and out[ "failed" ] == [] and out[ "answers" ] == []
    assert out[ "rows" ][ 0 ][ "status" ] == "not_reached" and out[ "rows" ][ 0 ][ "attempts" ] == 0


def test_the_token_budget_charges_each_half_of_a_split_pack_separately():
    budget = rc.TokenBudget( 20, 10_000_000 )
    fake   = Fake( refuse_over=2, budget=budget )
    rp.send_pack( fake, NEED, ENTRIES[ :4 ], budget=budget )
    assert budget.used == 3 and budget.reserved_tokens == 0
    assert budget.spent_tokens == rc.input_reserve( fake.bodies[ 0 ] ) + 2 * ( 100 + 20 )


@pytest.mark.parametrize( "response", [ None, {}, { "answers": [] }, "text" ] )
def test_a_response_of_the_wrong_shape_fails_every_entry( response ):
    class Odd( Fake ):
        def post_with_meta( self, body ): return response, { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 1 }

    out = rp.send_pack( Odd(), NEED, ENTRIES[ :2 ] )
    assert out[ "answers" ] == [] and out[ "failed" ] == [ e[ "id" ] for e in ENTRIES[ :2 ] ]


def test_a_transport_that_only_has_post_is_used_and_the_row_has_no_http_meta():
    class Plain:
        def __init__( self ): self.inner = Fake()
        def post( self, body ): return self.inner.post_with_meta( body )[ 0 ]

    out = rp.send_pack( Plain(), NEED, ENTRIES[ :2 ] )
    assert len( out[ "answers" ] ) == 2 and out[ "rows" ][ 0 ][ "http" ] is None


def test_an_empty_pack_is_refused():
    with pytest.raises( ValueError, match="empty" ):
        rp.send_pack( Fake(), NEED, [] )
