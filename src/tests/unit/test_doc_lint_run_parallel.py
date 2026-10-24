"""
Unit tests for harness_runner.run_parallel, called with items that are not pairs.

run_all reaches the same code with pairs; test_doc_lint_harness.py holds those cases and stays unchanged.
"""
import asyncio

import pytest

from cosa.repo.doc_lint import harness_runner as hn
from cosa.repo.doc_lint import model_transport as mt


def go( items, run_one, parallel, key=lambda item: item ):
    """Run run_parallel to completion and return its results."""
    return asyncio.run( hn.run_parallel( items, run_one, parallel, key ) )


def test_results_come_back_in_input_order_for_items_that_are_not_pairs():
    async def run_one( item ):
        await asyncio.sleep( 0.01 * ( 5 - item ) )          # later items finish first
        return item * 10
    assert go( [ 0, 1, 2, 3, 4 ], run_one, 5 ) == [ 0, 10, 20, 30, 40 ]


def test_with_parallel_one_the_items_run_one_at_a_time_in_order():
    seen = []
    async def run_one( item ):
        seen.append( ( "start", item ) )
        await asyncio.sleep( 0.001 )
        seen.append( ( "end", item ) )
        return item
    assert go( [ "a", "b" ], run_one, 1 ) == [ "a", "b" ]
    assert seen == [ ( "start", "a" ), ( "end", "a" ), ( "start", "b" ), ( "end", "b" ) ]


def test_at_most_parallel_items_are_in_flight_and_that_many_do_overlap():
    state = { "now": 0, "peak": 0 }
    async def run_one( item ):
        state[ "now" ] += 1
        state[ "peak" ] = max( state[ "peak" ], state[ "now" ] )
        await asyncio.sleep( 0.01 )
        state[ "now" ] -= 1
        return item
    go( list( range( 8 ) ), run_one, 3, key=lambda item: item )
    assert state[ "peak" ] == 3


def test_items_with_an_equal_key_never_overlap():
    state = { "now": 0, "peak": 0 }
    async def run_one( item ):
        state[ "now" ] += 1
        state[ "peak" ] = max( state[ "peak" ], state[ "now" ] )
        await asyncio.sleep( 0.005 )
        state[ "now" ] -= 1
        return item
    go( [ 1, 2, 3, 4 ], run_one, 4, key=lambda item: "same" )
    assert state[ "peak" ] == 1


def test_parallel_below_one_is_refused_before_any_item_runs():
    ran = []
    async def run_one( item ):
        ran.append( item )
    with pytest.raises( ValueError, match="parallel must be 1 or more, got 0" ):
        go( [ 1 ], run_one, 0 )
    assert ran == []


def test_a_sequential_failure_is_raised_and_sets_the_stop_signal():
    async def run_one( item ):
        if item == 1: raise RuntimeError( "boom" )
        return item
    with pytest.raises( RuntimeError, match="boom" ):
        go( [ 0, 1, 2 ], run_one, 1 )
    assert mt.AGY_WAKE.is_set()


def test_a_stop_signal_left_from_an_earlier_run_is_cleared_first():
    mt.AGY_WAKE.set()
    async def run_one( item ):
        return mt.AGY_WAKE.is_set()
    assert go( [ 0 ], run_one, 1 ) == [ False ]
    assert go( [ 0, 1 ], run_one, 2 ) == [ False, False ]


def test_a_parallel_failure_skips_items_not_started_and_lets_those_in_flight_finish():
    finished = []
    async def run_one( item ):
        await asyncio.sleep( 0.01 )
        if item == 1: raise RuntimeError( "second dies" )
        finished.append( item )
        return item
    with pytest.raises( RuntimeError, match="second dies" ):
        go( [ 0, 1, 2, 3, 4 ], run_one, 3 )
    assert finished == [ 0, 2 ]                              # 0 and 2 were in flight beside 1; 3 and 4 never started
    assert mt.AGY_WAKE.is_set()


def test_the_earliest_failure_in_input_order_is_raised():
    async def run_one( item ):
        await asyncio.sleep( 0.01 * ( 3 - item ) )          # item 2 fails first in time, item 0 is first in order
        raise RuntimeError( f"failed {item}" )
    with pytest.raises( RuntimeError, match="failed 0" ):
        go( [ 0, 1, 2 ], run_one, 3 )


def test_a_cut_short_wait_is_passed_over_for_the_failure_that_cut_it():
    async def run_one( item ):
        await asyncio.sleep( 0.01 )                          # both are in flight before either fails
        if item == 0: raise mt.ModelWaitCutShort( "woken" )
        raise RuntimeError( "the real cause" )
    with pytest.raises( RuntimeError, match="the real cause" ):
        go( [ 0, 1 ], run_one, 2 )


def test_when_every_failure_is_a_cut_short_wait_the_earliest_of_them_is_raised():
    async def run_one( item ):
        await asyncio.sleep( 0.01 )
        raise mt.ModelWaitCutShort( f"woken {item}" )
    with pytest.raises( mt.ModelWaitCutShort, match="woken 0" ):
        go( [ 0, 1 ], run_one, 2 )
