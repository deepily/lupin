"""
Add trust_states.decision_history — per-day decision counts, so restored history can decay

Revision ID: 5efa1547bd37
Revises: d4bf48f78a01

`trust_states` keeps totals and one `updated_at`. `update_after_ratification` refreshes
`updated_at` on every decision, and `restore_category` stamped every restored decision with it.
For an active user the whole stored history therefore loaded as "just now": no half-life
weighting, and the rolling window pruned nothing.

This migration adds `decision_history JSONB NULL`: per-day buckets
`{"YYYY-MM-DD": [approved, rejected]}` in UTC, written by `update_after_ratification` and
pruned there to a fixed retention. It is nullable with no backfill. A row written before this
migration has no record of when its decisions happened, and any value would invent history.
Such a row restores as before until its first new ratification. That write seeds the column
with the row's old totals, stamped at its `updated_at` (the date the old restore used).
New decisions are then counted by their own day.

Scope is one nullable column on one table: no `CHECK`, no index, no data touched.
The migration is idempotent: the column is added only when missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5efa1547bd37'
down_revision: Union[str, Sequence[str], None] = 'd4bf48f78a01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "trust_states"
COLUMN_NAME = "decision_history"


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add decision_history (nullable JSONB).

    Ensures:
        - no-op when trust_states is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME in _column_names( inspector ):
        return

    op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, postgresql.JSONB(), nullable=True ) )


def downgrade() -> None:
    """
    Drop the decision_history column.

    Ensures:
        - no-op when trust_states is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
