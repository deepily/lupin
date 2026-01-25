"""Expand job_id column to 64 chars for SHA256 hashes

Revision ID: a3b4c5d6e7f8
Revises: 62ec6f256d27
Create Date: 2026-01-25 18:30:00.000000

Problem: Queue jobs use 64-character SHA256 hashes as job IDs, but the
job_id column was only varchar(32). This caused PostgreSQL truncation
errors when persisting queue-originated notifications.

Solution: Expand job_id column from varchar(32) to varchar(64) to
accommodate both short format (e.g., "dr-a1b2c3d4") and SHA256 hashes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = '62ec6f256d27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Expand job_id column from varchar(32) to varchar(64)."""
    op.alter_column(
        'notifications',
        'job_id',
        existing_type=sa.String( length=32 ),
        type_=sa.String( length=64 ),
        existing_nullable=True
    )


def downgrade() -> None:
    """Shrink job_id column back to varchar(32).

    WARNING: This will truncate any job_id values longer than 32 chars.
    """
    op.alter_column(
        'notifications',
        'job_id',
        existing_type=sa.String( length=64 ),
        type_=sa.String( length=32 ),
        existing_nullable=True
    )
