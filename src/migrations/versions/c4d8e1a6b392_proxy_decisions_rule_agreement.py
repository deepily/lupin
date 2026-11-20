"""
Add proxy_decisions.rule_agreement, the human answer against the row's action

Revision ID: c4d8e1a6b392
Revises: 7a3e9c5d1b28

Rule agreement is kept apart from the trust gate's success.
An act or suggest row implies approval, so the column is true when the human approved and false when they did not.
It is NULL for a shadow row, a defer row, and a row nobody answered.
This is Mr. Radio's reading of "rule", for Rick to confirm.

The column is nullable boolean with no backfill, so every earlier row reads NULL.
The upgrade adds the column only when missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'c4d8e1a6b392'
down_revision: Union[str, Sequence[str], None] = '7a3e9c5d1b28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "proxy_decisions"
COLUMN_NAME = "rule_agreement"


def _column_names( inspector ) -> set:
    """
    Name the columns of proxy_decisions.

    Requires:
        - inspector reads the database the migration runs against, and the table exists

    Ensures:
        - returns the set of column names
    """
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add rule_agreement (nullable boolean).

    Ensures:
        - no-op when proxy_decisions is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, sa.Boolean(), nullable=True ) )


def downgrade() -> None:
    """
    Drop the rule_agreement column.

    Ensures:
        - no-op when proxy_decisions is absent or the column is already gone
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
