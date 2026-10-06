"""add_fcm_tokens_table

Revision ID: a1b2c3d4e5f6
Revises: f0a1b2c3d4e5
Create Date: 2026-06-12

Add the fcm_tokens table, the durable registry of mobile FCM device tokens for
the silent-relay wake channel. There is one row per device token, upserted on
token. The wake trigger resolves tokens by user_id when a notification is
enqueued for a user with no live mobile queue-WS. The registry must survive
parent restarts, so that rehydration works.

Merge-train note: down_revision stacks on the task-store head f0a1b2c3d4e5.
This migration lands after that branch merges. Never re-point it at
e9f0a1b2c3d4, because that forks the head.
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
    """Create the fcm_tokens registry table.

    Idempotent. A create_all-bootstrapped DB stamped below this revision already
    holds fcm_tokens, so an unguarded ``create_table`` raises ``DuplicateTable``
    on ``upgrade head``. Create the table only when it is absent. That is a safe
    no-op on a create_all DB, and a full build on a truly-empty DB.
    """
    existing_tables = set( sa.inspect( op.get_bind() ).get_table_names() )

    if "fcm_tokens" not in existing_tables:
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
    """Drop the fcm_tokens registry table (idempotent — only when present)."""

    existing_tables = set( sa.inspect( op.get_bind() ).get_table_names() )

    if "fcm_tokens" in existing_tables:
        op.drop_index( 'ix_fcm_tokens_user_id', table_name='fcm_tokens' )
        op.drop_index( 'ix_fcm_tokens_token', table_name='fcm_tokens' )
        op.drop_table( 'fcm_tokens' )
