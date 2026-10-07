"""Add task_items.request_state / request_move / request_ts + their three `CHECK`s

Revision ID: 8beada291153
Revises: 9a1c4f27bd30

Backs the rule that a manager may request either move, and a request defaults to no.

Columns on task_items, not a table: the request rides on the ticket, with no `resolves_by`, no `TaskPromotionTicket` and no
background resolver. The accepted cost is no history of repeated requests, since a re-file overwrites the last. History needs a
new ruling, not a quietly added table. `TaskPromotionTicket` exists but carries the synchronous ask, so it is not reused.

Columns: `request_state` VARCHAR NULL holds pending, approved or denied. NULL means no
request. `request_move` VARCHAR NULL is the move asked for, which
`task_request_lifecycle.badge_for_move` classifies into a badge. `request_ts` TIMESTAMPTZ NULL
is when it was filed. They are scalar columns, not a JSON blob. `badge_counts` counts
pending requests per badge on every board render, and a predicate that must open a blob
cannot use an index.

No backfill. Every `CHECK` reads `request_state IS NULL OR ...`, so a row with no request satisfies all three vacuously. Every
existing row has a NULL `request_state` the instant the column is added, so no row can violate and no fabricated value enters
the table.

There are three separate `CHECK`s, not one conjunction, so a violation names the missing
field. Their literals must match `postgres_models.py` verbatim, and
`src/tests/unit/test_task_request_columns_migration.py` asserts it. Parity guards are per
migration, so a new revision inherits none. A divergence would make a `CHECK` mean two
things on a metadata-built database and a migrated one.

The constraints enforce shape, never authority. No validated account exists at this layer,
so nothing here can tell Rick's verdict from a manager typing one. The router decides
authority through `approver_persona_for_account`. Moving that check down re-opens the hole.
`task_request_lifecycle.refusal_for_verdict` names the same authority seam in its own docstring.

The migration is idempotent: every step inspects the live schema first, because `auto_migrate.run_migrations_to_head` runs
`upgrade head` on every process start. The `CHECK` half is PostgreSQL only: on SQLite `upgrade()` adds the columns, then
raises at `op.create_check_constraint`. That half-finish does not bite in practice. Production is Postgres. A fresh test
database is built from `Base.metadata.create_all` plus `stamp head`, not by running migrations. `d47487369407` calls the
same op. The test drives the real upgrade for the columns and the no-backfill claim; the `CHECK` half is proven structurally
only. The revision id is random, because the neighbours' hex pattern walks into the absorbed range.
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
    Prove no row violates the request `CHECK`s before they are created.

    The module docstring argues no backfill is needed: a new nullable column is NULL everywhere,
    so every `request_state IS NULL OR ...` clause holds vacuously. This is the receipt. It
    counts non-NULL `request_state` rows: none on a first run, real requests on a re-run.

    Requires:
        - bind is a live connection whose task_items has the three request columns

    Ensures:
        - returns silently iff no row breaks any of the three predicates
        - raises RuntimeError naming the violating count otherwise, failing the
          upgrade rather than creating a constraint the table already breaks
        - never guesses: it asks the rows, not the schema
        - on a re-run existing requests were written through the constraints, so they cannot violate
        - a non-zero count is not itself a failure; it is printed because a silent zero and a silent hundred read identically
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
    Add the three request columns, verify no row breaks the rules, add the three `CHECK`s.

    The order matters, as in `d47487369407`. A `CHECK` created against a table that already
    violates it fails the migration with a message about a constraint, not about the data.

    Ensures:
        - no-op when task_items is absent (a fresh DB built from metadata)
        - each column is added only when missing, so a partial upgrade completes
        - the verification runs after the columns exist and before any `CHECK`
        - each `CHECK` is created only when absent, by name
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
    Drop the three `CHECK`s and the three request columns.

    Ensures:
        - no-op when task_items is absent
        - every constraint is dropped before the columns it references
        - each drop is guarded, so a partial upgrade downgrades cleanly
        - any live request goes with the columns. There is no other copy: the request rides
          on the ticket by ruling, so downgrading discards pending requests rather than
          parking them. A downgrade that loses a human's unanswered question should be a
          decision, not a surprise.
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
