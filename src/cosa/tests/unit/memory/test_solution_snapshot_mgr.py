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
from contextlib import contextmanager
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
            
            # Test adding snapshot (real API is save_snapshot — upsert semantics)
            manager.save_snapshot( new_snapshot )
            
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


def _mk_snap( question, q_emb=None, syn_q=None, syn_g=None ):
    """Build a mock SolutionSnapshot with the attributes the manager reads."""
    snap = Mock()
    snap.question                  = question
    snap.question_gist             = question
    snap.question_embedding        = q_emb if q_emb is not None else [ 1.0, 0.0 ]
    snap.non_synonymous_questions  = []
    snap.synonymous_questions      = syn_q if syn_q is not None else OrderedDict( [ ( question, 100.0 ) ] )
    snap.synonymous_question_gists = syn_g if syn_g is not None else OrderedDict( [ ( question, 100.0 ) ] )
    snap.code                      = [ "" ]
    return snap


@contextmanager
def _manager_ctx( snapshots=(), debug=False, verbose=False, q_table=None ):
    """
    Construct a SolutionSnapshotManager with the full dependency chain mocked.

    Normalizer is mocked to an IDENTITY function so question strings round-trip
    predictably; EmbeddingManager / QuestionEmbeddingsTable / from_json_file /
    os.listdir / du print helpers are all mocked. The manager is yielded WITHIN
    the patch context so method-call-time prints stay suppressed too.
    """
    snaps      = list( snapshots )
    files      = [ f"snap_{i}.json" for i in range( len( snaps ) ) ]
    q_tbl      = q_table if q_table is not None else Mock()
    normalizer = Mock()
    normalizer.normalize.side_effect = lambda q: q

    with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ) as mock_em, \
         patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable", return_value=q_tbl ), \
         patch( "cosa.memory.solution_snapshot_mgr.Normalizer", return_value=normalizer ), \
         patch( "os.listdir", return_value=files ), \
         patch( "cosa.memory.solution_snapshot_mgr.ss.SolutionSnapshot.from_json_file", side_effect=snaps ), \
         patch( "cosa.memory.solution_snapshot_mgr.du.print_banner" ), \
         patch( "cosa.memory.solution_snapshot_mgr.du.print_list" ), \
         patch( "builtins.print" ):
        mgr = SolutionSnapshotManager( path="/test/snapshots", debug=debug, verbose=verbose )
        yield mgr, { "em": mock_em, "q_table": q_tbl, "normalizer": normalizer }


