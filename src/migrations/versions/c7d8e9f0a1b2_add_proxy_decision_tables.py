"""add_proxy_decision_tables

Revision ID: c7d8e9f0a1b2
Revises: b5c6d7e8f9a0
Create Date: 2026-02-23

Add proxy_decisions and trust_states tables for the decision proxy system.
Enables proxy decision logging, ratification workflow, and per-user trust tracking.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, Sequence[str], None] = 'b5c6d7e8f9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create proxy_decisions and trust_states tables with indexes."""

    # --- Table 1: proxy_decisions ---
    op.create_table(
        'proxy_decisions',
        sa.Column( 'id', postgresql.UUID( as_uuid=True ), primary_key=True, server_default=sa.text( 'gen_random_uuid()' ) ),
        sa.Column( 'notification_id', sa.String( 255 ), nullable=False ),
        sa.Column( 'domain', sa.String( 50 ), nullable=False ),
        sa.Column( 'category', sa.String( 100 ), nullable=False ),
        sa.Column( 'question', sa.Text(), nullable=False ),
        sa.Column( 'sender_id', sa.String( 255 ), nullable=True ),
        sa.Column( 'action', sa.String( 50 ), nullable=False ),
        sa.Column( 'decision_value', sa.Text(), nullable=True ),
        sa.Column( 'confidence', sa.Float(), nullable=True ),
        sa.Column( 'trust_level', sa.Integer(), nullable=False, server_default='1' ),
        sa.Column( 'reason', sa.Text(), nullable=True ),
        sa.Column( 'ratification_state', sa.String( 50 ), nullable=False, server_default='not_required' ),
        sa.Column( 'ratified_by', sa.String( 255 ), nullable=True ),
        sa.Column( 'ratified_at', sa.DateTime( timezone=True ), nullable=True ),
        sa.Column( 'ratification_feedback', sa.Text(), nullable=True ),
        sa.Column( 'metadata_json', postgresql.JSONB(), nullable=True ),
        sa.Column( 'created_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) ),
    )

    # proxy_decisions indexes
    op.create_index( 'idx_proxy_decisions_domain', 'proxy_decisions', ['domain'] )
    op.create_index( 'idx_proxy_decisions_category', 'proxy_decisions', ['category'] )
    op.create_index( 'idx_proxy_decisions_action', 'proxy_decisions', ['action'] )
    op.create_index( 'idx_proxy_decisions_ratification', 'proxy_decisions', ['ratification_state'] )
    op.create_index( 'idx_proxy_decisions_created_at', 'proxy_decisions', ['created_at'] )
    op.create_index( 'idx_proxy_decisions_domain_category', 'proxy_decisions', ['domain', 'category'] )

    # --- Table 2: trust_states ---
    op.create_table(
        'trust_states',
        sa.Column( 'id', postgresql.UUID( as_uuid=True ), primary_key=True, server_default=sa.text( 'gen_random_uuid()' ) ),
        sa.Column( 'user_email', sa.String( 255 ), nullable=False ),
        sa.Column( 'domain', sa.String( 50 ), nullable=False ),
        sa.Column( 'category', sa.String( 100 ), nullable=False ),
        sa.Column( 'trust_level', sa.Integer(), nullable=False, server_default='1' ),
        sa.Column( 'total_decisions', sa.Integer(), nullable=False, server_default='0' ),
        sa.Column( 'successful_decisions', sa.Integer(), nullable=False, server_default='0' ),
        sa.Column( 'rejected_decisions', sa.Integer(), nullable=False, server_default='0' ),
        sa.Column( 'circuit_breaker_state', postgresql.JSONB(), nullable=True ),
        sa.Column( 'created_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) ),
        sa.Column( 'updated_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) ),
    )

    # trust_states indexes
    op.create_index( 'idx_trust_states_user_domain', 'trust_states', ['user_email', 'domain'] )
    op.create_index( 'idx_trust_states_category', 'trust_states', ['category'] )
    op.create_index( 'idx_trust_states_user_domain_category', 'trust_states', ['user_email', 'domain', 'category'], unique=True )


def downgrade() -> None:
    """Drop trust_states and proxy_decisions tables and indexes."""

    # Drop trust_states indexes, then table
    op.drop_index( 'idx_trust_states_user_domain_category', 'trust_states' )
    op.drop_index( 'idx_trust_states_category', 'trust_states' )
    op.drop_index( 'idx_trust_states_user_domain', 'trust_states' )
    op.drop_table( 'trust_states' )

    # Drop proxy_decisions indexes, then table
    op.drop_index( 'idx_proxy_decisions_domain_category', 'proxy_decisions' )
    op.drop_index( 'idx_proxy_decisions_created_at', 'proxy_decisions' )
    op.drop_index( 'idx_proxy_decisions_ratification', 'proxy_decisions' )
    op.drop_index( 'idx_proxy_decisions_action', 'proxy_decisions' )
    op.drop_index( 'idx_proxy_decisions_category', 'proxy_decisions' )
    op.drop_index( 'idx_proxy_decisions_domain', 'proxy_decisions' )
    op.drop_table( 'proxy_decisions' )
