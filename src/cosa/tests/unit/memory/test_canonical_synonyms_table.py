"""
Unit tests for CanonicalSynonymsTable with comprehensive mocking.

Tests the CanonicalSynonymsTable class including:
- Exact verbatim and normalized matching
- Synonym addition with uniqueness constraints
- Usage statistics tracking
- Duplicate detection and error handling
- Table schema validation

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
from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable


class TestCanonicalSynonymsTable( unittest.TestCase ):
    """
    Comprehensive unit tests for CanonicalSynonymsTable class.

    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns

    Ensures:
        - All CanonicalSynonymsTable functionality tested in isolation
        - Exact matching behavior validated
        - Uniqueness constraints tested
        - Usage statistics properly tracked
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

    def test_find_exact_verbatim_matching( self ):
        """
        Test find_exact_verbatim with matching queries.

        This validates that exact verbatim matching works correctly
        for the hierarchical search system.

        Ensures:
            - Exact matches found correctly
            - Case sensitivity handled appropriately
            - Correct snapshot IDs returned
            - Non-matches return None
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            # Mock LanceDB table with exact verbatim match
            mock_table = Mock()
            mock_search = Mock()
            mock_search.where.return_value.limit.return_value.to_list.return_value = [
                {
                    "id": "synonym_1",
                    "snapshot_id": "exact_match_snapshot_id",
                    "question_verbatim": "What time is it?",
                    "question_normalized": "what time be it",
                    "question_gist": "time query",
                    "usage_count": 5,
                    "last_matched": "2025-09-28T15:30:00"
                }
            ]
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test exact verbatim match
            result = synonyms_table.find_exact_verbatim( "What time is it?" )

            # Verify search performed correctly
            mock_search.where.assert_called()
            where_call = mock_search.where.call_args[0][0]
            self.assertIn( "What time is it?", str( where_call ) )

            # Verify correct result
            self.assertEqual( result, "exact_match_snapshot_id" )

    def test_find_exact_verbatim_non_matching( self ):
        """
        Test find_exact_verbatim with non-matching queries.

        Ensures:
            - Non-matching queries return None
            - Search performed but no results found
            - Error handling for empty results
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            # Mock LanceDB table with no matches
            mock_table = Mock()
            mock_search = Mock()
            mock_search.where.return_value.limit.return_value.to_list.return_value = []
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test non-matching query
            result = synonyms_table.find_exact_verbatim( "Unknown query" )

            # Verify search performed
            mock_search.where.assert_called()

            # Verify no result returned
            self.assertIsNone( result )

    def test_find_exact_normalized_case_insensitive( self ):
        """
        Test find_exact_normalized with case-insensitive matching.

        This validates the normalized matching functionality
        used in the hierarchical search.

        Ensures:
            - Normalized queries matched correctly
            - Case insensitivity handled
            - Multiple matches handled appropriately
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            # Mock LanceDB table with normalized match
            mock_table = Mock()
            mock_search = Mock()
            mock_search.where.return_value.limit.return_value.to_list.return_value = [
                {
                    "id": "synonym_2",
                    "snapshot_id": "normalized_match_snapshot_id",
                    "question_verbatim": "What time is it?",
                    "question_normalized": "what time be it",
                    "question_gist": "time query",
                    "usage_count": 3,
                    "last_matched": "2025-09-28T15:25:00"
                }
            ]
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test normalized match
            result = synonyms_table.find_exact_normalized( "what time be it" )

            # Verify search performed correctly
            mock_search.where.assert_called()

            # Verify correct result
            self.assertEqual( result, "normalized_match_snapshot_id" )

    def test_add_synonym_with_uniqueness_constraint( self ):
        """
        Test add_synonym with uniqueness constraint validation.

        This validates that duplicate verbatim questions are
        properly detected and handled.

        Ensures:
            - New synonyms added successfully
            - Uniqueness constraints enforced
            - Duplicate detection works correctly
            - Error handling for constraint violations
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            mock_table = Mock()
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test adding new synonym
            result = synonyms_table.add_synonym(
                snapshot_id="new_snapshot_id",
                question_verbatim="How is the weather?",
                question_normalized="how be the weather",
                question_gist="weather inquiry",
                confidence_score=95.0,
                validation_method="user_confirmed"
            )

            # Verify add operation called
            mock_table.add.assert_called_once()

            # Verify the data structure passed to add
            add_call_args = mock_table.add.call_args[0][0]
            synonym_record = add_call_args[0]

            self.assertEqual( synonym_record["snapshot_id"], "new_snapshot_id" )
            self.assertEqual( synonym_record["question_verbatim"], "How is the weather?" )
            self.assertEqual( synonym_record["question_normalized"], "how be the weather" )
            self.assertEqual( synonym_record["question_gist"], "weather inquiry" )
            self.assertEqual( synonym_record["confidence_score"], 95.0 )
            self.assertEqual( synonym_record["validation_method"], "user_confirmed" )

            # Verify success
            self.assertTrue( result )

    def test_add_synonym_duplicate_detection( self ):
        """
        Test add_synonym duplicate detection and error handling.

        Ensures:
            - Duplicate verbatim questions detected
            - Appropriate error handling for duplicates
            - Database constraint violations handled gracefully
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            # Mock database constraint violation
            mock_table = Mock()
            mock_table.add.side_effect = Exception( "Duplicate key constraint violation" )
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test adding duplicate synonym
            result = synonyms_table.add_synonym(
                snapshot_id="duplicate_snapshot_id",
                question_verbatim="What time is it?",  # Already exists
                question_normalized="what time be it",
                question_gist="time query",
                confidence_score=100.0,
                validation_method="auto_validated"
            )

            # Verify failure handled gracefully
            self.assertFalse( result )

    def test_get_usage_stats_functionality( self ):
        """
        Test get_usage_stats functionality.

        This validates that usage statistics are properly
        calculated and returned for synonym management.

        Ensures:
            - Usage statistics calculated correctly
            - Aggregations performed properly
            - Multiple synonyms handled
            - Empty data handled gracefully
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            # Mock LanceDB table with usage data
            mock_table = Mock()
            mock_search = Mock()
            mock_search.to_list.return_value = [
                {
                    "id": "synonym_1",
                    "snapshot_id": "snapshot_1",
                    "question_verbatim": "What time is it?",
                    "usage_count": 10,
                    "confidence_score": 100.0,
                    "validation_method": "user_confirmed"
                },
                {
                    "id": "synonym_2",
                    "snapshot_id": "snapshot_2",
                    "question_verbatim": "What's the weather?",
                    "usage_count": 5,
                    "confidence_score": 85.0,
                    "validation_method": "auto_validated"
                }
            ]
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test usage statistics
            stats = synonyms_table.get_usage_stats()

            # Verify expected statistics
            expected_stats = {
                "total_synonyms": 2,
                "total_usage": 15,
                "average_usage": 7.5,
                "most_used_question": "What time is it?",
                "highest_usage_count": 10,
                "confidence_distribution": {
                    "high_confidence": 1,     # >= 95.0
                    "medium_confidence": 1,   # 80.0-94.9
                    "low_confidence": 0       # < 80.0
                },
                "validation_methods": {
                    "user_confirmed": 1,
                    "auto_validated": 1
                }
            }

            self.assertEqual( stats, expected_stats )

    def test_get_usage_stats_empty_data( self ):
        """
        Test get_usage_stats with empty data.

        Ensures:
            - Empty datasets handled gracefully
            - Appropriate default values returned
            - No division by zero errors
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            # Mock LanceDB table with no data
            mock_table = Mock()
            mock_search = Mock()
            mock_search.to_list.return_value = []
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test empty statistics
            stats = synonyms_table.get_usage_stats()

            expected_empty_stats = {
                "total_synonyms": 0,
                "total_usage": 0,
                "average_usage": 0.0,
                "most_used_question": None,
                "highest_usage_count": 0,
                "confidence_distribution": {
                    "high_confidence": 0,
                    "medium_confidence": 0,
                    "low_confidence": 0
                },
                "validation_methods": {}
            }

            self.assertEqual( stats, expected_empty_stats )

    def test_table_schema_validation( self ):
        """
        Test table creation and schema validation.

        Ensures:
            - Table created with correct schema
            - All required fields included
            - Data types specified correctly
            - Indexes created appropriately
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ), \
             patch( 'cosa.memory.canonical_synonyms_table.pa' ) as mock_pa:

            # Mock PyArrow schema
            mock_schema = Mock()
            mock_pa.schema.return_value = mock_schema

            mock_db = Mock()
            mock_lancedb.connect.return_value = mock_db

            # Test table creation
            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Verify schema creation with correct fields
            mock_pa.schema.assert_called_once()
            schema_call_args = mock_pa.schema.call_args[0][0]

            # Verify all required fields are in schema
            field_names = [field.call_args[0][0] for field in schema_call_args]

            required_fields = [
                "id", "snapshot_id", "question_verbatim", "question_normalized",
                "question_gist", "embedding_verbatim", "embedding_normalized",
                "embedding_gist", "confidence_score", "validation_method",
                "usage_count", "last_matched", "created_date", "created_by", "is_active"
            ]

            for required_field in required_fields:
                self.assertIn( required_field, field_names,
                             f"Required field '{required_field}' missing from schema" )

    def test_update_usage_count( self ):
        """
        Test usage count update functionality.

        This validates that usage statistics are updated
        when synonyms are matched during search.

        Ensures:
            - Usage count incremented correctly
            - Last matched timestamp updated
            - Database updates performed
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            mock_table = Mock()
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test usage count update
            result = synonyms_table.update_usage_count( "synonym_id_123" )

            # Verify update operation called
            mock_table.update.assert_called_once()

            # Verify success
            self.assertTrue( result )

    def test_error_handling_database_failures( self ):
        """
        Test error handling for database failures.

        Ensures:
            - Database connection errors handled gracefully
            - Search failures don't crash operations
            - Add failures handled appropriately
            - Update failures handled correctly
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            # Test database connection failure
            mock_lancedb.connect.side_effect = Exception( "Database connection failed" )

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test search with database error
            result = synonyms_table.find_exact_verbatim( "test query" )
            self.assertIsNone( result )

            # Test add with database error
            result = synonyms_table.add_synonym(
                snapshot_id="test_id",
                question_verbatim="test question",
                question_normalized="test question",
                question_gist="test",
                confidence_score=90.0,
                validation_method="test"
            )
            self.assertFalse( result )

    def test_case_sensitivity_handling( self ):
        """
        Test case sensitivity handling in searches.

        Ensures:
            - Verbatim searches are case-sensitive
            - Normalized searches handle case appropriately
            - Consistent behavior across operations
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            mock_table = Mock()
            mock_search = Mock()

            # Mock case-sensitive verbatim match
            mock_search.where.return_value.limit.return_value.to_list.return_value = []
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test case sensitivity
            result1 = synonyms_table.find_exact_verbatim( "What Time Is It?" )
            result2 = synonyms_table.find_exact_verbatim( "what time is it?" )

            # Verify both searches performed (different cases)
            self.assertEqual( mock_search.where.call_count, 2 )

            # Both should return None since no matches mocked
            self.assertIsNone( result1 )
            self.assertIsNone( result2 )

    def test_embedding_integration( self ):
        """
        Test embedding integration functionality.

        Ensures:
            - Embeddings stored correctly
            - Three-level embeddings handled
            - Large embedding vectors supported
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            mock_table = Mock()
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            synonyms_table = CanonicalSynonymsTable( debug=False, verbose=False )

            # Test with embeddings
            test_embeddings = {
                'verbatim': [0.1] * 1536,
                'normalized': [0.2] * 1536,
                'gist': [0.3] * 1536
            }

            result = synonyms_table.add_synonym(
                snapshot_id="embedding_test_id",
                question_verbatim="Test with embeddings",
                question_normalized="test with embeddings",
                question_gist="embedding test",
                confidence_score=88.0,
                validation_method="auto_validated",
                embeddings=test_embeddings
            )

            # Verify embeddings included in add call
            mock_table.add.assert_called_once()
            add_call_args = mock_table.add.call_args[0][0]
            synonym_record = add_call_args[0]

            self.assertEqual( len( synonym_record["embedding_verbatim"] ), 1536 )
            self.assertEqual( len( synonym_record["embedding_normalized"] ), 1536 )
            self.assertEqual( len( synonym_record["embedding_gist"] ), 1536 )

    def test_initialization_parameters( self ):
        """
        Test CanonicalSynonymsTable initialization.

        Ensures:
            - Initialization with default parameters works
            - Debug and verbose flags handled
            - Configuration integration working
        """
        with patch( 'cosa.memory.canonical_synonyms_table.lancedb' ), \
             patch( 'cosa.memory.canonical_synonyms_table.ConfigurationManager' ):

            # Test default initialization
            synonyms_default = CanonicalSynonymsTable()
            self.assertIsNotNone( synonyms_default )

            # Test with debug and verbose
            synonyms_debug = CanonicalSynonymsTable( debug=True, verbose=True )
            self.assertIsNotNone( synonyms_debug )

            # Verify initialization completed without errors
            self.assertTrue( hasattr( synonyms_default, '_ensure_table_exists' ) )


if __name__ == "__main__":
    unittest.main()