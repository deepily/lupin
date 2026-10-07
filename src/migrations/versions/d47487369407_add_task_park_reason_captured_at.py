"""Add task_items.park_reason_captured_at + its parked `CHECK` constraint

Revision ID: d47487369407
Revises: c1a7f0e2b9d4

Backs park_reason staleness detection (design src/rnd/v0.1.9/2026.07.19-park-reason-staleness-detection.md, section 3.1).

`park_reason_captured_at` TIMESTAMPTZ NULL records when the `park_reason` quote was frozen.
Amend the row afterward and the quote stays valid in form while it stops being true.
`task_store_owed.park_reason_is_stale` compares the capture instant to `updated_ts`.
One `CHECK`, mirroring the two `c1a7f0e2b9d4` added, is a separate constraint so a
violation names the missing field:

```
status != 'parked' OR park_reason_captured_at IS NOT NULL
```

The value written at park time is the post-write `updated_ts`, which `onupdate=func.now()`
bumps on the park write itself. Writing `now()` races the stamp by microsecond order.
The pre-write value leaves captured_at below updated_ts, so every row is born stale.
The post-write value gives equality at park and a later amendment bumps updated_ts above it, so the invariant is equality.

The backfill value is fabricated, not measured. Rows already parked have no recoverable
capture time, so the migration writes `park_reason_captured_at = updated_ts` for them.
That does not mean the quote was captured then. It means we cannot know, and the value makes
the row read not-stale, as the design prescribes. It is labelled so because an unlabelled
synthetic timestamp looks measured.

Backfill rather than `CHECK ... NOT VALID`: the model's `CheckConstraint` (used by
`create_all`) has no `NOT VALID` equivalent, so migration and model would disagree.
The backfill cannot bump `updated_ts`: `onupdate` is ORM-client-side only, with no DB
trigger, and the raw SQL `SET` list names one column. `_verify_backfill_equality` is the
receipt and fails the upgrade on any violating row. A green does not prove a write path got
the ordering right, because Postgres `now()` is stable across a transaction. Pin the
ordering at the mechanism: one captured value written to both columns in one statement.

Scope is `WHERE status = 'parked'` only. Each step inspects the live schema and the backfill
is guarded by `IS NULL`, so a re-run is idempotent. The revision id is random (uuid4),
because the neighbours' visual hex pattern walks into the absorbed range.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'd47487369407'
down_revision: Union[str, Sequence[str], None] = 'c1a7f0e2b9d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "task_items"
COLUMN_NAME = "park_reason_captured_at"

CHECK_NAME      = "ck_task_items_parked_requires_captured_at"
CHECK_CONDITION = "status != 'parked' OR park_reason_captured_at IS NOT NULL"


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def _constraint_names( inspector ) -> set:
    return { c[ "name" ] for c in inspector.get_check_constraints( TABLE_NAME ) }


def _backfill_parked_rows( bind ) -> int:
    """
    Stamp the fabricated capture time onto pre-existing parked rows.

    See the module docstring. `updated_ts` is written here because it makes the row read
    not-stale, as the design prescribes for rows parked before this shipped. It is not the
    time the quote was captured.

    Requires:
        - bind is a live connection whose task_items has park_reason_captured_at

    Ensures:
        - touches only rows with `status = 'parked'` and a NULL capture time
        - sets exactly one column, so the raw `UPDATE` cannot bump updated_ts
          (onupdate is ORM-client-side; this never enters the flush path)
        - returns the number of rows stamped (0 on a re-run, because of the NULL guard)
    """
    result = bind.execute(
        sa.text(
            f"UPDATE {TABLE_NAME} "
            f"SET {COLUMN_NAME} = updated_ts "
            f"WHERE status = 'parked' AND {COLUMN_NAME} IS NULL"
        )
    )
    return result.rowcount


def _verify_backfill_equality( bind ) -> None:
    """
    Prove the backfill left every parked row at captured_at == updated_ts exactly.

    The mechanism argument (raw SQL cannot fire an ORM-side onupdate) is a claim; this is its
    receipt, since `captured_at < updated_ts` would be born stale. `IS DISTINCT FROM` rather
    than `!=` makes a NULL capture time a violation, so the check cannot match nothing.

    Requires:
        - bind is a live connection, post-backfill

    Ensures:
        - returns silently iff every parked row satisfies the equality
        - raises RuntimeError naming the violating count otherwise, failing the
          migration rather than shipping born-stale rows
    """
    violations = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {TABLE_NAME} "
            f"WHERE status = 'parked' AND {COLUMN_NAME} IS DISTINCT FROM updated_ts"
        )
    ).scalar()

    if violations:
        raise RuntimeError(
            f"{revision}: {violations} parked row(s) violate "
            f"{COLUMN_NAME} == updated_ts after backfill — those rows are BORN "
            f"STALE (design §3.4). Either the backfill UPDATE bumped updated_ts "
            f"(onupdate fired: this is no longer raw-SQL-only, or a DB trigger "
            f"now exists), or a parked row was left with a NULL capture time."
        )


def upgrade() -> None:
    """
    Add park_reason_captured_at, backfill pre-existing parked rows, add the `CHECK`.

    The order matters. The `CHECK` is created only after the backfill, because a live table
    with parked rows would violate it the moment it is added.

    Ensures:
        - no-op when task_items is absent (fresh DB built from metadata)
        - the column is added only when missing
        - the backfill runs before the `CHECK`, touching only parked rows
        - equality is verified, and the upgrade fails on any violation, before the
          `CHECK` is created
        - the `CHECK` is created only when absent, by name
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, sa.DateTime( timezone=True ), nullable=True ) )

    stamped = _backfill_parked_rows( bind )
    print( f"[{revision}] backfilled {stamped} pre-existing parked row(s) with a FABRICATED capture time (= updated_ts)" )

    _verify_backfill_equality( bind )

    if CHECK_NAME not in _constraint_names( inspector ):
        op.create_check_constraint( CHECK_NAME, TABLE_NAME, CHECK_CONDITION )


def downgrade() -> None:
    """
    Drop the `CHECK` and the park_reason_captured_at column.

    Ensures:
        - no-op when task_items is absent
        - the constraint is dropped before the column it references
        - each drop is guarded, so a partial upgrade downgrades cleanly
        - the backfilled values go with the column; nothing to un-stamp
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    if CHECK_NAME in _constraint_names( inspector ):
        op.drop_constraint( CHECK_NAME, TABLE_NAME, type_="check" )

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