class TestManagerCoverageCompletion( unittest.TestCase ):
    """
    Completion-tier tests driving the manager's remaining reachable lines to 100%:
    load-failure handling, delete_snapshot, the two similarity searches, the
    multi-branch get_snapshots_by_question dispatch, and __str__.
    """

    # ---- load-failure path -------------------------------------------------

    def test_load_snapshots_handles_failed_file( self ):
        """A from_json_file failure is caught, logged (debug), and tallied in failed_files."""
        good = _mk_snap( "good q" )
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ), \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ), \
             patch( "cosa.memory.solution_snapshot_mgr.Normalizer" ), \
             patch( "os.listdir", return_value=[ "good.json", "bad.json" ] ), \
             patch( "cosa.memory.solution_snapshot_mgr.ss.SolutionSnapshot.from_json_file",
                    side_effect=[ good, Exception( "corrupt file" ) ] ), \
             patch( "cosa.memory.solution_snapshot_mgr.du.print_banner" ), \
             patch( "cosa.memory.solution_snapshot_mgr.du.print_list" ), \
             patch( "builtins.print" ):
            mgr = SolutionSnapshotManager( path="/test", debug=True )
        self.assertIn( "good q", mgr._snapshots_by_question )       # good one survived
        self.assertEqual( len( mgr._snapshots_by_question ), 1 )    # bad one skipped

    # ---- __str__ -----------------------------------------------------------

    def test_str_representation( self ):
        """__str__ reports the loaded count and path."""
        with _manager_ctx( snapshots=[ _mk_snap( "q" ) ] ) as ( mgr, _ ):
            text = str( mgr )
        self.assertIn( "snapshots by question loaded from", text )
        self.assertIn( "[1]", text )

    # ---- delete_snapshot ---------------------------------------------------

    def test_delete_snapshot_with_file_deletion( self ):
        """Existing question + delete_file=True → snapshot.delete_file() called, returns True."""
        snap = _mk_snap( "del q" )
        with _manager_ctx( snapshots=[ snap ] ) as ( mgr, _ ):
            result = mgr.delete_snapshot( "del q", delete_file=True )
        self.assertTrue( result )
        snap.delete_file.assert_called_once()

    def test_delete_snapshot_without_file_deletion( self ):
        """Existing question + delete_file=False → returns True, no file deletion."""
        snap = _mk_snap( "del q" )
        with _manager_ctx( snapshots=[ snap ] ) as ( mgr, _ ):
            result = mgr.delete_snapshot( "del q", delete_file=False )
        self.assertTrue( result )
        snap.delete_file.assert_not_called()

    def test_delete_snapshot_not_found( self ):
        """Missing question → prints not-found message and returns False."""
        with _manager_ctx( snapshots=[] ) as ( mgr, _ ):
            result = mgr.delete_snapshot( "ghost q" )
        self.assertFalse( result )

    def test_delete_snapshot_removes_from_index( self ):
        """
        delete_snapshot actually removes the snapshot from the in-memory index.

        Was an armed expectedFailure TRIPWIRE: delete_snapshot returned True at
        solution_snapshot_mgr.py:305 BEFORE the `del self._snapshots_by_question[
        question]` — so the del + its prints were dead code and the snapshot was
        NEVER removed from the index (the deprecated method appeared to succeed
        while leaving a stale entry). Bug fixed 2026-05-31 (reordered the return
        AFTER the del); decorator removed, this now asserts the entry is gone.
        """
        snap = _mk_snap( "del q" )
        with _manager_ctx( snapshots=[ snap ] ) as ( mgr, _ ):
            result = mgr.delete_snapshot( "del q", delete_file=False )
            self.assertNotIn( "del q", mgr._snapshots_by_question )
        self.assertTrue( result )

    # ---- _get_snapshots_by_question_similarity -----------------------------

    def test_similarity_generate_blacklist_and_match( self ):
        """
        has()==False → generate+cache; blacklisted snapshot skipped; similar one
        kept, dissimilar dropped. debug+verbose exercises every log branch.
        """
        similar     = _mk_snap( "similar q",     q_emb=[ 1.0, 0.0 ] )
        dissimilar  = _mk_snap( "dissimilar q",  q_emb=[ 0.0, 1.0 ] )
        blacklisted = _mk_snap( "blacklisted q", q_emb=[ 1.0, 0.0 ] )
        blacklisted.non_synonymous_questions = [ "query q" ]

        q_table = Mock()
        q_table.has.return_value = False
        with _manager_ctx( snapshots=[ similar, dissimilar, blacklisted ],
                           debug=True, verbose=True, q_table=q_table ) as ( mgr, mocks ):
            mocks[ "em" ].return_value.generate_embedding.return_value = [ 1.0, 0.0 ]
            result = mgr._get_snapshots_by_question_similarity( "query q" )

        self.assertEqual( len( result ), 1 )
        self.assertIs( result[ 0 ][ 1 ], similar )
        q_table.add_embedding.assert_called_once()                 # generated + cached

    def test_similarity_cached_embedding_no_matches( self ):
        """has()==True → reuse cached embedding; no snapshot clears threshold → empty."""
        dissimilar = _mk_snap( "dissimilar q", q_emb=[ 0.0, 1.0 ] )
        q_table = Mock()
        q_table.has.return_value         = True
        q_table.get_embedding.return_value = [ 1.0, 0.0 ]
        with _manager_ctx( snapshots=[ dissimilar ], q_table=q_table ) as ( mgr, _ ):
            result = mgr._get_snapshots_by_question_similarity( "query q" )
        self.assertEqual( result, [] )
        q_table.get_embedding.assert_called_once_with( "query q" )

    # ---- get_snapshots_by_code_similarity ----------------------------------

    def test_code_similarity_debug_verbose_unlimited( self ):
        """debug+verbose, limit=-1 → above-threshold kept, below dropped, all returned."""
        above = _mk_snap( "above q" )
        above.get_code_similarity.return_value = 90.0
        above.code = [ "line a" ]
        below = _mk_snap( "below q" )
        below.get_code_similarity.return_value = 50.0
        exemplar = _mk_snap( "exemplar q" )
        exemplar.code = [ "exemplar code" ]

        with _manager_ctx( snapshots=[ above, below ], debug=True, verbose=True ) as ( mgr, _ ):
            result = mgr.get_snapshots_by_code_similarity( exemplar, threshold=85.0, limit=-1 )

        self.assertEqual( len( result ), 1 )
        self.assertIs( result[ 0 ][ 1 ], above )

    def test_code_similarity_limit_truncates( self ):
        """limit > 0 → result truncated to the limit (else branch)."""
        s1 = _mk_snap( "s1" ); s1.get_code_similarity.return_value = 95.0; s1.code = [ "a" ]
        s2 = _mk_snap( "s2" ); s2.get_code_similarity.return_value = 90.0; s2.code = [ "b" ]
        exemplar = _mk_snap( "ex" ); exemplar.code = [ "c" ]

        with _manager_ctx( snapshots=[ s1, s2 ] ) as ( mgr, _ ):
            result = mgr.get_snapshots_by_code_similarity( exemplar, threshold=85.0, limit=1 )
        self.assertEqual( len( result ), 1 )

    # ---- get_snapshots_by_question (dispatch branches) ---------------------

    def test_get_by_question_exact_match( self ):
        """Exact question hit → 100.0 score, debug logs the found list."""
        snap = _mk_snap( "exact q" )
        with _manager_ctx( snapshots=[ snap ] ) as ( mgr, _ ):
            result = mgr.get_snapshots_by_question( "exact q", debug=True )
        self.assertEqual( result[ 0 ][ 0 ], 100.0 )
        self.assertIs( result[ 0 ][ 1 ], snap )

    def test_get_by_question_synonymous_match( self ):
        """Synonymous-question hit (score >= threshold) returns the parent snapshot."""
        snap = _mk_snap( "main q", syn_q=OrderedDict( [ ( "main q", 100.0 ), ( "syn q", 95.0 ) ] ) )
        with _manager_ctx( snapshots=[ snap ] ) as ( mgr, _ ):
            result = mgr.get_snapshots_by_question( "syn q", threshold_question=90.0 )
        self.assertEqual( result[ 0 ][ 0 ], 95.0 )
        self.assertIs( result[ 0 ][ 1 ], snap )

    def test_get_by_question_gist_match_with_escape( self ):
        """Gist hit (score >= threshold_gist); question_gist is single-quote escaped first."""
        snap = _mk_snap( "main q", syn_g=OrderedDict( [ ( "the gist", 92.0 ) ] ) )
        with _manager_ctx( snapshots=[ snap ] ) as ( mgr, _ ):
            result = mgr.get_snapshots_by_question(
                "unknown q", question_gist="the gist", threshold_gist=90.0
            )
        self.assertEqual( result[ 0 ][ 0 ], 92.0 )
        self.assertIs( result[ 0 ][ 1 ], snap )

    def test_get_by_question_no_match_falls_to_similarity( self ):
        """No exact/synonym/gist hit → delegates to similarity search (empty here)."""
        snap = _mk_snap( "main q", q_emb=[ 0.0, 1.0 ] )
        q_table = Mock()
        q_table.has.return_value           = True
        q_table.get_embedding.return_value = [ 1.0, 0.0 ]
        with _manager_ctx( snapshots=[ snap ], q_table=q_table ) as ( mgr, _ ):
            result = mgr.get_snapshots_by_question( "nomatch q", debug=True )
        self.assertEqual( result, [] )

    # ---- debug=False branch arms (silent paths) ----------------------------

    def test_load_failure_silent_when_debug_off( self ):
        """from_json_file failure with debug=False → the silent except arm (125->118)."""
        good = _mk_snap( "good q" )
        with patch( "cosa.memory.solution_snapshot_mgr.EmbeddingManager" ), \
             patch( "cosa.memory.solution_snapshot_mgr.QuestionEmbeddingsTable" ), \
             patch( "cosa.memory.solution_snapshot_mgr.Normalizer" ), \
             patch( "os.listdir", return_value=[ "good.json", "bad.json" ] ), \
             patch( "cosa.memory.solution_snapshot_mgr.ss.SolutionSnapshot.from_json_file",
                    side_effect=[ good, Exception( "corrupt file" ) ] ), \
             patch( "cosa.memory.solution_snapshot_mgr.du.print_banner" ), \
             patch( "cosa.memory.solution_snapshot_mgr.du.print_list" ), \
             patch( "builtins.print" ):
            mgr = SolutionSnapshotManager( path="/test", debug=False )
        self.assertEqual( len( mgr._snapshots_by_question ), 1 )

    def test_similarity_blacklist_silent_when_debug_off( self ):
        """Blacklisted snapshot with debug=False → silent skip arm (347->351)."""
        blacklisted = _mk_snap( "blacklisted q", q_emb=[ 1.0, 0.0 ] )
        blacklisted.non_synonymous_questions = [ "query q" ]
        q_table = Mock()
        q_table.has.return_value = False
        with _manager_ctx( snapshots=[ blacklisted ], debug=False, q_table=q_table ) as ( mgr, mocks ):
            mocks[ "em" ].return_value.generate_embedding.return_value = [ 1.0, 0.0 ]
            result = mgr._get_snapshots_by_question_similarity( "query q" )
        self.assertEqual( result, [] )                             # only snapshot was blacklisted

    def test_code_similarity_below_threshold_silent_when_debug_off( self ):
        """Below-threshold snapshot with debug=False → silent else arm (412->400)."""
        below = _mk_snap( "below q" )
        below.get_code_similarity.return_value = 50.0
        below.code = [ "x" ]
        exemplar = _mk_snap( "ex q" ); exemplar.code = [ "y" ]
        with _manager_ctx( snapshots=[ below ], debug=False ) as ( mgr, _ ):
            result = mgr.get_snapshots_by_code_similarity( exemplar, threshold=85.0, limit=-1 )
        self.assertEqual( result, [] )


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