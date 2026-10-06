"""Add task_promotion_tickets.answer_by + its ordering `CHECK`

Revision ID: 525a4ad4067a
Revises: 8beada291153
Create Date: 2026-09-10

What it adds:
1. `answer_by` TIMESTAMPTZ NULL — when the answer window closes: `requested_at` plus
   the ask timeout. A ticket already carried `resolves_by`, the stall deadline (ask
   timeout + notification grace + apply margin, 480 s by default). Nothing said
   which of the two was the 120 s answer window, and that misled a relay.
2. `CHECK answer_by IS NULL OR answer_by <= resolves_by` — the schema itself says
   which of the two comes first.

No backfill: a pre-existing ticket keeps `answer_by` NULL. Its window
was the ask timeout in force when it was minted, and that number was never stored.
Computing it from today's timeout would record a guess as a fact. That is the same
re-derivation `resolves_by_for` forbids for `resolves_by`. NULL means "not
recorded", which is true. Every `CHECK` clause starts with `answer_by IS NULL OR`,
so those rows satisfy it vacuously.

The `CHECK` literal must match `postgres_models.TaskPromotionTicket` verbatim.
`src/tests/unit/test_task_promotion_ticket_answer_by_migration.py` asserts it. The
parity guards in this tree are per-migration, so this revision inherits none from
8d404f635e84.

Idempotent, and the column and the `CHECK` are guarded separately.
`auto_migrate.run_migrations_to_head` runs `upgrade head` on every process start,
so an already-migrated database is the normal case. A database built by
`create_all` from a model with the column but not the `CHECK` would be skipped
whole by "column exists, return". That leaves it unconstrained, so each step checks
for its own object.

Postgres only for the `CHECK` half, as for 8beada291153: SQLite cannot
`ALTER TABLE ADD CONSTRAINT`. A fresh test database is built from metadata, not by
this DDL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '525a4ad4067a'
down_revision: Union[str, Sequence[str], None] = '8beada291153'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "task_promotion_tickets"
COLUMN_NAME = "answer_by"

# ⚠️ MIRRORED VERBATIM IN postgres_models.py. A parity test compares them.
CHECK_ANSWER_BY_NAME      = "ck_task_promotion_tickets_answer_by_before_resolves_by"
CHECK_ANSWER_BY_CONDITION = "answer_by IS NULL OR answer_by <= resolves_by"


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def _check_names( inspector ) -> set:
    return { c[ "name" ] for c in inspector.get_check_constraints( TABLE_NAME ) }


def _count_violations( bind ) -> int:
    """
    Rows that would break the `CHECK`, counted before it is created.

    Requires:
        - bind is a live connection whose task_promotion_tickets has `answer_by`

    Ensures:
        - returns the count of rows with answer_by later than resolves_by
        - prints the count of rows carrying answer_by at all, so a silent zero and a
          silent hundred do not read the same
    """
    carrying = bind.execute(
        sa.text( f"SELECT count(*) FROM {TABLE_NAME} WHERE {COLUMN_NAME} IS NOT NULL" )
    ).scalar()
    print( f"[{revision}] tickets carrying answer_by before the CHECK is added: {carrying}" )
    return bind.execute(
        sa.text( f"SELECT count(*) FROM {TABLE_NAME} WHERE NOT ( {CHECK_ANSWER_BY_CONDITION} )" )
    ).scalar()


def upgrade() -> None:
    """
    Add `answer_by`, verify nothing violates, add the `CHECK`.

    Ensures:
        - no-op when the table is absent (a fresh DB built from metadata)
        - the column is added only when missing
        - the `CHECK` is created only when absent, by name, independently of the column
        - raises RuntimeError, altering nothing further, when a row already breaks the
          `CHECK` — a message about the data rather than about a constraint
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( "answer_by", sa.DateTime( timezone=True ), nullable=True ) )

    # Re-inspect: the schema just changed under this connection.
    if CHECK_ANSWER_BY_NAME not in _check_names( inspect( bind ) ):
        violations = _count_violations( bind )
        if violations:
            raise RuntimeError(
                f"{revision}: {violations} ticket(s) in {TABLE_NAME} have answer_by later "
                f"than resolves_by. The answer window cannot close after the stall deadline; "
                f"fix those rows first. The CHECK was not created."
            )
        op.create_check_constraint( CHECK_ANSWER_BY_NAME, TABLE_NAME, CHECK_ANSWER_BY_CONDITION )


def downgrade() -> None:
    """
    Drop the `CHECK`, then the column.

    Ensures:
        - no-op when the table is absent
        - the constraint is dropped before the column it references
        - each drop is guarded, so a partial upgrade downgrades cleanly
        - every stored answer_by goes with the column; there is no other copy
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    if CHECK_ANSWER_BY_NAME in _check_names( inspector ):
        op.drop_constraint( CHECK_ANSWER_BY_NAME, TABLE_NAME, type_="check" )

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
