"""Add task_items.body_changed_ts — the content-change marker park staleness reads

Revision ID: 38e025169a73
Revises: 53835fd51f1a
Create Date: 2026-07-26

Closes bug `54924128` (María 🌸, 2026-07-26), on Rick's ruling (option a,
ask_multiple_choice, answered=true, default_used=false): the live-store schema
migration is AUTHORIZED, and it is the whole reason that bug was a decision
rather than a build.

WHAT WAS WRONG — MEASURED, NOT INFERRED
----------------------------------------
`park_reason_is_stale` compared `park_reason_captured_at` against `updated_ts`.
`updated_ts` moves on EVERY write. `task_edit`'s five free-edit fields are
title / body / priority / gate_class / urgency, and **only `body` can make a
park quote untrue** — but a priority-only edit bumps `updated_ts` and flips the
flag anyway. So can any transition, any patch, any amend.

Two priority-only edits during a routine board recut on 2026-07-26 produced two
false STALEs in three minutes. At that moment **every parked row in production
carried the flag and every one of them was wrong: 0 of 2 correct.**

⇒ `updated_ts` was being used as a proxy for "the row's content changed," and it
is not one. This column is the thing it was standing in for.

⚠️ WHY A FALSE *STALE* IS THE ONE DIRECTION THIS FEATURE FORBIDS — its own words
--------------------------------------------------------------------------------
From `park_reason_is_stale`'s § WHICH WAY THIS INSTRUMENT LIES:

    "Staleness is ADVISORY: it changes no owed-ness and blocks nothing, so a
    false STALE has no mechanism to correct it — it merely defames a correct
    quote and teaches readers to ignore the flag, which disarms the feature
    permanently. A false FRESH is exactly the status quo this change improves
    on. Silence is recoverable here; a crying wolf is not."

The predicate was built to bias every ambiguous arm toward FRESH for exactly
this reason — and then read a column that the single most common maintenance
write on the board moves.

WHAT THIS ADDS
--------------
`body_changed_ts` TIMESTAMPTZ NULL — the instant the row's `body` last actually
CHANGED. Stamped from the DATABASE clock by the two paths that write body:

    apply_amendment  -> always (an amend only ever appends to body)
    apply_patch      -> ONLY when `body` is in the payload AND its value differs

**That second condition is the entire fix.** A patch touching priority /
gate_class / urgency / title leaves this column alone, so the quote keeps its
freshness.

⚠️ NO BACKFILL, AND THAT IS A DECISION WITH A CONSEQUENCE
----------------------------------------------------------
Every existing row gets NULL, and a NULL third argument returns FRESH
(`task_store_owed.park_reason_is_stale`, the `else: return False` arm —
ambiguity → FRESH, §3.3).

**So the flag goes globally inert until each row's body next changes.** That is
stated here rather than discovered later: it is the honest reading of a column
whose history genuinely does not exist, and it is the same bias the predicate
already applies to a row parked before capture-time shipped. The alternative —
backfilling `updated_ts` — would preserve every current value, and every current
value is a false positive. Backfilling `created_ts` would fabricate a claim that
the body has not changed since creation, which is false for most rows.

⇒ Contrast with `d47487369407`, which HAD to backfill because
`ck_task_items_parked_requires_captured_at` would have rejected live parked rows
the moment the CHECK was added. **There is no CHECK here and there must not be**:
a row whose body has never changed since this shipped legitimately has no value,
forever. A NOT NULL on this column would be a constraint asserting a fact about
history that nobody recorded.

⇒ Immediate effect: the two live false positives (`76f26f9b`, `dc36ff69` — both
María's, both from the recut) clear when this lands, without a backfill guessing
at history it does not have.

WHY THE DB CLOCK AND NOT `datetime.now()` — inherited, not re-derived
----------------------------------------------------------------------
`park_reason_captured_at` is written from the DATABASE clock
(`TaskRepository._db_clock_now`, and see `_park_capture_ts`'s reasoning). This
column is compared AGAINST it. An application-clock stamp would make the
comparison cross-clock, and skew would surface as a **false FRESH** — a parked
row quietly failing to report an expired quote, which is the very defect the
feature exists to detect, arriving in the silent direction. One clock, one value.

SCOPE: adds one nullable column. No CHECK, no backfill, no other row touched.

IDEMPOTENT + SAFE TO RE-RUN: the column is added only when missing (the
auto-migrate startup path may reach this on an already-migrated DB, and the test
DB is built from metadata rather than from migrations).

REVISION ID NOTE: `38e025169a73` was chosen RANDOMLY (uuid4), NOT by continuing
the visual hex pattern of the neighbouring filenames — that pattern walks into
the absorbed range, which is how `a3b4c5d6e7f8` collided with a real migration.
Verified absent from `_ABSORBED_REVISIONS` and from the repo by grep, with the
grep first proven capable of positives against a known-present id
(`d47487369407`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '38e025169a73'
down_revision: Union[str, Sequence[str], None] = '53835fd51f1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "task_items"
COLUMN_NAME = "body_changed_ts"


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add the nullable body_changed_ts column.

    Ensures:
        - no-op when task_items is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe)
        - NO backfill and NO CHECK — see the module docstring; existing rows keep
          NULL, which the predicate reads as FRESH
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, sa.DateTime( timezone=True ), nullable=True ) )
        print( f"[{revision}] added {TABLE_NAME}.{COLUMN_NAME} (NULL for every existing row — reads as FRESH by design)" )


def downgrade() -> None:
    """
    Drop the body_changed_ts column.

    ⚠️ Downgrading RE-ARMS bug `54924128`: the predicate falls back to `updated_ts`
    and a priority-only edit will defame a correct quote again.

    Ensures:
        - no-op when task_items is absent
        - the drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
