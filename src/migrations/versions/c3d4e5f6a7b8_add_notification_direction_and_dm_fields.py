"""Add direction + DM provenance/threading columns to notifications

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-15 09:00:00.000000

First-class columns for notification-native AI<->AI messaging (cosa-voice token
reduction). Adds:
  - direction       (varchar 20, NOT NULL, server_default 'ai_to_human', indexed)
                    human_to_ai | ai_to_ai | ai_to_human — orthogonal to `type`.
  - sender_persona  (varchar 64, nullable) — DM sender persona name (e.g. "Maria").
  - sender_icon     (varchar 16, nullable) — DM sender icon (e.g. an emoji).
  - reply_to        (varchar 64, nullable) — id of the message this answers.
  - thread_id       (varchar 64, nullable, indexed) — conversation correlation.

Wire JSON keys map 1:1 to these column names (external repr == internal repr).
See: src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add direction + DM provenance/threading columns and their indexes."""
    op.add_column(
        'notifications',
        sa.Column(
            'direction',
            sa.String( length=20 ),
            nullable=False,
            server_default='ai_to_human'
        )
    )
    op.add_column( 'notifications', sa.Column( 'sender_persona', sa.String( length=64 ), nullable=True ) )
    op.add_column( 'notifications', sa.Column( 'sender_icon',    sa.String( length=16 ), nullable=True ) )
    op.add_column( 'notifications', sa.Column( 'reply_to',       sa.String( length=64 ), nullable=True ) )
    op.add_column( 'notifications', sa.Column( 'thread_id',      sa.String( length=64 ), nullable=True ) )

    op.create_index( op.f( 'ix_notifications_direction' ), 'notifications', ['direction'], unique=False )
    op.create_index( op.f( 'ix_notifications_thread_id' ), 'notifications', ['thread_id'], unique=False )


def downgrade() -> None:
    """Remove the direction + DM provenance/threading columns and indexes."""
    op.drop_index( op.f( 'ix_notifications_thread_id' ), table_name='notifications' )
    op.drop_index( op.f( 'ix_notifications_direction' ), table_name='notifications' )
    op.drop_column( 'notifications', 'thread_id' )
    op.drop_column( 'notifications', 'reply_to' )
    op.drop_column( 'notifications', 'sender_icon' )
    op.drop_column( 'notifications', 'sender_persona' )
    op.drop_column( 'notifications', 'direction' )
