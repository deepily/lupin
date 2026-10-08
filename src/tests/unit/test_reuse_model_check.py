"""
A response from another model is not an answer, and it stops the sweep.

The pinned model name is part of what a measurement means. A packed response naming another model, or none,
fails its entries as ModelMismatch and keeps the served name in its row. It counts its tokens and stops the
sweep with its own reason. Nothing it holds is cached. The stand-in transport is the one the send tests use.
"""
import pytest

from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_send import ENTRIES, NEED, Fake

OTHER = "jev-9.9.9"


class Served( Fake ):
    """A Fake that names `served` as its model; "absent" leaves the model out."""

    def __init__( self, served, **kw ):
        super().__init__( **kw )
        self.served = served

    def post_with_meta( self, body ):
        response, meta = super().post_with_meta( body )
        meta[ "attempt_log" ] = [ { "status": 200, "request_ids": { "request-id": "m" } } ]
        if self.served == "absent": del response[ "model" ]
        else: response[ "model" ] = self.served
        return response, meta


@pytest.fixture
def ctx_for( tmp_path ):
    def make( transport ): return rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=transport )
    return make


@pytest.mark.parametrize( "served", [ OTHER, "absent" ] )
def test_a_pack_from_another_model_answers_nothing_and_keeps_the_served_name( served ):
    out = rp.send_pack( Served( served ), NEED, ENTRIES[ :3 ] )
    row = out[ "rows" ][ 0 ]
    assert out[ "answers" ] == [] and out[ "failed" ] == row[ "ids" ] and out[ "not_reached" ] == []
    assert row[ "status" ] == "failed" and row[ "error" ] == "ModelMismatch" and row[ "model" ] == ( None if served == "absent" else served )
    assert row[ "tokens_in" ] == 100 and row[ "tokens_out" ] == 20
    assert row[ "attempt_log" ] == [ { "status": 200, "request_ids": { "request-id": "m" } } ]       # the paid attempt stays in the log


def test_the_named_model_is_still_answered():
    out = rp.send_pack( Served( rt.JEV_MODEL ), NEED, ENTRIES[ :3 ] )
    assert len( out[ "answers" ] ) == 3 and out[ "rows" ][ 0 ][ "status" ] == "answered"


def test_a_mismatch_counts_its_tokens_against_the_budget():
    budget = rc.TokenBudget( 10, 1_000_000 )
    fake   = Served( OTHER, budget=budget )
    rp.send_pack( fake, NEED, ENTRIES[ :2 ], budget=budget )
    assert budget.spent_tokens == 120 and budget.reserved_tokens == 0


def test_a_mismatch_stops_a_given_breaker_and_a_matching_answer_does_not():
    breaker = rt.RefusalBreaker( 5 )
    rp.send_pack( Served( rt.JEV_MODEL ), NEED, ENTRIES[ :2 ], breaker=breaker )
    assert breaker.stopped is False and breaker.model_mismatch is None
    rp.send_pack( Served( OTHER ), NEED, ENTRIES[ :2 ], breaker=breaker )
    assert breaker.stopped is True and breaker.model_mismatch == OTHER
    breaker.mismatched( "jev-8.8.8" )
    assert breaker.model_mismatch == OTHER                                         # the first served name is kept


def test_a_response_that_names_no_model_is_recorded_as_an_empty_name():
    breaker = rt.RefusalBreaker( 5 )
    rp.send_pack( Served( "absent" ), NEED, ENTRIES[ :2 ], breaker=breaker )
    assert breaker.stopped is True and breaker.model_mismatch == ""


def test_a_stopped_breaker_sends_nothing_more():
    breaker = rt.RefusalBreaker( 5 )
    fake    = Served( OTHER )
    rp.send_pack( fake, NEED, ENTRIES[ :2 ], breaker=breaker )
    out = rp.send_pack( fake, NEED, ENTRIES[ 2:4 ], breaker=breaker )
    assert len( fake.bodies ) == 1 and out[ "not_reached" ] == [ e[ "id" ] for e in ENTRIES[ 2:4 ] ]


def test_a_sweep_stops_with_its_own_reason_and_caches_nothing( ctx_for ):
    fake = Served( OTHER )
    ctx  = ctx_for( fake )
    out  = rp.sweep_packed( ctx, NEED, ENTRIES, 1, workers=rp.WORKERS_MIN )
    assert out[ "stopped_by" ] == "model_mismatch" and out[ "refused_422" ] == 0 and out[ "answers" ] == []
    assert len( fake.bodies ) <= rp.WORKERS_MIN and len( out[ "failed" ] ) + len( out[ "not_reached" ] ) == len( ENTRIES ) and out[ "not_reached" ]
    assert [ r[ "error" ] for r in out[ "rows" ] if r[ "status" ] == "failed" ] == [ "ModelMismatch" ] * len( fake.bodies )
    again = Served( rt.JEV_MODEL )
    fresh = rp.sweep_packed( ctx_for( again ), NEED, ENTRIES, 1, workers=rp.WORKERS_MIN )
    assert fresh[ "cache_hits" ] == 0 and fresh[ "stopped_by" ] is None and len( fresh[ "answers" ] ) == len( ENTRIES )


def test_a_refusal_stop_keeps_its_own_reason( ctx_for ):
    out = rp.sweep_packed( ctx_for( Served( rt.JEV_MODEL, refuse_over=0 ) ), NEED, ENTRIES, 1, workers=rp.WORKERS_MIN )
    assert out[ "stopped_by" ] == "consecutive_422"


def test_the_right_model_with_no_answers_is_no_answers_and_not_a_mismatch():
    breaker = rt.RefusalBreaker( 5 )
    out = rp.send_pack( Fake( omit=[ e[ "id" ] for e in ENTRIES[ :2 ] ] ), NEED, ENTRIES[ :2 ], breaker=breaker )
    assert out[ "rows" ][ 0 ][ "error" ] == "NoAnswers" and breaker.stopped is False and breaker.model_mismatch is None
