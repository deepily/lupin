"""
PredictionDecisionRepository — Postgres+pgvector storage for the
``prediction_decisions`` decision-proxy VECTOR store (LanceDB source:
ProxyDecisionEmbeddings).

DISTINCT from the relational ``proxy_decisions`` log served by
ProxyDecisionRepository — this is the 1:1 vector mirror whose
``question_embedding`` IS ANN-searched (HNSW dot). Storage-only: embeddings are
supplied by the caller. ``find_similar`` mirrors the LanceDB semantics: dot
nearest-k, similarity clamped to [0,100], threshold applied as a percentage.

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.repositories.vector_search import dot_topk
from cosa.rest.db.vector_store_models import PredictionDecision


class PredictionDecisionRepository( BaseRepository[PredictionDecision] ):
    """Repository for prediction_decisions (question_embedding ANN-searched, HNSW dot)."""

    def __init__( self, session: Session ):
        """
        Initialize with a database session.

        Requires:
            - session: active SQLAlchemy session

        Ensures:
            - repository is ready for CRUD + dot nearest-k on prediction_decisions
        """
        super().__init__( PredictionDecision, session )

    def add_decision( self, id: str, question: str, category: str, decision_value: str,
                      ratification_state: str, question_embedding: List[float],
                      created_at: Optional[str] = None, data_origin: str = "organic",
                      response_type: str = "" ) -> PredictionDecision:
        """
        Store a decision row.

        Requires:
            - id is a unique string primary key
            - question_embedding is a dim-768 list

        Ensures:
            - creates and flushes a row (caller commits); returns the entity
        """
        return self.create(
            id                 = id,
            question           = question,
            category           = category,
            decision_value     = decision_value,
            ratification_state = ratification_state,
            data_origin        = data_origin,
            response_type      = response_type,
            question_embedding = question_embedding,
            created_at         = created_at,
        )

    def find_similar( self, query_embedding: List[float], category: Optional[str] = None,
                      limit: int = 5, threshold: float = 0.75,
                      data_origin: Optional[str] = None,
                      response_type: Optional[str] = None ) -> List[Tuple[float, PredictionDecision]]:
        """
        Dot nearest-k over question_embedding with optional scalar filters.

        Requires:
            - query_embedding is a dim-768 list; limit is a positive int
            - threshold is a fraction in [0,1] (compared as threshold * 100)

        Ensures:
            - returns up to limit ``( similarity_pct, entity )`` tuples, strongest
              dot first, similarity_pct clamped to [0,100] and kept only when
              >= threshold * 100 (mirrors ProxyDecisionEmbeddings.find_similar)
            - category / data_origin / response_type are ANDed as exact filters
        """
        exclude_filter = None
        conditions = []
        if category is not None:      conditions.append( PredictionDecision.category      == category )
        if data_origin is not None:   conditions.append( PredictionDecision.data_origin   == data_origin )
        if response_type is not None: conditions.append( PredictionDecision.response_type == response_type )
        if conditions:
            from sqlalchemy import and_
            exclude_filter = and_( *conditions )

        return dot_topk(
            self.session, PredictionDecision, PredictionDecision.question_embedding,
            query_embedding, limit=limit, exclude_filter=exclude_filter,
            threshold_pct=threshold * 100.0, clamp=True,
        )

    def exists( self, id: str ) -> bool:
        """
        Existence check by id.

        Requires:
            - id is a string

        Ensures:
            - returns True iff a row with that id exists
        """
        return self.session.query(
            self.session.query( PredictionDecision ).filter(
                PredictionDecision.id == id
            ).exists()
        ).scalar()

    def update_ratification_state( self, id: str, new_state: str ) -> Optional[PredictionDecision]:
        """
        Update a decision's ratification_state.

        Requires:
            - id is a string; new_state is a string

        Ensures:
            - updates the row's ratification_state and returns it, or None if absent
        """
        row = self.get_by_id( id )
        if row is None:
            return None
        row.ratification_state = new_state
        self.session.flush()
        return row
