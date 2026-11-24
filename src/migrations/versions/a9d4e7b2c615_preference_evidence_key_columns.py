"""
Add six nullable key and note columns to preference_evidence

Revision ID: a9d4e7b2c615
Revises: e1b7c4a9d286

The writer stores each column on the evidence row when it writes the row.

- source_key: names the one source behind the row, so status counts copies of a source once.
- condition_key: the canonical form of the condition, so status compares keys with no model call.
- caveat: a short warning for the forecaster, read at retrieval.
- decision_stage: who_decides or what_to_do_once_asked, read at retrieval.
- antecedent: the principle's antecedent as the extractor quoted it, read at retrieval.
- standing_quote: the answer's own words stating a standing rule. NULL means an inferred refusal.

Every column is nullable with no backfill. NULL means none, which is every row written before this revision.
The upgrade adds a column only when its table exists and the column is missing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'a9d4e7b2c615'
down_revision: Union[str, Sequence[str], None] = 'e1b7c4a9d286'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EVIDENCE_TABLE = "preference_evidence"
NAMES          = ( "source_key", "condition_key", "caveat", "decision_stage", "antecedent", "standing_quote" )


def _column_names( inspector, table ) -> set:
    return { column[ "name" ] for column in inspector.get_columns( table ) }


def upgrade() -> None:
    """
    Add the six evidence columns.

    Ensures:
        - nothing is done when the evidence table is absent (a database built from the models has the columns already)
        - each column is added only when missing (re-run safe, and a half-applied upgrade finishes)
        - no existing row is changed
    """
    inspector = inspect( op.get_bind() )
    if EVIDENCE_TABLE not in inspector.get_table_names(): return
    present = _column_names( inspector, EVIDENCE_TABLE )
    # Literal names, one call each: test_model_migration_drift reads the chain statically and cannot see a loop's names.
    if "source_key"     not in present: op.add_column( EVIDENCE_TABLE, sa.Column( "source_key",     sa.String( 255 ), nullable=True ) )
    if "condition_key"  not in present: op.add_column( EVIDENCE_TABLE, sa.Column( "condition_key",  sa.Text(),        nullable=True ) )
    if "caveat"         not in present: op.add_column( EVIDENCE_TABLE, sa.Column( "caveat",         sa.Text(),        nullable=True ) )
    if "decision_stage" not in present: op.add_column( EVIDENCE_TABLE, sa.Column( "decision_stage", sa.String( 100 ), nullable=True ) )
    if "antecedent"     not in present: op.add_column( EVIDENCE_TABLE, sa.Column( "antecedent",     sa.Text(),        nullable=True ) )
    if "standing_quote" not in present: op.add_column( EVIDENCE_TABLE, sa.Column( "standing_quote", sa.Text(),        nullable=True ) )


def downgrade() -> None:
    """
    Drop the six evidence columns.

    Ensures:
        - nothing is done when the evidence table is absent
        - each drop is guarded, so a partial upgrade downgrades cleanly
    """
    inspector = inspect( op.get_bind() )
    if EVIDENCE_TABLE not in inspector.get_table_names(): return
    present = _column_names( inspector, EVIDENCE_TABLE )
    for name in NAMES:
        if name in present: op.drop_column( EVIDENCE_TABLE, name )
