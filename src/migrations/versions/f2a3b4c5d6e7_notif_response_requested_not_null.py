"""notifications.response_requested -> `NOT NULL` (reconcile DB with ORM)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6

This migration was re-filed. The original, authored as revision a7b8c9d0e1f2 on
a branch stranded by a squash-merge, never reached the v0.1.9 line. A different
migration (`a7b8c9d0e1f2_reheal_task_project_aliases`) has since claimed that id
with the same parent. The original could not merge without giving Alembic two
revisions that share one id. This is the identical fix chained onto the current
head (e1f2a3b4c5d6) under a fresh revision id. The logic is unchanged.

The ORM (`postgres_models.py`) declares `notifications.response_requested` as a
non-Optional `Mapped[bool]` with `server_default="false"`, which means `NOT NULL`.
A real deployed DB built by SQLAlchemy `create_all` honored that and stores the
column as `boolean DEFAULT false NOT NULL` (see the captured dump
`postgresql-backup.sql`). The true-baseline migration (000000000000) wrote the
column as `BOOLEAN DEFAULT FALSE` without `NOT NULL`. A DB built purely from
`alembic upgrade head` therefore ends up with a nullable column, diverging from
both the ORM and every `create_all`-built deployment. An independent
`alembic autogenerate` against the ORM metadata on a freshly upgraded throwaway
DB surfaced this. It predates e5f6a7b8c9d0 and was not introduced by it, since
that revision never touches `response_requested`.

The direction is to tighten the DB to `NOT NULL`, not to relax the ORM. The ORM
and the real deployed schema both already say `NOT NULL` with
`server_default false`, and the baseline migration is the lone outlier.
Relaxing the ORM would contradict the deployed reality and the `server_default`,
which guarantees the column is always populated. The only coherent reconcile is
to make the migration-built schema match.

The migration is idempotent and safe over both DB lineages. The backfill
`UPDATE` touches zero rows when none are NULL, and `SET NOT NULL` on an
already-`NOT NULL` column is a no-op in Postgres. So it is safe over a
`create_all`-bootstrapped DB (column already `NOT NULL`) and over a pure
`upgrade head` DB (nullable, then tightened). The `server_default` is preserved
verbatim (`existing_server_default`), never rewritten. It is inspector-guarded:
if the `notifications` table is absent (an env that stamps before it exists),
the migration no-ops.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _notifications_exists( bind ) -> bool:
    """Return True iff the `notifications` table is present on the live DB."""
    return inspect( bind ).has_table( "notifications" )


def upgrade() -> None:
    """Backfill any NULLs to false, then tighten response_requested to `NOT NULL`."""
    bind = op.get_bind()
    if not _notifications_exists( bind ):
        # Table not present yet (an env that stamps before notifications exists)
        # — nothing to tighten. Keep the migration safe/idempotent.
        return

    # Backfill FIRST: any legacy NULL becomes the canonical default before the
    # NOT NULL constraint is applied, so the ALTER cannot fail on existing rows.
    bind.execute(
        text( "UPDATE notifications SET response_requested = false WHERE response_requested IS NULL" )
    )

    op.alter_column(
        "notifications",
        "response_requested",
        existing_type=sa.Boolean(),
        nullable=False,
        existing_server_default=sa.text( "false" ),
    )


def downgrade() -> None:
    """Relax response_requested back to NULLABLE (server_default preserved)."""
    op.alter_column(
        "notifications",
        "response_requested",
        existing_type=sa.Boolean(),
        nullable=True,
        existing_server_default=sa.text( "false" ),
    )
