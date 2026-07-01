"""
SQLAlchemy ORM models for the pgvector vector store (v0.2.0 LanceDB → Postgres migration).

Mirrors the shape of the LIVE LanceDB tables (grounded in the P0 inventory —
src/rnd/v0.2.0/2026.07.01-lane-a-p0-live-lancedb-schema-inventory.md) onto the
SAME declarative ``Base`` used by ``cosa.rest.postgres_models`` so these tables
register in ``Base.metadata`` for both alembic autogenerate and the empty-DB
``create_all`` bootstrap.

Metric ruling (design §4.2, Pass-1 F1 + Pass-2 H2, confirmed by P0):
    Live LanceDB search uses ``.metric("dot")`` on every ANN column. The safe
    pgvector mirror is INNER-PRODUCT (``vector_ip_ops`` / the ``<#>`` operator),
    NOT cosine — the keystone ``input_and_output`` vectors are NOT L2-normalized
    (live norm ≈ 22); dot is correct because it is the IDENTICAL metric, not
    because of any normalization invariant. NEVER substitute cosine ``<=>``.

Index rule (design §4.2, per-column, gated on "is it ANN-searched?"):
    Only the 4 columns actually ANN-searched get an HNSW ``vector_ip_ops`` index:
        - input_and_output.input_embedding          (input_and_output_table.py:303)
        - prediction_decisions.question_embedding    (proxy_decision_embeddings.py:227)
        - solution_snapshots.question_embedding      (lancedb_solution_manager.py:1382)
        - solution_snapshots.code_embedding          (lancedb_solution_manager.py:1502)
    Scalar KV lookup keys get btree; write-only telemetry / never-searched vectors
    get NO index until a real ANN consumer appears.

Synthetic-PK note (Rachel review N1): the four tables whose LanceDB source carried
no natural key — ``input_and_output``, ``question_embeddings``, ``embedding_cache``,
``gist_cache`` — get a synthetic ``BigInteger autoincrement`` surrogate PK (Postgres
requires a primary key; LanceDB did not). Tables with an authoritative natural key
(``canonical_synonyms``, ``query_log``, ``prediction_decisions``, ``solution_snapshots``)
keep that key as their PK instead.

Created: 2026-07-01 (Lane A · Tiffany 💍) · v0.2.0
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    String,
    Text,
    Boolean,
    Float,
    Integer,
    BigInteger,
    DateTime,
    Index,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

# Import the shared declarative Base so these tables land in the same metadata
# that env.py / auto_migrate already consume. (postgres_models imports THIS module
# at its tail to guarantee registration — see the note there.)
from cosa.rest.postgres_models import Base


# --------------------------------------------------------------------------- #
# Module constants — single source of truth for dim + HNSW params.
# EMBEDDING_DIM is grounded: EVERY live LanceDB vector column is dim 768 (P0).
# HNSW params mirror pgvector defaults; design §4.4 promotes them to config keys
# (`vector index m` / `ef_construction`) at the config layer (Lane A §4.4 / P2).
# --------------------------------------------------------------------------- #
EMBEDDING_DIM        = 768
HNSW_M               = 16
HNSW_EF_CONSTRUCTION = 64

# Opclass constant so the metric ruling lives in exactly one place.
_IP_OPS = "vector_ip_ops"   # inner-product (dot); the `<#>` operator's opclass


def _hnsw_index( index_name, column_name ):
    """
    Build an HNSW inner-product (dot) index descriptor for one vector column.

    Requires:
        - index_name is a unique, non-empty index identifier
        - column_name names a ``Vector`` column on the owning table

    Ensures:
        - returns a SQLAlchemy ``Index`` using method ``hnsw`` with the
          ``vector_ip_ops`` opclass and the module HNSW build params
    """
    return Index(
        index_name,
        column_name,
        postgresql_using = "hnsw",
        postgresql_ops   = { column_name: _IP_OPS },
        postgresql_with  = { "m": HNSW_M, "ef_construction": HNSW_EF_CONSTRUCTION },
    )


# =========================================================================== #
# 1. input_and_output — keystone solution/IO store (LanceDB: input_and_output_tbl,
#    190,677 rows). ONLY input_embedding is ANN-searched (HNSW dot).
# =========================================================================== #
class InputAndOutput( Base ):
    """Keystone input/output store; the sole design-scope ANN table."""
    __tablename__ = "input_and_output"

    id:                     Mapped[int]            = mapped_column( BigInteger, primary_key=True, autoincrement=True )
    date:                   Mapped[Optional[str]]  = mapped_column( Text )
    time:                   Mapped[Optional[str]]  = mapped_column( Text )
    input_type:             Mapped[Optional[str]]  = mapped_column( Text )
    input:                  Mapped[Optional[str]]  = mapped_column( Text )
    input_embedding:        Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )
    output_raw:             Mapped[Optional[str]]  = mapped_column( Text )
    output_final:           Mapped[Optional[str]]  = mapped_column( Text )
    output_final_embedding: Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )
    solution_path_wo_root:  Mapped[Optional[str]]  = mapped_column( Text )

    __table_args__ = (
        # ANN target — the only HNSW dot index on this table.
        _hnsw_index( "idx_input_and_output_input_embedding_hnsw", "input_embedding" ),
        # output_final_embedding: not ANN-searched → deliberately NO index.
    )


# =========================================================================== #
# 2. question_embeddings — text→embedding cache (KV get-by-text). No vector index.
# =========================================================================== #
class QuestionEmbedding( Base ):
    """question→embedding cache; exact-match KV, btree on the question key."""
    __tablename__ = "question_embeddings"

    id:        Mapped[int]            = mapped_column( BigInteger, primary_key=True, autoincrement=True )
    question:  Mapped[Optional[str]]  = mapped_column( Text )
    embedding: Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )

    __table_args__ = (
        Index( "idx_question_embeddings_question", "question" ),
    )


# =========================================================================== #
# 3. embedding_cache — normalized_text→embedding cache. No vector index.
# =========================================================================== #
class EmbeddingCache( Base ):
    """text→embedding cache; exact-match KV, btree on normalized_text."""
    __tablename__ = "embedding_cache"

    id:              Mapped[int]            = mapped_column( BigInteger, primary_key=True, autoincrement=True )
    normalized_text: Mapped[Optional[str]]  = mapped_column( Text )
    embedding:       Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )

    __table_args__ = (
        Index( "idx_embedding_cache_normalized_text", "normalized_text" ),
    )


# =========================================================================== #
# 4. gist_cache — RELATIONAL ONLY (P0: no vector column). Plain scalar cache.
# =========================================================================== #
class GistCache( Base ):
    """gist/summary cache; NO pgvector column (P0-confirmed relational-only)."""
    __tablename__ = "gist_cache"

    id:                  Mapped[int]           = mapped_column( BigInteger, primary_key=True, autoincrement=True )
    question_verbatim:   Mapped[Optional[str]] = mapped_column( Text )
    question_normalized: Mapped[Optional[str]] = mapped_column( Text )
    question_gist:       Mapped[Optional[str]] = mapped_column( Text )
    created_date:        Mapped[Optional[str]] = mapped_column( Text )   # live LanceDB stored this as string
    access_count:        Mapped[Optional[int]] = mapped_column( Integer )
    last_accessed:       Mapped[Optional[str]] = mapped_column( Text )   # live LanceDB stored this as string

    __table_args__ = (
        Index( "idx_gist_cache_question_normalized", "question_normalized" ),
    )


# =========================================================================== #
# 5. canonical_synonyms — synonym canonicalization. Exact-match .where lookups,
#    NOT ANN — so NO vector index on any of the 3 embedding columns.
# =========================================================================== #
class CanonicalSynonym( Base ):
    """synonym canonicalization; 3 vectors used for exact-match, no HNSW."""
    __tablename__ = "canonical_synonyms"

    id:                   Mapped[str]            = mapped_column( String( 255 ), primary_key=True )
    snapshot_id:          Mapped[Optional[str]]  = mapped_column( Text )
    question_verbatim:    Mapped[Optional[str]]  = mapped_column( Text )
    question_normalized:  Mapped[Optional[str]]  = mapped_column( Text )
    question_gist:        Mapped[Optional[str]]  = mapped_column( Text )
    embedding_verbatim:   Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )
    embedding_normalized: Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )
    embedding_gist:       Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )
    confidence_score:     Mapped[Optional[float]]    = mapped_column( Float )
    usage_count:          Mapped[Optional[int]]      = mapped_column( Integer )
    last_matched:         Mapped[Optional[datetime]] = mapped_column( DateTime )
    created_date:         Mapped[Optional[datetime]] = mapped_column( DateTime )
    source:               Mapped[Optional[str]]      = mapped_column( Text )

    __table_args__ = (
        Index( "idx_canonical_synonyms_snapshot_id", "snapshot_id" ),
        Index( "idx_canonical_synonyms_question_normalized", "question_normalized" ),
    )


# =========================================================================== #
# 6. query_log — write-only query telemetry. Vectors are NOT searched → NO index.
#    F6: live column is normalization_version (underscore) — the space is only in
#    the legacy create-table code; the fresh-start Postgres column is underscore.
# =========================================================================== #
class QueryLog( Base ):
    """query telemetry; write-only, 3 unsearched vectors → no vector index."""
    __tablename__ = "query_log"

    id:                    Mapped[str]            = mapped_column( String( 255 ), primary_key=True )
    timestamp:             Mapped[Optional[datetime]] = mapped_column( DateTime )
    user_id:               Mapped[Optional[str]]  = mapped_column( Text )
    session_id:            Mapped[Optional[str]]  = mapped_column( Text )
    query_verbatim:        Mapped[Optional[str]]  = mapped_column( Text )
    query_normalized:      Mapped[Optional[str]]  = mapped_column( Text )
    query_gist:            Mapped[Optional[str]]  = mapped_column( Text )
    embedding_verbatim:    Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )
    embedding_normalized:  Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )
    embedding_gist:        Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )
    matched_snapshot_id:   Mapped[Optional[str]]  = mapped_column( Text )
    match_type:            Mapped[Optional[str]]  = mapped_column( Text )
    match_confidence:      Mapped[Optional[float]] = mapped_column( Float )
    processing_time_ms:    Mapped[Optional[int]]  = mapped_column( Integer )
    input_type:            Mapped[Optional[str]]  = mapped_column( Text )
    user_satisfaction:     Mapped[Optional[str]]  = mapped_column( Text )
    normalization_version: Mapped[Optional[str]]  = mapped_column( Text )   # F6: underscore, no quoting
    gist_model_version:    Mapped[Optional[str]]  = mapped_column( Text )
    cache_hit_verbatim:    Mapped[Optional[bool]] = mapped_column( Boolean )
    cache_hit_normalized:  Mapped[Optional[bool]] = mapped_column( Boolean )
    cache_hit_gist:        Mapped[Optional[bool]] = mapped_column( Boolean )

    __table_args__ = (
        Index( "idx_query_log_session_id", "session_id" ),
        Index( "idx_query_log_timestamp", "timestamp" ),
    )


# =========================================================================== #
# 7. prediction_decisions — decision-proxy VECTOR store (LanceDB-only; the
#    Postgres proxy_decisions table is a SEPARATE relational log with no vector
#    search). question_embedding IS ANN-searched (HNSW dot). Mirrored 1:1 — NOT
#    folded into proxy_decisions (that unification is a future Lane C decision).
# =========================================================================== #
class PredictionDecision( Base ):
    """decision-proxy embedding store; question_embedding ANN-searched (HNSW dot)."""
    __tablename__ = "prediction_decisions"

    id:                 Mapped[str]            = mapped_column( String( 255 ), primary_key=True )
    question:           Mapped[Optional[str]]  = mapped_column( Text )
    category:           Mapped[Optional[str]]  = mapped_column( Text )
    decision_value:     Mapped[Optional[str]]  = mapped_column( Text )
    ratification_state: Mapped[Optional[str]]  = mapped_column( Text )
    data_origin:        Mapped[Optional[str]]  = mapped_column( Text )
    response_type:      Mapped[Optional[str]]  = mapped_column( Text )
    question_embedding: Mapped[Optional[list]] = mapped_column( Vector( EMBEDDING_DIM ) )
    created_at:         Mapped[Optional[str]]  = mapped_column( Text )   # live LanceDB stored created_at as string

    __table_args__ = (
        _hnsw_index( "idx_prediction_decisions_question_embedding_hnsw", "question_embedding" ),
        Index( "idx_prediction_decisions_category", "category" ),
    )


# =========================================================================== #
# 8. solution_snapshots — lancedb_solution_manager store (DISTINCT from
#    input_and_output). 7 vector columns; question_embedding + code_embedding are
#    ANN-searched (HNSW dot); the other 5 are not searched → no index.
# =========================================================================== #
class SolutionSnapshot( Base ):
    """solution-snapshot store; question_embedding + code_embedding ANN (HNSW dot)."""
    __tablename__ = "solution_snapshots"

    id_hash:                     Mapped[str]                 = mapped_column( String( 255 ), primary_key=True )
    user_id:                     Mapped[Optional[str]]       = mapped_column( Text )
    question:                    Mapped[Optional[str]]       = mapped_column( Text )
    question_normalized:         Mapped[Optional[str]]       = mapped_column( Text )
    question_gist:               Mapped[Optional[str]]       = mapped_column( Text )
    answer:                      Mapped[Optional[str]]       = mapped_column( Text )
    answer_conversational:       Mapped[Optional[str]]       = mapped_column( Text )
    solution_summary:            Mapped[Optional[str]]       = mapped_column( Text )
    thoughts:                    Mapped[Optional[str]]       = mapped_column( Text )
    error:                       Mapped[Optional[str]]       = mapped_column( Text )
    routing_command:             Mapped[Optional[str]]       = mapped_column( Text )
    agent_class_name:            Mapped[Optional[str]]       = mapped_column( Text )
    code:                        Mapped[Optional[List[str]]] = mapped_column( ARRAY( Text ) )   # LanceDB list<string>
    solution_summary_gist:       Mapped[Optional[str]]       = mapped_column( Text )
    code_returns:                Mapped[Optional[str]]       = mapped_column( Text )
    code_example:                Mapped[Optional[str]]       = mapped_column( Text )
    code_type:                   Mapped[Optional[str]]       = mapped_column( Text )
    programming_language:        Mapped[Optional[str]]       = mapped_column( Text )
    language_version:            Mapped[Optional[str]]       = mapped_column( Text )
    synonymous_questions:        Mapped[Optional[str]]       = mapped_column( Text )   # LanceDB string (not a list)
    synonymous_question_gists:   Mapped[Optional[str]]       = mapped_column( Text )   # LanceDB string (not a list)
    non_synonymous_questions:    Mapped[Optional[List[str]]] = mapped_column( ARRAY( Text ) )   # LanceDB list<string>
    last_question_asked:         Mapped[Optional[str]]       = mapped_column( Text )
    created_date:                Mapped[Optional[str]]       = mapped_column( Text )
    updated_date:                Mapped[Optional[str]]       = mapped_column( Text )
    run_date:                    Mapped[Optional[str]]       = mapped_column( Text )
    runtime_stats:               Mapped[Optional[str]]       = mapped_column( Text )
    replay_history:              Mapped[Optional[str]]       = mapped_column( Text )
    replay_stats:                Mapped[Optional[str]]       = mapped_column( Text )
    is_cache_hit:                Mapped[Optional[bool]]      = mapped_column( Boolean )
    answer_is_correct:           Mapped[Optional[str]]       = mapped_column( Text )
    question_embedding:            Mapped[Optional[list]]    = mapped_column( Vector( EMBEDDING_DIM ) )
    question_normalized_embedding: Mapped[Optional[list]]    = mapped_column( Vector( EMBEDDING_DIM ) )
    question_gist_embedding:       Mapped[Optional[list]]    = mapped_column( Vector( EMBEDDING_DIM ) )
    solution_embedding:            Mapped[Optional[list]]    = mapped_column( Vector( EMBEDDING_DIM ) )
    code_embedding:                Mapped[Optional[list]]    = mapped_column( Vector( EMBEDDING_DIM ) )
    thoughts_embedding:            Mapped[Optional[list]]    = mapped_column( Vector( EMBEDDING_DIM ) )
    solution_gist_embedding:       Mapped[Optional[list]]    = mapped_column( Vector( EMBEDDING_DIM ) )

    __table_args__ = (
        _hnsw_index( "idx_solution_snapshots_question_embedding_hnsw", "question_embedding" ),
        _hnsw_index( "idx_solution_snapshots_code_embedding_hnsw", "code_embedding" ),
    )


# Public registry of the vector-store tables this migration owns — handy for
# tests + the equivalence harness to iterate without re-deriving the list.
VECTOR_STORE_MODELS = [
    InputAndOutput,
    QuestionEmbedding,
    EmbeddingCache,
    GistCache,
    CanonicalSynonym,
    QueryLog,
    PredictionDecision,
    SolutionSnapshot,
]

# The 4 ANN-searched (table, col) pairs that carry an HNSW vector_ip_ops index.
HNSW_DOT_INDEXES = [
    ( "input_and_output",     "input_embedding" ),
    ( "prediction_decisions", "question_embedding" ),
    ( "solution_snapshots",   "question_embedding" ),
    ( "solution_snapshots",   "code_embedding" ),
]
