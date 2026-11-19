"""
Add prediction_log.draft_at_reveal, the draft answer when the forecast fold opened

Revision ID: e5b7d9a2c418
Revises: d3a6c1e8b5f2

The seen route stores the first fold-open time. This column keeps the draft answer at that moment, so the
learner can tell an unaided answer from one the forecast may have changed.

The column is nullable JSONB, shaped like actual_value, with no backfill. A row whose fold was never opened,
or whose client did not send a draft, holds NULL, which means unknown. The upgrade adds the column only when
missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e5b7d9a2c418'
down_revision: Union[str, Sequence[str], None] = 'd3a6c1e8b5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "prediction_log"
COLUMN_NAME = "draft_at_reveal"


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add draft_at_reveal (nullable JSONB).

    Ensures:
        - no-op when prediction_log is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, postgresql.JSONB(), nullable=True ) )


def downgrade() -> None:
    """
    Drop the draft_at_reveal column.

    Ensures:
        - no-op when prediction_log is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
