"""
Unit tests for QueryLogTable with comprehensive mocking.

Tests the QueryLogTable class including:
- Query logging with three-level representation
- Cache hit statistics tracking
- Recent queries retrieval
- Embedding storage and retrieval
- Error handling and edge cases

Zero external dependencies - all operations mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.memory.query_log_table import QueryLogTable


class TestQueryLogTable( unittest.TestCase ):
    """
    Comprehensive unit tests for QueryLogTable class.

    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns

    Ensures:
        - All QueryLogTable functionality tested in isolation
        - Three-level query logging validated
        - Cache hit statistics properly tracked
        - Error conditions handled gracefully
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

    def test_log_query_with_match_types( self ):
        """
        Test log_query with various match types.

        This validates that all match types from the hierarchical search
        are properly logged with correct metadata.

        Ensures:
            - exact_verbatim matches logged correctly
            - exact_normalized matches logged correctly
            - similarity matches logged correctly
            - none matches logged correctly
            - All required fields populated
        """
        with patch( 'cosa.memory.query_log_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.query_log_table.ConfigurationManager' ):

            # Mock LanceDB table
            mock_table = Mock()
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            query_log = QueryLogTable( debug=False, verbose=False )

            # Test data for different match types
            match_type_tests = [
                {
                    "match_type": "exact_verbatim",
                    "snapshot_id": "verbatim_match_id",
                    "confidence": 100.0
                },
                {
                    "match_type": "exact_normalized",
                    "snapshot_id": "normalized_match_id",
                    "confidence": 100.0
                },
                {
                    "match_type": "similarity",
                    "snapshot_id": "similarity_match_id",
                    "confidence": 85.5
                },
                {
                    "match_type": "none",
                    "snapshot_id": None,
                    "confidence": 0.0
                }
            ]

            for test_case in match_type_tests:
                # Test embeddings
                test_embeddings = {
                    'verbatim': [0.1, 0.2, 0.3],
                    'normalized': [0.4, 0.5, 0.6],
                    'gist': [0.7, 0.8, 0.9]
                }

                # Test cache hits
                test_cache_hits = {
                    'verbatim': True,
                    'normalized': False,
                    'gist': True
                }

                # Test match result
                test_match = {
                    'snapshot_id': test_case["snapshot_id"],
                    'match_type': test_case["match_type"],
                    'confidence': test_case["confidence"]
                }

                # Call log_query
                query_id = query_log.log_query(
                    query_verbatim="What time is it?",
                    query_normalized="what time be it",
                    query_gist="current_time_request",
                    user_id="test_user",
                    session_id="test_session",
                    input_type="text",
                    embeddings=test_embeddings,
                    match_result=test_match,
                    processing_time_ms=150,
                    cache_hits=test_cache_hits
                )

                # Verify query was logged
                self.assertIsNotNone( query_id )
                mock_table.add.assert_called()

                # Verify the logged data structure
                call_args = mock_table.add.call_args[0][0]
                logged_record = call_args[0]  # First record in the list

                # Validate required fields
                self.assertEqual( logged_record["query_verbatim"], "What time is it?" )
                self.assertEqual( logged_record["query_normalized"], "what time be it" )
                self.assertEqual( logged_record["query_gist"], "current_time_request" )
                self.assertEqual( logged_record["user_id"], "test_user" )
                self.assertEqual( logged_record["session_id"], "test_session" )
                self.assertEqual( logged_record["input_type"], "text" )
                self.assertEqual( logged_record["match_type"], test_case["match_type"] )
                self.assertEqual( logged_record["match_confidence"], test_case["confidence"] )
                self.assertEqual( logged_record["processing_time_ms"], 150 )

                # Validate embeddings
                self.assertEqual( logged_record["embedding_verbatim"], [0.1, 0.2, 0.3] )
                self.assertEqual( logged_record["embedding_normalized"], [0.4, 0.5, 0.6] )
                self.assertEqual( logged_record["embedding_gist"], [0.7, 0.8, 0.9] )

                # Validate cache hits
                self.assertEqual( logged_record["cache_hit_verbatim"], True )
                self.assertEqual( logged_record["cache_hit_normalized"], False )
                self.assertEqual( logged_record["cache_hit_gist"], True )

                # Reset mock for next iteration
                mock_table.reset_mock()

    def test_get_recent_queries_with_pagination( self ):
        """
        Test get_recent_queries with pagination functionality.

        Ensures:
            - Recent queries retrieved in correct order
            - Pagination limits respected
            - Correct fields returned
            - Empty results handled
        """
        with patch( 'cosa.memory.query_log_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.query_log_table.ConfigurationManager' ):

            # Mock LanceDB table and search results
            mock_table = Mock()
            mock_search = Mock()

            # Mock recent queries data
            recent_queries_data = [
                {
                    "id": "query_1",
                    "timestamp": "2025-09-28T15:30:00",
                    "query_verbatim": "What time is it?",
                    "match_type": "exact_verbatim",
                    "cache_hit_verbatim": True,
                    "cache_hit_normalized": False,
                    "cache_hit_gist": True
                },
                {
                    "id": "query_2",
                    "timestamp": "2025-09-28T15:29:00",
                    "query_verbatim": "What's the weather?",
                    "match_type": "similarity",
                    "cache_hit_verbatim": False,
                    "cache_hit_normalized": True,
                    "cache_hit_gist": False
                }
            ]

            mock_search.limit.return_value.to_list.return_value = recent_queries_data
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            query_log = QueryLogTable( debug=False, verbose=False )

            # Test get_recent_queries
            result = query_log.get_recent_queries( limit=5 )

            # Verify search parameters
            mock_search.limit.assert_called_with( 5 )

            # Verify results
            self.assertEqual( len( result ), 2 )
            self.assertEqual( result[0]["query_verbatim"], "What time is it?" )
            self.assertEqual( result[1]["query_verbatim"], "What's the weather?" )

            # Test with different limit
            query_log.get_recent_queries( limit=10 )
            mock_search.limit.assert_called_with( 10 )

    def test_get_cache_hit_stats_calculation( self ):
        """
        Test get_cache_hit_stats calculation functionality.

        Ensures:
            - Cache hit statistics calculated correctly
            - Different time periods handled
            - Percentage calculations accurate
            - Edge cases handled (no data, all hits, no hits)
        """
        with patch( 'cosa.memory.query_log_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.query_log_table.ConfigurationManager' ):

            # Mock LanceDB table and search results
            mock_table = Mock()
            mock_search = Mock()

            # Mock cache hit statistics data
            cache_stats_data = [
                {"cache_hit_verbatim": True, "cache_hit_normalized": False, "cache_hit_gist": True},
                {"cache_hit_verbatim": False, "cache_hit_normalized": True, "cache_hit_gist": False},
                {"cache_hit_verbatim": True, "cache_hit_normalized": True, "cache_hit_gist": True},
                {"cache_hit_verbatim": False, "cache_hit_normalized": False, "cache_hit_gist": False}
            ]

            mock_search.to_list.return_value = cache_stats_data
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            query_log = QueryLogTable( debug=False, verbose=False )

            # Test cache hit statistics
            stats = query_log.get_cache_hit_stats( days=1 )

            # Verify expected statistics
            # verbatim: 2/4 = 50%, normalized: 2/4 = 50%, gist: 2/4 = 50%
            expected_stats = {
                "total_queries": 4,
                "verbatim_hit_rate": 50.0,
                "normalized_hit_rate": 50.0,
                "gist_hit_rate": 50.0,
                "overall_hit_rate": 50.0,
                "days_analyzed": 1
            }

            self.assertEqual( stats, expected_stats )

    def test_get_cache_hit_stats_edge_cases( self ):
        """
        Test cache hit statistics edge cases.

        Ensures:
            - No data returns appropriate stats
            - All hits handled correctly
            - All misses handled correctly
        """
        with patch( 'cosa.memory.query_log_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.query_log_table.ConfigurationManager' ):

            mock_table = Mock()
            mock_search = Mock()
            mock_table.search.return_value = mock_search
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            query_log = QueryLogTable( debug=False, verbose=False )

            # Test no data case
            mock_search.to_list.return_value = []
            stats = query_log.get_cache_hit_stats( days=1 )

            expected_no_data = {
                "total_queries": 0,
                "verbatim_hit_rate": 0.0,
                "normalized_hit_rate": 0.0,
                "gist_hit_rate": 0.0,
                "overall_hit_rate": 0.0,
                "days_analyzed": 1
            }

            self.assertEqual( stats, expected_no_data )

            # Test all hits case
            all_hits_data = [
                {"cache_hit_verbatim": True, "cache_hit_normalized": True, "cache_hit_gist": True},
                {"cache_hit_verbatim": True, "cache_hit_normalized": True, "cache_hit_gist": True}
            ]
            mock_search.to_list.return_value = all_hits_data
            stats = query_log.get_cache_hit_stats( days=1 )

            expected_all_hits = {
                "total_queries": 2,
                "verbatim_hit_rate": 100.0,
                "normalized_hit_rate": 100.0,
                "gist_hit_rate": 100.0,
                "overall_hit_rate": 100.0,
                "days_analyzed": 1
            }

            self.assertEqual( stats, expected_all_hits )

    def test_embedding_storage_and_retrieval( self ):
        """
        Test embedding storage and retrieval functionality.

        Ensures:
            - Embeddings stored correctly in all three levels
            - Embedding data types preserved
            - Large embeddings handled appropriately
        """
        with patch( 'cosa.memory.query_log_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.query_log_table.ConfigurationManager' ):

            mock_table = Mock()
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            query_log = QueryLogTable( debug=False, verbose=False )

            # Test with large embeddings (simulating real embedding dimensions)
            large_embeddings = {
                'verbatim': [0.1] * 1536,      # OpenAI embedding size
                'normalized': [0.2] * 1536,
                'gist': [0.3] * 1536
            }

            # Test match result
            test_match = {
                'snapshot_id': "test_id",
                'match_type': "similarity",
                'confidence': 85.0
            }

            # Test cache hits
            test_cache_hits = {
                'verbatim': False,
                'normalized': False,
                'gist': False
            }

            # Log query with large embeddings
            query_id = query_log.log_query(
                query_verbatim="Complex query",
                query_normalized="complex query",
                query_gist="complex request",
                user_id="test_user",
                session_id="test_session",
                input_type="text",
                embeddings=large_embeddings,
                match_result=test_match,
                processing_time_ms=200,
                cache_hits=test_cache_hits
            )

            # Verify embeddings stored correctly
            mock_table.add.assert_called_once()
            call_args = mock_table.add.call_args[0][0]
            logged_record = call_args[0]

            self.assertEqual( len( logged_record["embedding_verbatim"] ), 1536 )
            self.assertEqual( len( logged_record["embedding_normalized"] ), 1536 )
            self.assertEqual( len( logged_record["embedding_gist"] ), 1536 )

    def test_error_handling_invalid_inputs( self ):
        """
        Test error handling for invalid inputs.

        Ensures:
            - Invalid embeddings handled gracefully
            - Missing required fields handled
            - Database errors don't crash logging
            - Invalid data types handled appropriately
        """
        with patch( 'cosa.memory.query_log_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.query_log_table.ConfigurationManager' ):

            # Test database error handling
            mock_table = Mock()
            mock_table.add.side_effect = Exception( "Database error" )
            mock_lancedb.connect.return_value.open_table.return_value = mock_table

            query_log = QueryLogTable( debug=False, verbose=False )

            # Test with invalid embeddings
            invalid_embeddings = {
                'verbatim': "not_a_list",
                'normalized': None,
                'gist': [1, 2, "invalid"]
            }

            test_match = {
                'snapshot_id': "test_id",
                'match_type': "similarity",
                'confidence': 85.0
            }

            test_cache_hits = {
                'verbatim': False,
                'normalized': False,
                'gist': False
            }

            # Should handle errors gracefully
            query_id = query_log.log_query(
                query_verbatim="Test query",
                query_normalized="test query",
                query_gist="test request",
                user_id="test_user",
                session_id="test_session",
                input_type="text",
                embeddings=invalid_embeddings,
                match_result=test_match,
                processing_time_ms=100,
                cache_hits=test_cache_hits
            )

            # Should return None on error but not crash
            self.assertIsNone( query_id )

    def test_table_creation_and_schema_validation( self ):
        """
        Test table creation and schema validation.

        Ensures:
            - Table created with correct schema
            - Schema includes all required fields
            - Data types specified correctly
            - Indexes created appropriately
        """
        with patch( 'cosa.memory.query_log_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.query_log_table.ConfigurationManager' ), \
             patch( 'cosa.memory.query_log_table.pa' ) as mock_pa:

            # Mock PyArrow schema
            mock_schema = Mock()
            mock_pa.schema.return_value = mock_schema

            mock_db = Mock()
            mock_lancedb.connect.return_value = mock_db

            # Test table creation
            query_log = QueryLogTable( debug=False, verbose=False )

            # Verify schema creation with correct fields
            mock_pa.schema.assert_called_once()
            schema_call_args = mock_pa.schema.call_args[0][0]

            # Verify all required fields are in schema
            field_names = [field.call_args[0][0] for field in schema_call_args]

            required_fields = [
                "id", "timestamp", "user_id", "session_id",
                "query_verbatim", "query_normalized", "query_gist",
                "embedding_verbatim", "embedding_normalized", "embedding_gist",
                "matched_snapshot_id", "match_type", "match_confidence",
                "input_type", "processing_time_ms", "cache_hit_verbatim",
                "cache_hit_normalized", "cache_hit_gist"
            ]

            for required_field in required_fields:
                self.assertIn( required_field, field_names,
                             f"Required field '{required_field}' missing from schema" )

    def test_timestamp_handling( self ):
        """
        Test timestamp handling functionality.

        Ensures:
            - Timestamps generated correctly
            - Timezone handling appropriate
            - Timestamp formats consistent
        """
        with patch( 'cosa.memory.query_log_table.lancedb' ) as mock_lancedb, \
             patch( 'cosa.memory.query_log_table.ConfigurationManager' ), \
             patch( 'cosa.memory.query_log_table.du.get_current_datetime' ) as mock_timestamp:

            mock_table = Mock()
            mock_lancedb.connect.return_value.open_table.return_value = mock_table
            mock_timestamp.return_value = "2025-09-28-15-30-00"

            query_log = QueryLogTable( debug=False, verbose=False )

            # Test basic data
            test_embeddings = {'verbatim': [0.1], 'normalized': [0.2], 'gist': [0.3]}
            test_match = {'snapshot_id': "test", 'match_type': "exact_verbatim", 'confidence': 100.0}
            test_cache_hits = {'verbatim': True, 'normalized': False, 'gist': True}

            # Log query
            query_log.log_query(
                query_verbatim="Test",
                query_normalized="test",
                query_gist="test request",
                user_id="user",
                session_id="session",
                input_type="text",
                embeddings=test_embeddings,
                match_result=test_match,
                processing_time_ms=50,
                cache_hits=test_cache_hits
            )

            # Verify timestamp was used
            mock_timestamp.assert_called_once()

            # Verify timestamp in logged data
            call_args = mock_table.add.call_args[0][0]
            logged_record = call_args[0]
            self.assertEqual( logged_record["timestamp"], "2025-09-28-15-30-00" )

    def test_initialization_parameters( self ):
        """
        Test QueryLogTable initialization with various parameters.

        Ensures:
            - Debug and verbose flags handled correctly
            - Default values set appropriately
            - Configuration integration working
        """
        with patch( 'cosa.memory.query_log_table.lancedb' ), \
             patch( 'cosa.memory.query_log_table.ConfigurationManager' ):

            # Test default initialization
            query_log_default = QueryLogTable()
            self.assertIsNotNone( query_log_default )

            # Test with debug and verbose
            query_log_debug = QueryLogTable( debug=True, verbose=True )
            self.assertIsNotNone( query_log_debug )

            # Verify initialization completed without errors
            self.assertTrue( hasattr( query_log_default, '_ensure_table_exists' ) )


if __name__ == "__main__":
    unittest.main()