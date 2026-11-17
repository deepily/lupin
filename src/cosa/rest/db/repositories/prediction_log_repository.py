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
from cosa.rest.postgres_models import PredictionLog


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
                        sender_id: Optional[str] = None ) -> PredictionLog:
        """
        Log a new prediction for a notification.

        Requires:
            - notification_id: UUID string of the notification
            - response_type: One of yes_no, multiple_choice, open_ended, open_ended_batch
            - category: Classification category (permission, confirmation, etc.)
            - prediction_strategy: Strategy used (cbr_majority_vote, cold_start, etc.)

        Ensures:
            - Creates a new prediction_log row
            - predicted_at is set to current UTC time
            - actual_value, accuracy_match, accuracy_detail are NULL (filled on response)
            - Returns the created PredictionLog instance

        Raises:
            - SQLAlchemy exceptions for constraint violations
        """
        return self.create(
            notification_id       = uuid.UUID( notification_id ),
            response_type         = response_type,
            category              = category,
            predicted_value       = predicted_value,
            prediction_confidence = prediction_confidence,
            prediction_strategy   = prediction_strategy,
            similar_case_count    = similar_case_count,
            sender_id             = sender_id,
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
            - Finds the prediction_log row by notification_id
            - Sets actual_value, accuracy_match, accuracy_detail, responded_at
            - Returns updated PredictionLog or None if not found

        Raises:
            - None (returns None if not found)
        """
        prediction = self.get_by_notification_id( notification_id )
        if prediction is None:
            return None

        prediction.actual_value    = actual_value
        prediction.accuracy_match  = accuracy_match
        prediction.accuracy_detail = accuracy_detail
        prediction.responded_at    = datetime.now( timezone.utc )

        self.session.flush()
        return prediction

    def get_by_notification_id( self, notification_id: str ) -> Optional[PredictionLog]:
        """
        Get prediction log entry by notification ID.

        Requires:
            - notification_id: UUID string

        Ensures:
            - Returns the prediction log row for this notification
            - Returns None if not found
        """
        return self.session.query( PredictionLog ).filter(
            PredictionLog.notification_id == uuid.UUID( notification_id )
        ).first()

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
            - Only includes predictions with actual outcomes for accuracy calc
            - Leaves out rows scored with a similarity above 1 ( see legacy_similarity_clause );
              their count is returned as excluded_legacy_similarity
            - Also leaves out rows with a stored confidence above 1 ( see legacy_confidence_clause );
              their count, without the rows already counted above, is returned as
              excluded_legacy_confidence, so the two counts add up
        """
        cutoff = datetime.now( timezone.utc ) - timedelta( days=window_days )

        # Base query
        filters = [ PredictionLog.predicted_at >= cutoff ]
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

        # Accuracy (only for responded predictions)
        total_correct = self.session.query( func.count( PredictionLog.id ) ).filter(
            combined_filter,
            PredictionLog.accuracy_match == True
        ).scalar() or 0

        accuracy_rate = ( total_correct / total_responded ) if total_responded > 0 else 0.0

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
            "total_correct"     : total_correct,
            "accuracy_rate"     : round( accuracy_rate, 4 ),
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
            - Returns dict of group_value → {count, responded, correct, accuracy}
        """
        rows = self.session.query(
            group_column,
            func.count( PredictionLog.id ).label( "count" ),
            func.count( PredictionLog.actual_value ).label( "responded" ),
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
            correct     = row[3] or 0
            accuracy    = ( correct / responded ) if responded > 0 else 0.0

            breakdown[ group_value ] = {
                "count"    : count,
                "responded": responded,
                "correct"  : correct,
                "accuracy" : round( accuracy, 4 ),
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
