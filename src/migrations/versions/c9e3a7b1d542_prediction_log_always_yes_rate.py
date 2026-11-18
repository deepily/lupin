"""
Add prediction_log.always_yes_rate, the always-yes label stored with the forecast

Revision ID: c9e3a7b1d542
Revises: b4d8f2a61c07

The forecast card shows how often "always yes" would have been right for this recipient. The figure is
computed at ask time, so the forecast row keeps the exact rate and denominator the card showed.

The column is nullable JSONB with no backfill. Old rows were forecast before the label existed. A row for a
notification that is not a yes/no ask has no rate. The upgrade adds the column only when missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9e3a7b1d542'
down_revision: Union[str, Sequence[str], None] = 'b4d8f2a61c07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "prediction_log"
COLUMN_NAME = "always_yes_rate"


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add always_yes_rate (nullable JSONB).

    Ensures:
        - no-op when prediction_log is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( "prediction_log", sa.Column( "always_yes_rate", postgresql.JSONB(), nullable=True ) )


def downgrade() -> None:
    """
    Drop the always_yes_rate column.

    Ensures:
        - no-op when prediction_log is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
