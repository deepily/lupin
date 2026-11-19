"""
Exposure rules on synthetic rows, the draft decoder, and the switch rate.
"""
import datetime as dt
import json
import unittest

from cosa.agents.prediction_engine import exposure as ex
from cosa.agents.principle_learner import extractor_rules

_OPENED = dt.datetime( 2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc )
YN      = "yes_no"
MC      = "multiple_choice"


def _a( value ): return { "value": value, "source": "ui" }


def _card( **answers ): return { "value": json.dumps( { "answers": answers }, separators=( ",", ":" ) ) }


class TestClassifyExposure( unittest.TestCase ):

    def test_no_answer_is_unanswered_even_with_a_reveal_and_draft( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "yes" }, None, response_type=YN ), ex.UNANSWERED )

    def test_no_reveal_is_unaided_even_when_a_stray_draft_differs( self ):
        self.assertEqual( ex.classify_exposure( None, None,               _a( "no" ), response_type=YN ), ex.UNAIDED )
        self.assertEqual( ex.classify_exposure( None, { "value": "yes" }, _a( "no" ), response_type=YN ), ex.UNAIDED )

    def test_an_answer_equal_to_the_draft_is_unaided( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "yes" }, _a( "yes" ), response_type=YN ), ex.UNAIDED )

    def test_an_answer_that_differs_from_the_draft_is_switched( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "yes" }, _a( "no" ), response_type=YN ), ex.SWITCHED )

    def test_a_reveal_with_no_draft_is_exposed( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, None, _a( "yes" ), response_type=YN ), ex.EXPOSED )

    def test_a_reveal_after_the_answer_is_unaided_with_or_without_a_draft( self ):
        answered = _OPENED - dt.timedelta( minutes=1 )
        self.assertEqual( ex.classify_exposure( _OPENED, None,               _a( "no" ), response_type=YN, answered_at=answered ), ex.UNAIDED )
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "yes" }, _a( "no" ), response_type=YN, answered_at=answered ), ex.UNAIDED )

    def test_a_reveal_exactly_at_the_answer_time_is_too_late_to_influence( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, None, _a( "no" ), response_type=YN, answered_at=_OPENED ), ex.UNAIDED )

    def test_a_reveal_before_the_answer_is_judged_on_the_draft( self ):
        answered = _OPENED + dt.timedelta( minutes=1 )
        self.assertEqual( ex.classify_exposure( _OPENED, None,               _a( "no" ), response_type=YN, answered_at=answered ), ex.EXPOSED )
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "yes" }, _a( "no" ), response_type=YN, answered_at=answered ), ex.SWITCHED )

    def test_a_draft_held_for_only_some_fields_is_exposed_not_unaided( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, _card( Database="PostgreSQL" ), _card( Database="PostgreSQL", Tags=[ "a" ] ), response_type=MC ), ex.EXPOSED )

    def test_a_card_draft_in_another_order_or_spacing_is_still_the_same_answer( self ):
        draft = { "value": '{ "answers": { "Tags": [ "b", "a" ] } }' }
        self.assertEqual( ex.classify_exposure( _OPENED, draft, { "answers": { "Tags": [ "a", "b" ] } }, response_type=MC ), ex.UNAIDED )

    def test_the_response_type_and_answer_time_must_be_passed_by_keyword( self ):
        with self.assertRaises( TypeError ): ex.classify_exposure( _OPENED, None, _a( "no" ), YN )
        with self.assertRaises( TypeError ): ex.classify_exposure( _OPENED, None, _a( "no" ), YN, _OPENED )
        with self.assertRaises( TypeError ): ex.classify_exposure( _OPENED, None, _a( "no" ), answered_at=_OPENED )

    def test_an_unknown_response_type_is_exposed_not_read_as_text( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "x" }, _a( "x" ), response_type="drag_and_drop" ), ex.EXPOSED )

    def test_an_unreadable_draft_is_exposed( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "not json" }, _card( Tags=[ "a" ] ), response_type=MC ), ex.EXPOSED )

    def test_an_answers_source_or_author_never_makes_a_switch( self ):
        answer = { "value": "yes", "source": "ui", "answered_by": { "user_id": "x" } }
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "yes" }, answer, response_type=YN ), ex.UNAIDED )


