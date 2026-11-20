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

import types
import unittest
from datetime import datetime, timezone
import uuid
from unittest.mock import MagicMock, Mock

from sqlalchemy.dialects import postgresql

from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository, OutcomeAlreadyRecorded, LEDGER_COLUMNS, legacy_similarity_clause, legacy_confidence_clause
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
        prediction.responded_at = None
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
            132,   # excluded_legacy_similarity
            414,   # excluded_legacy_confidence
            10,    # total_predictions
            4,     # total_responded
            5,     # total_scored (a multi-select row is scored without an actual_value of its own)
            3,     # total_correct
            0.8,   # avg_confidence
        ]
        self.repo._get_breakdown = Mock( side_effect=[ { "by_cat": 1 }, { "by_type": 2 } ] )
        self.repo._get_abstention_counts = Mock( return_value={ "embedding_missing": 2 } )
        summary = self.repo.get_accuracy_summary()
        self.assertEqual( summary[ "window_days" ], 30 )
        self.assertEqual( summary[ "excluded_legacy_similarity" ], 132 )
        self.assertEqual( summary[ "excluded_legacy_confidence" ], 414 )
        self.assertEqual( summary[ "total_predictions" ], 10 )
        self.assertEqual( summary[ "total_responded" ], 4 )
        self.assertEqual( summary[ "total_scored" ], 5 )
        self.assertEqual( summary[ "total_correct" ], 3 )
        self.assertEqual( summary[ "accuracy_rate" ], 0.6 )      # 3 over the 5 scored rows, never over the 4 answered
        self.assertEqual( summary[ "status" ], "ok" )
        self.assertEqual( summary[ "avg_confidence" ], 0.8 )
        self.assertEqual( summary[ "by_category" ], { "by_cat": 1 } )
        self.assertEqual( summary[ "by_response_type" ], { "by_type": 2 } )
        self.assertEqual( summary[ "by_abstention_reason" ], { "embedding_missing": 2 } )

    def test_all_filters_no_responses_uses_or_defaults( self ):
        # All scalars falsy → exercise the `or 0` / `or 0.0` right arcs + responded==0 else.
        self.session.query.return_value.filter.return_value.scalar.side_effect = [
            None,  # excluded_legacy_similarity → or 0
            None,  # excluded_legacy_confidence → or 0
            None,  # total_predictions → or 0
            0,     # total_responded  → or 0
            None,  # total_scored     → or 0
            None,  # total_correct    → or 0
            None,  # avg_confidence   → or 0.0
        ]
        self.repo._get_breakdown = Mock( return_value={} )
        self.repo._get_abstention_counts = Mock( return_value={} )
        summary = self.repo.get_accuracy_summary(
            window_days=7, category="permission", response_type="yes_no",
            sender_id="sess-1"
        )
        self.assertEqual( summary[ "window_days" ], 7 )
        self.assertEqual( summary[ "excluded_legacy_similarity" ], 0 )
        self.assertEqual( summary[ "excluded_legacy_confidence" ], 0 )
        self.assertEqual( summary[ "total_predictions" ], 0 )
        self.assertEqual( summary[ "total_responded" ], 0 )
        self.assertEqual( summary[ "total_correct" ], 0 )
        self.assertEqual( summary[ "total_scored" ], 0 )
        self.assertIsNone( summary[ "accuracy_rate" ] )
        self.assertEqual( summary[ "status" ], "insufficient data" )
        self.assertEqual( summary[ "avg_confidence" ], 0.0 )


