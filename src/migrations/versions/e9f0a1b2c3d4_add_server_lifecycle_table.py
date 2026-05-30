"""add_server_lifecycle_table

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-05-29

Add server_lifecycle table — a single-row marker recording when the server was
last available (stamped by the clock-loop heartbeat + the clean-shutdown ritual).
On startup, mark_interrupted_jobs() reads last_available_at to compute the exact
downtime window [last_available_at, now] and catch up scheduled jobs whose fire
time was missed because the server was down (the missed-window fix).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the single-row server_lifecycle table."""

    op.create_table(
        'server_lifecycle',
        sa.Column( 'key', sa.String( 32 ), primary_key=True ),
        sa.Column( 'last_available_at', sa.DateTime( timezone=True ), nullable=False ),
        sa.Column( 'updated_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) )
    )


def downgrade() -> None:
    """Drop the server_lifecycle table."""

    op.drop_table( 'server_lifecycle' )
