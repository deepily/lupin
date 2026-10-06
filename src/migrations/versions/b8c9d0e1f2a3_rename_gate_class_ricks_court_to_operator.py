"""Rename gate_class value 'ricks_court' -> 'operator' (one-name-everywhere)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-23

Data migration for the `operator` rename. The design is in planning-is-prompting/src/rnd/
2026.06.23-proactive-manager-doctrine-and-mechanism.md, section Rename. `ricks_court` baked
a person's name into the gate-class enum, which does not port to the next human overseer.
The role-based `operator` replaces it everywhere, with no compatibility shim or alias.

The app-side enum (`task_store_rules.VALID_GATE_CLASSES`) and every code filter and mint
site are renamed in the same commit. This migration heals the back-catalogue. A row
persisted under the retired `ricks_court` value stays queryable. The arbiter keeps
recognizing it as user-gated, because `_item_is_user_gated` matches `gate_class == "operator"`.

It touches the gate_class column only, and it is idempotent. The statement is
`UPDATE task_items SET gate_class = 'operator' WHERE gate_class = 'ricks_court'`.
It touches no other column and no row whose gate_class is not the retired value, so a
terminal (done or dropped) row keeps its status. After it runs no rows remain under the
retired key, so a re-run updates zero rows. It is safe on every environment, including a
fresh database whose task_items table is empty.

`gate_class` is a free VARCHAR (house style: no Postgres enum type, see the enums section
of task_store_rules.py). There is no enum type or `CHECK` constraint to alter, so the
value rename is a pure data update.
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

    This is a faithful inverse for the value rename. The downgrade also restores the
    pre-rename application code. That code's `VALID_GATE_CLASSES` accepts only
    `ricks_court`, never `operator`, for a user gate. Mapping every `operator` row back
    to `ricks_court` gives the value the reverted code expects. Like the upgrade it
    touches the gate_class column only and is idempotent.
    """
    bind = op.get_bind()
    if not _task_items_exists( bind ):
        return

    bind.execute(
        text( "UPDATE task_items SET gate_class = 'ricks_court' WHERE gate_class = 'operator'" )
    )
