"""Add task_items.park_reason + the two parked-status CHECK constraints

Revision ID: c1a7f0e2b9d4
Revises: f2a3b4c5d6e7
Create Date: 2026-07-19

Backs the `parked` status (design
src/rnd/v0.1.9/2026.07.19-parked-status-board-hygiene.md, store record
954428b3, gate 522f4815 Rick-approved).

WHAT IT ADDS
------------
1. `park_reason` TEXT NULL — the row's own decisive sentence, quoted. A real
   column rather than the transition `reason`, which lands only on the
   append-only TaskEvent trail: a parked row is hidden by default, so surfacing
   one to read WHY would cost an event-trail fetch per row, and the terse
   projection (the token-efficient path every board glance uses) could not carry
   it at all.

2. Two CHECK constraints mirroring `ck_task_items_blocked_requires_chase_ts`:
       status != 'parked' OR next_chase_ts IS NOT NULL
       status != 'parked' OR park_reason   IS NOT NULL
   TWO constraints rather than one conjunction, so a violation names WHICH field
   is missing. They are what give the rejection tests teeth BELOW Pydantic: a
   hand-written INSERT or a future non-ORM writer cannot create a park that never
   expires, or a park with no stated reason.

WHY next_chase_ts IS REUSED AND NOT DUPLICATED
----------------------------------------------
Rick overruled a proposed `unpark_when` field: parking "doesn't need an
unpack-when field, it needs a chase, which already exists." `next_chase_ts` is
already the chase mechanism for `blocked` — required by validate_transition (I3,
"no 'pending X' graves") and enforced by the CHECK this migration mirrors. A
second date field would have been a fresh source of the exact reader-divergence
this whole change exists to kill.

Expiry is computed at READ time (cosa.rest.task_store_owed) and never written
back, so NO column records it and no daemon maintains it: a parked row whose
chase has passed simply stops being parked. An unbounded hold is therefore
structurally unrepresentable — any timestamp eventually passes.

NO DATA RE-STAMP
----------------
`parked` does not exist before this revision, so no row can be in that status and
no backfill is possible or needed. The CHECKs are vacuously true over every
existing row, so adding them cannot fail on live data.

IDEMPOTENT + SAFE TO RE-RUN: each step inspects the live schema first (the
auto-migrate startup path may reach this on an already-migrated DB, and the test
DB is created from metadata rather than from migrations).

REVISION ID NOTE: this was first authored as `a3b4c5d6e7f8`, picked by
pattern-continuing the hex sequence of the neighbouring filenames. That id was
NOT free — it belonged to a real, DIFFERENT migration,
`expand_job_id_column_to_64_chars`, since absorbed into the baseline script (its
.pyc is still sitting in versions/__pycache__). Reusing it would have put two
distinct migrations under one revision id, making the chain ambiguous to anyone
reading history or bisecting it.

`test_alembic_baseline_chain.test_absorbed_revisions_are_gone` caught it. Renamed
to `c1a7f0e2b9d4`, verified absent from every script under versions/.

⇒ When picking a revision id, do NOT continue the visual hex pattern of the
neighbouring filenames — that pattern walks straight into the absorbed range.
Check `_ABSORBED_REVISIONS` in the baseline-chain test AND the live scripts first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'c1a7f0e2b9d4'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "task_items"
COLUMN_NAME = "park_reason"

CHECK_CONSTRAINTS = (
    ( "ck_task_items_parked_requires_chase_ts", "status != 'parked' OR next_chase_ts IS NOT NULL" ),
    ( "ck_task_items_parked_requires_reason",   "status != 'parked' OR park_reason   IS NOT NULL" ),
)


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def _constraint_names( inspector ) -> set:
    return { c[ "name" ] for c in inspector.get_check_constraints( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add the park_reason column and both parked CHECK constraints.

    Ensures:
        - no-op when task_items is absent (fresh DB built from metadata)
        - the column is added only when missing
        - each CHECK is created only when absent, by name
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, sa.Text(), nullable=True ) )

    existing = _constraint_names( inspector )
    for name, condition in CHECK_CONSTRAINTS:
        if name not in existing:
            op.create_check_constraint( name, TABLE_NAME, condition )


def downgrade() -> None:
    """
    Drop both parked CHECK constraints and the park_reason column.

    Ensures:
        - no-op when task_items is absent
        - constraints are dropped BEFORE the column they reference
        - each drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    existing = _constraint_names( inspector )
    for name, _condition in CHECK_CONSTRAINTS:
        if name in existing:
            op.drop_constraint( name, TABLE_NAME, type_="check" )

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
