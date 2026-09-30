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
recorded, in the rows themselves. `soft_guard_title` trims to EXACTLY the cap,
so a title still sitting at the cap is the record of the cut, and "was this row
trimmed" is answerable from the data rather than guessed.

⚠️ THE BODY MARKER IS NOT THAT RECORD, THOUGH IT LOOKS LIKE ONE. It makes the
cut text RECOVERABLE by grep, which is what it was built for, but its presence
in a body is not evidence that THAT row's title is currently cut — see the two
false-positive classes below.

THE BACKFILL, and what it is allowed to claim
----------------------------------------------
    title_trimmed = TRUE  WHERE length( title ) = 60

ONE arm, deliberately: the CURRENT read-time derived value, frozen. The backfill
therefore agrees EXACTLY with what a reader sees today, so nothing that is
flagged now stops being flagged when this lands. This migration must not itself
be the regression it exists to prevent.

⚠️ THERE WAS A SECOND ARM — `OR body LIKE '%[title overflow%'` — AND IT IS
REMOVED RATHER THAN NARROWED. Rio ⚡ found it stamping TRUE on rows that were
trimmed and then REPAIRED by a shorter retitle (row 6a43a4be), and proposed
`AND length( title ) = cap`. That is correct, and it makes the arm DEAD: `A AND B`
OR'd with `B` is `B`. Measured rather than argued from algebra, in lupin_db_dev:

    body LIKE marker OR  length( title ) = 60                    1620   <- original
    ( body LIKE marker AND length( title ) = 60 ) OR len = 60     1612   <- Rio's narrowing
    length( title ) = 60                                         1612   <- this clause

The deeper reason the arm can go outright is in `soft_guard_title` itself: it
trims with `title[ :cap ]`, so a trimmed title is EXACTLY cap characters, never
fewer. A row that was trimmed AND is still hiding a tail therefore ALWAYS
satisfies the length arm. The marker could only ever contribute rows whose length
DIFFERS from the cap — and every one of those is a false positive.

⚠️ **60 IS A HISTORICAL LITERAL, NOT THE CURRENT CAP, AND MUST NOT BE UPDATED
WHEN THE CAP CHANGES.** It names the cap that trimmed the existing rows. If a
later reader "fixes" it to 120 to match the config, the backfill stops
describing the corpus it was written for — which is the same defect one level
down.

WHAT THE BACKFILL CANNOT SEPARATE, stated rather than papered over: 657 rows sit
at exactly 60 with no marker. Each is consistent with having been trimmed into an
EMPTY body — that arm relocates the overflow unmarked, because there is nothing
for it to be distinguished from — so the clause over-reports in the harmless
direction: a false positive costs a reader one look at a body with nothing missing.

🔴 THE FALSE-POSITIVE RATE IS NOT UNKNOWN. THIS PARAGRAPH SAID "None can be shown
to be naturally 60" AND THAT WAS WRONG — 14 CAN BE, BY ARITHMETIC RATHER THAN
TASTE. (The claim was mine, in the first cut of this file. It is corrected here
rather than quietly deleted, because a docstring that has been wrong once is
evidence about how carefully the next sentence should be read.)

The predicate: `length( title ) = 60` AND the title ENDS in `)` AND its parens
BALANCE. A cut at an arbitrary character landing on a paren that closes an opener
is a coincidence; fourteen of them is not. Measured 2026-08-31 in lupin_db_dev:

    Steward Fleet#6 + Task#7 live-render verify (final MVP gate)
    REVIEW: arbiter staleness work_owed=false fix (bug 25ba173e)
    [LUPIN] Plan 1 lane 2: land qa-card-tester impl (12 commits)
    ... 14 in total

⚠️ THREE LEGS, AND THE THIRD IS WHAT MAKES THE OTHER TWO MEAN ANYTHING:

  1. NONE of the 14 carries the overflow marker — asked with the marker exclusion
     REMOVED from the WHERE, so the zero is not manufactured by the filter that
     found them: balanced rows 14, of those with marker 0.
  2. POSITIVE CONTROL: the same marker test returns 965 rows store-wide. The zero
     is a real absence, not a search over an empty population.
  3. ⚠️ "NO MARKER" PROVES NOTHING ON ITS OWN, which is the trap this correction
     had to walk through rather than around: the empty-body arm files the overflow
     WITHOUT a marker. So the marker's absence is consistent with a trim. What
     rules that arm out is the body itself — of the 14, ZERO have a null or blank
     body, the SHORTEST is 259 characters, and 9 carry newlines. That arm sets
     `body` to the title's own tail; a 259-character multi-line body is not one.

⇒ So the over-report has a measured FLOOR of 14 rather than an unknown rate, and
the predicate is reproducible by anyone who doubts it. It changes NO code: those
14 were always in the harmless direction and still are. What changes is that the
next reader is handed a number and a query instead of a shrug.

⚠️ WHAT THE MARKER ARM ACTUALLY MATCHED — TWO CLASSES, NEITHER OF THEM TRIMMED
---------------------------------------------------------------------------------
Measured 2026-08-31 in `lupin_db_dev`, named because a host shell reads dev while
a `:8000` job writes test — and `lupin_db_test` holds ZERO task_items, so the same
query run there returns an empty answer indistinguishable from "no such rows".
The same query returns 963 marker rows in dev, which is the positive control that
makes the test-side zero readable as an empty population rather than a real absence.

`body LIKE '%[title overflow%' AND length( title ) <> 60` returns 8 rows, none of
them OVER the cap:

  · 4 carry the FULL marker line and WERE trimmed, then REPAIRED by a shorter
    retitle — f45b37a9, 462b985c, 309f4213, c89cec9b. Their titles are complete
    sentences now and nothing is hidden, so FALSE is the right answer. This is the
    class Rio found.
  · 4 carry only the loose prefix `[title overflow`, because their bodies QUOTE
    the marker while DISCUSSING it — 21792c5d, c1bbb917, 26a672b3, and 6a43a4be,
    which is Rio's own bug row. These were never trimmed at all.

⚠️ THE SECOND CLASS IS WHY THE ARM GOES RATHER THAN SHRINKS, AND IT GROWS ON ITS
OWN. Every future row written ABOUT this defect matches a body-text search for the
marker: filing the bug at 16:25:10 is what took the population from the 7 rows
Mr. Radio 🦉 measured to the 8 above — the two counts reconcile exactly, and the
new member is the bug row itself. A text search over bodies cannot separate a row
that WAS trimmed from a row that TALKS about trimming; `length( title ) = cap`
never had to.

GOING FORWARD, unchanged: `apply_patch` writes the flag on EVERY title change from
the guard's own verdict, so a later retitle keeps the value honest without this
UPDATE having to infer anyone's intent.

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
          flagged afterwards, and no other row is (the clause IS that predicate,
          frozen at the historical cap)
        - a row carrying the overflow marker but a title NOT at the cap is left
          False: it was either repaired by a later retitle, or its body merely
          quotes the marker while discussing it
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
