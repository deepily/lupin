"""Add task_items.title_trimmed — record the trim instead of re-deriving it

Revision ID: 47513717b7e5
Revises: 3da5c0d1eee6
Create Date: 2026-08-31

Closes bug `769b3574` (Pocholo, 2026-08-31). Prerequisite for decision
`cc6519a6` (raise the title cap 60 -> 120): step 2 of that ruling ships a
silent regression unless this lands first.

WHAT IS WRONG — MEASURED, NOT INFERRED
---------------------------------------
`task_store_rules.title_may_be_trimmed` is `len( title ) == TITLE_SOFT_CAP`,
and `_serialize_item_terse` calls it with NO cap argument. So the board's
`title_trimmed` flag is not a record of what happened to a row — it is
re-derived on every read against whatever the cap currently is.

Two arms over one variable (a real source edit to the constant, caches purged
between arms), driven through the real serializer over all 2,278 stored title
lengths in `lupin_db_dev` — the database is named because a host shell reads
`lupin_db_dev` while a `:8000` job writes `lupin_db_test`:

    TITLE_SOFT_CAP=60    rows=2278   title_trimmed_True=1606
    TITLE_SOFT_CAP=120   rows=2278   title_trimmed_True=1

Of the 1,606, **951 carry the overflow marker in their body**, so they are
provably trimmed rather than merely cap-length; **21 of those 951 are
non-terminal**, which is the population a routine board glance actually shows.
Under a raised cap that becomes 0.

⇒ The reader-side signal shipped at `5f7b0e1f` — whose entire point is that a
terse board glance shows the trim — would switch off across the whole existing
corpus the moment the cap moves, with nothing failing and nothing logged.

WHAT THIS ADDS
--------------
`title_trimmed BOOLEAN NOT NULL DEFAULT false` — written at both write paths
from the guard's own return value, never re-derived at read time.

⚠️ NOT NULL WITH A DEFAULT, WHICH IS THE OPPOSITE CHOICE FROM `body_changed_ts`
-------------------------------------------------------------------------------
`38e025169a73` deliberately left `body_changed_ts` nullable with no backfill,
because every value it could have written would have been a fabrication about
history nobody recorded. **This column is the other case**: the history IS
recorded, in the rows themselves. `soft_guard_title` relocated the overflow
into the body under a greppable marker, so "was this row trimmed" is answerable
from the data rather than guessed.

THE BACKFILL, and what it is allowed to claim
----------------------------------------------
    title_trimmed = TRUE  WHERE body LIKE '%[title overflow%'   -- provably trimmed
                       OR length( title ) = 60                  -- the value the board shows today

The second arm is deliberately the CURRENT derived value, not a stricter truth.
It makes the backfill a SUPERSET of what a reader sees right now, so nothing
that is flagged today stops being flagged when this lands. That matters more
than precision here: this migration must not itself be the regression it exists
to prevent.

⚠️ **60 IS A HISTORICAL LITERAL, NOT THE CURRENT CAP, AND MUST NOT BE UPDATED
WHEN THE CAP CHANGES.** It names the cap that trimmed the existing rows. If a
later reader "fixes" it to 120 to match the config, the backfill stops
describing the corpus it was written for — which is the same defect one level
down.

WHAT THE BACKFILL CANNOT SEPARATE, stated rather than papered over: 655 rows sit
at exactly 60 with no marker. Every one has a non-empty body, so each is
consistent with having been trimmed into an EMPTY body (that arm relocates the
overflow unmarked, because there is nothing for it to be distinguished from).
None can be shown to be naturally 60. So the second arm's false-positive rate is
UNKNOWN rather than zero, and it is the harmless direction: a false positive
costs a reader one look at a body with nothing missing.

⚠️ IT DOES NOT CLEAR A REPAIRED ROW, AND THAT IS THE RIGHT CALL AT MIGRATION TIME
---------------------------------------------------------------------------------
Six rows (`f45b37a9` `462b985c` `309f4213` `c89cec9b` `21792c5d` `c1bbb917`)
were trimmed and then REPAIRED by a shorter retitle: their titles are complete
sentences now, and the length check happens to return False for them. This
backfill's first arm sets them TRUE, because the marker is still in the body.

That is a knowing over-report of six rows, chosen over the alternative of
teaching the migration to guess which retitles were repairs. The going-forward
behaviour is what fixes them properly: `apply_patch` writes the flag on EVERY
title change, so the next edit to any of the six clears it. A stale over-report
that self-corrects on the next write beats a migration inferring intent.

SCOPE: adds one column and one UPDATE over `task_items`. No CHECK, no other
table, no title text altered anywhere.

IDEMPOTENT + SAFE TO RE-RUN: the column is added only when missing, and the
backfill runs only in the same branch as the add, so re-running never re-stamps
rows whose flag has since been legitimately cleared by a retitle.

REVISION ID NOTE: `47513717b7e5` was chosen RANDOMLY (uuid4), NOT by continuing
the visual hex pattern of neighbouring filenames — that pattern walks into the
absorbed range, which is how `a3b4c5d6e7f8` collided with a real migration.
Verified absent from `_ABSORBED_REVISIONS` and from the repo by grep, with the
grep first proven capable of positives against a known-present id
(`38e025169a73`, 6 hits).
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
    Add title_trimmed NOT NULL DEFAULT false, then backfill it from the evidence
    already present in the rows.

    Ensures:
        - no-op when task_items is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - the backfill runs ONLY in the same branch as the add, so a re-run never
          re-stamps a row whose flag a later retitle legitimately cleared
        - every row flagged by the pre-migration read-time predicate is still
          flagged afterwards (the length arm is that predicate, frozen)
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
            f"WHERE body LIKE :marker OR length( title ) = :cap"
        ),
        { "marker": "%[title overflow%", "cap": HISTORICAL_CAP },
    )
    print(
        f"[{revision}] added {TABLE_NAME}.{COLUMN_NAME} and backfilled "
        f"{result.rowcount} row(s) — the overflow marker OR a title at the "
        f"historical {HISTORICAL_CAP}-char cap"
    )


def downgrade() -> None:
    """
    Drop the title_trimmed column.

    ⚠️ Downgrading returns the flag to read-time derivation against the CURRENT
    cap, which re-arms bug 769b3574: if the cap has moved in the meantime, every
    historically trimmed row silently stops being flagged.

    Ensures:
        - no-op when task_items is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
