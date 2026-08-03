"""Add notifications.answer_delivered_at + partial owed index — the late-answer handback mark

Revision ID: 3da5c0d1eee6
Revises: 38e025169a73
Create Date: 2026-08-01

Implements §4.1 of src/rnd/v0.1.9/2026.08.01-late-answer-handback.md (store row
`7bb0a7df`, P1). When a human answers a blocking ask, the answer is persisted
durably but handed back only by waking an in-memory dict — if that entry is gone
(server bounce, dropped SSE stream) the answer is stored and never travels, and
the asking session times out and re-asks. This migration adds the durable
"owed" mark the handback reads.

WHAT THIS ADDS
--------------
1. `answer_delivered_at` TIMESTAMPTZ NULL — the handback mark: simultaneously the
   "owed" flag and the don't-deliver-twice guard. No default ⇒ PG catalog-only
   ADD COLUMN, no table rewrite.
2. `idx_notifications_answer_owed` — a PARTIAL index over the owed set, built
   `CONCURRENTLY` so the forever-kept `notifications` table (ruling 5) is never
   write-locked. Its predicate is the owed predicate, character-identical to the
   ORM `Index` in postgres_models.py and to §4.4's repo query:

       response_requested AND responded_at IS NOT NULL AND answer_delivered_at IS NULL

   The middle term is the §3 design-level invariant: an offline/expired persist
   carries a machine default with `responded_at` NULL and must NEVER be served as
   an owed answer.

WHY CONCURRENTLY NEEDS THE AUTOCOMMIT BLOCK
-------------------------------------------
`CREATE INDEX CONCURRENTLY` cannot run inside a transaction, and Alembic's
default migration IS a transaction. `op.get_context().autocommit_block()` runs
the create outside it. Both the ORM declaration AND this migration are mandatory:
`schema_drift` checks columns only and would never flag a missing index, so the
ORM `Index` keeps the schema honest against `autogenerate`; this migration is
what actually builds the index on the server.

IDEMPOTENT + SAFE TO RE-RUN: the column is added only when missing and the index
created only when missing (the auto-migrate startup path may reach this on an
already-migrated DB, and the test DB is built from metadata rather than from
migrations).

REVISION ID NOTE: `3da5c0d1eee6` was chosen RANDOMLY (uuid4 hex[:12]), NOT by
continuing any visual hex pattern (that pattern walks into the absorbed range).
Verified absent from the repo by grep over `src/`, with the grep first proven
capable of positives against a known-present id (`38e025169a73`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '3da5c0d1eee6'
down_revision: Union[str, Sequence[str], None] = '38e025169a73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "notifications"
COLUMN_NAME = "answer_delivered_at"
INDEX_NAME  = "idx_notifications_answer_owed"
INDEX_WHERE = "response_requested AND responded_at IS NOT NULL AND answer_delivered_at IS NULL"


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def _index_names( inspector ) -> set:
    return { index[ "name" ] for index in inspector.get_indexes( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add the nullable answer_delivered_at column and the partial owed index.

    Ensures:
        - no-op when notifications is absent (fresh DB built from metadata)
        - the column is added only when missing (re-run safe); no default ⇒ no rewrite
        - the partial index is built CONCURRENTLY (no ShareLock, no full scan) and
          only when missing (re-run safe)
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, sa.DateTime( timezone=True ), nullable=True ) )
        print( f"[{revision}] added {TABLE_NAME}.{COLUMN_NAME} (NULL for every existing row — owed set is answered-but-undelivered)" )

    # CONCURRENTLY cannot run inside the migration's transaction — the autocommit
    # block runs it outside. Re-run safe: skip when the index already exists.
    if INDEX_NAME not in _index_names( inspector ):
        with op.get_context().autocommit_block():
            op.create_index(
                INDEX_NAME, TABLE_NAME,
                [ "sender_persona", "responded_at" ],
                postgresql_concurrently=True,
                postgresql_where=sa.text( INDEX_WHERE ),
            )
        print( f"[{revision}] created partial index {INDEX_NAME} CONCURRENTLY over the answer-owed set" )


def downgrade() -> None:
    """
    Drop the partial owed index and the answer_delivered_at column.

    Ensures:
        - no-op when notifications is absent
        - both drops are guarded, so a partial upgrade downgrades cleanly
        - the index is dropped CONCURRENTLY (symmetry with the concurrent create)
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    if INDEX_NAME in _index_names( inspector ):
        with op.get_context().autocommit_block():
            op.drop_index( INDEX_NAME, table_name=TABLE_NAME, postgresql_concurrently=True )

    if COLUMN_NAME in _column_names( inspector ):
        op.drop_column( TABLE_NAME, COLUMN_NAME )
