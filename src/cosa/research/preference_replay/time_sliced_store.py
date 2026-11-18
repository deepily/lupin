"""
An in-memory case store that only knows what had been answered at a given moment.

The replay harness calls the live ``PredictionEngine.predict()``, which reads past cases through
``self._embedding_store.find_similar`` and writes them through ``add_decision``. This store stands in for
``ProxyDecisionEmbeddings`` there. A case is visible only when its ``responded_at`` is at or before the
moment the harness has advanced to. So a forecast for one ask never sees a later answer.
The store never reads a case's ``created_at``, which the database keeps as text.

``find_similar`` mirrors ``PredictionDecisionRepository.find_similar`` and ``dot_topk``. Filters apply
before the limit. The limit applies to the raw distance order. Then the score is clamped, the threshold
applies after the limit, and the survivors are sorted strongest first. The parity test in
``src/cosa/tests/unit/research/test_time_sliced_store_parity.py`` holds the two paths together.

Known difference on the dot path. The SQL query fails when a row with a NULL vector falls inside the limit,
and the proxy wrapper then returns an empty list. This store leaves such a row out instead.
Replay input has no row without a vector, so the difference is never reached.
"""

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
from cosa.rest.db.repositories.prediction_decision_repository import refuse_unusable_cosine_query

# The record shape the wrapper returns. Taken from the wrapper so the two cannot drift apart.
RECORD_FIELDS = ProxyDecisionEmbeddings._RECORD_FIELDS


class TimeSlicedDecisionStore:
    """Case memory that gains a case only once its human answer exists."""

    def __init__( self, cases: Iterable[Dict[str, Any]] ):
        """
        Load the full set of cases the replay may ever see.

        Requires:
            - cases is an iterable of dicts, each holding every field of RECORD_FIELDS plus ``responded_at``
            - ``responded_at`` is a timezone-aware datetime, or None for a case whose answer never arrived
            - question_embedding is a list of floats, or None

        Ensures:
            - no case is visible until advance_to is called
            - refused_writes is 0

        Raises:
            - KeyError if a case lacks one of the fields
        """
        self._cases          = [ { field: case[ field ] for field in RECORD_FIELDS + ( "responded_at", ) } for case in cases ]
        self._as_of          = None
        self.refused_writes  = 0
        has_vector           = [ case[ "question_embedding" ] is not None for case in self._cases ]
        self._has_vector     = np.array( has_vector, dtype=bool )
        dimension            = max( ( len( case[ "question_embedding" ] ) for case in self._cases if case[ "question_embedding" ] is not None ), default=0 )
        self._vectors        = np.zeros( ( len( self._cases ), dimension ), dtype=np.float64 )
        for row, case in enumerate( self._cases ):
            if case[ "question_embedding" ] is not None: self._vectors[ row ] = case[ "question_embedding" ]
        self._norms          = np.linalg.norm( self._vectors, axis=1 )

    def advance_to( self, moment: datetime ) -> None:
        """
        Make visible every case answered at or before ``moment``.

        Requires:
            - moment is a timezone-aware datetime, the ask being predicted

        Ensures:
            - a case with responded_at <= moment is visible, one answered later or never is not
        """
        self._as_of = moment

    def visible_ids( self ) -> List[str]:
        """
        List the ids of the visible cases.

        Ensures:
            - returns ids in load order; empty before advance_to
        """
        return [ self._cases[ row ][ "id" ] for row in self._visible_rows() ]

    def add_decision( self, *args: Any, **kwargs: Any ) -> None:
        """
        Refuse a write: in replay a case enters by its stored answer time, never by the engine.

        Ensures:
            - nothing is stored
            - refused_writes goes up by one, so a harness can assert it stayed 0
        """
        self.refused_writes += 1

    def find_similar( self, query_embedding: List[float], category: Optional[str] = None, limit: int = 5,
                      threshold: float = 0.75, data_origin: Optional[str] = None, response_type: Optional[str] = None,
                      owner_user_id: Optional[str] = None, answer_source: Optional[str] = None,
                      metric: str = "dot" ) -> List[Tuple[float, Dict[str, Any]]]:
        """
        Nearest visible cases, as ``ProxyDecisionEmbeddings.find_similar`` returns them.

        Requires:
            - query_embedding is a list of floats; limit is a positive int
            - threshold is a fraction in [0,1], compared as threshold * 100
            - metric is "dot" or "cosine"

        Ensures:
            - returns up to limit ``( similarity_pct, record )`` pairs, strongest first
            - similarity_pct is dot * 100 or cosine * 100, clamped to [0,100], and kept only at or above threshold * 100
            - the filters are ANDed exact matches applied before the limit; the threshold is applied after it
            - with metric "cosine" a case with no vector or a zero-norm vector is never returned
            - a record carries exactly RECORD_FIELDS

        Raises:
            - ValueError if metric is neither "dot" nor "cosine"
            - QueryVectorRefused on the cosine path for a query vector the repository would refuse
        """
        if metric not in ( "dot", "cosine" ): raise ValueError( f"metric must be 'dot' or 'cosine', got {metric!r}" )
        if metric == "cosine": refuse_unusable_cosine_query( query_embedding )

        filters = { "category": category, "data_origin": data_origin, "response_type": response_type,
                    "owner_user_id": owner_user_id, "answer_source": answer_source }
        rows    = [ row for row in self._visible_rows()
                    if self._has_vector[ row ]
                    and all( wanted is None or self._cases[ row ][ name ] == wanted for name, wanted in filters.items() )
                    and ( metric == "dot" or self._norms[ row ] > 0 ) ]
        if not rows: return []

        query = np.asarray( query_embedding, dtype=np.float64 )
        dots  = self._vectors[ rows ] @ query
        if metric == "cosine": scores = dots / ( self._norms[ rows ] * np.linalg.norm( query ) )
        else:                  scores = dots
        order   = np.argsort( -scores, kind="stable" )[ :limit ]
        results = []
        for position in order:
            similarity_pct = max( 0.0, min( 100.0, float( scores[ position ] ) * 100.0 ) )
            if similarity_pct < threshold * 100.0: continue
            record = { field: self._cases[ rows[ position ] ][ field ] for field in RECORD_FIELDS }
            record[ "question_embedding" ] = list( record[ "question_embedding" ] )
            results.append( ( similarity_pct, record ) )
        results.sort( key=lambda pair: pair[ 0 ], reverse=True )
        return results

    def _visible_rows( self ) -> List[int]:
        """
        Return the row numbers of the cases answered at or before the current moment.

        Ensures:
            - returns an empty list before advance_to
        """
        if self._as_of is None: return []
        return [ row for row, case in enumerate( self._cases )
                 if case[ "responded_at" ] is not None and case[ "responded_at" ] <= self._as_of ]
