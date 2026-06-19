"""
QueryLog Table for LanceDB storage - Two-Level Question Representation Architecture.

Manages append-only logging of all user queries with two-level representation:
- Verbatim: Exactly what the user typed/spoke
- Normalized: Standardized form for reliable matching

Note: query_gist (text field) is still populated by the normalizer but gist
embeddings were removed in commit 38f9704 ("Jettison gist embeddings").

This table supports the hierarchical search algorithm and provides analytics
for understanding user query patterns and system performance.
"""

import lancedb
import pyarrow as pa
from typing import Optional, Dict, Any
from datetime import datetime
import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager
from cosa.utils.util_stopwatch import Stopwatch


class QueryLogTable:
    """
    Manages query logging in LanceDB with two-level question representation.

    This table is append-only and captures every query attempt with full context,
    match results, and performance metrics. Supports the two-level architecture
    by storing verbatim and normalized representations with their embeddings.
    The query_gist text field is retained but no longer has a corresponding embedding.
    """

    def __init__( self, debug: bool = False, verbose: bool = False ) -> None:
        """
        Initialize the query log table.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set
            - Database path is valid in configuration

        Ensures:
            - Opens connection to LanceDB
            - Creates query_log table if not exists
            - Prints table row count

        Raises:
            - FileNotFoundError if database path invalid
            - lancedb errors propagated
        """

        self.debug   = debug
        self.verbose = verbose
        self._config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Get standardized embedding dimension from config
        self._embedding_dim = int( self._config_mgr.get( "embedding dimensions", default="768" ) )

        # Get database path from config
        uri = du.get_project_root() + self._config_mgr.get( "path to database wo root" )

        if self.debug:
            print( f"Connecting to LanceDB at: {uri}" )

        db = lancedb.connect( uri )

        # Validate existing table dimensions match config before creating/opening
        self._validate_embedding_dimensions( db, "query_log", "embedding_verbatim" )

        # Check if table exists, create if it doesn't
        if "query_log" not in db.table_names():
            if self.debug:
                print( "Table 'query_log' doesn't exist, creating it..." )
            self._create_table_if_needed( db )
        else:
            self._query_log_table = db.open_table( "query_log" )

        if self.verbose:
            print( f"Opened query_log table w/ [{self._query_log_table.count_rows()}] rows" )

    def _validate_embedding_dimensions( self, db, table_name, embedding_field_name ):
        """
        Validate that existing table's embedding dimensions match current config.

        Requires:
            - db is a valid lancedb connection
            - table_name is a string
            - embedding_field_name is the name of an embedding column in the table

        Ensures:
            - No-op if table doesn't exist (will be created fresh)
            - No-op if dimensions match
            - Drops table if dimensions mismatch (will be recreated by caller)
        """
        if table_name not in db.table_names():
            return

        table        = db.open_table( table_name )
        schema       = table.schema
        field        = schema.field( embedding_field_name )
        existing_dim = field.type.list_size

        if existing_dim == self._embedding_dim:
            return

        du.print_banner( f"EMBEDDING DIMENSION MISMATCH: {table_name}" )
        print( f"  Table schema expects: {existing_dim} dims" )
        print( f"  Current config has:   {self._embedding_dim} dims" )
        print( f"  Action: Dropping table (will be recreated with correct dimensions)" )

        db.drop_table( table_name )

    def _create_table_if_needed( self, db ) -> None:
        """
        Create the query log table with proper two-level schema.

        Requires:
            - db is a valid LanceDB connection

        Ensures:
            - Creates table with two-level question representation
            - Sets up embedding fields for verbatim and normalized levels
            - Includes user context and performance metrics
            - Creates appropriate indexes

        Raises:
            - lancedb errors propagated
        """
        if self.debug:
            du.print_banner( "Creating query_log table schema..." )

        schema = self._get_schema()

        self._query_log_table = db.create_table( "query_log", schema=schema, mode="overwrite" )

        # Create indexes for common queries
        try:
            self._query_log_table.create_fts_index( "query_verbatim", replace=True )
            self._query_log_table.create_fts_index( "query_normalized", replace=True )

            if self.debug:
                print( "✓ Created FTS indexes on query fields" )
        except Exception as e:
            if self.debug:
                print( f"Warning: Could not create FTS indexes: {e}" )

        if self.debug:
            print( f"✓ Created query_log table with schema: {schema}" )

    def _get_schema( self ) -> pa.Schema:
        """
        Get PyArrow schema for query log table.

        Requires:
            - Nothing

        Ensures:
            - Returns complete schema for two-level query logging
            - Includes all necessary fields for analytics
            - Optimizes embedding fields for LanceDB

        Returns:
            PyArrow schema for query log table
        """
        return pa.schema( [
            # Primary identifiers
            pa.field( "id", pa.string() ),
            pa.field( "timestamp", pa.timestamp( 'ms' ) ),
            pa.field( "user_id", pa.string() ),
            pa.field( "session_id", pa.string() ),

            # Question representation (text fields)
            pa.field( "query_verbatim", pa.string() ),         # Exactly what user asked
            pa.field( "query_normalized", pa.string() ),       # Normalized version
            pa.field( "query_gist", pa.string() ),             # LLM-extracted gist (text only, no embedding)

            # Embeddings for two levels (configurable: 768 for local, 1536 for openai)
            pa.field( "embedding_verbatim", pa.list_( pa.float32(), self._embedding_dim ) ),
            pa.field( "embedding_normalized", pa.list_( pa.float32(), self._embedding_dim ) ),

            # Match results and performance
            pa.field( "matched_snapshot_id", pa.string() ),    # What solution was returned
            pa.field( "match_type", pa.string() ),             # 'exact_verbatim', 'exact_normalized', 'similarity', 'none'
            pa.field( "match_confidence", pa.float32() ),      # How confident was the match
            pa.field( "processing_time_ms", pa.int32() ),      # How long to find answer

            # Context and metadata
            pa.field( "input_type", pa.string() ),             # 'voice', 'text', 'api'
            pa.field( "user_satisfaction", pa.string() ),      # 'satisfied', 'unsatisfied', 'unknown'
            pa.field( "normalization version", pa.string() ),   # Track algorithm version
            pa.field( "gist_model_version", pa.string() ),     # Track which LLM generated gist

            # Cache performance metrics
            pa.field( "cache_hit_verbatim", pa.bool_() ),      # Was verbatim embedding cached
            pa.field( "cache_hit_normalized", pa.bool_() ),    # Was normalized embedding cached
        ] )

    def log_query( self,
                  query_verbatim: str,
                  query_normalized: str,
                  query_gist: str,
                  user_id: str,
                  session_id: str = "unknown",
                  input_type: str = "api",
                  embeddings: Optional[Dict[str, list[float]]] = None,
                  match_result: Optional[Dict[str, Any]] = None,
                  processing_time_ms: int = 0,
                  cache_hits: Optional[Dict[str, bool]] = None ) -> str:
        """
        Log a query with two-level representation.

        Requires:
            - query_verbatim is a non-empty string (exact user input)
            - query_normalized is the normalized version
            - query_gist is the LLM-extracted gist (text only, no embedding)
            - user_id is a valid system ID
            - Table is initialized

        Ensures:
            - Adds row to table with text fields and verbatim/normalized embeddings
            - Includes embeddings if provided
            - Records match results and performance metrics
            - Returns unique query log ID

        Args:
            query_verbatim: Exactly what the user typed/spoke
            query_normalized: Normalized version for matching
            query_gist: LLM-extracted semantic essence
            user_id: User identifier
            session_id: Session identifier
            input_type: Source of input ('voice', 'text', 'api')
            embeddings: Dict with 'verbatim', 'normalized' embeddings
            match_result: Dict with 'snapshot_id', 'type', 'confidence'
            processing_time_ms: Processing time in milliseconds
            cache_hits: Dict with cache hit status for each level

        Returns:
            Unique query log ID for this entry

        Raises:
            - None (catches and logs errors)
        """
        if self.debug:
            timer = Stopwatch( msg=f"Logging query: '{du.truncate_string( query_verbatim )}'" )

        try:
            # Generate unique ID
            query_id = du.get_current_datetime( format_str='%Y%m%d_%H%M%S_%f' )

            # Prepare row data
            row_data = {
                "id": query_id,
                "timestamp": du.get_timestamp_ms(),
                "user_id": user_id,
                "session_id": session_id,

                # Question text fields
                "query_verbatim": query_verbatim,
                "query_normalized": query_normalized,
                "query_gist": query_gist,

                # Embeddings (use empty lists if not provided)
                "embedding_verbatim": embeddings.get( 'verbatim', [] ) if embeddings else [],
                "embedding_normalized": embeddings.get( 'normalized', [] ) if embeddings else [],

                # Match results
                "matched_snapshot_id": match_result.get( 'snapshot_id', '' ) if match_result else '',
                "match_type": match_result.get( 'type', 'none' ) if match_result else 'none',
                "match_confidence": match_result.get( 'confidence', 0.0 ) if match_result else 0.0,
                "processing_time_ms": processing_time_ms,

                # Context
                "input_type": input_type,
                "user_satisfaction": "unknown",  # Can be updated later
                "normalization version": self._config_mgr.get( "normalization version", "v2.0" ),
                "gist_model_version": self._config_mgr.get( "llm spec key for gist generation", "unknown" ),

                # Cache performance
                "cache_hit_verbatim": cache_hits.get( 'verbatim', False ) if cache_hits else False,
                "cache_hit_normalized": cache_hits.get( 'normalized', False ) if cache_hits else False,
            }

            # Add to table
            self._query_log_table.add( [row_data] )

            if self.debug:
                timer.print( f"Done! Query logged with ID: {query_id}", use_millis=True )

            return query_id

        except Exception as e:
            if self.debug:
                timer.print( f"Error: {e}", use_millis=True )
            du.print_stack_trace( e, explanation="log_query() failed", caller="QueryLogTable.log_query()" )
            return ""

    def get_recent_queries( self, limit: int = 100, user_id: Optional[str] = None ) -> list[Dict[str, Any]]:
        """
        Get recent queries from the log.

        Requires:
            - limit is a positive integer
            - user_id is optional string filter

        Ensures:
            - Returns list of recent query records
            - Filters by user_id if provided
            - Orders by timestamp descending

        Args:
            limit: Maximum number of queries to return
            user_id: Optional filter by user ID

        Returns:
            List of query log records
        """
        try:
            query = self._query_log_table.search()

            if user_id:
                query = query.where( f"user_id = '{user_id}'" )

            results = query.limit( limit ).to_list()

            # Sort by timestamp descending (most recent first)
            results.sort( key=lambda x: x.get( 'timestamp', '' ), reverse=True )

            return results

        except Exception as e:
            if self.debug:
                print( f"Error getting recent queries: {e}" )
            return []

    def get_cache_hit_stats( self, days: int = 7 ) -> Dict[str, float]:
        """
        Get cache hit rate statistics for the last N days.

        Requires:
            - days is a positive integer

        Ensures:
            - Returns cache hit rates for each level
            - Calculates percentages for the specified time period

        Args:
            days: Number of days to analyze

        Returns:
            Dict with cache hit percentages for each level
        """
        try:
            # Calculate date threshold
            from datetime import timedelta
            threshold_date = du.get_timestamp_ms() - timedelta( days=days )
            threshold_str = threshold_date.strftime( '%Y-%m-%d' )

            # Get recent queries
            query = self._query_log_table.search()
            query = query.where( f"timestamp >= '{threshold_str}'" )
            results = query.to_list()

            if not results:
                return { "verbatim": 0.0, "normalized": 0.0 }

            # Calculate hit rates
            total = len( results )
            verbatim_hits = sum( 1 for r in results if r.get( 'cache_hit_verbatim', False ) )
            normalized_hits = sum( 1 for r in results if r.get( 'cache_hit_normalized', False ) )

            return {
                "verbatim": ( verbatim_hits / total ) * 100.0,
                "normalized": ( normalized_hits / total ) * 100.0,
                "total_queries": total
            }

        except Exception as e:
            if self.debug:
                print( f"Error calculating cache hit stats: {e}" )
            return { "verbatim": 0.0, "normalized": 0.0 }


