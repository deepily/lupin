"""
QuestionEmbeddingRepository — Postgres storage for the ``question_embeddings``
text→embedding cache.

Exact-match KV cache (btree on ``question``) — NOT ANN-searched. Storage-only:
``get_embedding`` returns the cached vector or None (the Lane-C memory layer
generates on a miss, then calls ``add_embedding``).

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.vector_store_models import QuestionEmbedding


class QuestionEmbeddingRepository( BaseRepository[QuestionEmbedding] ):
    """Repository for the question_embeddings KV cache (exact-match, no vector index)."""

    def __init__( self, session: Session ):
        """
        Initialize with a database session.

        Requires:
            - session: active SQLAlchemy session

        Ensures:
            - repository is ready for KV cache operations on question_embeddings
        """
        super().__init__( QuestionEmbedding, session )

    def has( self, question: str ) -> bool:
        """
        Existence check by exact question.

        Requires:
            - question is a string

        Ensures:
            - returns True iff a row with that exact question exists
        """
        return self.session.query(
            self.session.query( QuestionEmbedding ).filter(
                QuestionEmbedding.question == question
            ).exists()
        ).scalar()

    def get_embedding( self, question: str ) -> Optional[List[float]]:
        """
        Fetch the cached embedding for an exact question.

        Requires:
            - question is a string

        Ensures:
            - returns the stored embedding as a list of floats, or None on a miss
            - does NOT generate on a miss (Lane C owns generation)
        """
        row = self.session.query( QuestionEmbedding ).filter(
            QuestionEmbedding.question == question
        ).first()
        if row is None or row.embedding is None:
            return None
        return list( row.embedding )

    def add_embedding( self, question: str, embedding: List[float] ) -> QuestionEmbedding:
        """
        Store a question→embedding row.

        Requires:
            - question is a string; embedding is a dim-768 list

        Ensures:
            - creates and flushes a row (caller commits); returns the entity
        """
        return self.create( question=question, embedding=embedding )
