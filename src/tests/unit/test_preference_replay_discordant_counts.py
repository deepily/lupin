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

from cosa.research.preference_replay import replay_loop


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
