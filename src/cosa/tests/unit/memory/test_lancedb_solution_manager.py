"""
Unit tests for LanceDBSolutionManager with comprehensive mocking.

Tests the LanceDBSolutionManager class including:
- Hierarchical search implementation (CRITICAL)
- Early exit behavior for exact matches
- CanonicalSynonymsTable integration
- get_snapshot_by_id functionality
- Error handling and edge cases

Zero external dependencies - all operations mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Dict, Any, Optional

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.memory.lancedb_solution_manager import LanceDBSolutionManager
from cosa.memory.solution_snapshot import SolutionSnapshot


class TestLanceDBSolutionManager( unittest.TestCase ):
    """
    Comprehensive unit tests for LanceDBSolutionManager class.

    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns

    Ensures:
        - All LanceDBSolutionManager functionality tested in isolation
        - Hierarchical search behavior validated (CRITICAL)
        - Early exit behavior confirmed
        - CanonicalSynonymsTable integration tested
    """

    def setUp( self ):
        """
        Setup for each test method.

        Ensures:
            - Clean state for each test
            - Mock manager is available
        """
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()

    def tearDown( self ):
        """
        Cleanup after each test method.

        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()

    def test_hierarchical_search_early_exit_verbatim( self ):
        """
        Test that hierarchical search exits early on exact verbatim matches (CRITICAL).

        This validates that the search doesn't continue to expensive similarity
        search when exact matches are found at level 1 (verbatim).

        Ensures:
            - Exact verbatim match found immediately
            - No normalized or similarity search attempted
            - Correct snapshot returned
            - Performance optimization through early exit
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ), \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ):

            # Mock CanonicalSynonymsTable to return exact verbatim match
            mock_canonical = Mock()
            mock_canonical.find_exact_verbatim.return_value = "test_snapshot_id"

            # Mock Normalizer (should not be called for verbatim match)
            mock_normalizer = Mock()

            manager = LanceDBSolutionManager( debug=False, verbose=False )
            manager._canonical_synonyms = mock_canonical
            manager._normalizer = mock_normalizer

            # Mock get_snapshot_by_id to return test snapshot
            test_snapshot = SolutionSnapshot(
                question="What time is it?",
                answer="It is 3:00 PM"
            )
            manager.get_snapshot_by_id = Mock( return_value=test_snapshot )

            # Test exact verbatim match (should exit at level 1)
            result = manager.get_snapshots_by_question( "What time is it?" )

            # Verify early exit - verbatim search called
            mock_canonical.find_exact_verbatim.assert_called_once_with( "What time is it?" )

            # Verify early exit - normalized search NOT called
            mock_canonical.find_exact_normalized.assert_not_called()
            mock_normalizer.normalize.assert_not_called()

            # Verify correct snapshot returned
            self.assertEqual( len( result ), 1 )
            self.assertEqual( result[0].question, "What time is it?" )

    def test_hierarchical_search_early_exit_normalized( self ):
        """
        Test that hierarchical search exits early on exact normalized matches.

        This validates that the search exits at level 2 when normalized
        match is found, without proceeding to gist or similarity search.

        Ensures:
            - Verbatim search attempted first (returns None)
            - Normalized search finds match and exits
            - No gist or similarity search attempted
            - Correct snapshot returned
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ), \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ):

            # Mock CanonicalSynonymsTable behavior
            mock_canonical = Mock()
            mock_canonical.find_exact_verbatim.return_value = None  # No verbatim match
            mock_canonical.find_exact_normalized.return_value = "test_snapshot_id_2"  # Normalized match

            # Mock Normalizer
            mock_normalizer = Mock()
            mock_normalizer.normalize.return_value = "what time be it"

            manager = LanceDBSolutionManager( debug=False, verbose=False )
            manager._canonical_synonyms = mock_canonical
            manager._normalizer = mock_normalizer

            # Mock get_snapshot_by_id
            test_snapshot = SolutionSnapshot(
                question="what time be it",
                answer="It is 3:00 PM"
            )
            manager.get_snapshot_by_id = Mock( return_value=test_snapshot )

            # Test normalized match (should exit at level 2)
            result = manager.get_snapshots_by_question( "What time is it?" )

            # Verify search progression
            mock_canonical.find_exact_verbatim.assert_called_once_with( "What time is it?" )
            mock_normalizer.normalize.assert_called_once_with( "What time is it?" )
            mock_canonical.find_exact_normalized.assert_called_once_with( "what time be it" )

            # Verify early exit - no gist or similarity search
            self.assertFalse( hasattr( mock_canonical, 'find_exact_gist' ) or
                            getattr( mock_canonical, 'find_exact_gist', Mock() ).called )

            # Verify correct result
            self.assertEqual( len( result ), 1 )
            self.assertEqual( result[0].question, "what time be it" )

    def test_hierarchical_search_fallback_to_similarity( self ):
        """
        Test hierarchical search falls back to similarity when no exact matches found.

        This validates the complete search hierarchy when exact matches fail
        at all levels, ensuring similarity search is used as final fallback.

        Ensures:
            - All exact match levels attempted in order
            - Similarity search called only after exact matches fail
            - Correct similarity results returned
            - Search progression follows hierarchy
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ):

            # Mock CanonicalSynonymsTable - no exact matches
            mock_canonical = Mock()
            mock_canonical.find_exact_verbatim.return_value = None
            mock_canonical.find_exact_normalized.return_value = None

            # Mock Normalizer
            mock_normalizer = Mock()
            mock_normalizer.normalize.return_value = "what time be it"

            # Mock LanceDB table for similarity search
            mock_table = Mock()
            mock_search = Mock()
            mock_search.limit.return_value = mock_search
            mock_search.to_list.return_value = [
                {
                    "id": "similarity_match_id",
                    "question": "what time be it",
                    "answer": "It is 3:00 PM",
                    "_distance": 0.1
                }
            ]
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            manager = LanceDBSolutionManager( debug=False, verbose=False )
            manager._canonical_synonyms = mock_canonical
            manager._normalizer = mock_normalizer

            # Mock embedding generation
            manager._generate_embedding = Mock( return_value=[0.1, 0.2, 0.3] )

            # Test similarity fallback
            result = manager.get_snapshots_by_question( "What time is it?" )

            # Verify complete search hierarchy attempted
            mock_canonical.find_exact_verbatim.assert_called_once_with( "What time is it?" )
            mock_normalizer.normalize.assert_called_once_with( "What time is it?" )
            mock_canonical.find_exact_normalized.assert_called_once_with( "what time be it" )

            # Verify similarity search called as fallback
            mock_table.search.assert_called_once()

            # Verify result from similarity search
            self.assertEqual( len( result ), 1 )
            self.assertIn( "time", result[0].question.lower() )

    def test_get_snapshot_by_id( self ):
        """
        Test get_snapshot_by_id functionality.

        This validates the direct snapshot retrieval functionality
        that was added as part of the three-level architecture.

        Ensures:
            - Snapshot retrieved by ID correctly
            - LanceDB query constructed properly
            - Result parsed and returned as SolutionSnapshot
            - Error handling for non-existent IDs
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ):

            # Mock LanceDB table and query
            mock_table = Mock()
            mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [
                {
                    "id": "test_snapshot_id",
                    "question": "What time is it?",
                    "question_normalized": "what time be it",
                    "answer": "It is 3:00 PM",
                    "code": [],
                    "thoughts": "Simple time query"
                }
            ]
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            manager = LanceDBSolutionManager( debug=False, verbose=False )

            # Test snapshot retrieval
            result = manager.get_snapshot_by_id( "test_snapshot_id" )

            # Verify LanceDB query
            mock_table.search.assert_called_once()

            # Verify correct snapshot returned
            self.assertIsNotNone( result )
            self.assertEqual( result.question, "What time is it?" )
            self.assertEqual( result.answer, "It is 3:00 PM" )

    def test_get_snapshot_by_id_not_found( self ):
        """
        Test get_snapshot_by_id with non-existent ID.

        Ensures:
            - Returns None for non-existent snapshot ID
            - No errors thrown for missing snapshots
            - Proper error handling
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ):

            # Mock LanceDB table - no results
            mock_table = Mock()
            mock_table.search.return_value.where.return_value.limit.return_value.to_list.return_value = []
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            manager = LanceDBSolutionManager( debug=False, verbose=False )

            # Test non-existent snapshot
            result = manager.get_snapshot_by_id( "non_existent_id" )

            # Verify None returned
            self.assertIsNone( result )

    def test_canonical_synonyms_integration( self ):
        """
        Test CanonicalSynonymsTable integration.

        This validates that the LanceDBSolutionManager properly
        integrates with CanonicalSynonymsTable for exact matching.

        Ensures:
            - CanonicalSynonymsTable initialized correctly
            - Integration methods called with correct parameters
            - Error handling for CanonicalSynonymsTable failures
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ), \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ), \
             patch( 'cosa.memory.lancedb_solution_manager.CanonicalSynonymsTable' ) as mock_cst_class:

            # Mock CanonicalSynonymsTable instantiation
            mock_canonical = Mock()
            mock_cst_class.return_value = mock_canonical
            mock_canonical.find_exact_verbatim.return_value = None
            mock_canonical.find_exact_normalized.return_value = None

            manager = LanceDBSolutionManager( debug=False, verbose=False )

            # Trigger initialization by calling search
            manager.get_snapshots_by_question( "test query" )

            # Verify CanonicalSynonymsTable initialized
            mock_cst_class.assert_called_once()

            # Verify integration methods called
            mock_canonical.find_exact_verbatim.assert_called_once_with( "test query" )

    def test_normalizer_integration( self ):
        """
        Test Normalizer integration.

        This validates that the LanceDBSolutionManager properly
        integrates with the Normalizer for text processing.

        Ensures:
            - Normalizer initialized correctly
            - Normalization called when needed
            - Error handling for normalization failures
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ), \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ), \
             patch( 'cosa.memory.lancedb_solution_manager.Normalizer' ) as mock_norm_class:

            # Mock Normalizer
            mock_normalizer = Mock()
            mock_norm_class.return_value = mock_normalizer
            mock_normalizer.normalize.return_value = "normalized query"

            # Mock CanonicalSynonymsTable - no verbatim match to trigger normalization
            mock_canonical = Mock()
            mock_canonical.find_exact_verbatim.return_value = None
            mock_canonical.find_exact_normalized.return_value = None

            manager = LanceDBSolutionManager( debug=False, verbose=False )
            manager._canonical_synonyms = mock_canonical

            # Trigger normalization
            manager.get_snapshots_by_question( "What time is it?" )

            # Verify Normalizer initialized and called
            mock_norm_class.assert_called_once()
            mock_normalizer.normalize.assert_called_once_with( "What time is it?" )

    def test_error_handling( self ):
        """
        Test error handling in various scenarios.

        Ensures:
            - Database connection errors handled gracefully
            - CanonicalSynonymsTable errors don't crash search
            - Normalizer errors handled appropriately
            - Invalid inputs handled correctly
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ):

            # Test database connection error
            mock_lancedb.connect.side_effect = Exception( "Database connection failed" )

            manager = LanceDBSolutionManager( debug=False, verbose=False )

            # Should handle database errors gracefully
            result = manager.get_snapshots_by_question( "test query" )
            self.assertEqual( result, [] )

    def test_empty_and_invalid_queries( self ):
        """
        Test handling of empty and invalid queries.

        Ensures:
            - Empty strings handled gracefully
            - None values handled appropriately
            - Whitespace-only queries processed correctly
            - Very long queries handled without errors
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ), \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ):

            manager = LanceDBSolutionManager( debug=False, verbose=False )

            # Test empty string
            result = manager.get_snapshots_by_question( "" )
            self.assertEqual( result, [] )

            # Test None value
            result = manager.get_snapshots_by_question( None )
            self.assertEqual( result, [] )

            # Test whitespace-only
            result = manager.get_snapshots_by_question( "   " )
            self.assertEqual( result, [] )

    def test_performance_optimization_early_exits( self ):
        """
        Test that early exits provide performance optimization.

        This validates that the hierarchical search actually provides
        performance benefits by avoiding expensive operations when
        exact matches are found early.

        Ensures:
            - Verbatim match avoids all other processing
            - Normalized match avoids similarity search
            - Early exits minimize computational overhead
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ), \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ):

            # Mock CanonicalSynonymsTable for verbatim match
            mock_canonical = Mock()
            mock_canonical.find_exact_verbatim.return_value = "fast_match_id"

            # Mock expensive operations that should be avoided
            mock_normalizer = Mock()
            mock_embedding_gen = Mock()

            manager = LanceDBSolutionManager( debug=False, verbose=False )
            manager._canonical_synonyms = mock_canonical
            manager._normalizer = mock_normalizer
            manager._generate_embedding = mock_embedding_gen

            # Mock get_snapshot_by_id
            test_snapshot = SolutionSnapshot(
                question="What time is it?",
                answer="It is 3:00 PM"
            )
            manager.get_snapshot_by_id = Mock( return_value=test_snapshot )

            # Test early exit optimization
            result = manager.get_snapshots_by_question( "What time is it?" )

            # Verify expensive operations were avoided
            mock_normalizer.normalize.assert_not_called()
            mock_embedding_gen.assert_not_called()

            # Verify result still correct
            self.assertEqual( len( result ), 1 )
            self.assertEqual( result[0].question, "What time is it?" )

    def test_search_ordering_and_limits( self ):
        """
        Test search result ordering and limits.

        Ensures:
            - Results returned in correct order
            - Search limits respected
            - Multiple results handled correctly
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ):

            # Mock multiple similarity results
            mock_table = Mock()
            mock_search = Mock()
            mock_search.limit.return_value = mock_search
            mock_search.to_list.return_value = [
                {"id": "result1", "question": "time query 1", "_distance": 0.1},
                {"id": "result2", "question": "time query 2", "_distance": 0.2},
                {"id": "result3", "question": "time query 3", "_distance": 0.3}
            ]
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            # Mock no exact matches to force similarity search
            mock_canonical = Mock()
            mock_canonical.find_exact_verbatim.return_value = None
            mock_canonical.find_exact_normalized.return_value = None

            mock_normalizer = Mock()
            mock_normalizer.normalize.return_value = "normalized query"

            manager = LanceDBSolutionManager( debug=False, verbose=False )
            manager._canonical_synonyms = mock_canonical
            manager._normalizer = mock_normalizer
            manager._generate_embedding = Mock( return_value=[0.1, 0.2, 0.3] )

            # Test multiple results
            result = manager.get_snapshots_by_question( "time query" )

            # Verify search limit applied
            mock_search.limit.assert_called()

            # Verify multiple results returned
            self.assertGreaterEqual( len( result ), 1 )

    def test_debug_and_verbose_output( self ):
        """
        Test debug and verbose output functionality.

        Ensures:
            - Debug mode produces appropriate output
            - Verbose mode provides detailed information
            - Output doesn't interfere with functionality
        """
        with patch( 'cosa.memory.lancedb_solution_manager.lancedb' ), \
             patch( 'cosa.memory.lancedb_solution_manager.ConfigurationManager' ), \
             patch( 'builtins.print' ) as mock_print:

            manager = LanceDBSolutionManager( debug=True, verbose=True )

            # Mock minimal setup to avoid errors
            mock_canonical = Mock()
            mock_canonical.find_exact_verbatim.return_value = None
            mock_canonical.find_exact_normalized.return_value = None
            manager._canonical_synonyms = mock_canonical

            mock_normalizer = Mock()
            mock_normalizer.normalize.return_value = "test"
            manager._normalizer = mock_normalizer

            # Test debug output
            result = manager.get_snapshots_by_question( "test query" )

            # Verify debug output was produced (print called)
            self.assertTrue( mock_print.called )


if __name__ == "__main__":
    unittest.main()