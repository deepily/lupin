"""add_fcm_tokens_table

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-06-12

Add fcm_tokens table — the DURABLE registry of mobile FCM device tokens for the
S6 silent-relay wake channel. One row per device token (upsert keyed on token);
the wake trigger resolves tokens by user_id when a notification is enqueued for
a user with no live mobile queue-WS. Durability is the F-S6-S2-1a requirement:
the registry must survive parent restarts (AC-S6.1 rehydration).

Merge-train note (Tiberius routing, 2026-06-12): down_revision deliberately
stacks on Krishna's task-store head f0a1b2c3d4e5 — this migration lands AFTER
his branch merges; never re-point it at e9f0a1b2c3d4 (that forks the head).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the fcm_tokens registry table."""

    op.create_table(
        'fcm_tokens',
        sa.Column( 'id', UUID( as_uuid=True ), primary_key=True ),
        sa.Column( 'token', sa.String( 512 ), nullable=False ),
        sa.Column( 'user_id', sa.String( 64 ), nullable=False ),
        sa.Column( 'user_email', sa.String( 255 ), nullable=False ),
        sa.Column( 'platform', sa.String( 32 ), nullable=False ),
        sa.Column( 'created_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) ),
        sa.Column( 'last_registered_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) )
    )
    op.create_index( 'ix_fcm_tokens_token', 'fcm_tokens', [ 'token' ], unique=True )
    op.create_index( 'ix_fcm_tokens_user_id', 'fcm_tokens', [ 'user_id' ] )


def downgrade() -> None:
    """Drop the fcm_tokens registry table."""

    op.drop_index( 'ix_fcm_tokens_user_id', table_name='fcm_tokens' )
    op.drop_index( 'ix_fcm_tokens_token', table_name='fcm_tokens' )
    op.drop_table( 'fcm_tokens' )
