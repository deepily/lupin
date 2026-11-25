"""
Tests that replay_loop.summarize still cuts a longer record list instead of refusing it.

The shared counter is strict by default, for the rerun script. summarize asks for the lenient zip.
A change of that argument fails a named test here.
"""

import pytest

from cosa.research.preference_replay import replay_loop as rl


def rec( correct ):
    return { "meta": { "correct": correct } }


RUN = { "records": { "engine": [ rec( True ), rec( True ), rec( False ), rec( True ) ], "base": [ rec( False ), rec( True ), rec( True ) ] },
        "not_replayable": [], "unrebuildable_cases": [], "families": 1 }


def test_summarize_cuts_the_longer_list_and_counts_the_pairs_that_match():
    got = rl.summarize( RUN, "base", 6 )
    assert ( got[ "engine_only_right" ], got[ "baseline_only_right" ] ) == ( 1, 1 ), "the fourth engine record has no partner and is not counted"


def test_the_shared_counter_is_strict_unless_asked_otherwise():
    assert rl.paired_wins( RUN, "engine", "base", strict=False ) == ( 1, 1 )
    with pytest.raises( ValueError ): rl.paired_wins( RUN, "engine", "base" )
