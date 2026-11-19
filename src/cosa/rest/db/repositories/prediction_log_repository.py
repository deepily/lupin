"""
PredictionLogRepository — CRUD and query operations for the prediction_log table.

Follows the BaseRepository pattern established by ProxyDecisionRepository.
Provides logging, outcome recording, and accuracy aggregation for
the Universal Prediction Engine.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
import uuid

from sqlalchemy.orm import Session
import sqlalchemy as sa
from sqlalchemy import func, and_

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.postgres_models import Notification, PredictionLog
from cosa.utils.notification_utils import extract_qualifier_comment


TEST_OVERRIDE_SOURCE = "test_override"   # forecast_source of a row a test planted; never counted
STATUS_INSUFFICIENT  = "insufficient data"


LEDGER_COLUMNS = frozenset( {
    "asked_at", "rendered_at", "fold_opened_at", "forecast_ready_at", "forecast_source", "predictor_version",
    "config_version", "encoder_version", "context_version", "owner_email", "evidence_ids", "evidence_scores",
    "abstention_reason", "latency_ms", "display_decision", "original_message", "batch_question_key", "code_identity", "always_yes_rate",
} )


class OutcomeAlreadyRecorded( ValueError ):
    """Raised when an outcome is attached to a forecast row that already holds one."""


def legacy_similarity_clause():
    """
    SQL condition that is true for a row scored before similarity became a true cosine.

    Those rows stored a similarity above 1, a bare dot product of unnormalised vectors.
    Their match flag says nothing about the 0.85 threshold.

    Requires:
        - nothing

    Ensures:
        - Returns a SQLAlchemy boolean expression over PredictionLog
        - True when accuracy_detail.similarity ( open_ended ) or accuracy_detail.avg_similarity
          ( open_ended_batch ) is a number above 1.0
        - NULL, never True, for rows with no such number
    """
    detail = PredictionLog.accuracy_detail
    return sa.or_(
        sa.cast( detail[ "similarity" ].astext,     sa.Float ) > 1.0,
        sa.cast( detail[ "avg_similarity" ].astext, sa.Float ) > 1.0,
    )


def legacy_confidence_clause():
    """
    SQL condition that is true for a row whose stored confidence is above 1.

    Those rows were scored from a dot product of unnormalised vectors, so the confidence reached 420.
    Rows written since the true-cosine fix top out at 1.0.

    Requires:
        - nothing

    Ensures:
        - Returns a SQLAlchemy boolean expression over PredictionLog
        - True when prediction_confidence is above 1.0
    """
    return PredictionLog.prediction_confidence > 1.0


class PredictionLogRepository( BaseRepository[PredictionLog] ):
    """
    Repository for prediction_log table operations.

    Requires:
        - session: Active SQLAlchemy session

    Ensures:
        - All methods operate within the provided session
        - Caller is responsible for commit/rollback
        - Thread-safe when each thread has its own session
    """

    def __init__( self, session: Session ):
        """
        Initialize with database session.

        Requires:
            - session: Active SQLAlchemy session from get_db()

        Ensures:
            - Repository is ready for CRUD operations on prediction_log
        """
        super().__init__( PredictionLog, session )

    def log_prediction( self, notification_id: str, response_type: str, category: str,
                        predicted_value: Optional[dict], prediction_confidence: float,
                        prediction_strategy: str, similar_case_count: int = 0,
                        sender_id: Optional[str] = None, ledger: Optional[Dict[str, Any]] = None ) -> PredictionLog:
        """
        Log a new prediction for a notification.

        Requires:
            - notification_id: UUID string of the notification
            - response_type: One of yes_no, multiple_choice, open_ended, open_ended_batch
            - category: Classification category (permission, confirmation, etc.)
            - prediction_strategy: Strategy used (cbr_majority_vote, cold_start, etc.)
            - ledger: optional { column: value } for the forecast-ledger columns in LEDGER_COLUMNS

        Ensures:
            - Creates a new prediction_log row
            - predicted_at is set to current UTC time
            - actual_value, accuracy_match, accuracy_detail are NULL (filled on response)
            - every ledger value lands on its own column
            - Returns the created PredictionLog instance

        Raises:
            - ValueError if ledger names a column outside LEDGER_COLUMNS
            - SQLAlchemy exceptions for constraint violations, including a second row for one notification
        """
        ledger  = ledger or {}
        unknown = set( ledger ) - LEDGER_COLUMNS
        if unknown: raise ValueError( f"not forecast-ledger columns: {sorted( unknown )}" )
        return self.create(
            notification_id       = uuid.UUID( notification_id ),
            response_type         = response_type,
            category              = category,
            predicted_value       = predicted_value,
            prediction_confidence = prediction_confidence,
            prediction_strategy   = prediction_strategy,
            similar_case_count    = similar_case_count,
            sender_id             = sender_id,
            **ledger,
        )

    def update_outcome( self, notification_id: str, actual_value: Optional[dict],
                        accuracy_match: Optional[bool], accuracy_detail: Optional[dict] ) -> Optional[PredictionLog]:
        """
        Record the actual outcome and accuracy comparison on a prediction.

        Requires:
            - notification_id: UUID string of the notification
            - actual_value: The actual response from the user (JSONB)
            - accuracy_match: Boolean result of comparison (or None)
            - accuracy_detail: Detailed comparison info (or None)

        Ensures:
            - Finds the prediction_log row by notification_id, reading it under a row lock so that two
              simultaneous duplicate answers cannot both pass the already-recorded check
            - Sets actual_value, accuracy_match, accuracy_detail, responded_at
            - Returns updated PredictionLog or None if not found

        Raises:
            - OutcomeAlreadyRecorded if the row already holds an outcome; the stored outcome is left as it was
        """
        prediction = self.get_by_notification_id( notification_id, for_update=True )
        if prediction is None:
            return None
        if prediction.responded_at is not None:
            raise OutcomeAlreadyRecorded( f"prediction_log row for {notification_id} already holds an outcome" )

        prediction.actual_value    = actual_value
        prediction.accuracy_match  = accuracy_match
        prediction.accuracy_detail = accuracy_detail
        prediction.responded_at    = datetime.now( timezone.utc )

        self.session.flush()
        return prediction

    def get_by_notification_id( self, notification_id: str, for_update: bool = False ) -> Optional[PredictionLog]:
        """
        Get prediction log entry by notification ID.

        Requires:
            - notification_id: UUID string
            - for_update: True to read the row under a row lock

        Ensures:
            - Returns the prediction log row for this notification
            - Returns None if not found
        """
        query = self.session.query( PredictionLog ).filter(
            PredictionLog.notification_id == uuid.UUID( notification_id )
        )
        if for_update: query = query.with_for_update()
        return query.first()

    def always_yes_counts( self, recipient_id: str, before: Optional[datetime] = None ) -> Optional[Dict[str, Any]]:
        """
        Count how often always answering yes would have been right for one recipient.

        Requires:
            - recipient_id: UUID string of the notification's recipient
            - before: only answers recorded before this instant count; None means now

        Ensures:
            - looks at the recipient's scored yes/no forecast rows (accuracy_match not null), joined to the notification
              through notification_id, because older rows carry no owner column
            - leaves out rows whose strategy is test_override
            - reads each stance with extract_qualifier_comment, so an answer with no recognised stance counts nowhere
            - returns { "yes": answers that were yes, "n": answers with a stance, "rate": yes / n rounded to 4 places }
            - returns None when no answer has a stance

        Raises:
            - ValueError if recipient_id is not a UUID
        """
        before = before or datetime.now( timezone.utc )
        # Accepted for now: this loads the recipient's whole scored history into Python to read each stance.
        rows   = self.session.query( PredictionLog.actual_value ).join(
            Notification, Notification.id == PredictionLog.notification_id
        ).filter(
            Notification.recipient_id == uuid.UUID( recipient_id ),
            PredictionLog.response_type == "yes_no",
            PredictionLog.actual_value.isnot( None ),
            PredictionLog.accuracy_match.isnot( None ),
            PredictionLog.responded_at < before,
            PredictionLog.prediction_strategy != "test_override",
        ).all()

        stances = [ extract_qualifier_comment( actual_value.get( "value" ) )[ 0 ] for ( actual_value, ) in rows ]
        stances = [ stance for stance in stances if stance is not None ]
        if not stances: return None
        yes = stances.count( "yes" )
        return { "yes": yes, "n": len( stances ), "rate": round( yes / len( stances ), 4 ) }

    def record_seen( self, notification_id: str, rendered: bool = False,
                     fold_opened: bool = False, draft_at_reveal: Optional[dict] = None ) -> Optional[Dict[str, Any]]:
        """
        Store a forecast hint's first render time, first fold-open time and draft at reveal.

        Requires:
            - notification_id: UUID string of the notification
            - rendered / fold_opened: which of the two events the client is reporting
            - draft_at_reveal: optional state of the answer controls when the fold opened, a JSON object
              shaped like actual_value ( { "value": ... } ), stored as JSONB for that reason; None means
              the client sent none

        Ensures:
            - Reads the row under a row lock, so two simultaneous calls cannot both be first
            - Sets rendered_at / fold_opened_at to the server's current UTC time only when the
              column is still NULL; a later call never overwrites it
            - A column whose event was not reported stays NULL
            - draft_at_reveal is stored only by the call that stores fold_opened_at, so it is the state at
              the reveal and first write wins like fold_opened_at. A draft sent with any other call, a
              render-only call or a later call after the fold time is stored, is ignored
            - A request with no draft changes nothing about the draft column and behaves as before
            - Returns { "rendered_recorded": bool, "fold_opened_recorded": bool, "draft_recorded": bool },
              each True only when this call stored the value
            - Returns None when no forecast row exists for the notification

        Raises:
            - ValueError if notification_id is not a UUID
        """
        prediction = self.session.query( PredictionLog ).filter(
            PredictionLog.notification_id == uuid.UUID( notification_id )
        ).with_for_update().first()
        if prediction is None:
            return None

        now      = datetime.now( timezone.utc )
        recorded = { "rendered_recorded": False, "fold_opened_recorded": False, "draft_recorded": False }
        if rendered and prediction.rendered_at is None:
            prediction.rendered_at      = now
            recorded[ "rendered_recorded" ] = True
        if fold_opened and prediction.fold_opened_at is None:
            prediction.fold_opened_at   = now
            recorded[ "fold_opened_recorded" ] = True
        if recorded[ "fold_opened_recorded" ] and draft_at_reveal is not None:
            prediction.draft_at_reveal  = draft_at_reveal
            recorded[ "draft_recorded" ] = True

        self.session.flush()
        return recorded

    def get_accuracy_summary( self, window_days: int = 30, category: Optional[str] = None,
                              response_type: Optional[str] = None,
                              sender_id: Optional[str] = None ) -> Dict[str, Any]:
        """
        Get accuracy statistics for the prediction engine.

        Requires:
            - window_days: Number of days to look back (default 30)
            - category: Optional filter by category
            - response_type: Optional filter by response type
            - sender_id: Optional filter by sender

        Ensures:
            - Returns dict with total_predictions, total_responded, accuracy_rate,
              and per-category/per-type breakdowns
            - Leaves out rows whose forecast_source is test_override, from every count
            - accuracy_rate is total_correct over total_scored, the rows with a non-null accuracy_match
              ( strict: every field exact ), never over answered rows
            - with no scored row, accuracy_rate is None and status is "insufficient data"
            - Leaves out rows scored with a similarity above 1 ( see legacy_similarity_clause );
              their count is returned as excluded_legacy_similarity
            - Also leaves out rows with a stored confidence above 1 ( see legacy_confidence_clause );
              their count, without the rows already counted above, is returned as
              excluded_legacy_confidence, so the two counts add up
        """
        cutoff = datetime.now( timezone.utc ) - timedelta( days=window_days )

        # Base query
        filters = [ PredictionLog.predicted_at >= cutoff,
                    func.coalesce( PredictionLog.forecast_source, "" ) != TEST_OVERRIDE_SOURCE ]
        if category:      filters.append( PredictionLog.category == category )
        if response_type: filters.append( PredictionLog.response_type == response_type )
        if sender_id:     filters.append( PredictionLog.sender_id == sender_id )

        window_filter = and_( *filters )

        excluded_legacy = self.session.query( func.count( PredictionLog.id ) ).filter(
            window_filter,
            legacy_similarity_clause()
        ).scalar() or 0

        # coalesce: a row with no similarity number is NULL here and must stay in
        not_legacy_similarity = sa.not_( func.coalesce( legacy_similarity_clause(), False ) )

        excluded_confidence = self.session.query( func.count( PredictionLog.id ) ).filter(
            window_filter,
            not_legacy_similarity,
            legacy_confidence_clause()
        ).scalar() or 0

        combined_filter = and_( window_filter, not_legacy_similarity, sa.not_( legacy_confidence_clause() ) )

        # Total predictions
        total_predictions = self.session.query( func.count( PredictionLog.id ) ).filter(
            combined_filter
        ).scalar() or 0

        # Total with outcomes
        total_responded = self.session.query( func.count( PredictionLog.id ) ).filter(
            combined_filter,
            PredictionLog.actual_value.isnot( None )
        ).scalar() or 0

        # Scored rows: the denominator of every accuracy figure
        total_scored = self.session.query( func.count( PredictionLog.id ) ).filter(
            combined_filter,
            PredictionLog.accuracy_match.isnot( None )
        ).scalar() or 0

        total_correct = self.session.query( func.count( PredictionLog.id ) ).filter(
            combined_filter,
            PredictionLog.accuracy_match == True
        ).scalar() or 0

        accuracy_rate = ( total_correct / total_scored ) if total_scored > 0 else None

        # Average confidence
        avg_confidence = self.session.query( func.avg( PredictionLog.prediction_confidence ) ).filter(
            combined_filter
        ).scalar() or 0.0

        # Per-category breakdown
        category_breakdown = self._get_breakdown( combined_filter, PredictionLog.category )

        # Per-type breakdown
        type_breakdown = self._get_breakdown( combined_filter, PredictionLog.response_type )

        return {
            "window_days"       : window_days,
            "total_predictions" : total_predictions,
            "total_responded"   : total_responded,
            "total_scored"      : total_scored,
            "total_correct"     : total_correct,
            "accuracy_rate"     : round( accuracy_rate, 4 ) if accuracy_rate is not None else None,
            "status"            : STATUS_INSUFFICIENT if total_scored == 0 else "ok",
            "excluded_legacy_similarity" : excluded_legacy,
            "excluded_legacy_confidence" : excluded_confidence,
            "avg_confidence"    : round( float( avg_confidence ), 4 ),
            "by_category"       : category_breakdown,
            "by_response_type"  : type_breakdown,
        }

    def _get_breakdown( self, base_filter, group_column ) -> Dict[str, Dict[str, Any]]:
        """
        Get accuracy breakdown by a grouping column.

        Requires:
            - base_filter: SQLAlchemy filter expression
            - group_column: Column to group by

        Ensures:
            - Returns dict of group_value → {count, responded, scored, correct, accuracy}
            - accuracy is correct over scored, or None when nothing is scored
        """
        rows = self.session.query(
            group_column,
            func.count( PredictionLog.id ).label( "count" ),
            func.count( PredictionLog.actual_value ).label( "responded" ),
            func.count( PredictionLog.accuracy_match ).label( "scored" ),
            func.sum(
                func.cast( PredictionLog.accuracy_match == True, sa.Integer )
            ).label( "correct" )
        ).filter(
            base_filter
        ).group_by(
            group_column
        ).all()

        breakdown = {}
        for row in rows:
            group_value = row[0]
            count       = row[1]
            responded   = row[2]
            scored      = row[3]
            correct     = row[4] or 0
            accuracy    = ( correct / scored ) if scored > 0 else None

            breakdown[ group_value ] = {
                "count"    : count,
                "responded": responded,
                "scored"   : scored,
                "correct"  : correct,
                "accuracy" : round( accuracy, 4 ) if accuracy is not None else None,
            }

        return breakdown

    def get_recent( self, limit: int = 50, response_type: Optional[str] = None ) -> List[PredictionLog]:
        """
        Get recent prediction log entries.

        Requires:
            - limit: Maximum entries to return
            - response_type: Optional filter

        Ensures:
            - Returns list ordered by predicted_at descending
            - Respects limit and optional type filter
        """
        query = self.session.query( PredictionLog )

        if response_type:
            query = query.filter( PredictionLog.response_type == response_type )

        return query.order_by( PredictionLog.predicted_at.desc() ).limit( limit ).all()


# Need this import for the func.cast in _get_breakdown
import sqlalchemy as sa
