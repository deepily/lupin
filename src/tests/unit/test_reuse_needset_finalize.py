"""
Choosing what the reviewers see, and the item built for a need.
"""
import copy

import pytest

from cosa.repo.labelling import errors as lbe
from lupin_mcp.reuse_needset import draft, finalize, schema
from lupin_mcp.reuse_needset import errors as er

COMMIT  = "0123456789abcdef0123456789abcdef01234567"
DRAFTER = { "model": draft.DRAFTER_MODEL, "prompt_version": "v1", "server": "max-plan" }
SENTENCE = "A function that adds up a list of numbers but stops once a ceiling has been reached."


def checked( need, result="agree" ):
    """Return a copy of a drafted need, checked with the given result."""
    out = copy.deepcopy( need )
    out[ "check" ], out[ "status" ] = { "model": "claude-opus-5-5", "result": result, "note": "n", "mechanical": [] }, "checked"
    schema.validate_need( out )
    return out


def matched( n, result="agree" ):
    """Return a checked near-copy need number n."""
    return checked( schema.new_need( "near_copy", "py", f"pkg.a.f{n}", None, [ f"pkg.b.g{n}" ], "py", "twin", SENTENCE, COMMIT, DRAFTER ), result )


def nothing( n, result="agree" ):
    """Return a checked nothing-exists need number n."""
    return checked( schema.new_need( "nothing", "py", None, None, [], None, None, f"A function that does job number {n} and returns its result to the caller.", COMMIT, DRAFTER ), result )


def pile():
    """Return 20 agreed matched needs, 2 disputed, 4 agreed nothing and 1 disputed nothing."""
    return [ matched( n ) for n in range( 20 ) ] + [ matched( 20, "disagree" ), matched( 21, "unsure" ) ] + [ nothing( n ) for n in range( 4 ) ] + [ nothing( 9, "disagree" ) ]


@pytest.mark.parametrize( "n, expected", [ ( 0, 0 ), ( 1, 0 ), ( 3, 0 ), ( 4, 1 ), ( 7, 1 ), ( 10, 2 ), ( 20, 3 ), ( 30, 5 ), ( 100, 15 ) ] )
def test_the_sample_is_fifteen_percent_with_a_half_rounded_up( n, expected ):
    assert finalize.sample_size( n ) == expected
    assert round( 4.5 ) == 4, "Python's round goes to even, which is why this does not use it"


def test_disputed_then_nothing_then_a_seeded_sample_then_pairs_each_sorted_by_id():
    needs = pile()
    got   = finalize.select_for_labelling( needs, 11, semdup_items=[ "p2", "p1" ] )
    by    = lambda reason: [ g[ "id" ] for g in got if g[ "reason" ] == reason ]
    ids   = { n[ "id" ]: n for n in needs }
    assert [ g[ "reason" ] for g in got ] == [ "disputed" ] * 3 + [ "nothing" ] * 4 + [ "sample" ] * 3 + [ "semdup_pair" ] * 2
    assert by( "disputed" ) == sorted( i for i, n in ids.items() if n[ "check" ][ "result" ] != "agree" ) and len( by( "disputed" ) ) == 3
    assert by( "nothing" ) == sorted( i for i, n in ids.items() if n[ "kind" ] == "nothing" and n[ "check" ][ "result" ] == "agree" )
    assert by( "semdup_pair" ) == [ "p1", "p2" ] and len( {g[ "id" ] for g in got} ) == len( got )
    agreed = {i for i, n in ids.items() if n[ "kind" ] != "nothing" and n[ "check" ][ "result" ] == "agree"}
    assert set( by( "sample" ) ) <= agreed and by( "sample" ) == sorted( by( "sample" ) )


def test_the_same_needs_and_seed_give_the_same_list_and_another_seed_another_sample():
    needs = pile()
    one   = finalize.select_for_labelling( needs, 11 )
    assert finalize.select_for_labelling( list( reversed( needs ) ), 11 ) == one
    assert [ g for g in finalize.select_for_labelling( needs, 12 ) if g[ "reason" ] == "sample" ] != [ g for g in one if g[ "reason" ] == "sample" ]


def test_the_sample_for_one_seed_is_these_ids():
    got = finalize.select_for_labelling( pile(), 11 )
    assert [ g[ "id" ] for g in got if g[ "reason" ] == "sample" ] == [ "n-0502350ad6", "n-8c19a21adc", "n-c84823c57b" ]


def test_an_unchecked_need_and_a_smoke_need_are_refused():
    drafted = schema.new_need( "near_copy", "py", "pkg.a.f", None, [ "pkg.b.g" ], "py", "twin", SENTENCE, COMMIT, DRAFTER )
    with pytest.raises( er.NeedsetError ) as e: finalize.select_for_labelling( [ drafted ], 1 )
    assert e.value.code == er.BAD_NEED
    smoke = checked( schema.new_need( "near_copy", "py", "pkg.a.f", None, [ "pkg.b.g" ], "py", "twin", SENTENCE, COMMIT, DRAFTER, smoke=True ) )
    with pytest.raises( er.NeedsetError ) as e: finalize.select_for_labelling( [ smoke ], 1 )
    assert e.value.code == er.BAD_NEED and "smoke" in e.value.detail


def test_no_needs_and_no_agreed_needs_select_nothing_for_the_sample():
    assert finalize.select_for_labelling( [], 1 ) == []
    assert [ g[ "reason" ] for g in finalize.select_for_labelling( [ matched( 0, "disagree" ) ], 1 ) ] == [ "disputed" ]


def test_the_item_for_a_matched_need_holds_the_sentence_and_the_key_sources_and_no_verdict():
    item = finalize.need_item( matched( 1, "disagree" ), key_texts=[ "def g(): pass" ] )
    assert item[ "type" ] == "need_key" and item[ "payload" ] == { "need": SENTENCE, "key_sources": [ "def g(): pass" ] } and set( item ) == { "item_id", "type", "payload" }


def test_the_item_for_a_nothing_need_holds_the_hits_and_says_nothing_exists():
    item = finalize.need_item( nothing( 1 ), hits=[ "pkg.a.f() — Adds." ] )
    assert item[ "payload" ][ "nothing_exists" ] is True and item[ "payload" ][ "hits" ] == [ "pkg.a.f() — Adds." ] and "key_sources" not in item[ "payload" ]


def test_material_that_does_not_fit_the_kind_is_a_bad_item():
    for need, kwargs in ( ( matched( 1 ), {} ), ( nothing( 1 ), {} ) ):
        with pytest.raises( lbe.LabellingError ) as e: finalize.need_item( need, **kwargs )
        assert e.value.code == lbe.BAD_ITEM
