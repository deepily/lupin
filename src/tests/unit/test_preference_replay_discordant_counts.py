#!/usr/bin/env python3
"""
paired_wins, the re-score's discordant counts, on planted pairs with known counts.

Venue: :7999-eligible / local, pure.
"""
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.research.preference_replay import pairing, replay_loop


def run_of( **arms ):
    return { "records": { name: [ { "meta": { "correct": bool( c ) } } for c in correct ] for name, correct in arms.items() } }


def test_planted_pairs_give_their_exact_discordant_counts():
    # 3 asks only "new" got right, 2 only "old", 4 both, 1 neither
    new = [ 1, 1, 1, 0, 0, 1, 1, 1, 1, 0 ]
    old = [ 0, 0, 0, 1, 1, 1, 1, 1, 1, 0 ]
    run = run_of( new=new, old=old )
    assert replay_loop.paired_wins( run, "new", "old" ) == ( 3, 2 )
    assert replay_loop.paired_wins( run, "old", "new" ) == ( 2, 3 )


def test_arms_that_agree_everywhere_have_no_discordant_pair():
    run = run_of( a=[ 1, 0, 1 ], b=[ 1, 0, 1 ] )
    assert replay_loop.paired_wins( run, "a", "b" ) == ( 0, 0 )


def test_an_ask_missing_from_one_arm_is_refused():
    with pytest.raises( ValueError ): replay_loop.paired_wins( run_of( a=[ 1, 0 ], b=[ 1 ] ), "a", "b" )


def records( snapshot="s1", **correct_by_id ):
    return [ { "snapshot_sha256": snapshot, "meta": { "notification_id": i, "correct": bool( c ) } } for i, c in correct_by_id.items() ]


def test_arms_in_different_orders_are_paired_by_ask_id_not_by_position():
    new = records( a=1, b=1, c=0, d=0 )
    old = records( d=0, c=0, b=1, a=0 )
    first, second = pairing.pair_by_ask( new, old )
    assert [ r[ "meta" ][ "notification_id" ] for r in second ] == [ "a", "b", "c", "d" ] and first == new
    # by id only ask "a" differs; by position all four places would be read against another ask
    assert replay_loop.paired_wins( { "records": { "new": first, "old": second } }, "new", "old" ) == ( 1, 0 )
    assert replay_loop.paired_wins( { "records": { "new": new, "old": old } }, "new", "old" ) == ( 2, 1 )


def test_two_empty_arms_pair_to_nothing():
    assert pairing.pair_by_ask( [], [] ) == ( [], [] )


@pytest.mark.parametrize( "a, b, reason", [
    ( records( a=1 ),                          records( "s2", a=1 ),                     "one snapshot" ),
    ( records( a=1 ) + records( "s2", b=1 ),   records( a=1 ) + records( "s2", b=1 ),    "one snapshot" ),
    ( records( a=1 ) + records( a=0 ),         records( a=1 ),                           "twice" ),
    ( records( a=1 ),                          records( a=1 ) + records( a=0 ),          "twice" ),
    ( records( a=1, b=1 ),                     records( a=1, c=1 ),                      "different asks" ),
    ( records( a=1 ),                          records( a=1, c=1 ),                      "different asks" ),
    ( records( a=1, c=1 ),                     records( a=1 ),                           "different asks" ),
] )
def test_arms_that_cannot_be_paired_are_refused( a, b, reason ):
    with pytest.raises( ValueError, match=reason ): pairing.pair_by_ask( a, b )


def test_a_record_with_no_snapshot_is_refused():
    with pytest.raises( KeyError ): pairing.pair_by_ask( [ { "meta": { "notification_id": "a" } } ], records( a=1 ) )
