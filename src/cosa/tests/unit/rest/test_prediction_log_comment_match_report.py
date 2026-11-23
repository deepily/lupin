"""
Unit tests for the comment-match report in PredictionLogRepository.get_accuracy_summary.

The rows are planted in an in-memory SQLite copy of the PredictionLog table, opened through scratch_db.
The summary's counts come from real SQL over planted outcomes, not from a mocked scalar.
No real Postgres is touched.
"""

import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from cosa.research.preference_replay.scratch_db import scratch_session
from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository, COMMENT_MATCH_REPORT_KEY
from cosa.rest.postgres_models import PredictionLog


def _config_returning( switch_on ):
    """A ConfigurationManager stand-in whose get() answers the switch and records the key asked."""
    asked = []

    class _Config:
        def __init__( self, *args, **kwargs ): pass
        def get( self, key, default=None, return_type="string" ):
            asked.append( key )
            return switch_on
    return _Config, asked


class TestCommentMatchReport( unittest.TestCase ):
    """Planted outcomes: 5 yes/no scored rows, 2 multiple-choice scored rows, 1 unscored row."""

    def setUp( self ):
        scope        = scratch_session()
        self.session = scope.__enter__()
        self.addCleanup( scope.__exit__, None, None, None )
        now = datetime.now( timezone.utc )
        rows = [
            # yes/no: stance right, comment right
            ( "yes_no", True,  { "match": True,  "qualifier_match": True } ),
            ( "yes_no", True,  { "match": True,  "qualifier_match": True } ),
            # yes/no: stance right, comment wrong
            ( "yes_no", True,  { "match": True,  "qualifier_match": False } ),
            # yes/no: stance wrong, comment agrees (comment right does not rescue a wrong stance)
            ( "yes_no", False, { "match": False, "qualifier_match": True } ),
            # yes/no: stance wrong, comment wrong
            ( "yes_no", False, { "match": False, "qualifier_match": False } ),
            # multiple choice: scored, no qualifier_match key at all
            ( "multiple_choice", True,  { "matches": 1, "total": 1 } ),
            ( "multiple_choice", False, { "matches": 0, "total": 1 } ),
            # a yes/no row not yet scored
            ( "yes_no", None, None ),
        ]
        for response_type, match, detail in rows:
            self.session.add( PredictionLog(
                id=uuid.uuid4(), notification_id=uuid.uuid4(), response_type=response_type, category="permission",
                predicted_value={ "value": "yes" }, prediction_confidence=0.5, prediction_strategy="cbr",
                similar_case_count=1, accuracy_match=match, accuracy_detail=detail, predicted_at=now
            ) )
        self.session.commit()
        self.repo = PredictionLogRepository( self.session )

    def _summary( self, switch_on, **kwargs ):
        config, asked = _config_returning( switch_on )
        with patch( "cosa.rest.db.repositories.prediction_log_repository.ConfigurationManager", config ):
            return self.repo.get_accuracy_summary( **kwargs ), asked

    def test_the_second_layer_counts_yes_no_rows_only_with_multiple_choice_rows_present( self ):
        summary, asked = self._summary( True )
        report = summary[ "comment_match" ]
        self.assertEqual( asked, [ COMMENT_MATCH_REPORT_KEY ] )
        self.assertEqual( summary[ "total_scored" ], 7 )                 # 5 yes/no + 2 multiple choice
        self.assertEqual( report[ "yes_no_scored" ], 5 )                 # the 2 multiple-choice rows are left out
        self.assertEqual( report[ "stance_right" ], 3 )
        self.assertEqual( report[ "stance_and_comment_right" ], 2 )      # a wrong stance never counts, even with a matching comment
        self.assertEqual( report[ "stance_rate" ], 0.6 )
        self.assertEqual( report[ "stance_and_comment_rate" ], 0.4 )

    def test_the_stance_only_figure_is_kept_and_still_includes_multiple_choice_rows( self ):
        summary, _ = self._summary( True )
        self.assertEqual( summary[ "total_correct" ], 4 )                # 3 yes/no + 1 multiple choice
        self.assertEqual( summary[ "accuracy_rate" ], round( 4 / 7, 4 ) )

    def test_the_denominator_with_multiple_choice_rows_left_out_is_the_same_yes_no_count( self ):
        self.session.query( PredictionLog ).filter( PredictionLog.response_type == "multiple_choice" ).delete()
        self.session.commit()
        summary, _ = self._summary( True )
        self.assertEqual( summary[ "total_scored" ], 5 )
        self.assertEqual( summary[ "comment_match" ][ "yes_no_scored" ], 5 )
        self.assertEqual( summary[ "comment_match" ][ "stance_rate" ], 0.6 )

    def test_no_yes_no_scored_row_gives_zero_counts_and_no_rates( self ):
        self.session.query( PredictionLog ).filter( PredictionLog.response_type == "yes_no" ).delete()
        self.session.commit()
        report = self._summary( True )[ 0 ][ "comment_match" ]
        self.assertEqual( report, { "yes_no_scored": 0, "stance_right": 0, "stance_and_comment_right": 0,
                                    "stance_rate": None, "stance_and_comment_rate": None } )

    def test_switch_off_summary_has_no_comment_match_key_and_matches_todays_keys( self ):
        summary, asked = self._summary( False )
        self.assertEqual( asked, [ COMMENT_MATCH_REPORT_KEY ] )
        self.assertNotIn( "comment_match", summary )
        self.assertEqual( sorted( summary.keys() ), sorted( [
            "window_days", "total_predictions", "total_responded", "total_scored", "total_correct", "accuracy_rate", "status",
            "excluded_legacy_similarity", "excluded_legacy_confidence", "avg_confidence", "by_category", "by_response_type",
            "by_abstention_reason" ] ) )
        self.assertEqual( ( summary[ "total_scored" ], summary[ "total_correct" ], summary[ "accuracy_rate" ] ), ( 7, 4, round( 4 / 7, 4 ) ) )

    def test_switch_on_leaves_every_other_figure_identical_to_switch_off( self ):
        on  = self._summary( True )[ 0 ]
        off = self._summary( False )[ 0 ]
        on.pop( "comment_match" )
        self.assertEqual( on, off )


if __name__ == "__main__":
    unittest.main()
