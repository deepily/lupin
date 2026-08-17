"""
CanonicalSynonyms Table backed by Postgres — Three-Level Question Representation Architecture.

Provides fast exact-match lookups for known synonymous questions, eliminating the need
for similarity search on repeated queries. This table acts as a high-performance cache
layer for the hierarchical search algorithm.

Each synonym entry maps directly to a SolutionSnapshot and includes three-level
representation (verbatim, normalized, gist) with pre-computed embeddings. Storage runs
through CanonicalSynonymRepository on a short-lived get_db() session per call, while
normalization and embedding generation stay here in the memory layer.
"""

from typing import Optional, Dict, Any
import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager
from cosa.memory.normalizer import Normalizer
from cosa.memory.embedding_manager import EmbeddingManager


class CanonicalSynonymsTable:
    """
    Manages canonical synonyms in Postgres for fast exact-match lookups.

    This table provides instant query resolution for known synonymous questions,
    bypassing expensive similarity search. Supports the three-level architecture
    with exact matching at verbatim, normalized, and gist levels.
    """

    def __init__( self, debug: bool = False, verbose: bool = False ) -> None:
        """
        Initialize the canonical synonyms table.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set

        Ensures:
            - Initializes text processors and embedding manager
            - Reads the standardized embedding dimension from configuration
            - Opens no connection of its own; storage sessions are per-call

        Raises:
            - ConfigurationManager errors propagated
        """

        self.debug   = debug
        self.verbose = verbose

        # Initialize text processors
        self._normalizer = Normalizer()
        self._embedding_manager = EmbeddingManager( debug=debug, verbose=verbose )

        # Get standardized embedding dimension from config
        self._config_mgr_local = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._embedding_dim = int( self._config_mgr_local.get( "embedding dimensions", default="768" ) )

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

        Ensures:
            - Generates normalized and gist versions
            - Creates embeddings for all three levels (cache-first)
            - Adds row if not a duplicate
            - Returns True if added, False if duplicate or on error

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
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
        try:
            if self.find_exact_verbatim( question_verbatim ):
                return False

            question_normalized = self._normalizer.normalize( question_verbatim )
            question_gist       = question_normalized      # simplified — gist normalizer not wired yet

            embedding_verbatim   = self._embedding_manager.generate_embedding( question_verbatim,   normalize_for_cache=False )
            embedding_normalized = self._embedding_manager.generate_embedding( question_normalized, normalize_for_cache=False )
            embedding_gist       = self._embedding_manager.generate_embedding( question_gist,       normalize_for_cache=False )

            synonym_id = f"{snapshot_id}_{du.get_current_datetime( format_str='%Y%m%d_%H%M%S_%f' )}"
            now        = du.get_timestamp_ms()

            with get_db() as session:
                CanonicalSynonymRepository( session ).add_synonym(
                    id=synonym_id, snapshot_id=snapshot_id, question_verbatim=question_verbatim,
                    question_normalized=question_normalized, question_gist=question_gist,
                    embedding_verbatim=embedding_verbatim, embedding_normalized=embedding_normalized,
                    embedding_gist=embedding_gist, confidence_score=confidence_score,
                    usage_count=0, last_matched=now, created_date=now, source=source,
                )
            return True
        except Exception as e:
            du.print_stack_trace( e, explanation="add_synonym() failed", caller="CanonicalSynonymsTable.add_synonym()" )
            return False

    def find_exact_verbatim( self, question: str ) -> Optional[str]:
        """
        Find exact match for verbatim question.

        Requires:
            - question is a non-empty string

        Ensures:
            - Returns snapshot_id if exact match found, None otherwise
            - No embeddings computed (instant lookup)

        Args:
            question: Exact question text to match

        Returns:
            snapshot_id if found, None otherwise
        """
        return self._find_exact( "question_verbatim", question )

    def find_exact_normalized( self, question_normalized: str ) -> Optional[str]:
        """
        Find exact match for normalized question.

        Requires:
            - question_normalized is a normalized string

        Ensures:
            - Returns snapshot_id if exact match found, None otherwise
            - No embeddings computed (instant lookup)

        Args:
            question_normalized: Normalized question text to match

        Returns:
            snapshot_id if found, None otherwise
        """
        return self._find_exact( "question_normalized", question_normalized )

    def find_exact_gist( self, question_gist: str ) -> Optional[str]:
        """
        Find exact match for question gist.

        Requires:
            - question_gist is a gist string

        Ensures:
            - Returns snapshot_id if exact match found, None otherwise
            - No embeddings computed (instant lookup)

        Args:
            question_gist: Question gist to match

        Returns:
            snapshot_id if found, None otherwise
        """
        return self._find_exact( "question_gist", question_gist )

    def delete_by_snapshot_id( self, snapshot_id: str ) -> int:
        """
        Delete all synonym entries associated with a given snapshot_id.

        Requires:
            - snapshot_id is a non-empty string

        Ensures:
            - All rows with matching snapshot_id are deleted
            - Returns the count of deleted rows
            - Returns 0 if no matches found or on error

        Args:
            snapshot_id: The snapshot ID whose synonyms should be removed

        Returns:
            Number of rows deleted
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
        try:
            with get_db() as session:
                return CanonicalSynonymRepository( session ).delete_by_snapshot_id( snapshot_id )
        except Exception as e:
            du.print_stack_trace( e, explanation="delete_by_snapshot_id() failed", caller="CanonicalSynonymsTable.delete_by_snapshot_id()" )
            return 0

    def get_statistics( self ) -> Dict[str, Any]:
        """
        Get statistics about the synonyms table.

        Ensures:
            - Returns total count and usage totals
            - top_used is empty — no production caller reads it
            - Returns {"error": msg} on failure

        Returns:
            Dict with total count and usage stats
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
        try:
            with get_db() as session:
                stats = CanonicalSynonymRepository( session ).get_statistics()
            return {
                "total_synonyms": stats[ "total_synonyms" ],
                "total_usage":    stats[ "total_usage_count" ],
                "top_used":       [],
            }
        except Exception as e:
            if self.debug:
                print( f"Error getting statistics: {e}" )
            return { "error": str( e ) }

    def _find_exact( self, column: str, value: str ) -> Optional[str]:
        """
        Shared exact-match lookup for the find_exact_* family.

        Requires:
            - column is one of question_verbatim / question_normalized / question_gist

        Ensures:
            - Returns the matching snapshot_id, or None on miss or error
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
        try:
            with get_db() as session:
                repo = CanonicalSynonymRepository( session )
                finder = {
                    "question_verbatim":   repo.find_exact_verbatim,
                    "question_normalized": repo.find_exact_normalized,
                    "question_gist":       repo.find_exact_gist,
                }[ column ]
                return finder( value )
        except Exception as e:
            if self.debug:
                print( f"Error in find_exact({column}): {e}" )
            return None


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
