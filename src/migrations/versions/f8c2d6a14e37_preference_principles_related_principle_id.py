"""
Add preference_principles.related_principle_id, the principle a re-extraction continues

Revision ID: f8c2d6a14e37
Revises: e5b7d9a2c418

A new extractor version may re-extract a principle Rick has already ruled on.
Matching the new row to the ruled one by owner, scope and dimension is unsafe.
It would carry the ruling onto a different principle in the same dimension.
So the new row names the earlier principle it continues.

The column is a nullable foreign key to preference_principles.id, with no backfill. NULL means the row
continues none, which is every row written before this revision. The upgrade adds the column only when
the table exists and the column is missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f8c2d6a14e37'
down_revision: Union[str, Sequence[str], None] = 'e5b7d9a2c418'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "preference_principles"
COLUMN_NAME = "related_principle_id"


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add related_principle_id (nullable UUID, foreign key to preference_principles.id).

    Ensures:
        - no-op when preference_principles is absent (a database built from the models has the column already)
        - the column is added only when missing (re-run safe)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, postgresql.UUID( as_uuid=True ), sa.ForeignKey( 'preference_principles.id' ), nullable=True ) )


def downgrade() -> None:
    """
    Drop the related_principle_id column.

    Ensures:
        - no-op when preference_principles is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if TABLE_NAME not in inspector.get_table_names():
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
