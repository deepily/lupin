"""
Cohen's kappa, the agreement report, disputes and final labels.
"""
import pytest

from cosa.repo.labelling import adjudicate as adj
from cosa.repo.labelling import agreement as ag
from cosa.repo.labelling import errors as er
from cosa.repo.labelling import packets as pk
from tests.unit.test_labelling_items_and_packets import code_of, label

YES_NO = ( "yes", "no" )


def test_kappa_on_a_two_by_two_table_worked_by_hand():
    pairs = [ ( "yes", "yes" ) ] * 20 + [ ( "yes", "no" ) ] * 5 + [ ( "no", "yes" ) ] * 10 + [ ( "no", "no" ) ] * 15
    # observed 35 / 50 = 0.7; A says yes 25 times, B 30 times; expected 0.5 * 0.6 + 0.5 * 0.4 = 0.5; kappa (0.7 - 0.5) / 0.5 = 0.4
    assert ag.cohen_kappa( pairs, YES_NO ) == pytest.approx( 0.4 )


def test_perfect_agreement_is_one_and_complete_disagreement_is_below_zero():
    assert ag.cohen_kappa( [ ( "yes", "yes" ), ( "no", "no" ) ], YES_NO ) == pytest.approx( 1.0 )
    assert ag.cohen_kappa( [ ( "yes", "no" ), ( "no", "yes" ) ], YES_NO ) == pytest.approx( -1.0 )


def test_every_label_in_one_category_leaves_kappa_undefined():
    assert code_of( ag.cohen_kappa, [ ( "yes", "yes" ), ( "yes", "yes" ) ], YES_NO ) == er.KAPPA_UNDEFINED


def test_an_empty_list_or_a_choice_outside_the_categories_is_a_bad_label():
    assert code_of( ag.cohen_kappa, [], YES_NO ) == er.BAD_LABEL
    assert code_of( ag.cohen_kappa, [ ( "yes", "maybe" ) ], YES_NO ) == er.BAD_LABEL
    assert code_of( ag.cohen_kappa, [ ( "maybe", "yes" ) ], YES_NO ) == er.BAD_LABEL


def two_reviewers():
    """Return two reviewers' labels over six items: one dispute, one split choice."""
    rick = [ label( "i1" ), label( "i2" ), label( "i3", choice="NONE" ), label( "i4", choice="OTHER", symbols=[ "a.f" ] ), label( "i5", choice="OTHER", symbols=[ "a.f", "a.g" ] ), label( "i6", choice="NONE" ) ]
    sam  = [ dict( label( "i1" ), reviewer="sam" ), dict( label( "i2", choice="NONE" ), reviewer="sam" ), dict( label( "i3", choice="NONE" ), reviewer="sam" ),
             dict( label( "i4", choice="OTHER", symbols=[ "a.f" ] ), reviewer="sam" ), dict( label( "i5", choice="OTHER", symbols=[ "a.h" ] ), reviewer="sam" ),
             dict( label( "i6", choice="NONE" ), reviewer="sam" ) ]
    return rick, sam


def test_two_reviewers_choosing_other_with_different_symbols_agree_in_kappa_are_disputed_and_show_in_the_equal_sets_count():
    rick, sam = two_reviewers()
    report = ag.agreement_report( rick, sam, pk.CHOICES )
    assert report[ "other_both" ] == 2 and report[ "other_equal_symbols" ] == 1
    assert adj.disputes( rick, sam ) == [ "i2", "i5" ]
    only_choice = ag.cohen_kappa( [ ( a[ "choice" ], b[ "choice" ] ) for a, b in zip( rick, sam ) ], pk.CHOICES )
    assert report[ "kappa" ] == pytest.approx( only_choice ) and report[ "raw_agreement" ] == pytest.approx( 4 / 6 )
    assert report[ "n" ] == 6 and report[ "per_category" ] == { "AS_PROPOSED": { "a": 2, "b": 1 }, "OTHER": { "a": 2, "b": 2 }, "NONE": { "a": 2, "b": 3 } }


def test_reviewers_who_labelled_different_items_cannot_be_compared():
    rick, sam = two_reviewers()
    assert code_of( ag.paired, rick, sam[ :-1 ] ) == er.BAD_LABEL
    assert [ a[ "item_id" ] for a, b in ag.paired( list( reversed( rick ) ), sam ) ] == [ "i1", "i2", "i3", "i4", "i5", "i6" ]


def test_a_dispute_takes_the_tiebreak_an_agreed_item_keeps_its_label_and_an_unseen_item_is_model_agreed():
    rick, sam = two_reviewers()
    tie = { "i2": { "choice": "AS_PROPOSED", "symbols": [] }, "i5": { "choice": "OTHER", "symbols": [ "a.g" ] } }
    got = adj.resolve( rick, sam, tie, unlabelled=[ "u1" ] )
    assert got[ "i1" ] == { "choice": "AS_PROPOSED", "symbols": [], "final_source": "agreed" } and got[ "i4" ] == { "choice": "OTHER", "symbols": [ "a.f" ], "final_source": "agreed" }
    assert got[ "i2" ] == { "choice": "AS_PROPOSED", "symbols": [], "final_source": "rick_tiebreak" } and got[ "i5" ][ "symbols" ] == [ "a.g" ] and got[ "i5" ][ "final_source" ] == "rick_tiebreak"
    assert got[ "u1" ] == { "choice": None, "symbols": None, "final_source": "model_agreed" } and sorted( got ) == [ "i1", "i2", "i3", "i4", "i5", "i6", "u1" ]


@pytest.mark.parametrize( "tie, unlabelled", [
    ( { "i2": { "choice": "NONE", "symbols": [] } }, () ),
    ( { "i2": { "choice": "NONE", "symbols": [] }, "i5": { "choice": "NONE", "symbols": [] }, "i1": { "choice": "NONE", "symbols": [] } }, () ),
    ( { "i2": { "choice": "MAYBE", "symbols": [] }, "i5": { "choice": "NONE", "symbols": [] } }, () ),
    ( { "i2": { "choice": "OTHER", "symbols": [] }, "i5": { "choice": "NONE", "symbols": [] } }, () ),
    ( { "i2": { "choice": "NONE", "symbols": [ "x" ] }, "i5": { "choice": "NONE", "symbols": [] } }, () ),
    ( { "i2": { "choice": "NONE", "symbols": [] }, "i5": { "choice": "NONE", "symbols": [] } }, [ "i1" ] ) ] )
def test_a_missing_stray_or_invalid_tiebreak_and_a_mislabelled_unseen_item_are_refused( tie, unlabelled ):
    rick, sam = two_reviewers()
    assert code_of( adj.resolve, rick, sam, tie, unlabelled ) == er.BAD_LABEL
