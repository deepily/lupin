"""Add task_promotion_tickets — the observable record of a promotion out of the holding area

Revision ID: 8d404f635e84
Revises: 47513717b7e5

Backs the first stage of the asynchronous promotion approval design: one table, no
behaviour change, and no status code touched. The observability surface goes in
place, and is testable, before anything stops blocking. The ruling that authorised
this work is conditional on a caller being able to observe the outcome.

Nothing writes to this table in this revision. That is intended, and it is the thing
a reader is most likely to mistake for an oversight. The writer arrives with the 202,
which must not land until the sweeper exists. Once the door returns 202, a caller
that walks away must not be able to lose the approver's keypress.

Why a table rather than columns on `task_items`: the full argument is in the model's
docstring (`cosa/rest/postgres_models.py::TaskPromotionTicket`). In short, the
notification record knows that a human was asked, not which task, which to_status or
who asked. Four columns on the hot `task_items` table would be carried forever by
every reader, for a state that is rare and short-lived.

The two `CHECK` literals must match the model's verbatim.
`postgres_models.TaskPromotionTicket.__table_args__` carries the same two strings,
and a test asserts the pair agree. A schema built by `create_all` and one built by
migration are two records of one fact, and two records of one fact drift. They are
structural invariants, not a membership test on `state`.
The state vocabulary is enforced at the API layer, as `task_items.status` is
against `task_store_rules.VALID_STATUSES`. A schema enum here would be a third
record.

Idempotent and safe to re-run: the upgrade inspects the live schema first.
The auto-migrate startup path can reach it on an already-migrated DB, and the test DB
is built from metadata. No backfill, and nothing to back-fill: the table is new and
starts empty. A promotion that already happened left its record on `task_events`.
Inventing ticket rows for it would fabricate history nobody measured.
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
    Create task_promotion_tickets, its two indexes and its two structural `CHECK`s.

    The checks are declared inside `create_table`, not added afterwards. The
    park_reason_captured_at migration did the opposite, because it constrained live
    rows. This table is born empty, so no row can violate either check.

    Ensures:
        - no-op when the table already exists (create_all may have built it, and the
          auto-migrate startup path may reach this on an already-migrated DB)
        - constraints are created with the table, so a half-constrained table is not
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
        - the `CHECK`s and the FK go with the table; nothing to un-stamp, because
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
