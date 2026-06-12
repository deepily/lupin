"""add_task_event_reason

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-12

Task store Phase 2 (write-path hooks): adds the `reason` column to
task_events (cold-review C12 "->dropped requires a reason", pulled forward
into Phase 2 by Tiberius ruling qid b312b0f1 — the hook's harness-deleted ->
dropped mapping and the C1 supersede mechanics both need the field).

ADDITIVE + nullable: D1 (task_events is the fleet-allocation convergence
target) is unaffected. Requiredness for ->dropped is enforced at the API
layer (task_store_rules.validate_transition), not by the schema.

Design: planning-is-prompting -> src/rnd/2026.06.11-unified-task-store-design.md
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
    """Add nullable task_events.reason."""
    op.add_column( 'task_events', sa.Column( 'reason', sa.Text(), nullable=True ) )


def downgrade() -> None:
    """Symmetric removal of task_events.reason."""
    op.drop_column( 'task_events', 'reason' )
