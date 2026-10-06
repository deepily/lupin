"""Add task_items.body_changed_ts — the content-change marker park staleness reads

Revision ID: 38e025169a73
Revises: 53835fd51f1a
Create Date: 2026-07-26

`body_changed_ts TIMESTAMPTZ NULL` is the instant the row's `body` last actually
changed. The database clock stamps it, from the two paths that write body:

    `apply_amendment` always stamps it, because an amend only ever appends to body.
    `apply_patch` stamps it only when `body` is in the payload and its value differs.

Why: `park_reason_is_stale` compared `park_reason_captured_at` against `updated_ts`,
which moves on every write. Only a change to `body` can make a park quote untrue.
Yet a priority-only edit bumped `updated_ts` and flipped the flag anyway. Staleness
is advisory and blocks nothing, so a false stale has nothing to correct it. It
defames a correct quote and teaches readers to ignore the flag, which disarms the
feature. A false fresh is only the old behaviour, so the predicate biases every
ambiguous case toward fresh.

No backfill: every existing row gets NULL, and a NULL third argument reads as fresh
(the `else: return False` arm of `task_store_owed.park_reason_is_stale`). So the
flag is inert until each row's body next changes. Backfilling `updated_ts` would
keep every current false positive. Backfilling `created_ts` would claim the body
never changed since creation, which is false for most rows. There is no `CHECK`
and there must not be one. A row whose body never changed legitimately has no
value, and a `NOT NULL` would assert history nobody recorded. (`d47487369407` had
to backfill only because its `CHECK` would have rejected live parked rows.)

Why the database clock, not `datetime.now()`: `park_reason_captured_at` comes from
the database clock (`TaskRepository._db_clock_now`, see `_park_capture_ts`). This
column is compared against it. An application-clock stamp would make that
comparison cross-clock, and skew would surface as a false fresh: an expired quote
quietly going unreported. One clock, one value.

Scope: one nullable column, no `CHECK`, no backfill. Idempotent and safe to re-run:
the column is added only when missing. The auto-migrate startup path may reach this
on an already-migrated DB, and the test DB is built from metadata.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '38e025169a73'
down_revision: Union[str, Sequence[str], None] = '53835fd51f1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "task_items"
COLUMN_NAME = "body_changed_ts"


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add the nullable body_changed_ts column.

    Ensures:
        - no-op when task_items is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - no backfill and no `CHECK` — see the module docstring; existing rows keep
          NULL, which the predicate reads as fresh
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, sa.DateTime( timezone=True ), nullable=True ) )
        print( f"[{revision}] added {TABLE_NAME}.{COLUMN_NAME} (NULL for every existing row — reads as FRESH by design)" )


def downgrade() -> None:
    """
    Drop the body_changed_ts column.

    Downgrading re-arms the false-stale defect: the predicate falls back to
    `updated_ts` and a priority-only edit will defame a correct quote again.

    Ensures:
        - no-op when task_items is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
