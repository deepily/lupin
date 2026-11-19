"""
Add preference_principles, preference_evidence and prediction_arm_forecast

Revision ID: d3a6c1e8b5f2
Revises: c9e3a7b1d542

Layer 1 of the context-aware preference learner keeps short conditional principles
(preference_principles) and append-only timed evidence for them (preference_evidence). Layer 0 keeps one
forecast row per notification and arm (prediction_arm_forecast), the displayed arm included, beside
prediction_log's single slot per notification.

preference_evidence is unique on ( principle_id, notification_id, field_key, extractor_version, source ).
prediction_arm_forecast is unique on ( notification_id, arm ). Each table is created only when absent,
so a re-run, or a database built from the models, is a safe no-op. The embedding column is pgvector
vector( 768 ), the dimension every other Lupin vector column uses.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd3a6c1e8b5f2'
down_revision: Union[str, Sequence[str], None] = 'c9e3a7b1d542'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PRINCIPLES_TABLE = "preference_principles"
EVIDENCE_TABLE   = "preference_evidence"
ARM_TABLE        = "prediction_arm_forecast"

EVIDENCE_UNIQUE  = "uq_preference_evidence_key"
ARM_UNIQUE       = "uq_prediction_arm_forecast_notification_arm"


def upgrade() -> None:
    """
    Create the three tables.

    Ensures:
        - each table is created only when absent
        - principle_id references preference_principles; notification_id on the arm table references
          notifications and cascades on delete, as prediction_log does
        - the evidence and arm tables carry the unique keys named in the module docstring
    """
    existing = set( sa.inspect( op.get_bind() ).get_table_names() )

    if PRINCIPLES_TABLE not in existing:
        op.create_table(
            'preference_principles',
            sa.Column( 'id', postgresql.UUID( as_uuid=True ), primary_key=True, server_default=sa.text( 'gen_random_uuid()' ) ),
            sa.Column( 'owner_id', sa.String( 64 ), nullable=False ),
            sa.Column( 'kind', sa.String( 20 ), nullable=False ),
            sa.Column( 'dimension', sa.String( 255 ), nullable=False ),
            sa.Column( 'statement', sa.Text(), nullable=False ),
            sa.Column( 'rationale', sa.Text(), nullable=True ),
            sa.Column( 'scope', sa.String( 255 ), nullable=False ),
            sa.Column( 'embedding', Vector( 768 ), nullable=True ),
            sa.Column( 'encoder_version', sa.String( 100 ), nullable=True ),
            sa.Column( 'extractor_version', sa.String( 100 ), nullable=False ),
            sa.Column( 'created_at', sa.DateTime( timezone=True ), nullable=False, server_default=sa.text( 'NOW()' ) )
        )
        op.create_index( 'ix_preference_principles_owner_id', 'preference_principles', [ 'owner_id' ] )

    if EVIDENCE_TABLE not in existing:
        op.create_table(
            'preference_evidence',
            sa.Column( 'id', postgresql.UUID( as_uuid=True ), primary_key=True, server_default=sa.text( 'gen_random_uuid()' ) ),
            sa.Column( 'principle_id', postgresql.UUID( as_uuid=True ), sa.ForeignKey( 'preference_principles.id' ), nullable=False ),
            sa.Column( 'notification_id', postgresql.UUID( as_uuid=True ), nullable=False ),
            sa.Column( 'field_key', sa.String( 255 ), nullable=False ),
            sa.Column( 'relation', sa.String( 20 ), nullable=False ),
            sa.Column( 'condition', sa.Text(), nullable=True ),
            sa.Column( 'answered_at', sa.DateTime( timezone=True ), nullable=False ),
            sa.Column( 'extracted_at', sa.DateTime( timezone=True ), nullable=False ),
            sa.Column( 'extractor_version', sa.String( 100 ), nullable=False ),
            sa.Column( 'retracted_at', sa.DateTime( timezone=True ), nullable=True ),
            sa.Column( 'source', sa.String( 20 ), nullable=False ),
            sa.UniqueConstraint( 'principle_id', 'notification_id', 'field_key', 'extractor_version', 'source', name='uq_preference_evidence_key' )
        )
        op.create_index( 'ix_preference_evidence_principle_id', 'preference_evidence', [ 'principle_id' ] )
        op.create_index( 'ix_preference_evidence_notification_id', 'preference_evidence', [ 'notification_id' ] )

    if ARM_TABLE not in existing:
        op.create_table(
            'prediction_arm_forecast',
            sa.Column( 'id', postgresql.UUID( as_uuid=True ), primary_key=True, server_default=sa.text( 'gen_random_uuid()' ) ),
            sa.Column( 'notification_id', postgresql.UUID( as_uuid=True ), sa.ForeignKey( 'notifications.id', ondelete='CASCADE' ), nullable=False ),
            sa.Column( 'arm', sa.String( 50 ), nullable=False ),
            sa.Column( 'predictor_version', sa.String( 100 ), nullable=True ),
            sa.Column( 'forecast', postgresql.JSONB(), nullable=True ),
            sa.Column( 'input_cutoff', sa.DateTime( timezone=True ), nullable=True ),
            sa.Column( 'evidence_ids', postgresql.JSONB(), nullable=True ),
            sa.Column( 'forecast_ready_at', sa.DateTime( timezone=True ), nullable=True ),
            sa.Column( 'abstention_reason', sa.Text(), nullable=True ),
            sa.Column( 'displayed', sa.Boolean(), nullable=False, server_default=sa.text( 'false' ) ),
            sa.UniqueConstraint( 'notification_id', 'arm', name='uq_prediction_arm_forecast_notification_arm' )
        )
        op.create_index( 'ix_prediction_arm_forecast_notification_id', 'prediction_arm_forecast', [ 'notification_id' ] )


def downgrade() -> None:
    """
    Drop the three tables, evidence first, only when present.

    Ensures:
        - a partial upgrade downgrades cleanly
    """
    existing = set( sa.inspect( op.get_bind() ).get_table_names() )
    for table in ( ARM_TABLE, EVIDENCE_TABLE, PRINCIPLES_TABLE ):
        if table in existing:
            op.drop_table( table )
