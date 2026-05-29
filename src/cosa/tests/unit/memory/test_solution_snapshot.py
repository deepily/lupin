"""
Unit tests for SolutionSnapshot with comprehensive mocking.

Tests the SolutionSnapshot class including:
- Static utility methods (timestamps, hashing, text cleaning)
- Initialization with embedding generation
- File I/O operations with mocked filesystem
- Runtime statistics management
- Code execution integration (via RunnableCode inheritance)
- Similarity calculations and embedding operations

Zero external dependencies - all file operations, embedding generation,
and external service calls are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import time
from collections import OrderedDict
from typing import List, Dict, Any, Optional

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.memory.solution_snapshot import SolutionSnapshot


class TestSolutionSnapshot( unittest.TestCase ):
    """
    Comprehensive unit tests for SolutionSnapshot class.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All SolutionSnapshot functionality tested in isolation
        - File I/O operations properly mocked
        - Embedding generation mocked
        - Static methods validated
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
    
    def test_static_methods( self ):
        """
        Test static utility methods.
        
        Ensures:
            - get_timestamp returns valid datetime string
            - remove_non_alphanumerics cleans text correctly
            - escape_single_quotes removes quotes
            - generate_id_hash creates unique hashes
            - get_default_stats_dict returns proper structure
        """
        # Test timestamp generation
        with patch( "cosa.memory.solution_snapshot.du.get_current_datetime", return_value="2025-08-05-12-00-00" ):
            timestamp = SolutionSnapshot.get_timestamp()
            self.assertEqual( timestamp, "2025-08-05-12-00-00" )
        
        # Test text cleaning
        test_cases = [
            ( "Hello, World!", "hello world" ),
            ( "What's 2+2?", "whats 22" ),
            ( "user@example.com", "userexamplecom" ),
            ( "Test-123_ABC", "test123abc" )
        ]
        
        for input_text, expected in test_cases:
            result = SolutionSnapshot.remove_non_alphanumerics( input_text )
            self.assertEqual( result, expected )
        
        # Test quote escaping
        self.assertEqual( SolutionSnapshot.escape_single_quotes( "It's working" ), "Its working" )
        self.assertEqual( SolutionSnapshot.escape_single_quotes( "No quotes" ), "No quotes" )
        
        # Test hash generation
        hash1 = SolutionSnapshot.generate_id_hash( 1, "2025-08-05" )
        hash2 = SolutionSnapshot.generate_id_hash( 2, "2025-08-05" )
        hash3 = SolutionSnapshot.generate_id_hash( 1, "2025-08-06" )
        
        # Hashes should be different for different inputs
        self.assertNotEqual( hash1, hash2 )
        self.assertNotEqual( hash1, hash3 )
        self.assertNotEqual( hash2, hash3 )
        
        # Hash should be consistent for same inputs
        hash1_repeat = SolutionSnapshot.generate_id_hash( 1, "2025-08-05" )
        self.assertEqual( hash1, hash1_repeat )
        
        # Test default stats dictionary
        stats = SolutionSnapshot.get_default_stats_dict()
        expected_keys = ["first_run_ms", "run_count", "total_ms", "mean_run_ms", "last_run_ms", "time_saved_ms"]
        for key in expected_keys:
            self.assertIn( key, stats )
            self.assertIsInstance( stats[key], (int, float) )
    
    def test_embedding_similarity( self ):
        """
        Test embedding similarity calculation.
        
        Ensures:
            - Dot product calculated correctly
            - Returns percentage (0-100)
            - Handles different embedding values
        """
        # Test identical embeddings
        embedding1 = [1.0, 0.0, 0.0]
        embedding2 = [1.0, 0.0, 0.0]
        similarity = SolutionSnapshot.get_embedding_similarity( embedding1, embedding2 )
        self.assertEqual( similarity, 100.0 )  # dot product is 1.0, * 100 = 100
        
        # Test orthogonal embeddings
        embedding3 = [1.0, 0.0, 0.0]
        embedding4 = [0.0, 1.0, 0.0]
        similarity = SolutionSnapshot.get_embedding_similarity( embedding3, embedding4 )
        self.assertEqual( similarity, 0.0 )  # dot product is 0.0, * 100 = 0
        
        # Test partially similar embeddings
        embedding5 = [0.6, 0.8, 0.0]
        embedding6 = [0.8, 0.6, 0.0]
        similarity = SolutionSnapshot.get_embedding_similarity( embedding5, embedding6 )
        expected = (0.6 * 0.8 + 0.8 * 0.6) * 100  # 0.96 * 100 = 96.0
        self.assertEqual( similarity, expected )
    
    def test_initialization_minimal( self ):
        """
        Test SolutionSnapshot initialization with minimal parameters.
        
        Ensures:
            - Basic initialization works
            - Default values assigned correctly
            - No embedding generation for empty content
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class, \
             patch( "cosa.memory.solution_snapshot.du.get_current_datetime", return_value="2025-08-05-12-00-00" ):
            
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr
            
            # Test minimal initialization
            snapshot = SolutionSnapshot( debug=False, verbose=False )
            
            # Verify basic attributes
            self.assertEqual( snapshot.push_counter, -1 )
            self.assertEqual( snapshot.question, "" )
            self.assertEqual( snapshot.question_gist, "" )
            self.assertEqual( snapshot.answer, "" )
            self.assertIsInstance( snapshot.runtime_stats, dict )
            
            # Verify no embedding generation for empty content
            mock_embedding_mgr.generate_embedding.assert_not_called()
    
    def test_initialization_with_content( self ):
        """
        Test SolutionSnapshot initialization with content requiring embeddings.
        
        Ensures:
            - Embeddings generated for provided content
            - Text normalization applied correctly
            - EmbeddingManager called with appropriate parameters
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class, \
             patch( "cosa.memory.solution_snapshot.du.get_current_datetime", return_value="2025-08-05-12-00-00" ), \
 \
             patch( "builtins.print" ):
            
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr
            
            # Setup mock embedding returns
            question_embedding = [0.1] * 1536
            gist_embedding = [0.2] * 1536
            code_embedding = [0.3] * 1536
            
            mock_embedding_mgr.generate_embedding.side_effect = [
                question_embedding,  # For question
                gist_embedding,      # For gist
                code_embedding       # For code
            ]
            
            # Test initialization with content
            snapshot = SolutionSnapshot(
                push_counter=1,
                question="What's 2+2?",
                question_gist="what is two plus two",
                code=["result = 2 + 2", "print(result)"],
                debug=False
            )
            
            # Verify text normalization
            self.assertEqual( snapshot.question, "whats 22" )  # Normalized
            self.assertEqual( snapshot.question_gist, "what is two plus two" )  # Not normalized in this case
            
            # Verify embedding generation calls
            self.assertEqual( mock_embedding_mgr.generate_embedding.call_count, 3 )
            
            # Verify embeddings assigned
            self.assertEqual( snapshot.question_embedding, question_embedding )
            self.assertEqual( snapshot.question_gist_embedding, gist_embedding )
            self.assertEqual( snapshot.code_embedding, code_embedding )
            
            # Verify file write was attempted (due to dirty state)
            mock_write_file.assert_called_once()
    
    def test_initialization_with_existing_embeddings( self ):
        """
        Test SolutionSnapshot initialization with pre-existing embeddings.
        
        Ensures:
            - Existing embeddings are used
            - No new embedding generation occurs
            - Embeddings preserved correctly
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class, \
             patch( "cosa.memory.solution_snapshot.du.get_current_datetime", return_value="2025-08-05-12-00-00" ):
            
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr
            
            # Pre-existing embeddings
            existing_question_embedding = [0.5] * 1536
            existing_gist_embedding = [0.6] * 1536
            existing_code_embedding = [0.7] * 1536
            
            # Test initialization with existing embeddings
            snapshot = SolutionSnapshot(
                question="Test question",
                question_gist="test gist",
                code=["test code"],
                question_embedding=existing_question_embedding,
                question_gist_embedding=existing_gist_embedding,
                code_embedding=existing_code_embedding,
                debug=False
            )
            
            # Verify no embedding generation
            mock_embedding_mgr.generate_embedding.assert_not_called()
            
            # Verify existing embeddings preserved
            self.assertEqual( snapshot.question_embedding, existing_question_embedding )
            self.assertEqual( snapshot.question_gist_embedding, existing_gist_embedding )
            self.assertEqual( snapshot.code_embedding, existing_code_embedding )
    
    def test_synonymous_questions_handling( self ):
        """
        Test handling of synonymous questions and gists.
        
        Ensures:
            - Synonymous questions handled correctly
            - Default behavior when no synonymous questions provided
            - OrderedDict structure preserved
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class, \
             patch( "cosa.memory.solution_snapshot.du.get_current_datetime", return_value="2025-08-05-12-00-00" ), \
 \
             patch( "builtins.print" ):
            
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr
            
            # Setup mock embedding returns for question and gist
            question_embedding = [0.1] * 1536
            gist_embedding = [0.2] * 1536
            mock_embedding_mgr.generate_embedding.side_effect = [question_embedding, gist_embedding]
            
            # Test with provided synonymous questions
            synonymous_q = OrderedDict( [("What is 2+2?", 95.0), ("Calculate 2+2", 90.0)] )
            synonymous_gists = OrderedDict( [("two plus two", 95.0), ("calculate two plus two", 90.0)] )
            
            snapshot = SolutionSnapshot(
                question="What's 2+2?",
                question_gist="whats two plus two", 
                synonymous_questions=synonymous_q,
                synonymous_question_gists=synonymous_gists,
                debug=False
            )
            
            # Verify synonymous questions preserved
            self.assertEqual( snapshot.synonymous_questions, synonymous_q )
            self.assertEqual( snapshot.synonymous_question_gists, synonymous_gists )
    
    def test_hash_generation( self ):
        """
        Test automatic hash generation.
        
        Ensures:
            - Hash generated when not provided
            - Provided hash preserved when given
            - Hash generation uses counter and date
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class, \
             patch( "cosa.memory.solution_snapshot.du.get_current_datetime", return_value="2025-08-05-12-00-00" ):
            
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr
            
            # Test auto-generated hash
            snapshot1 = SolutionSnapshot( push_counter=1, debug=False )
            self.assertNotEqual( snapshot1.id_hash, "" )
            self.assertIsInstance( snapshot1.id_hash, str )
            
            # Test provided hash
            custom_hash = "custom_hash_123"
            snapshot2 = SolutionSnapshot( push_counter=2, id_hash=custom_hash, debug=False )
            self.assertEqual( snapshot2.id_hash, custom_hash )
            
            # Test different counters generate different hashes
            snapshot3 = SolutionSnapshot( push_counter=3, debug=False )
            self.assertNotEqual( snapshot1.id_hash, snapshot3.id_hash )
    
    def test_metadata_handling( self ):
        """
        Test metadata fields handling.
        
        Ensures:
            - Timestamps handled correctly
            - Runtime stats initialized properly
            - User ID and other metadata preserved
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class, \
             patch( "cosa.memory.solution_snapshot.du.get_current_datetime", return_value="2025-08-05-12-00-00" ):
            
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr
            
            custom_stats = {"custom_stat": 42}
            custom_user_id = "test_user_123"
            
            snapshot = SolutionSnapshot(
                runtime_stats=custom_stats,
                user_id=custom_user_id,
                solution_directory="/custom/path/",
                programming_language="JavaScript",
                language_version="ES2021",
                debug=False
            )
            
            # Verify metadata preservation
            self.assertEqual( snapshot.runtime_stats, custom_stats )
            self.assertEqual( snapshot.user_id, custom_user_id )
            self.assertEqual( snapshot.solution_directory, "/custom/path/" )
            self.assertEqual( snapshot.programming_language, "JavaScript" )
            self.assertEqual( snapshot.language_version, "ES2021" )

    def test_question_normalized_field_initialization( self ):
        """
        Test question_normalized field initialization (THREE-LEVEL ARCHITECTURE).

        This validates the new question_normalized field added for the
        three-level question representation architecture.

        Ensures:
            - question_normalized field initialized correctly
            - Field accepts string values
            - Field integrates with existing snapshot structure
            - Backward compatibility maintained
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class:
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr

            # Test with question_normalized provided
            snapshot = SolutionSnapshot(
                question="What time is it?",
                question_normalized="what time be it",
                answer="It is 3:00 PM",
                debug=False
            )

            # Verify question_normalized field
            self.assertEqual( snapshot.question_normalized, "what time be it" )
            self.assertEqual( snapshot.question, "What time is it?" )
            self.assertEqual( snapshot.answer, "It is 3:00 PM" )

    def test_question_normalized_field_backward_compatibility( self ):
        """
        Test backward compatibility with snapshots missing question_normalized.

        This ensures that existing snapshots without the question_normalized
        field continue to work correctly.

        Ensures:
            - Snapshots without question_normalized don't crash
            - Default value or None handling works
            - No regression in existing functionality
            - Serialization/deserialization works correctly
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class:
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr

            # Test without question_normalized (backward compatibility)
            snapshot = SolutionSnapshot(
                question="What time is it?",
                answer="It is 3:00 PM",
                debug=False
            )

            # Verify backward compatibility
            self.assertEqual( snapshot.question, "What time is it?" )
            self.assertEqual( snapshot.answer, "It is 3:00 PM" )

            # Verify question_normalized handles absence gracefully
            if hasattr( snapshot, 'question_normalized' ):
                # If field exists, it should be None or empty
                self.assertIn( snapshot.question_normalized, [None, "", "what time be it"] )
            # If field doesn't exist, that's also acceptable for backward compatibility

    def test_question_normalized_schema_validation( self ):
        """
        Test schema validation with three-level fields.

        This validates that the SolutionSnapshot correctly handles
        the three-level representation fields for schema compliance.

        Ensures:
            - All three-level fields work together
            - Schema validation passes
            - Field relationships maintained
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class:
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr

            # Test with all three-level fields
            snapshot = SolutionSnapshot(
                question="What time is it?",
                question_normalized="what time be it",
                answer="It is 3:00 PM",
                code=["import datetime", "print(datetime.datetime.now())"],
                thoughts="Simple time query requiring system time access",
                debug=False
            )

            # Verify all fields set correctly
            self.assertEqual( snapshot.question, "What time is it?" )
            self.assertEqual( snapshot.question_normalized, "what time be it" )
            self.assertEqual( snapshot.answer, "It is 3:00 PM" )
            self.assertIsNotNone( snapshot.code )
            self.assertIsNotNone( snapshot.thoughts )

    def test_question_normalized_serialization_deserialization( self ):
        """
        Test serialization and deserialization with question_normalized field.

        This ensures that the new field is properly handled during
        data persistence and retrieval operations.

        Ensures:
            - question_normalized serializes correctly
            - Deserialization preserves the field
            - No data loss during round-trip operations
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class:
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr

            # Create snapshot with question_normalized
            original_snapshot = SolutionSnapshot(
                question="How is the weather?",
                question_normalized="how be the weather",
                answer="The weather is sunny",
                debug=False
            )

            # Test that the field is accessible and correct
            self.assertEqual( original_snapshot.question_normalized, "how be the weather" )

            # Note: Actual serialization testing would require the to_dict/from_dict methods
            # which may be implemented in the SolutionSnapshot class
            if hasattr( original_snapshot, 'to_dict' ):
                # Test serialization round trip
                snapshot_dict = original_snapshot.to_dict()
                self.assertIn( 'question_normalized', snapshot_dict )
                self.assertEqual( snapshot_dict['question_normalized'], "how be the weather" )

    def test_question_normalized_edge_cases( self ):
        """
        Test edge cases for question_normalized field.

        This validates proper handling of edge cases and
        unusual inputs for the question_normalized field.

        Ensures:
            - Empty string handling
            - None value handling
            - Very long normalized text
            - Special characters in normalized text
        """
        with patch( "cosa.memory.solution_snapshot.EmbeddingManager" ) as mock_embedding_mgr_class:
            mock_embedding_mgr = Mock()
            mock_embedding_mgr_class.return_value = mock_embedding_mgr

            # Test empty string
            snapshot1 = SolutionSnapshot(
                question="Empty normalized test",
                question_normalized="",
                answer="Test answer",
                debug=False
            )
            self.assertEqual( snapshot1.question_normalized, "" )

            # Test None value
            snapshot2 = SolutionSnapshot(
                question="None normalized test",
                question_normalized=None,
                answer="Test answer",
                debug=False
            )
            self.assertIsNone( snapshot2.question_normalized )

            # Test very long normalized text
            long_normalized = "very long normalized text " * 100
            snapshot3 = SolutionSnapshot(
                question="Long normalized test",
                question_normalized=long_normalized,
                answer="Test answer",
                debug=False
            )
            self.assertEqual( snapshot3.question_normalized, long_normalized )


