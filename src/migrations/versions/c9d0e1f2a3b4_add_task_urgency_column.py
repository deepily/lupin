"""Add task_items.urgency column (operator-gate time-sensitivity tiering)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-23

Adds the `urgency` column. An operator gate carries a time-sensitivity tier, one of
urgent, normal or low, distinct from the existing `priority` importance field.
The arbiter, the single pusher, routes a gate by it. Urgent means an immediate
interrupt, normal a batched digest, and low queue-until-pulled. The design is in
planning-is-prompting/src/rnd/2026.06.23-proactive-manager-doctrine-and-mechanism.md.

The column is `NOT NULL` with server_default 'normal'. The add therefore backfills every
existing row to the low-friction default in one statement, with no separate data pass.
It is indexed to mirror the ORM column. The arbiter's per-tier query filters on it:
`task_query(gate_class=operator, urgency=urgent)`. The add-column shape mirrors the
proxy/trust columns migration (e5f6a7b8c9d0).

Guarded and idempotent. It is skipped when task_items is absent (a database stamped
before the task store existed). It is a no-op when the column already exists, so it is
safe on a fresh create_all database and on a re-run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "task_items"
_COLUMN = "urgency"
_INDEX  = "ix_task_items_urgency"


def _has_table( bind ) -> bool:
    return inspect( bind ).has_table( _TABLE )


def _has_column( bind ) -> bool:
    return any( c[ "name" ] == _COLUMN for c in inspect( bind ).get_columns( _TABLE ) )


def _has_index( bind ) -> bool:
    return any( ix[ "name" ] == _INDEX for ix in inspect( bind ).get_indexes( _TABLE ) )


def upgrade() -> None:
    """Add the urgency column (default 'normal') + its index, idempotently."""
    bind = op.get_bind()
    if not _has_table( bind ):
        return
    if not _has_column( bind ):
        op.add_column(
            _TABLE,
            sa.Column( _COLUMN, sa.String( 8 ), nullable=False, server_default="normal" ),
        )
    if not _has_index( bind ):
        op.create_index( _INDEX, _TABLE, [ _COLUMN ] )


def downgrade() -> None:
    """Drop the urgency index + column, idempotently."""
    bind = op.get_bind()
    if not _has_table( bind ):
        return
    if _has_index( bind ):
        op.drop_index( _INDEX, table_name=_TABLE )
    if _has_column( bind ):
        op.drop_column( _TABLE, _COLUMN )
