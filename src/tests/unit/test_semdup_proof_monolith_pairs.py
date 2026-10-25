"""Unit tests for semdup.proof.monolith_pairs: the three sources, the pin and the tag check."""
import hashlib
import subprocess

import pytest

from cosa.repo.semdup import errors as err
from cosa.repo.semdup.proof import monolith_pairs as mp


def defs_of( *ids ):
    """Build definition records that carry only an id."""
    return [ { "id": i } for i in ids ]


def clone( a, b, size ):
    """Build a structural clone pair."""
    return { "ids": sorted( [ a, b ] ), "size": size, "source": "jscpd" }


VECTORS = { "a": [ 1.0, 0.0 ], "b": [ 0.99, 0.1 ], "c": [ 0.0, 1.0 ], "d": [ 0.1, 0.99 ], "e": [ 0.7, 0.7 ], "z": [ 0.0, 0.0 ] }


# ---- candidate_pairs --------------------------------------------------------------------------------------------

def test_each_source_contributes_its_own_pairs_with_its_own_tag():
    defs   = defs_of( "a", "b", "c", "d" )
    out    = mp.candidate_pairs( defs, [ clone( "a", "b", 90 ) ], VECTORS, [ [ "a", "c" ] ], per_source=1 )
    assert out == [ { "ids": [ "a", "b" ], "source": "structural" }, { "ids": [ "c", "d" ], "source": "neighbour" }, { "ids": [ "a", "c" ], "source": "nominated" } ]


def test_the_neighbour_source_skips_pairs_the_structural_list_already_holds_and_goes_on_to_the_next_closest():
    defs = defs_of( "a", "b", "c", "d" )
    out  = mp.candidate_pairs( defs, [ clone( "a", "b", 90 ), clone( "c", "d", 80 ) ], VECTORS, [], per_source=1 )
    assert [ ( p[ "ids" ], p[ "source" ] ) for p in out ] == [ ( [ "a", "b" ], "structural" ), ( [ "b", "d" ], "neighbour" ) ]


def test_structural_takes_the_largest_clones_first_and_only_those_inside_the_monolith():
    defs = defs_of( "a", "b", "c", "d" )
    out  = mp.candidate_pairs( defs, [ clone( "a", "b", 50 ), clone( "c", "d", 70 ), clone( "a", "outside", 99 ) ], VECTORS, [], per_source=1 )
    assert [ p[ "ids" ] for p in out if p[ "source" ] == "structural" ] == [ [ "c", "d" ] ]
    two = mp.candidate_pairs( defs, [ clone( "a", "b", 50 ), clone( "c", "d", 70 ) ], VECTORS, [], per_source=2 )
    assert [ p[ "ids" ] for p in two if p[ "source" ] == "structural" ] == [ [ "a", "b" ], [ "c", "d" ] ]


def test_neighbours_are_ranked_by_cosine_with_ties_broken_by_ids_and_a_zero_vector_scores_zero():
    two = mp.candidate_pairs( defs_of( "a", "b", "c", "z" ), [], VECTORS, [], per_source=2 )
    assert [ p[ "ids" ] for p in two ] == [ [ "a", "b" ], [ "b", "c" ] ]
    out = mp.candidate_pairs( defs_of( "a", "b", "c", "z" ), [], VECTORS, [], per_source=4 )
    assert [ p[ "ids" ] for p in out ] == [ [ "a", "b" ], [ "a", "c" ], [ "a", "z" ], [ "b", "c" ] ]
    ties = mp.candidate_pairs( defs_of( "p", "q", "r" ), [], { "p": [ 1.0, 0.0 ], "q": [ 1.0, 0.0 ], "r": [ 1.0, 0.0 ] }, [], per_source=2 )
    assert [ p[ "ids" ] for p in ties ] == [ [ "p", "q" ], [ "p", "r" ] ]


def test_equal_similarities_are_broken_by_the_first_id_and_then_the_second():
    same = { i: [ 1.0, 0.0 ] for i in "abcd" }
    out  = mp.candidate_pairs( defs_of( *"abcd" ), [], same, [], per_source=3 )
    assert [ p[ "ids" ] for p in out ] == [ [ "a", "b" ], [ "a", "c" ], [ "a", "d" ] ]


