"""Drop the input_and_output HNSW index — exact-scan ruling (v0.2.0 cutover)

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-07 10:45:00.000000

The keystone `input_and_output` knn path serves via exact scan, not HNSW.
The grounding is in the swap-chain execution log
(src/rnd/v0.1.9/2026.07.07-pgvector-swap-chain-execution.md):

  - The live keystone is 97.2% duplicate vectors (202,012 rows, 5,728 distinct
    embeddings, all notification-pipeline texts). HNSW beam search gets trapped
    in duplicate plateaus. The default ef_search returned wrong neighbors on
    real-query probes. Only the pgvector maximum ef_search=1000 recovered them,
    with no guarantee for unprobed queries.
  - Exact scan is guaranteed LanceDB-parity. At about 481ms median it is 2.7x
    faster than the legacy LanceDB flat scan (about 1,293ms) it replaces.
  - With no vector index on the column, `ORDER BY input_embedding <#> q` falls
    back to an exact seq-scan plus a top-k sort. No dot_topk code change is
    needed.

Revisit: re-introduce HNSW after the notification-spam purge and dedup collapse
the duplicate mass, since 5,728 distinct vectors index cleanly.

The solution_snapshots HNSW indexes stay (35 rows; index irrelevant but
harmless, and the table is not duplicate-pathological).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "idx_input_and_output_input_embedding_hnsw"


def upgrade() -> None:
    """Drop the keystone HNSW index so `<#>` knn serves via exact scan.

    Idempotent: `IF EXISTS` makes a re-run a no-op, as is a fresh DB built from
    the amended models, which no longer declare the index.
    """
    op.execute( f"DROP INDEX IF EXISTS {_INDEX_NAME}" )


def downgrade() -> None:
    """Recreate the HNSW dot index (params from vector_store_models constants)."""
    from cosa.rest.db.vector_store_models import HNSW_M, HNSW_EF_CONSTRUCTION

    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} "
        f"ON input_and_output USING hnsw (input_embedding vector_ip_ops) "
        f"WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})"
    )
