"""
SolutionSnapshotRepository — Postgres+pgvector storage for the
``solution_snapshots`` table (LanceDB source: SolutionSnapshotManager).

DISTINCT from ``input_and_output``. Two of its seven vector columns are
ANN-searched (HNSW dot): ``question_embedding`` + ``code_embedding``
(``solution_embedding`` is also searched by the solution-similarity path). PK is
the natural ``id_hash``. Storage-only: embeddings arrive on the field dict; the
Lane-C memory layer keeps SolutionSnapshot marshalling + embedding generation.

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.repositories.vector_search import dot_topk
from cosa.rest.db.vector_store_models import SolutionSnapshot


class SolutionSnapshotRepository( BaseRepository[SolutionSnapshot] ):
    """Repository for solution_snapshots (question_embedding + code_embedding ANN, HNSW dot)."""

    def __init__( self, session: Session ):
        """
        Initialize with a database session.

        Requires:
            - session: active SQLAlchemy session

        Ensures:
            - repository is ready for upsert + CRUD + dot nearest-k on solution_snapshots
        """
        super().__init__( SolutionSnapshot, session )

    def get_snapshot_by_id( self, id_hash: str ) -> Optional[SolutionSnapshot]:
        """
        Fetch a snapshot by id_hash.

        Requires:
            - id_hash is a string

        Ensures:
            - returns the snapshot or None
        """
        return self.session.query( SolutionSnapshot ).filter(
            SolutionSnapshot.id_hash == id_hash
        ).first()

    def upsert_snapshot( self, id_hash: str, **fields: Any ) -> SolutionSnapshot:
        """
        Insert or update a snapshot keyed on id_hash.

        Requires:
            - id_hash is a string; fields are valid SolutionSnapshot columns

        Ensures:
            - creates a new row when id_hash is absent, else updates the existing
              row's supplied fields; flushes (caller commits); returns the entity
        """
        existing = self.get_snapshot_by_id( id_hash )
        if existing is None:
            return self.create( id_hash=id_hash, **fields )

        for key, value in fields.items():
            setattr( existing, key, value )
        self.session.flush()
        return existing

    def delete_snapshot( self, id_hash: str ) -> bool:
        """
        Delete a snapshot by id_hash.

        Requires:
            - id_hash is a string

        Ensures:
            - deletes the row and returns True, or returns False if absent
        """
        existing = self.get_snapshot_by_id( id_hash )
        if existing is None:
            return False
        self.session.delete( existing )
        return True

    def _exclude_filter( self, exclude_id_hash: Optional[str] ):
        """
        Build an id_hash-exclusion filter, or None.

        Requires:
            - exclude_id_hash is a string or None

        Ensures:
            - returns a SQLAlchemy filter excluding that id_hash, or None
        """
        if exclude_id_hash is None:
            return None
        return SolutionSnapshot.id_hash != exclude_id_hash

    def get_snapshots_by_question( self, query_embedding: List[float],
                                   threshold: float = 90.0, limit: int = 7,
                                   exclude_id_hash: Optional[str] = None ) -> List[Tuple[float, SolutionSnapshot]]:
        """
        Dot nearest-k over question_embedding.

        Requires:
            - query_embedding is a dim-768 list; limit is a positive int
            - threshold is a similarity percentage in [0,100]

        Ensures:
            - returns up to limit ``( similarity_pct, entity )`` tuples >= threshold,
              strongest dot first; excludes exclude_id_hash when given
        """
        return dot_topk(
            self.session, SolutionSnapshot, SolutionSnapshot.question_embedding,
            query_embedding, limit=limit, exclude_filter=self._exclude_filter( exclude_id_hash ),
            threshold_pct=threshold,
        )

    def get_snapshots_by_code_similarity( self, query_embedding: List[float],
                                          threshold: float = 85.0, limit: int = 20,
                                          exclude_id_hash: Optional[str] = None ) -> List[Tuple[float, SolutionSnapshot]]:
        """
        Dot nearest-k over code_embedding.

        Requires:
            - query_embedding is a dim-768 list; limit is a positive int
            - threshold is a similarity percentage in [0,100]

        Ensures:
            - returns up to limit ``( similarity_pct, entity )`` tuples >= threshold,
              strongest dot first; excludes exclude_id_hash when given
        """
        return dot_topk(
            self.session, SolutionSnapshot, SolutionSnapshot.code_embedding,
            query_embedding, limit=limit, exclude_filter=self._exclude_filter( exclude_id_hash ),
            threshold_pct=threshold,
        )

    def get_snapshots_by_solution_similarity( self, query_embedding: List[float],
                                              threshold: float = 85.0, limit: int = 20,
                                              exclude_id_hash: Optional[str] = None ) -> List[Tuple[float, SolutionSnapshot]]:
        """
        Dot nearest-k over solution_embedding.

        Requires:
            - query_embedding is a dim-768 list; limit is a positive int
            - threshold is a similarity percentage in [0,100]

        Ensures:
            - returns up to limit ``( similarity_pct, entity )`` tuples >= threshold,
              strongest dot first; excludes exclude_id_hash when given
        """
        return dot_topk(
            self.session, SolutionSnapshot, SolutionSnapshot.solution_embedding,
            query_embedding, limit=limit, exclude_filter=self._exclude_filter( exclude_id_hash ),
            threshold_pct=threshold,
        )

    def get_gists( self ) -> List[str]:
        """
        List distinct non-null question gists.

        Ensures:
            - returns the distinct question_gist values (nulls excluded)
        """
        rows = self.session.query( SolutionSnapshot.question_gist ).filter(
            SolutionSnapshot.question_gist.isnot( None )
        ).distinct().all()
        return [ row[ 0 ] for row in rows ]

    def get_stats( self ) -> Dict[str, Any]:
        """
        Aggregate snapshot statistics.

        Ensures:
            - returns { total_snapshots } over the whole table
        """
        total = self.session.query( func.count( SolutionSnapshot.id_hash ) ).scalar() or 0
        return { "total_snapshots": int( total ) }
