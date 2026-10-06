"""Add the approval_settings table (approval policy behind login)

Revision ID: a80513825b01
Revises: 9184990becdf
Create Date: 2026-09-29

The approval settings (manager-pull rescission, approver allowlist and
accounts, enforcement flag, ...) lived in a JSON file every writer on the host could
rewrite. They now live in this table, reached only through the server's validated setter.
No backfill here: `task_approval_settings.import_legacy_override_file` copies the old
file's values in once, at boot, so the copy can check the file's stamp.

Idempotent: `auto_migrate.run_migrations_to_head` runs on every process start, so the
table is created only when absent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'a80513825b01'
down_revision: Union[str, Sequence[str], None] = '9184990becdf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "approval_settings"


def upgrade() -> None:
    """
    Create approval_settings when it is missing.

    Ensures:
        - a no-op when the table already exists
    """
    if TABLE_NAME in inspect( op.get_bind() ).get_table_names():
        return

    op.create_table(
        TABLE_NAME,
        sa.Column( "key", sa.String( 64 ), primary_key=True ),
        sa.Column( "value", sa.JSON().with_variant( JSONB(), "postgresql" ), nullable=False ),
        sa.Column( "updated_by", sa.String( 255 ), nullable=True ),
        sa.Column( "updated_ts", sa.DateTime( timezone=True ), nullable=False,
                   server_default=sa.func.now() ),
    )


def downgrade() -> None:
    """
    Drop approval_settings when present.

    Ensures:
        - a no-op when the table is absent
    """
    if TABLE_NAME in inspect( op.get_bind() ).get_table_names():
        op.drop_table( TABLE_NAME )