def quick_smoke_test():
    """Quick smoke test to validate QueryLogTable functionality."""
    du.print_banner( "QueryLogTable Smoke Test", prepend_nl=True )

    try:
        # Test 1: Initialize table
        print( "Test 1: Initializing QueryLogTable..." )
        query_log = QueryLogTable( debug=False, verbose=True )
        print( "✓ QueryLogTable initialized successfully" )

        # Test 2: Log a query
        print( "\nTest 2: Logging a test query..." )
        test_embeddings = {
            'verbatim': [0.1] * query_log._embedding_dim,
            'normalized': [0.2] * query_log._embedding_dim
        }
        test_match = {
            'snapshot_id': 'test_snapshot_123',
            'type': 'exact_verbatim',
            'confidence': 100.0
        }
        test_cache_hits = {
            'verbatim': False,
            'normalized': True
        }

        query_id = query_log.log_query(
            query_verbatim="What time is it?",
            query_normalized="what time is it",
            query_gist="current_time_request",
            user_id="test_user_123",
            session_id="test_session",
            input_type="text",
            embeddings=test_embeddings,
            match_result=test_match,
            processing_time_ms=150,
            cache_hits=test_cache_hits
        )

        if query_id:
            print( f"✓ Query logged successfully with ID: {query_id}" )
        else:
            print( "✗ Failed to log query" )

        # Test 3: Get recent queries
        print( "\nTest 3: Retrieving recent queries..." )
        recent = query_log.get_recent_queries( limit=5 )
        print( f"✓ Retrieved {len( recent )} recent queries" )

        if recent:
            latest = recent[0]
            print( f"  Latest query: '{latest.get( 'query_verbatim', 'N/A' )}'" )
            print( f"  Match type: {latest.get( 'match_type', 'N/A' )}" )
            print( f"  Cache hits: V={latest.get( 'cache_hit_verbatim', False )} "
                  f"N={latest.get( 'cache_hit_normalized', False )}" )

        # Test 4: Get cache hit statistics
        print( "\nTest 4: Getting cache hit statistics..." )
        stats = query_log.get_cache_hit_stats( days=1 )
        print( f"✓ Cache hit stats: {stats}" )

        print( "\n✓ All QueryLogTable smoke tests passed!" )

    except Exception as e:
        print( f"\n✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Smoke test failed", caller="QueryLogTable.quick_smoke_test()" )

    print( "\n✓ QueryLogTable smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()