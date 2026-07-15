"""notifications.response_requested -> NOT NULL (reconcile DB with ORM)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-18 (re-filed 2026-07-14)

Follow-on migration-drift fix for bug 11cda843.

RE-FILED: originally authored 2026-06-18 as revision a7b8c9d0e1f2 on branch
`wip-notif-nn-11cda843`, which was stranded when v0.1.8 was squash-merged (PR #18)
and never reached the v0.1.9 line. In the interim a DIFFERENT migration claimed
a7b8c9d0e1f2 (`a7b8c9d0e1f2_reheal_task_project_aliases`) with the same parent —
so the original file could not be merged without giving Alembic two revisions
sharing one id. This is the identical fix re-chained onto the current head
(e1f2a3b4c5d6) under a fresh, non-colliding revision id. Logic is unchanged.

The ORM (`postgres_models.py`) declares `notifications.response_requested` as a
non-Optional `Mapped[bool]` with `server_default="false"` — i.e. NOT NULL. A
real deployed DB (built by SQLAlchemy `create_all`) honored that and stored the
column as `boolean DEFAULT false NOT NULL` (see the captured dump
`postgresql-backup.sql`). But the TRUE-baseline migration (000000000000) wrote
the column as `BOOLEAN DEFAULT FALSE` WITHOUT a NOT NULL constraint, so a DB
built purely from `alembic upgrade head` ends up with a NULLABLE column —
diverging from BOTH the ORM and every `create_all`-built deployment. The
migration-drift fresh-critical reviewer (session 0ed0fbb0) surfaced this via an
independent `alembic autogenerate` vs ORM metadata on a freshly-upgraded
throwaway DB (bug 11cda843). It is PRE-EXISTING and was NOT introduced by
e5f6a7b8c9d0 (which never touches `response_requested`).

DIRECTION CHOSEN — tighten the DB to NOT NULL, NOT relax the ORM: the ORM AND
the real deployed schema both already say NOT NULL with `server_default false`;
the baseline migration is the lone outlier. Relaxing the ORM would contradict
the deployed reality and the `server_default` (which guarantees the column is
always populated), so the only coherent reconcile is to make the
migration-built schema match.

IDEMPOTENT / SAFE over both DB lineages: the backfill UPDATE touches zero rows
when none are NULL, and `SET NOT NULL` on an already-NOT-NULL column is a no-op
in Postgres — so this is safe over a `create_all`-bootstrapped DB (column
already NOT NULL) AND a pure `upgrade head` DB (nullable -> tightened). The
`server_default` is preserved verbatim (`existing_server_default`), never
rewritten. Inspector-guarded: if the `notifications` table is absent (an env
that stamps before it exists), the migration no-ops.
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
    """Backfill any NULLs to false, then tighten response_requested to NOT NULL."""
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
