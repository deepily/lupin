"""
GistCacheRepository — Postgres storage for the ``gist_cache`` table.

RELATIONAL ONLY — P0-confirmed no vector column. Two-tier exact lookup (verbatim
then normalized). Text normalization stays in the Lane-C memory layer; this
repository stores + fetches by the exact keys it is handed.

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.vector_store_models import GistCache


class GistCacheRepository( BaseRepository[GistCache] ):
    """Repository for the gist_cache relational cache (no pgvector column)."""

    def __init__( self, session: Session ):
        """
        Initialize with a database session.

        Requires:
            - session: active SQLAlchemy session

        Ensures:
            - repository is ready for relational cache operations on gist_cache
        """
        super().__init__( GistCache, session )

    def get_by_verbatim( self, question_verbatim: str ) -> Optional[GistCache]:
        """
        Fetch a row by exact verbatim question.

        Requires:
            - question_verbatim is a string

        Ensures:
            - returns the row or None
        """
        return self.session.query( GistCache ).filter(
            GistCache.question_verbatim == question_verbatim
        ).first()

    def get_by_normalized( self, question_normalized: str ) -> Optional[GistCache]:
        """
        Fetch a row by exact normalized question.

        Requires:
            - question_normalized is a string

        Ensures:
            - returns the row or None
        """
        return self.session.query( GistCache ).filter(
            GistCache.question_normalized == question_normalized
        ).first()

    def get_cached_gist( self, question_verbatim: Optional[str] = None,
                         question_normalized: Optional[str] = None ) -> Optional[str]:
        """
        Two-tier gist lookup: verbatim first, then normalized.

        Requires:
            - at least one of question_verbatim / question_normalized is provided

        Ensures:
            - returns the question_gist of the first matching tier, or None
        """
        if question_verbatim is not None:
            row = self.get_by_verbatim( question_verbatim )
            if row is not None:
                return row.question_gist
        if question_normalized is not None:
            row = self.get_by_normalized( question_normalized )
            if row is not None:
                return row.question_gist
        return None

    def has_cached_gist( self, question_verbatim: Optional[str] = None,
                         question_normalized: Optional[str] = None ) -> bool:
        """
        Existence check across the two lookup tiers.

        Requires:
            - at least one of question_verbatim / question_normalized is provided

        Ensures:
            - returns True iff either tier matches a row
        """
        return self.get_cached_gist( question_verbatim, question_normalized ) is not None

    def cache_gist( self, question_verbatim: str, question_gist: str,
                    question_normalized: str = "", created_date: Optional[str] = None,
                    access_count: int = 0, last_accessed: Optional[str] = None ) -> GistCache:
        """
        Store a gist-cache row.

        Requires:
            - question_verbatim + question_gist are strings

        Ensures:
            - creates and flushes a row (caller commits); returns the entity
        """
        return self.create(
            question_verbatim   = question_verbatim,
            question_normalized = question_normalized,
            question_gist       = question_gist,
            created_date        = created_date,
            access_count        = access_count,
            last_accessed       = last_accessed,
        )

    def get_statistics( self ) -> Dict[str, Any]:
        """
        Aggregate cache statistics.

        Ensures:
            - returns { total_entries, total_access_count } over the whole table
        """
        total_entries = self.session.query( func.count( GistCache.id ) ).scalar() or 0
        total_access  = self.session.query( func.coalesce( func.sum( GistCache.access_count ), 0 ) ).scalar() or 0
        return {
            "total_entries"      : int( total_entries ),
            "total_access_count" : int( total_access ),
        }
