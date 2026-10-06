"""Add task_items.title_trimmed — record the trim, not re-derive it

Revision ID: 47513717b7e5
Revises: 3da5c0d1eee6
Create Date: 2026-08-31

`task_store_rules.title_may_be_trimmed` is `len( title ) == TITLE_SOFT_CAP`, and
`_serialize_item_terse` calls it with no cap argument. The board's `title_trimmed` flag is
therefore re-derived on every read against whatever the cap currently is, not recorded.
Raising the cap would switch the flag off across the existing corpus, with nothing failing.
This migration is the prerequisite for raising the cap. It adds
`title_trimmed BOOLEAN NOT NULL DEFAULT false`, written at both write paths from the
guard's own return value and never re-derived at read time.

Unlike `body_changed_ts` (`38e025169a73`), which is nullable with no backfill because any
value would fabricate unrecorded history, this column can be backfilled from the rows.
`soft_guard_title` trims with `title[ :cap ]`, so a trimmed title is exactly cap characters
long. A title still at the cap is the record of the cut. The overflow marker in a body is
not that record. It makes the cut text recoverable by grep, but does not show a cut title.

The backfill is one arm: `title_trimmed = TRUE WHERE length( title ) = 60`. It freezes the
current read-time value, so nothing flagged now stops being flagged when this lands. A second
arm, `OR body LIKE '%[title overflow%'`, was removed rather than narrowed. Every row it could
add has a length other than the cap, so every one is a false positive. Rows matching only the
marker were trimmed and then repaired by a shorter retitle, or have bodies that quote the
marker while discussing it. Narrowing with `AND length( title ) = cap` makes the arm dead,
because `A AND B` combined with `B` is `B`.

60 is a historical literal, not the current cap, and must not be updated when the cap
changes. It names the cap that trimmed the existing rows, which the backfill describes.

The clause over-reports in the harmless direction. A row at exactly 60 characters with no
marker is consistent with a trim into an empty body, which files the overflow unmarked. A
false positive costs a reader one look at a body with nothing missing.

Going forward `apply_patch` writes the flag on every title change from the guard's verdict.
Scope is one column and one `UPDATE`: no `CHECK`, no other table, no title text altered.
The migration is idempotent. The backfill runs only in the branch that adds the column,
so a re-run never re-stamps a row whose flag a later retitle cleared. The revision id is
random (uuid4), because the neighbours' hex pattern walks into the absorbed range.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '47513717b7e5'
down_revision: Union[str, Sequence[str], None] = '3da5c0d1eee6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "task_items"
COLUMN_NAME = "title_trimmed"

# The cap that trimmed the EXISTING corpus. Historical, not configuration —
# see the module docstring. Do not track TITLE_SOFT_CAP with this.
HISTORICAL_CAP = 60


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add title_trimmed (`NOT NULL`, default false), then backfill it from the rows.

    Ensures:
        - no-op when task_items is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - the backfill runs only in the same branch as the add, so a re-run never
          re-stamps a row whose flag a later retitle legitimately cleared
        - every row flagged by the pre-migration read-time predicate is still
          flagged afterwards, and no other row is (the clause is that predicate,
          frozen at the historical cap)
        - a row carrying the overflow marker but a title not at the cap is left
          False: it was repaired by a later retitle, or its body merely quotes
          the marker while discussing it
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME in _column_names( inspector ):
        return

    op.add_column(
        TABLE_NAME,
        sa.Column( COLUMN_NAME, sa.Boolean(), nullable=False, server_default=sa.false() )
    )

    result = bind.execute(
        sa.text(
            f"UPDATE {TABLE_NAME} SET {COLUMN_NAME} = true "
            f"WHERE length( title ) = :cap"
        ),
        { "cap": HISTORICAL_CAP },
    )
    print(
        f"[{revision}] added {TABLE_NAME}.{COLUMN_NAME} and backfilled "
        f"{result.rowcount} row(s) — titles sitting at the historical "
        f"{HISTORICAL_CAP}-char cap"
    )


def downgrade() -> None:
    """
    Drop the title_trimmed column.

    Downgrading returns the flag to read-time derivation against the current cap. If the
    cap has moved meanwhile, every historically trimmed row silently stops being flagged.

    Ensures:
        - no-op when task_items is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
