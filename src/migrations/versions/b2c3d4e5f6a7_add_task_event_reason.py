"""add_task_event_reason

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-12

Adds the `reason` column to task_events. A transition to dropped requires a
reason. The hook's harness-deleted to dropped mapping and the supersede
mechanics both need the field.

Additive and nullable, so task_events, the fleet-allocation convergence
target, is unaffected. The API layer enforces the reason for a transition to
dropped (task_store_rules.validate_transition), not the schema.

Design: planning-is-prompting -> planning-is-prompting/src/rnd/2026.06.11-unified-task-store-design.md
(v0.4.1) + lupin src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable task_events.reason.

    Idempotent. A create_all-bootstrapped DB stamped below this revision already
    has task_events.reason, so an unguarded ``add_column`` raises DuplicateColumn
    on ``upgrade head``. Add the column only when it is absent. That is a safe
    no-op on a create_all DB. It is a real add on the empty-DB path, where
    f0a1b2c3d4e5 just built task_events without it.
    """
    insp   = sa.inspect( op.get_bind() )
    tables = set( insp.get_table_names() )
    cols   = { c[ "name" ] for c in insp.get_columns( "task_events" ) } if "task_events" in tables else set()

    if "task_events" in tables and "reason" not in cols:
        op.add_column( 'task_events', sa.Column( 'reason', sa.Text(), nullable=True ) )


def downgrade() -> None:
    """Symmetric removal of task_events.reason (idempotent — only when present)."""
    insp   = sa.inspect( op.get_bind() )
    tables = set( insp.get_table_names() )
    cols   = { c[ "name" ] for c in insp.get_columns( "task_events" ) } if "task_events" in tables else set()

    if "reason" in cols:
        op.drop_column( 'task_events', 'reason' )
