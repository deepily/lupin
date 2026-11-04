"""Add the podcast_proxy_spent_cards table (one yes starts one podcast)

Revision ID: d4bf48f78a01
Revises: b80513825c02

A seat asks for a podcast and Rick answers yes on a card. The start door records the card here
before it queues the job. The card id is the primary key, so a second start of the same card finds
the row and is refused, whatever the timing.

Idempotent: `auto_migrate.run_migrations_to_head` runs on every process start, so the table is
created only when absent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'd4bf48f78a01'
down_revision: Union[str, Sequence[str], None] = 'b80513825c02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "podcast_proxy_spent_cards"


def upgrade() -> None:
    """
    Create podcast_proxy_spent_cards when it is missing.

    Ensures:
        - a no-op when the table already exists
    """
    if TABLE_NAME in inspect( op.get_bind() ).get_table_names():
        return

    op.create_table(
        TABLE_NAME,
        sa.Column( "card_id", UUID( as_uuid=True ), primary_key=True ),
        sa.Column( "spent_at", sa.DateTime( timezone=True ), nullable=False, server_default=sa.func.now() ),
        sa.Column( "started_by", sa.String( 255 ), nullable=False ),
        sa.Column( "scope_path", sa.Text(), nullable=False ),
        sa.Column( "sha256", sa.String( 64 ), nullable=False ),
        sa.Column( "job_id", sa.String( 64 ), nullable=True ),
    )


def downgrade() -> None:
    """
    Drop podcast_proxy_spent_cards when present.

    Ensures:
        - a no-op when the table is absent
    """
    if TABLE_NAME in inspect( op.get_bind() ).get_table_names():
        op.drop_table( TABLE_NAME )