class TestAbstentionCounts( _PLRTestBase ):
    """Phase 11: the summary counts forecast rows per named abstention reason."""

    def test_counts_per_reason_most_frequent_first_with_ties_in_name_order( self ):
        self.session.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
            ( "store_error: RuntimeError", 1 ), ( "embedding_missing", 3 ), ( "no_similar_cases", 3 ), ( "store_write_failed", 2 ) ]
        counts = self.repo._get_abstention_counts( "base-filter" )
        self.assertEqual( list( counts.items() ), [
            ( "embedding_missing", 3 ), ( "no_similar_cases", 3 ), ( "store_write_failed", 2 ), ( "store_error: RuntimeError", 1 ) ] )

    def test_the_query_leaves_out_rows_with_no_reason_and_applies_the_summary_filter( self ):
        self.session.query.return_value.filter.return_value.group_by.return_value.all.return_value = []
        self.assertEqual( self.repo._get_abstention_counts( "base-filter" ), {} )
        args = self.session.query.return_value.filter.call_args.args
        self.assertEqual( args[ 0 ], "base-filter" )
        self.assertIn( "abstention_reason IS NOT NULL", str( args[ 1 ].compile( dialect=postgresql.dialect() ) ) )

    def test_the_summary_passes_its_own_filter_to_the_counter( self ):
        self.session.query.return_value.filter.return_value.scalar.return_value = 0
        self.repo._get_breakdown = Mock( return_value={} )
        self.repo._get_abstention_counts = Mock( return_value={ "store_write_failed": 1 } )
        summary = self.repo.get_accuracy_summary()
        self.repo._get_abstention_counts.assert_called_once()
        self.assertEqual( summary[ "by_abstention_reason" ], { "store_write_failed": 1 } )


class TestSummaryScopeFilters( _PLRTestBase ):
    """The shared window filter drops test_override rows and keeps null forecast sources."""

    def test_the_window_filter_excludes_test_override_rows_and_keeps_null_sources( self ):
        self.session.query.return_value.filter.return_value.scalar.return_value = 0
        self.repo._get_breakdown = Mock( return_value={} )
        self.repo.get_accuracy_summary()
        window = self.session.query.return_value.filter.call_args_list[ 0 ].args[ 0 ]
        sql    = str( window.compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } ) )
        self.assertIn( "coalesce(prediction_log.forecast_source, '') != 'test_override'", sql )

    def test_the_scored_count_filters_on_a_non_null_accuracy_match( self ):
        self.session.query.return_value.filter.return_value.scalar.return_value = 0
        self.repo._get_breakdown = Mock( return_value={} )
        self.repo.get_accuracy_summary()
        sqls = [ str( c.args[ -1 ].compile( dialect=postgresql.dialect() ) ) for c in self.session.query.return_value.filter.call_args_list if len( c.args ) > 1 ]
        self.assertTrue( any( "accuracy_match IS NOT NULL" in sql for sql in sqls ), sqls )


class TestLegacySimilarityClause( unittest.TestCase ):
    def _sql( self ):
        return str( legacy_similarity_clause().compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } ) )

    def test_reads_both_similarity_keys_as_floats_above_one( self ):
        sql = self._sql()
        self.assertIn( "accuracy_detail ->> 'similarity'", sql )
        self.assertIn( "accuracy_detail ->> 'avg_similarity'", sql )
        self.assertEqual( sql.count( "> 1.0" ), 2 )
        self.assertIn( " OR ", sql )

    def test_summary_filters_exclude_the_legacy_rows_but_keep_null_rows( self ):
        self.session = MagicMock( name="session" )
        repo = PredictionLogRepository( self.session )
        self.session.query.return_value.filter.return_value.scalar.return_value = 0
        repo._get_breakdown = Mock( return_value={} )
        repo.get_accuracy_summary()
        # 3rd query call onward uses the combined filter: NOT coalesce( clause, false ) and NOT confidence > 1
        calls = self.session.query.return_value.filter.call_args_list
        sql   = str( calls[ 2 ].args[ 0 ].compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } ) )
        self.assertIn( "NOT coalesce(", sql )
        self.assertIn( "accuracy_detail ->> 'similarity'", sql )
        self.assertIn( "prediction_confidence <= 1.0", sql )

    def test_confidence_count_skips_rows_already_counted_as_legacy_similarity( self ):
        self.session = MagicMock( name="session" )
        repo = PredictionLogRepository( self.session )
        self.session.query.return_value.filter.return_value.scalar.return_value = 0
        repo._get_breakdown = Mock( return_value={} )
        repo.get_accuracy_summary()
        args = self.session.query.return_value.filter.call_args_list[ 1 ].args
        self.assertEqual( len( args ), 3 )
        sql = [ str( a.compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } ) ) for a in args ]
        self.assertIn( "NOT coalesce(", sql[ 1 ] )
        self.assertIn( "prediction_confidence > 1.0", sql[ 2 ] )