class TestDecodeAnswerFields( unittest.TestCase ):

    def test_yes_no_reads_the_stance_and_ignores_the_comment( self ):
        self.assertEqual( ex.decode_answer_fields( YN, _a( "No [comment: not ready]" ) ), { ex.WHOLE_ANSWER_KEY: ( "no", ) } )

    def test_yes_no_with_unreadable_text_keeps_the_text_and_with_nothing_is_empty( self ):
        self.assertEqual( ex.decode_answer_fields( YN, _a( "  Maybe later " ) ), { ex.WHOLE_ANSWER_KEY: ( "Maybe later", ) } )
        self.assertEqual( ex.decode_answer_fields( YN, _a( "" ) ), { ex.WHOLE_ANSWER_KEY: () } )
        self.assertEqual( ex.decode_answer_fields( YN, None ), { ex.WHOLE_ANSWER_KEY: () } )
        self.assertEqual( ex.decode_answer_fields( YN, { "value": None } ), { ex.WHOLE_ANSWER_KEY: () } )

    def test_open_ended_reads_the_stripped_text( self ):
        self.assertEqual( ex.decode_answer_fields( "open_ended", _a( "  write it down " ) ), { ex.WHOLE_ANSWER_KEY: ( "write it down", ) } )
        self.assertEqual( ex.decode_answer_fields( "open_ended", _a( " " ) ), { ex.WHOLE_ANSWER_KEY: () } )

    def test_a_card_reads_every_stored_form_the_same_way( self ):
        wire     = '{"answers":{"Database":"PostgreSQL","Tags":["b","a"]}}'
        expected = { "Database": ( "PostgreSQL", ), "Tags": ( "a", "b" ) }
        for stored in ( wire, { "value": wire }, { "value": wire, "source": "ui", "answered_by": { "user_id": "x" } },
                        { "answers": { "Database": "PostgreSQL", "Tags": [ "b", "a" ] } } ):
            self.assertEqual( ex.decode_answer_fields( MC, stored ), expected, stored )

    def test_a_card_drops_blank_picks_and_keeps_an_empty_field_as_empty( self ):
        self.assertEqual( ex.decode_answer_fields( MC, { "answers": { "A": [ " ", "x" ], "B": [], "C": "" } } ), { "A": ( "x", ), "B": (), "C": () } )

    def test_a_cancelled_card_has_no_fields_and_a_missing_card_answer_is_empty( self ):
        self.assertEqual( ex.decode_answer_fields( MC, { "value": '{"cancelled":true,"answers":{}}' } ), {} )
        self.assertEqual( ex.decode_answer_fields( MC, None ), {} )

    def test_an_unreadable_card_answer_is_none( self ):
        self.assertIsNone( ex.decode_answer_fields( MC, { "value": "not json" } ) )
        self.assertIsNone( ex.decode_answer_fields( "open_ended_batch", { "value": '{"no":"answers"}' } ) )

    def test_an_unknown_response_type_is_unreadable_for_a_draft_and_an_answer_alike( self ):
        for kind in ( "drag_and_drop", "", None ):
            self.assertIsNone( ex.decode_answer_fields( kind, _a( "yes" ) ), kind )
            self.assertIsNone( ex.decode_answer_fields( kind, None ), kind )
            self.assertEqual( ex.compare_draft_to_answer( kind, _a( "yes" ), _a( "yes" ) ), { "outcome": ex.UNREADABLE, "fields": {} }, kind )

    def test_the_whole_answer_key_is_the_one_the_extractor_uses( self ):
        self.assertEqual( ex.WHOLE_ANSWER_KEY, extractor_rules.WHOLE_ANSWER_KEY )


