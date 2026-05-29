"""
Embedding Cache Table for LanceDB storage.

Manages normalized text embedding cache to improve performance and reduce
OpenAI API calls by storing frequently requested embeddings.
"""

import lancedb
from typing import Optional
import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager
from cosa.utils.util_stopwatch import Stopwatch


class EmbeddingCacheTable:
    """
    Manages normalized text embedding cache in LanceDB.
    
    Caches embeddings for normalized text to avoid regenerating them.
    Supports embedding lookup and storage with singleton pattern.
    """
    def __init__( self, debug: bool=False, verbose: bool=False ) -> None:
        """
        Initialize the embedding cache table.
        
        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set or defaults available
            - Database path is valid in configuration
            
        Ensures:
            - Opens connection to LanceDB
            - Opens embedding_cache_tbl
            - Prints table row count
            
        Raises:
            - FileNotFoundError if database path invalid
            - lancedb errors propagated
        """
        
        self.debug       = debug
        self.verbose     = verbose
        self._config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Get standardized embedding dimension from config
        self._embedding_dim = int( self._config_mgr.get( "embedding dimensions", default="768" ) )

        uri = du.get_project_root() + self._config_mgr.get( "path to database wo root" )

        db = lancedb.connect( uri )

        # Validate existing table dimensions match config before creating/opening
        self._validate_embedding_dimensions( db, "embedding_cache_tbl", "embedding" )

        # Check if table exists, create if it doesn't
        if "embedding_cache_tbl" not in db.table_names():
            if self.debug:
                print( "Table 'embedding_cache_tbl' doesn't exist, creating it..." )
            self._create_table_if_needed( db )
        else:
            self._embedding_cache_tbl = db.open_table( "embedding_cache_tbl" )

            # Check for corruption and recover if needed
            if self._is_table_corrupted():
                print( "⚠️ WARNING: embedding_cache_tbl is corrupted, recreating..." )
                db.drop_table( "embedding_cache_tbl" )
                self._create_table_if_needed( db )
                print( "✓ Table recreated successfully (cache was cleared)" )

        try:
            row_count = self._embedding_cache_tbl.count_rows()
            print( f"Opened embedding_cache_tbl w/ [{row_count}] rows" )
        except Exception as e:
            print( f"⚠️ WARNING: Could not count rows in embedding_cache_tbl: {e}" )

    def _is_table_corrupted( self ) -> bool:
        """
        Check if the table is corrupted by attempting to read actual data.

        Requires:
            - self._embedding_cache_tbl is initialized

        Ensures:
            - Returns True if table is corrupted and needs recreation
            - Returns False if table is healthy

        Raises:
            - Re-raises unexpected exceptions (non-corruption errors)

        Note:
            count_rows() only reads metadata, not data fragments.
            We must attempt an actual scan to detect missing fragment files.
        """
        try:
            # Attempt to read actual data - this will fail if data files are missing
            # limit(1) minimizes overhead while still triggering data access
            # Use to_lance().scanner() to avoid nprobes warning (filter-only query, no vector search)
            self._embedding_cache_tbl.to_lance().scanner( limit=1 ).to_table().to_pylist()
            return False
        except Exception as e:
            error_str = str( e ).lower()
            # Check for LanceDB IO/NotFound errors indicating missing data files
            if "not found" in error_str or "lance" in error_str:
                return True
            # Re-raise unexpected errors
            raise

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
        Create the embedding cache table with proper schema.
        
        Requires:
            - db is a valid LanceDB connection
            
        Ensures:
            - Creates table with normalized_text and embedding fields
            - Sets up FTS index for search
            - Sets self._embedding_cache_tbl to the new table
            
        Raises:
            - lancedb errors propagated
        """
        import pyarrow as pa
        
        if self.debug: 
            du.print_banner( "Creating embedding_cache_tbl schema..." )
        
        schema = pa.schema( [
            pa.field( "normalized_text", pa.string() ),
            pa.field( "embedding", pa.list_( pa.float32(), self._embedding_dim ) )
        ] )

        self._embedding_cache_tbl = db.create_table( "embedding_cache_tbl", schema=schema, mode="overwrite" )
        self._embedding_cache_tbl.create_fts_index( "normalized_text", replace=True )

        if self.debug:
            print( f"✓ Created embedding_cache_tbl with schema: {schema}" )
            print( f"✓ Created FTS index on normalized_text field" )

    def has_cached_embedding( self, normalized_text: str ) -> bool:
        """
        Check if a normalized text has cached embedding.
        
        Requires:
            - normalized_text is a non-empty string
            - Table is initialized
            
        Ensures:
            - Returns True if normalized text exists in table
            - Returns False if normalized text not found
            - Performs exact string match
            
        Raises:
            - None (handles errors gracefully)
        """
        if self.debug and self.verbose: timer = Stopwatch( msg=f"has_cached_embedding( '{normalized_text}' )" )

        try:
            # Escape single quotes by doubling them to prevent SQL parsing errors
            escaped_text = normalized_text.replace( "'", "''" )
            # Use to_lance().scanner() to avoid nprobes warning (filter-only query, no vector search)
            results = self._embedding_cache_tbl.to_lance().scanner(
                filter=f"normalized_text = '{escaped_text}'",
                limit=1,
                columns=[ "normalized_text" ]
            ).to_table().to_pylist()
            if self.debug and self.verbose: timer.print( "Done!", use_millis=True )
            return len( results ) > 0
        except Exception as e:
            if self.debug and self.verbose: timer.print( f"Error: {e}", use_millis=True )
            du.print_stack_trace( e, explanation="has_cached_embedding() failed", caller="EmbeddingCacheTable.has_cached_embedding()" )
            return False
    
    def get_cached_embedding( self, normalized_text: str ) -> Optional[ list[ float ] ]:
        """
        Get the cached embedding for the given normalized text.
        
        Requires:
            - normalized_text is a non-empty string
            - Table is initialized
            
        Ensures:
            - Returns embedding from cache if found
            - Returns None if not in cache
            - Returns list of 1536 floats if found
            
        Raises:
            - None (handles exceptions internally)
        """
        if self.debug and self.verbose: timer = Stopwatch( msg=f"get_cached_embedding( '{normalized_text}' )", silent=True )

        try:
            # Escape single quotes by doubling them to prevent SQL parsing errors
            escaped_text = normalized_text.replace( "'", "''" )
            # Use to_lance().scanner() to avoid nprobes warning (filter-only query, no vector search)
            rows_returned = self._embedding_cache_tbl.to_lance().scanner(
                filter=f"normalized_text = '{escaped_text}'",
                limit=1,
                columns=[ "embedding" ]
            ).to_table().to_pylist()
            if self.debug and self.verbose: timer.print( f"Done! w/ {len( rows_returned )} rows returned", use_millis=True )

            if rows_returned:
                return rows_returned[ 0 ][ "embedding" ]
            else:
                return None

        except Exception as e:
            if self.debug and self.verbose: timer.print( f"Error: {e}", use_millis=True )
            du.print_stack_trace( e, explanation="get_cached_embedding() failed", caller="EmbeddingCacheTable.get_cached_embedding()" )
            return None
        
    def cache_embedding( self, normalized_text: str, embedding: list[ float ] ) -> None:
        """
        Add a normalized text and its embedding to the cache.
        
        Requires:
            - normalized_text is a non-empty string
            - embedding is a list of 1536 floats
            - Table is initialized
            
        Ensures:
            - Adds row to table with normalized text and embedding
            - Handles LanceDB errors gracefully
            
        Raises:
            - None (catches and logs errors)
        """
        new_row = [ { "normalized_text": normalized_text, "embedding": embedding } ]
        
        try:
            self._embedding_cache_tbl.add( new_row )
            if self.debug and self.verbose: print( f"Cached embedding for normalized text: '{du.truncate_string( normalized_text )}'" )
        except Exception as e:
            du.print_stack_trace( e, explanation="cache_embedding() failed", caller="EmbeddingCacheTable.cache_embedding()" )
    
    def init_tbl( self ) -> None:
        """
        Initialize the embedding cache table schema.
        
        Requires:
            - Database connection is established
            
        Ensures:
            - Creates table with proper schema
            - Sets up normalized_text and embedding fields
            - Creates FTS index for search
            - Overwrites existing table if present
            
        Raises:
            - lancedb errors propagated
        """
        import pyarrow as pa
        
        uri = du.get_project_root() + self._config_mgr.get( "path to database wo root" )
        db = lancedb.connect( uri )
        
        du.print_banner( "Initializing embedding_cache_tbl schema..." )
        
        schema = pa.schema( [
            pa.field( "normalized_text", pa.string() ),
            pa.field( "embedding", pa.list_( pa.float32(), self._embedding_dim ) )
        ] )

        self._embedding_cache_tbl = db.create_table( "embedding_cache_tbl", schema=schema, mode="overwrite" )
        self._embedding_cache_tbl.create_fts_index( "normalized_text", replace=True )

        print( f"✓ Created embedding_cache_tbl with schema: {schema}" )
        print( f"✓ Created FTS index on normalized_text field" )
        print( f"✓ Table initialized with {self._embedding_cache_tbl.count_rows()} rows" )


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
        dummy_embedding = [ 0.1 ] * cache_table._embedding_dim  # Create 1536-dimension dummy embedding
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

        # Test 7: Verify corruption detection returns False for healthy table
        print( f"\nTest 7: Testing corruption detection on healthy table..." )
        is_corrupted = cache_table._is_table_corrupted()
        if not is_corrupted:
            print( "✓ Corruption detection correctly reports healthy table" )
        else:
            print( "✗ Corruption detection incorrectly reports corruption on healthy table" )

        # Test 8: Simulate corruption recovery (using temp directory)
        print( f"\nTest 8: Testing corruption recovery with simulated corruption..." )
        import tempfile
        import os
        import shutil

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a fresh LanceDB in temp directory
            temp_db = lancedb.connect( temp_dir )
            import pyarrow as pa
            schema = pa.schema( [
                pa.field( "normalized_text", pa.string() ),
                pa.field( "embedding", pa.list_( pa.float32(), cache_table._embedding_dim ) )
            ] )
            temp_table = temp_db.create_table( "test_tbl", schema=schema )

            # Add some data
            temp_table.add( [ { "normalized_text": "test", "embedding": [ 0.1 ] * cache_table._embedding_dim } ] )
            initial_count = temp_table.count_rows()
            print( f"  Created temp table with {initial_count} row(s)" )

            # Find and delete a data fragment file to simulate corruption
            data_dir = os.path.join( temp_dir, "test_tbl.lance", "data" )
            if os.path.exists( data_dir ):
                lance_files = [ f for f in os.listdir( data_dir ) if f.endswith( ".lance" ) ]
                if lance_files:
                    # Delete the first fragment file
                    corrupt_file = os.path.join( data_dir, lance_files[ 0 ] )
                    os.remove( corrupt_file )
                    print( f"  Deleted fragment file to simulate corruption" )

                    # Reopen the table and test corruption detection
                    temp_db2 = lancedb.connect( temp_dir )
                    corrupted_table = temp_db2.open_table( "test_tbl" )

                    # Manually call the corruption check logic using scanner pattern
                    try:
                        # Use to_lance().scanner() to match production code pattern
                        corrupted_table.to_lance().scanner( limit=1 ).to_table().to_pylist()
                        detected_corruption = False
                    except Exception as e:
                        error_str = str( e ).lower()
                        detected_corruption = "not found" in error_str or "lance" in error_str

                    if detected_corruption:
                        print( "✓ Corruption correctly detected in simulated corrupt table" )
                    else:
                        print( "✗ Failed to detect simulated corruption" )
                else:
                    print( "  ⚠ No fragment files found to corrupt (empty table)" )
            else:
                print( "  ⚠ Data directory not found (LanceDB structure may differ)" )

        print( "\n✓ All basic cache operations completed successfully" )

    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Smoke test failed", caller="EmbeddingCacheTable.quick_smoke_test()" )

    print( "\n✓ EmbeddingCacheTable smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()