class TestLegacyConfidenceClause( unittest.TestCase ):
    def test_is_confidence_above_one( self ):
        sql = str( legacy_confidence_clause().compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } ) )
        self.assertIn( "prediction_confidence > 1.0", sql )


class TestGetBreakdown( _PLRTestBase ):
    def test_groups_rows_with_both_responded_arcs( self ):
        rows = [
            ( "permission",   5, 4, 4, 3 ),     # scored > 0, correct truthy
            ( "confirmation", 2, 0, 0, None ),  # scored == 0, correct None → 0, accuracy None
            ( "batch",        3, 3, 2, 1 ),     # answered 3, scored 2: the rate divides by scored
        ]
        chain = self.session.query.return_value.filter.return_value.group_by.return_value
        chain.all.return_value = rows
        out = self.repo._get_breakdown( base_filter="f", group_column=PredictionLog.category )
        self.assertEqual( out[ "permission" ],
                          { "count": 5, "responded": 4, "scored": 4, "correct": 3, "accuracy": 0.75 } )
        self.assertEqual( out[ "confirmation" ],
                          { "count": 2, "responded": 0, "scored": 0, "correct": 0, "accuracy": None } )
        self.assertEqual( out[ "batch" ],
                          { "count": 3, "responded": 3, "scored": 2, "correct": 1, "accuracy": 0.5 } )


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


class TestRecordSeen( _PLRTestBase ):
    """record_seen: first rendered / first fold-open time, never overwritten, row-locked read."""

    def _row( self, rendered_at=None, fold_opened_at=None, draft_at_reveal=None ):
        row = types.SimpleNamespace( rendered_at=rendered_at, fold_opened_at=fold_opened_at, draft_at_reveal=draft_at_reveal )
        self.session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = row
        return row

    def test_missing_row_returns_none_and_flushes_nothing( self ):
        self.session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None
        self.assertIsNone( self.repo.record_seen( _NID, rendered=True ) )
        self.session.flush.assert_not_called()

    def test_reads_under_a_row_lock( self ):
        self._row()
        self.repo.record_seen( _NID, rendered=True )
        self.session.query.return_value.filter.return_value.with_for_update.assert_called_once_with()

    def test_first_rendered_call_stores_the_time_and_leaves_fold_open_null( self ):
        row = self._row()
        out = self.repo.record_seen( _NID, rendered=True )
        self.assertEqual( out, { "rendered_recorded": True, "fold_opened_recorded": False, "draft_recorded": False } )
        self.assertIsNotNone( row.rendered_at )
        self.assertIsNone( row.fold_opened_at )
        self.session.flush.assert_called_once_with()

    def test_first_fold_open_call_stores_the_time_and_leaves_rendered_alone( self ):
        row = self._row()
        out = self.repo.record_seen( _NID, fold_opened=True )
        self.assertEqual( out, { "rendered_recorded": False, "fold_opened_recorded": True, "draft_recorded": False } )
        self.assertIsNone( row.rendered_at )
        self.assertIsNotNone( row.fold_opened_at )

    def test_later_calls_keep_both_stored_times( self ):
        first = datetime( 2020, 1, 1, tzinfo=timezone.utc )
        row   = self._row( rendered_at=first, fold_opened_at=first )
        out   = self.repo.record_seen( _NID, rendered=True, fold_opened=True )
        self.assertEqual( out, { "rendered_recorded": False, "fold_opened_recorded": False, "draft_recorded": False } )
        self.assertEqual( ( row.rendered_at, row.fold_opened_at ), ( first, first ) )

    def test_a_draft_is_stored_once_and_the_first_draft_is_kept( self ):
        row   = self._row()
        first = self.repo.record_seen( _NID, fold_opened=True, draft_at_reveal={ "value": "yes" } )
        later = self.repo.record_seen( _NID, fold_opened=True, draft_at_reveal={ "value": "no" } )
        self.assertTrue( first[ "draft_recorded" ] )
        self.assertFalse( later[ "draft_recorded" ] )
        self.assertEqual( row.draft_at_reveal, { "value": "yes" } )

    def test_a_draft_on_a_call_that_does_not_open_the_fold_is_ignored( self ):
        row = self._row()
        out = self.repo.record_seen( _NID, rendered=True, draft_at_reveal={ "value": "yes" } )
        self.assertFalse( out[ "draft_recorded" ] )
        self.assertIsNone( row.draft_at_reveal )

    def test_a_draft_after_the_fold_time_was_already_stored_is_ignored( self ):
        row = self._row( fold_opened_at=datetime( 2020, 1, 1, tzinfo=timezone.utc ) )
        out = self.repo.record_seen( _NID, fold_opened=True, draft_at_reveal={ "value": "yes" } )
        self.assertEqual( out, { "rendered_recorded": False, "fold_opened_recorded": False, "draft_recorded": False } )
        self.assertIsNone( row.draft_at_reveal )

    def test_a_draft_and_the_first_fold_open_in_one_call_are_both_stored( self ):
        row = self._row()
        out = self.repo.record_seen( _NID, fold_opened=True, draft_at_reveal={ "value": "yes" } )
        self.assertTrue( out[ "fold_opened_recorded" ] and out[ "draft_recorded" ] )
        self.assertEqual( row.draft_at_reveal, { "value": "yes" } )

    def test_no_draft_leaves_the_stored_draft_untouched( self ):
        row = self._row( draft_at_reveal={ "value": "yes" } )
        out = self.repo.record_seen( _NID, fold_opened=True )
        self.assertFalse( out[ "draft_recorded" ] )
        self.assertEqual( row.draft_at_reveal, { "value": "yes" } )

    def test_a_non_uuid_id_raises_value_error( self ):
        with self.assertRaises( ValueError ):
            self.repo.record_seen( "not-a-uuid", rendered=True )


