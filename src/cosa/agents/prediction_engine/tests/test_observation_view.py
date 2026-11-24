"""
The observation view of one answer, read-only.
"""
import datetime as dt
import unittest

from cosa.agents.prediction_engine import exposure as ex

_CARD   = { "questions": [ { "header": "Code review", "options": [ { "label": "Yes (Recommended)" }, { "label": "No" } ] }, { "header": "Scope", "options": [ { "label": "All" } ] } ] }
_VALUE  = { "value": "{\"answers\":{\"Code review\":\"Yes (Recommended)\"}}", "source": "ui", "answered_by": { "method": "jwt", "user_id": "u1" } }
_AT     = dt.datetime( 2026, 11, 23, 12, 0, tzinfo=dt.timezone.utc )
_OPENED = dt.datetime( 2026, 11, 23, 11, 59, tzinfo=dt.timezone.utc )
_DRAFT  = { "value": "{\"answers\":{\"Code review\":\"No\"}}" }


def _view( **changes ):
    args = dict( response_type="multiple_choice", response_options=_CARD, response_value=_VALUE, responded_at=_AT, fold_opened_at=_OPENED, draft_at_reveal=_DRAFT )
    args.update( changes )
    return ex.observation_view( **args )


class TestObservationView( unittest.TestCase ):

    def test_it_carries_the_card_the_raw_answer_the_actor_and_the_times( self ):
        view = _view()
        self.assertEqual( view[ "response_type" ], "multiple_choice" )
        self.assertEqual( view[ "card" ][ "questions" ][ 0 ][ "options" ][ 1 ][ "label" ], "No" )
        self.assertEqual( view[ "raw_response" ], _VALUE[ "value" ] )
        self.assertEqual( view[ "source" ], "ui" )
        self.assertEqual( view[ "actor" ][ "user_id" ], "u1" )
        self.assertEqual( ( view[ "answered_at" ], view[ "fold_opened_at" ] ), ( _AT, _OPENED ) )
        self.assertEqual( view[ "draft_at_reveal" ][ "value" ], _DRAFT[ "value" ] )

    def test_option_ids_follow_the_displayed_order_and_depend_only_on_header_and_position( self ):
        self.assertEqual( _view()[ "option_ids" ], { "Code review": ( "Code review#0", "Code review#1" ), "Scope": ( "Scope#0", ) } )
        reworded = { "questions": [ { "header": "Code review", "options": [ { "label": "Sure" }, { "label": "Nope" } ] } ] }
        self.assertEqual( _view( response_options=reworded )[ "option_ids" ][ "Code review" ], ( "Code review#0", "Code review#1" ) )

    def test_a_card_without_options_gives_no_option_ids( self ):
        self.assertEqual( dict( ex.option_ids_of( None ) ), {} )
        self.assertEqual( dict( ex.option_ids_of( { "questions": [ { "header": "Q" } ] } ) ), { "Q": () } )
        self.assertEqual( dict( ex.option_ids_of( {} ) ), {} )

    def test_the_view_refuses_a_write_at_every_depth( self ):
        view = _view()
        with self.assertRaises( TypeError ): view[ "raw_response" ] = "x"
        with self.assertRaises( TypeError ): view[ "card" ][ "questions" ] = ()
        with self.assertRaises( TypeError ): view[ "actor" ][ "user_id" ] = "u2"
        with self.assertRaises( TypeError ): view[ "card" ][ "questions" ][ 0 ][ "options" ][ 0 ][ "label" ] = "x"
        with self.assertRaises( TypeError ): view[ "card" ][ "questions" ][ 0 ][ "options" ][ 0 ] = {}
        with self.assertRaises( TypeError ): del view[ "actor" ]

    def test_building_the_view_does_not_change_what_it_was_given( self ):
        card = { "questions": [ { "header": "H", "options": [ { "label": "L" } ] } ] }
        value = { "value": "yes", "source": "ui" }
        _view( response_options=card, response_value=value )
        self.assertEqual( card, { "questions": [ { "header": "H", "options": [ { "label": "L" } ] } ] } )
        self.assertEqual( value, { "value": "yes", "source": "ui" } )

    def test_a_missing_part_reads_none_and_nothing_is_guessed( self ):
        view = _view( response_type="yes_no", response_options=None, response_value=None, responded_at=None, fold_opened_at=None, draft_at_reveal=None )
        for key in ( "card", "raw_response", "source", "actor", "answered_at", "fold_opened_at", "draft_at_reveal" ):
            self.assertIsNone( view[ key ], key )
        self.assertEqual( dict( view[ "option_ids" ] ), {} )

    def test_the_input_route_has_a_named_place_that_reads_none_until_the_capture_slice_lands( self ):
        self.assertEqual( ex.INPUT_ROUTE_KEY, "input_route" )
        self.assertIn( ex.INPUT_ROUTE_KEY, _view() )
        self.assertIsNone( _view()[ ex.INPUT_ROUTE_KEY ] )

    def test_a_response_value_that_is_not_a_mapping_reads_as_no_answer( self ):
        self.assertIsNone( _view( response_value="yes" )[ "raw_response" ] )
