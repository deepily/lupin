"""
Exposure rules on synthetic rows, and the switch rate.
"""
import datetime as dt
import unittest

from cosa.agents.prediction_engine import exposure as ex

_OPENED = dt.datetime( 2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc )


def _a( value ): return { "value": value, "source": "ui" }


class TestClassifyExposure( unittest.TestCase ):

    def test_no_answer_is_unanswered_even_with_a_reveal_and_draft( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "yes" }, None ), ex.UNANSWERED )

    def test_no_reveal_is_unaided_even_when_a_stray_draft_differs( self ):
        self.assertEqual( ex.classify_exposure( None, None,                 _a( "no" ) ), ex.UNAIDED )
        self.assertEqual( ex.classify_exposure( None, { "value": "yes" },   _a( "no" ) ), ex.UNAIDED )

    def test_an_answer_equal_to_the_draft_is_unaided( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "yes" }, _a( "yes" ) ), ex.UNAIDED )

    def test_an_answer_that_differs_from_the_draft_is_switched( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, { "value": "yes" }, _a( "no" ) ), ex.SWITCHED )

    def test_a_reveal_with_no_draft_is_exposed( self ):
        self.assertEqual( ex.classify_exposure( _OPENED, None, _a( "yes" ) ), ex.EXPOSED )

    def test_only_the_value_entry_is_compared( self ):
        draft = { "value": "yes" }
        self.assertEqual( ex.classify_exposure( _OPENED, draft, { "value": "yes", "source": "ui", "answered_by": "x" } ), ex.UNAIDED )

    def test_an_entry_without_a_value_raises( self ):
        with self.assertRaises( KeyError ):
            ex.classify_exposure( _OPENED, {}, _a( "yes" ) )


class TestSwitchRate( unittest.TestCase ):

    def test_a_switched_card_is_counted_in_the_rate( self ):
        rows = [ ( None, None, _a( "yes" ) ), ( _OPENED, { "value": "yes" }, _a( "yes" ) ),
                 ( _OPENED, { "value": "yes" }, _a( "no" ) ), ( _OPENED, None, _a( "no" ) ) ]
        classes = [ ex.classify_exposure( *r ) for r in rows ]
        self.assertEqual( classes, [ ex.UNAIDED, ex.UNAIDED, ex.SWITCHED, ex.EXPOSED ] )
        self.assertEqual( ex.switch_rate( classes ), 0.25 )

    def test_unanswered_cards_are_left_out_of_both_counts( self ):
        self.assertEqual( ex.switch_rate( [ ex.UNANSWERED, ex.SWITCHED, ex.UNAIDED ] ), 0.5 )

    def test_nothing_answered_gives_none( self ):
        self.assertIsNone( ex.switch_rate( [] ) )
        self.assertIsNone( ex.switch_rate( [ ex.UNANSWERED ] ) )

    def test_the_rate_rounds_to_four_places( self ):
        self.assertEqual( ex.switch_rate( [ ex.SWITCHED, ex.UNAIDED, ex.UNAIDED ] ), 0.3333 )


if __name__ == "__main__":
    unittest.main()
