"""Add task_items.park_reason_captured_at + its parked CHECK constraint

Revision ID: d47487369407
Revises: c1a7f0e2b9d4
Create Date: 2026-07-19

Backs park_reason STALENESS DETECTION (design
src/rnd/v0.1.9/2026.07.19-park-reason-staleness-detection.md §3.1, AC1).

WHAT IT ADDS
------------
1. `park_reason_captured_at` TIMESTAMPTZ NULL — WHEN the `park_reason` quote was
   frozen. `park_reason` is a frozen quote of the row's decisive sentence; amend
   the row afterward and the quote stays syntactically valid while it stops being
   true, and NOTHING GOES RED. Recording the capture instant is what lets
   `task_store_owed.park_reason_is_stale` compare it against `updated_ts` and make
   the divergence VISIBLE.

2. One CHECK, mirroring the two `c1a7f0e2b9d4` added:
       status != 'parked' OR park_reason_captured_at IS NOT NULL
   A third separate constraint rather than a conjunction onto an existing one, so
   a violation names WHICH field is missing.

THE VALUE WRITTEN AT PARK TIME IS THE **POST-WRITE** `updated_ts`
-----------------------------------------------------------------
Not `now()`, and not the PRE-write value. `updated_ts` carries
`onupdate=func.now()`, so the park write itself bumps it:

    now()      -> races the updated_ts stamp; born stale or fresh by microsecond
                  order (non-deterministic)
    pre-write  -> captured_at < updated_ts the instant park commits => EVERY ROW
                  BORN STALE (the trap; the design prescribed this arm in draft)
    post-write -> captured_at == updated_ts at park, and any later amendment
                  bumps updated_ts strictly greater  <-- correct

The invariant is EQUALITY, not merely "not stale": asserting only
`stale == False` also passes for a `now()`-written-after implementation that
leaves an undetectable amendment window.

⚠️ THE BACKFILL VALUE IS **FABRICATED**, NOT MEASURED
------------------------------------------------------
Rows already `parked` when this revision runs have no capture time and no way to
recover one — the quote was frozen at some unrecorded instant before now. This
migration writes `park_reason_captured_at = updated_ts` for exactly those rows.

**That value is FABRICATED.** It does NOT mean "the quote was captured then." It
means: *we cannot know, and this is the value that makes the row read NOT-STALE*,
which is the behavior the design prescribes for rows parked before this shipped
(§7 as amended by Mr. Radio's ruling, 2026-07-19 — the original §7 said "no
backfill", which is unsatisfiable alongside the CHECK on a table with live parked
rows).

It is labelled here in those words on purpose: an unlabelled synthetic timestamp
is indistinguishable from a measured one to every future reader, and that
indistinguishability is this plan's entire subject.

WHY BACKFILL RATHER THAN `CHECK ... NOT VALID`
-----------------------------------------------
`NOT VALID` would exempt the pre-existing rows and keep the original §7 literal,
but the MODEL-level `CheckConstraint` (used by `create_all` on a metadata-built
DB) has no `NOT VALID` equivalent — migration and model would then say different
things about the same constraint. That is a second two-records-of-one-fact, which
is the exact defect class this build exists to fix. Ruled by Mr. Radio: not
paying it.

WHY THE BACKFILL CANNOT BUMP `updated_ts` (and why it is verified anyway)
--------------------------------------------------------------------------
If the backfill UPDATE bumped `updated_ts`, every backfilled row would land
`captured_at < updated_ts` and be BORN STALE — §3.4's trap arriving through the
migration instead of through the write path.

It cannot: `updated_ts`'s `onupdate=func.now()` is ORM-CLIENT-SIDE ONLY, with no
DB trigger (`postgres_models.py`, cold-review note N6), and this backfill is raw
SQL via `op.execute`, which never enters the ORM's flush path. The `SET` list
names one column.

That is the MECHANISM, not the RECEIPT. The source says what the ORM does; the
rows say what they are, and those are different claims. `_verify_backfill_equality`
counts the rows and FAILS the upgrade on any violation.

⚠️ WHAT THE EQUALITY RECEIPT DOES **NOT** PROVE (seat 2's PG probe, 2026-07-19)
-------------------------------------------------------------------------------
Postgres `now()` is `transaction_timestamp()` and is STABLE across a transaction.
So within ONE transaction, all three candidate capture orderings — post-write,
pre-write, and `now()` — produce EXACT equality, and §3.4's born-stale arm cannot
fire at all.

⇒ "0 equality violations on PG" is a real receipt for THIS migration (it shows the
backfill did not bump `updated_ts`, corroborated independently by an unchanged
md5 fingerprint over `id||updated_ts` across the parked set). It is NOT evidence
that a write path implemented the ordering correctly — on this backend the engine
disarms the trap regardless of which value the writer chose. The ordering must be
pinned at the MECHANISM (one captured value written to both columns in one
statement), not sampled at this consequence. Do not read more from a green here
than it proves.

SCOPE: `WHERE status = 'parked'` ONLY. No other row is touched.

IDEMPOTENT + SAFE TO RE-RUN: each step inspects the live schema first (the
auto-migrate startup path may reach this on an already-migrated DB, and the test
DB is created from metadata rather than from migrations). The backfill is
`WHERE ... IS NULL`-guarded, so a re-run writes nothing.

REVISION ID NOTE: `d47487369407` was chosen RANDOMLY (uuid4), NOT by continuing
the visual hex pattern of the neighbouring filenames — that pattern walks
straight into the absorbed range, which is how `a3b4c5d6e7f8` collided with a
real migration. Verified absent from `_ABSORBED_REVISIONS`, from all 15 revisions
in the chain (`ScriptDirectory.walk_revisions`), and from the repo by grep — with
the grep first proven capable of positives against two known-present ids.
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
    Stamp the FABRICATED capture time onto pre-existing parked rows.

    See the module docstring: `updated_ts` is written here NOT because the quote
    was captured then, but because it is the value that makes the row read
    NOT-STALE, which is what the design prescribes for rows parked before this
    shipped.

    Requires:
        - bind is a live connection whose task_items has park_reason_captured_at

    Ensures:
        - touches ONLY rows with status = 'parked' AND a NULL capture time
        - sets exactly one column, so the raw UPDATE cannot bump updated_ts
          (onupdate is ORM-client-side; this never enters the flush path)
        - returns the number of rows stamped (0 on a re-run — the NULL guard)
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
    Prove the backfill left every parked row at captured_at == updated_ts EXACTLY.

    The mechanism argument (raw SQL cannot fire an ORM-side onupdate) is a claim;
    this is its receipt. A row that came out `captured_at < updated_ts` would be
    BORN STALE — the design's §3.4 trap, arriving through the migration.

    `IS DISTINCT FROM` rather than `!=`, so a NULL capture time counts as a
    violation instead of evaluating to NULL and being silently excluded — the
    three-valued-logic arm that would let the check pass by matching nothing.

    Requires:
        - bind is a live connection, post-backfill

    Ensures:
        - returns silently iff EVERY parked row satisfies the equality
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
    Add park_reason_captured_at, backfill pre-existing parked rows, add the CHECK.

    ORDER IS LOAD-BEARING: the CHECK is created only AFTER the backfill, because a
    live table with parked rows would violate it the moment it is added.

    Ensures:
        - no-op when task_items is absent (fresh DB built from metadata)
        - the column is added only when missing
        - the backfill runs before the CHECK, touching only parked rows
        - equality is verified, and the upgrade FAILS on any violation, before the
          CHECK is created
        - the CHECK is created only when absent, by name
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
    Drop the CHECK and the park_reason_captured_at column.

    Ensures:
        - no-op when task_items is absent
        - the constraint is dropped BEFORE the column it references
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
