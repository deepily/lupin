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


class TestAnEmbeddingTheApiCouldNotProduce( unittest.TestCase ):
    """
    `EmbeddingManager.generate_embedding` returns `[]` on API errors — its own Ensures
    block says so, and two of its three such paths print "CONTINUING WITHOUT EMBEDDINGS".
    That empty list is a value pgvector refuses, so before this fix one API error took
    down the whole INSERT and the synonym was silently lost behind a bare `False`.

    Found by Rachel 🕊️ reviewing the twin defect in the query-log write (row 0e7c9214
    symptom 4), after I had claimed this file was not affected.
    """

    # add_synonym calls generate_embedding three times, in this order: verbatim,
    # normalized, gist. Three DISTINCT vectors, so which one lands in which column is
    # observable. A single return_value cannot see a swap — see the class docstring.
    V_VERBATIM   = [ 0.11 ] * 768
    V_NORMALIZED = [ 0.22 ] * 768
    V_GIST       = [ 0.33 ] * 768

    def _kwargs_when_embeddings_return( self, *values ):
        """
        Drive add_synonym with a scripted embedding sequence.

        Pass ONE value to give all three calls the same thing, or THREE to give each call
        its own. `side_effect` rather than `return_value` is the whole point: a fixture
        that answers every call identically cannot tell correct routing from crossed.
        """
        table, _, emb = _make()
        emb.generate_embedding.side_effect = list( values ) if len( values ) > 1 else [ values[ 0 ] ] * 3
        repo, ctx, repo_ctx = _patch_repo()
        repo.find_exact_verbatim.return_value = None
        with ctx, repo_ctx, \
             patch( "cosa.memory.canonical_synonyms_table.du.get_current_datetime", return_value="TS" ), \
             patch( "cosa.memory.canonical_synonyms_table.du.get_timestamp_ms", return_value="NOW" ):
            added = table.add_synonym( "snap1", "How Are You?" )
        return added, repo.add_synonym.call_args.kwargs

    def test_an_api_error_stores_nulls_and_still_writes_the_row( self ):
        """
        The row must survive. This table earns its keep through exact-match lookups on the
        TEXT columns — its repository's own module docstring says the embedding columns are
        "stored but NOT ANN-searched", and the indexes are on `snapshot_id` and
        `question_normalized`. So NULL embeddings still do the job; losing the row does not.
        """
        added, kw = self._kwargs_when_embeddings_return( [] )
        self.assertTrue( added )
        self.assertIsNone( kw[ "embedding_verbatim" ] )
        self.assertIsNone( kw[ "embedding_normalized" ] )
        self.assertIsNone( kw[ "embedding_gist" ] )
        self.assertEqual( kw[ "question_verbatim" ], "How Are You?" )
        self.assertEqual( kw[ "question_normalized" ], "how are you?" )

    def test_a_real_vector_is_not_touched( self ):
        """
        Guards the opposite over-correction. Mapping every embedding to None would also
        make the write succeed, while silently dropping the vectors we do have.

        Each column is asserted against its OWN vector, so this also fails if the three
        results reach the wrong columns. With one shared value it could not.
        """
        _added, kw = self._kwargs_when_embeddings_return(
            self.V_VERBATIM, self.V_NORMALIZED, self.V_GIST
        )
        self.assertEqual( kw[ "embedding_verbatim" ],   self.V_VERBATIM )
        self.assertEqual( kw[ "embedding_normalized" ], self.V_NORMALIZED )
        self.assertEqual( kw[ "embedding_gist" ],       self.V_GIST )

    def test_one_empty_result_does_not_take_the_others_down_with_it( self ):
        """
        The three calls are independent and an API error need not hit all of them — the
        manager caches, so one text can miss while another hits. Only the empty one
        becomes NULL; the other two are stored.

        Untested before this: every earlier case handed all three calls the same value,
        so "one of them empty" and "all of them empty" were the same experiment.
        """
        _added, kw = self._kwargs_when_embeddings_return(
            self.V_VERBATIM, [], self.V_GIST
        )
        self.assertEqual( kw[ "embedding_verbatim" ], self.V_VERBATIM )
        self.assertIsNone( kw[ "embedding_normalized" ] )
        self.assertEqual( kw[ "embedding_gist" ], self.V_GIST )

    def test_every_embedding_we_hand_the_repository_is_one_pgvector_can_store( self ):
        """
        The discriminating case: it drives the REAL pgvector binder at the real column
        width, so it is about the storage contract rather than about our own MagicMock.

        REWRITTEN 2026-08-31 on Rachel 🕊️'s correction, and the correction is the point.
        The first cut imported the private helper by name and drove it directly. Without
        the fix that import raises ImportError — so the test went red on a MISSING SYMBOL,
        not on the defect, and a red like that is not evidence the test caught anything.
        It would have reddened just as loudly if the helper had merely been renamed.

        This version never names the helper. It takes the embeddings the module actually
        handed the repository and puts each one through the binder, so an unfixed module
        fails HERE, on the value it produced, by the same mechanism that killed the INSERT
        in production.
        """
        from pgvector.utils import Vector

        # The control: prove the binder can still tell the two apart, so a pass below
        # means the values were storable rather than the check being asleep.
        with self.assertRaises( ValueError ) as caught:
            Vector._to_db( [], 768 )
        self.assertIn( "expected 768 dimensions, not 0", str( caught.exception ) )

        _added, kw = self._kwargs_when_embeddings_return( [] )
        for column in ( "embedding_verbatim", "embedding_normalized", "embedding_gist" ):
            self.assertIsNone(
                Vector._to_db( kw[ column ], 768 ),
                f"{column} was handed {kw[ column ]!r}, which pgvector will not store"
            )
