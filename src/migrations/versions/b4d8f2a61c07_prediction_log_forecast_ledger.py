"""
Add the forecast ledger columns to prediction_log; make notification_id unique

Revision ID: b4d8f2a61c07
Revises: f1c9a4d27b36

The forecast is stored when the question is asked, one row per notification. This migration adds
the nullable ledger columns. They record the ask, render and fold-open times, the forecast source
and ready time, and the versions. They also record the owner, evidence, abstention reason, latency,
display decision, original message, batch question key and code identity. The revision adds the unique
constraint `uq_prediction_log_notification_id`.

Before adding the constraint it counts duplicate notification_id values. If any exist it raises and
lists them; it never deletes a row. Removing duplicates is a separate step Rick rules on.
Every column is added only when missing, and the constraint only when absent, so a re-run is safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4d8f2a61c07'
down_revision: Union[str, Sequence[str], None] = 'f1c9a4d27b36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME      = "prediction_log"
CONSTRAINT_NAME = "uq_prediction_log_notification_id"

_TS = sa.DateTime( timezone=True )

COLUMNS = (
    ( "asked_at",           _TS ),
    ( "rendered_at",        _TS ),
    ( "fold_opened_at",     _TS ),
    ( "forecast_ready_at",  _TS ),
    ( "forecast_source",    sa.String( 50 ) ),
    ( "predictor_version",  sa.String( 100 ) ),
    ( "config_version",     sa.String( 100 ) ),
    ( "encoder_version",    sa.String( 100 ) ),
    ( "context_version",    sa.String( 100 ) ),
    ( "owner_email",        sa.String( 255 ) ),
    ( "evidence_ids",       postgresql.JSONB() ),
    ( "evidence_scores",    postgresql.JSONB() ),
    ( "abstention_reason",  sa.Text() ),
    ( "latency_ms",         sa.Float() ),
    ( "display_decision",   sa.String( 50 ) ),
    ( "original_message",   sa.Text() ),
    ( "batch_question_key", sa.String( 255 ) ),
    ( "code_identity",      postgresql.JSONB() ),
)


class DuplicateNotificationIdsError( RuntimeError ):
    """Raised when prediction_log holds more than one row for a notification_id."""


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def _has_unique_on_notification_id( inspector ) -> bool:
    """True when a unique constraint or unique index covers exactly notification_id."""
    for constraint in inspector.get_unique_constraints( TABLE_NAME ):
        if constraint[ "column_names" ] == [ "notification_id" ]: return True
    for index in inspector.get_indexes( TABLE_NAME ):
        if index.get( "unique" ) and index[ "column_names" ] == [ "notification_id" ]: return True
    return False


def _duplicate_notification_ids( bind ) -> list:
    """Return ( notification_id, row_count ) for every notification_id with more than one row."""
    rows = bind.execute( sa.text(
        f"SELECT notification_id, COUNT(*) AS n FROM {TABLE_NAME} "
        "GROUP BY notification_id HAVING COUNT(*) > 1 ORDER BY notification_id"
    ) ).fetchall()
    return [ ( str( row[ 0 ] ), row[ 1 ] ) for row in rows ]


def upgrade() -> None:
    """
    Add the ledger columns and the unique constraint.

    Ensures:
        - no-op when prediction_log is absent (fresh DB built from metadata)
        - each column is added only when missing
        - raises DuplicateNotificationIdsError, listing each id and its count, and changes nothing
          (no column, no constraint, no deletion) when duplicate notification_id values exist
        - the constraint is added only when no unique key on notification_id exists
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if not _has_unique_on_notification_id( inspector ):
        duplicates = _duplicate_notification_ids( bind )
        if duplicates:
            listing = ", ".join( f"{nid} x{count}" for nid, count in duplicates )
            raise DuplicateNotificationIdsError(
                f"{TABLE_NAME} has {len( duplicates )} duplicate notification_id value(s): {listing}. "
                "Nothing was changed. Removing duplicates is a separate step for Rick to rule on."
            )

    # One literal op per column: test_model_migration_drift reads this file statically.
    existing = _column_names( inspector )
    if "asked_at" not in existing:
        op.add_column( "prediction_log", sa.Column( "asked_at", _TS, nullable=True ) )
    if "rendered_at" not in existing:
        op.add_column( "prediction_log", sa.Column( "rendered_at", _TS, nullable=True ) )
    if "fold_opened_at" not in existing:
        op.add_column( "prediction_log", sa.Column( "fold_opened_at", _TS, nullable=True ) )
    if "forecast_ready_at" not in existing:
        op.add_column( "prediction_log", sa.Column( "forecast_ready_at", _TS, nullable=True ) )
    if "forecast_source" not in existing:
        op.add_column( "prediction_log", sa.Column( "forecast_source", sa.String( 50 ), nullable=True ) )
    if "predictor_version" not in existing:
        op.add_column( "prediction_log", sa.Column( "predictor_version", sa.String( 100 ), nullable=True ) )
    if "config_version" not in existing:
        op.add_column( "prediction_log", sa.Column( "config_version", sa.String( 100 ), nullable=True ) )
    if "encoder_version" not in existing:
        op.add_column( "prediction_log", sa.Column( "encoder_version", sa.String( 100 ), nullable=True ) )
    if "context_version" not in existing:
        op.add_column( "prediction_log", sa.Column( "context_version", sa.String( 100 ), nullable=True ) )
    if "owner_email" not in existing:
        op.add_column( "prediction_log", sa.Column( "owner_email", sa.String( 255 ), nullable=True ) )
    if "evidence_ids" not in existing:
        op.add_column( "prediction_log", sa.Column( "evidence_ids", postgresql.JSONB(), nullable=True ) )
    if "evidence_scores" not in existing:
        op.add_column( "prediction_log", sa.Column( "evidence_scores", postgresql.JSONB(), nullable=True ) )
    if "abstention_reason" not in existing:
        op.add_column( "prediction_log", sa.Column( "abstention_reason", sa.Text(), nullable=True ) )
    if "latency_ms" not in existing:
        op.add_column( "prediction_log", sa.Column( "latency_ms", sa.Float(), nullable=True ) )
    if "display_decision" not in existing:
        op.add_column( "prediction_log", sa.Column( "display_decision", sa.String( 50 ), nullable=True ) )
    if "original_message" not in existing:
        op.add_column( "prediction_log", sa.Column( "original_message", sa.Text(), nullable=True ) )
    if "batch_question_key" not in existing:
        op.add_column( "prediction_log", sa.Column( "batch_question_key", sa.String( 255 ), nullable=True ) )
    if "code_identity" not in existing:
        op.add_column( "prediction_log", sa.Column( "code_identity", postgresql.JSONB(), nullable=True ) )

    if not _has_unique_on_notification_id( inspect( bind ) ):
        op.create_unique_constraint( CONSTRAINT_NAME, TABLE_NAME, [ "notification_id" ] )


def downgrade() -> None:
    """
    Drop the unique constraint and the ledger columns.

    Ensures:
        - no-op when prediction_log is absent
        - each drop is guarded, so a partial upgrade downgrades cleanly
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if any( c[ "name" ] == CONSTRAINT_NAME for c in inspector.get_unique_constraints( TABLE_NAME ) ):
        op.drop_constraint( CONSTRAINT_NAME, TABLE_NAME, type_="unique" )

    existing = _column_names( inspect( bind ) )
    for name, _ in COLUMNS:
        if name in existing:
            op.drop_column( TABLE_NAME, name )