class TestLedgerWrites( _PLRTestBase ):
    """log_prediction's ledger kwargs and update_outcome's refusal of a second outcome."""

    def test_ledger_values_reach_create_beside_the_prediction_fields( self ):
        self.repo.create = Mock( return_value=object() )
        self.repo.log_prediction( notification_id=_NID, response_type="yes_no", category="c", predicted_value=None,
                                  prediction_confidence=0.0, prediction_strategy="error",
                                  ledger={ "abstention_reason": "predictor_error: X", "forecast_source": "foundation_sync" } )
        kwargs = self.repo.create.call_args.kwargs
        self.assertEqual( kwargs[ "abstention_reason" ], "predictor_error: X" )
        self.assertEqual( kwargs[ "forecast_source" ], "foundation_sync" )
        self.assertEqual( kwargs[ "prediction_strategy" ], "error" )

    def test_a_column_outside_the_ledger_is_refused_before_any_write( self ):
        self.repo.create = Mock()
        with self.assertRaises( ValueError ) as caught:
            self.repo.log_prediction( notification_id=_NID, response_type="yes_no", category="c", predicted_value=None,
                                      prediction_confidence=0.0, prediction_strategy="x", ledger={ "accuracy_match": True } )
        self.assertIn( "accuracy_match", str( caught.exception ) )
        self.repo.create.assert_not_called()

    def test_every_ledger_column_is_a_real_prediction_log_column( self ):
        names = { c.name for c in PredictionLog.__table__.columns }
        self.assertTrue( LEDGER_COLUMNS <= names )
        self.assertEqual( len( LEDGER_COLUMNS ), 19 )

    def test_a_second_outcome_is_refused_and_the_first_is_untouched( self ):
        prediction = types.SimpleNamespace( actual_value={ "value": "yes" }, accuracy_match=True, accuracy_detail=None,
                                            responded_at=datetime( 2020, 1, 1, tzinfo=timezone.utc ) )
        self.repo.get_by_notification_id = Mock( return_value=prediction )
        with self.assertRaises( OutcomeAlreadyRecorded ):
            self.repo.update_outcome( _NID, { "value": "no" }, False, None )
        self.assertEqual( prediction.actual_value, { "value": "yes" } )
        self.assertTrue( prediction.accuracy_match )
        self.session.flush.assert_not_called()


