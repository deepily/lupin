"""
InputAndOutputRepository — Postgres+pgvector storage for the keystone
``input_and_output`` table.

Storage-only: embeddings are SUPPLIED by the caller
(the Lane-C memory layer keeps embedding generation), and ``get_knn_by_input``
takes a pre-computed query embedding and runs the dot (`<#>`) nearest-k search.

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.repositories.vector_search import dot_topk
from cosa.rest.db.vector_store_models import InputAndOutput


class InputAndOutputRepository( BaseRepository[InputAndOutput] ):
    """Repository for the input_and_output table (input_embedding is the sole ANN target)."""

    def __init__( self, session: Session ):
        """
        Initialize with a database session.

        Requires:
            - session: active SQLAlchemy session from get_db()

        Ensures:
            - repository is ready for CRUD + dot nearest-k on input_and_output
        """
        super().__init__( InputAndOutput, session )

    def insert_io_row( self, date: Optional[str] = None, time: Optional[str] = None,
                       input_type: str = "", input: str = "",
                       input_embedding: Optional[List[float]] = None,
                       output_raw: str = "", output_final: str = "",
                       output_final_embedding: Optional[List[float]] = None,
                       solution_path_wo_root: Optional[str] = None ) -> InputAndOutput:
        """
        Insert one input/output row.

        Requires:
            - input_embedding / output_final_embedding are dim-768 lists or None

        Ensures:
            - creates and flushes a row (caller commits); returns the entity
            - embeddings are stored verbatim (no generation here — Lane C owns that)
        """
        return self.create(
            date                   = date,
            time                   = time,
            input_type             = input_type,
            input                  = input,
            input_embedding        = input_embedding,
            output_raw             = output_raw,
            output_final           = output_final,
            output_final_embedding = output_final_embedding,
            solution_path_wo_root  = solution_path_wo_root,
        )

    def get_knn_by_input( self, query_embedding: List[float], k: int = 10 ) -> List[Tuple[float, InputAndOutput]]:
        """
        Dot nearest-k over input_embedding.

        Requires:
            - query_embedding is a dim-768 list; k is a positive int

        Ensures:
            - returns up to k ``( similarity_pct, entity )`` tuples, strongest
              dot first (similarity_pct = dot * 100)
        """
        return dot_topk( self.session, InputAndOutput, InputAndOutput.input_embedding,
                         query_embedding, limit=k )

    def get_all_io( self, max_rows: int = 1000 ) -> List[InputAndOutput]:
        """
        List rows (bounded scan).

        Requires:
            - max_rows is a positive int

        Ensures:
            - returns up to max_rows rows
        """
        return self.session.query( InputAndOutput ).limit( max_rows ).all()

    def get_io_stats_by_input_type( self, max_rows: int = 1000 ) -> Dict[str, int]:
        """
        Count rows grouped by input_type (over a bounded window).

        Requires:
            - max_rows is a positive int

        Ensures:
            - returns { input_type: count } for the first max_rows rows
        """
        from sqlalchemy import func

        subq = self.session.query( InputAndOutput.input_type ).limit( max_rows ).subquery()
        rows = self.session.query( subq.c.input_type, func.count().label( "n" ) ).group_by( subq.c.input_type ).all()
        return { input_type: count for input_type, count in rows }

    def get_all_qnr( self, max_rows: int = 50 ) -> List[InputAndOutput]:
        """
        List agent-router rows (input_type LIKE 'agent router go to %').

        Requires:
            - max_rows is a positive int

        Ensures:
            - returns up to max_rows rows whose input_type starts with the router prefix
        """
        return self.session.query( InputAndOutput ).filter(
            InputAndOutput.input_type.like( "agent router go to %" )
        ).limit( max_rows ).all()
