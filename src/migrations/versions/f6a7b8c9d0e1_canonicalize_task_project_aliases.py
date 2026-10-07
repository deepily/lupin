"""Canonicalize task_items.project through the shared _PROJECT_ALIASES map

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0

One-time data re-stamp for an alias read/write mismatch that made sessions look idle.

The owed-work oracle (stop.py `_owed_count_from_store` -> `resolve_project_name`)
alias-normalizes the project on read, for example "planning-is-prompting" -> "plan".
The MCP `task_create` write path stored the project raw. Aliased-repo sessions wrote
rows under "planning-is-prompting" while the oracle queried "plan", so query_owed
was 0 and every aliased-repo session looked idle while still owing work.

The code fix canonicalizes at the write seam (task_create_impl) going forward.
This migration re-stamps rows already written under a raw alias key, so the
back-catalogue becomes queryable too.

Single source of the alias map: the canonical-name pairs are imported from the one
`_PROJECT_ALIASES` table in `cosa.agents.utils.sender_id` and never copied into this
migration. The read seam, the write seam and `resolve_project_name()` use the same table.

It is idempotent: each `UPDATE` re-stamps `project = canonical WHERE project = raw`.
After it runs, no rows remain under the raw key. A re-run, or the auto-migrate startup
path (cosa.rest.db.auto_migrate), updates zero rows. It is safe on every environment,
including a fresh database whose task_items table is empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _task_items_exists( bind ) -> bool:
    """Return True iff the `task_items` table is present on the live DB."""
    return inspect( bind ).has_table( "task_items" )


def upgrade() -> None:
    """Re-stamp every raw alias key to its canonical short name (idempotent)."""
    # Imported here (not at module top) so the revision file can be IMPORTED for
    # offline tooling even if the app package is not on the path; at online
    # upgrade time env.py has already put `src/` on sys.path (it imports
    # cosa.rest.postgres_models), so this resolves.
    from cosa.agents.utils.sender_id import _PROJECT_ALIASES

    bind = op.get_bind()
    if not _task_items_exists( bind ):
        # No table yet (an env that stamps before the task-store tables exist) —
        # nothing to re-stamp. Keep the migration safe/idempotent.
        return

    for raw, canonical in _PROJECT_ALIASES.items():
        bind.execute(
            text( "UPDATE task_items SET project = :canonical WHERE project = :raw" ),
            { "canonical": canonical, "raw": raw },
        )


def downgrade() -> None:
    """
    Intentional no-op.

    This is a lossy canonicalization. After the re-stamp, a row stored as the
    canonical short name (e.g. "plan") is indistinguishable from a row that was
    always canonical. Reverse-mapping every canonical row back to a raw alias key
    would corrupt rows that never used the alias. The forward direction is the
    only safe one, so the downgrade does nothing.
    """
    pass
