"""
RefusalBreaker stops a sweep after a limit of distinct refused keys in a row.

A caller that splits a pack and resends its halves passes one key for the pack and all its halves.
So the whole family is one refusal. Any answered request resets the streak. Once the limit is reached the breaker
stays stopped. The sweep takes a breaker as an optional argument and makes its own when none is given.

Driven directly, and through rt.sweep over a live transport with a scripted door. No case reaches Jev.
"""
import threading

import pytest

from cosa.repo.doc_lint import jev_transport
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_422_breaker import Door, ctx_over, entries
from tests.unit.test_reuse_tools import N


@pytest.fixture( autouse=True )
def no_jev_key( monkeypatch ):
    """No test here may find a real key: a live call would be spend and a leak."""
    monkeypatch.delenv( jev_transport.KEY_VARIABLE, raising=False )


@pytest.fixture
def env( tmp_path ):
    root = make_lupin_repo( tmp_path )
    return root, tmp_path / "data", tmp_path / "out"


def test_a_new_breaker_has_no_streak_no_answer_and_is_not_stopped():
    b = rt.RefusalBreaker( 3 )
    assert ( b.streak, b.refusals, b.has_answered, b.stopped ) == ( 0, 0, False, False )


def test_the_same_key_refused_again_is_one_refusal_in_the_streak():
    b = rt.RefusalBreaker( 3 )
    for _ in range( 5 ): b.refused( "pack-a" )
    assert b.streak == 1 and b.refusals == 5 and not b.stopped


def test_the_limit_of_distinct_keys_stops_the_breaker():
    b = rt.RefusalBreaker( 3 )
    for key in ( "a", "b" ): b.refused( key )
    assert not b.stopped
    b.refused( "c" )
    assert b.stopped and b.streak == 3


def test_an_answer_clears_the_streak_and_marks_the_breaker_answered():
    b = rt.RefusalBreaker( 3 )
    b.refused( "a" ); b.refused( "b" ); b.answered()
    assert ( b.streak, b.has_answered, b.refusals ) == ( 0, True, 2 )
    b.refused( "a" ); b.refused( "b" )
    assert not b.stopped


def test_a_stopped_breaker_stays_stopped_after_an_answer():
    b = rt.RefusalBreaker( 1 )
    b.refused( "a" ); b.answered()
    assert b.stopped


def test_counting_from_many_threads_loses_no_refusal():
    b = rt.RefusalBreaker( 10_000 )
    def work( n ):
        for i in range( 200 ): b.refused( f"{n}-{i}" )
    threads = [ threading.Thread( target=work, args=( n, ) ) for n in range( 8 ) ]
    for t in threads: t.start()
    for t in threads: t.join()
    assert b.refusals == 1600 and b.streak == 1600


def test_a_sweep_stops_at_the_limit_of_the_breaker_it_is_given( env ):
    door = Door( [ 422 ] )
    b    = rt.RefusalBreaker( 2 )
    sw   = rt.sweep( ctx_over( env, door ), N( "q" ), entries( 6 ), breaker=b )
    assert door.posts == 2 and sw[ "refused_422" ] == 2 and sw[ "stopped_by" ] == "consecutive_422" and len( sw[ "not_reached" ] ) == 4
    assert b.stopped


def test_a_sweep_given_a_stopped_breaker_asks_nothing( env ):
    door = Door( [ 200 ] )
    b    = rt.RefusalBreaker( 1 )
    b.refused( "earlier" )
    sw   = rt.sweep( ctx_over( env, door ), N( "q" ), entries( 3 ), breaker=b )
    assert door.posts == 0 and len( sw[ "not_reached" ] ) == 3 and sw[ "stopped_by" ] == "consecutive_422"


def test_a_sweep_without_a_breaker_makes_one_from_the_module_limit( env, monkeypatch ):
    monkeypatch.setattr( rt, "BREAKER_422", 3 )
    door = Door( [ 422 ] )
    sw   = rt.sweep( ctx_over( env, door ), N( "q" ), entries( 6 ) )
    assert door.posts == 3 and sw[ "stopped_by" ] == "consecutive_422"
