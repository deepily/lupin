"""
Unit tests for cosa.memory.file_based_solution_manager.FileBasedSolutionManager.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, memory lane). The module is
@DEPRECATED (file-based backend, superseded by LanceDBSolutionManager) but still
in-tree and subject to the Lupin-wide 100% coverage mandate.

These tests drive the FULL surface — construction + path validation, initialize/
reload/load, add/delete/get_snapshot_by_id, the four-tier get_snapshots_by_question
(exact → synonymous → gist → embedding-similarity fallback), code-similarity search,
gists/stats/health, and the serialization/loading internals — with every external
dependency (filesystem, json, EmbeddingManager, embedding provider, Normalizer,
QuestionEmbeddingsTable) mocked at the boundary. No real file or model I/O occurs.

TWO prod bugs were surfaced here and FIXED by Tiberius (2026-05-31) — the tripwires
that armed them have been de-armed into real passing tests:
  • #5 get_snapshot_by_id() iterated `self.solution_snapshots` (undefined NOWHERE) →
    AttributeError → except → always None. Fixed: now iterates
    `self._snapshots_by_question.values()` matching `.id_hash`
    (test_get_snapshot_by_id_returns_match / _returns_match_debug / test_absent_id_returns_none /
    test_query_error_returns_none cover the found / debug / not-found / error arcs).
  • #8 the class omitted the interface's `save_snapshot` @abstractmethod (had legacy
    `add_snapshot`) → UNINSTANTIABLE (ABCMeta TypeError). Fixed: `save_snapshot` now
    delegates to `add_snapshot` (test_direct_instantiation +
    test_save_snapshot_delegates_to_add_snapshot).
Module now at 100% (lines + branches), zero pragmas.
"""

import os
import json
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch, mock_open, call

from cosa.memory.file_based_solution_manager import FileBasedSolutionManager
from cosa.memory.solution_snapshot import SolutionSnapshot


_FBSM = "cosa.memory.file_based_solution_manager"


def _make_manager( debug=False, verbose=False, path="/test/solutions" ):
    """
    Construct a FileBasedSolutionManager with all construction-time deps mocked
    (EmbeddingManager, embedding provider, Normalizer) and os.path.exists forced
    True so the path-validation branch is a no-op. Deprecation warning suppressed.

    The Normalizer mock normalizes with identity (q → q) so test questions and
    dictionary keys line up predictably.
    """
    with patch( f"{_FBSM}.EmbeddingManager" ), \
         patch( f"{_FBSM}.get_embedding_provider" ), \
         patch( f"{_FBSM}.Normalizer" ) as MockNorm, \
         patch( f"{_FBSM}.os.path.exists", return_value=True ), \
         warnings.catch_warnings():
        warnings.simplefilter( "ignore" )
        MockNorm.return_value.normalize.side_effect = lambda q: q
        mgr = FileBasedSolutionManager( { "path": path }, debug=debug, verbose=verbose )
    return mgr


def _fake_snapshot( **overrides ):
    """SimpleNamespace standing in for a SolutionSnapshot (real __dict__ for serialization)."""
    base = dict(
        question                   = "what time is it",
        id_hash                    = "hash_abc",
        question_gist              = "time gist",
        synonymous_questions       = { "what is the time": 100.0 },
        synonymous_question_gists  = { "time gist": 100.0 },
        non_synonymous_questions   = [ "what is the weather" ],
        question_embedding         = [ 0.1, 0.2, 0.3, 0.4 ],
        code                       = [ "print( 'hi' )" ],
        code_embedding             = [ 0.5, 0.6, 0.7, 0.8 ],
    )
    base.update( overrides )
    ns = SimpleNamespace( **base )
    return ns


# ======================================================================
# Construction + path validation
# ======================================================================
class TestConstruction( unittest.TestCase ):

    def test_direct_instantiation( self ):
        # PROD BUG #8 FIXED (2026-05-31): FileBasedSolutionManager now implements the
        # interface-required `save_snapshot` (delegating to legacy add_snapshot), so it
        # is directly instantiable (previously ABCMeta raised TypeError on the missing
        # abstractmethod). This asserts the corrected contract.
        with patch( f"{_FBSM}.EmbeddingManager" ), \
             patch( f"{_FBSM}.get_embedding_provider" ), \
             patch( f"{_FBSM}.Normalizer" ), \
             patch( f"{_FBSM}.os.path.exists", return_value=True ), \
             warnings.catch_warnings():
            warnings.simplefilter( "ignore" )
            FileBasedSolutionManager( { "path": "/test/solutions" } )   # must not raise

    def test_missing_path_raises_keyerror( self ):
        with warnings.catch_warnings():
            warnings.simplefilter( "ignore" )
            with self.assertRaises( KeyError ):
                FileBasedSolutionManager( {} )

    def test_deprecation_warning_emitted( self ):
        with patch( f"{_FBSM}.EmbeddingManager" ), \
             patch( f"{_FBSM}.get_embedding_provider" ), \
             patch( f"{_FBSM}.Normalizer" ), \
             patch( f"{_FBSM}.os.path.exists", return_value=True ):
            with self.assertWarns( DeprecationWarning ):
                FileBasedSolutionManager( { "path": "/test/solutions" } )

    def test_debug_construction_sets_path( self ):
        mgr = _make_manager( debug=True )
        self.assertEqual( mgr.path, "/test/solutions" )
        self.assertFalse( mgr._initialized )

    def test_path_fallback_to_project_root( self ):
        # self.path missing → project-root-prefixed full_path exists → adopt it
        def exists( p ):
            return p == "/root/test/solutions"
        with patch( f"{_FBSM}.EmbeddingManager" ), \
             patch( f"{_FBSM}.get_embedding_provider" ), \
             patch( f"{_FBSM}.Normalizer" ), \
             patch( f"{_FBSM}.du.get_project_root", return_value="/root" ), \
             patch( f"{_FBSM}.os.path.exists", side_effect=exists ), \
             warnings.catch_warnings():
            warnings.simplefilter( "ignore" )
            mgr = FileBasedSolutionManager( { "path": "/test/solutions" } )
        self.assertEqual( mgr.path, "/root/test/solutions" )

    def test_path_invalid_raises_valueerror( self ):
        # neither self.path nor the project-root fallback exists → ValueError
        with patch( f"{_FBSM}.EmbeddingManager" ), \
             patch( f"{_FBSM}.get_embedding_provider" ), \
             patch( f"{_FBSM}.Normalizer" ), \
             patch( f"{_FBSM}.du.get_project_root", return_value="/root" ), \
             patch( f"{_FBSM}.os.path.exists", return_value=False ), \
             warnings.catch_warnings():
            warnings.simplefilter( "ignore" )
            with self.assertRaises( ValueError ):
                FileBasedSolutionManager( { "path": "/test/solutions" } )

    def test_path_fallback_get_project_root_error_raises_valueerror( self ):
        # the bare `except Exception` re-wraps any fallback failure as ValueError
        with patch( f"{_FBSM}.EmbeddingManager" ), \
             patch( f"{_FBSM}.get_embedding_provider" ), \
             patch( f"{_FBSM}.Normalizer" ), \
             patch( f"{_FBSM}.du.get_project_root", side_effect=RuntimeError( "no root" ) ), \
             patch( f"{_FBSM}.os.path.exists", return_value=False ), \
             warnings.catch_warnings():
            warnings.simplefilter( "ignore" )
            with self.assertRaises( ValueError ):
                FileBasedSolutionManager( { "path": "/test/solutions" } )


