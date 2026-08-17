"""
Unit tests for cosa.memory.canonical_synonyms_table.CanonicalSynonymsTable.

REWRITTEN 2026-08-17 by Pocholo 📣 (LanceDB total-removal sweep, Lane A, rows
5ff7b8f5 / 8098838f). The LanceDB path is gone, and with it the ctor's
db_path/connect/validate/create/open branches, _get_schema, the pandas
exact-match scans and _update_usage_stats (a LanceDB-era stub that only the
deleted scans called). The tests that covered them were testing deleted code
and were DELETED, not skipped.

What remains is the Postgres path, which was already the only one running in
every INI section: a ctor that builds the normalizer + embedding manager, and
five methods that open a short-lived get_db() session and delegate to
CanonicalSynonymRepository — with normalization and embedding generation kept
here in the memory layer.
"""

import contextlib
import unittest
from unittest.mock import Mock, MagicMock, patch

from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable


def _make( debug=False, verbose=False ):
    """Build a CanonicalSynonymsTable with its ctor deps mocked. Returns (table, normalizer, emb)."""
    cfg = Mock()
    cfg.get.side_effect = lambda key, default=None, return_type=None: {
        "embedding dimensions": "768",
    }.get( key, default )
    normalizer = Mock()
    normalizer.normalize.side_effect = lambda q: q.lower()
    emb = Mock()
    emb.generate_embedding.return_value = [ 0.1 ] * 768
    with patch( "cosa.memory.canonical_synonyms_table.ConfigurationManager", return_value=cfg ), \
         patch( "cosa.memory.canonical_synonyms_table.Normalizer", return_value=normalizer ), \
         patch( "cosa.memory.canonical_synonyms_table.EmbeddingManager", return_value=emb ):
        table = CanonicalSynonymsTable( debug=debug, verbose=verbose )
    return table, normalizer, emb


def _patch_repo():
    """Patch get_db (ctx mgr → mock session) + the repo class; return (repo_instance, ctx, repo_ctx)."""
    session   = MagicMock()
    repo_inst = MagicMock()

    @contextlib.contextmanager
    def fake_get_db():
        yield session

    ctx      = patch( "cosa.rest.db.database.get_db", fake_get_db )
    repo_ctx = patch( "cosa.rest.db.repositories.canonical_synonym_repository.CanonicalSynonymRepository",
                      return_value=repo_inst )
    return repo_inst, ctx, repo_ctx


class TestInit( unittest.TestCase ):
    """__init__ — text processors + embedding dimension; opens nothing."""

    def test_wires_dependencies( self ):
        table, normalizer, emb = _make( debug=True, verbose=True )
        self.assertIs( table._normalizer, normalizer )
        self.assertIs( table._embedding_manager, emb )
        self.assertEqual( table._embedding_dim, 768 )
        self.assertTrue( table.debug )
        self.assertTrue( table.verbose )


class TestFindExact( unittest.TestCase ):
    """The find_exact_* family routes to the matching repository finder."""

    def test_verbatim_normalized_gist( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.find_exact_verbatim.return_value   = "snapV"
        repo.find_exact_normalized.return_value = "snapN"
        repo.find_exact_gist.return_value       = "snapG"
        with ctx, repo_ctx:
            self.assertEqual( table.find_exact_verbatim( "q" ), "snapV" )
            self.assertEqual( table.find_exact_normalized( "q" ), "snapN" )
            self.assertEqual( table.find_exact_gist( "q" ), "snapG" )

    def test_error_returns_none_debug_on( self ):
        table, _, _ = _make( debug=True )
        repo, ctx, repo_ctx = _patch_repo()
        repo.find_exact_verbatim.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "builtins.print" ) as p:
            self.assertIsNone( table.find_exact_verbatim( "q" ) )
        p.assert_called_once()

    def test_error_returns_none_debug_off( self ):
        table, _, _ = _make( debug=False )
        repo, ctx, repo_ctx = _patch_repo()
        repo.find_exact_verbatim.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx:
            self.assertIsNone( table.find_exact_verbatim( "q" ) )


