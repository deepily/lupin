"""Unit tests for semdup.cluster: pair joining, clusters, surplus and score."""
import pytest

from cosa.repo.semdup import cluster as cl
from cosa.repo.semdup import errors as err


def row( a, b, verdict ):
    """Build a verdict row of definition a on candidate b."""
    return { "id": a, "candidate": b, "verdict": verdict, "reason": "r", "slot": 0 }


def origins( new=(), server=() ):
    """Map each id to its origin."""
    return { **{ i: "new" for i in new }, **{ i: "server" for i in server } }


# ---- join_pairs -------------------------------------------------------------------------------------------------

def test_a_pair_is_flagged_when_either_side_rules_duplicate_or_near_duplicate():
    rows = [ row( "b", "a", "duplicate" ), row( "a", "b", "distinct" ), row( "c", "d", "near_duplicate" ), row( "d", "c", "related" ) ]
    assert cl.join_pairs( rows ) == [ [ "a", "b" ], [ "c", "d" ] ]


def test_related_and_distinct_join_nothing_and_a_pair_flagged_twice_is_listed_once():
    assert cl.join_pairs( [ row( "a", "b", "related" ), row( "b", "a", "distinct" ) ] ) == []
    twice = [ row( "a", "b", "duplicate" ), row( "b", "a", "duplicate" ), { **row( "a", "b", "duplicate" ), "slot": 1 } ]
    assert cl.join_pairs( twice ) == [ [ "a", "b" ] ]


def test_a_definition_is_never_paired_with_itself_and_no_rows_give_no_pairs():
    assert cl.join_pairs( [ row( "a", "a", "duplicate" ) ] ) == [] and cl.join_pairs( [] ) == []


# ---- clusters ---------------------------------------------------------------------------------------------------

def test_a_chain_a_b_c_is_one_cluster_of_three_and_a_lone_id_is_a_cluster_of_one():
    assert cl.clusters( [ "a", "b", "c", "z" ], [ [ "a", "b" ], [ "b", "c" ] ] ) == [ [ "a", "b", "c" ], [ "z" ] ]


def test_clusters_are_ordered_by_first_id_and_members_are_sorted_whatever_the_input_order():
    assert cl.clusters( [ "m", "k", "b", "a" ], [ [ "m", "k" ] ] ) == [ [ "a" ], [ "b" ], [ "k", "m" ] ]


def test_a_definition_paired_with_two_others_joins_all_three():
    assert cl.clusters( [ "a", "b", "c", "d" ], [ [ "a", "b" ], [ "a", "c" ] ] ) == [ [ "a", "b", "c" ], [ "d" ] ]


def test_two_separate_pairs_make_two_clusters():
    assert cl.clusters( list( "abcd" ), [ [ "a", "b" ], [ "c", "d" ] ] ) == [ [ "a", "b" ], [ "c", "d" ] ]


def test_a_pair_that_names_an_unknown_id_is_refused_on_either_side():
    with pytest.raises( ValueError, match="x" ): cl.clusters( [ "a" ], [ [ "a", "x" ] ] )
    with pytest.raises( ValueError, match="x" ): cl.clusters( [ "a" ], [ [ "x", "a" ] ] )


def test_union_find_joins_a_long_chain_declared_from_the_far_end():
    ids = [ f"d{i:02d}" for i in range( 12 ) ]
    pairs = [ [ ids[ i ], ids[ i + 1 ] ] for i in reversed( range( 11 ) ) ]
    assert cl.clusters( ids, pairs ) == [ ids ]


# ---- surplus ----------------------------------------------------------------------------------------------------

def test_three_new_definitions_in_one_cluster_give_surplus_two():
    assert cl.surplus( [ [ "a", "b", "c" ] ], origins( new="abc" ) ) == 2


def test_two_new_and_one_server_in_one_cluster_give_surplus_two():
    assert cl.surplus( [ [ "a", "b", "s" ] ], origins( new="ab", server="s" ) ) == 2


def test_one_new_and_one_server_give_surplus_one():
    assert cl.surplus( [ [ "a", "s" ] ], origins( new="a", server="s" ) ) == 1


def test_one_new_definition_joined_to_two_server_definitions_gives_surplus_one_not_two():
    assert cl.surplus( [ [ "a", "s", "t" ] ], origins( new="a", server="st" ) ) == 1


def test_two_separate_new_pairs_give_surplus_two_and_lone_definitions_give_none():
    assert cl.surplus( [ [ "a", "b" ], [ "c", "d" ], [ "e" ], [ "s" ] ], origins( new="abcde", server="s" ) ) == 2


def test_a_cluster_of_servers_only_adds_nothing_and_cannot_go_negative():
    assert cl.surplus( [ [ "s", "t" ], [ "u" ] ], origins( server="stu" ) ) == 0


# ---- sizes and the score ----------------------------------------------------------------------------------------

def test_clusters_are_counted_by_size_with_distinct_sizes_two_three_four():
    groups = [ [ "a", "b" ], [ "c", "d", "e" ], [ "f", "g", "h", "i" ], [ "j" ] ]
    assert cl.sizes( groups ) == { "2": 1, "3": 1, "4": 1 }
    assert cl.surplus( groups, origins( new="abcdefghij" ) ) == 1 + 2 + 3
    assert cl.sizes( [ [ "a", "b" ], [ "c", "d" ] ] ) == { "2": 2 } and cl.sizes( [ [ "a" ] ] ) == {}


def test_the_score_is_surplus_per_one_hundred_passing_tests():
    assert cl.score( 3, 50 ) == 6.0 and cl.score( 0, 10 ) == 0.0 and cl.score( 1, 3 ) == pytest.approx( 33.3333333 )


@pytest.mark.parametrize( "passing", [ 0, -1 ] )
def test_a_score_over_no_passing_tests_is_refused_by_name_with_the_raw_surplus_in_the_message(passing):
    with pytest.raises( err.SemdupError ) as caught: cl.score( 4, passing )
    assert caught.value.code == err.NO_PASSING_TESTS and "raw surplus 4" in caught.value.detail
