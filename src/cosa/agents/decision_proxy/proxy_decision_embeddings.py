#!/usr/bin/env python3
"""
Embedding store for proxy decision records.

Manages proxy decision records with 768-dim question embeddings for semantic
similarity search, backed by PostgreSQL + pgvector through
PredictionDecisionRepository. Used for Case-Based Reasoning (CBR) retrieval.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

import threading


class ProxyDecisionEmbeddings:
    """
    Vector store for proxy decision embeddings.

    Stores decision records with 768-dim question embeddings and provides
    semantic similarity search for CBR retrieval. All operations are
    best-effort — failures are logged but never propagate.

    Requires:
        - Embeddings are 768-dimensional float32 vectors (normalized)

    Ensures:
        - add_decision() inserts a record via the repository
        - find_similar() returns results sorted by descending similarity
        - update_ratification_state() modifies an existing record
        - All operations are non-fatal (try/except wrapped)
    """

    # Shared re-entrant lock available to callers that need a check-then-act
    # compound to be atomic — e.g. PredictionEngine.record_hint_vote's
    # exists()→(update|add) sequence holds it across the whole sequence while the
    # nested add_decision / update_ratification_state re-acquire it cleanly.
    #
    # It is RE-ENTRANT (RLock) and CLASS-LEVEL (one lock shared by all stores) for
    # exactly that reason. Individual repository calls are already atomic in
    # Postgres; this lock exists for the compound, not for the single write.
    _write_lock = threading.RLock()

    def __init__( self, table_name="proxy_decisions", embedding_dim=768, debug=False ):
        """
        Initialize the proxy decision embedding store.

        Requires:
            - table_name is a non-empty string
            - embedding_dim is a positive integer

        Ensures:
            - Store is configured; it opens no connection of its own
              (storage sessions are per-call)

        Args:
            table_name: Logical name of the decision store
            embedding_dim: Dimensionality of question embeddings
            debug: Enable debug output
        """
        self.table_name    = table_name
        self.embedding_dim = embedding_dim
        self.debug         = debug

    _RECORD_FIELDS = (
        "id", "question", "category", "decision_value", "ratification_state",
        "data_origin", "response_type", "question_embedding", "created_at",
    )

    @classmethod
    def _record_to_dict( cls, entity ):
        """Project a PredictionDecision entity to the clean record dict (no _-fields)."""
        record = { f: getattr( entity, f ) for f in cls._RECORD_FIELDS }
        if record[ "question_embedding" ] is not None:
            record[ "question_embedding" ] = list( record[ "question_embedding" ] )
        return record

    def add_decision( self, id, question, category, decision_value, ratification_state, question_embedding, created_at, data_origin="organic", response_type="" ):
        """
        Insert a decision record into the store.

        Requires:
            - id is a non-empty string
            - question_embedding is a list of floats with length == embedding_dim

        Ensures:
            - Record is added on success
            - Failure is logged but never raises

        Args:
            id: Unique decision identifier (notification_id or UUID)
            question: Original question text
            category: Classified decision category
            decision_value: The decision value (e.g., "approved", "requires_review")
            ratification_state: Current ratification state (e.g., "pending", "ratified")
            question_embedding: 768-dim float vector
            created_at: ISO timestamp string
            data_origin: Provenance tag (organic, synthetic_seed, synthetic_generated)
            response_type: Notification response type (yes_no, multiple_choice, open_ended, open_ended_batch)
        """
        try:
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
            with self._write_lock, get_db() as session:
                PredictionDecisionRepository( session ).add_decision(
                    id=id, question=question, category=category, decision_value=decision_value,
                    ratification_state=ratification_state, question_embedding=question_embedding,
                    created_at=created_at, data_origin=data_origin, response_type=response_type,
                )
            if self.debug: print( f"[ProxyDecisionEmbeddings] Added decision: {id}" )
        except Exception as e:
            if self.debug: print( f"[ProxyDecisionEmbeddings] add_decision failed (non-fatal): {e}" )

    def find_similar( self, query_embedding, category=None, limit=5, threshold=0.75, data_origin=None, response_type=None ):
        """
        Find similar decisions by vector search.

        Requires:
            - query_embedding is a list of floats with length == embedding_dim
            - threshold is 0.0-1.0 (similarity percentage as fraction)

        Ensures:
            - Returns list of ( similarity_pct, record_dict ) tuples
            - Results are sorted by descending similarity
            - Only results above threshold are returned
            - similarity_pct is clamped to [0, 100] by the repository, so every
              downstream consumer ( pct / 100 → confidence ) stays in [0, 1]
            - Empty list returned on failure or no results

        Args:
            query_embedding: 768-dim query vector
            category: Optional category filter (exact match)
            limit: Maximum number of results
            threshold: Minimum similarity (0.0-1.0) to include
            data_origin: Optional provenance filter (e.g., "organic" to exclude synthetic)
            response_type: Optional response type filter (e.g., "multiple_choice", "yes_no")

        Returns:
            list[ tuple[ float, dict ] ]: ( similarity_pct, record ) pairs
        """
        try:
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
            with get_db() as session:
                hits = PredictionDecisionRepository( session ).find_similar(
                    query_embedding, category=category, limit=limit, threshold=threshold,
                    data_origin=data_origin, response_type=response_type,
                )
                return [ ( pct, self._record_to_dict( entity ) ) for pct, entity in hits ]
        except Exception as e:
            if self.debug: print( f"[ProxyDecisionEmbeddings] find_similar failed (non-fatal): {e}" )
            return []

    def exists( self, id ) -> bool:
        """
        Return True iff a decision with this id is present in the store.

        Lets callers choose the proven insert path (add_decision) vs the proven update
        path (update_ratification_state) for an idempotent upsert.

        Ensures:
            - returns False on any error (never raises)
        """
        try:
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
            with get_db() as session:
                return PredictionDecisionRepository( session ).exists( id )
        except Exception as e:
            if self.debug: print( f"[ProxyDecisionEmbeddings] exists check failed: {e}" )
            return False

    def update_ratification_state( self, id, new_state ):
        """
        Update the ratification state of an existing decision record.

        Requires:
            - id is a string matching an existing record
            - new_state is a non-empty string

        Ensures:
            - Record's ratification_state is updated on success
            - A missing record is logged under debug, not raised
            - Failure is logged but never raises

        Args:
            id: Decision identifier to update
            new_state: New ratification state value
        """
        try:
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
            with self._write_lock, get_db() as session:
                updated = PredictionDecisionRepository( session ).update_ratification_state( id, new_state )
            if self.debug:
                if updated is None:
                    print( f"[ProxyDecisionEmbeddings] Record not found for update: {id}" )
                else:
                    print( f"[ProxyDecisionEmbeddings] Updated ratification state: {id} -> {new_state}" )
        except Exception as e:
            if self.debug: print( f"[ProxyDecisionEmbeddings] update_ratification_state failed (non-fatal): {e}" )
