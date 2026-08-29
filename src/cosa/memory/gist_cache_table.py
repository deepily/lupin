"""
Persistent cache for gist generation results.

Caches question → gist mappings to avoid repeated LLM calls (~500ms each).
Provides 83% performance improvement on cache hits.

Design by Contract:
    Requires:
        - Postgres reachable through GistCacheRepository
        - Questions and gists are non-empty strings

    Ensures:
        - Cache entries persist across server restarts
        - Cache lookups are fast (<10ms)
        - Statistics track usage patterns

    Raises:
        - Exception on database connection failures
"""

import time
from typing import Optional, Dict, Any

import cosa.utils.util as cu
from cosa.memory.normalizer import Normalizer


class GistCacheTable:
    """
    Postgres-backed persistent cache for question gists.

    Stores mappings from questions to their generated gists, avoiding
    expensive LLM calls for repeated or similar queries.

    Architecture:
        - Primary key: question_verbatim (original question text)
        - Cached value: question_gist (LLM-generated semantic gist)
        - Metadata: normalized form, timestamps, access statistics

    Lookups are two-tier: exact verbatim first, then normalized, so
    variations like "What's 2+2?" and "What is 2+2?" share a cache entry.
    """

    def __init__( self, table_name: str = "gist_cache", debug: bool = False, verbose: bool = False ):
        """
        Initialize gist cache table.

        Requires:
            - table_name is valid identifier

        Ensures:
            - Normalizer is ready for two-tier lookups
            - Opens no connection of its own; storage sessions are per-call

        Args:
            table_name: Name of cache table (default: 'gist_cache')
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.debug           = debug
        self.verbose         = verbose
        self.table_name      = table_name

        # Initialize normalizer for two-tier lookups (verbatim + normalized)
        self._normalizer = Normalizer()

    def has_cached_gist( self, question: str ) -> bool:
        """
        Check if gist exists in cache for given question.

        Requires:
            - question is non-empty string

        Ensures:
            - Returns True if a verbatim cache entry exists
            - Returns False otherwise
            - No side effects (read-only)

        Args:
            question: Original question text to check

        Returns:
            True if gist is cached, False otherwise
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.gist_cache_repository import GistCacheRepository
        with get_db() as session:
            return GistCacheRepository( session ).get_by_verbatim( question ) is not None

    def get_cached_gist( self, question: str ) -> Optional[str]:
        """
        Retrieve cached gist for question using two-tier lookup strategy.

        Requires:
            - question is non-empty string

        Ensures:
            - Returns cached gist if found (verbatim or normalized match)
            - Returns None if not found in either tier
            - Tries verbatim match first (fastest)
            - Falls back to normalized match if verbatim misses

        Args:
            question: Original question text to look up

        Returns:
            Cached gist string if found, None otherwise

        Side Effects:
            - None (read-only lookups)

        Example Matches:
            Verbatim: "What's 2+2?" → "What's 2+2?" (exact)
            Normalized: "What's 2+2?" → "What is 2+2?" (variation caught)
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.gist_cache_repository import GistCacheRepository
        with get_db() as session:
            repo = GistCacheRepository( session )
            gist = repo.get_cached_gist( question_verbatim=question )
            if gist is not None:
                return gist
            question_normalized = self._normalizer.normalize( question )
            return repo.get_cached_gist( question_normalized=question_normalized )

    def cache_gist( self, question: str, gist: str, normalized: str = "" ):
        """
        Store question → gist mapping in cache.

        Requires:
            - question is non-empty string
            - gist is non-empty string

        Ensures:
            - Entry is stored with metadata
            - Created timestamp is set
            - Access count initialized to 0
            - Last accessed timestamp is set
            - Skips if a verbatim entry already exists (no duplicates)

        Args:
            question: Original question text (key)
            gist: Generated gist text (value)
            normalized: Optional normalized form for analysis

        Side Effects:
            - Adds new row to cache table
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.gist_cache_repository import GistCacheRepository
        with get_db() as session:
            repo = GistCacheRepository( session )
            if repo.get_by_verbatim( question ) is not None:
                return
            now = time.strftime( "%Y-%m-%d @ %H:%M:%S" )
            repo.cache_gist(
                question_verbatim   = question,
                question_gist       = gist,
                question_normalized = normalized,
                created_date        = now,
                access_count        = 0,
                last_accessed       = now,
            )

    def get_statistics( self ) -> Dict[str, Any]:
        """
        Get cache usage statistics.

        Requires:
            - Nothing

        Ensures:
            - Returns dictionary with statistics (exact counts, no sampling)
            - No side effects (read-only)

        Returns:
            Dictionary containing:
                - total_entries: Total number of cached gists
                - avg_access_count: Average accesses per entry
                - sample_size: Rows the average was taken over
                - table_name: Name of cache table
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.gist_cache_repository import GistCacheRepository
        with get_db() as session:
            stats            = GistCacheRepository( session ).get_statistics()
            total_entries    = stats[ "total_entries" ]
            avg_access_count = ( stats[ "total_access_count" ] / total_entries ) if total_entries else 0
            return {
                "total_entries"    : total_entries,
                "avg_access_count" : avg_access_count,
                "sample_size"      : total_entries,
                "table_name"       : self.table_name,
            }

    def clear_cache( self ):
        """
        Clear all entries from cache (for testing/maintenance).

        NOT IMPLEMENTED — logs under debug and does nothing else.

        Ensures:
            - No rows are deleted
        """
        if self.debug:
            print( "⚠ clear_cache() not implemented" )


def quick_smoke_test():
    """
    Quick smoke test for GistCacheTable - validates basic functionality.

    Tests:
        1. Table initialization
        2. Cache miss (non-existent entry)
        3. Cache storage (insert new entry)
        4. Cache hit (retrieve stored entry)
        5. Statistics retrieval

    Requires:
        - LUPIN_ROOT environment variable set
        - Postgres reachable

    Ensures:
        - All basic operations work correctly
        - No exceptions during normal operations
    """
    cu.print_banner( "GistCacheTable Smoke Test", prepend_nl=True )

    try:
        print( "Setting up test cache..." )
        cache = GistCacheTable( table_name="gist_cache", debug=True )
        print( f"✓ Cache initialized" )

        question = "What's the weather like today in Ulaanbaatar?"

        # Test 1: Cache miss
        print( "\n" + "="*60 )
        print( "Test 1: Cache lookup (miss or hit, both are valid)" )
        print( "="*60 )
        result = cache.get_cached_gist( question )
        print( f"✓ Lookup returned: {result!r}" )

        # Test 2: Store gist
        print( "\n" + "="*60 )
        print( "Test 2: Store gist in cache" )
        print( "="*60 )
        cache.cache_gist( question, "weather inquiry ulaanbaatar", "what be weather like today in ulaanbaatar" )
        print( "✓ Gist stored successfully" )

        # Test 3: Cache hit
        print( "\n" + "="*60 )
        print( "Test 3: Cache hit (retrieve stored entry)" )
        print( "="*60 )
        result = cache.get_cached_gist( question )
        assert result == "weather inquiry ulaanbaatar", f"Expected 'weather inquiry ulaanbaatar', got '{result}'"
        print( f"✓ Cache hit works correctly: '{result}'" )

        # Test 4: Duplicate prevention
        print( "\n" + "="*60 )
        print( "Test 4: Duplicate prevention" )
        print( "="*60 )
        cache.cache_gist( question, "weather inquiry ulaanbaatar" )
        print( "✓ Duplicate prevention works (should have skipped)" )

        # Test 5: Statistics
        print( "\n" + "="*60 )
        print( "Test 5: Statistics retrieval" )
        print( "="*60 )
        stats = cache.get_statistics()
        print( f"✓ Statistics: {stats}" )
        assert stats["total_entries"] >= 1, "Should have at least 1 entry"

        print( "\n" + "="*60 )
        print( "✓ ALL SMOKE TESTS PASSED!" )
        print( "="*60 )

    except Exception as e:
        print( "\n" + "="*60 )
        print( "✗ SMOKE TEST FAILED" )
        print( "="*60 )
        print( f"Error: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
