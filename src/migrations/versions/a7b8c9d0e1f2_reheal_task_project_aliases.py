"""Re-heal task_items.project back-catalogue through _PROJECT_ALIASES (fix-forward)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-22

The write seam (routers/tasks.py `_canon_project`) and the query filter both
canonicalize the project name. Every row written now, and every filter value
queried, normalizes through the one `_PROJECT_ALIASES` map ("planning-is-
prompting" -> "plan"). That is correct and stays.

It did not heal the back-catalogue. The query canonicalizes the filter value,
never the stored column. A row already persisted under a raw alias key (for
example the TODO-archival task, still project="planning-is-prompting") stays
out of `query_owed(project="plan")`. The owning session then false-idles while
it still owes work.

The earlier re-stamp (revision f6a7b8c9d0e1) did re-stamp, but it is already
applied, so alembic will never run it again. Any raw-alias row written after
that revision was stamped (a non-wrapper POST, an older write path) is therefore
unhealed. A fresh revision at the head re-runs the re-stamp now, sweeping up
exactly those rows, and runs once more on every future fresh-DB stamp.

Single source of the alias map: the canonical-name pairs are imported from the
one `_PROJECT_ALIASES` table in `cosa.agents.utils.sender_id` and never copied
here. It is the same table the read seam, the write seam,
`canonicalize_project_name`, and `resolve_project_name()` all use, so there is
no second alias map.

The migration touches only the project column and is idempotent. Each statement
is `UPDATE task_items SET project = :canonical WHERE project = :raw`. It touches
no other column and no row whose project is not a raw alias key, so a terminal
(done/dropped) row keeps its status untouched. Only its project is
canonicalized, which is what makes a closed-but-still-relevant row queryable.
After it runs no rows remain under the raw key, so a re-run updates zero rows.
It is safe on every environment, including a fresh DB whose task_items table is
empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
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

    This is a lossy canonicalization: after the re-stamp, a row stored as the
    canonical short name (e.g. "plan") is indistinguishable from a row that was
    always canonical. Reverse-mapping every canonical row back to a raw alias key
    would corrupt rows that never used the alias. The forward direction is the
    only safe one, so the downgrade does nothing.
    """
    pass
