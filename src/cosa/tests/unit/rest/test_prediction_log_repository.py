"""
Unit tests for PredictionLogRepository (cosa.rest.db.repositories.prediction_log_repository).

Covers __init__, log_prediction, update_outcome (found / not-found),
get_by_notification_id, get_accuracy_summary (no-filters/responded>0 and
all-filters/responded==0 paths), _get_breakdown (responded>0 + responded==0 +
correct-None arcs), and get_recent (with / without response_type filter) — to
genuine 100% line + branch + function.

All DB access is boundary-mocked: the SQLAlchemy Session is a MagicMock; real
PredictionLog column expressions are built but never executed. ZERO real DB.
"""

import unittest
import uuid
from unittest.mock import MagicMock, Mock

from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository
from cosa.rest.postgres_models import PredictionLog


_NID = "12345678-1234-5678-1234-567812345678"


class _PLRTestBase( unittest.TestCase ):
    """Shared harness: a mock SQLAlchemy session + the repository under test."""

    def setUp( self ):
        self.session = MagicMock( name="session" )
        self.repo    = PredictionLogRepository( self.session )


class TestInit( _PLRTestBase ):
    def test_binds_model_and_session( self ):
        self.assertIs( self.repo.model, PredictionLog )
        self.assertIs( self.repo.session, self.session )


class TestLogPrediction( _PLRTestBase ):
    def test_translates_kwargs_and_delegates_to_create( self ):
        sentinel = object()
        self.repo.create = Mock( return_value=sentinel )
        result = self.repo.log_prediction(
            notification_id       = _NID,
            response_type         = "yes_no",
            category              = "permission",
            predicted_value       = { "answer": "yes" },
            prediction_confidence = 0.9,
            prediction_strategy   = "cbr_majority_vote",
        )
        self.assertIs( result, sentinel )
        self.repo.create.assert_called_once_with(
            notification_id       = uuid.UUID( _NID ),
            response_type         = "yes_no",
            category              = "permission",
            predicted_value       = { "answer": "yes" },
            prediction_confidence = 0.9,
            prediction_strategy   = "cbr_majority_vote",
            similar_case_count    = 0,
            sender_id             = None,
        )


class TestUpdateOutcome( _PLRTestBase ):
    def test_found_sets_fields_flushes_and_returns( self ):
        prediction = MagicMock( name="prediction" )
        self.repo.get_by_notification_id = Mock( return_value=prediction )
        result = self.repo.update_outcome(
            _NID, actual_value={ "answer": "no" }, accuracy_match=False,
            accuracy_detail={ "delta": 1 }
        )
        self.assertIs( result, prediction )
        self.assertEqual( prediction.actual_value, { "answer": "no" } )
        self.assertEqual( prediction.accuracy_match, False )
        self.assertEqual( prediction.accuracy_detail, { "delta": 1 } )
        self.assertIsNotNone( prediction.responded_at )
        self.session.flush.assert_called_once_with()

    def test_not_found_returns_none_without_flush( self ):
        self.repo.get_by_notification_id = Mock( return_value=None )
        self.assertIsNone(
            self.repo.update_outcome( _NID, actual_value=None,
                                      accuracy_match=None, accuracy_detail=None )
        )
        self.session.flush.assert_not_called()


class TestGetByNotificationId( _PLRTestBase ):
    def test_returns_first_filtered_row( self ):
        sentinel = object()
        self.session.query.return_value.filter.return_value.first.return_value = sentinel
        self.assertIs( self.repo.get_by_notification_id( _NID ), sentinel )
        self.session.query.assert_called_once_with( PredictionLog )


class TestGetAccuracySummary( _PLRTestBase ):
    def test_no_filters_with_responses( self ):
        self.session.query.return_value.filter.return_value.scalar.side_effect = [
            10,    # total_predictions
            4,     # total_responded
            3,     # total_correct
            0.8,   # avg_confidence
        ]
        self.repo._get_breakdown = Mock( side_effect=[ { "by_cat": 1 }, { "by_type": 2 } ] )
        summary = self.repo.get_accuracy_summary()
        self.assertEqual( summary[ "window_days" ], 30 )
        self.assertEqual( summary[ "total_predictions" ], 10 )
        self.assertEqual( summary[ "total_responded" ], 4 )
        self.assertEqual( summary[ "total_correct" ], 3 )
        self.assertEqual( summary[ "accuracy_rate" ], 0.75 )
        self.assertEqual( summary[ "avg_confidence" ], 0.8 )
        self.assertEqual( summary[ "by_category" ], { "by_cat": 1 } )
        self.assertEqual( summary[ "by_response_type" ], { "by_type": 2 } )

    def test_all_filters_no_responses_uses_or_defaults( self ):
        # All scalars falsy → exercise the `or 0` / `or 0.0` right arcs + responded==0 else.
        self.session.query.return_value.filter.return_value.scalar.side_effect = [
            None,  # total_predictions → or 0
            0,     # total_responded  → or 0
            None,  # total_correct    → or 0
            None,  # avg_confidence   → or 0.0
        ]
        self.repo._get_breakdown = Mock( return_value={} )
        summary = self.repo.get_accuracy_summary(
            window_days=7, category="permission", response_type="yes_no",
            sender_id="sess-1"
        )
        self.assertEqual( summary[ "window_days" ], 7 )
        self.assertEqual( summary[ "total_predictions" ], 0 )
        self.assertEqual( summary[ "total_responded" ], 0 )
        self.assertEqual( summary[ "total_correct" ], 0 )
        self.assertEqual( summary[ "accuracy_rate" ], 0.0 )
        self.assertEqual( summary[ "avg_confidence" ], 0.0 )


class TestGetBreakdown( _PLRTestBase ):
    def test_groups_rows_with_both_responded_arcs( self ):
        rows = [
            ( "permission",   5, 4, 3 ),     # responded > 0, correct truthy
            ( "confirmation", 2, 0, None ),  # responded == 0, correct None → 0
        ]
        chain = self.session.query.return_value.filter.return_value.group_by.return_value
        chain.all.return_value = rows
        out = self.repo._get_breakdown( base_filter="f", group_column=PredictionLog.category )
        self.assertEqual( out[ "permission" ],
                          { "count": 5, "responded": 4, "correct": 3, "accuracy": 0.75 } )
        self.assertEqual( out[ "confirmation" ],
                          { "count": 2, "responded": 0, "correct": 0, "accuracy": 0.0 } )


class TestGetRecent( _PLRTestBase ):
    def test_without_response_type_filter( self ):
        rows = [ object(), object() ]
        chain = self.session.query.return_value.order_by.return_value.limit.return_value
        chain.all.return_value = rows
        self.assertEqual( self.repo.get_recent(), rows )
        self.session.query.assert_called_once_with( PredictionLog )
        # filter must NOT be applied on the base query when no response_type
        self.session.query.return_value.filter.assert_not_called()

    def test_with_response_type_filter( self ):
        rows  = [ object() ]
        q     = self.session.query.return_value
        chain = q.filter.return_value.order_by.return_value.limit.return_value
        chain.all.return_value = rows
        self.assertEqual( self.repo.get_recent( limit=10, response_type="yes_no" ), rows )
        q.filter.assert_called_once()


def isolated_unit_test():
    """
    Run the PredictionLogRepository unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} PredictionLogRepository tests in {secs:.3f}s — {msg}" )
