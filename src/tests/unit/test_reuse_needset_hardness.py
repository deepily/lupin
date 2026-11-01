"""
The hardness sourcer: a work-alike seed counts only when a plain word search misses it.

Set B takes real code whose need a BM25 search over identifiers and docstrings does not return in its top 10.
The fixtures fix each rank in advance with filler words, not by reading it back from the code under test.
"""
import pytest

from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import hardness


def entry( i, name, doc="" ):
    """Ensures: returns an index record with the fields the hardness search reads."""
    return { "id": i, "module": "m", "name": name, "sig": "()", "doc": doc }


def crowded_index():
    """
    Build an index where 13 entries outrank "target_late" on the query "banana".

    Ensures: returns ( index, entries ), the 13 being 12 crowd entries and "target_best".

    The crowd entries hold the word twice in a short text and the best entry three times. The late entry holds it once among filler words, and the never entry not at all.
    """
    crowd   = [ entry( f"m.crowd{n:02d}", "banana", "banana" ) for n in range( 12 ) ]
    late    = entry( "m.target_late", "target_late", "a banana among many other filler words that dilute the score" )
    never   = entry( "m.target_never", "target_never", "turns one text into another" )
    best    = entry( "m.target_best", "banana_best", "banana banana banana" )
    entries = crowd + [ late, never, best ]
    return hardness.build_index( entries ), entries


def test_a_target_ranked_below_ten_or_not_listed_is_hard_and_one_inside_ten_is_not():
    index, _ = crowded_index()
    late, never, best = ( hardness.rank_of( index, "banana", t ) for t in ( "m.target_late", "m.target_never", "m.target_best" ) )
    assert never is None and late == 14 and best == 1
    assert [ hardness.is_hard( r ) for r in ( never, late, best ) ] == [ True, True, False ]


def test_the_cut_off_sits_between_ten_and_eleven():
    assert hardness.BM25_K == 10
    assert [ hardness.is_hard( r ) for r in ( 10, 11 ) ] == [ False, True ]
    assert [ hardness.is_hard( r, k=3 ) for r in ( 3, 4 ) ] == [ False, True ]


def test_excluded_ids_are_removed_before_the_rank_is_counted():
    index, _ = crowded_index()
    assert hardness.rank_of( index, "banana", "m.target_late", exclude=( "m.crowd00", "m.crowd01" ) ) == 12
    assert hardness.rank_of( index, "banana", "m.target_late", exclude=() ) == 14


def test_a_row_is_hard_only_when_every_target_is_missed_and_the_seed_is_left_out():
    index, _ = crowded_index()
    rows = [ { "seed": "m.crowd00", "need": "banana", "targets": [ "m.target_late" ], "lang": "py" },
             { "seed": "m.crowd00", "need": "banana", "targets": [ "m.target_late", "m.target_best" ], "lang": "py" },
             { "seed": "m.crowd00", "need": "banana", "targets": [ "m.target_best" ], "lang": "ts" } ]
    out = hardness.source_hard( rows, index )
    assert [ r[ "hard" ] for r in out ] == [ True, False, False ]
    assert out[ 0 ][ "ranks" ] == { "m.target_late": 13 }          # the seed was one of the 12 crowd entries and is gone
    assert out[ 1 ][ "hard_members" ] == [ "m.target_late" ]
    assert out[ 1 ][ "ranks" ] == { "m.target_late": 13, "m.target_best": 1 }
    assert "ranks" not in rows[ 0 ] and "hard" not in rows[ 0 ]    # the rows given are not changed


def test_a_row_with_no_targets_is_refused_by_name():
    index, _ = crowded_index()
    with pytest.raises( er.NeedsetError ) as caught:
        hardness.source_hard( [ { "seed": "m.s", "need": "banana", "targets": [], "lang": "py" } ], index )
    assert caught.value.code == er.BAD_NEED


def test_the_yield_is_counted_per_language_per_hundred_seeds():
    index, _ = crowded_index()
    rows = [ { "seed": "m.s", "need": "banana", "targets": [ t ], "lang": lang }
             for t, lang in ( ( "m.target_never", "py" ), ( "m.target_best", "py" ), ( "m.target_late", "ts" ), ( "m.target_never", "ts" ) ) ]
    report = hardness.yield_report( hardness.source_hard( rows, index ) )
    assert report == { "k": 10, "seeds": 4, "hard": 3,
                       "by_lang": { "py": { "seeds": 2, "hard": 1, "per_100": 50.0 }, "ts": { "seeds": 2, "hard": 2, "per_100": 100.0 } } }


def test_the_search_reads_identifiers_and_docstrings_and_not_the_body():
    assert hardness.HARDNESS_FIELDS == ( "id", "module", "name", "sig", "doc" )
    index = hardness.build_index( [ entry( "m.a", "alpha", "uses zebra" ), entry( "m.b", "beta", "plain" ) ] )
    assert hardness.rank_of( index, "zebra", "m.a" ) == 1
    assert hardness.rank_of( index, "zebra", "m.b" ) is None


def test_a_seed_that_is_its_own_target_is_refused_by_name_before_any_rank_is_read():
    index, _ = crowded_index()
    rows = [ { "seed": "m.target_late", "need": "banana", "targets": [ "m.target_best", "m.target_late" ], "lang": "py" } ]
    with pytest.raises( er.NeedsetError ) as caught: hardness.source_hard( rows, index )
    assert caught.value.code == er.SEED_IS_TARGET and "m.target_late" in caught.value.detail
