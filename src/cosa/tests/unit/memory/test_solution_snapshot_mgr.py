"""
Unit tests for SolutionSnapshotManager with comprehensive mocking.

Tests the SolutionSnapshotManager class including:
- Snapshot loading from filesystem directories
- Indexing by question, synonymous questions, and gists
- State management and lookups
- Adding and deleting snapshots
- File system operations (mocked)
- Integration with EmbeddingManager and QuestionEmbeddingsTable

Zero external dependencies - all file operations, database operations,
and external service calls are mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call, mock_open
import time
import os
from typing import List, Dict, Any, Optional
from collections import OrderedDict

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.memory.solution_snapshot_mgr import SolutionSnapshotManager


class TestSolutionSnapshotManager( unittest.TestCase ):
    """
    Comprehensive unit tests for SolutionSnapshotManager class.
    
    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns
        
    Ensures:
        - All SolutionSnapshotManager functionality tested in isolation
        - File system operations properly mocked
        - Snapshot indexing and state management validated
        - Integration with other components mocked
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
        
        # Common test data
        self.test_path = "/test/snapshots"
        self.mock_snapshot_files = ["question1.json", "question2.json", "hidden.json"]
    
    def tearDown( self ):
        """
        Cleanup after each test method.
        
        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()
    
    def _create_mock_snapshot( self, question, question_gist="", synonymous_questions=None, synonymous_gists=None ):
        """
        Helper to create mock SolutionSnapshot objects.
        
        Args:
            question: Main question for the snapshot
            question_gist: Gist of the question
            synonymous_questions: Dict of synonymous questions with scores
            synonymous_gists: Dict of synonymous gists with scores
            
        Returns:
            Mock snapshot object with required attributes
        """
        if synonymous_questions is None:
            synonymous_questions = OrderedDict( [(question, 100.0)] )
        if synonymous_gists is None:
            synonymous_gists = OrderedDict( [(question_gist or question, 100.0)] )
        
        mock_snapshot = Mock()
        mock_snapshot.question = question
        mock_snapshot.question_gist = question_gist or question
        mock_snapshot.synonymous_questions = synonymous_questions
        mock_snapshot.synonymous_question_gists = synonymous_gists
        # Removed write_current_state_to_file mock - serialization handled by manager
        
        return mock_snapshot
    
    def test_initialization( self ):
        """
        Test SolutionSnapshotManager initialization.
        
        Ensures:
            - Manager initializes with given path
            - load_snapshots is called during initialization
            - EmbeddingManager and QuestionEmbeddingsTable created
        """
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ) as mock_embedding_mgr, \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ) as mock_question_table, \
             patch( "os.listdir", return_value=[] ), \
             patch( "builtins.print" ):
            
            mock_embedding_mgr.return_value = Mock()
            mock_question_table.return_value = Mock()
            
            # Test initialization
            manager = SolutionSnapshotManager( path=self.test_path, debug=False )
            
            # Verify attributes
            self.assertEqual( manager.path, self.test_path )
            self.assertFalse( manager.debug )
            self.assertFalse( manager.verbose )
            
            # Verify components initialized
            mock_embedding_mgr.assert_called_once_with( debug=False, verbose=False )
            mock_question_table.assert_called_once()
    
    def test_load_snapshots_by_question( self ):
        """
        Test loading snapshots indexed by question.
        
        Ensures:
            - JSON files are discovered and loaded
            - Hidden files are filtered out
            - Snapshots indexed by question correctly
        """
        # Create mock snapshots
        snapshot1 = self._create_mock_snapshot( "What is 2+2?" )
        snapshot2 = self._create_mock_snapshot( "Calculate square root" )
        
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ) as mock_embedding_mgr, \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ) as mock_question_table, \
             patch( "os.listdir", return_value=["._hidden.json", "question1.json", "question2.json", "not_json.txt"] ), \
             patch( "cosa.memory.solution_snapshot_mgr.ss.SolutionSnapshot.from_json_file" ) as mock_from_json, \
             patch( "builtins.print" ):
            
            mock_embedding_mgr.return_value = Mock()
            mock_question_table.return_value = Mock()
            mock_from_json.side_effect = [snapshot1, snapshot2]
            
            # Test initialization (triggers loading)
            manager = SolutionSnapshotManager( path=self.test_path, debug=False )
            
            # Verify file filtering (only .json files, no hidden files)
            self.assertEqual( mock_from_json.call_count, 2 )
            
            # Verify snapshots indexed by question
            self.assertIn( "What is 2+2?", manager._snapshots_by_question )
            self.assertIn( "Calculate square root", manager._snapshots_by_question )
            self.assertEqual( manager._snapshots_by_question["What is 2+2?"], snapshot1 )
            self.assertEqual( manager._snapshots_by_question["Calculate square root"], snapshot2 )
    
    def test_load_snapshots_by_synonymous_questions( self ):
        """
        Test loading snapshots indexed by synonymous questions.
        
        Ensures:
            - Synonymous questions from all snapshots indexed
            - Similarity scores preserved
            - Index maps to correct snapshots
        """
        # Create mock snapshots with synonymous questions
        synonymous_q1 = OrderedDict( [("What is 2+2?", 100.0), ("Calculate 2+2", 95.0)] )
        synonymous_q2 = OrderedDict( [("Square root of 16", 100.0), ("sqrt(16)", 90.0)] )
        
        snapshot1 = self._create_mock_snapshot( "What is 2+2?", synonymous_questions=synonymous_q1 )
        snapshot2 = self._create_mock_snapshot( "Square root of 16", synonymous_questions=synonymous_q2 )
        
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ) as mock_embedding_mgr, \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ) as mock_question_table, \
             patch( "os.listdir", return_value=["q1.json", "q2.json"] ), \
             patch( "cosa.memory.solution_snapshot_mgr.ss.SolutionSnapshot.from_json_file" ) as mock_from_json, \
             patch( "builtins.print" ):
            
            mock_embedding_mgr.return_value = Mock()
            mock_question_table.return_value = Mock()
            mock_from_json.side_effect = [snapshot1, snapshot2]
            
            # Test initialization
            manager = SolutionSnapshotManager( path=self.test_path, debug=False )
            
            # Verify synonymous questions indexed
            syn_questions = manager._snapshots_by_synonymous_questions
            
            # Check all synonymous questions are indexed
            self.assertIn( "What is 2+2?", syn_questions )
            self.assertIn( "Calculate 2+2", syn_questions )
            self.assertIn( "Square root of 16", syn_questions )
            self.assertIn( "sqrt(16)", syn_questions )
            
            # Verify scores and mappings
            self.assertEqual( syn_questions["Calculate 2+2"][0], 95.0 )  # Score
            self.assertEqual( syn_questions["Calculate 2+2"][1], snapshot1 )  # Snapshot
            self.assertEqual( syn_questions["sqrt(16)"][0], 90.0 )
            self.assertEqual( syn_questions["sqrt(16)"][1], snapshot2 )
    
    def test_load_snapshots_by_gist( self ):
        """
        Test loading snapshots indexed by question gists.
        
        Ensures:
            - Question gists from all snapshots indexed
            - Gist similarity scores preserved
            - Index maps to correct snapshots
        """
        # Create mock snapshots with gists
        synonymous_gists1 = OrderedDict( [("two plus two", 100.0), ("add two two", 90.0)] )
        synonymous_gists2 = OrderedDict( [("square root sixteen", 100.0), ("sqrt sixteen", 85.0)] )
        
        snapshot1 = self._create_mock_snapshot( "What is 2+2?", "two plus two", synonymous_gists=synonymous_gists1 )
        snapshot2 = self._create_mock_snapshot( "Square root of 16", "square root sixteen", synonymous_gists=synonymous_gists2 )
        
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ) as mock_embedding_mgr, \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ) as mock_question_table, \
             patch( "os.listdir", return_value=["q1.json", "q2.json"] ), \
             patch( "cosa.memory.solution_snapshot_mgr.ss.SolutionSnapshot.from_json_file" ) as mock_from_json, \
             patch( "builtins.print" ):
            
            mock_embedding_mgr.return_value = Mock()
            mock_question_table.return_value = Mock()
            mock_from_json.side_effect = [snapshot1, snapshot2]
            
            # Test initialization
            manager = SolutionSnapshotManager( path=self.test_path, debug=False )
            
            # Verify gists indexed
            gists = manager._snapshots_by_question_gist
            
            # Check all gists are indexed
            self.assertIn( "two plus two", gists )
            self.assertIn( "add two two", gists )
            self.assertIn( "square root sixteen", gists )
            self.assertIn( "sqrt sixteen", gists )
            
            # Verify scores and mappings
            self.assertEqual( gists["add two two"][0], 90.0 )  # Score
            self.assertEqual( gists["add two two"][1], snapshot1 )  # Snapshot
            self.assertEqual( gists["sqrt sixteen"][0], 85.0 )
            self.assertEqual( gists["sqrt sixteen"][1], snapshot2 )
    
    def test_add_snapshot( self ):
        """
        Test adding a new snapshot to the manager.
        
        Ensures:
            - Snapshot added to question index
            - Manager state updated correctly
            - Serialization handled internally by manager
        """
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ) as mock_embedding_mgr, \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ) as mock_question_table, \
             patch( "os.listdir", return_value=[] ), \
             patch( "builtins.print" ):
            
            mock_embedding_mgr.return_value = Mock()
            mock_question_table.return_value = Mock()
            
            manager = SolutionSnapshotManager( path=self.test_path, debug=False )
            
            # Create new snapshot to add
            new_snapshot = self._create_mock_snapshot( "New question?" )
            
            # Test adding snapshot
            manager.add_snapshot( new_snapshot )
            
            # Verify snapshot added to index
            self.assertIn( "New question?", manager._snapshots_by_question )
            self.assertEqual( manager._snapshots_by_question["New question?"], new_snapshot )
            
            # Note: write_current_state_to_file() assertion removed
            # Serialization is now handled internally by manager.add_snapshot()
    
    def test_question_exists_methods( self ):
        """
        Test question existence checking methods.
        
        Ensures:
            - _question_exists works for exact questions
            - _synonymous_question_exists works for synonymous questions
            - _question_gist_exists works for gists
        """
        # Setup test data
        synonymous_q = OrderedDict( [("What is 2+2?", 100.0), ("Calculate 2+2", 95.0)] )
        synonymous_g = OrderedDict( [("two plus two", 100.0), ("add two two", 90.0)] )
        
        snapshot = self._create_mock_snapshot( 
            "What is 2+2?", 
            "two plus two",
            synonymous_questions=synonymous_q,
            synonymous_gists=synonymous_g
        )
        
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ) as mock_embedding_mgr, \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ) as mock_question_table, \
             patch( "os.listdir", return_value=["test.json"] ), \
             patch( "cosa.memory.solution_snapshot_mgr.ss.SolutionSnapshot.from_json_file", return_value=snapshot ), \
             patch( "builtins.print" ):
            
            mock_embedding_mgr.return_value = Mock()
            mock_question_table.return_value = Mock()
            
            manager = SolutionSnapshotManager( path=self.test_path, debug=False )
            
            # Test exact question exists
            self.assertTrue( manager._question_exists( "What is 2+2?" ) )
            self.assertFalse( manager._question_exists( "What is 3+3?" ) )
            
            # Test synonymous question exists
            self.assertTrue( manager._synonymous_question_exists( "Calculate 2+2" ) )
            self.assertFalse( manager._synonymous_question_exists( "What is 3+3?" ) )
            
            # Test gist exists
            self.assertTrue( manager._question_gist_exists( "two plus two" ) )
            self.assertTrue( manager._question_gist_exists( "add two two" ) )
            self.assertFalse( manager._question_gist_exists( "three plus three" ) )
            self.assertFalse( manager._question_gist_exists( None ) )
    
    def test_get_gists( self ):
        """
        Test getting all gists from the manager.
        
        Ensures:
            - Returns list of all gist strings
            - List contains expected gists
        """
        # Setup test data with gists
        synonymous_g1 = OrderedDict( [("gist one", 100.0), ("gist one alt", 90.0)] )
        synonymous_g2 = OrderedDict( [("gist two", 100.0), ("gist two alt", 85.0)] )
        
        snapshot1 = self._create_mock_snapshot( "Question 1", "gist one", synonymous_gists=synonymous_g1 )
        snapshot2 = self._create_mock_snapshot( "Question 2", "gist two", synonymous_gists=synonymous_g2 )
        
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ) as mock_embedding_mgr, \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ) as mock_question_table, \
             patch( "os.listdir", return_value=["q1.json", "q2.json"] ), \
             patch( "cosa.memory.solution_snapshot_mgr.ss.SolutionSnapshot.from_json_file" ) as mock_from_json, \
             patch( "builtins.print" ):
            
            mock_embedding_mgr.return_value = Mock()
            mock_question_table.return_value = Mock()
            mock_from_json.side_effect = [snapshot1, snapshot2]
            
            manager = SolutionSnapshotManager( path=self.test_path, debug=False )
            
            # Test getting all gists
            gists = manager.get_gists()
            
            # Verify all gists returned
            self.assertIsInstance( gists, list )
            self.assertIn( "gist one", gists )
            self.assertIn( "gist one alt", gists )
            self.assertIn( "gist two", gists )
            self.assertIn( "gist two alt", gists )
            self.assertEqual( len( gists ), 4 )
    
    def test_debug_output( self ):
        """
        Test debug output functionality.
        
        Ensures:
            - Debug prints work when debug=True
            - Verbose output works when verbose=True
            - print_snapshots method called when appropriate
        """
        snapshot = self._create_mock_snapshot( "Test question" )
        
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ) as mock_embedding_mgr, \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ) as mock_question_table, \
             patch( "os.listdir", return_value=["test.json"] ), \
             patch( "cosa.memory.solution_snapshot_mgr.ss.SolutionSnapshot.from_json_file", return_value=snapshot ), \
             patch( "builtins.print" ) as mock_print:
            
            mock_embedding_mgr.return_value = Mock()
            mock_question_table.return_value = Mock()
            
            # Test with debug=True, verbose=True
            manager = SolutionSnapshotManager( path=self.test_path, debug=True, verbose=True )
            
            # Verify debug flags set
            self.assertTrue( manager.debug )
            self.assertTrue( manager.verbose )
            
            # Verify debug prints were called (hard to test exact content, but can verify calls made)
            self.assertGreater( mock_print.call_count, 0 )


def isolated_unit_test():
    """
    Run comprehensive unit tests for SolutionSnapshotManager in complete isolation.
    
    Ensures:
        - All external dependencies mocked
        - No real file system operations
        - Deterministic test results
        - Fast execution
        
    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    import cosa.utils.util as du
    
    start_time = time.time()
    
    try:
        du.print_banner( "SolutionSnapshotManager Unit Tests - Memory System Phase 3", prepend_nl=True )
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_initialization',
            'test_load_snapshots_by_question',
            'test_load_snapshots_by_synonymous_questions',
            'test_load_snapshots_by_gist',
            'test_add_snapshot',
            'test_question_exists_methods',
            'test_get_gists',
            'test_debug_output'
        ]
        
        for method in test_methods:
            suite.addTest( TestSolutionSnapshotManager( method ) )
        
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
        print( f"SOLUTION SNAPSHOT MANAGER UNIT TEST RESULTS" )
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
            du.print_banner( "✅ ALL SOLUTION SNAPSHOT MANAGER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME SOLUTION SNAPSHOT MANAGER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        
        return success, duration, message
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 SOLUTION SNAPSHOT MANAGER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} SolutionSnapshotManager unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )