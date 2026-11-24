"""
Add the nullable applicability column to prediction_arm_forecast

Revision ID: b3f7d1a94e62
Revises: a9d4e7b2c615

applicability lists { principle_id, rule } for each principle the applicability checks dropped for the card.
It is written only when the switch "principle learner applicability checks enabled" is on.
NULL means the checks did not run, and a row written before this revision has NULL.
The upgrade adds the column only when its table exists and the column is missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b3f7d1a94e62'
down_revision: Union[str, Sequence[str], None] = 'a9d4e7b2c615'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ARM_TABLE = "prediction_arm_forecast"


def _column_names( inspector, table ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( table ) }


def upgrade() -> None:
    """
    Add the applicability column.

    Ensures:
        - nothing is done when the table is absent (a database built from the models has the column already)
        - the column is added only when missing (re-run safe)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    if ARM_TABLE not in inspector.get_table_names(): return
    if "applicability" not in _column_names( inspector, ARM_TABLE ):
        op.add_column( ARM_TABLE, sa.Column( "applicability", postgresql.JSONB( astext_type=sa.Text() ), nullable=True ) )


def downgrade() -> None:
    """
    Drop the applicability column.

    Ensures:
        - nothing is done when the table is absent or the column is missing
    """
    inspector = inspect( op.get_bind() )
    if ARM_TABLE not in inspector.get_table_names(): return
    if "applicability" in _column_names( inspector, ARM_TABLE ): op.drop_column( ARM_TABLE, "applicability" )
