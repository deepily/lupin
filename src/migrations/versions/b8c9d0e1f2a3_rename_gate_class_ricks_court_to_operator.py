"""Rename gate_class value 'ricks_court' -> 'operator' (one-name-everywhere)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-23

Data migration for the `operator` rename (Lane A0, proactive-manager mechanism
design — planning-is-prompting/src/rnd/2026.06.23-proactive-manager-doctrine-and-
mechanism.md §Rename). Rick's portability catch: `ricks_court` baked a person's
name into the gate-class enum — off-putting and non-portable to the next human
overseer. The role-based `operator` replaces it EVERYWHERE with NO compat
shim/alias (Rick's one-name-everywhere contract rule).

The app-side enum (`task_store_rules.VALID_GATE_CLASSES`) and every code filter/
mint site are renamed in the same commit; this migration heals the BACK-CATALOGUE
so a row already persisted under the retired `ricks_court` value stays queryable
and keeps being recognized as user-gated by the arbiter
(`_item_is_user_gated` now matches `gate_class == "operator"`).

GATE-CLASS-COLUMN-ONLY + IDEMPOTENT: the statement is
`UPDATE task_items SET gate_class = 'operator' WHERE gate_class = 'ricks_court'`
— it touches NO other column and NO row whose gate_class is not the retired
value, so a terminal (done/dropped) row keeps its status untouched. After it runs
no rows remain under the retired key, so a re-run updates zero rows. Safe on every
environment, including a fresh DB whose task_items table is empty.

`gate_class` is a free VARCHAR (house style: no PG ENUM — see
task_store_rules.py §Enums), so there is NO enum type / CHECK constraint to
alter; the value rename is a pure data UPDATE.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _task_items_exists( bind ) -> bool:
    """Return True iff the `task_items` table is present on the live DB."""
    return inspect( bind ).has_table( "task_items" )


def upgrade() -> None:
    """Re-stamp every retired `ricks_court` gate to `operator` (idempotent)."""
    bind = op.get_bind()
    if not _task_items_exists( bind ):
        # No table yet (an env that stamps before the task-store tables exist) —
        # nothing to re-stamp. Keep the migration safe/idempotent.
        return

    bind.execute(
        text( "UPDATE task_items SET gate_class = 'operator' WHERE gate_class = 'ricks_court'" )
    )


def downgrade() -> None:
    """
    Reverse the rename: restore every `operator` gate to `ricks_court`.

    This is a FAITHFUL inverse for the value-rename. The downgrade also restores
    the pre-rename application code, whose `VALID_GATE_CLASSES` accepts ONLY
    `ricks_court` (never `operator`) for a user gate — so mapping every `operator`
    row back to `ricks_court` is exactly the value the reverted code expects. Like
    the upgrade it is gate-class-column-only + idempotent.
    """
    bind = op.get_bind()
    if not _task_items_exists( bind ):
        return

    bind.execute(
        text( "UPDATE task_items SET gate_class = 'ricks_court' WHERE gate_class = 'operator'" )
    )
