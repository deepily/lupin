"""
Embedding Cache Table backed by Postgres+pgvector.

Manages normalized text embedding cache to improve performance and reduce
OpenAI API calls by storing frequently requested embeddings.

Storage runs through EmbeddingCacheRepository; each call opens a short-lived
get_db() session (commit on success / rollback on error).
"""

from typing import Optional
import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager


class EmbeddingCacheTable:
    """
    Manages normalized text embedding cache in Postgres+pgvector.

    Caches embeddings for normalized text to avoid regenerating them.
    Supports embedding lookup and storage with singleton pattern.
    """
    def __init__( self, debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize the embedding cache table.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set or defaults available

        Ensures:
            - Reads the standardized embedding dimension from configuration
            - Opens no connection of its own; storage sessions are per-call

        Raises:
            - ConfigurationManager errors propagated
        """

        self.debug       = debug
        self.verbose     = verbose
        self._config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Get standardized embedding dimension from config
        self._embedding_dim = int( self._config_mgr.get( "embedding dimensions", default="768" ) )

    def has_cached_embedding( self, normalized_text: str ) -> bool:
        """
        Check if a normalized text has cached embedding.

        Requires:
            - normalized_text is a non-empty string

        Ensures:
            - Returns True if normalized text exists in the store
            - Returns False if normalized text not found
            - Performs exact string match

        Raises:
            - Repository/session errors propagated
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.embedding_cache_repository import EmbeddingCacheRepository
        with get_db() as session:
            return EmbeddingCacheRepository( session ).has_cached_embedding( normalized_text )

    def get_cached_embedding( self, normalized_text: str ) -> Optional[ list[ float ] ]:
        """
        Get the cached embedding for the given normalized text.

        Requires:
            - normalized_text is a non-empty string

        Ensures:
            - Returns embedding from cache if found
            - Returns None if not in cache

        Raises:
            - Repository/session errors propagated
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.embedding_cache_repository import EmbeddingCacheRepository
        with get_db() as session:
            return EmbeddingCacheRepository( session ).get_cached_embedding( normalized_text )

    def cache_embedding( self, normalized_text: str, embedding: list[ float ] ) -> None:
        """
        Add a normalized text and its embedding to the cache.

        Requires:
            - normalized_text is a non-empty string
            - embedding is a list of floats of the configured dimension

        Ensures:
            - Appends a normalized_text → embedding row to the store

        Raises:
            - Repository/session errors propagated
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.embedding_cache_repository import EmbeddingCacheRepository
        with get_db() as session:
            EmbeddingCacheRepository( session ).cache_embedding( normalized_text, embedding )


def quick_smoke_test():
    """Quick smoke test to validate EmbeddingCacheTable functionality."""
    du.print_banner( "EmbeddingCacheTable Smoke Test", prepend_nl=True )

    try:
        # Test 1: Initialize table
        print( "Test 1: Initializing EmbeddingCacheTable..." )
        cache_table = EmbeddingCacheTable( debug=False )
        print( "✓ EmbeddingCacheTable initialized successfully" )

        # Test 2: Check cache miss
        test_text = "what time is it"
        print( f"\nTest 2: Checking cache for '{test_text}'..." )
        has_cached = cache_table.has_cached_embedding( test_text )
        print( f"✓ Cache check complete: {'HIT' if has_cached else 'MISS'}" )

        # Test 3: Cache an embedding (simulate with dummy data)
        print( f"\nTest 3: Caching dummy embedding for '{test_text}'..." )
        dummy_embedding = [ 0.1 ] * cache_table._embedding_dim
        cache_table.cache_embedding( test_text, dummy_embedding )
        print( "✓ Embedding cached successfully" )

        # Test 4: Verify cache hit
        print( f"\nTest 4: Verifying cache hit for '{test_text}'..." )
        has_cached_after = cache_table.has_cached_embedding( test_text )
        if has_cached_after:
            print( "✓ Cache HIT verified" )

            # Test 5: Retrieve cached embedding
            print( f"\nTest 5: Retrieving cached embedding..." )
            retrieved_embedding = cache_table.get_cached_embedding( test_text )
            if retrieved_embedding and len( retrieved_embedding ) == cache_table._embedding_dim:
                print( f"✓ Retrieved embedding with {len( retrieved_embedding )} dimensions" )
                print( f"  First 5 values: {retrieved_embedding[ :5 ]}" )
            else:
                print( "✗ Failed to retrieve valid embedding" )
        else:
            print( "✗ Cache miss after caching - unexpected!" )

        # Test 6: Test different normalized texts
        print( f"\nTest 6: Testing cache with different texts..." )
        test_texts = [ "hello world", "123 main street", "user@example.com" ]
        for text in test_texts:
            has_cache = cache_table.has_cached_embedding( text )
            print( f"  '{text}': {'HIT' if has_cache else 'MISS'}" )

        print( "\n✓ All basic cache operations completed successfully" )

    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Smoke test failed", caller="EmbeddingCacheTable.quick_smoke_test()" )

    print( "\n✓ EmbeddingCacheTable smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