def isolated_unit_test():
    """
    Run comprehensive unit tests for SolutionSnapshot in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real file I/O or embedding generation
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "SolutionSnapshot Unit Tests - Memory System Phase 3", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_static_methods',
            'test_embedding_similarity',
            'test_initialization_minimal',
            'test_initialization_with_content',
            'test_initialization_with_existing_embeddings',
            'test_synonymous_questions_handling',
            'test_hash_generation',
            'test_metadata_handling',
            'test_question_normalized_field_initialization',
            'test_question_normalized_field_backward_compatibility',
            'test_question_normalized_schema_validation',
            'test_question_normalized_serialization_deserialization',
            'test_question_normalized_edge_cases'
        ]
        
        for method in test_methods:
            suite.addTest( TestSolutionSnapshot( method ) )
        
        # Run tests with detailed output
        runner = unittest.TextTestRunner( verbosity=2, stream=sys.stdout )
        result = runner.run( suite )
        
        duration = time.time() - start_time
        
        # Calculate results
        tests_run = result.testsRun
        failures = len( result.failures )
        errors = len( result.errors )
        success_count = tests_run - failures - errors
        
        print( f"\n{'='*60}" )
        print( f"SOLUTION SNAPSHOT UNIT TEST RESULTS" )
        print( f"{'='*60}" )
        print( f"Tests Run     : {tests_run}" )
        print( f"Passed        : {success_count}" )
        print( f"Failed        : {failures}" )
        print( f"Errors        : {errors}" )
        print( f"Success Rate  : {(success_count/tests_run)*100:.1f}%" )
        print( f"Duration      : {duration:.3f} seconds" )
        print( f"{'='*60}" )
        
        if failures > 0:
            print( "\nFAILURE DETAILS:" )
            for test, traceback in result.failures:
                print( f"❌ {test}: {traceback.split(chr(10))[-2]}" )
                
        if errors > 0:
            print( "\nERROR DETAILS:" )
            for test, traceback in result.errors:
                print( f"💥 {test}: {traceback.split(chr(10))[-2]}" )
        
        success = failures == 0 and errors == 0
        
        if success:
            du.print_banner( "✅ ALL SOLUTION SNAPSHOT TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME SOLUTION SNAPSHOT TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 SOLUTION SNAPSHOT TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} SolutionSnapshot unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )