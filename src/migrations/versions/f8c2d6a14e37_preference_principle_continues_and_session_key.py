"""
Add continues_principle_id to the principles and session_key to the evidence

Revision ID: f8c2d6a14e37
Revises: e5b7d9a2c418

A new extractor version may re-extract a principle Rick has already ruled on.
Matching the new row to the ruled one by owner, scope and dimension is unsafe.
It would carry the ruling onto a different principle in the same dimension.
So the new principle names the earlier principle it continues, in preference_principles.continues_principle_id.

The evidence table has no foreign key to notifications, so pruning a notification leaves its evidence.
Status counts sessions from the notification, so a pruned one would read as no session.
So the evidence row keeps its own session key, in preference_evidence.session_key.

Both columns are nullable with no backfill: NULL means none, which is every row written before this revision.
The principle column is a foreign key to preference_principles.id.
The upgrade adds each column only when its table exists and the column is missing.
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


PRINCIPLES_TABLE = "preference_principles"
EVIDENCE_TABLE   = "preference_evidence"
CONTINUES_COLUMN = "continues_principle_id"
SESSION_COLUMN   = "session_key"


def _column_names( inspector, table ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( table ) }


def upgrade() -> None:
    """
    Add continues_principle_id and session_key.

    Ensures:
        - a column whose table is absent is skipped (a database built from the models has both already)
        - each column is added only when missing (re-run safe, and a half-applied upgrade finishes)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    tables    = set( inspector.get_table_names() )

    if PRINCIPLES_TABLE in tables and CONTINUES_COLUMN not in _column_names( inspector, PRINCIPLES_TABLE ):
        op.add_column( PRINCIPLES_TABLE, sa.Column( CONTINUES_COLUMN, postgresql.UUID( as_uuid=True ), sa.ForeignKey( 'preference_principles.id' ), nullable=True ) )

    if EVIDENCE_TABLE in tables and SESSION_COLUMN not in _column_names( inspector, EVIDENCE_TABLE ):
        op.add_column( EVIDENCE_TABLE, sa.Column( SESSION_COLUMN, sa.String( 255 ), nullable=True ) )


def downgrade() -> None:
    """
    Drop the two columns.

    Ensures:
        - a column whose table is absent is skipped
        - each drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    tables    = set( inspector.get_table_names() )

    if EVIDENCE_TABLE in tables and SESSION_COLUMN in _column_names( inspector, EVIDENCE_TABLE ):
        op.drop_column( EVIDENCE_TABLE, SESSION_COLUMN )

    if PRINCIPLES_TABLE in tables and CONTINUES_COLUMN in _column_names( inspector, PRINCIPLES_TABLE ):
        op.drop_column( PRINCIPLES_TABLE, CONTINUES_COLUMN )