def test_similarity_is_the_cosine_so_a_long_vector_does_not_outrank_a_close_direction():
    vectors = { "x": [ 10.0, 0.0 ], "y": [ 1.0, 1.0 ], "w": [ 0.01, 0.01 ] }
    out     = mp.candidate_pairs( defs_of( "x", "y", "w" ), [], vectors, [], per_source=1 )
    assert [ p[ "ids" ] for p in out ] == [ [ "w", "y" ] ]


def test_a_pair_found_by_two_sources_keeps_the_earlier_source_and_appears_once():
    out = mp.candidate_pairs( defs_of( "a", "b", "c" ), [ clone( "a", "b", 90 ) ], VECTORS, [ [ "b", "a" ], [ "a", "c" ] ], per_source=1 )
    assert [ ( p[ "ids" ], p[ "source" ] ) for p in out ] == [ ( [ "a", "b" ], "structural" ), ( [ "b", "c" ], "neighbour" ), ( [ "a", "c" ], "nominated" ) ]


def test_a_nominated_pair_that_is_not_two_definitions_of_the_monolith_is_refused():
    defs = defs_of( "a", "b" )
    for bad in ( [ "a", "a" ], [ "a", "missing" ], [ "missing", "b" ] ):
        with pytest.raises( ValueError, match="not two distinct definitions" ): mp.candidate_pairs( defs, [], VECTORS, [ bad ], per_source=1 )
    with pytest.raises( ValueError, match="per_source must be 1 or more" ): mp.candidate_pairs( defs, [], VECTORS, [], per_source=0 )


# ---- assemble_pairs ---------------------------------------------------------------------------------------------

def test_every_tag_is_accepted_and_the_list_is_ordered_by_source_then_ids():
    tagged = [ { "ids": [ "z", "y" ], "source": "nominated" }, { "ids": [ "b", "a" ], "source": "structural" }, { "ids": [ "c", "d" ], "source": "neighbour" }, { "ids": [ "e", "f" ], "source": "structural" } ]
    assert [ ( p[ "source" ], p[ "ids" ] ) for p in mp.assemble_pairs( tagged ) ] == [ ( "structural", [ "a", "b" ] ), ( "structural", [ "e", "f" ] ), ( "neighbour", [ "c", "d" ] ), ( "nominated", [ "y", "z" ] ) ]


@pytest.mark.parametrize( "pair", [ { "ids": [ "a", "b" ] }, { "ids": [ "a", "b" ], "source": None }, { "ids": [ "a", "b" ], "source": "guess" }, { "ids": [ "a", "b" ], "source": "" } ] )
def test_a_pair_with_no_tag_or_a_tag_outside_the_three_is_refused_by_name(pair):
    with pytest.raises( err.SemdupError ) as caught: mp.assemble_pairs( [ pair ] )
    assert caught.value.code == err.BAD_PAIR_SOURCE


def test_a_pair_listed_twice_is_refused_even_when_written_the_other_way_round():
    with pytest.raises( ValueError, match="listed twice" ): mp.assemble_pairs( [ { "ids": [ "a", "b" ], "source": "structural" }, { "ids": [ "b", "a" ], "source": "neighbour" } ] )


# ---- the pin ----------------------------------------------------------------------------------------------------

def test_blob_sha_equals_what_git_hash_object_gives(tmp_path):
    path = tmp_path / "m.js"
    path.write_bytes( b"function a() {}\n\xc3\xa9\n" )
    git = subprocess.run( [ "git", "hash-object", str( path ) ], capture_output=True, text=True, check=True ).stdout.strip()
    assert mp.blob_sha( path ) == git and len( git ) == 40


def test_a_changed_monolith_is_refused_and_the_pinned_one_passes(tmp_path):
    path = tmp_path / "m.js"
    path.write_text( "one\n", encoding="utf-8" )
    pinned = mp.blob_sha( path )
    mp.check_pin( path, pinned )
    path.write_text( "two\n", encoding="utf-8" )
    with pytest.raises( ValueError, match=f"pinned to {pinned}" ): mp.check_pin( path, pinned )
