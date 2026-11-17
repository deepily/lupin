"""
Add trust_states.blr_state, so the BLR trust model keeps what it learned

Revision ID: a7c3e91b5d20
Revises: 5efa1547bd37

The "blr" trust model keeps a Bayesian logistic regression per category (weights, covariance,
feature sums, counters). It lived only in memory, so a server restart started it from zero.
Per-decision features are not stored, so the model cannot be rebuilt from stored rows.

This migration adds `blr_state JSONB NULL`, written with the counters by the orchestrator and
read back by `TrustTracker.restore_category`. It is nullable with no backfill: the "count" and
"beta" models never write it, and no existing row has BLR history to invent.

Scope is one nullable column on one table: no `CHECK`, no index, no data touched.
The migration is idempotent: the column is added only when missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91b5d20'
down_revision: Union[str, Sequence[str], None] = '5efa1547bd37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "trust_states"
COLUMN_NAME = "blr_state"


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add blr_state (nullable JSONB).

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
    Drop the blr_state column.

    Ensures:
        - no-op when trust_states is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
