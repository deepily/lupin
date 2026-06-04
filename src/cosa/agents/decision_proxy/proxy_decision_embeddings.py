#!/usr/bin/env python3
"""
LanceDB embedding store for proxy decision records.

Manages a LanceDB table that mirrors proxy decisions from PostgreSQL with
768-dim question embeddings for semantic similarity search. PostgreSQL
remains the source of truth; this store is a secondary vector index for
Case-Based Reasoning (CBR) retrieval.

Follows patterns from cosa.memory.lancedb_solution_manager.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

import lancedb
import pyarrow as pa

import cosa.utils.util as cu


class ProxyDecisionEmbeddings:
    """
    LanceDB vector store for proxy decision embeddings.

    Stores decision records with 768-dim question embeddings and provides
    semantic similarity search for CBR retrieval. All operations are
    best-effort — failures are logged but never propagate.

    Requires:
        - db_path points to a valid LanceDB database directory
        - Embeddings are 768-dimensional float32 vectors (normalized)

    Ensures:
        - add_decision() inserts a record into the LanceDB table
        - find_similar() returns results sorted by descending similarity
        - update_ratification_state() modifies an existing record
        - All operations are non-fatal (try/except wrapped)
    """

    def __init__( self, db_path, table_name="proxy_decisions", embedding_dim=768, nprobes=20, debug=False ):
        """
        Initialize the proxy decision embedding store.

        Requires:
            - db_path is a valid filesystem path
            - table_name is a non-empty string
            - embedding_dim is a positive integer

        Ensures:
            - Store is configured but table is lazily created on first use

        Args:
            db_path: Path to the LanceDB database directory
            table_name: Name of the table within the database
            embedding_dim: Dimensionality of question embeddings
            nprobes: Number of probes for IVF index search
            debug: Enable debug output
        """
        self.db_path       = db_path
        self.table_name    = table_name
        self.embedding_dim = embedding_dim
        self.nprobes       = nprobes
        self.debug         = debug

        self._db    = None
        self._table = None

    def _get_schema( self ):
        """
        Get PyArrow schema for the proxy_decisions table.

        Ensures:
            - Returns 7-field schema matching the decision record structure
            - question_embedding is a fixed-size list of float32

        Returns:
            pa.Schema
        """
        return pa.schema( [
            pa.field( "id",                  pa.string() ),
            pa.field( "question",            pa.string() ),
            pa.field( "category",            pa.string() ),
            pa.field( "decision_value",      pa.string() ),
            pa.field( "ratification_state",  pa.string() ),
            pa.field( "data_origin",         pa.string() ),
            pa.field( "response_type",       pa.string() ),
            pa.field( "question_embedding",  pa.list_( pa.float32(), self.embedding_dim ) ),
            pa.field( "created_at",          pa.string() ),
        ] )

    def _ensure_table( self ):
        """
        Lazily connect to LanceDB and open or create the table.

        Ensures:
            - self._db and self._table are set on success
            - Returns True if table is ready, False on failure
        """
        if self._table is not None:
            return True

        try:
            self._db = lancedb.connect( self.db_path )

            schema = self._get_schema()
            expected_columns = set( schema.names )

            if self.table_name in self._db.table_names():
                self._table = self._db.open_table( self.table_name )
                existing_columns = set( self._table.schema.names )

                if existing_columns != expected_columns:
                    missing = expected_columns - existing_columns
                    print( f"[ProxyDecisionEmbeddings] Schema mismatch — missing columns: {missing}. Dropping and recreating table." )
                    self._db.drop_table( self.table_name )
                    self._table = self._db.create_table( self.table_name, schema=schema )
                else:
                    if self.debug: print( f"[ProxyDecisionEmbeddings] Opened existing table: {self.table_name}" )
            else:
                self._table = self._db.create_table( self.table_name, schema=schema )
                if self.debug: print( f"[ProxyDecisionEmbeddings] Created new table: {self.table_name}" )

            return True

        except Exception as e:
            if self.debug: print( f"[ProxyDecisionEmbeddings] Failed to initialize table: {e}" )
            return False

    def add_decision( self, id, question, category, decision_value, ratification_state, question_embedding, created_at, data_origin="organic", response_type="" ):
        """
        Insert a decision record into the LanceDB table.

        Requires:
            - id is a non-empty string
            - question_embedding is a list of floats with length == embedding_dim

        Ensures:
            - Record is added to the table on success
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
            if not self._ensure_table():
                return

            record = {
                "id"                 : id,
                "question"           : question,
                "category"           : category,
                "decision_value"     : decision_value,
                "ratification_state" : ratification_state,
                "data_origin"        : data_origin,
                "response_type"      : response_type,
                "question_embedding" : question_embedding,
                "created_at"         : created_at,
            }

            self._table.add( [ record ] )

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
            if not self._ensure_table():
                return []

            search = self._table.search(
                query_embedding,
                vector_column_name="question_embedding"
            ).metric( "dot" ).nprobes( self.nprobes ).limit( limit )

            # Build WHERE clause with optional filters
            where_clauses = []
            if category is not None:
                escaped = category.replace( "'", "''" )
                where_clauses.append( f"category = '{escaped}'" )

            if data_origin is not None:
                escaped_origin = data_origin.replace( "'", "''" )
                where_clauses.append( f"data_origin = '{escaped_origin}'" )

            if response_type is not None:
                escaped_type = response_type.replace( "'", "''" )
                where_clauses.append( f"response_type = '{escaped_type}'" )

            if where_clauses:
                search = search.where( " AND ".join( where_clauses ) )

            results = search.to_list()

            similar = []
            for record in results:
                # With dot metric: _distance = 1 - dot_product (lower = more similar).
                # The dot product is only bounded to [-1, 1] for UNIT-normalized
                # vectors; when stored/query vectors are not unit-norm, _distance can
                # fall outside [0, 1], so ( 1 - distance ) * 100 can exceed 100 or go
                # negative. Clamp to the [0, 100] percentage contract at this boundary
                # so every downstream consumer ( similarity_pct / 100 → confidence ) stays
                # in [0, 1]. An unclamped value is what produced the "22123%" hint bug.
                distance       = record.get( "_distance", 0.0 )
                similarity_pct = max( 0.0, min( 100.0, ( 1.0 - distance ) * 100 ) )

                if similarity_pct >= ( threshold * 100 ):
                    # Remove LanceDB internal fields from record
                    clean_record = {
                        k: v for k, v in record.items()
                        if not k.startswith( "_" )
                    }
                    similar.append( ( similarity_pct, clean_record ) )

            # Sort by descending similarity
            similar.sort( key=lambda x: x[ 0 ], reverse=True )

            if self.debug: print( f"[ProxyDecisionEmbeddings] find_similar: {len( similar )} results above {threshold:.0%}" )

            return similar

        except Exception as e:
            if self.debug: print( f"[ProxyDecisionEmbeddings] find_similar failed (non-fatal): {e}" )
            return []

    def exists( self, id ) -> bool:
        """
        Return True iff a decision with this id is present in the table.

        Lets callers choose the proven insert path (add_decision) vs the proven update
        path (update_ratification_state) for an idempotent upsert, without a manual
        merge_insert (which risks embedding-column schema coercion on a fresh insert).

        Ensures:
            - returns False on any error or missing table (never raises)
        """
        try:
            if not self._ensure_table():
                return False
            escaped = id.replace( "'", "''" )
            return len( self._table.search().where( f"id = '{escaped}'" ).limit( 1 ).to_list() ) > 0
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
            - Failure is logged but never raises

        Args:
            id: Decision identifier to update
            new_state: New ratification state value
        """
        try:
            if not self._ensure_table():
                return

            # Find existing record, update, and re-add
            escaped  = id.replace( "'", "''" )
            results  = self._table.search().where( f"id = '{escaped}'" ).limit( 1 ).to_list()

            if not results:
                if self.debug: print( f"[ProxyDecisionEmbeddings] Record not found for update: {id}" )
                return

            record = results[ 0 ]
            record[ "ratification_state" ] = new_state

            # Remove internal LanceDB fields before re-inserting
            clean_record = { k: v for k, v in record.items() if not k.startswith( "_" ) }

            # Use merge_insert for upsert behavior
            import pyarrow as pa
            update_table = pa.table( { k: [ v ] for k, v in clean_record.items() } )
            self._table.merge_insert( "id" ).when_matched_update_all().execute( update_table )

            if self.debug: print( f"[ProxyDecisionEmbeddings] Updated ratification state: {id} -> {new_state}" )

        except Exception as e:
            if self.debug: print( f"[ProxyDecisionEmbeddings] update_ratification_state failed (non-fatal): {e}" )