# ======================================================================
# initialize / reload / load_snapshots
# ======================================================================
class TestInitializeReloadLoad( unittest.TestCase ):

    def test_initialize_success( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr.load_snapshots = Mock( side_effect=lambda: setattr( mgr, "_snapshots_by_question", { "q": _fake_snapshot() } ) )
                mgr.initialize()
                self.assertTrue( mgr._initialized )
                mgr.load_snapshots.assert_called_once()

    def test_initialize_failure_resets_and_raises( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr._initialized = True
                mgr.load_snapshots = Mock( side_effect=Exception( "load boom" ) )
                with self.assertRaises( Exception ):
                    mgr.initialize()
                self.assertFalse( mgr._initialized )

    def test_reload_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with self.assertRaises( RuntimeError ):
            mgr.reload()

    def test_reload_success( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr._initialized = True
                mgr.load_snapshots = Mock( side_effect=lambda: setattr( mgr, "_snapshots_by_question", {} ) )
                mgr.reload()
                mgr.load_snapshots.assert_called_once()

    def test_load_snapshots_wires_all_indexes( self ):
        for debug, verbose in ( ( True, True ), ( False, False ) ):
            with self.subTest( debug=debug, verbose=verbose ):
                mgr = _make_manager( debug=debug, verbose=verbose )
                snap = _fake_snapshot()
                mgr._load_snapshots_by_question              = Mock( return_value={ "what time is it": snap } )
                mgr._load_snapshots_by_synonymous_questions  = Mock( return_value={ "what is the time": ( 100.0, snap ) } )
                mgr._load_snapshots_by_gist                  = Mock( return_value={ "time gist": ( 100.0, snap ) } )
                mgr._print_snapshots                         = Mock()
                with patch( f"{_FBSM}.QuestionEmbeddingsTable" ) as MockQET:
                    mgr.load_snapshots()
                self.assertEqual( mgr._snapshots_by_question, { "what time is it": snap } )
                self.assertEqual( mgr._snapshots_by_synonymous_questions, { "what is the time": ( 100.0, snap ) } )
                self.assertEqual( mgr._snapshots_by_question_gist, { "time gist": ( 100.0, snap ) } )
                MockQET.assert_called_once()
                if debug and verbose:
                    mgr._print_snapshots.assert_called_once()


# ======================================================================
# _load_snapshots_by_question / _by_gist / _by_synonymous_questions
# ======================================================================
class TestLoaders( unittest.TestCase ):

    def test_load_by_question_filters_and_loads( self ):
        mgr = _make_manager( debug=True, verbose=True )
        snap = _fake_snapshot( question="what time is it" )
        with patch( f"{_FBSM}.os.listdir", return_value=[ "good.json", "._hidden.json", "notes.txt" ] ), \
             patch.object( mgr, "_load_snapshot_from_file", return_value=snap ):
            out = mgr._load_snapshots_by_question()
        self.assertEqual( out, { "what time is it": snap } )

    def test_load_by_question_skips_failed_files( self ):
        mgr = _make_manager( debug=True )
        good = _fake_snapshot( question="good q" )
        def loader( path ):
            if path.endswith( "bad.json" ):
                raise ValueError( "corrupt" )
            return good
        with patch( f"{_FBSM}.os.listdir", return_value=[ "good.json", "bad.json" ] ), \
             patch.object( mgr, "_load_snapshot_from_file", side_effect=loader ):
            out = mgr._load_snapshots_by_question()
        self.assertEqual( out, { "good q": good } )          # bad file skipped, warning printed

    def test_load_by_gist_builds_index( self ):
        mgr = _make_manager( debug=True )
        snap = _fake_snapshot( synonymous_question_gists={ "g1": 95.0, "g2": 88.0 } )
        out = mgr._load_snapshots_by_gist( { "q": snap } )
        self.assertEqual( out, { "g1": ( 95.0, snap ), "g2": ( 88.0, snap ) } )

    def test_load_by_synonymous_builds_index( self ):
        mgr = _make_manager( debug=True )
        snap = _fake_snapshot( question="canonical q", synonymous_questions={ "syn a": 99.0, "canonical q": 100.0 } )
        out = mgr._load_snapshots_by_synonymous_questions( { "canonical q": snap } )
        self.assertEqual( out, { "syn a": ( 99.0, snap ), "canonical q": ( 100.0, snap ) } )

    def test_print_snapshots( self ):
        mgr = _make_manager()
        mgr._snapshots_by_question = { "q1": _fake_snapshot(), "q2": _fake_snapshot() }
        mgr._print_snapshots()                               # smoke: prints without error


# ======================================================================
# add_snapshot
# ======================================================================
class TestAddSnapshot( unittest.TestCase ):

    def _ready( self, debug=False ):
        mgr = _make_manager( debug=debug )
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        mgr._snapshots_by_synonymous_questions = {}
        mgr._snapshots_by_question_gist = {}
        mgr._persist_snapshot = Mock()
        return mgr

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with self.assertRaises( RuntimeError ):
            mgr.add_snapshot( _fake_snapshot() )

    def test_invalid_snapshot_raises( self ):
        mgr = self._ready()
        with self.assertRaises( ValueError ):
            mgr.add_snapshot( _fake_snapshot( question="" ) )

    def test_add_success_updates_all_indexes( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = self._ready( debug=debug )
                snap = _fake_snapshot(
                    question="what time is it",
                    synonymous_questions={ "what is the time": 100.0 },
                    synonymous_question_gists={ "time gist": 100.0 },
                )
                self.assertTrue( mgr.add_snapshot( snap ) )
                mgr._persist_snapshot.assert_called_once_with( snap )
                self.assertIs( mgr._snapshots_by_question[ "what time is it" ], snap )   # normalize=identity
                self.assertEqual( mgr._snapshots_by_synonymous_questions[ "what is the time" ], ( 100.0, snap ) )
                self.assertEqual( mgr._snapshots_by_question_gist[ "time gist" ], ( 100.0, snap ) )

    def test_add_persist_failure_returns_false( self ):
        mgr = self._ready( debug=True )
        mgr._persist_snapshot.side_effect = Exception( "disk full" )
        self.assertFalse( mgr.add_snapshot( _fake_snapshot() ) )

    def test_save_snapshot_delegates_to_add_snapshot( self ):
        # PROD BUG #8 FIXED: the interface-required save_snapshot delegates to add_snapshot.
        mgr = _make_manager()
        mgr.add_snapshot = Mock( return_value=True )
        snap = _fake_snapshot()
        self.assertTrue( mgr.save_snapshot( snap ) )
        mgr.add_snapshot.assert_called_once_with( snap )


# ======================================================================
# get_snapshot_by_id (incl. PROD BUG tripwire)
# ======================================================================
class TestGetSnapshotById( unittest.TestCase ):

    def test_not_initialized_returns_none( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr._initialized = False
                self.assertIsNone( mgr.get_snapshot_by_id( "abc" ) )

    def test_absent_id_returns_none( self ):
        # FIX-ROBUST: an ABSENT id_hash returns None — correct behavior BOTH pre-fix
        # (line 229 `self.solution_snapshots` is undefined → AttributeError → except →
        # None, covering 227/229/239-242 NOW) AND post-fix (loop exhausts → not-found
        # → None). Deliberately NOT a present id (that would ratify the bug + break the
        # suite when Tiberius patches :229). See module docstring + Tiberius DM 226684a9.
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr._initialized = True
                mgr._snapshots_by_question = { "q": _fake_snapshot( id_hash="present_hash" ) }
                self.assertIsNone( mgr.get_snapshot_by_id( "absent_hash" ) )

    def test_get_snapshot_by_id_returns_match( self ):
        # PROD BUG #5 FIXED (2026-05-31): :229 now iterates
        # self._snapshots_by_question.values() (was the undefined self.solution_snapshots),
        # so a present id_hash returns its snapshot. Covers lines 230-233.
        mgr = _make_manager()
        mgr._initialized = True
        snap = _fake_snapshot( id_hash="hash_abc" )
        mgr._snapshots_by_question = { "what time is it": snap }
        self.assertIs( mgr.get_snapshot_by_id( "hash_abc" ), snap )

    def test_returns_match_debug( self ):
        # debug=True + present id → the "Found snapshot ..." debug-print arm on the match path
        mgr = _make_manager( debug=True )
        mgr._initialized = True
        snap = _fake_snapshot( id_hash="hash_abc", question="what time is it" )
        mgr._snapshots_by_question = { "what time is it": snap }
        self.assertIs( mgr.get_snapshot_by_id( "hash_abc" ), snap )

    def test_query_error_returns_none( self ):
        # force an exception inside the try (the search iterable raises) → except → None.
        # Now reachable only via a genuine error since :229 no longer raises on every call.
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr._initialized = True
                broken = Mock()
                broken.values.side_effect = Exception( "store boom" )
                mgr._snapshots_by_question = broken
                self.assertIsNone( mgr.get_snapshot_by_id( "abc" ) )


# ======================================================================
# delete_snapshot
# ======================================================================
class TestDeleteSnapshot( unittest.TestCase ):

    def _ready( self, debug=False ):
        mgr = _make_manager( debug=debug )
        mgr._initialized = True
        snap = _fake_snapshot( question="what time is it" )
        mgr._snapshots_by_question = { "what time is it": snap }
        mgr._snapshots_by_synonymous_questions = { "syn": ( 100.0, snap ) }
        mgr._snapshots_by_question_gist = { "g": ( 100.0, snap ) }
        return mgr, snap

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with self.assertRaises( RuntimeError ):
            mgr.delete_snapshot( "q" )

    def test_empty_question_raises( self ):
        mgr, _ = self._ready()
        with self.assertRaises( ValueError ):
            mgr.delete_snapshot( "" )

    def test_not_found_returns_false( self ):
        mgr, _ = self._ready( debug=True )
        self.assertFalse( mgr.delete_snapshot( "no such question" ) )

    def test_delete_in_memory_only( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr, snap = self._ready( debug=debug )
                # synonymous/gist entries reference snap whose .question == the normalized key
                mgr._snapshots_by_synonymous_questions = { "syn": ( 100.0, snap ) }
                mgr._snapshots_by_question_gist        = { "g":   ( 100.0, snap ) }
                self.assertTrue( mgr.delete_snapshot( "what time is it" ) )
                self.assertNotIn( "what time is it", mgr._snapshots_by_question )
                # cleanup removes entries whose snap.question matches the (normalized) question
                self.assertEqual( mgr._snapshots_by_synonymous_questions, {} )
                self.assertEqual( mgr._snapshots_by_question_gist, {} )

    def test_delete_physical_removes_file( self ):
        mgr, snap = self._ready( debug=True )
        mgr._generate_file_path = Mock( return_value="/test/solutions/f.json" )
        with patch( f"{_FBSM}.os.path.exists", return_value=True ), \
             patch( f"{_FBSM}.os.remove" ) as mock_remove:
            self.assertTrue( mgr.delete_snapshot( "what time is it", delete_physical=True ) )
        mock_remove.assert_called_once_with( "/test/solutions/f.json" )

    def test_delete_physical_file_absent_skips_remove( self ):
        mgr, snap = self._ready()
        mgr._generate_file_path = Mock( return_value="/test/solutions/f.json" )
        with patch( f"{_FBSM}.os.path.exists", return_value=False ), \
             patch( f"{_FBSM}.os.remove" ) as mock_remove:
            self.assertTrue( mgr.delete_snapshot( "what time is it", delete_physical=True ) )
        mock_remove.assert_not_called()

    def test_delete_error_returns_false( self ):
        mgr, _ = self._ready( debug=True )
        # force an error after the existence check: normalize raises
        mgr._normalizer.normalize.side_effect = Exception( "boom" )
        self.assertFalse( mgr.delete_snapshot( "what time is it" ) )


# ======================================================================
# get_snapshots_by_question (4-tier)
# ======================================================================
class TestGetSnapshotsByQuestion( unittest.TestCase ):

    def _ready( self, debug=False ):
        mgr = _make_manager( debug=debug )
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        mgr._snapshots_by_synonymous_questions = {}
        mgr._snapshots_by_question_gist = {}
        return mgr

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with self.assertRaises( RuntimeError ):
            mgr.get_snapshots_by_question( "q" )

    def test_empty_question_raises( self ):
        mgr = self._ready()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_question( "" )

    def test_out_of_range_threshold_raises( self ):
        mgr = self._ready()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_question( "q", threshold_question=150.0 )

    def test_exact_match( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = self._ready( debug=debug )
                snap = _fake_snapshot()
                with patch.object( SolutionSnapshot, "remove_non_alphanumerics", lambda q: q ):
                    mgr._snapshots_by_question = { "what time is it": snap }
                    result = mgr.get_snapshots_by_question( "what time is it", debug=debug )
        self.assertEqual( result, [ ( 100.0, snap ) ] )

    def test_synonymous_match_above_threshold( self ):
        mgr = self._ready( debug=True )
        snap = _fake_snapshot()
        with patch.object( SolutionSnapshot, "remove_non_alphanumerics", lambda q: q ):
            mgr._snapshots_by_synonymous_questions = { "what time is it": ( 95.0, snap ) }
            result = mgr.get_snapshots_by_question( "what time is it", threshold_question=90.0 )
        self.assertEqual( result, [ ( 95.0, snap ) ] )

    def test_gist_match_above_threshold( self ):
        mgr = self._ready( debug=True )
        snap = _fake_snapshot()
        with patch.object( SolutionSnapshot, "remove_non_alphanumerics", lambda q: q ), \
             patch.object( SolutionSnapshot, "escape_single_quotes", lambda g: g ):
            mgr._snapshots_by_question_gist = { "the gist": ( 92.0, snap ) }
            result = mgr.get_snapshots_by_question( "unmatched q", question_gist="the gist", threshold_gist=90.0 )
        self.assertEqual( result, [ ( 92.0, snap ) ] )

    def test_similarity_fallback( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = self._ready( debug=debug )
                snap = _fake_snapshot()
                with patch.object( SolutionSnapshot, "remove_non_alphanumerics", lambda q: q ), \
                     patch.object( mgr, "_get_snapshots_by_question_similarity", return_value=[ ( 73.0, snap ) ] ) as sim:
                    result = mgr.get_snapshots_by_question( "novel question" )
                sim.assert_called_once()
        self.assertEqual( result, [ ( 73.0, snap ) ] )

    def test_no_results_branch( self ):
        mgr = self._ready( debug=True )
        with patch.object( SolutionSnapshot, "remove_non_alphanumerics", lambda q: q ), \
             patch.object( mgr, "_get_snapshots_by_question_similarity", return_value=[] ):
            result = mgr.get_snapshots_by_question( "novel question" )
        self.assertEqual( result, [] )

    def test_exception_reraises( self ):
        mgr = self._ready( debug=True )
        with patch.object( SolutionSnapshot, "remove_non_alphanumerics", side_effect=Exception( "boom" ) ):
            with self.assertRaises( Exception ):
                mgr.get_snapshots_by_question( "q" )


# ======================================================================
# get_snapshots_by_code_similarity
# ======================================================================
class TestCodeSimilarity( unittest.TestCase ):

    def _ready( self, debug=False, verbose=False ):
        mgr = _make_manager( debug=debug, verbose=verbose )
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        return mgr

    def _snap_with_score( self, question, score, **kw ):
        ns = _fake_snapshot( question=question, **kw )
        ns.get_code_similarity = lambda exemplar: score
        return ns

    def test_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with self.assertRaises( RuntimeError ):
            mgr.get_snapshots_by_code_similarity( _fake_snapshot() )

    def test_missing_code_embedding_raises( self ):
        mgr = self._ready()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_code_similarity( _fake_snapshot( code_embedding=[] ) )

    def test_bad_threshold_raises( self ):
        mgr = self._ready()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_code_similarity( _fake_snapshot(), threshold=200.0 )

    def test_filters_by_threshold_and_sorts( self ):
        mgr = self._ready( debug=True, verbose=True )
        hi  = self._snap_with_score( "hi q",  95.0 )
        mid = self._snap_with_score( "mid q", 88.0 )
        lo  = self._snap_with_score( "lo q",  40.0 )         # below threshold → excluded + debug print
        mgr._snapshots_by_question = { "a": mid, "b": hi, "c": lo }
        result = mgr.get_snapshots_by_code_similarity( _fake_snapshot(), threshold=85.0 )
        self.assertEqual( [ round( s, 1 ) for s, _ in result ], [ 95.0, 88.0 ] )   # sorted desc, lo dropped

    def test_limit_applied( self ):
        mgr = self._ready()
        a = self._snap_with_score( "a", 99.0 )
        b = self._snap_with_score( "b", 98.0 )
        c = self._snap_with_score( "c", 97.0 )
        mgr._snapshots_by_question = { "a": a, "b": b, "c": c }
        result = mgr.get_snapshots_by_code_similarity( _fake_snapshot(), threshold=10.0, limit=2 )
        self.assertEqual( len( result ), 2 )

    def test_limit_unlimited_returns_all( self ):
        mgr = self._ready()
        a = self._snap_with_score( "a", 99.0 )
        b = self._snap_with_score( "b", 98.0 )
        mgr._snapshots_by_question = { "a": a, "b": b }
        result = mgr.get_snapshots_by_code_similarity( _fake_snapshot(), threshold=10.0, limit=-1 )
        self.assertEqual( len( result ), 2 )

    def test_exception_reraises( self ):
        mgr = self._ready( debug=True )
        bad = _fake_snapshot()
        bad.get_code_similarity = Mock( side_effect=Exception( "boom" ) )
        mgr._snapshots_by_question = { "a": bad }
        with self.assertRaises( Exception ):
            mgr.get_snapshots_by_code_similarity( _fake_snapshot() )


# ======================================================================
# get_gists / get_stats / health_check
# ======================================================================
class TestGistsStatsHealth( unittest.TestCase ):

    def test_gists_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with self.assertRaises( RuntimeError ):
            mgr.get_gists()

    def test_gists_returns_keys( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                mgr._initialized = True
                mgr._snapshots_by_question_gist = { "g1": ( 1.0, None ), "g2": ( 1.0, None ) }
                self.assertEqual( sorted( mgr.get_gists() ), [ "g1", "g2" ] )

    def test_gists_error_returns_empty( self ):
        mgr = _make_manager( debug=True )
        mgr._initialized = True
        broken = Mock()
        broken.keys.side_effect = Exception( "boom" )
        mgr._snapshots_by_question_gist = broken
        self.assertEqual( mgr.get_gists(), [] )

    def test_stats_not_initialized_raises( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with self.assertRaises( RuntimeError ):
            mgr.get_stats()

    def test_stats_success_with_storage_size( self ):
        mgr = _make_manager( debug=True )
        mgr._initialized = True
        mgr._snapshots_by_question = { "q1": None, "q2": None }
        with patch( f"{_FBSM}.os.path.exists", return_value=True ), \
             patch( f"{_FBSM}.os.listdir", return_value=[ "a.json", "b.json", "notes.txt" ] ), \
             patch( f"{_FBSM}.os.path.isfile", return_value=True ), \
             patch( f"{_FBSM}.os.path.getsize", return_value=1024 * 1024 ):
            stats = mgr.get_stats()
        self.assertEqual( stats[ "total_snapshots" ], 2 )
        self.assertEqual( stats[ "backend_type" ], "file_based" )
        self.assertEqual( stats[ "storage_size_mb" ], 2.0 )  # 2 .json files × 1 MB (txt ignored)

    def test_stats_missing_path_zero_size( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = { "q": None }
        with patch( f"{_FBSM}.os.path.exists", return_value=False ):
            stats = mgr.get_stats()
        self.assertEqual( stats[ "storage_size_mb" ], 0.0 )

    def test_stats_error_returns_error_dict( self ):
        mgr = _make_manager( debug=True )
        mgr._initialized = True
        broken = Mock()
        broken.__len__ = Mock( side_effect=Exception( "boom" ) )
        mgr._snapshots_by_question = broken
        stats = mgr.get_stats()
        self.assertEqual( stats[ "status" ], "error" )

    def test_health_healthy( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = { "q": None }
        with patch( f"{_FBSM}.os.path.exists", return_value=True ), \
             patch( f"{_FBSM}.os.access", return_value=True ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "healthy" )
        self.assertEqual( health[ "snapshot_count" ], 1 )

    def test_health_unhealthy_path_missing_not_initialized( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with patch( f"{_FBSM}.os.path.exists", return_value=False ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "unhealthy" )

    def test_health_degraded_not_readable( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        with patch( f"{_FBSM}.os.path.exists", return_value=True ), \
             patch( f"{_FBSM}.os.access", return_value=False ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_health_degraded_not_writable( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        def access( path, mode ):
            return mode == os.R_OK                           # readable, not writable
        with patch( f"{_FBSM}.os.path.exists", return_value=True ), \
             patch( f"{_FBSM}.os.access", side_effect=access ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_health_degraded_when_not_initialized_but_path_ok( self ):
        mgr = _make_manager()
        mgr._initialized = False
        with patch( f"{_FBSM}.os.path.exists", return_value=True ), \
             patch( f"{_FBSM}.os.access", return_value=True ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_health_degraded_on_snapshot_access_error( self ):
        mgr = _make_manager()
        mgr._initialized = True
        broken = Mock()
        broken.__len__ = Mock( side_effect=Exception( "boom" ) )
        mgr._snapshots_by_question = broken
        with patch( f"{_FBSM}.os.path.exists", return_value=True ), \
             patch( f"{_FBSM}.os.access", return_value=True ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "degraded" )

    def test_health_unhealthy_on_top_level_exception( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( side_effect=Exception( "boom" ) )
        health = mgr.health_check()
        self.assertEqual( health[ "status" ], "unhealthy" )


# ======================================================================
# serialization internals
# ======================================================================
class TestSerialization( unittest.TestCase ):

    def test_persist_snapshot_writes_and_chmods( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                snap = _fake_snapshot()
                mgr._generate_file_path = Mock( return_value="/test/solutions/f.json" )
                mgr._snapshot_to_json   = Mock( return_value='{"a": 1}' )
                m = mock_open()
                with patch( f"{_FBSM}.open", m, create=True ), \
                     patch( f"{_FBSM}.os.chmod" ) as mock_chmod:
                    mgr._persist_snapshot( snap )
                m.assert_called_once_with( "/test/solutions/f.json", "w" )
                m().write.assert_called_once_with( '{"a": 1}' )
                mock_chmod.assert_called_once_with( "/test/solutions/f.json", 0o666 )

    def test_snapshot_to_json_excludes_sensitive_fields( self ):
        mgr = _make_manager()
        snap = _fake_snapshot( question="q" )
        snap.config_mgr        = object()                    # excluded
        snap._embedding_mgr    = object()                    # excluded
        snap.user_id           = "secret"                    # excluded
        snap.answer            = "kept"                       # kept
        json_str = mgr._snapshot_to_json( snap )
        data = json.loads( json_str )
        self.assertIn( "answer", data )
        self.assertNotIn( "config_mgr", data )
        self.assertNotIn( "_embedding_mgr", data )
        self.assertNotIn( "user_id", data )

    def test_load_snapshot_from_file( self ):
        for debug in ( True, False ):
            with self.subTest( debug=debug ):
                mgr = _make_manager( debug=debug )
                payload = { "question": "q", "answer": "a" }
                m = mock_open( read_data=json.dumps( payload ) )
                with patch( f"{_FBSM}.open", m, create=True ), \
                     patch( f"{_FBSM}.SolutionSnapshot" ) as MockSnap:
                    mgr._load_snapshot_from_file( "/test/solutions/f.json" )
                MockSnap.assert_called_once_with( question="q", answer="a" )


# ======================================================================
# _generate_file_path
# ======================================================================
class TestGenerateFilePath( unittest.TestCase ):

    def test_uses_existing_solution_file( self ):
        mgr = _make_manager()
        snap = _fake_snapshot()
        snap.solution_file = "preexisting.json"
        path = mgr._generate_file_path( snap )
        self.assertEqual( path, "/test/solutions/preexisting.json" )

    def test_generates_from_question_with_count_suffix( self ):
        mgr = _make_manager()
        snap = _fake_snapshot( question="what time is it" )   # no solution_file attr
        with patch( f"{_FBSM}.glob.glob", return_value=[ "a-0.json", "a-1.json" ] ):
            path = mgr._generate_file_path( snap )
        self.assertTrue( path.endswith( "-2.json" ) )         # count == 2 existing
        self.assertTrue( path.startswith( "/test/solutions/" ) )

    def test_path_without_trailing_slash_is_normalized( self ):
        mgr = _make_manager( path="/no/slash" )
        snap = _fake_snapshot( question="q" )
        with patch( f"{_FBSM}.glob.glob", return_value=[] ):
            path = mgr._generate_file_path( snap )
        self.assertTrue( path.startswith( "/no/slash/" ) )


# ======================================================================
# existence helpers
# ======================================================================
class TestExistenceHelpers( unittest.TestCase ):

    def test_question_exists( self ):
        mgr = _make_manager()
        mgr._snapshots_by_question = { "q": _fake_snapshot() }
        self.assertTrue( mgr._question_exists( "q" ) )
        self.assertFalse( mgr._question_exists( "nope" ) )

    def test_synonymous_question_exists( self ):
        mgr = _make_manager()
        mgr._snapshots_by_synonymous_questions = { "syn": ( 1.0, None ) }
        self.assertTrue( mgr._synonymous_question_exists( "syn" ) )
        self.assertFalse( mgr._synonymous_question_exists( "nope" ) )

    def test_question_gist_exists( self ):
        mgr = _make_manager()
        mgr._snapshots_by_question_gist = { "g": ( 1.0, None ) }
        self.assertTrue( mgr._question_gist_exists( "g" ) )
        self.assertFalse( mgr._question_gist_exists( "nope" ) )
        self.assertFalse( mgr._question_gist_exists( None ) )   # None short-circuits


# ======================================================================
# _get_snapshots_by_question_similarity
# ======================================================================
class TestQuestionSimilarity( unittest.TestCase ):

    def _ready( self, debug=False, verbose=False ):
        mgr = _make_manager( debug=debug, verbose=verbose )
        mgr._initialized = True
        mgr._question_embeddings_tbl = Mock()
        return mgr

    def test_generates_embedding_on_cache_miss( self ):
        mgr = self._ready( debug=True )
        mgr._question_embeddings_tbl.has.return_value = False
        mgr._embedding_provider.generate_embedding.return_value = [ 0.1, 0.2 ]
        snap = _fake_snapshot( question="snap q", non_synonymous_questions=[] )
        mgr._snapshots_by_question = { "snap q": snap }
        with patch.object( SolutionSnapshot, "get_embedding_similarity", return_value=80.0 ):
            result = mgr._get_snapshots_by_question_similarity( "query q", limit=7 )
        mgr._embedding_provider.generate_embedding.assert_called_once_with( "query q", content_type="prose" )
        mgr._question_embeddings_tbl.add_embedding.assert_called_once()
        self.assertEqual( round( result[ 0 ][ 0 ], 1 ), 80.0 )

    def test_uses_cached_embedding_on_hit( self ):
        mgr = self._ready( debug=True )
        mgr._question_embeddings_tbl.has.return_value = True
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.3, 0.4 ]
        snap = _fake_snapshot( question="snap q", non_synonymous_questions=[] )
        mgr._snapshots_by_question = { "snap q": snap }
        with patch.object( SolutionSnapshot, "get_embedding_similarity", return_value=70.0 ):
            result = mgr._get_snapshots_by_question_similarity( "query q", limit=7 )
        mgr._embedding_provider.generate_embedding.assert_not_called()
        self.assertEqual( round( result[ 0 ][ 0 ], 1 ), 70.0 )

    def test_gist_embedding_generated_and_cached( self ):
        mgr = self._ready( debug=True, verbose=True )
        # question cached; gist NOT cached → generated
        def has( text ):
            return text == "query q"
        mgr._question_embeddings_tbl.has.side_effect = has
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.3, 0.4 ]
        mgr._embedding_provider.generate_embedding.return_value = [ 0.9, 0.8 ]
        snap = _fake_snapshot( question="snap q", non_synonymous_questions=[] )
        mgr._snapshots_by_question = { "snap q": snap }
        with patch.object( SolutionSnapshot, "get_embedding_similarity", return_value=60.0 ):
            mgr._get_snapshots_by_question_similarity( "query q", question_gist="the gist", limit=7 )
        # gist embedding generated (not cached) + stored
        mgr._embedding_provider.generate_embedding.assert_called_once_with( "the gist", content_type="prose" )

    def test_gist_embedding_cached_branch( self ):
        mgr = self._ready( debug=True, verbose=True )
        mgr._question_embeddings_tbl.has.return_value = True   # both question + gist cached
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.3, 0.4 ]
        snap = _fake_snapshot( question="snap q", non_synonymous_questions=[] )
        mgr._snapshots_by_question = { "snap q": snap }
        with patch.object( SolutionSnapshot, "get_embedding_similarity", return_value=55.0 ):
            mgr._get_snapshots_by_question_similarity( "query q", question_gist="the gist", limit=7 )
        mgr._embedding_provider.generate_embedding.assert_not_called()

    def test_excludes_blacklisted_non_synonymous( self ):
        mgr = self._ready( debug=True )
        mgr._question_embeddings_tbl.has.return_value = True
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.3, 0.4 ]
        # snap blacklists the query → skipped via `continue`
        blacklister = _fake_snapshot( question="snap q", non_synonymous_questions=[ "query q" ] )
        keeper      = _fake_snapshot( question="keep q", non_synonymous_questions=[] )
        mgr._snapshots_by_question = { "snap q": blacklister, "keep q": keeper }
        with patch.object( SolutionSnapshot, "get_embedding_similarity", return_value=50.0 ):
            result = mgr._get_snapshots_by_question_similarity( "query q", limit=7 )
        questions = [ snap.question for _, snap in result ]
        self.assertIn( "keep q", questions )
        self.assertNotIn( "snap q", questions )

    def test_no_results_debug_branch( self ):
        mgr = self._ready( debug=True )
        mgr._question_embeddings_tbl.has.return_value = True
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.3, 0.4 ]
        mgr._snapshots_by_question = {}                       # nothing to compare → empty
        with patch.object( SolutionSnapshot, "get_embedding_similarity", return_value=50.0 ):
            result = mgr._get_snapshots_by_question_similarity( "query q", limit=7 )
        self.assertEqual( result, [] )

    def test_limit_truncates( self ):
        mgr = self._ready()
        mgr._question_embeddings_tbl.has.return_value = True
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.3, 0.4 ]
        snaps = { f"q{i}": _fake_snapshot( question=f"q{i}", non_synonymous_questions=[] ) for i in range( 5 ) }
        mgr._snapshots_by_question = snaps
        with patch.object( SolutionSnapshot, "get_embedding_similarity", return_value=50.0 ):
            result = mgr._get_snapshots_by_question_similarity( "query q", limit=3 )
        self.assertEqual( len( result ), 3 )


class TestFileBasedDebugFalseArcs( unittest.TestCase ):
    """
    debug=False / verbose-off / loop-no-match companion passes. The classes above
    exercise the methods with debug ON (and some loop branches one-sided); these runs
    close the corresponding FALSE-side `if self.debug:` arcs, the no-match loop arcs,
    and the verbose-off arc so both sides of every guard are covered.
    """

    # ---- add_snapshot ----
    def test_add_exception_no_debug( self ):
        mgr = _make_manager()                                # debug False
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        mgr._snapshots_by_synonymous_questions = {}
        mgr._snapshots_by_question_gist = {}
        mgr._persist_snapshot = Mock( side_effect=Exception( "boom" ) )
        self.assertFalse( mgr.add_snapshot( _fake_snapshot() ) )

    # ---- delete_snapshot ----
    def test_delete_not_found_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        mgr._snapshots_by_synonymous_questions = {}
        mgr._snapshots_by_question_gist = {}
        self.assertFalse( mgr.delete_snapshot( "nope" ) )

    def test_delete_cleanup_no_match_arc( self ):
        # synonymous/gist entries that reference OTHER snapshots → the `if snap.question
        # == question` FALSE arc (entries are NOT removed).
        mgr = _make_manager()
        mgr._initialized = True
        target = _fake_snapshot( question="delete me" )
        other  = _fake_snapshot( question="keep me" )
        mgr._snapshots_by_question = { "delete me": target }
        mgr._snapshots_by_synonymous_questions = { "syn_other": ( 100.0, other ) }
        mgr._snapshots_by_question_gist        = { "gist_other": ( 100.0, other ) }
        self.assertTrue( mgr.delete_snapshot( "delete me" ) )
        # other-referencing entries survive (no-match arc)
        self.assertIn( "syn_other", mgr._snapshots_by_synonymous_questions )
        self.assertIn( "gist_other", mgr._snapshots_by_question_gist )

    def test_delete_error_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = { "q": _fake_snapshot() }
        mgr._normalizer.normalize.side_effect = Exception( "boom" )
        self.assertFalse( mgr.delete_snapshot( "q" ) )

    # ---- get_snapshots_by_question (debug off) ----
    def test_synonymous_match_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        mgr._snapshots_by_question_gist = {}
        snap = _fake_snapshot()
        with patch.object( SolutionSnapshot, "remove_non_alphanumerics", lambda q: q ):
            mgr._snapshots_by_synonymous_questions = { "q": ( 95.0, snap ) }
            result = mgr.get_snapshots_by_question( "q", threshold_question=90.0 )
        self.assertEqual( result, [ ( 95.0, snap ) ] )

    def test_gist_match_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        mgr._snapshots_by_synonymous_questions = {}
        snap = _fake_snapshot()
        with patch.object( SolutionSnapshot, "remove_non_alphanumerics", lambda q: q ), \
             patch.object( SolutionSnapshot, "escape_single_quotes", lambda g: g ):
            mgr._snapshots_by_question_gist = { "g": ( 92.0, snap ) }
            result = mgr.get_snapshots_by_question( "q", question_gist="g", threshold_gist=90.0 )
        self.assertEqual( result, [ ( 92.0, snap ) ] )

    def test_no_results_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        mgr._snapshots_by_synonymous_questions = {}
        mgr._snapshots_by_question_gist = {}
        with patch.object( SolutionSnapshot, "remove_non_alphanumerics", lambda q: q ), \
             patch.object( mgr, "_get_snapshots_by_question_similarity", return_value=[] ):
            self.assertEqual( mgr.get_snapshots_by_question( "novel" ), [] )

    def test_exception_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = {}
        with patch.object( SolutionSnapshot, "remove_non_alphanumerics", side_effect=Exception( "boom" ) ):
            with self.assertRaises( Exception ):
                mgr.get_snapshots_by_question( "q" )

    # ---- code similarity (debug off) ----
    def test_code_sim_below_threshold_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        below = _fake_snapshot( question="below q" )
        below.get_code_similarity = lambda ex: 40.0          # below 85 → else arc, dbg off
        mgr._snapshots_by_question = { "a": below }
        self.assertEqual( mgr.get_snapshots_by_code_similarity( _fake_snapshot(), threshold=85.0 ), [] )

    def test_code_sim_exception_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        bad = _fake_snapshot()
        bad.get_code_similarity = Mock( side_effect=Exception( "boom" ) )
        mgr._snapshots_by_question = { "a": bad }
        with self.assertRaises( Exception ):
            mgr.get_snapshots_by_code_similarity( _fake_snapshot() )

    # ---- gists error (debug off) ----
    def test_gists_error_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        broken = Mock()
        broken.keys.side_effect = Exception( "boom" )
        mgr._snapshots_by_question_gist = broken
        self.assertEqual( mgr.get_gists(), [] )

    # ---- stats (json-but-not-file arc + except debug off) ----
    def test_stats_json_not_isfile_arc( self ):
        mgr = _make_manager()
        mgr._initialized = True
        mgr._snapshots_by_question = { "q": None }
        with patch( f"{_FBSM}.os.path.exists", return_value=True ), \
             patch( f"{_FBSM}.os.listdir", return_value=[ "a.json" ] ), \
             patch( f"{_FBSM}.os.path.isfile", return_value=False ), \
             patch( f"{_FBSM}.os.path.getsize", return_value=999 ) as gs:
            stats = mgr.get_stats()
        gs.assert_not_called()                               # isfile False → getsize skipped
        self.assertEqual( stats[ "storage_size_mb" ], 0.0 )

    def test_stats_error_no_debug( self ):
        mgr = _make_manager()
        mgr._initialized = True
        broken = Mock()
        broken.__len__ = Mock( side_effect=Exception( "boom" ) )
        mgr._snapshots_by_question = broken
        self.assertEqual( mgr.get_stats()[ "status" ], "error" )

    # ---- load_snapshots verbose-off-while-debug-on arc ----
    def test_load_snapshots_debug_without_verbose( self ):
        mgr = _make_manager( debug=True, verbose=False )
        mgr._load_snapshots_by_question             = Mock( return_value={} )
        mgr._load_snapshots_by_synonymous_questions = Mock( return_value={} )
        mgr._load_snapshots_by_gist                 = Mock( return_value={} )
        mgr._print_snapshots                        = Mock()
        with patch( f"{_FBSM}.QuestionEmbeddingsTable" ):
            mgr.load_snapshots()
        mgr._print_snapshots.assert_not_called()             # verbose False → no print

    # ---- loaders (debug off) ----
    def test_load_by_question_no_debug( self ):
        mgr = _make_manager()                                # debug False
        snap = _fake_snapshot( question="q" )
        with patch( f"{_FBSM}.os.listdir", return_value=[ "good.json" ] ), \
             patch.object( mgr, "_load_snapshot_from_file", return_value=snap ):
            self.assertEqual( mgr._load_snapshots_by_question(), { "q": snap } )

    def test_load_by_question_failed_no_debug( self ):
        mgr = _make_manager()
        with patch( f"{_FBSM}.os.listdir", return_value=[ "bad.json" ] ), \
             patch.object( mgr, "_load_snapshot_from_file", side_effect=ValueError( "x" ) ):
            self.assertEqual( mgr._load_snapshots_by_question(), {} )

    def test_load_by_gist_no_debug( self ):
        mgr = _make_manager()
        snap = _fake_snapshot( synonymous_question_gists={ "g": 90.0 } )
        self.assertEqual( mgr._load_snapshots_by_gist( { "q": snap } ), { "g": ( 90.0, snap ) } )

    def test_load_by_synonymous_no_debug( self ):
        mgr = _make_manager()
        snap = _fake_snapshot( question="c", synonymous_questions={ "s": 90.0 } )
        self.assertEqual( mgr._load_snapshots_by_synonymous_questions( { "c": snap } ), { "s": ( 90.0, snap ) } )

    # ---- _get_snapshots_by_question_similarity (debug off) ----
    def test_similarity_gist_cached_no_debug( self ):
        mgr = _make_manager()                                # debug False
        mgr._initialized = True
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.has.return_value = True
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.3, 0.4 ]
        snap = _fake_snapshot( question="snap q", non_synonymous_questions=[] )
        mgr._snapshots_by_question = { "snap q": snap }
        with patch.object( SolutionSnapshot, "get_embedding_similarity", return_value=55.0 ):
            mgr._get_snapshots_by_question_similarity( "query q", question_gist="g", limit=7 )
        mgr._embedding_provider.generate_embedding.assert_not_called()

    def test_similarity_blacklist_no_debug( self ):
        mgr = _make_manager()                                # debug False
        mgr._initialized = True
        mgr._question_embeddings_tbl = Mock()
        mgr._question_embeddings_tbl.has.return_value = True
        mgr._question_embeddings_tbl.get_embedding.return_value = [ 0.3, 0.4 ]
        blk = _fake_snapshot( question="snap q", non_synonymous_questions=[ "query q" ] )
        mgr._snapshots_by_question = { "snap q": blk }
        with patch.object( SolutionSnapshot, "get_embedding_similarity", return_value=50.0 ):
            self.assertEqual( mgr._get_snapshots_by_question_similarity( "query q", limit=7 ), [] )


if __name__ == "__main__":
    unittest.main()
