"""Add task_items.request_deletion_id + its `CHECK` (a pledge only rides on an admit)

Revision ID: ffbf50040d99
Revises: 525a4ad4067a

An admit request must name one ticket of the requester's own to delete. The
request rides on the ticket (see 8beada291153), so the pledge rides there too.
The verdict reads the row it drops from this column rather than parsing an
audit string.
Plan: src/rnd/v0.2.1/2026.09.14-sword-of-damocles-enforcement-plan.md §3.3.

What it adds:
1. `request_deletion_id` UUID NULL — the ticket pledged on this row's admit request.
2. `CHECK request_deletion_id IS NULL OR request_move = 'admit'` — a demote
   carries no pledge.
3. `request_pledged_by` VARCHAR(64) NULL — the persona that pledged the ticket.
   It is part of this revision because the ownership check ran only at filing.
   A pledge reassigned afterwards was therefore still dropped at the verdict.
   The verdict compares this column to the owner.

No backfill: the column starts NULL on every row, so the `CHECK` holds vacuously.
Idempotent on Postgres: every step inspects the live schema first, because
`auto_migrate.run_migrations_to_head` runs `upgrade head` on every process start.
On SQLite `op.create_check_constraint` raises after the column is added, exactly
as 8beada291153 does.

The `CHECK` literal must match `postgres_models.py` verbatim.
`src/tests/unit/test_task_request_deletion_column_migration.py` asserts it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'ffbf50040d99'
down_revision: Union[str, Sequence[str], None] = '525a4ad4067a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "task_items"
COLUMN     = "request_deletion_id"
PLEDGER    = "request_pledged_by"

CHECKS = (
    ( "ck_task_items_request_deletion_only_on_admit",
      "request_deletion_id IS NULL OR request_move = 'admit'" ),
)


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def upgrade() -> None:
    """
    Add the pledge column, then its `CHECK`.

    Ensures:
        - no-op when task_items is absent (a fresh DB built from metadata)
        - each column is added only when missing; the `CHECK` only when absent, by name
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    columns = { c[ "name" ] for c in inspector.get_columns( TABLE_NAME ) }
    if COLUMN not in columns:
        op.add_column( TABLE_NAME, sa.Column( COLUMN, UUID( as_uuid=True ), nullable=True ) )
    if PLEDGER not in columns:
        op.add_column( TABLE_NAME, sa.Column( PLEDGER, sa.String( 64 ), nullable=True ) )

    existing_checks = { c[ "name" ] for c in inspect( bind ).get_check_constraints( TABLE_NAME ) }
    for name, condition in CHECKS:
        if name not in existing_checks:
            op.create_check_constraint( name, TABLE_NAME, condition )


def downgrade() -> None:
    """
    Drop the `CHECK`, then both columns.

    Ensures:
        - no-op when task_items is absent; each drop guarded
        - a pending request's pledge is discarded with the column; the request itself
          (8beada291153's columns) survives without it
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    existing_checks = { c[ "name" ] for c in inspector.get_check_constraints( TABLE_NAME ) }
    for name, _ in CHECKS:
        if name in existing_checks:
            op.drop_constraint( name, TABLE_NAME, type_="check" )

    columns = { c[ "name" ] for c in inspector.get_columns( TABLE_NAME ) }
    if PLEDGER in columns:
        op.drop_column( TABLE_NAME, PLEDGER )
    if COLUMN in columns:
        op.drop_column( TABLE_NAME, COLUMN )
