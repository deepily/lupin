"""
Postgres and pgvector store for the decision-proxy ``prediction_decisions`` vectors.

Distinct from the relational ``proxy_decisions`` log served by ProxyDecisionRepository. This is the 1:1 vector
mirror whose ``question_embedding`` is ANN-searched (HNSW dot). Storage only: the caller supplies embeddings.
``find_similar`` does dot nearest-k, similarity clamped to [0,100], threshold applied as a percentage.
"""

from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from cosa.rest.db.embedding_regeneration import validate_fresh_vector
from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.repositories.vector_search import dot_topk
from cosa.rest.db.vector_errors import QueryVectorRefused
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
                      response_type: str = "", owner_user_id: Optional[str] = None,
                      answer_source: str = "unknown" ) -> PredictionDecision:
        """
        Store a decision row.

        Requires:
            - id is a unique string primary key
            - question_embedding is a dim-768 list
            - owner_user_id is the answering account's id, or None
            - answer_source is one of human, proxy, timeout_default, test, hint_vote or unknown

        Ensures:
            - creates and flushes a row (caller commits); returns the entity
            - a caller that does not say who answered stores "unknown", which casts no personal vote
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
            owner_user_id      = owner_user_id,
            answer_source      = answer_source,
        )

    def find_similar( self, query_embedding: List[float], category: Optional[str] = None,
                      limit: int = 5, threshold: float = 0.75,
                      data_origin: Optional[str] = None,
                      response_type: Optional[str] = None,
                      owner_user_id: Optional[str] = None,
                      answer_source: Optional[str] = None,
                      metric: str = "dot" ) -> List[Tuple[float, PredictionDecision]]:
        """
        Nearest-k over question_embedding with optional scalar filters.

        Requires:
            - query_embedding is a dim-768 list; limit is a positive int
            - threshold is a fraction in [0,1] (compared as threshold * 100)
            - metric is "dot" (the default, used by the decision proxy) or "cosine"

        Ensures:
            - returns up to limit ``( similarity_pct, entity )`` tuples, strongest
              first, similarity_pct clamped to [0,100] and kept only when
              >= threshold * 100 (mirrors ProxyDecisionEmbeddings.find_similar)
            - category / data_origin / response_type / owner_user_id / answer_source are ANDed as exact filters
            - with metric "dot" the query is exactly what it was before the parameter existed
            - with metric "cosine", rows whose question_embedding is NULL or has zero norm
              are never returned (they would make the distance conversion raise)

        Raises:
            - ValueError if metric is neither "dot" nor "cosine"
            - QueryVectorRefused on the cosine path when the query vector is missing,
              of the wrong dimension, non-finite, zero-norm or out of the current model's band
        """
        if metric == "cosine":
            reason = validate_fresh_vector( query_embedding )
            if reason is not None: raise QueryVectorRefused( reason )
        exclude_filter = None
        conditions = []
        if category is not None:      conditions.append( PredictionDecision.category      == category )
        if data_origin is not None:   conditions.append( PredictionDecision.data_origin   == data_origin )
        if response_type is not None: conditions.append( PredictionDecision.response_type == response_type )
        if owner_user_id is not None: conditions.append( PredictionDecision.owner_user_id == owner_user_id )
        if answer_source is not None: conditions.append( PredictionDecision.answer_source == answer_source )
        if metric == "cosine":
            conditions.append( PredictionDecision.question_embedding.is_not( None ) )
            conditions.append( func.vector_norm( PredictionDecision.question_embedding ) > 0 )
        if conditions:
            from sqlalchemy import and_
            exclude_filter = and_( *conditions )

        return dot_topk(
            self.session, PredictionDecision, PredictionDecision.question_embedding,
            query_embedding, limit=limit, exclude_filter=exclude_filter,
            threshold_pct=threshold * 100.0, clamp=True, metric=metric,
        )

    def delete_all( self ) -> int:
        """
        Delete every row in prediction_decisions (test reset; the table is kept).

        The table itself is alembic-managed.

        Ensures:
            - removes all rows; returns the count deleted (caller commits)
        """
        return self.session.query( PredictionDecision ).delete( synchronize_session=False )

    def update_ratification_state( self, id: str, new_state: str ) -> Optional[PredictionDecision]:
        """
        Set a decision's ratification_state.

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