class TestAddSynonym( unittest.TestCase ):
    """add_synonym() — three-level generation, dedupe, error swallow."""

    def test_inserts_when_new( self ):
        table, normalizer, emb = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.find_exact_verbatim.return_value = None      # not a duplicate
        with ctx, repo_ctx, \
             patch( "cosa.memory.canonical_synonyms_table.du.get_current_datetime", return_value="TS" ), \
             patch( "cosa.memory.canonical_synonyms_table.du.get_timestamp_ms", return_value="NOW" ):
            self.assertTrue( table.add_synonym( "snap1", "How Are You?", confidence_score=90.0, source="test" ) )
        kw = repo.add_synonym.call_args.kwargs
        self.assertEqual( kw[ "snapshot_id" ], "snap1" )
        self.assertEqual( kw[ "question_normalized" ], "how are you?" )    # normalizer.lower()
        self.assertEqual( kw[ "question_gist" ], "how are you?" )
        self.assertEqual( kw[ "embedding_verbatim" ], [ 0.1 ] * 768 )
        self.assertEqual( kw[ "confidence_score" ], 90.0 )
        self.assertEqual( kw[ "source" ], "test" )
        self.assertEqual( kw[ "id" ], "snap1_TS" )
        self.assertEqual( emb.generate_embedding.call_count, 3 )

    def test_skips_duplicate( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.find_exact_verbatim.return_value = "existing"    # duplicate
        with ctx, repo_ctx:
            self.assertFalse( table.add_synonym( "snap1", "q" ) )
        repo.add_synonym.assert_not_called()

    def test_error_returns_false( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.find_exact_verbatim.return_value = None
        repo.add_synonym.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "cosa.memory.canonical_synonyms_table.du.print_stack_trace" ) as trace:
            self.assertFalse( table.add_synonym( "snap1", "q" ) )
        trace.assert_called_once()


class TestDeleteBySnapshotId( unittest.TestCase ):
    """delete_by_snapshot_id() — count-through, zero on error."""

    def test_delegates( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.delete_by_snapshot_id.return_value = 3
        with ctx, repo_ctx:
            self.assertEqual( table.delete_by_snapshot_id( "snap1" ), 3 )

    def test_error_returns_zero( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.delete_by_snapshot_id.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "cosa.memory.canonical_synonyms_table.du.print_stack_trace" ):
            self.assertEqual( table.delete_by_snapshot_id( "snap1" ), 0 )


class TestGetStatistics( unittest.TestCase ):
    """get_statistics() — shape mapping + error dict on both debug arcs."""

    def test_maps_shape( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_statistics.return_value = { "total_synonyms": 5, "total_usage_count": 12 }
        with ctx, repo_ctx:
            stats = table.get_statistics()
        self.assertEqual( stats, { "total_synonyms": 5, "total_usage": 12, "top_used": [] } )

    def test_error_returns_error_dict_debug_on( self ):
        table, _, _ = _make( debug=True )
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_statistics.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "builtins.print" ) as p:
            self.assertIn( "error", table.get_statistics() )
        p.assert_called_once()

    def test_error_returns_error_dict_debug_off( self ):
        table, _, _ = _make( debug=False )
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_statistics.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx:
            self.assertIn( "error", table.get_statistics() )


class TestNoLancedbSurface( unittest.TestCase ):
    """The removal itself, pinned."""

    def test_module_does_not_import_lancedb( self ):
        import cosa.memory.canonical_synonyms_table as mod
        self.assertFalse( hasattr( mod, "lancedb" ) )
        self.assertFalse( hasattr( mod, "pa" ) )

    def test_lancedb_only_members_are_gone( self ):
        for name in ( "_validate_embedding_dimensions", "_create_table_if_needed",
                      "_get_schema", "_update_usage_stats", "_pg_add_synonym" ):
            self.assertFalse( hasattr( CanonicalSynonymsTable, name ), f"{name} should be deleted" )

    def test_ctor_takes_no_db_path( self ):
        import inspect
        params = list( inspect.signature( CanonicalSynonymsTable.__init__ ).parameters )
        self.assertNotIn( "db_path", params )


if __name__ == "__main__":
    unittest.main()
