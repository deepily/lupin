"""add_prediction_log_table

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-02-27

Add prediction_log table for the Universal Prediction Engine.
Tracks prediction attempts (predicted_value, confidence, strategy)
alongside actual human responses (actual_value, accuracy_match) for
progressive learning across all notification response types.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create prediction_log table with indexes."""

    op.create_table(
        'prediction_log',
        sa.Column( 'id', postgresql.UUID( as_uuid=True ), primary_key=True, server_default=sa.text( 'gen_random_uuid()' ) ),
        sa.Column( 'notification_id', postgresql.UUID( as_uuid=True ), nullable=False ),
        sa.Column( 'response_type', sa.String( 50 ), nullable=False ),
        sa.Column( 'category', sa.String( 100 ), nullable=False ),
        sa.Column( 'predicted_value', postgresql.JSONB(), nullable=True ),
        sa.Column( 'prediction_confidence', sa.Float(), nullable=False, server_default=sa.text( '0.0' ) ),
        sa.Column( 'prediction_strategy', sa.String( 50 ), nullable=False ),
        sa.Column( 'similar_case_count', sa.Integer(), nullable=False, server_default=sa.text( '0' ) ),
        sa.Column( 'actual_value', postgresql.JSONB(), nullable=True ),
        sa.Column( 'accuracy_match', sa.Boolean(), nullable=True ),
        sa.Column( 'accuracy_detail', postgresql.JSONB(), nullable=True ),
        sa.Column( 'predicted_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) ),
        sa.Column( 'responded_at', sa.DateTime( timezone=True ), nullable=True ),
        sa.Column( 'sender_id', sa.String( 255 ), nullable=True ),
        sa.ForeignKeyConstraint( ['notification_id'], ['notifications.id'], ondelete='CASCADE' )
    )

    # Individual column indexes
    op.create_index( 'idx_prediction_log_notification_id', 'prediction_log', ['notification_id'] )
    op.create_index( 'idx_prediction_log_response_type', 'prediction_log', ['response_type'] )
    op.create_index( 'idx_prediction_log_category', 'prediction_log', ['category'] )
    op.create_index( 'idx_prediction_log_accuracy_match', 'prediction_log', ['accuracy_match'] )
    op.create_index( 'idx_prediction_log_sender_id', 'prediction_log', ['sender_id'] )

    # Composite indexes
    op.create_index( 'idx_prediction_log_response_type_category', 'prediction_log', ['response_type', 'category'] )
    op.create_index( 'idx_prediction_log_predicted_at', 'prediction_log', ['predicted_at'] )


def downgrade() -> None:
    """Drop prediction_log table and all indexes."""

    op.drop_index( 'idx_prediction_log_predicted_at', table_name='prediction_log' )
    op.drop_index( 'idx_prediction_log_response_type_category', table_name='prediction_log' )
    op.drop_index( 'idx_prediction_log_sender_id', table_name='prediction_log' )
    op.drop_index( 'idx_prediction_log_accuracy_match', table_name='prediction_log' )
    op.drop_index( 'idx_prediction_log_category', table_name='prediction_log' )
    op.drop_index( 'idx_prediction_log_response_type', table_name='prediction_log' )
    op.drop_index( 'idx_prediction_log_notification_id', table_name='prediction_log' )

    op.drop_table( 'prediction_log' )
