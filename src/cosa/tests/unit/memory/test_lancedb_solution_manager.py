"""
Unit tests for cosa.memory.lancedb_solution_manager.LanceDBSolutionManager.

REWRITTEN 2026-05-31 by Sam 🎙️ (memory takeover, CoSA coverage campaign) — the
prior tests targeted a stale API: they constructed the manager with no `config`
(now required), patched module-level `CanonicalSynonymsTable` / `Normalizer`
(those are LOCAL imports inside get_snapshots_by_question, lazily bound to the
`_canonical_synonyms` / `_normalizer` instance attrs), and asserted a bare-
snapshot return shape (the method actually returns `[(score, snapshot)]` tuples
behind an `is_initialized()` gate, raising ValueError on empty input).

These tests drive the CURRENT hierarchical search (Level 1 verbatim → Level 2
normalized → Level 4 similarity) by injecting mock collaborators directly onto
the instance — legitimate unit isolation, not over-mocking of the unit under
test. Construction deps (QuestionEmbeddingsTable, db-path resolution) are mocked
so no real LanceDB/embedding I/O occurs. Reviewed by Mr. Radio (no self-audit).
"""
import os
import unittest
from unittest.mock import Mock, MagicMock, patch

from cosa.memory.lancedb_solution_manager import LanceDBSolutionManager


_CONFIG = { "table_name": "test_solutions", "db_path": "/tmp/__sam_lancedb_test__", "storage backend": "local" }


def _make_manager( debug=False, verbose=False ):
    """
    Construct a LanceDBSolutionManager with its construction-time deps mocked
    (QuestionEmbeddingsTable + db-path resolution), then mark it initialized
    with a mock table so the search/retrieval gates pass.
    """
    with patch( "cosa.memory.lancedb_solution_manager.QuestionEmbeddingsTable" ), \
         patch.object( LanceDBSolutionManager, "_resolve_db_path", return_value=_CONFIG[ "db_path" ] ):
        mgr = LanceDBSolutionManager( _CONFIG, debug=debug, verbose=verbose )
    mgr._initialized = True
    mgr.is_initialized = Mock( return_value=True )
    mgr._table = MagicMock()
    return mgr


class TestHierarchicalSearch( unittest.TestCase ):
    """get_snapshots_by_question — Level 1/2/4 hierarchy + early exits."""

    def test_level1_verbatim_early_exit( self ):
        """A Level-1 verbatim hit returns [(100.0, snapshot)] and skips normalize/Level-2."""
        mgr = _make_manager()
        canonical = Mock()
        canonical.find_exact_verbatim.return_value = "snap_id_1"
        normalizer = Mock()
        mgr._canonical_synonyms = canonical
        mgr._normalizer = normalizer

        snap = Mock( question="What time is it?" )
        mgr.get_snapshot_by_id = Mock( return_value=snap )

        result = mgr.get_snapshots_by_question( "What time is it?" )

        canonical.find_exact_verbatim.assert_called_once_with( "What time is it?" )
        normalizer.normalize.assert_not_called()                 # early exit before Level 2
        canonical.find_exact_normalized.assert_not_called()
        self.assertEqual( result, [ ( 100.0, snap ) ] )

    def test_level2_normalized_early_exit( self ):
        """No verbatim hit → normalize → Level-2 normalized hit returns [(100.0, snapshot)]."""
        mgr = _make_manager()
        canonical = Mock()
        canonical.find_exact_verbatim.return_value = None
        canonical.find_exact_normalized.return_value = "snap_id_2"
        normalizer = Mock()
        normalizer.normalize.return_value = "what time be it"
        mgr._canonical_synonyms = canonical
        mgr._normalizer = normalizer

        snap = Mock( question="what time be it" )
        mgr.get_snapshot_by_id = Mock( return_value=snap )

        result = mgr.get_snapshots_by_question( "What time is it?" )

        canonical.find_exact_verbatim.assert_called_once_with( "What time is it?" )
        normalizer.normalize.assert_called_once_with( "What time is it?" )
        canonical.find_exact_normalized.assert_called_once_with( "what time be it" )
        self.assertEqual( result, [ ( 100.0, snap ) ] )

    def test_level1_ghost_snapshot_auto_heals( self ):
        """A Level-1 synonym pointing at a missing snapshot triggers delete_by_snapshot_id."""
        mgr = _make_manager()
        canonical = Mock()
        canonical.find_exact_verbatim.return_value = "ghost_id"
        canonical.find_exact_normalized.return_value = None
        normalizer = Mock()
        normalizer.normalize.return_value = "norm"
        mgr._canonical_synonyms = canonical
        mgr._normalizer = normalizer
        mgr.get_snapshot_by_id = Mock( return_value=None )       # ghost: id resolves to nothing

        mgr.get_snapshots_by_question( "ghost question" )

        canonical.delete_by_snapshot_id.assert_any_call( "ghost_id" )

    def test_local_cache_exact_match( self ):
        """A verbatim hit in the in-memory cache returns [(100.0, snapshot)] via _record_to_snapshot."""
        mgr = _make_manager()
        mgr._canonical_synonyms = False                          # unavailable → skip Levels 1/2
        mgr._normalizer = False
        mgr._question_lookup = { "cached q": "id_hash_9" }
        mgr._id_lookup = { "id_hash_9": { "stub": "record" } }
        snap = Mock( question="cached q" )
        mgr._record_to_snapshot = Mock( return_value=snap )

        result = mgr.get_snapshots_by_question( "cached q" )

        mgr._record_to_snapshot.assert_called_once_with( { "stub": "record" } )
        self.assertEqual( result, [ ( 100.0, snap ) ] )


class TestGuards( unittest.TestCase ):
    """Initialization + input-validation gates."""

    def test_not_initialized_raises_runtime_error( self ):
        mgr = _make_manager()
        mgr.is_initialized = Mock( return_value=False )
        with self.assertRaises( RuntimeError ):
            mgr.get_snapshots_by_question( "anything" )

    def test_empty_question_raises_value_error( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_question( "" )

    def test_none_question_raises_value_error( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_question( None )

    def test_out_of_range_threshold_raises_value_error( self ):
        mgr = _make_manager()
        with self.assertRaises( ValueError ):
            mgr.get_snapshots_by_question( "q", threshold_question=150.0 )


class TestGetSnapshotById( unittest.TestCase ):
    """get_snapshot_by_id — query, not-found, not-initialized, error."""

    def test_returns_snapshot_when_found( self ):
        mgr = _make_manager()
        record = { "id_hash": "abc", "question": "Q?", "answer": "A" }
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = [ record ]
        snap = Mock( question="Q?" )
        mgr._record_to_snapshot = Mock( return_value=snap )

        result = mgr.get_snapshot_by_id( "abc" )
        self.assertIs( result, snap )
        mgr._record_to_snapshot.assert_called_once_with( record )

    def test_returns_none_when_not_found( self ):
        mgr = _make_manager()
        mgr._table.search.return_value.where.return_value.limit.return_value.to_list.return_value = []
        self.assertIsNone( mgr.get_snapshot_by_id( "missing" ) )

    def test_returns_none_when_not_initialized( self ):
        mgr = _make_manager()
        mgr._initialized = False
        self.assertIsNone( mgr.get_snapshot_by_id( "abc" ) )

    def test_returns_none_on_query_error( self ):
        mgr = _make_manager()
        mgr._table.search.side_effect = RuntimeError( "lancedb boom" )
        self.assertIsNone( mgr.get_snapshot_by_id( "abc" ) )


if __name__ == "__main__":
    unittest.main()
