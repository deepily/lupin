"""
Add answer_meaning, the versioned reading of a stored answer

Revision ID: e1b7c4a9d286
Revises: d5e9f2b7c413

The meaning record of the answer-record plan. It is append-only.
It is unique on ( notification_id, schema_version, annotator ).
A new schema version or annotator is a new row.
The old row stays.
notification_id has no foreign key, so pruning notifications never removes a reading.
The table is created only when absent, so a re-run, or a database built from the models, is a safe no-op.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e1b7c4a9d286'
down_revision: Union[str, Sequence[str], None] = 'd5e9f2b7c413'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "answer_meaning"
UNIQUE_KEY = "uq_answer_meaning_key"
INDEX_NAME = "ix_answer_meaning_notification_id"


def upgrade() -> None:
    """
    Create the answer_meaning table.

    Ensures:
        - the table is created only when absent
        - it carries the unique key named in the module docstring and an index on notification_id
    """
    if TABLE_NAME in set( sa.inspect( op.get_bind() ).get_table_names() ): return
    op.create_table(
        TABLE_NAME,
        sa.Column( 'id', postgresql.UUID( as_uuid=True ), primary_key=True, server_default=sa.text( 'gen_random_uuid()' ) ),
        sa.Column( 'notification_id', postgresql.UUID( as_uuid=True ), nullable=False ),
        sa.Column( 'schema_version', sa.String( 50 ), nullable=False ),
        sa.Column( 'annotator', sa.String( 100 ), nullable=False ),
        sa.Column( 'source', sa.String( 20 ), nullable=False ),
        sa.Column( 'native_answer', postgresql.JSONB(), nullable=False ),
        sa.Column( 'acts', postgresql.JSONB(), nullable=False ),
        sa.Column( 'conditions', postgresql.JSONB(), nullable=False ),
        sa.Column( 'alignment', sa.String( 30 ), nullable=False ),
        sa.Column( 'unknowns', postgresql.JSONB(), nullable=False ),
        sa.Column( 'supporting_spans', postgresql.JSONB(), nullable=True ),
        sa.Column( 'uncertainty', sa.Float(), nullable=True ),
        sa.Column( 'answered_at', sa.DateTime( timezone=True ), nullable=True ),
        sa.Column( 'annotated_at', sa.DateTime( timezone=True ), nullable=False ),
        sa.Column( 'session_key', sa.String( 255 ), nullable=True ),
        sa.UniqueConstraint( 'notification_id', 'schema_version', 'annotator', name=UNIQUE_KEY )
    )
    op.create_index( INDEX_NAME, TABLE_NAME, [ 'notification_id' ] )


def downgrade() -> None:
    """
    Drop the answer_meaning table, only when present.

    Ensures:
        - a database that never had the table downgrades cleanly
    """
    if TABLE_NAME in set( sa.inspect( op.get_bind() ).get_table_names() ):
        op.drop_table( TABLE_NAME )
