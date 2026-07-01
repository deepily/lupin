"""
CanonicalSynonymRepository — Postgres storage for the ``canonical_synonyms``
table (LanceDB source: CanonicalSynonymsTable).

Exact-match lookups on the three text keys (btree on question_normalized +
snapshot_id) — the 3 embedding columns are stored but NOT ANN-searched.
Storage-only: embeddings + normalization are supplied by the Lane-C memory layer.

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.vector_store_models import CanonicalSynonym


class CanonicalSynonymRepository( BaseRepository[CanonicalSynonym] ):
    """Repository for the canonical_synonyms table (exact-match, no HNSW)."""

    def __init__( self, session: Session ):
        """
        Initialize with a database session.

        Requires:
            - session: active SQLAlchemy session

        Ensures:
            - repository is ready for CRUD + exact lookups on canonical_synonyms
        """
        super().__init__( CanonicalSynonym, session )

    def add_synonym( self, id: str, snapshot_id: str, question_verbatim: str,
                     question_normalized: str, question_gist: str,
                     embedding_verbatim: Optional[List[float]] = None,
                     embedding_normalized: Optional[List[float]] = None,
                     embedding_gist: Optional[List[float]] = None,
                     confidence_score: float = 100.0, usage_count: int = 0,
                     last_matched: Optional[datetime] = None,
                     created_date: Optional[datetime] = None,
                     source: str = "runtime" ) -> CanonicalSynonym:
        """
        Store a canonical-synonym row.

        Requires:
            - id + snapshot_id + the three question_* keys are strings
            - the three embedding_* args are dim-768 lists or None

        Ensures:
            - creates and flushes a row (caller commits); returns the entity
        """
        return self.create(
            id                   = id,
            snapshot_id          = snapshot_id,
            question_verbatim    = question_verbatim,
            question_normalized  = question_normalized,
            question_gist        = question_gist,
            embedding_verbatim   = embedding_verbatim,
            embedding_normalized = embedding_normalized,
            embedding_gist       = embedding_gist,
            confidence_score     = confidence_score,
            usage_count          = usage_count,
            last_matched         = last_matched,
            created_date         = created_date,
            source               = source,
        )

    def find_exact_verbatim( self, question_verbatim: str ) -> Optional[str]:
        """
        Find a snapshot_id by exact verbatim question.

        Requires:
            - question_verbatim is a string

        Ensures:
            - returns the matching snapshot_id, or None
        """
        row = self.session.query( CanonicalSynonym ).filter(
            CanonicalSynonym.question_verbatim == question_verbatim
        ).first()
        return row.snapshot_id if row is not None else None

    def find_exact_normalized( self, question_normalized: str ) -> Optional[str]:
        """
        Find a snapshot_id by exact normalized question.

        Requires:
            - question_normalized is a string

        Ensures:
            - returns the matching snapshot_id, or None
        """
        row = self.session.query( CanonicalSynonym ).filter(
            CanonicalSynonym.question_normalized == question_normalized
        ).first()
        return row.snapshot_id if row is not None else None

    def find_exact_gist( self, question_gist: str ) -> Optional[str]:
        """
        Find a snapshot_id by exact question gist.

        Requires:
            - question_gist is a string

        Ensures:
            - returns the matching snapshot_id, or None
        """
        row = self.session.query( CanonicalSynonym ).filter(
            CanonicalSynonym.question_gist == question_gist
        ).first()
        return row.snapshot_id if row is not None else None

    def delete_by_snapshot_id( self, snapshot_id: str ) -> int:
        """
        Delete all rows for a snapshot.

        Requires:
            - snapshot_id is a string

        Ensures:
            - deletes every row with that snapshot_id; returns the count deleted
        """
        return self.session.query( CanonicalSynonym ).filter(
            CanonicalSynonym.snapshot_id == snapshot_id
        ).delete( synchronize_session=False )

    def get_statistics( self ) -> Dict[str, Any]:
        """
        Aggregate synonym statistics.

        Ensures:
            - returns { total_synonyms, total_usage_count } over the whole table
        """
        total = self.session.query( func.count( CanonicalSynonym.id ) ).scalar() or 0
        usage = self.session.query( func.coalesce( func.sum( CanonicalSynonym.usage_count ), 0 ) ).scalar() or 0
        return {
            "total_synonyms"    : int( total ),
            "total_usage_count" : int( usage ),
        }
