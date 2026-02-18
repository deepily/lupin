"""Add progress_group_id column to notifications

Revision ID: b5c6d7e8f9a0
Revises: a3b4c5d6e7f8
Create Date: 2026-02-17 12:00:00.000000

Adds progress_group_id column (varchar 12, nullable, indexed) for tracking
in-place DOM update groups. Format: pg-[a-f0-9]{8} (e.g., pg-a1b2c3d4).
Enables progress group history accumulation and persistence across page refresh.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add progress_group_id column with index."""
    op.add_column( 'notifications', sa.Column( 'progress_group_id', sa.String( length=12 ), nullable=True ) )
    op.create_index( op.f( 'ix_notifications_progress_group_id' ), 'notifications', ['progress_group_id'], unique=False )


def downgrade() -> None:
    """Remove progress_group_id column and index."""
    op.drop_index( op.f( 'ix_notifications_progress_group_id' ), table_name='notifications' )
    op.drop_column( 'notifications', 'progress_group_id' )
