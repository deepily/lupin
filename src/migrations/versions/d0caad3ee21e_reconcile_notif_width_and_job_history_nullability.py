"""Reconcile notifications.progress_group_id width + job_history.is_cache_hit nullability

Revision ID: d0caad3ee21e
Revises: d47487369407
Create Date: 2026-07-19

Closes `692d1596` — lupin_db_dev diverged from its own alembic stamp.

WHAT DIVERGED, AND HOW IT WAS FOUND
------------------------------------
`compare_metadata( MigrationContext, Base.metadata )` run against both live
databases at the SAME stamp (`d47487369407`):

    lupin_db_test -> 0 diff entries
    lupin_db_dev  -> 27 diff entries

The models and the migration chain were in sync; dev had diverged from what its
own chain produces. Two of the 27 are column-shape defects, and they are what this
revision fixes:

    notifications.progress_group_id   dev VARCHAR(12)   model/test VARCHAR(24)
    job_history.is_cache_hit          dev NULLable      model/test NOT NULL

The remaining 25 are index-level and are deliberately OUT OF SCOPE — a model-side
duplicate index declaration on `job_history` plus an `idx_*`/`ix_*` naming
divergence. Different substrate, different fix, filed as its own row.

⚠️ THE MECHANISM — A GUARD THAT REPORTS SUCCESS FOR THE ONE CASE IT CANNOT SEE
-------------------------------------------------------------------------------
`e5f6a7b8c9d0` lines 213-214 add the column like this:

    if "progress_group_id" not in notif_cols:
        op.add_column( 'notifications', sa.Column( 'progress_group_id', sa.String( 24 ), nullable=True ) )

Dev already carried a `VARCHAR(12)` from a pre-alembic path. The guard asked
whether the column EXISTED, never whether it was the RIGHT SHAPE, so it skipped —
and the migration stamped anyway. Dev has read "at head" ever since while being
two columns wrong.

**A presence-only guard is indistinguishable from success for exactly the case it
exists to catch.** That is now a standing crew rule.

THIS REVISION CARRIES NO GUARDS AT ALL — DELIBERATELY
------------------------------------------------------
An earlier draft guarded each ALTER on `table_name in inspector.get_table_names()`.
That guard was defensible under the crew test — the banned pattern reads a PROXY
for the property it repairs (column exists => assume the shape is right), whereas
a table-exists check reads a PRECONDITION whose decision input is INDEPENDENT of
the property being repaired, and independence is the test rather than coarseness.

It was dropped anyway, because it was still BLIND in one case: a table absent from
a database where it SHOULD exist would skip the ALTER *and* skip the verification,
passing both silently. The only argument for keeping it was consistency with
`d47487369407` and `e5f6a7b8c9d0` — and one of those is the file that carried the
defect. Consistency with a defective file is not a safety property; it is how the
defect propagates.

⇒ Every statement below is UNCONDITIONAL. A missing table raises loudly. What is
verified afterwards is the resulting SHAPE, never whether a statement ran.

LIVE RISK THIS RETIRES
-----------------------
`progress_group_id` carries two documented formats (`postgres_models.py` L536):
`pg-{hex}` and `pr-{hex}-{batch}`. `pg-` + 8 hex = 11 characters, so it fit in
`VARCHAR(12)` by ONE character — which is why nobody had hit it. Measured on dev
immediately before this revision was written: **185,805 rows, max observed length
12** — already sitting exactly on the ceiling. Postgres `varchar(n)` RAISES on
overflow rather than truncating, so the `pr-` format would have produced a
write-time 500.

IDEMPOTENCY
-----------
None is needed and none is added. Both statements are naturally re-runnable at the
SQL level: widening a column already `VARCHAR(24)` and setting `NOT NULL` on one
already `NOT NULL` are no-op successes in Postgres. An unconditional ALTER that
errors loudly on an unexpected state is safer than a guard that skips quietly.

REVISION ID: `d0caad3ee21e` chosen randomly (uuid4), NOT by continuing the visual
hex pattern of neighbouring filenames — that pattern walks into the absorbed
range, which is how `a3b4c5d6e7f8` once collided with a real migration. Verified
absent from all 16 revisions in the chain, from the 8 `_ABSORBED_REVISIONS`, and
from the repo by grep — with the grep first proven capable of positives (23 hits
for the known-present head).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0caad3ee21e'
down_revision: Union[str, Sequence[str], None] = 'd47487369407'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NOTIF_TABLE  = "notifications"
NOTIF_COLUMN = "progress_group_id"
NOTIF_WIDTH  = 24
LEGACY_WIDTH = 12

JOB_TABLE  = "job_history"
JOB_COLUMN = "is_cache_hit"


def _column_shape( bind, table_name, column_name ):
    """
    Read a column's ACTUAL width and nullability from the live catalog.

    Requires:
        - bind is a live connection

    Ensures:
        - returns ( character_maximum_length | None, is_nullable_bool )
        - returns ( None, None ) when the column does not exist, so a caller can
          distinguish "absent" from "present but wrong"

    Returns:
        tuple
    """
    row = bind.execute(
        sa.text(
            "SELECT character_maximum_length, is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        { "t": table_name, "c": column_name }
    ).fetchone()

    if row is None:
        return ( None, None )
    return ( row[ 0 ], row[ 1 ] == "YES" )


def _backfill_null_cache_hits( bind ) -> int:
    """
    Set any NULL is_cache_hit to FALSE so SET NOT NULL can succeed.

    FALSE is the column's own server default, so this asserts nothing new about
    those rows — it writes the value they would have had.

    Requires:
        - bind is a live connection whose job_history exists

    Ensures:
        - touches ONLY rows where is_cache_hit IS NULL
        - returns the number of rows written (0 when there are none)
    """
    result = bind.execute(
        sa.text( f"UPDATE {JOB_TABLE} SET {JOB_COLUMN} = FALSE WHERE {JOB_COLUMN} IS NULL" )
    )
    return result.rowcount


def _verify_shapes( bind ) -> None:
    """
    Prove the SHAPES are correct — not merely that the statements ran.

    This is the receipt `e5f6a7b8c9d0` never had. It confirmed a column EXISTED
    and stamped; it never asked what shape that column was. Checking the OUTCOME
    rather than the ACTION is the whole correction.

    An ABSENT column is a violation here, not a skip. That is the difference the
    dropped table-exists guard would have hidden.

    Requires:
        - bind is a live connection, post-ALTER

    Ensures:
        - returns silently iff progress_group_id is VARCHAR(24) AND is_cache_hit
          is NOT NULL, both read back from information_schema
        - raises RuntimeError naming every offending column and its ACTUAL shape
          otherwise, FAILING the migration rather than stamping a wrong schema
    """
    problems = []

    width, _ = _column_shape( bind, NOTIF_TABLE, NOTIF_COLUMN )
    if width != NOTIF_WIDTH:
        actual = "ABSENT" if width is None else f"VARCHAR({width})"
        problems.append( f"{NOTIF_TABLE}.{NOTIF_COLUMN} is {actual}, expected VARCHAR({NOTIF_WIDTH})" )

    _, nullable = _column_shape( bind, JOB_TABLE, JOB_COLUMN )
    if nullable is not False:
        actual = "ABSENT" if nullable is None else f"nullable={nullable}"
        problems.append( f"{JOB_TABLE}.{JOB_COLUMN} is {actual}, expected NOT NULL" )

    if problems:
        raise RuntimeError(
            f"{revision}: schema SHAPE verification FAILED after the ALTERs — "
            + "; ".join( problems )
            + ". This migration has NOT produced a correct schema. Do not read a "
              "stamped revision as evidence of shape — that assumption IS 692d1596."
        )


def upgrade() -> None:
    """
    Widen progress_group_id to VARCHAR(24) and make is_cache_hit NOT NULL.

    Ensures:
        - both ALTERs are UNCONDITIONAL; a missing table raises loudly rather
          than being skipped
        - NULL is_cache_hit rows are backfilled to FALSE BEFORE SET NOT NULL, so
          the constraint cannot fail on live data
        - the resulting SHAPES are verified from the catalog, and the upgrade
          FAILS rather than stamping a schema that is still wrong
    """
    bind = op.get_bind()

    op.alter_column(
        NOTIF_TABLE, NOTIF_COLUMN,
        existing_type     = sa.String( LEGACY_WIDTH ),
        type_             = sa.String( NOTIF_WIDTH ),
        existing_nullable = True
    )

    backfilled = _backfill_null_cache_hits( bind )
    print( f"[{revision}] backfilled {backfilled} NULL {JOB_TABLE}.{JOB_COLUMN} row(s) to FALSE" )

    op.alter_column(
        JOB_TABLE, JOB_COLUMN,
        existing_type           = sa.Boolean(),
        nullable                = False,
        existing_server_default = sa.text( "false" )
    )

    _verify_shapes( bind )


def downgrade() -> None:
    """
    Restore the pre-reconciliation shapes.

    ⚠️ Narrowing VARCHAR(24) back to VARCHAR(12) DESTROYS values longer than 12
    characters. This REFUSES rather than truncating: it counts the offending rows
    first and raises, because a downgrade that silently shortens live ids is a
    worse outcome than a failed downgrade.

    Ensures:
        - is_cache_hit returns to nullable; the backfilled FALSE values remain,
          being indistinguishable from genuine FALSE and not recoverable
        - the width narrowing is REFUSED, loudly, when any value exceeds 12 chars
    """
    bind = op.get_bind()

    op.alter_column(
        JOB_TABLE, JOB_COLUMN,
        existing_type           = sa.Boolean(),
        nullable                = True,
        existing_server_default = sa.text( "false" )
    )

    too_long = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {NOTIF_TABLE} "
            f"WHERE length( {NOTIF_COLUMN} ) > {LEGACY_WIDTH}"
        )
    ).scalar()

    if too_long:
        raise RuntimeError(
            f"{revision}: refusing to downgrade {NOTIF_TABLE}.{NOTIF_COLUMN} to "
            f"VARCHAR({LEGACY_WIDTH}) — {too_long} row(s) hold longer values and "
            f"would be TRUNCATED. Shorten or remove those rows first if this "
            f"downgrade is genuinely intended."
        )

    op.alter_column(
        NOTIF_TABLE, NOTIF_COLUMN,
        existing_type     = sa.String( NOTIF_WIDTH ),
        type_             = sa.String( LEGACY_WIDTH ),
        existing_nullable = True
    )