class TestRowLocks( _PLRTestBase ):
    """The outcome check and write run under a row lock, so duplicate answers cannot both pass."""

    def test_get_by_notification_id_locks_only_when_asked( self ):
        chain = self.session.query.return_value.filter.return_value
        chain.first.return_value = "row"
        self.assertEqual( self.repo.get_by_notification_id( _NID ), "row" )
        chain.with_for_update.assert_not_called()
        chain.with_for_update.return_value.first.return_value = "locked-row"
        self.assertEqual( self.repo.get_by_notification_id( _NID, for_update=True ), "locked-row" )
        chain.with_for_update.assert_called_once_with()

    def test_update_outcome_reads_under_a_row_lock( self ):
        chain = self.session.query.return_value.filter.return_value
        chain.with_for_update.return_value.first.return_value = types.SimpleNamespace(
            actual_value=None, accuracy_match=None, accuracy_detail=None, responded_at=None )
        self.repo.update_outcome( _NID, { "value": "yes" }, True, None )
        chain.with_for_update.assert_called_once_with()


class TestAlwaysYesCounts( _PLRTestBase ):
    """always_yes_counts reads each stance through the one parser and counts scored answers."""

    def _rows( self, *values ):
        chain = self.session.query.return_value.join.return_value.filter.return_value
        chain.all.return_value = [ ( v, ) for v in values ]
        return chain

    def test_counts_yes_over_every_answer_with_a_stance( self ):
        self._rows( { "value": "yes" }, { "value": "yes [comment: after review]" }, { "value": "no" },
                    { "value": "neither" }, { "value": "Maybe later" }, { "answers": { "x": "y" } }, { "value": None } )
        out = self.repo.always_yes_counts( _NID )
        self.assertEqual( out, { "yes": 2, "n": 4, "rate": 0.5 } )

    def test_the_rate_is_rounded_to_four_places( self ):
        self._rows( { "value": "yes" }, { "value": "no" }, { "value": "no" } )
        self.assertEqual( self.repo.always_yes_counts( _NID )[ "rate" ], 0.3333 )

    def test_no_answer_with_a_stance_returns_none( self ):
        self._rows( { "value": "Maybe later" } )
        self.assertIsNone( self.repo.always_yes_counts( _NID ) )

    def test_no_rows_returns_none( self ):
        self._rows()
        self.assertIsNone( self.repo.always_yes_counts( _NID ) )

    def test_the_query_is_scoped_to_the_recipients_scored_yes_no_rows_before_the_cutoff_and_not_overrides( self ):
        chain = self._rows( { "value": "yes" } )
        cutoff = datetime( 2026, 11, 18, tzinfo=timezone.utc )
        self.repo.always_yes_counts( _NID, before=cutoff )
        conditions = " | ".join( str( c.compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": False } ) )
                                 for c in self.session.query.return_value.join.return_value.filter.call_args.args )
        self.assertIn( "notifications.recipient_id =", conditions )
        self.assertIn( "prediction_log.response_type =", conditions )
        self.assertIn( "prediction_log.actual_value IS NOT NULL", conditions )
        self.assertIn( "prediction_log.accuracy_match IS NOT NULL", conditions )
        self.assertIn( "prediction_log.responded_at <", conditions )
        self.assertIn( "prediction_log.prediction_strategy !=", conditions )

    def test_the_join_goes_through_notification_id( self ):
        self._rows( { "value": "yes" } )
        self.repo.always_yes_counts( _NID )
        on_clause = str( self.session.query.return_value.join.call_args.args[ 1 ].compile( dialect=postgresql.dialect() ) )
        self.assertIn( "notifications.id = prediction_log.notification_id", on_clause )

    def test_a_non_uuid_recipient_raises_value_error( self ):
        self._rows()
        with self.assertRaises( ValueError ):
            self.repo.always_yes_counts( "not-a-uuid" )
