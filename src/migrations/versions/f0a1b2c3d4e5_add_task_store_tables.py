"""add_task_store_tables

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-06-11

Unified task store, Phase 1 (design: planning-is-prompting ->
src/rnd/2026.06.11-unified-task-store-design.md v0.4, Rick-ruled F1=Postgres):

    task_items  — one row per obligation; correlation_key indexed (C1, poured
                  Phase 1); typed blocked_by JSONB refs; CHECK enforcing
                  next_chase_ts-required-when-blocked (I3)
    task_events — append-only per-item audit trail; receipt_refs JSONB
                  (non-empty REQUIRED for ->done at the API layer, T3)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
# Rebased onto the TRUE baseline (000000000000) — was 'e9f0a1b2c3d4', the former
# stamp target; the pre-baseline span 210acf4d54dd..e9f0a1b2c3d4 is now absorbed
# into the baseline (see 000000000000_true_baseline_schema.py).
down_revision: Union[str, Sequence[str], None] = '000000000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create task_items + task_events with indexes and the I3 CHECK.

    IDEMPOTENT (hardened 2026-06-22, same bug-class as the b633d12a hotfix for
    e5f6a7b8c9d0). A DB bootstrapped by ``Base.metadata.create_all`` and stamped
    BELOW this revision (e.g. at the true baseline ``000000000000``) ALREADY holds
    both task-store tables, so an unguarded ``upgrade head`` raises ``DuplicateTable``
    on the first ``create_table`` and aborts boot. Snapshot the live schema once and
    create each table only when absent — a safe no-op on a create_all DB (just
    advances the stamp), full build on a truly-empty DB.
    """
    existing_tables = set( sa.inspect( op.get_bind() ).get_table_names() )

    if "task_items" not in existing_tables:
        op.create_table(
            'task_items',
            sa.Column( 'id', UUID( as_uuid=True ), primary_key=True, server_default=sa.text( 'gen_random_uuid()' ) ),
            sa.Column( 'item_class', sa.String( 32 ), nullable=False ),
            sa.Column( 'title', sa.Text(), nullable=False ),
            sa.Column( 'body', sa.Text(), nullable=True ),
            sa.Column( 'project', sa.String( 255 ), nullable=False ),
            sa.Column( 'owner_persona', sa.String( 255 ), nullable=True ),
            sa.Column( 'accountable_manager', sa.String( 255 ), nullable=True ),
            sa.Column( 'created_by', sa.String( 255 ), nullable=False ),
            sa.Column( 'status', sa.String( 32 ), nullable=False, server_default='queued' ),
            sa.Column( 'blocked_by', JSONB(), nullable=False, server_default='[]' ),
            sa.Column( 'next_chase_ts', sa.DateTime( timezone=True ), nullable=True ),
            sa.Column( 'gate_class', sa.String( 32 ), nullable=False, server_default='none' ),
            sa.Column( 'priority', sa.String( 2 ), nullable=False, server_default='P2' ),
            sa.Column( 'source_qid', sa.String( 64 ), nullable=True ),
            sa.Column( 'correlation_key', sa.String( 255 ), nullable=True ),
            sa.Column( 'created_ts', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) ),
            sa.Column( 'updated_ts', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) ),
            sa.CheckConstraint(
                "status != 'blocked' OR next_chase_ts IS NOT NULL",
                name='ck_task_items_blocked_requires_chase_ts'
            )
        )
        op.create_index( 'ix_task_items_item_class', 'task_items', [ 'item_class' ] )
        op.create_index( 'ix_task_items_project', 'task_items', [ 'project' ] )
        op.create_index( 'ix_task_items_owner_persona', 'task_items', [ 'owner_persona' ] )
        op.create_index( 'ix_task_items_accountable_manager', 'task_items', [ 'accountable_manager' ] )
        op.create_index( 'ix_task_items_status', 'task_items', [ 'status' ] )
        op.create_index( 'ix_task_items_gate_class', 'task_items', [ 'gate_class' ] )
        op.create_index( 'idx_task_items_correlation_key', 'task_items', [ 'correlation_key' ] )
        op.create_index( 'idx_task_items_owner_status', 'task_items', [ 'owner_persona', 'status' ] )

    if "task_events" not in existing_tables:
        op.create_table(
            'task_events',
            sa.Column( 'id', sa.BigInteger(), primary_key=True, autoincrement=True ),
            sa.Column( 'item_id', UUID( as_uuid=True ), sa.ForeignKey( 'task_items.id', ondelete='CASCADE' ), nullable=False ),
            sa.Column( 'ts', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) ),
            sa.Column( 'actor', sa.String( 255 ), nullable=False ),
            sa.Column( 'transition', sa.String( 64 ), nullable=False ),
            sa.Column( 'receipt_refs', JSONB(), nullable=True ),
            sa.Column( 'authority', sa.String( 32 ), nullable=False, server_default='standing' )
        )
        op.create_index( 'idx_task_events_item_id', 'task_events', [ 'item_id' ] )


def downgrade() -> None:
    """Drop both task-store tables symmetrically (children first — FK order).

    IDEMPOTENT (symmetric with upgrade): each table is dropped only when present,
    so a downgrade over a partially-applied schema is a safe no-op for the absent.
    """
    existing_tables = set( sa.inspect( op.get_bind() ).get_table_names() )

    if "task_events" in existing_tables:
        op.drop_index( 'idx_task_events_item_id', table_name='task_events' )
        op.drop_table( 'task_events' )

    if "task_items" in existing_tables:
        op.drop_index( 'idx_task_items_owner_status', table_name='task_items' )
        op.drop_index( 'idx_task_items_correlation_key', table_name='task_items' )
        op.drop_index( 'ix_task_items_gate_class', table_name='task_items' )
        op.drop_index( 'ix_task_items_status', table_name='task_items' )
        op.drop_index( 'ix_task_items_accountable_manager', table_name='task_items' )
        op.drop_index( 'ix_task_items_owner_persona', table_name='task_items' )
        op.drop_index( 'ix_task_items_project', table_name='task_items' )
        op.drop_index( 'ix_task_items_item_class', table_name='task_items' )
        op.drop_table( 'task_items' )
