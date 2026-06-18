"""add_proxy_trust_prediction_serverlifecycle_tables_and_notif_columns

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-17

Close the migration<->ORM drift left open after the L3 "true baseline"
collapse (baseline 000000000000). Four ORM tables had NO migration anywhere
in the chain, and five notifications columns were never added by any
migration -- the empty-DB ``alembic upgrade head`` path silently MISSED them.
They only ever existed in deployed DBs because the app-boot auto-migrator
(``auto_migrate.py`` case 2) bootstraps an empty DB via
``Base.metadata.create_all`` + ``stamp head`` rather than a pure
``upgrade head``. That create_all mask is exactly what bites a fresh GCP
Cloud-SQL bring-up that runs migrations directly -- the reproducible-deploy
mandate requires the migration chain itself to be the single source of truth.

This migration makes ``upgrade head`` on an empty DB build the SAME schema
``Base.metadata.create_all`` builds for these objects, so the create_all mask
can be retired with zero behavioral change.

Tables created (verbatim ORM DDL from src/cosa/rest/postgres_models.py):
    - proxy_decisions     (ProxyDecision,   models L765)
    - trust_states        (TrustState,      models L899)
    - prediction_log      (PredictionLog,   models L993; FK -> notifications.id)
    - server_lifecycle    (ServerLifecycle, models L1227)

notifications columns added (the FIVE not already added by c3d4e5f6a7b8,
which added direction/sender_persona/sender_icon/reply_to/thread_id):
    - job_id            (models L527, indexed)
    - progress_group_id (models L532, indexed)
    - abstract          (models L547)
    - response_options  (models L630)
    - is_hidden         (models L649, indexed, server_default false)

Index parity note: the ORM declares BOTH the named ``idx_*`` indexes (in each
model's ``__table_args__``) AND auto ``ix_*`` indexes (from per-column
``index=True``). create_all emits both, so this migration emits both -- this
is what makes a post-migration autogenerate report a CLEAN diff for these
four tables and five columns. The redundant idx_*/ix_* overlap is a
pre-existing ORM modeling characteristic, not introduced here; deduping it is
a separate ORM-cleanup concern out of scope for a parity migration.

server_default note: several NOT NULL integer/float columns on these tables
carry only a CLIENT-side ``default=`` in the ORM (trust_level,
total_decisions, successful_decisions, rejected_decisions,
prediction_confidence, similar_case_count) -- NO server_default. The original
pre-baseline migrations (c7d8e9f0a1b2 / d8e9f0a1b2c3) DID set server defaults
on these, but the current ORM does not; this migration matches the ORM (the
stated source of truth), so create_all parity holds exactly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the 4 drift tables + add the 5 missing notifications columns."""

    # ------------------------------------------------------------------
    # Table 1: proxy_decisions  (ProxyDecision)
    # ------------------------------------------------------------------
    op.create_table(
        'proxy_decisions',
        sa.Column( 'id', postgresql.UUID( as_uuid=True ), nullable=False, server_default=sa.text( 'gen_random_uuid()' ) ),
        sa.Column( 'notification_id', sa.String( 255 ), nullable=False ),
        sa.Column( 'domain', sa.String( 50 ), nullable=False ),
        sa.Column( 'category', sa.String( 100 ), nullable=False ),
        sa.Column( 'question', sa.Text(), nullable=False ),
        sa.Column( 'sender_id', sa.String( 255 ), nullable=True ),
        sa.Column( 'action', sa.String( 50 ), nullable=False ),
        sa.Column( 'decision_value', sa.Text(), nullable=True ),
        sa.Column( 'confidence', sa.Float(), nullable=True ),
        sa.Column( 'trust_level', sa.Integer(), nullable=False ),
        sa.Column( 'reason', sa.Text(), nullable=True ),
        sa.Column( 'ratification_state', sa.String( 50 ), nullable=False, server_default='not_required' ),
        sa.Column( 'ratified_by', sa.String( 255 ), nullable=True ),
        sa.Column( 'ratified_at', sa.DateTime( timezone=True ), nullable=True ),
        sa.Column( 'ratification_feedback', sa.Text(), nullable=True ),
        sa.Column( 'metadata_json', postgresql.JSONB(), nullable=True ),
        sa.Column( 'data_origin', sa.String( 50 ), nullable=False, server_default='organic' ),
        sa.Column( 'created_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'now()' ) ),
        sa.PrimaryKeyConstraint( 'id' ),
    )
    # Named composite/explicit indexes (__table_args__)
    op.create_index( 'idx_proxy_decisions_action', 'proxy_decisions', ['action'] )
    op.create_index( 'idx_proxy_decisions_category', 'proxy_decisions', ['category'] )
    op.create_index( 'idx_proxy_decisions_created_at', 'proxy_decisions', ['created_at'] )
    op.create_index( 'idx_proxy_decisions_data_origin', 'proxy_decisions', ['data_origin'] )
    op.create_index( 'idx_proxy_decisions_domain', 'proxy_decisions', ['domain'] )
    op.create_index( 'idx_proxy_decisions_domain_category', 'proxy_decisions', ['domain', 'category'] )
    op.create_index( 'idx_proxy_decisions_ratification', 'proxy_decisions', ['ratification_state'] )
    # Auto per-column indexes (index=True)
    op.create_index( op.f( 'ix_proxy_decisions_action' ), 'proxy_decisions', ['action'] )
    op.create_index( op.f( 'ix_proxy_decisions_category' ), 'proxy_decisions', ['category'] )
    op.create_index( op.f( 'ix_proxy_decisions_data_origin' ), 'proxy_decisions', ['data_origin'] )
    op.create_index( op.f( 'ix_proxy_decisions_domain' ), 'proxy_decisions', ['domain'] )
    op.create_index( op.f( 'ix_proxy_decisions_notification_id' ), 'proxy_decisions', ['notification_id'] )
    op.create_index( op.f( 'ix_proxy_decisions_ratification_state' ), 'proxy_decisions', ['ratification_state'] )
    op.create_index( op.f( 'ix_proxy_decisions_sender_id' ), 'proxy_decisions', ['sender_id'] )

    # ------------------------------------------------------------------
    # Table 2: trust_states  (TrustState)
    # ------------------------------------------------------------------
    op.create_table(
        'trust_states',
        sa.Column( 'id', postgresql.UUID( as_uuid=True ), nullable=False, server_default=sa.text( 'gen_random_uuid()' ) ),
        sa.Column( 'user_email', sa.String( 255 ), nullable=False ),
        sa.Column( 'domain', sa.String( 50 ), nullable=False ),
        sa.Column( 'category', sa.String( 100 ), nullable=False ),
        sa.Column( 'trust_level', sa.Integer(), nullable=False ),
        sa.Column( 'total_decisions', sa.Integer(), nullable=False ),
        sa.Column( 'successful_decisions', sa.Integer(), nullable=False ),
        sa.Column( 'rejected_decisions', sa.Integer(), nullable=False ),
        sa.Column( 'circuit_breaker_state', postgresql.JSONB(), nullable=True ),
        sa.Column( 'created_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'now()' ) ),
        sa.Column( 'updated_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'now()' ) ),
        sa.PrimaryKeyConstraint( 'id' ),
    )
    # Named indexes (__table_args__)
    op.create_index( 'idx_trust_states_category', 'trust_states', ['category'] )
    op.create_index( 'idx_trust_states_user_domain', 'trust_states', ['user_email', 'domain'] )
    op.create_index( 'idx_trust_states_user_domain_category', 'trust_states', ['user_email', 'domain', 'category'], unique=True )
    # Auto per-column indexes (index=True)
    op.create_index( op.f( 'ix_trust_states_category' ), 'trust_states', ['category'] )
    op.create_index( op.f( 'ix_trust_states_domain' ), 'trust_states', ['domain'] )
    op.create_index( op.f( 'ix_trust_states_user_email' ), 'trust_states', ['user_email'] )

    # ------------------------------------------------------------------
    # Table 3: prediction_log  (PredictionLog; FK -> notifications.id CASCADE)
    # ------------------------------------------------------------------
    op.create_table(
        'prediction_log',
        sa.Column( 'id', postgresql.UUID( as_uuid=True ), nullable=False, server_default=sa.text( 'gen_random_uuid()' ) ),
        sa.Column( 'notification_id', postgresql.UUID( as_uuid=True ), nullable=False ),
        sa.Column( 'response_type', sa.String( 50 ), nullable=False ),
        sa.Column( 'category', sa.String( 100 ), nullable=False ),
        sa.Column( 'predicted_value', postgresql.JSONB(), nullable=True ),
        sa.Column( 'prediction_confidence', sa.Float(), nullable=False ),
        sa.Column( 'prediction_strategy', sa.String( 50 ), nullable=False ),
        sa.Column( 'similar_case_count', sa.Integer(), nullable=False ),
        sa.Column( 'actual_value', postgresql.JSONB(), nullable=True ),
        sa.Column( 'accuracy_match', sa.Boolean(), nullable=True ),
        sa.Column( 'accuracy_detail', postgresql.JSONB(), nullable=True ),
        sa.Column( 'predicted_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'now()' ) ),
        sa.Column( 'responded_at', sa.DateTime( timezone=True ), nullable=True ),
        sa.Column( 'sender_id', sa.String( 255 ), nullable=True ),
        sa.ForeignKeyConstraint( ['notification_id'], ['notifications.id'], ondelete='CASCADE' ),
        sa.PrimaryKeyConstraint( 'id' ),
    )
    # Named indexes (__table_args__)
    op.create_index( 'idx_prediction_log_predicted_at', 'prediction_log', ['predicted_at'] )
    op.create_index( 'idx_prediction_log_response_type_category', 'prediction_log', ['response_type', 'category'] )
    # Auto per-column indexes (index=True)
    op.create_index( op.f( 'ix_prediction_log_accuracy_match' ), 'prediction_log', ['accuracy_match'] )
    op.create_index( op.f( 'ix_prediction_log_category' ), 'prediction_log', ['category'] )
    op.create_index( op.f( 'ix_prediction_log_notification_id' ), 'prediction_log', ['notification_id'] )
    op.create_index( op.f( 'ix_prediction_log_response_type' ), 'prediction_log', ['response_type'] )
    op.create_index( op.f( 'ix_prediction_log_sender_id' ), 'prediction_log', ['sender_id'] )

    # ------------------------------------------------------------------
    # Table 4: server_lifecycle  (ServerLifecycle; singleton row, PK only)
    # ------------------------------------------------------------------
    op.create_table(
        'server_lifecycle',
        sa.Column( 'key', sa.String( 32 ), nullable=False ),
        sa.Column( 'last_available_at', sa.DateTime( timezone=True ), nullable=False ),
        sa.Column( 'updated_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'now()' ) ),
        sa.PrimaryKeyConstraint( 'key' ),
    )

    # ------------------------------------------------------------------
    # notifications: add the 5 missing columns + their per-column indexes
    # (direction/sender_persona/sender_icon/reply_to/thread_id already
    #  added by c3d4e5f6a7b8 -- NOT re-added here)
    # ------------------------------------------------------------------
    op.add_column( 'notifications', sa.Column( 'job_id', sa.String( 256 ), nullable=True ) )
    op.add_column( 'notifications', sa.Column( 'progress_group_id', sa.String( 24 ), nullable=True ) )
    op.add_column( 'notifications', sa.Column( 'abstract', sa.Text(), nullable=True ) )
    op.add_column( 'notifications', sa.Column( 'response_options', postgresql.JSONB(), nullable=True ) )
    op.add_column( 'notifications', sa.Column( 'is_hidden', sa.Boolean(), nullable=False, server_default='false' ) )
    op.create_index( op.f( 'ix_notifications_job_id' ), 'notifications', ['job_id'] )
    op.create_index( op.f( 'ix_notifications_progress_group_id' ), 'notifications', ['progress_group_id'] )
    op.create_index( op.f( 'ix_notifications_is_hidden' ), 'notifications', ['is_hidden'] )


def downgrade() -> None:
    """Reverse upgrade(): drop the 5 notifications columns + the 4 tables."""

    # notifications columns (indexes drop with the columns, but be explicit)
    op.drop_index( op.f( 'ix_notifications_is_hidden' ), table_name='notifications' )
    op.drop_index( op.f( 'ix_notifications_progress_group_id' ), table_name='notifications' )
    op.drop_index( op.f( 'ix_notifications_job_id' ), table_name='notifications' )
    op.drop_column( 'notifications', 'is_hidden' )
    op.drop_column( 'notifications', 'response_options' )
    op.drop_column( 'notifications', 'abstract' )
    op.drop_column( 'notifications', 'progress_group_id' )
    op.drop_column( 'notifications', 'job_id' )

    # Tables (drop_table cascades each table's own indexes). prediction_log
    # carries the FK to notifications, so drop it first; the other three are
    # independent.
    op.drop_table( 'prediction_log' )
    op.drop_table( 'server_lifecycle' )
    op.drop_table( 'trust_states' )
    op.drop_table( 'proxy_decisions' )
