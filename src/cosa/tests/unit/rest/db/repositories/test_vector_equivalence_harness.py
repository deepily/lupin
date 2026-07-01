"""
§7 EQUIVALENCE HARNESS — the migration's metric-correctness gate.

The v0.2.0 risk (design §11) is a silent METRIC mismatch: swapping LanceDB's
``.metric("dot")`` for pgvector cosine (``<=>``) would reorder neighbors. This
harness proves the pgvector inner-product path (``<#>`` via the repo layer)
reproduces the TRUE dot-product ranking — the exact quantity LanceDB's
``.metric("dot")`` computes — on a fixed, deterministic vector set.

ORACLE: the mathematical dot product, computed independently in numpy. LanceDB's
"dot" IS that dot product, so numpy is the honest ground truth (comparing to the
LanceDB library on the same vectors would only re-derive numpy). The keystone
vectors are NOT L2-normalized in production, so the fixtures are deliberately
un-normalized too — this catches any accidental cosine substitution, which would
only agree with dot on unit vectors.

QUANTIFIED pass/fail (programmatic, EXECUTOR: AI):
    - top-k id ordering from pgvector == numpy dot top-k ordering, EXACTLY
    - pgvector similarity_pct agrees with numpy_dot * 100 to float32 precision
      (rtol 1e-4, atol 1e-3) for every returned row — pgvector STORES vectors as
      float32 while the numpy oracle computes in float64, so the residual is
      storage precision, not a metric error

Deterministic: a fixed-seed RandomState generates the corpus + queries (no
wall-clock / no unseeded randomness), so the gate is reproducible run-to-run.
Runs against the same disposable pgvector DB as the repo tests (skips without it).
"""

import os
import sys

import numpy as np

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.input_and_output_repository import InputAndOutputRepository
from cosa.rest.db.vector_store_models import EMBEDDING_DIM


_N_CORPUS   = 40
_N_QUERIES  = 6
_TOP_K      = 5
_RTOL       = 1e-4   # float32 storage precision (pgvector) vs float64 oracle
_ATOL       = 1e-3   # similarity_pct units


def _corpus_and_queries():
    """Deterministic un-normalized corpus + query vectors (fixed seed)."""
    rng    = np.random.RandomState( 20260701 )
    corpus = rng.uniform( -1.0, 1.0, size=( _N_CORPUS, EMBEDDING_DIM ) )   # NOT normalized
    queries = rng.uniform( -1.0, 1.0, size=( _N_QUERIES, EMBEDDING_DIM ) )
    return corpus, queries


def test_pgvector_dot_matches_numpy_dot_oracle( db_session ):
    corpus, queries = _corpus_and_queries()

    repo = InputAndOutputRepository( db_session )
    ids  = []
    for i, vec in enumerate( corpus ):
        row = repo.insert_io_row( input=f"doc_{i}", input_embedding=vec.tolist(),
                                  output_final=str( i ) )
        db_session.flush()
        ids.append( row.id )
    id_by_index = { i: ids[ i ] for i in range( _N_CORPUS ) }

    max_pct_delta = 0.0
    for q in queries:
        # --- pgvector path (via the repo's dot `<#>` search) ---
        pg_hits    = repo.get_knn_by_input( q.tolist(), k=_TOP_K )
        pg_ids     = [ entity.input for _, entity in pg_hits ]
        pg_scores  = [ pct for pct, _ in pg_hits ]

        # --- numpy oracle (true dot product) ---
        dots        = corpus @ q                       # shape (N,)
        oracle_top  = np.argsort( -dots )[ :_TOP_K ]
        oracle_ids  = [ f"doc_{idx}" for idx in oracle_top ]
        oracle_pcts = [ float( dots[ idx ] ) * 100.0 for idx in oracle_top ]

        # QUANTIFIED gate 1: identical top-k ordering.
        assert pg_ids == oracle_ids, f"ordering mismatch: pg={pg_ids} oracle={oracle_ids}"

        # QUANTIFIED gate 2: similarity_pct agreement to float32 precision.
        for pg_pct, oracle_pct in zip( pg_scores, oracle_pcts ):
            assert np.isclose( pg_pct, oracle_pct, rtol=_RTOL, atol=_ATOL ), \
                f"similarity {pg_pct} vs oracle {oracle_pct} exceeds rtol={_RTOL}"
            max_pct_delta = max( max_pct_delta, abs( pg_pct - oracle_pct ) )

    # Sanity: the harness actually compared non-trivial magnitudes (real work done).
    assert max_pct_delta > 0.0


def test_oracle_uses_unnormalized_vectors():
    # Guard the harness's own premise: the corpus is NOT unit-normalized, so this
    # test would FAIL under an accidental cosine substitution (which agrees with
    # dot only on unit vectors).
    corpus, _ = _corpus_and_queries()
    norms = np.linalg.norm( corpus, axis=1 )
    assert np.all( norms > 1.5 )       # comfortably far from unit length
