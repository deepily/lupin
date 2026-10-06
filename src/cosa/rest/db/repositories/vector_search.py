"""
Shared dot-product (inner-product) nearest-k search for the pgvector repos.

Every ANN column is searched by dot product, and the keystone vectors are not normalized to unit length.
So the operator is inner product, ``<#>`` (``max_inner_product`` in pgvector's SQLAlchemy binding).
It is never cosine ``<=>`` by default.

Similarity scale:
    Callers expect ``similarity_pct = dot * 100``. pgvector's ``<#>`` returns the negative inner product.
    So ``dot = -(col <#> q)`` and ``similarity_pct = -(col <#> q) * 100``. This module returns that scale,
    so thresholds and the equivalence harness compare like for like.

``metric="cosine"``:
    ``dot * 100`` is a percentage only if both vectors are unit length. That held for OpenAI
    ``text-embedding-3-small``, which returns unit-length vectors, where dot is cosine. It stopped
    holding with the local ``nomic-ai`` models, which do not normalize: a measured query norm of
    19.809 against stored rows at norm 1.000.

    The score then came out about 20 times too high. A live question scored 1024.15% for a true cosine of
    0.517. The caller's ``>= 100.0`` branch read that as a perfect exact match, so an unrelated
    cached row was replayed. Nothing failed loudly because both models emit 768 dimensions: the vectors
    stayed shape-compatible while becoming scale-incompatible.

    ``metric="cosine"`` divides by both norms (pgvector ``<=>``), so the score is correct whatever
    either side's vector length, normalized or not. The ``dot`` convention depended on an unwritten,
    untested precondition.

The ``dot`` default is unchanged and stays correct for callers whose thresholds were tuned against it
(proxy decisions, input_and_output). Cosine is opt-in per caller, not a global re-scale. The index
opclass (``vector_ip_ops``) is still inner product. A cosine search does not use that index, which
is irrelevant at snapshot-table scale.
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
    Return the top-``limit`` rows of ``model`` nearest to ``query_embedding``.

    Requires:
        - session is an active SQLAlchemy Session
        - model is a mapped vector-store class; vector_column is one of its
          ``Vector`` columns
        - query_embedding is a list of floats matching the column dimension
        - limit is a positive int

    Ensures:
        - orders by ``vector_column <#> query_embedding`` ascending (strongest dot first),
          or by cosine distance when ``metric="cosine"``, and returns at most ``limit``
          rows after applying ``exclude_filter``
        - each element is ``( similarity_pct, entity )`` with
          ``similarity_pct = -(col <#> q) * 100`` (dot * 100), or ``( 1 - cosine distance ) * 100``
          when ``metric="cosine"``
        - when clamp is True, similarity_pct is clamped to [0.0, 100.0]
          (mirrors ProxyDecisionEmbeddings.find_similar)
        - when threshold_pct is not None, rows whose similarity_pct <
          threshold_pct are dropped (applied after the limit)
        - result is sorted by similarity_pct descending

    Raises:
        - ValueError if metric is neither "dot" nor "cosine"
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
