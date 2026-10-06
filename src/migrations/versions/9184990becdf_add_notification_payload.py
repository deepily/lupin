"""Add notifications.payload (JSONB NULL) + the partial broadcast-ack lookup index

Revision ID: 9184990becdf
Revises: ffbf50040d99
Create Date: 2026-09-23

Broadcast acks are saved with the notifications, carrying the metadata that
says which broadcast and which seat each one belongs to. A
`commons_broadcast_ack` used to reach the browser as an in-memory push and
nothing else. Its identity lived only in the push's `payload=` dict, which no
table holds. A page reload lost the tally, and closing the page lost the ack.
This column is where that dict lands.

1. `payload` `JSONB NULL`, the notification's structured side-channel. With no
   default and no backfill, Postgres does a catalog-only `ADD COLUMN`, so there
   is no table rewrite. Existing rows stay NULL, which is right: no payload.
2. `idx_notifications_ack_broadcast`, a partial index over ack rows only, keyed
   by `(recipient_id, (payload->>'broadcast_id'))`. Those are the two selective
   terms of `NotificationRepository.get_latest_acks_for_broadcast`. The partial
   predicate confines the index to acks, not every notification ever written.
   It is character-identical to the ORM `Index` in postgres_models.py and to the
   repo query's `type` filter:
```
type = 'commons_broadcast_ack'
```

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction and an Alembic
migration is one, so `op.get_context().autocommit_block()` runs the create
outside it. The `notifications` table is kept forever and is on the notify hot
path. A plain `CREATE INDEX` would take a ShareLock over it for the whole build.
Same shape as `3da5c0d1eee6`, which added the partial answer-owed index.

Both declarations are mandatory. `schema_drift` compares columns only and would
never notice a missing index, so the ORM `Index` keeps `autogenerate` honest.
This migration is what builds the index on a server.

The migration is idempotent and safe to re-run. `auto_migrate.run_migrations_to_head`
runs `upgrade head` on every process start. The test DB is built from
`Base.metadata.create_all` and then stamped. So each step inspects the live
schema first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '9184990becdf'
down_revision: Union[str, Sequence[str], None] = 'ffbf50040d99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME  = "notifications"
COLUMN_NAME = "payload"
INDEX_NAME  = "idx_notifications_ack_broadcast"
INDEX_WHERE = "type = 'commons_broadcast_ack'"
INDEX_EXPR  = "(payload->>'broadcast_id')"


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names( inspector ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( TABLE_NAME ) }


def _index_names( inspector ) -> set:
    return { index[ "name" ] for index in inspector.get_indexes( TABLE_NAME ) }


def upgrade() -> None:
    """
    Add the nullable JSONB payload column and the partial broadcast-ack index.

    Ensures:
        - no-op when notifications is absent (a fresh DB built from metadata)
        - the column is added only when missing (re-run safe); no default, so no rewrite
        - the partial index is built `CONCURRENTLY` and only when missing (re-run safe)
    """
    bind      = op.get_bind()
    inspector = inspect( bind )
    if not _table_exists( inspector ):
        return

    if COLUMN_NAME not in _column_names( inspector ):
        op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, JSONB, nullable=True ) )
        print( f"[{revision}] added {TABLE_NAME}.{COLUMN_NAME} (NULL for every existing row — they carried no payload)" )

    # CONCURRENTLY cannot run inside the migration's transaction — the autocommit
    # block runs it outside. Re-run safe: skip when the index already exists.
    if INDEX_NAME not in _index_names( inspector ):
        with op.get_context().autocommit_block():
            op.create_index(
                INDEX_NAME, TABLE_NAME,
                [ "recipient_id", sa.text( INDEX_EXPR ) ],
                postgresql_concurrently=True,
                postgresql_where=sa.text( INDEX_WHERE ),
            )
        print( f"[{revision}] created partial index {INDEX_NAME} CONCURRENTLY over the broadcast-ack rows" )


def downgrade() -> None:
    """
    Drop the partial broadcast-ack index and the payload column.

    Ensures:
        - no-op when notifications is absent
        - both drops are guarded, so a partial upgrade downgrades cleanly
        - the index is dropped `CONCURRENTLY` (symmetry with the concurrent create)
        - every saved ack's identity is discarded with the column; the rows survive
          as bodiless `commons_broadcast_ack` notifications, which is what they were
          before this revision
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
