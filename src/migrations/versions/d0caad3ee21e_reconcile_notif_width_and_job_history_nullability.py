"""Reconcile notifications.progress_group_id width + job_history.is_cache_hit nullability

Revision ID: d0caad3ee21e
Revises: d47487369407

Fixes `lupin_db_dev`, which diverged from its own alembic stamp. `compare_metadata`
against both live databases at the same stamp (`d47487369407`) gave 0 diff entries
on the test database and 27 on dev. The models and the migration chain agree, but
dev diverged from what its own chain produces. Two diffs are column shapes:

    `notifications.progress_group_id`  dev VARCHAR(12)  model and test VARCHAR(24)
    `job_history.is_cache_hit`         dev nullable     model and test `NOT NULL`

The other 25 are index-level and out of scope: a model-side duplicate index
declaration on `job_history` and an `idx_*`/`ix_*` naming divergence.

The mechanism was a guard that reports success for the one case it cannot see.
`e5f6a7b8c9d0` adds the column only if `"progress_group_id" not in notif_cols`.
Dev already carried a VARCHAR(12) from a pre-alembic path. The guard asked whether
the column existed, never whether it had the right shape, so it skipped and the
migration stamped anyway. A presence-only guard is indistinguishable from success
for the very case it exists to catch.

This revision carries no guards at all. A table-exists guard is independent of the
property being repaired, but it is still blind in one case. A table absent where
it should exist would skip the `ALTER` and the verification, passing both silently.
Consistency with `d47487369407` and `e5f6a7b8c9d0` is no reason to keep it, because
one of them carried the defect. Every statement is unconditional, so a missing
table raises loudly. What is verified afterwards is the resulting shape.

Live risk retired: `progress_group_id` carries two formats, `pg-{hex}` and
`pr-{hex}-{batch}`. `pg-` plus 8 hex is 11 characters, so it fit VARCHAR(12) by one
character. Postgres `varchar(n)` raises on overflow instead of truncating, so the
`pr-` format would have produced a write-time 500.

Idempotency is not needed: both statements are no-op successes when re-run, and an
unconditional `ALTER` that errors loudly beats a guard that skips quietly.
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
    Read a column's actual width and nullability from the live catalog.

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
    Set any NULL is_cache_hit to `FALSE` so `SET NOT NULL` can succeed.

    `FALSE` is the column's own server default, so this asserts nothing new about
    those rows — it writes the value they would have had.

    Requires:
        - bind is a live connection whose job_history exists

    Ensures:
        - touches only rows where is_cache_hit `IS NULL`
        - returns the number of rows written (0 when there are none)
    """
    result = bind.execute(
        sa.text( f"UPDATE {JOB_TABLE} SET {JOB_COLUMN} = FALSE WHERE {JOB_COLUMN} IS NULL" )
    )
    return result.rowcount


def _verify_shapes( bind ) -> None:
    """
    Prove the shapes are correct, not merely that the statements ran.

    This is the receipt `e5f6a7b8c9d0` never had: it confirmed a column existed and
    stamped, without asking its shape. Checking the outcome rather than the action
    is the whole correction. An absent column is a violation here, not a skip.

    Requires:
        - bind is a live connection, post-ALTER

    Ensures:
        - returns silently iff progress_group_id is VARCHAR(24) and is_cache_hit
          is `NOT NULL`, both read back from information_schema
        - raises RuntimeError naming every offending column and its actual shape
          otherwise, failing the migration rather than stamping a wrong schema
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
    Widen progress_group_id to VARCHAR(24) and make is_cache_hit `NOT NULL`.

    Ensures:
        - both `ALTER`s are unconditional; a missing table raises loudly rather
          than being skipped
        - NULL is_cache_hit rows are backfilled to `FALSE` before `SET NOT NULL`, so
          the constraint cannot fail on live data
        - the resulting shapes are verified from the catalog, and the upgrade
          fails rather than stamping a schema that is still wrong
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

    Narrowing VARCHAR(24) back to VARCHAR(12) would destroy values longer than 12
    characters, so this refuses rather than truncating. It counts the offending
    rows first and raises. A silent shortening of live ids is worse than a failure.

    Ensures:
        - is_cache_hit returns to nullable; the backfilled `FALSE` values remain,
          being indistinguishable from genuine `FALSE` and not recoverable
        - the width narrowing is refused, loudly, when any value exceeds 12 chars
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
