"""Add task_promotion_tickets — the observable record of a promotion out of the holding area

Revision ID: 8d404f635e84
Revises: 47513717b7e5
Create Date: 2026-09-06

Backs STAGE 1 of the asynchronous promotion approval design
(`src/rnd/v0.2.1/2026.09.06-asynchronous-promotion-approval-and-its-observable-
resolution.md`, row `3493ae9b`).

WHAT IT ADDS, AND WHAT IT DELIBERATELY DOES NOT
------------------------------------------------
One table. **No behaviour change whatsoever, and no status code is touched.** Stage 1
exists so the observability surface is in place and testable BEFORE anything stops
blocking — the ruling that authorised this work is conditional on a caller being able
to observe the outcome, and building the observation surface after the behaviour
change would be shipping the condition last.

⚠️ NOTHING WRITES TO THIS TABLE IN THIS REVISION. That is intended, and it is the one
thing a reader is most likely to mistake for an oversight. The writer arrives with the
202 (design stage 2), which does not land until stage 3's sweeper exists — because the
moment the door returns 202, a caller that walks away must not be able to lose Rick's
keypress.

WHY A TABLE RATHER THAN COLUMNS ON `task_items`
------------------------------------------------
Full argument in the model's docstring
(`cosa/rest/postgres_models.py::TaskPromotionTicket`) and design §5.2. In short: the
notification record knows THAT a human was asked and not which task, which to_status,
or who asked; and four columns on the hot `task_items` table would be carried forever
by every reader of it, for a state that is rare and short-lived.

⚠️ THE TWO CHECK LITERALS MUST MATCH THE MODEL'S VERBATIM
----------------------------------------------------------
`postgres_models.TaskPromotionTicket.__table_args__` carries the same two strings, and
a test asserts the pair agree. Same reason the I3 chase CHECK already carries the same
warning in this tree: a schema built by `create_all` (an empty DB, and the test DB) and
one built by migration are two records of one fact, and two records of one fact drift.

They are STRUCTURAL invariants — facts about a resolved ticket — not a membership test
on `state`. The state vocabulary is enforced at the API layer, exactly as
`task_items.status` is against `task_store_rules.VALID_STATUSES`, which likewise has no
enum constraint in the schema. Adding one here would be a third record of one fact.

IDEMPOTENT + SAFE TO RE-RUN
----------------------------
The upgrade inspects the live schema first. The auto-migrate startup path can reach
this on an already-migrated DB, and the test DB is created from metadata rather than
from migrations, so `create_all` may have built the table already.

⚠️ NO BACKFILL, AND NOTHING TO BACK-FILL. The table is new and starts empty. There are
no pre-existing promotions to reconstruct — a promotion that already happened left its
record on `task_events`, and inventing ticket rows for them would be fabricating a
history nobody measured.

REVISION ID NOTE: `8d404f635e84` was chosen RANDOMLY (uuid4 hex), NOT by continuing the
visual hex pattern of neighbouring filenames — that pattern walks into the absorbed
range, which is how `a3b4c5d6e7f8` once collided with a real migration. Verified absent
from the repo by grep, with the grep first proven capable of a positive against a
known-present id; and `47513717b7e5` was confirmed as the single head by
`ScriptDirectory.get_heads()` rather than by reading down_revisions by eye.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8d404f635e84'
down_revision: Union[str, Sequence[str], None] = '47513717b7e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "task_promotion_tickets"

INDEX_ITEM_ID  = "idx_task_promotion_tickets_item_id"
INDEX_STATE_BY = "idx_task_promotion_tickets_state_resolves_by"

CHECK_RESOLVED_NAME      = "ck_task_promotion_tickets_resolved_has_timestamp"
CHECK_RESOLVED_CONDITION = "state = 'pending' OR resolved_at IS NOT NULL"

CHECK_REFUSED_NAME      = "ck_task_promotion_tickets_refused_has_reason"
CHECK_REFUSED_CONDITION = "state != 'refused' OR refusal IS NOT NULL"


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _index_names( inspector ) -> set:
    return { index[ "name" ] for index in inspector.get_indexes( TABLE_NAME ) }


def upgrade() -> None:
    """
    Create task_promotion_tickets, its two indexes and its two structural CHECKs.

    ⚠️ THE CHECKS ARE DECLARED INSIDE `create_table` RATHER THAN ADDED AFTERWARDS,
    which is the opposite of the park_reason_captured_at migration and correct for
    the opposite reason. That one added a constraint to a table holding live rows,
    so a backfill had to precede it. This table is BORN EMPTY: no row can violate
    either check at creation, and there is no ordering hazard to manage.

    Ensures:
        - no-op when the table already exists (create_all may have built it, and the
          auto-migrate startup path may reach this on an already-migrated DB)
        - constraints are created WITH the table, so a half-constrained table is not
          representable
    """
    inspector = inspect( op.get_bind() )
    if _table_exists( inspector ):
        return

    op.create_table(
        TABLE_NAME,
        sa.Column( "id", postgresql.UUID( as_uuid=True ), primary_key=True,
                   server_default=sa.text( "gen_random_uuid()" ), nullable=False ),
        sa.Column( "item_id", postgresql.UUID( as_uuid=True ),
                   sa.ForeignKey( "task_items.id", ondelete="CASCADE" ), nullable=False ),

        sa.Column( "to_status",    sa.String( 32 ),  nullable=False ),
        sa.Column( "requested_by", sa.String( 255 ), nullable=False ),
        sa.Column( "requested_at", sa.DateTime( timezone=True ), nullable=False,
                   server_default=sa.func.now() ),
        sa.Column( "resolves_by",  sa.DateTime( timezone=True ), nullable=False ),
        sa.Column( "payload",      postgresql.JSONB, nullable=True ),

        sa.Column( "state", sa.String( 32 ), nullable=False, server_default="pending" ),
        sa.Column( "notification_id", sa.String( 255 ), nullable=True ),
        sa.Column( "ask_status",      sa.String( 32 ),  nullable=True ),
        sa.Column( "approval_source", sa.String( 32 ),  nullable=True ),
        sa.Column( "refusal",         sa.Text,          nullable=True ),
        sa.Column( "response_body",   postgresql.JSONB, nullable=True ),
        sa.Column( "resolved_at",     sa.DateTime( timezone=True ), nullable=True ),

        sa.CheckConstraint( CHECK_RESOLVED_CONDITION, name=CHECK_RESOLVED_NAME ),
        sa.CheckConstraint( CHECK_REFUSED_CONDITION,  name=CHECK_REFUSED_NAME ),
    )

    op.create_index( INDEX_ITEM_ID,  TABLE_NAME, [ "item_id" ] )
    op.create_index( INDEX_STATE_BY, TABLE_NAME, [ "state", "resolves_by" ] )


def downgrade() -> None:
    """
    Drop the table, with its indexes and constraints.

    Ensures:
        - no-op when the table is already absent, so a partial upgrade downgrades
          cleanly rather than raising
        - each index is dropped by name, guarded individually, before the table
        - the CHECKs and the FK go with the table; nothing to un-stamp, because
          nothing was backfilled
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return

    existing = _index_names( inspector )
    for name in ( INDEX_STATE_BY, INDEX_ITEM_ID ):
        if name in existing:
            op.drop_index( name, table_name=TABLE_NAME )

    op.drop_table( TABLE_NAME )
