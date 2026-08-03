"""Add pgvector extension + vector-store tables (v0.2.0 LanceDB → Postgres)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-01 16:30:00.000000

Creates the pgvector `vector` extension and the 8 vector-store tables that
replace the LanceDB backend (7 with `vector(768)` columns + `gist_cache`, which
is relational-only per the P0 inventory). The 4 ANN-searched columns get an HNSW
index with the `vector_ip_ops` (dot / inner-product) opclass — mirroring the live
LanceDB `.metric("dot")` search EXACTLY (NOT cosine; the keystone vectors are not
L2-normalized). See:
  - src/rnd/v0.2.0/2026.06.30-lancedb-to-postgres-pgvector-migration-design.md §4.2
  - src/rnd/v0.2.0/2026.07.01-lane-a-p0-live-lancedb-schema-inventory.md

Single source of truth: the table + index DDL is driven from the ORM models in
cosa.rest.db.vector_store_models (registered on Base.metadata), so the migration
can never drift from the models. Selective `create_all(checkfirst=True)` keeps
this idempotent — a re-run against a DB already holding the tables is a no-op,
matching the same idempotency contract as the create_all-bootstrap path.

HARD PREREQUISITE (shared-infra, gated): the Postgres image MUST bundle pgvector
(docker-compose → pgvector/pgvector:pg16; Cloud-SQL supports it natively). On the
stock postgres:16.3-alpine image `CREATE EXTENSION vector` fails — apply only
after the image force-recreate.

Note on HNSW build cost (design §11): these indexes are created on EMPTY tables
here (fresh-start), so build is cheap. The one-time offline backfill utility
(Lane D / P4) is where "build index AFTER bulk load + tune maintenance_work_mem"
applies for the 190k-row input_and_output keystone.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _vector_store_tables():
    """
    Return the ordered list of vector-store Table objects from the ORM metadata.

    Ensures:
        - importing the models registers them on Base.metadata (tail import in
          postgres_models) so the returned tables carry the Vector columns +
          HNSW/btree index definitions verbatim
        - order follows VECTOR_STORE_MODELS (parents-free; no FKs between them)
    """
    from cosa.rest.postgres_models import Base
    from cosa.rest.db.vector_store_models import VECTOR_STORE_MODELS
    names = [ m.__tablename__ for m in VECTOR_STORE_MODELS ]
    return [ Base.metadata.tables[ n ] for n in names ]


def upgrade() -> None:
    """Enable pgvector + create the 8 vector-store tables and their indexes.

    IDEMPOTENT: the extension uses IF NOT EXISTS; table creation is guarded with
    checkfirst=True (skips any table already present from a create_all bootstrap).
    """
    bind = op.get_bind()

    # 1) The `vector` type must exist before any Vector column is created.
    op.execute( "CREATE EXTENSION IF NOT EXISTS vector" )

    # 2) Create exactly the vector-store tables (+ their HNSW/btree indexes),
    #    idempotently. Driven from the ORM models — never hand-duplicated DDL.
    tables = _vector_store_tables()
    for table in tables:
        table.create( bind=bind, checkfirst=True )


def downgrade() -> None:
    """Drop the 8 vector-store tables (reverse order); leave the extension.

    IDEMPOTENT: each table is dropped with checkfirst=True. The `vector` extension
    is deliberately NOT dropped — other/future objects may depend on it, and
    DROP EXTENSION is a heavier, riskier operation best left to an explicit
    operator teardown at end-of-migration-arc.
    """
    bind = op.get_bind()
    for table in reversed( _vector_store_tables() ):
        table.drop( bind=bind, checkfirst=True )
