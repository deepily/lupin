"""
Tests of the constructor fold in the verdict shortlist.

A Dart class and its constructor are two index entries. The model scores the constructor far above the class.
Without the fold, a family of near-identical classes fills the shortlist with constructor ids.
Each test names the path it covers: the old policy lists both, the shipped policy merges them, and a lone constructor stays.
"""
import pytest

from cosa.repo.symindex import verdict as vd

PKG = "app:lib.models."


def _family( n ):
    """Ensures: returns the ids of n classes and the default constructor id of each."""
    classes = [ f"{PKG}E{k:02d}Exception" for k in range( n ) ]
    return classes, [ f"{c}.{c.rpartition( '.' )[ 2 ]}" for c in classes ]


def _answer( i, p ):
    """Ensures: returns a valid old-style answer whose p_overlap is p and whose choice is reuse."""
    return { "id": i, "probabilities": { "reuse": p, "extend": 0.0, "unrelated": round( 1.0 - p, 6 ) } }


def _old_question( classes, ctors, others, class_p=0.7, ctor_p=0.99, other_p=0.9, policy=None ):
    """Ensures: returns decide over class, constructor and other rows at three scores."""
    answers = [ _answer( i, class_p ) for i in classes ] + [ _answer( i, ctor_p ) for i in ctors ] + [ _answer( i, other_p ) for i in others ]
    return vd.decide( answers, [ a[ "id" ] for a in answers ], [], set(), vd.POLICY if policy is None else policy )


OLD = { k: v for k, v in vd.POLICY.items() if k != "fold_constructors" }
OTHERS = [ f"{PKG}Other{k}" for k in range( 6 ) ]


def test_constructor_class_id_of_a_default_constructor():
    assert vd.constructor_class_id( "app:lib.m.Foo.Foo" ) == "app:lib.m.Foo"


def test_constructor_class_id_of_a_named_constructor():
    assert vd.constructor_class_id( "app:lib.m.Foo.Foo.fromJson" ) == "app:lib.m.Foo"


@pytest.mark.parametrize( "entry_id", [ "app:lib.m.Foo", "app:lib.m.Foo.run", "a.b", "solo" ] )
def test_constructor_class_id_is_none_for_other_ids( entry_id ):
    assert vd.constructor_class_id( entry_id ) is None


def test_without_the_fold_key_the_constructors_crowd_the_classes_out():
    classes, ctors = _family( 8 )
    got = _old_question( classes, ctors, OTHERS, policy=OLD )
    ids = [ r[ "id" ] for r in got[ "shortlist" ] ]
    assert set( ids ) & set( classes ) == set()
    assert got[ "shortlist_total" ] == 22


def test_with_the_fold_each_class_takes_one_slot_at_its_constructors_score():
    classes, ctors = _family( 8 )
    got = _old_question( classes, ctors, OTHERS )
    top = got[ "shortlist" ][ :8 ]
    assert sorted( r[ "id" ] for r in top ) == classes
    assert { r[ "p_overlap" ] for r in top } == { 0.99 }
    assert len( got[ "shortlist" ] ) == 10 and got[ "shortlist_total" ] == 14


def test_a_class_scored_above_its_constructor_keeps_its_own_score():
    classes, ctors = _family( 1 )
    got = _old_question( classes, ctors, [], class_p=0.95, ctor_p=0.5 )
    assert [ ( r[ "id" ], r[ "p_overlap" ] ) for r in got[ "shortlist" ] ] == [ ( classes[ 0 ], 0.95 ) ]


def test_a_class_below_the_threshold_still_surfaces_through_its_constructor():
    classes, ctors = _family( 1 )
    got = _old_question( classes, ctors, [], class_p=0.05, ctor_p=0.8 )
    assert [ r[ "id" ] for r in got[ "shortlist" ] ] == classes


def test_a_constructor_whose_class_is_not_an_entry_stays_under_its_own_id():
    classes, ctors = _family( 2 )
    got = _old_question( [ classes[ 0 ] ], ctors, [] )
    assert sorted( r[ "id" ] for r in got[ "shortlist" ] ) == sorted( [ classes[ 0 ], ctors[ 1 ] ] )


def test_a_named_constructor_folds_into_its_class_beside_the_default_one():
    cls = f"{PKG}Thing"
    got = _old_question( [ cls ], [ f"{cls}.Thing", f"{cls}.Thing.fromJson" ], [] )
    assert [ r[ "id" ] for r in got[ "shortlist" ] ] == [ cls ] and got[ "shortlist_total" ] == 1


def test_the_verdict_nearest_and_doubtful_do_not_change_with_the_fold():
    classes, ctors = _family( 3 )
    a = _old_question( classes, ctors, OTHERS )
    b = _old_question( classes, ctors, OTHERS, policy=OLD )
    assert ( a[ "verdict" ], a[ "causes" ], a[ "nearest" ], a[ "doubtful" ] ) == ( b[ "verdict" ], b[ "causes" ], b[ "nearest" ], b[ "doubtful" ] )


def _pair_answers( rows ): return [ { "id": i, "provides": p, "coverage": { "0": 0.1, "1": 0.0, "2": 0.9, "3": 0.0 } } for i, p in rows ]


def _pair_question( rows, policy=None ):
    answers = _pair_answers( rows )
    return vd.decide_provides( answers, [ a[ "id" ] for a in answers ], [], set(), policy )


PAIR_OLD = { k: v for k, v in vd.POLICY_PROVIDES.items() if k != "fold_constructors" }


def test_decide_provides_without_the_key_lists_the_constructors_and_not_the_classes():
    classes, ctors = _family( 8 )
    rows = [ ( c, 0.75 ) for c in classes ] + [ ( k, 0.95 ) for k in ctors ] + [ ( o, 0.8 ) for o in OTHERS ]
    got = _pair_question( rows, PAIR_OLD )
    assert got[ "verdict" ] == "REUSE" and set( r[ "id" ] for r in got[ "shortlist" ] ) & set( classes ) == set()
    assert got[ "shortlist_total" ] == 22


def test_decide_provides_with_the_fold_puts_each_class_in_the_causal_rows_once():
    classes, ctors = _family( 8 )
    rows = [ ( c, 0.75 ) for c in classes ] + [ ( k, 0.95 ) for k in ctors ] + [ ( o, 0.8 ) for o in OTHERS ]
    got = _pair_question( rows )
    assert got[ "verdict" ] == "REUSE"
    assert sorted( r[ "id" ] for r in got[ "shortlist" ][ :8 ] ) == classes and got[ "shortlist_total" ] == 14


def test_decide_provides_folds_an_extend_verdict_too():
    classes, ctors = _family( 2 )
    got = _pair_question( [ ( classes[ 0 ], 0.4 ), ( ctors[ 0 ], 0.6 ), ( classes[ 1 ], 0.5 ) ] )
    assert got[ "verdict" ] == "EXTEND" and [ r[ "id" ] for r in got[ "shortlist" ] ] == [ classes[ 0 ], classes[ 1 ] ]


def test_decide_provides_with_an_uncertain_verdict_folds_the_pool_and_has_no_causal_rows():
    classes, ctors = _family( 1 )
    answers = _pair_answers( [ ( classes[ 0 ], 0.6 ), ( ctors[ 0 ], 0.65 ) ] )
    got = vd.decide_provides( answers, [ a[ "id" ] for a in answers ], [], { "INDEX_STALE" } )
    assert got[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and [ r[ "id" ] for r in got[ "shortlist" ] ] == classes
