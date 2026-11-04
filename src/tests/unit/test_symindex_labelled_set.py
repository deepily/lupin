"""
The labelled set of the verdict layer: answered pairs joined to the negatives record.
"""
import pytest

from cosa.repo.symindex import labelled_set as ls


def _row( member, candidate, label, p=0.2 ):
    return { "member": member, "candidate": candidate, "label": label, "provides": 0.05, "coverage": 0.1, "score": 1.0, "p_overlap": p, "malformed": None, "unasked": False }


def _record():
    return { "members": {
        "m1": { "twins": [ "t1" ], "lexical": [ { "id": "l1", "score": 0.5 }, { "id": "l2", "score": 0.4 } ], "random": [ "r1" ], "held_out": [ { "id": "h1", "score": 0.95 } ] },
        "m2": { "twins": [ "t2" ], "lexical": [], "random": [ "r2", "r3" ], "held_out": [] } } }


def _answered():
    return [ _row( "m1", "t1", True ), _row( "m1", "l1", False ), _row( "m1", "r1", False ), _row( "m1", "h1", False ),
             _row( "m2", "t2", True ), _row( "m2", "r2", False ), _row( "stray", "x", False ) ]


def test_the_set_keeps_the_answered_pairs_of_the_record_and_reports_the_rest_by_class():
    got = ls.build( _record(), _answered() )
    assert [ ( r[ "member" ], r[ "candidate" ] ) for r in got[ "rows" ] ] == [ ( "m1", "t1" ), ( "m1", "l1" ), ( "m1", "r1" ), ( "m2", "t2" ), ( "m2", "r2" ) ]
    assert got[ "uncovered_counts" ] == { "twins": 0, "lexical": 1, "random": 1 }
    assert got[ "uncovered" ] == { "twins": [], "lexical": [ [ "m1", "l2" ] ], "random": [ [ "m2", "r3" ] ] }
    assert ( got[ "held_out" ], got[ "answered" ], got[ "ignored_rows" ] ) == ( 1, 5, 2 )


def test_a_held_out_pair_is_never_in_the_set_even_when_it_was_answered():
    assert ( "m1", "h1" ) not in [ ( r[ "member" ], r[ "candidate" ] ) for r in ls.build( _record(), _answered() )[ "rows" ] ]


def test_the_label_comes_from_the_record_and_a_row_that_disagrees_is_refused():
    rows = _answered()
    rows[ 0 ] = _row( "m1", "t1", False )
    with pytest.raises( ValueError, match="m1.*t1" ): ls.build( _record(), rows )


def test_a_pair_the_record_lists_twice_is_refused():
    rec = _record()
    rec[ "members" ][ "m1" ][ "random" ].append( "l1" )
    with pytest.raises( ValueError, match="twice" ): ls.build( rec, _answered() )


def test_an_answered_pair_that_appears_twice_is_refused():
    with pytest.raises( ValueError, match="answered twice" ): ls.build( _record(), _answered() + [ _row( "m1", "t1", True ) ] )


@pytest.mark.parametrize( "change", [ { "unasked": True, "p_overlap": None }, { "malformed": "sum_not_one" }, { "p_overlap": None } ] )
def test_a_row_that_was_never_asked_or_came_back_unreadable_is_uncovered_not_answered( change ):
    rows = [ { **r, **change } if ( r[ "member" ], r[ "candidate" ] ) == ( "m1", "t1" ) else r for r in _answered() ]
    got = ls.build( _record(), rows )
    assert got[ "uncovered_counts" ][ "twins" ] == 1 and got[ "uncovered" ][ "twins" ] == [ [ "m1", "t1" ] ]
    assert ( "m1", "t1" ) not in [ ( r[ "member" ], r[ "candidate" ] ) for r in got[ "rows" ] ] and got[ "answered" ] == 4


@pytest.mark.parametrize( "cls,pair_id", [ ( "twins", "t1" ), ( "lexical", "l1" ), ( "random", "r1" ) ] )
def test_a_held_out_pair_that_is_also_listed_in_a_class_is_refused( cls, pair_id ):
    rec = _record()
    rec[ "members" ][ "m1" ][ "held_out" ].append( { "id": pair_id, "score": 0.97 } )
    with pytest.raises( ValueError, match=f"m1.*{pair_id}.*held out" ): ls.build( rec, _answered() )
