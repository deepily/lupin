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
    """Add direction + DM provenance/threading columns and their indexes.

    IDEMPOTENT (hardened 2026-06-22, same bug-class as the b633d12a hotfix for
    e5f6a7b8c9d0). A create_all-bootstrapped DB stamped BELOW this revision already
    has all five columns (and their indexes), so unguarded ``add_column`` raises
    DuplicateColumn on ``upgrade head``. Add each column only when absent; the two
    per-column indexes ship WITH their column under create_all, so column-presence
    gates the index too (mirrors e5f6a7b8c9d0).
    """
    insp       = sa.inspect( op.get_bind() )
    tables     = set( insp.get_table_names() )
    notif_cols = { c[ "name" ] for c in insp.get_columns( "notifications" ) } if "notifications" in tables else set()

    if "direction" not in notif_cols:
        op.add_column(
            'notifications',
            sa.Column(
                'direction',
                sa.String( length=20 ),
                nullable=False,
                server_default='ai_to_human'
            )
        )
        op.create_index( op.f( 'ix_notifications_direction' ), 'notifications', ['direction'], unique=False )
    if "sender_persona" not in notif_cols:
        op.add_column( 'notifications', sa.Column( 'sender_persona', sa.String( length=64 ), nullable=True ) )
    if "sender_icon" not in notif_cols:
        op.add_column( 'notifications', sa.Column( 'sender_icon', sa.String( length=16 ), nullable=True ) )
    if "reply_to" not in notif_cols:
        op.add_column( 'notifications', sa.Column( 'reply_to', sa.String( length=64 ), nullable=True ) )
    if "thread_id" not in notif_cols:
        op.add_column( 'notifications', sa.Column( 'thread_id', sa.String( length=64 ), nullable=True ) )
        op.create_index( op.f( 'ix_notifications_thread_id' ), 'notifications', ['thread_id'], unique=False )


def downgrade() -> None:
    """Remove the direction + DM provenance/threading columns and indexes.

    IDEMPOTENT (symmetric with upgrade): each column is dropped only when present.
    """
    insp       = sa.inspect( op.get_bind() )
    tables     = set( insp.get_table_names() )
    notif_cols = { c[ "name" ] for c in insp.get_columns( "notifications" ) } if "notifications" in tables else set()

    if "thread_id" in notif_cols:
        op.drop_index( op.f( 'ix_notifications_thread_id' ), table_name='notifications' )
        op.drop_column( 'notifications', 'thread_id' )
    if "reply_to" in notif_cols:
        op.drop_column( 'notifications', 'reply_to' )
    if "sender_icon" in notif_cols:
        op.drop_column( 'notifications', 'sender_icon' )
    if "sender_persona" in notif_cols:
        op.drop_column( 'notifications', 'sender_persona' )
    if "direction" in notif_cols:
        op.drop_index( op.f( 'ix_notifications_direction' ), table_name='notifications' )
        op.drop_column( 'notifications', 'direction' )
