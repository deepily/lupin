"""
The packed path and the refusal breaker: a refused pack and its halves are one refusal.

A 422 is final for the request that drew it. The breaker stops a sweep after BREAKER_422 distinct refused
families in a row with no answer between them. The stand-in transport is the one the send tests use.
"""
import threading

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_send import ENTRIES, NEED, PROBS, Fake


class SpyBreaker( rt.RefusalBreaker ):
    """A real breaker that remembers the keys it was told about."""

    def __init__( self, limit=rt.BREAKER_422 ):
        super().__init__( limit )
        self.keys, self.answers = [], 0

    def refused( self, key ):
        self.keys.append( key )
        super().refused( key )

    def answered( self ):
        self.answers += 1
        super().answered()


class Refusing( Fake ):
    """Refuses with a 422 every body that holds any of `bad`, and counts what it was sent."""

    def __init__( self, bad, **kw ):
        super().__init__( **kw )
        self.bad = { rp.question_key( b ) for b in bad }

    def post_with_meta( self, body ):
        if self.bad & set( body[ "questions" ] ):
            with self.lock: self.bodies.append( body )
            raise jt.JevConfigError( "Jev refused the request with status 422", 422 )
        answers = { key: { "probabilities": dict( PROBS ) } for key in body[ "questions" ] }                   # any question, not only the fixture's eight entries
        return { "answers": answers, "model": body[ "model" ] }, { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 1 }


MANY = [ { "id": f"pkg.mod.fn{i}", "sig": "()", "doc": f"Does thing {i}.", "file": "src/pkg/mod.py" } for i in range( 24 ) ]


def test_a_refused_pack_that_splits_into_answered_halves_is_one_refusal_and_clears_the_streak():
    breaker = SpyBreaker()
    out     = rp.send_pack( Refusing( [ ENTRIES[ 1 ][ "id" ] ] ), NEED, ENTRIES[ :4 ], breaker=breaker )
    assert breaker.refusals == 1 and breaker.streak == 0 and breaker.has_answered and not breaker.stopped
    assert breaker.keys == [ out[ "rows" ][ 0 ][ "request_hash" ] ] and out[ "failed" ] == [ ENTRIES[ 1 ][ "id" ] ]


def test_the_breaker_hears_the_top_level_hash_once_however_deep_the_split_goes():
    breaker = SpyBreaker()
    rp.send_pack( Refusing( [ e[ "id" ] for e in ENTRIES[ :8 ] ] ), NEED, ENTRIES[ :8 ], breaker=breaker )
    assert len( breaker.keys ) == 1 and breaker.answers == 0 and breaker.streak == 1


def test_a_stopped_breaker_sends_nothing_and_leaves_the_pack_not_reached():
    breaker = SpyBreaker( limit=1 )
    breaker.refused( "earlier" )
    fake = Fake()
    out  = rp.send_pack( fake, NEED, ENTRIES[ :3 ], breaker=breaker )
    assert fake.bodies == [] and out[ "not_reached" ] == [ e[ "id" ] for e in ENTRIES[ :3 ] ] and out[ "rows" ][ 0 ][ "status" ] == "not_reached"


def test_the_breaker_stopping_mid_family_leaves_the_unsent_halves_not_reached():
    breaker = SpyBreaker( limit=1 )
    fake    = Refusing( [ e[ "id" ] for e in ENTRIES[ :4 ] ] )
    out     = rp.send_pack( fake, NEED, ENTRIES[ :4 ], breaker=breaker )
    assert breaker.stopped and len( fake.bodies ) == 1                                  # the first refusal stopped it before any half went out
    assert out[ "not_reached" ] == [ e[ "id" ] for e in ENTRIES[ :4 ] ] and out[ "failed" ] == []


def test_an_answered_request_is_told_to_the_breaker():
    breaker = SpyBreaker()
    rp.send_pack( Fake(), NEED, ENTRIES[ :3 ], breaker=breaker )
    assert breaker.answers == 1 and breaker.refusals == 0


def test_a_pack_that_splits_down_to_one_bad_entry_still_lets_the_next_pack_run( tmp_path ):
    bad = MANY[ 3 ][ "id" ]
    ctx = rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=Refusing( [ bad ] ) )
    out = rp.sweep_packed( ctx, NEED, MANY, 6, workers=4 )
    assert out[ "failed" ] == [ bad ] and len( out[ "answers" ] ) == 23 and out[ "not_reached" ] == []
    assert out[ "refused_422" ] == 1 and out[ "stopped_by" ] is None


def test_five_packs_refused_in_a_row_stop_the_sweep_and_the_rest_is_not_reached( tmp_path ):
    fake = Refusing( [ e[ "id" ] for e in MANY ] )
    ctx  = rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=fake )
    out  = rp.sweep_packed( ctx, NEED, MANY, 2, workers=4 )
    assert out[ "stopped_by" ] == "consecutive_422" and out[ "refused_422" ] >= rt.BREAKER_422
    assert len( out[ "not_reached" ] ) > 0 and out[ "answers" ] == []
    assert len( out[ "failed" ] ) + len( out[ "not_reached" ] ) == 24 and len( fake.bodies ) < 12 * 3


def test_a_sweep_that_was_not_refused_reports_zero_refusals_and_no_stop( tmp_path ):
    ctx = rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=Fake() )
    out = rp.sweep_packed( ctx, NEED, ENTRIES, 3 )
    assert out[ "refused_422" ] == 0 and out[ "stopped_by" ] is None


def test_a_breaker_passed_in_is_the_one_the_sweep_uses( tmp_path ):
    breaker = SpyBreaker()
    ctx     = rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=Refusing( [ ENTRIES[ 0 ][ "id" ] ] ) )
    rp.sweep_packed( ctx, NEED, ENTRIES, 4, breaker=breaker, workers=4 )
    assert breaker.refusals == 1 and breaker.answers >= 1


def test_a_stopped_breaker_passed_in_stops_the_whole_sweep_with_zero_http( tmp_path ):
    breaker = SpyBreaker( limit=1 )
    breaker.refused( "earlier" )
    fake = Fake()
    ctx  = rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=fake )
    out  = rp.sweep_packed( ctx, NEED, ENTRIES, 3, breaker=breaker )
    assert fake.bodies == [] and len( out[ "not_reached" ] ) == 8 and out[ "stopped_by" ] == "consecutive_422"


def test_a_failure_that_is_not_a_422_neither_trips_the_breaker_nor_clears_its_streak():
    breaker = SpyBreaker()
    breaker.refused( "k1" )
    rp.send_pack( Fake( fail=jt.JevCallError( "boom" ) ), NEED, ENTRIES[ :2 ], breaker=breaker )
    assert breaker.streak == 1 and breaker.answers == 0 and len( breaker.keys ) == 1
