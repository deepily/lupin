"""
Add prediction_log.three_way_shadow, the three-way challenger's recorded stance

Revision ID: d5e9f2b7c413
Revises: c4d8e1a6b392

The column is nullable JSONB with no backfill, so every earlier row reads NULL.
NULL means the challenger did not run for the ask.
The upgrade adds the column only when missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd5e9f2b7c413'
down_revision: Union[str, Sequence[str], None] = 'c4d8e1a6b392'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "prediction_log"
COLUMN_NAME = "three_way_shadow"


def _column_names( inspector ) -> set:
    """
    Name the columns of prediction_log.

    Requires:
        - inspector reads the database the migration runs against, and the table exists

    Ensures:
        - returns the set of column names
    """
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add three_way_shadow (nullable JSONB).

    Ensures:
        - no-op when prediction_log is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names(): return
    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, postgresql.JSONB(), nullable=True ) )


def downgrade() -> None:
    """
    Drop the three_way_shadow column.

    Ensures:
        - no-op when prediction_log is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names(): return
    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
