"""
Search result cache for Deep Research agent.

Provides per-user, per-day caching of web search results to:
1. Avoid re-fetching on rate limit failures
2. Enable reuse of similar queries
3. Reduce API costs on reruns

Cache expires daily (new directory per date).
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Optional, List, Tuple

import cosa.utils.util as cu

logger = logging.getLogger( __name__ )


# =============================================================================
# Cache Directory Management
# =============================================================================

def get_cache_dir( user_email: str, date: str = None ) -> str:
    """
    Get cache directory path for user and date.

    Requires:
        - user_email is a valid email string
        - date is YYYY.MM.DD format or None for today

    Ensures:
        - Returns absolute path to cache directory
        - Directory is created if it doesn't exist
    """
    if date is None:
        date = datetime.now().strftime( "%Y.%m.%d" )

    base_dir = cu.get_project_root() + "/io/deep-research"
    cache_dir = f"{base_dir}/{user_email}/cache/{date}"
    os.makedirs( cache_dir, exist_ok=True )
    return cache_dir


# =============================================================================
# Query Normalization
# =============================================================================

def normalize_query( query: str ) -> str:
    """
    Normalize query to cache key (filename-safe).

    Ensures:
        - Lowercase, sorted words, max 6 words
        - Only alphanumeric and hyphens
        - Suitable for filename

    Examples:
        "AI coding assistants" → "search-ai-assistants-coding"
        "coding assistants AI" → "search-ai-assistants-coding" (same!)
        "What are the best LLM tools?" → "search-are-best-llm-the-tools-what"
    """
    # Remove punctuation, lowercase, split
    cleaned = re.sub( r'[^\w\s]', '', query.lower() )
    words = sorted( cleaned.split() )[ :6 ]
    return "search-" + "-".join( words )


# =============================================================================
# Cache Operations
# =============================================================================

def cache_exists( user_email: str, query: str ) -> bool:
    """
    Check if exact/normalized match exists in today's cache.

    Requires:
        - user_email is a valid email string
        - query is a non-empty string

    Ensures:
        - Returns True if cache file exists for normalized query
        - Returns False otherwise
    """
    cache_dir = get_cache_dir( user_email )
    cache_key = normalize_query( query )
    cache_path = f"{cache_dir}/{cache_key}.json"
    return os.path.exists( cache_path )


def load_cached_result( user_email: str, query: str ) -> Optional[ dict ]:
    """
    Load cached search result if exists.

    Requires:
        - user_email is a valid email string
        - query is a non-empty string

    Ensures:
        - Returns dict with 'query', 'timestamp', 'results' if cache hit
        - Returns None if cache miss

    Returns:
        dict with cached data or None
    """
    cache_dir = get_cache_dir( user_email )
    cache_key = normalize_query( query )
    cache_path = f"{cache_dir}/{cache_key}.json"

    if os.path.exists( cache_path ):
        try:
            with open( cache_path, 'r' ) as f:
                data = json.load( f )
                logger.info( f"Cache hit: {cache_key}" )
                return data
        except ( json.JSONDecodeError, IOError ) as e:
            logger.warning( f"Failed to load cache {cache_path}: {e}" )
            return None

    return None


def save_to_cache( user_email: str, query: str, results: dict ) -> str:
    """
    Save search results to cache.

    Requires:
        - user_email is a valid email string
        - query is a non-empty string
        - results is a dict containing search results

    Ensures:
        - Cache file is written to disk
        - Returns path to saved cache file

    Returns:
        str: Path to saved cache file
    """
    cache_dir = get_cache_dir( user_email )
    cache_key = normalize_query( query )
    cache_path = f"{cache_dir}/{cache_key}.json"

    cache_data = {
        "query"          : query,
        "normalized_key" : cache_key,
        "timestamp"      : datetime.now().isoformat(),
        "results"        : results
    }

    try:
        with open( cache_path, 'w' ) as f:
            json.dump( cache_data, f, indent=2 )
        logger.info( f"Saved to cache: {cache_key}" )
    except IOError as e:
        logger.error( f"Failed to save cache {cache_path}: {e}" )

    return cache_path


def list_cached_queries( user_email: str, date: str = None ) -> List[ Tuple[ str, str ] ]:
    """
    List all cached queries for a given date.

    Requires:
        - user_email is a valid email string
        - date is YYYY.MM.DD format or None for today

    Ensures:
        - Returns list of (filename, original_query) tuples
        - Returns empty list if no cache exists

    Returns:
        List of (filename, original_query) tuples
    """
    if date is None:
        date = datetime.now().strftime( "%Y.%m.%d" )

    base_dir = cu.get_project_root() + "/io/deep-research"
    cache_dir = f"{base_dir}/{user_email}/cache/{date}"
    cached = []

    if os.path.exists( cache_dir ):
        for filename in sorted( os.listdir( cache_dir ) ):
            if filename.endswith( ".json" ):
                filepath = f"{cache_dir}/{filename}"
                try:
                    with open( filepath, 'r' ) as f:
                        data = json.load( f )
                        cached.append( ( filename, data.get( "query", filename ) ) )
                except ( json.JSONDecodeError, IOError ):
                    cached.append( ( filename, filename ) )

    return cached


def format_cache_listing( cached_queries: List[ Tuple[ str, str ] ] ) -> str:
    """
    Format cache listing for inclusion in LLM prompts.

    Requires:
        - cached_queries is a list of (filename, original_query) tuples

    Ensures:
        - Returns formatted string suitable for prompt injection
        - Returns empty string if no cached queries

    Returns:
        str: Formatted listing or empty string
    """
    if not cached_queries:
        return ""

    lines = [ "Available cached searches from today:" ]
    for filename, original_query in cached_queries:
        lines.append( f"- {filename} (\"{original_query}\")" )

    return "\n".join( lines )


# =============================================================================
# Cache Maintenance
# =============================================================================

def clear_cache( user_email: str, date: str = None ) -> int:
    """
    Clear cache for a specific date.

    Requires:
        - user_email is a valid email string
        - date is YYYY.MM.DD format or None for today

    Ensures:
        - All cache files for the date are deleted
        - Returns count of deleted files

    Returns:
        int: Number of files deleted
    """
    if date is None:
        date = datetime.now().strftime( "%Y.%m.%d" )

    base_dir = cu.get_project_root() + "/io/deep-research"
    cache_dir = f"{base_dir}/{user_email}/cache/{date}"
    deleted = 0

    if os.path.exists( cache_dir ):
        for filename in os.listdir( cache_dir ):
            if filename.endswith( ".json" ):
                filepath = f"{cache_dir}/{filename}"
                try:
                    os.remove( filepath )
                    deleted += 1
                except IOError as e:
                    logger.warning( f"Failed to delete {filepath}: {e}" )

    return deleted


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for search_cache module."""

    cu.print_banner( "Search Cache Smoke Test", prepend_nl=True )

    try:
        # Test 1: normalize_query
        print( "Testing normalize_query..." )
        assert normalize_query( "AI coding assistants" ) == "search-ai-assistants-coding"
        assert normalize_query( "coding assistants AI" ) == "search-ai-assistants-coding"
        assert normalize_query( "What are the BEST tools?" ) == "search-are-best-the-tools-what"
        print( "✓ normalize_query works correctly" )

        # Test 2: get_cache_dir
        print( "Testing get_cache_dir..." )
        test_email = "test@example.com"
        cache_dir = get_cache_dir( test_email )
        assert test_email in cache_dir
        assert "cache" in cache_dir
        assert os.path.exists( cache_dir )
        print( f"✓ Cache dir created: {cache_dir}" )

        # Test 3: save_to_cache and load_cached_result
        print( "Testing save/load cycle..." )
        test_query = "test query for smoke test"
        test_results = { "content": "test content", "tokens": 100 }

        save_path = save_to_cache( test_email, test_query, test_results )
        assert os.path.exists( save_path )
        print( f"✓ Saved to: {save_path}" )

        loaded = load_cached_result( test_email, test_query )
        assert loaded is not None
        assert loaded[ "query" ] == test_query
        assert loaded[ "results" ][ "content" ] == "test content"
        print( "✓ Load returned correct data" )

        # Test 4: cache_exists
        print( "Testing cache_exists..." )
        assert cache_exists( test_email, test_query ) is True
        assert cache_exists( test_email, "nonexistent query xyz" ) is False
        print( "✓ cache_exists works correctly" )

        # Test 5: list_cached_queries
        print( "Testing list_cached_queries..." )
        cached = list_cached_queries( test_email )
        assert len( cached ) >= 1
        filenames = [ f for f, q in cached ]
        assert any( "search-" in f for f in filenames )
        print( f"✓ Found {len( cached )} cached queries" )

        # Test 6: format_cache_listing
        print( "Testing format_cache_listing..." )
        listing = format_cache_listing( cached )
        assert "Available cached searches" in listing
        print( "✓ format_cache_listing works" )

        # Test 7: clear_cache (cleanup)
        print( "Testing clear_cache..." )
        deleted = clear_cache( test_email )
        assert deleted >= 1
        print( f"✓ Cleared {deleted} cache files" )

        print( "\n✓ Search cache smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
