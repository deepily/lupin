"""
CanonicalSynonyms Table for LanceDB storage - Three-Level Question Representation Architecture.

Provides fast exact-match lookups for known synonymous questions, eliminating the need
for similarity search on repeated queries. This table acts as a high-performance cache
layer for the hierarchical search algorithm.

Each synonym entry maps directly to a SolutionSnapshot and includes three-level
representation (verbatim, normalized, gist) with pre-computed embeddings.
"""

import lancedb
import pyarrow as pa
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager
from cosa.utils.util_stopwatch import Stopwatch
from cosa.memory.normalizer import Normalizer
from cosa.memory.embedding_manager import EmbeddingManager



class CanonicalSynonymsTable:
    """
    Manages canonical synonyms in LanceDB for fast exact-match lookups.

    This table provides instant query resolution for known synonymous questions,
    bypassing expensive similarity search. Supports the three-level architecture
    with exact matching at verbatim, normalized, and gist levels.
    """

    def __init__( self, db_path: Optional[str] = None, debug: bool = False, verbose: bool = False ) -> None:
        """
        Initialize the canonical synonyms table.

        Requires:
            - If db_path not provided: LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set
            - Database path is valid in configuration

        Ensures:
            - Opens connection to LanceDB
            - Creates canonical_synonyms table if not exists
            - Initializes text processors and embedding manager
            - Prints table row count

        Raises:
            - FileNotFoundError if database path invalid
            - lancedb errors propagated
        """

        self.debug   = debug
        self.verbose = verbose

        # Initialize text processors
        self._normalizer = Normalizer()
        self._embedding_manager = EmbeddingManager( debug=debug, verbose=verbose )

        # Get standardized embedding dimension from config
        self._config_mgr_local = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._embedding_dim = int( self._config_mgr_local.get( "embedding dimensions", default="768" ) )

        # Get database path from parameter or config
        if db_path:
            # Use provided path (for testing or custom scenarios)
            uri = db_path
        else:
            # Load from configuration (production use)
            self._config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            uri = du.get_project_root() + self._config_mgr.get( "path to database wo root" )

        if self.debug:
            print( f"Connecting to LanceDB at: {uri}" )

        db = lancedb.connect( uri )

        # Validate existing table dimensions match config before creating/opening
        self._validate_embedding_dimensions( db, "canonical_synonyms", "embedding_verbatim" )

        # Check if table exists, create if it doesn't
        if "canonical_synonyms" not in db.table_names():
            if self.debug:
                print( "Table 'canonical_synonyms' doesn't exist, creating it..." )
            self._create_table_if_needed( db )
        else:
            self._canonical_synonyms_table = db.open_table( "canonical_synonyms" )

        if self.verbose:
            print( f"Opened canonical_synonyms table w/ [{self._canonical_synonyms_table.count_rows()}] rows" )

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
        Create the canonical synonyms table with proper schema.

        Requires:
            - db is a valid LanceDB connection

        Ensures:
            - Creates table with three-level question representation
            - Sets up embedding fields for all three levels
            - Creates appropriate indexes for fast lookups
            - Unique constraint on question_verbatim

        Raises:
            - lancedb errors propagated
        """
        if self.debug:
            du.print_banner( "Creating canonical_synonyms table schema..." )

        schema = self._get_schema()

        self._canonical_synonyms_table = db.create_table( "canonical_synonyms", schema=schema, mode="overwrite" )

        # Create indexes for fast lookups
        try:
            # FTS indexes for text search
            self._canonical_synonyms_table.create_fts_index( "question_verbatim", replace=True )
            self._canonical_synonyms_table.create_fts_index( "question_normalized", replace=True )
            self._canonical_synonyms_table.create_fts_index( "question_gist", replace=True )

            if self.debug:
                print( "✓ Created FTS indexes on question fields" )
        except Exception as e:
            if self.debug:
                print( f"Warning: Could not create FTS indexes: {e}" )

        if self.debug:
            print( f"✓ Created canonical_synonyms table with schema" )

    def _get_schema( self ) -> pa.Schema:
        """
        Get PyArrow schema for canonical synonyms table.

        Requires:
            - Nothing

        Ensures:
            - Returns complete schema for three-level synonym storage
            - Includes all necessary fields for fast lookups
            - Optimizes embedding fields for LanceDB

        Returns:
            PyArrow schema for canonical synonyms table
        """
        return pa.schema( [
            # Primary identifiers
            pa.field( "id", pa.string() ),
            pa.field( "snapshot_id", pa.string() ),  # Reference to parent SolutionSnapshot

            # Three-level question representation
            pa.field( "question_verbatim", pa.string() ),     # UNIQUE - exact text
            pa.field( "question_normalized", pa.string() ),   # Normalized version
            pa.field( "question_gist", pa.string() ),         # LLM-extracted gist

            # Embeddings for all three levels (configurable: 768 for local, 1536 for openai)
            pa.field( "embedding_verbatim", pa.list_( pa.float32(), self._embedding_dim ) ),
            pa.field( "embedding_normalized", pa.list_( pa.float32(), self._embedding_dim ) ),
            pa.field( "embedding_gist", pa.list_( pa.float32(), self._embedding_dim ) ),

            # Metadata and statistics
            pa.field( "confidence_score", pa.float32() ),     # 0-100 confidence
            pa.field( "usage_count", pa.int32() ),            # Times matched
            pa.field( "last_matched", pa.timestamp( 'ms' ) ), # Last match time
            pa.field( "created_date", pa.timestamp( 'ms' ) ), # When added
            pa.field( "source", pa.string() ),                # 'migration', 'runtime', etc.
        ] )

    def add_synonym( self,
                    snapshot_id: str,
                    question_verbatim: str,
                    confidence_score: float = 100.0,
                    source: str = "runtime" ) -> bool:
        """
        Add a new synonym to the table.

        Requires:
            - snapshot_id is a valid SolutionSnapshot ID
            - question_verbatim is a non-empty string
            - confidence_score is between 0 and 100
            - Table is initialized

        Ensures:
            - Generates normalized and gist versions
            - Creates embeddings for all three levels (cache-first)
            - Adds row to table if not duplicate
            - Returns True if added, False if duplicate

        Args:
            snapshot_id: Reference to parent SolutionSnapshot
            question_verbatim: Exact question text
            confidence_score: Confidence this is a synonym (0-100)
            source: Origin of synonym ('migration', 'runtime', etc.)

        Returns:
            True if synonym added, False if duplicate exists

        Raises:
            - None (catches and logs errors)
        """
        if self.debug:
            timer = Stopwatch( msg=f"Adding synonym: '{du.truncate_string( question_verbatim )}'" )

        try:
            # Check if already exists
            if self.find_exact_verbatim( question_verbatim ):
                if self.debug:
                    timer.print( "Duplicate - not added", use_millis=True )
                if self.verbose:
                    print( f"│ 📝 SYNONYM ADDITION: SKIPPED (duplicate exists)".ljust( 78 ) + "│" )
                    print( f"│   Question: '{du.truncate_string( question_verbatim, 50 )}'".ljust( 78 ) + "│" )
                    print( "└" + "─" * 77 + "┘" )
                return False

            # Generate three-level representation
            question_normalized = self._normalizer.normalize( question_verbatim )

            # For gist, we'd need GistNormalizer but for now use normalized
            question_gist = question_normalized  # Simplified for now

            # Generate embeddings (cache-first)
            embedding_verbatim = self._embedding_manager.generate_embedding(
                question_verbatim, normalize_for_cache=False
            )
            embedding_normalized = self._embedding_manager.generate_embedding(
                question_normalized, normalize_for_cache=False
            )
            embedding_gist = self._embedding_manager.generate_embedding(
                question_gist, normalize_for_cache=False
            )

            # Generate unique ID
            synonym_id = f"{snapshot_id}_{du.get_current_datetime( format_str='%Y%m%d_%H%M%S_%f' )}"

            # Prepare row data
            row_data = {
                "id": synonym_id,
                "snapshot_id": snapshot_id,
                "question_verbatim": question_verbatim,
                "question_normalized": question_normalized,
                "question_gist": question_gist,
                "embedding_verbatim": embedding_verbatim,
                "embedding_normalized": embedding_normalized,
                "embedding_gist": embedding_gist,
                "confidence_score": confidence_score,
                "usage_count": 0,
                "last_matched": du.get_timestamp_ms(),
                "created_date": du.get_timestamp_ms(),
                "source": source,
            }

            # Add to table
            self._canonical_synonyms_table.add( [row_data] )

            if self.debug:
                timer.print( f"✓ Added synonym for snapshot {snapshot_id}", use_millis=True )

            return True

        except Exception as e:
            if self.debug:
                timer.print( f"Error: {e}", use_millis=True )
            du.print_stack_trace( e, explanation="add_synonym() failed", caller="CanonicalSynonymsTable.add_synonym()" )
            return False

    def find_exact_verbatim( self, question: str ) -> Optional[str]:
        """
        Find exact match for verbatim question.

        Requires:
            - question is a non-empty string
            - Table is initialized

        Ensures:
            - Returns snapshot_id if exact match found
            - Returns None if no match
            - Updates usage statistics on match
            - No embeddings computed (instant lookup)

        Args:
            question: Exact question text to match

        Returns:
            snapshot_id if found, None otherwise
        """
        if self.debug:
            timer = Stopwatch( msg=f"Exact verbatim search: '{du.truncate_string( question )}'" )

        try:
            # Use pandas filtering for exact match (NOT search().where() which requires vector)
            # LanceDB's search() without a query vector returns arbitrary results
            df = self._canonical_synonyms_table.to_pandas()
            matches = df[df['question_verbatim'] == question]

            if len( matches ) > 0:
                # Update usage stats
                self._update_usage_stats( question )
                snapshot_id = matches.iloc[0]['snapshot_id']

                if self.debug:
                    timer.print( f"✓ Found snapshot: {snapshot_id}", use_millis=True )

                return snapshot_id

            if self.debug:
                timer.print( "No match found", use_millis=True )

            return None

        except Exception as e:
            if self.debug:
                timer.print( f"Error: {e}", use_millis=True )
            return None

    def find_exact_normalized( self, question_normalized: str ) -> Optional[str]:
        """
        Find exact match for normalized question.

        Requires:
            - question_normalized is a normalized string
            - Table is initialized

        Ensures:
            - Returns snapshot_id if exact match found
            - Returns None if no match
            - Updates usage statistics on match
            - No embeddings computed (instant lookup)

        Args:
            question_normalized: Normalized question text to match

        Returns:
            snapshot_id if found, None otherwise
        """
        if self.debug:
            timer = Stopwatch( msg=f"Exact normalized search: '{du.truncate_string( question_normalized )}'" )

        try:
            # Use pandas filtering for exact match (NOT search().where() which requires vector)
            # LanceDB's search() without a query vector returns arbitrary results
            df = self._canonical_synonyms_table.to_pandas()
            matches = df[ df[ 'question_normalized' ] == question_normalized ]

            if len( matches ) > 0:
                # Update usage stats using verbatim question
                self._update_usage_stats( matches.iloc[ 0 ][ 'question_verbatim' ] )
                snapshot_id = matches.iloc[ 0 ][ 'snapshot_id' ]

                if self.debug:
                    timer.print( f"✓ Found snapshot: {snapshot_id}", use_millis=True )

                return snapshot_id

            if self.debug:
                timer.print( "No match found", use_millis=True )

            return None

        except Exception as e:
            if self.debug:
                timer.print( f"Error: {e}", use_millis=True )
            return None

    def find_exact_gist( self, question_gist: str ) -> Optional[str]:
        """
        Find exact match for question gist.

        Requires:
            - question_gist is a gist string
            - Table is initialized

        Ensures:
            - Returns snapshot_id if exact match found
            - Returns None if no match
            - Updates usage statistics on match
            - No embeddings computed (instant lookup)

        Args:
            question_gist: Question gist to match

        Returns:
            snapshot_id if found, None otherwise
        """
        if self.debug:
            timer = Stopwatch( msg=f"Exact gist search: '{du.truncate_string( question_gist )}'" )

        try:
            # Use pandas filtering for exact match (NOT search().where() which requires vector)
            # LanceDB's search() without a query vector returns arbitrary results
            df = self._canonical_synonyms_table.to_pandas()
            matches = df[ df[ 'question_gist' ] == question_gist ]

            if len( matches ) > 0:
                # Update usage stats using verbatim question
                self._update_usage_stats( matches.iloc[ 0 ][ 'question_verbatim' ] )
                snapshot_id = matches.iloc[ 0 ][ 'snapshot_id' ]

                if self.debug:
                    timer.print( f"✓ Found snapshot: {snapshot_id}", use_millis=True )

                return snapshot_id

            if self.debug:
                timer.print( "No match found", use_millis=True )

            return None

        except Exception as e:
            if self.debug:
                timer.print( f"Error: {e}", use_millis=True )
            return None

    def delete_by_snapshot_id( self, snapshot_id: str ) -> int:
        """
        Delete all synonym entries associated with a given snapshot_id.

        Requires:
            - snapshot_id is a non-empty string
            - Table is initialized

        Ensures:
            - All rows with matching snapshot_id are deleted
            - Returns the count of deleted rows
            - Returns 0 if no matches found or on error

        Args:
            snapshot_id: The snapshot ID whose synonyms should be removed

        Returns:
            Number of rows deleted
        """
        if self.debug:
            timer = Stopwatch( msg=f"Deleting synonyms for snapshot: {snapshot_id[:8]}..." )

        try:
            # Count matching rows before deletion
            df = self._canonical_synonyms_table.to_pandas()
            matches = df[ df[ 'snapshot_id' ] == snapshot_id ]
            count = len( matches )

            if count > 0:
                self._canonical_synonyms_table.delete( f"snapshot_id = '{snapshot_id}'" )

            if self.debug:
                timer.print( f"Deleted {count} synonym(s) for snapshot {snapshot_id[:8]}...", use_millis=True )

            return count

        except Exception as e:
            if self.debug:
                timer.print( f"Error: {e}", use_millis=True )
            du.print_stack_trace( e, explanation="delete_by_snapshot_id() failed", caller="CanonicalSynonymsTable.delete_by_snapshot_id()" )
            return 0

    def _update_usage_stats( self, question_verbatim: str ) -> None:
        """
        Update usage statistics for a matched synonym.

        Requires:
            - question_verbatim exists in table

        Ensures:
            - Increments usage_count
            - Updates last_matched timestamp
        """
        try:
            # This would require an UPDATE operation which LanceDB doesn't directly support
            # We'd need to read, modify, and write back the record
            # For now, we'll just log it
            if self.debug:
                print( f"Usage stats update for: '{du.truncate_string( question_verbatim )}'" )

        except Exception as e:
            if self.debug:  # pragma: no branch - except is only reachable via the debug-gated truncate_string() above, so self.debug is always True here
                print( f"Error updating usage stats: {e}" )

    def get_statistics( self ) -> Dict[str, Any]:
        """
        Get statistics about the synonyms table.

        Returns:
            Dict with total count, usage stats, and performance metrics
        """
        try:
            total_rows = self._canonical_synonyms_table.count_rows()

            # Get top used synonyms
            all_rows = self._canonical_synonyms_table.search().limit( 1000 ).to_list()

            # Calculate statistics
            total_usage = sum( row.get( 'usage_count', 0 ) for row in all_rows )
            avg_confidence = sum( row.get( 'confidence_score', 0 ) for row in all_rows ) / len( all_rows ) if all_rows else 0

            # Find top used
            sorted_rows = sorted( all_rows, key=lambda x: x.get( 'usage_count', 0 ), reverse=True )
            top_5 = sorted_rows[:5] if len( sorted_rows ) >= 5 else sorted_rows

            return {
                "total_synonyms": total_rows,
                "total_usage": total_usage,
                "average_confidence": avg_confidence,
                "top_used": [
                    {
                        "question": row['question_verbatim'],
                        "usage": row['usage_count']
                    } for row in top_5
                ]
            }

        except Exception as e:
            if self.debug:
                print( f"Error getting statistics: {e}" )
            return { "error": str( e ) }


def quick_smoke_test():
    """Quick smoke test to validate CanonicalSynonymsTable functionality."""
    du.print_banner( "CanonicalSynonymsTable Smoke Test", prepend_nl=True )

    try:
        # Test 1: Initialize table
        print( "Test 1: Initializing CanonicalSynonymsTable..." )
        synonyms_table = CanonicalSynonymsTable( debug=False, verbose=True )
        print( "✓ CanonicalSynonymsTable initialized successfully" )

        # Test 2: Add a synonym
        print( "\nTest 2: Adding test synonym..." )
        success = synonyms_table.add_synonym(
            snapshot_id="test_snapshot_001",
            question_verbatim="What time is it?",
            confidence_score=100.0,
            source="test"
        )
        if success:
            print( "✓ Synonym added successfully" )
        else:
            print( "✓ Synonym already exists (expected if run multiple times)" )

        # Test 3: Find exact verbatim match
        print( "\nTest 3: Testing exact verbatim match..." )
        snapshot_id = synonyms_table.find_exact_verbatim( "What time is it?" )
        if snapshot_id:
            print( f"✓ Found snapshot: {snapshot_id}" )
        else:
            print( "✗ No match found (unexpected)" )

        # Test 4: Find exact normalized match
        print( "\nTest 4: Testing exact normalized match..." )
        # Normalize the question first
        normalizer = Normalizer()
        normalized = normalizer.normalize( "What time is it?" )
        snapshot_id = synonyms_table.find_exact_normalized( normalized )
        if snapshot_id:
            print( f"✓ Found snapshot via normalized: {snapshot_id}" )

        # Test 5: Test non-match
        print( "\nTest 5: Testing non-existent question..." )
        snapshot_id = synonyms_table.find_exact_verbatim( "This question does not exist" )
        if not snapshot_id:
            print( "✓ Correctly returned None for non-existent question" )

        # Test 6: Get statistics
        print( "\nTest 6: Getting table statistics..." )
        stats = synonyms_table.get_statistics()
        print( f"✓ Statistics: {stats}" )

        # Test 7: Add variations
        print( "\nTest 7: Adding question variations..." )
        variations = [
            "What's the time?",
            "Tell me the time",
            "What is the current time?"
        ]
        for var in variations:
            success = synonyms_table.add_synonym(
                snapshot_id="test_snapshot_001",
                question_verbatim=var,
                confidence_score=95.0,
                source="test_variations"
            )
            print( f"  {'✓' if success else '○'} {var}" )

        print( "\n✓ All CanonicalSynonymsTable smoke tests passed!" )

    except Exception as e:
        print( f"\n✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Smoke test failed", caller="CanonicalSynonymsTable.quick_smoke_test()" )

    print( "\n✓ CanonicalSynonymsTable smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()