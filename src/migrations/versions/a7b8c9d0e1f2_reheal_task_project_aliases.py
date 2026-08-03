"""Re-heal task_items.project back-catalogue through _PROJECT_ALIASES (fix-forward)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-22

Fix-forward for the project-name canonicalization REQUEST-CHANGES (Tiberius
review of 8358ce1f). 8358ce1f added the FORWARD fix — server-side write-seam
canonicalization (routers/tasks.py `_canon_project`) + query-FILTER
canonicalization — so EVERY row written from now on, and every filter value
queried, normalizes through the ONE `_PROJECT_ALIASES` map ("planning-is-
prompting" -> "plan"). That is correct and stays.

What it did NOT do: heal the BACK-CATALOGUE. The query canonicalizes the
FILTER value, never the STORED column, so a row already persisted under a RAW
alias key (e.g. Rick's TODO-archival task, still project="planning-is-
prompting") stays OUT of `query_owed(project="plan")` — the owning session
false-idles while genuinely owing work (the alias-axis sibling of the
2026-06-18 persona-drift P0).

The earlier re-stamp (revision f6a7b8c9d0e1, 2026-06-18) DID re-stamp — but it
is ALREADY APPLIED, so alembic will never run it again. Any raw-alias row
written AFTER that revision was stamped (a non-wrapper POST, a pre-8358ce1f
write path) is therefore unhealed. A FRESH revision at the head re-runs the
re-stamp NOW, sweeping up exactly those rows, and runs once more on every
future fresh-DB stamp.

SINGLE SOURCE OF THE ALIAS MAP: the canonical-name pairs are imported from the
ONE `_PROJECT_ALIASES` table in `cosa.agents.utils.sender_id` — never copied
here. The same table the read seam, the write seam, `canonicalize_project_name`,
and `resolve_project_name()` all use (defect D from the review: reuse the SAME
canonicalize_project_name, no second alias map).

PROJECT-COLUMN-ONLY + IDEMPOTENT: each statement is
`UPDATE task_items SET project = :canonical WHERE project = :raw` — it touches
NO other column and NO row whose project is not a raw alias key, so a terminal
(done/dropped) row keeps its status untouched (only its project is canonicalized,
which is what makes a closed-but-still-relevant row queryable). After it runs no
rows remain under the raw key, so a re-run updates zero rows. Safe on every
environment, including a fresh DB whose task_items table is empty.
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
    ALWAYS canonical. Reverse-mapping every canonical row back to a raw alias key
    would corrupt rows that never used the alias. The forward direction is the
    only safe one, so the downgrade deliberately does nothing.
    """
    pass
