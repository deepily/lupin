"""
QueryLogRepository — Postgres storage for the ``query_log`` telemetry table
(LanceDB source: QueryLogTable).

Write-only telemetry: the 3 embedding columns are stored but NEVER ANN-searched
(no vector index). Storage-only; embeddings + cache-hit flags are supplied by the
caller. F6: the version column is ``normalization_version`` (underscore).

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.vector_store_models import QueryLog


class QueryLogRepository( BaseRepository[QueryLog] ):
    """Repository for the query_log telemetry table (write-only, no vector index)."""

    def __init__( self, session: Session ):
        """
        Initialize with a database session.

        Requires:
            - session: active SQLAlchemy session

        Ensures:
            - repository is ready for append + read on query_log
        """
        super().__init__( QueryLog, session )

    def log_query( self, id: str, query_verbatim: str, query_normalized: str,
                   query_gist: str, user_id: str, session_id: str = "unknown",
                   input_type: str = "api", timestamp: Optional[datetime] = None,
                   embedding_verbatim: Optional[List[float]] = None,
                   embedding_normalized: Optional[List[float]] = None,
                   embedding_gist: Optional[List[float]] = None,
                   matched_snapshot_id: Optional[str] = None,
                   match_type: Optional[str] = None,
                   match_confidence: Optional[float] = None,
                   processing_time_ms: int = 0,
                   user_satisfaction: Optional[str] = None,
                   normalization_version: Optional[str] = None,
                   gist_model_version: Optional[str] = None,
                   cache_hit_verbatim: bool = False,
                   cache_hit_normalized: bool = False,
                   cache_hit_gist: bool = False ) -> QueryLog:
        """
        Append one query-telemetry row.

        Requires:
            - id is a unique string primary key
            - the embedding_* args are dim-768 lists or None

        Ensures:
            - creates and flushes a row (caller commits); returns the entity
        """
        return self.create(
            id                    = id,
            timestamp             = timestamp,
            user_id               = user_id,
            session_id            = session_id,
            query_verbatim        = query_verbatim,
            query_normalized      = query_normalized,
            query_gist            = query_gist,
            embedding_verbatim    = embedding_verbatim,
            embedding_normalized  = embedding_normalized,
            embedding_gist        = embedding_gist,
            matched_snapshot_id   = matched_snapshot_id,
            match_type            = match_type,
            match_confidence      = match_confidence,
            processing_time_ms    = processing_time_ms,
            input_type            = input_type,
            user_satisfaction     = user_satisfaction,
            normalization_version = normalization_version,
            gist_model_version    = gist_model_version,
            cache_hit_verbatim    = cache_hit_verbatim,
            cache_hit_normalized  = cache_hit_normalized,
            cache_hit_gist        = cache_hit_gist,
        )

    def get_recent_queries( self, limit: int = 100, user_id: Optional[str] = None ) -> List[QueryLog]:
        """
        Return recent queries, newest first.

        Requires:
            - limit is a positive int

        Ensures:
            - returns up to limit rows ordered by timestamp descending
            - filtered to user_id when provided
        """
        query = self.session.query( QueryLog )
        if user_id is not None:
            query = query.filter( QueryLog.user_id == user_id )
        return query.order_by( QueryLog.timestamp.desc() ).limit( limit ).all()

    def get_cache_hit_stats( self, since: Optional[datetime] = None ) -> Dict[str, Any]:
        """
        Aggregate cache-hit rates across the three tiers.

        Requires:
            - since is a datetime lower-bound, or None for all-time

        Ensures:
            - returns { total_queries, verbatim_hit_rate, normalized_hit_rate,
              gist_hit_rate } — rates are 0.0 when total_queries is 0
        """
        # Explicit per-tier counts keep the aggregation readable + correct.
        base = self.session.query( QueryLog )
        if since is not None:
            base = base.filter( QueryLog.timestamp >= since )

        total = base.count()
        if total == 0:
            return {
                "total_queries"       : 0,
                "verbatim_hit_rate"   : 0.0,
                "normalized_hit_rate" : 0.0,
                "gist_hit_rate"       : 0.0,
            }

        verbatim   = base.filter( QueryLog.cache_hit_verbatim   == True ).count()
        normalized = base.filter( QueryLog.cache_hit_normalized == True ).count()
        gist       = base.filter( QueryLog.cache_hit_gist       == True ).count()

        return {
            "total_queries"       : total,
            "verbatim_hit_rate"   : round( verbatim   / total, 4 ),
            "normalized_hit_rate" : round( normalized / total, 4 ),
            "gist_hit_rate"       : round( gist       / total, 4 ),
        }
