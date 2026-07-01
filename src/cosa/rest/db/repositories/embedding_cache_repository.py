"""
EmbeddingCacheRepository — Postgres storage for the ``embedding_cache``
normalized_text→embedding cache (LanceDB source: EmbeddingCacheTable).

Exact-match KV cache (btree on ``normalized_text``) — NOT ANN-searched.
Storage-only: embeddings are always supplied by the caller.

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.vector_store_models import EmbeddingCache


class EmbeddingCacheRepository( BaseRepository[EmbeddingCache] ):
    """Repository for the embedding_cache KV cache (exact-match, no vector index)."""

    def __init__( self, session: Session ):
        """
        Initialize with a database session.

        Requires:
            - session: active SQLAlchemy session

        Ensures:
            - repository is ready for KV cache operations on embedding_cache
        """
        super().__init__( EmbeddingCache, session )

    def has_cached_embedding( self, normalized_text: str ) -> bool:
        """
        Existence check by exact normalized_text.

        Requires:
            - normalized_text is a string

        Ensures:
            - returns True iff a row with that exact normalized_text exists
        """
        return self.session.query(
            self.session.query( EmbeddingCache ).filter(
                EmbeddingCache.normalized_text == normalized_text
            ).exists()
        ).scalar()

    def get_cached_embedding( self, normalized_text: str ) -> Optional[List[float]]:
        """
        Fetch the cached embedding for exact normalized_text.

        Requires:
            - normalized_text is a string

        Ensures:
            - returns the stored embedding as a list of floats, or None on a miss
        """
        row = self.session.query( EmbeddingCache ).filter(
            EmbeddingCache.normalized_text == normalized_text
        ).first()
        if row is None or row.embedding is None:
            return None
        return list( row.embedding )

    def cache_embedding( self, normalized_text: str, embedding: List[float] ) -> EmbeddingCache:
        """
        Store a normalized_text→embedding row.

        Requires:
            - normalized_text is a string; embedding is a dim-768 list

        Ensures:
            - creates and flushes a row (caller commits); returns the entity
        """
        return self.create( normalized_text=normalized_text, embedding=embedding )
