"""
Shared dot-product (inner-product) nearest-k search for the pgvector repos.

Metric ruling (design §4.2, P0-confirmed): the live LanceDB path searches with
``.metric("dot")`` on every ANN column, and the keystone vectors are NOT
L2-normalized — so the correct pgvector mirror is INNER PRODUCT, the ``<#>``
operator (``max_inner_product`` in pgvector's SQLAlchemy binding), NEVER cosine
``<=>``.

Similarity scale parity with LanceDB:
    LanceDB dot search reports ``_distance = 1 - dot`` and callers derive
    ``similarity_pct = (1 - _distance) * 100 = dot * 100``.
    pgvector's ``<#>`` returns the NEGATIVE inner product, so
    ``dot = -(col <#> q)`` and therefore ``similarity_pct = -(col <#> q) * 100``.
    This module returns that same ``dot * 100`` scale so thresholds + the
    equivalence harness compare like-for-like against the LanceDB path.

``metric="cosine"`` — added 2026-08-02 (bug 78f21b1b), Rick's ruling
------------------------------------------------------------------
``dot * 100`` is a PERCENTAGE ONLY IF BOTH VECTORS ARE UNIT LENGTH. That held
when embeddings came from OpenAI ``text-embedding-3-small``, which returns
L2-normalized vectors — for unit vectors dot IS cosine. It stopped holding when
the provider moved to the local ``nomic-ai`` models, which do not normalize:
measured query norm **19.809** against stored (OpenAI-era) rows at norm 1.000.

Same arithmetic, ~20x the number. A live voice question scored **1024.15%** for a
true cosine of **0.517**, and the caller's ``>= 100.0`` branch read that as a
PERFECT EXACT MATCH — so an unrelated cached row was replayed instead of routing
to an agent. Nothing failed loudly because both models emit 768 dimensions: the
vectors stayed shape-compatible while becoming scale-incompatible.

``metric="cosine"`` divides by BOTH norms (pgvector ``<=>``), so the score is
correct regardless of either side's vector length — including for future
embedding models, normalized or not. That is the point: the previous convention
depended on an unwritten, untested precondition that silently left.

⚠️ The ``dot`` default is UNCHANGED and remains correct for callers whose
thresholds were tuned against it (proxy decisions, input_and_output). This is
opt-in per caller, not a global re-scale. The metric ruling above still governs
the INDEX opclass (``vector_ip_ops``); a cosine search does not use that index,
which is irrelevant at snapshot-table scale and noted here so it is not
rediscovered as a mystery.

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session


def dot_topk(
    session:         Session,
    model:           Any,
    vector_column:   Any,
    query_embedding: List[float],
    limit:           int,
    exclude_filter:  Optional[Any] = None,
    threshold_pct:   Optional[float] = None,
    clamp:           bool = False,
    metric:          str = "dot",
) -> List[Tuple[float, Any]]:
    """
    Return the top-``limit`` rows of ``model`` by descending dot product against
    ``query_embedding`` on ``vector_column`` — the pgvector mirror of LanceDB's
    ``.search(...).metric("dot").limit(k)``.

    Requires:
        - session is an active SQLAlchemy Session
        - model is a mapped vector-store class; vector_column is one of its
          ``Vector`` columns
        - query_embedding is a list of floats matching the column dimension
        - limit is a positive int

    Ensures:
        - orders by ``vector_column <#> query_embedding`` ASC (strongest dot first)
          and returns at most ``limit`` rows AFTER applying ``exclude_filter``
        - each element is ``( similarity_pct, entity )`` with
          ``similarity_pct = -(col <#> q) * 100`` (i.e. dot * 100 — LanceDB scale)
        - when clamp is True, similarity_pct is clamped to [0.0, 100.0]
          (mirrors ProxyDecisionEmbeddings.find_similar)
        - when threshold_pct is not None, rows whose similarity_pct <
          threshold_pct are dropped (applied AFTER the limit, as LanceDB does)
        - result is sorted by similarity_pct descending

    Raises:
        - SQLAlchemy exceptions on a malformed query / dimension mismatch
    """
    if metric == "cosine":
        # col <=> q  (= 1 - cosine_similarity), so similarity = 1 - distance.
        # Scale-free by construction: dividing by BOTH norms means neither side's
        # vector length can inflate the score. See the module docstring.
        distance = vector_column.cosine_distance( query_embedding )
    elif metric == "dot":
        distance = vector_column.max_inner_product( query_embedding )   # col <#> q  (= -dot)
    else:
        raise ValueError( f"metric must be 'dot' or 'cosine', got {metric!r}" )

    query = session.query( model, distance.label( "distance" ) )
    if exclude_filter is not None:
        query = query.filter( exclude_filter )

    rows = query.order_by( distance.asc() ).limit( limit ).all()

    results: List[Tuple[float, Any]] = []
    for entity, dist in rows:
        if metric == "cosine":
            similarity_pct = ( 1.0 - float( dist ) ) * 100.0
        else:
            similarity_pct = -float( dist ) * 100.0
        if clamp:
            similarity_pct = max( 0.0, min( 100.0, similarity_pct ) )
        if threshold_pct is not None and similarity_pct < threshold_pct:
            continue
        results.append( ( similarity_pct, entity ) )

    results.sort( key=lambda pair: pair[ 0 ], reverse=True )
    return results
