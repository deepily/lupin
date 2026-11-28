"""
The gold tracker: Rick's own count against the target, and class lifts (plan section 6).

Gold lines are built in the store's shape and checked by the store's own validator.
"""
import pytest

from cosa.repo.labelling import gold_progress as gp
from cosa.repo.labelling import gold_store as gs

STAMP = ( "certified_classes: [yes]   uncertified: [no, neither, support-on-no, dissent, re_frame]   "
          "basis: fewer than 20 of Rick's own labelled cards in the class, or fewer than 30 slice cards" )


def line( item, stance, source="human", reader="rick", relation="support" ):
    made = { "item_id": item, "notification_id": f"n-{item}", "field_key": "answer", "relation": relation, "card_stance": stance,
             "source": source, "reader": reader, "batch_id": "b", "ts": "2026-11-27T00:00:00+00:00" }
    gs.check_line( made )
    return made


def rick( stance, count, start=0 ): return [ line( f"{stance}-{n}", stance ) for n in range( start, start + count ) ]


def test_an_empty_store_is_zero_of_twenty_and_nothing_triggers():
    assert gp.gold_progress( [] ) == { "rick": { "no": 0, "neither": 0 }, "settled": { "no": 0, "neither": 0 }, "target": 20,
                                       "reached": [], "stamp_lifts_for": [], "pass_lines": {} }


def test_nineteen_of_ricks_own_does_not_trigger():
    report = gp.gold_progress( rick( "no", 19 ), slice_counts={ "no": 100 } )
    assert report[ "rick" ][ "no" ] == 19 and report[ "reached" ] == [] and report[ "pass_lines" ] == {}


def test_twenty_triggers_that_class_only():
    report = gp.gold_progress( rick( "no", 20 ) + rick( "neither", 19 ) )
    assert report[ "reached" ] == [ "no" ] and list( report[ "pass_lines" ] ) == [ "no" ]
    assert report[ "stamp_lifts_for" ] == []


def test_a_triggered_class_lifts_only_with_thirty_slice_cards():
    short = gp.gold_progress( rick( "neither", 20 ), slice_counts={ "neither": 29 } )
    assert short[ "stamp_lifts_for" ] == []
    assert short[ "pass_lines" ][ "neither" ][ "status" ] == "triggered, not scorable: the slice holds 29 of 30"
    full = gp.gold_progress( rick( "neither", 20 ), slice_counts={ "neither": 30 } )
    assert full[ "stamp_lifts_for" ] == [ "neither" ] and full[ "pass_lines" ][ "neither" ][ "status" ] == "triggered, scorable: the slice holds 30 of 30"


def test_with_no_slice_counts_a_triggered_class_says_so_and_stays_stamped():
    report = gp.gold_progress( rick( "no", 25 ) )
    assert report[ "pass_lines" ][ "no" ] == { "class": "no", "slice_cards": None, "floor": 30, "scorable": False,
                                              "status": "triggered, not scorable: no slice count was given" }


def test_a_settled_count_of_forty_with_ricks_nineteen_triggers_nothing():
    readers = [ line( f"no-{n}", "no", "ai_reader", name ) for n in range( 40 ) for name in ( "a", "b" ) ]
    report  = gp.gold_progress( readers + rick( "no", 19 ), slice_counts={ "no": 100 } )
    assert ( report[ "settled" ][ "no" ], report[ "rick" ][ "no" ] ) == ( 40, 19 )
    assert report[ "reached" ] == [] and report[ "stamp_lifts_for" ] == []


def test_a_card_labelled_twice_counts_once_and_yes_cards_are_not_counted():
    report = gp.gold_progress( rick( "no", 1 ) + rick( "no", 1 ) + rick( "yes", 50 ) )
    assert report[ "rick" ] == { "no": 1, "neither": 0 } and "yes" not in report[ "settled" ]


@pytest.mark.parametrize( "klass", [ "yes", "none", "support" ] )
def test_only_no_and_neither_have_a_trigger( klass ):
    with pytest.raises( ValueError, match=klass ): gp.labeller_pass_line( klass, {} )


def test_the_stamp_with_nothing_lifted_is_the_plans_line():
    assert gp.stamp_line() == STAMP


def test_a_lifted_class_moves_to_certified_and_the_rest_stay():
    assert gp.stamp_line( [ "neither" ] ).startswith( "certified_classes: [yes, neither]   uncertified: [no, support-on-no, dissent, re_frame]   basis:" )
    assert gp.stamp_line( [ "no", "neither" ] ).startswith( "certified_classes: [yes, no, neither]   uncertified: [support-on-no, dissent, re_frame]" )
    with pytest.raises( ValueError, match="dissent" ): gp.stamp_line( [ "dissent" ] )


def test_the_runners_report_stamp_is_this_line():
    from cosa.agents.answer_meaning import runner
    assert runner.STAMP[ 0 ] == STAMP
