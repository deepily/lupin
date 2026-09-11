"""Add task_items.request_state / request_move / request_ts + their three CHECKs

Revision ID: 8beada291153
Revises: 9a1c4f27bd30
Create Date: 2026-09-09

Backs rules 3 and 4 of row c9fafb9d — "a manager may REQUEST either move, and a
request defaults to NO". Rick ruled the door on 2026-09-09 by keypress: it is a
PERSISTENT QUEUE he works from a board.

WHY COLUMNS ON task_items AND NOT A TABLE
-----------------------------------------
Mr. Radio's ruling (row 8ed76594 amendment, 2026-09-09): the request RIDES ON THE
TICKET. No `resolves_by`, no `TaskPromotionTicket`, no background resolver. The
accepted cost, recorded rather than argued away: there is NO HISTORY of repeated
requests on a row — a re-file overwrites the last one. That is the shape he chose
knowing it, and a future reader who wants history must get a new ruling, not add a
table quietly.

⚠️ `TaskPromotionTicket` ALREADY EXISTS (postgres_models.py) AND IS DELIBERATELY NOT
REUSED HERE. It carries the synchronous promotion ASK, which the same amendment
rules out as this door's delivery path. Two mechanisms, similar nouns; do not merge
them on the strength of the names.

WHAT IT ADDS
------------
1. `request_state` VARCHAR NULL   — pending | approved | denied. NULL means NO
   REQUEST, which is the state almost every row is in forever.
2. `request_move`  VARCHAR NULL   — the move being asked for, so
   `task_request_lifecycle.badge_for_move` can classify it into a badge.
3. `request_ts`    TIMESTAMPTZ NULL — when the request was filed.

THREE COLUMNS RATHER THAN ONE JSON BLOB, AND THE REASON IS A QUERY
------------------------------------------------------------------
`badge_counts` has to COUNT pending requests per badge on every board render. A
predicate that must open a blob to filter cannot use an index; three scalar columns
can. The shape follows the read, not the writer's convenience.

NO BACKFILL, AND THIS IS A MEASURED CLAIM RATHER THAN A HOPE
-------------------------------------------------------------
Every CHECK below is written as `request_state IS NULL OR ...`, so a row with no
request satisfies all three VACUOUSLY. Every pre-existing row has a NULL
`request_state` the instant the column is added, because that is what adding a
nullable column does. ⇒ Zero rows can violate, so nothing is stamped and no
fabricated value enters the table.

That is worth saying explicitly next to `d47487369407`, which DID have to fabricate
a `park_reason_captured_at` for live parked rows and labelled it as fabricated. The
difference is not care, it is shape: that CHECK keyed off an EXISTING status value
that rows already carried, this one keys off a column that starts empty.

THREE SEPARATE CHECKS RATHER THAN ONE CONJUNCTION
--------------------------------------------------
Same convention as the `parked` pair already in this table: a violation must name
WHICH field is missing. One conjunction would report "the request constraint failed"
and leave the reader to bisect three fields by hand.

⚠️ THE CHECK LITERALS MUST MATCH `postgres_models.py` VERBATIM.
`src/tests/unit/test_task_request_columns_migration.py` asserts it verbatim, and kills a
ONE-SPACE drift by name (measured). Named rather than alluded to: the parity guards here
are PER-MIGRATION, so a new revision inherits none of them and a vague "a parity test
covers this" is exactly the reassurance that stops the next reader checking. It matters
because a model/migration divergence is a CHECK that silently means
two different things on a fresh-from-metadata DB versus a migrated one — the
two-records-of-one-fact defect this repo has already paid for.

WHAT THESE CONSTRAINTS DO NOT DO
---------------------------------
They enforce SHAPE, never AUTHORITY. Nothing here can tell Rick's verdict from a
manager typing one — the same seam `task_request_lifecycle.refusal_for_verdict`
names in its own docstring, and for the same reason: the fact needed (a validated
account) does not exist at this layer. Authority is decided in the router, where
`approver_persona_for_account` can be asked. A future reader who moves that check
down here to tidy it up re-opens the hole.

IDEMPOTENT + SAFE TO RE-RUN: every step inspects the live schema first, and that is
not a nicety — `auto_migrate.run_migrations_to_head` runs `upgrade head` on EVERY
process start, so meeting an already-migrated DB is the NORMAL case. A revision that
raised "column already exists" would take the server down on its second boot.

⚠️ POSTGRES ONLY FOR THE CHECK HALF, AND THIS WAS MEASURED RATHER THAN ASSUMED. Driven
against a scratch SQLite DB, `upgrade()` adds all three columns and then RAISES at
`op.create_check_constraint` — "No support for ALTER of constraints in SQLite dialect".
So on SQLite it half-finishes: columns in, constraints not.

That is NOT novel here — `d47487369407` calls the same op — and it does not bite in
practice, because production is Postgres and a fresh test DB is built from
`Base.metadata.create_all` + `stamp head` rather than by running migrations. But the
plain sentence "idempotent + safe to re-run" was TRUE ONLY OF POSTGRES while reading as
unconditional, so it is qualified here rather than left to be discovered by whoever
first points a non-Postgres backend at this chain.
`src/tests/unit/test_task_request_columns_migration.py` drives the real upgrade and
proves the COLUMN half plus the no-backfill claim on actual rows; the CHECK half stays
proven structurally, which is a named gap rather than a silent one.

REVISION ID NOTE: `8beada291153` was minted with uuid4 rather than by continuing the
visual hex pattern of neighbouring filenames — that pattern walks into the absorbed
range, which is how `a3b4c5d6e7f8` collided with a real migration. Verified absent
from the 8 `_ABSORBED_REVISIONS`, absent from all 23 revisions in the chain, and
absent from `src/` by grep — with the grep FIRST proven capable of a positive
(searching the known head `9a1c4f27bd30` returned 7 files).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '8beada291153'
down_revision: Union[str, Sequence[str], None] = '9a1c4f27bd30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "task_items"

# The column inventory, used by the DOWNGRADE and by the tests. The UPGRADE deliberately
# does NOT loop over this — see the note in `upgrade()`: a loop variable is invisible to
# the static drift oracle, and being seen by it matters more than avoiding a repetition.
NEW_COLUMNS = (
    ( "request_state", sa.String( 32 ) ),
    ( "request_move",  sa.String( 32 ) ),
    ( "request_ts",    sa.DateTime( timezone=True ) ),
)

# ⚠️ THESE STRINGS ARE MIRRORED VERBATIM IN postgres_models.py. A parity test compares
# them; edit one and you must edit the other.
CHECKS = (
    ( "ck_task_items_request_state_is_ruled",
      "request_state IS NULL OR request_state IN ('pending', 'approved', 'denied')" ),
    ( "ck_task_items_request_requires_move",
      "request_state IS NULL OR request_move IS NOT NULL" ),
    ( "ck_task_items_request_requires_ts",
      "request_state IS NULL OR request_ts IS NOT NULL" ),
)


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def _constraint_names( inspector ) -> set:
    return { c[ "name" ] for c in inspector.get_check_constraints( TABLE_NAME ) }


def _verify_nothing_violates( bind ) -> None:
    """
    Prove no row violates the request CHECKs before they are created.

    The module docstring ARGUES that no backfill is needed — a freshly added nullable
    column is NULL everywhere, so every `request_state IS NULL OR ...` clause holds
    vacuously. That is the mechanism; this is its receipt, and they are different
    claims. `d47487369407` earned the same distinction the hard way.

    Cheap by construction: it counts rows whose `request_state` is already non-NULL,
    which on a first run is zero and on a re-run is however many real requests exist —
    and on a re-run those have been written THROUGH the constraints, so they cannot
    violate. Either way a non-zero count here is not itself a failure; it is a number
    worth printing, because a silent zero and a silent hundred read identically.

    Requires:
        - bind is a live connection whose task_items has the three request columns

    Ensures:
        - returns silently iff no row breaks any of the three predicates
        - raises RuntimeError naming the violating count otherwise, failing the
          upgrade rather than creating a constraint the table already breaks
        - never guesses: it asks the rows, not the schema
    """
    existing = bind.execute(
        sa.text( f"SELECT count(*) FROM {TABLE_NAME} WHERE request_state IS NOT NULL" )
    ).scalar()
    print( f"[{revision}] rows carrying a request before the CHECKs are added: {existing}" )

    violations = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {TABLE_NAME} WHERE request_state IS NOT NULL AND ("
            f"  request_state NOT IN ('pending', 'approved', 'denied')"
            f"  OR request_move IS NULL"
            f"  OR request_ts IS NULL"
            f")"
        )
    ).scalar()

    if violations:
        raise RuntimeError(
            f"{revision}: {violations} row(s) in {TABLE_NAME} carry a request that breaks "
            f"one of the three predicates — an unruled request_state, or a request with no "
            f"move or no timestamp. Creating the CHECKs would fail anyway; this says WHICH "
            f"shape is wrong instead of leaving you to read a constraint violation. Nothing "
            f"was altered."
        )


def upgrade() -> None:
    """
    Add the three request columns, verify no row breaks the rules, add the three CHECKs.

    ORDER IS LOAD-BEARING, for the same reason as `d47487369407`: a CHECK created
    against a table that already violates it fails the migration with a message about
    a constraint rather than about the data.

    Ensures:
        - no-op when task_items is absent (a fresh DB built from metadata)
        - each column is added only when missing, so a partial upgrade completes
        - the verification runs AFTER the columns exist and BEFORE any CHECK
        - each CHECK is created only when absent, by name
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    # 🔴 THREE EXPLICIT CALLS WITH LITERAL NAMES, AND THE LOOP THAT WAS HERE WAS WRONG.
    # A `for name, column_type in NEW_COLUMNS` loop is tidier and DEFEATS
    # `test_model_migration_drift.py`, which statically parses every migration in the chain
    # to find which columns it adds — it cannot resolve a loop variable and refuses with
    # "sa.Column name is not a literal or module-level constant". That oracle exists to
    # catch a mapped column that NO migration ever adds, which is worth far more than the
    # loop's tidiness. It caught this within a minute of the file being written.
    # ⇒ `NEW_COLUMNS` survives for the downgrade and for the tests; the upgrade names each
    #   column where a static reader can see it.
    present = _column_names( inspector )
    if "request_state" not in present:
        op.add_column( TABLE_NAME, sa.Column( "request_state", sa.String( 32 ), nullable=True ) )
    if "request_move" not in present:
        op.add_column( TABLE_NAME, sa.Column( "request_move", sa.String( 32 ), nullable=True ) )
    if "request_ts" not in present:
        op.add_column( TABLE_NAME, sa.Column( "request_ts", sa.DateTime( timezone=True ), nullable=True ) )

    _verify_nothing_violates( bind )

    # Re-inspect: the constraint list is read from a connection whose schema just
    # changed, and a stale inspector would report the pre-upgrade set.
    existing_checks = _constraint_names( inspect( bind ) )
    for name, condition in CHECKS:
        if name not in existing_checks:
            op.create_check_constraint( name, TABLE_NAME, condition )


def downgrade() -> None:
    """
    Drop the three CHECKs and the three request columns.

    Ensures:
        - no-op when task_items is absent
        - every constraint is dropped BEFORE the columns it references
        - each drop is guarded, so a partial upgrade downgrades cleanly
        - ⚠️ any live request goes with the columns. There is no other copy — the
          request rides on the ticket by ruling, so downgrading DISCARDS pending
          requests rather than parking them somewhere. Said plainly because a
          downgrade that loses a human's unanswered question should be a decision,
          not a surprise.
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    existing_checks = _constraint_names( inspector )
    for name, _ in CHECKS:
        if name in existing_checks:
            op.drop_constraint( name, TABLE_NAME, type_="check" )

    present = _column_names( inspector )
    for name, _ in NEW_COLUMNS:
        if name in present:
            op.drop_column( TABLE_NAME, name )
