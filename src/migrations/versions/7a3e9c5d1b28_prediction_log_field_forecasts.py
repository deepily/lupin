"""
Add prediction_log.field_forecasts, the per-field forecast of a multiple-choice card

Revision ID: 7a3e9c5d1b28
Revises: f8c2d6a14e37

A multiple-choice card is forecast one field at a time.
The forecast row keeps the per-header result, so the outcome step and the replay read what the card showed.
For each header it holds the candidate with its confidence and case count, or the reason the field abstained.

The column is nullable JSONB with no backfill.
NULL means the per-field predictor did not make the forecast.
That covers every row written before this revision and every row of another response type.
The upgrade adds the column only when missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '7a3e9c5d1b28'
down_revision: Union[str, Sequence[str], None] = 'f8c2d6a14e37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "prediction_log"
COLUMN_NAME = "field_forecasts"


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add field_forecasts (nullable JSONB).

    Ensures:
        - no-op when prediction_log is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( "prediction_log", sa.Column( "field_forecasts", postgresql.JSONB(), nullable=True ) )


def downgrade() -> None:
    """
    Drop the field_forecasts column.

    Ensures:
        - no-op when prediction_log is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
