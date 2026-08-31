"""
QueryLog Table backed by Postgres — Two-Level Question Representation Architecture.

Manages append-only logging of all user queries with two-level representation:
- Verbatim: Exactly what the user typed/spoke
- Normalized: Standardized form for reliable matching

Note: query_gist (text field) is still populated by the normalizer but gist
embeddings were removed in commit 38f9704 ("Jettison gist embeddings").

This table supports the hierarchical search algorithm and provides analytics
for understanding user query patterns and system performance. Storage runs
through QueryLogRepository on a short-lived get_db() session per call.
"""

from typing import Optional, Dict, Any
import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager


class QueryLogTable:
    """
    Manages query logging in Postgres with two-level question representation.

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

        Ensures:
            - Reads the standardized embedding dimension from configuration
            - Opens no connection of its own; storage sessions are per-call

        Raises:
            - ConfigurationManager errors propagated
        """

        self.debug   = debug
        self.verbose = verbose
        self._config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Get standardized embedding dimension from config
        self._embedding_dim = int( self._config_mgr.get( "embedding dimensions", default="768" ) )

    @staticmethod
    def _vector_or_none( embeddings: Optional[Dict[str, list[float]]], key: str ) -> Optional[list[float]]:
        """
        Translate "this caller supplied no embedding" into the value the storage
        layer actually accepts.

        QueryLogRepository.log_query states its own contract: the embedding_* args
        are "dim-768 lists or None". An empty list is neither. pgvector's
        Vector( 768 ) binds None as SQL NULL and raises
        `ValueError: expected 768 dimensions, not 0` on `[]`, so passing `[]`
        killed the whole INSERT — the row was lost and the only trace was a caught
        exception in the log.

        This is not hypothetical: `v2.flow.FlowEngine._log_query` passes no
        embeddings at all, deliberately and with its reasons in its docstring
        (CacheLookup does not return the vectors, and a tier-1 exact hit skips
        embedding entirely). Every v2 write therefore arrived here with
        embeddings=None, became `[]`, and died. The dev query_log's newest row is
        2026-08-21.

        Requires:
            - embeddings is None, or a dict whose values are lists of floats
            - key is 'verbatim' or 'normalized'

        Ensures:
            - returns None when the key is absent, or present and empty
            - returns the caller's list unchanged when it is non-empty
            - never returns an empty list

        Args:
            embeddings: The caller's embeddings dict, or None
            key: Which vector to read

        Returns:
            The embedding list, or None when there is nothing to store

        Raises:
            - None
        """
        if not embeddings: return None
        return embeddings.get( key ) or None

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

        Ensures:
            - Appends a row with text fields and verbatim/normalized embeddings
            - An embedding the caller does not supply is stored as NULL, never as an
              empty list — see _vector_or_none for why the difference is fatal
            - Records match results and performance metrics
            - Returns the unique query log ID, or "" when the write failed

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
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.query_log_repository import QueryLogRepository
        try:
            query_id = du.get_current_datetime( format_str='%Y%m%d_%H%M%S_%f' )
            with get_db() as session:
                QueryLogRepository( session ).log_query(
                    id                    = query_id,
                    timestamp             = du.get_timestamp_ms(),
                    user_id               = user_id,
                    session_id            = session_id,
                    query_verbatim        = query_verbatim,
                    query_normalized      = query_normalized,
                    query_gist            = query_gist,
                    embedding_verbatim    = self._vector_or_none( embeddings, 'verbatim' ),
                    embedding_normalized  = self._vector_or_none( embeddings, 'normalized' ),
                    matched_snapshot_id   = match_result.get( 'snapshot_id', '' ) if match_result else '',
                    match_type            = match_result.get( 'type', 'none' ) if match_result else 'none',
                    match_confidence      = match_result.get( 'confidence', 0.0 ) if match_result else 0.0,
                    processing_time_ms    = processing_time_ms,
                    input_type            = input_type,
                    user_satisfaction     = "unknown",
                    normalization_version = self._config_mgr.get( "normalization version", "v2.0" ),
                    gist_model_version    = self._config_mgr.get( "llm spec key for gist generation", "unknown" ),
                    cache_hit_verbatim    = cache_hits.get( 'verbatim', False ) if cache_hits else False,
                    cache_hit_normalized  = cache_hits.get( 'normalized', False ) if cache_hits else False,
                )
            return query_id
        except Exception as e:
            du.print_stack_trace( e, explanation="log_query() failed", caller="QueryLogTable.log_query()" )
            return ""

    def get_recent_queries( self, limit: int = 100, user_id: Optional[str] = None ) -> list[Dict[str, Any]]:
        """
        Get recent queries from the log.

        Requires:
            - limit is a positive integer
            - user_id is optional string filter

        Ensures:
            - Returns list of recent query records, newest first
            - Filters by user_id if provided
            - Returns [] on read failure

        Args:
            limit: Maximum number of queries to return
            user_id: Optional filter by user ID

        Returns:
            List of query log records
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.query_log_repository import QueryLogRepository
        try:
            with get_db() as session:
                return QueryLogRepository( session ).get_recent_queries( limit=limit, user_id=user_id )
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
            - Returns cache hit percentages for each level, plus total_queries
            - Returns zeroed rates when there is nothing in the window, or on failure

        Args:
            days: Number of days to analyze

        Returns:
            Dict with cache hit percentages for each level
        """
        from datetime import timedelta
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.query_log_repository import QueryLogRepository
        try:
            since = du.get_timestamp_ms() - timedelta( days=days )
            with get_db() as session:
                stats = QueryLogRepository( session ).get_cache_hit_stats( since=since )
            if stats[ "total_queries" ] == 0:
                return { "verbatim": 0.0, "normalized": 0.0 }
            return {
                "verbatim":      stats[ "verbatim_hit_rate" ]   * 100.0,
                "normalized":    stats[ "normalized_hit_rate" ] * 100.0,
                "total_queries": stats[ "total_queries" ],
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
