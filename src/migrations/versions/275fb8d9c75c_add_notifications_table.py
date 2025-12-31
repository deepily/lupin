"""add_notifications_table

Revision ID: 275fb8d9c75c
Revises: 210acf4d54dd
Create Date: 2025-12-30

Add notifications table for sender-aware notification system.
Enables multi-project notification grouping with sender IDs like claude.code@lupin.deepily.ai.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '275fb8d9c75c'
down_revision: Union[str, Sequence[str], None] = '210acf4d54dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create notifications table with indexes."""

    # Create notifications table
    op.create_table(
        'notifications',
        sa.Column( 'id', postgresql.UUID( as_uuid=True ), primary_key=True, server_default=sa.text( 'gen_random_uuid()' ) ),
        sa.Column( 'sender_id', sa.String( 255 ), nullable=False ),
        sa.Column( 'recipient_id', postgresql.UUID( as_uuid=True ), nullable=False ),
        sa.Column( 'title', sa.String( 255 ), nullable=True ),
        sa.Column( 'message', sa.Text(), nullable=False ),
        sa.Column( 'type', sa.String( 50 ), nullable=False ),
        sa.Column( 'priority', sa.String( 50 ), nullable=False ),
        sa.Column( 'created_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) ),
        sa.Column( 'delivered_at', sa.DateTime( timezone=True ), nullable=True ),
        sa.Column( 'responded_at', sa.DateTime( timezone=True ), nullable=True ),
        sa.Column( 'expires_at', sa.DateTime( timezone=True ), nullable=True ),
        sa.Column( 'response_requested', sa.Boolean(), server_default='false', nullable=True ),
        sa.Column( 'response_type', sa.String( 50 ), nullable=True ),
        sa.Column( 'response_value', postgresql.JSONB(), nullable=True ),
        sa.Column( 'response_default', sa.String( 255 ), nullable=True ),
        sa.Column( 'timeout_seconds', sa.BigInteger(), nullable=True ),
        sa.Column( 'state', sa.String( 50 ), nullable=False, server_default='created' ),
        sa.ForeignKeyConstraint( ['recipient_id'], ['users.id'], ondelete='CASCADE' )
    )

    # Create indexes for efficient querying
    op.create_index( 'idx_notifications_sender_id', 'notifications', ['sender_id'] )
    op.create_index( 'idx_notifications_recipient_id', 'notifications', ['recipient_id'] )
    op.create_index( 'idx_notifications_state', 'notifications', ['state'] )
    op.create_index( 'idx_notifications_created_at', 'notifications', [sa.text( 'created_at DESC' )] )
    op.create_index( 'idx_notifications_sender_recipient', 'notifications', ['sender_id', 'recipient_id'] )
    op.create_index( 'idx_notifications_type', 'notifications', ['type'] )


def downgrade() -> None:
    """Drop notifications table and indexes."""

    # Drop indexes first
    op.drop_index( 'idx_notifications_type', 'notifications' )
    op.drop_index( 'idx_notifications_sender_recipient', 'notifications' )
    op.drop_index( 'idx_notifications_created_at', 'notifications' )
    op.drop_index( 'idx_notifications_state', 'notifications' )
    op.drop_index( 'idx_notifications_recipient_id', 'notifications' )
    op.drop_index( 'idx_notifications_sender_id', 'notifications' )

    # Drop table
    op.drop_table( 'notifications' )