class TestCompareDraftToAnswer( unittest.TestCase ):

    def test_a_yes_no_draft_equal_to_the_answer_is_same( self ):
        self.assertEqual( ex.compare_draft_to_answer( YN, _a( "yes" ), _a( "yes [comment: ok]" ) ), { "outcome": ex.SAME, "fields": { ex.WHOLE_ANSWER_KEY: ex.SAME } } )

    def test_a_yes_no_answer_that_changed_is_switched( self ):
        self.assertEqual( ex.compare_draft_to_answer( YN, _a( "yes" ), _a( "no" ) ), { "outcome": ex.SWITCHED, "fields": { ex.WHOLE_ANSWER_KEY: ex.SWITCHED } } )

    def test_a_yes_no_draft_with_nothing_chosen_is_undrafted( self ):
        self.assertEqual( ex.compare_draft_to_answer( YN, _a( "" ), _a( "no" ) ), { "outcome": ex.UNDRAFTED, "fields": { ex.WHOLE_ANSWER_KEY: ex.UNDRAFTED } } )
        self.assertEqual( ex.compare_draft_to_answer( YN, None, _a( "no" ) )[ "outcome" ], ex.UNDRAFTED )

    def test_a_card_is_judged_field_by_field( self ):
        draft  = _card( Database="PostgreSQL", Tags=[ "a" ] )
        answer = { "answers": { "Database": "SQLite", "Tags": [ "a" ], "Notes": "later" } }
        self.assertEqual( ex.compare_draft_to_answer( MC, draft, answer ),
                          { "outcome": ex.SWITCHED, "fields": { "Database": ex.SWITCHED, "Tags": ex.SAME, "Notes": ex.UNDRAFTED } } )

    def test_a_card_with_every_field_unchanged_is_same_and_one_with_an_added_field_is_undrafted( self ):
        draft = _card( Database="PostgreSQL" )
        self.assertEqual( ex.compare_draft_to_answer( MC, draft, { "answers": { "Database": "PostgreSQL" } } )[ "outcome" ], ex.SAME )
        self.assertEqual( ex.compare_draft_to_answer( MC, draft, { "answers": { "Database": "PostgreSQL", "Tags": [ "a" ] } } )[ "outcome" ], ex.UNDRAFTED )

    def test_a_field_the_draft_held_and_the_answer_cleared_is_switched( self ):
        result = ex.compare_draft_to_answer( MC, _card( Tags=[ "a" ] ), { "value": '{"cancelled":true,"answers":{}}' } )
        self.assertEqual( result, { "outcome": ex.SWITCHED, "fields": { "Tags": ex.SWITCHED } } )

    def test_a_field_neither_side_holds_is_left_out_and_two_empty_sides_are_undrafted( self ):
        self.assertEqual( ex.compare_draft_to_answer( MC, _card( Tags=[] ), { "answers": { "Tags": [] } } ), { "outcome": ex.UNDRAFTED, "fields": {} } )

    def test_an_unreadable_side_is_unreadable( self ):
        self.assertEqual( ex.compare_draft_to_answer( MC, { "value": "not json" }, _card( Tags=[ "a" ] ) ), { "outcome": ex.UNREADABLE, "fields": {} } )
        self.assertEqual( ex.compare_draft_to_answer( MC, _card( Tags=[ "a" ] ), { "value": "not json" } )[ "outcome" ], ex.UNREADABLE )


class TestSwitchRate( unittest.TestCase ):

    def test_only_measured_cards_enter_the_rate( self ):
        cards = [ ( ex.SWITCHED, True ), ( ex.UNAIDED, True ), ( ex.UNAIDED, False ), ( ex.EXPOSED, True ), ( ex.UNANSWERED, False ) ]
        self.assertEqual( ex.switch_rate( cards ), 0.5 )

    def test_nothing_measured_gives_none( self ):
        self.assertIsNone( ex.switch_rate( [] ) )
        self.assertIsNone( ex.switch_rate( [ ( ex.EXPOSED, True ), ( ex.UNAIDED, False ), ( ex.UNANSWERED, False ) ] ) )

    def test_the_rate_rounds_to_four_places( self ):
        self.assertEqual( ex.switch_rate( [ ( ex.SWITCHED, True ), ( ex.UNAIDED, True ), ( ex.UNAIDED, True ) ] ), 0.3333 )

    def test_classes_from_real_rows_feed_the_rate( self ):
        rows = [ ( None, None, _a( "yes" ), YN ), ( _OPENED, { "value": "yes" }, _a( "yes" ), YN ),
                 ( _OPENED, { "value": "yes" }, _a( "no" ), YN ), ( _OPENED, None, _a( "no" ), YN ) ]
        classes = [ ex.classify_exposure( *r[ :3 ], response_type=r[ 3 ] ) for r in rows ]
        self.assertEqual( classes, [ ex.UNAIDED, ex.UNAIDED, ex.SWITCHED, ex.EXPOSED ] )
        cards = [ ( cls, ex.revealed_before_answer( row[ 0 ], None ) ) for cls, row in zip( classes, rows ) ]
        self.assertEqual( ex.switch_rate( cards ), 0.5 )


class TestRevealedBeforeAnswer( unittest.TestCase ):

    def test_no_reveal_is_never_before_the_answer( self ):
        self.assertFalse( ex.revealed_before_answer( None, _OPENED ) )

    def test_only_a_strictly_earlier_reveal_counts( self ):
        later = _OPENED + dt.timedelta( seconds=1 )
        self.assertTrue( ex.revealed_before_answer( _OPENED, later ) )
        self.assertFalse( ex.revealed_before_answer( _OPENED, _OPENED ) )
        self.assertFalse( ex.revealed_before_answer( later, _OPENED ) )

    def test_a_reveal_with_an_unknown_answer_time_counts( self ):
        self.assertTrue( ex.revealed_before_answer( _OPENED, None ) )


if __name__ == "__main__":
    unittest.main()
