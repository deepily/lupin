"""
Unit tests for InputAndOutputTable with comprehensive mocking.

REWRITTEN 2026-08-17 by Pocholo 📣 (LanceDB total-removal sweep, Lane A, rows
5ff7b8f5 / 8098838f). The LanceDB path is gone, and with it the ctor's
connect/validate/create/open branches, _validate_embedding_dimensions,
_create_table_if_needed, init_tbl, the nprobes tuning key and the four readers'
`.search()...` chains. The tests that covered them were testing deleted code
and were DELETED, not skipped.

What remains is the storage-agnostic insert path (sync + async-via-pool, with
its failure accounting) and five methods that open a short-lived get_db()
session and delegate to InputAndOutputRepository. Query-embedding generation
stays in the memory layer via the question-embedding cache.

Zero external dependencies — every database, pool, and provider call is mocked.
"""

import contextlib
import unittest
from unittest.mock import Mock, MagicMock, patch


@contextlib.contextmanager
def _capture_pool_submit():
    """
    Capture the fn insert_io_row submits to the embedding pool.

    The async insert path was refactored (bug 81854972) from a per-call
    threading.Thread to a bounded embedding pool: it now calls
    get_embedding_pool( ... ).submit( fn ). Tests capture that fn and run it
    synchronously to exercise the async worker body.
    """
    captured = [ ]
    pool = MagicMock()
    pool.submit.side_effect = lambda fn: captured.append( fn )
    with patch( "cosa.memory.embedding_pool.get_embedding_pool", return_value=pool ):
        yield captured


from cosa.memory.input_and_output_table import InputAndOutputTable


_EMB = [ 0.1 ] * 768


def _make( debug=False, verbose=False, async_default=False ):
    """Build an InputAndOutputTable with its ctor deps mocked. Returns (table, question_tbl, provider)."""
    cfg = Mock()
    cfg.get.side_effect = lambda key, default=None, return_type=None: {
        "embedding dimensions":         "768",
        "debug text truncation length": 48,
        "async embedding generation":   async_default,
    }.get( key, default )
    question_tbl = Mock()
    question_tbl.get_embedding.return_value = _EMB
    question_tbl.has.return_value = False
    provider = Mock()
    provider.generate_embedding.return_value = _EMB
    with patch( "cosa.memory.input_and_output_table.ConfigurationManager", return_value=cfg ), \
         patch( "cosa.memory.input_and_output_table.EmbeddingManager" ), \
         patch( "cosa.memory.input_and_output_table.get_embedding_provider", return_value=provider ), \
         patch( "cosa.memory.input_and_output_table.QuestionEmbeddingsTable", return_value=question_tbl ):
        table = InputAndOutputTable( debug=debug, verbose=verbose )
    return table, question_tbl, provider


def _patch_repo():
    """Patch get_db (ctx mgr → mock session) + the repo class; return (repo_instance, ctx, repo_ctx)."""
    session   = MagicMock()
    repo_inst = MagicMock()

    @contextlib.contextmanager
    def fake_get_db():
        yield session

    ctx      = patch( "cosa.rest.db.database.get_db", fake_get_db )
    repo_ctx = patch( "cosa.rest.db.repositories.input_and_output_repository.InputAndOutputRepository",
                      return_value=repo_inst )
    return repo_inst, ctx, repo_ctx


class TestInit( unittest.TestCase ):
    """__init__ — config, failure accounting, question-embedding cache; opens nothing."""

    def test_wires_dependencies( self ):
        table, question_tbl, provider = _make( debug=True, verbose=True )
        self.assertEqual( table._embedding_dim, 768 )
        self.assertIs( table._question_embeddings_tbl, question_tbl )
        self.assertIs( table._embedding_provider, provider )
        self.assertEqual( table.async_failure_count, 0 )
        self.assertIsNone( table.last_async_failure )
        self.assertTrue( table.debug )
        self.assertTrue( table.verbose )


class TestInsertIoRow( unittest.TestCase ):
    """insert_io_row() — sync, async-via-pool, provided-vs-generated embeddings, failure accounting."""

    def test_sync_stores_via_repo( self ):
        table, question_tbl, provider = _make()
        repo, ctx, repo_ctx = _patch_repo()
        with ctx, repo_ctx, patch( "cosa.memory.input_and_output_table.Stopwatch" ), patch( "builtins.print" ):
            table.insert_io_row(
                input_type="t", input="q", output_raw="r", output_final="out", async_embedding=False,
            )
        repo.insert_io_row.assert_called_once()
        kw = repo.insert_io_row.call_args.kwargs
        self.assertEqual( kw[ "input_type" ], "t" )
        self.assertEqual( kw[ "input_embedding" ], _EMB )          # generated via question cache
        self.assertEqual( kw[ "output_final_embedding" ], _EMB )

    def test_sync_honors_provided_embeddings( self ):
        table, question_tbl, provider = _make()
        repo, ctx, repo_ctx = _patch_repo()
        supplied = [ 0.9 ] * 768
        with ctx, repo_ctx, patch( "cosa.memory.input_and_output_table.Stopwatch" ), patch( "builtins.print" ):
            table.insert_io_row(
                input_type="t", input="q", input_embedding=supplied,
                output_raw="r", output_final="out", output_final_embedding=supplied,
                async_embedding=False,
            )
        kw = repo.insert_io_row.call_args.kwargs
        self.assertEqual( kw[ "input_embedding" ], supplied )
        self.assertEqual( kw[ "output_final_embedding" ], supplied )
        question_tbl.get_embedding.assert_not_called()
        provider.generate_embedding.assert_not_called()

    def test_async_defers_to_pool_then_stores( self ):
        table, question_tbl, provider = _make()
        repo, ctx, repo_ctx = _patch_repo()
        with ctx, repo_ctx, patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             _capture_pool_submit() as submitted, patch( "builtins.print" ):
            table.insert_io_row(
                input_type="t", input="q", output_raw="r", output_final="out", async_embedding=True,
            )
            repo.insert_io_row.assert_not_called()     # deferred to the pool worker
            submitted[ 0 ]()
        repo.insert_io_row.assert_called_once()

    def test_async_default_comes_from_config( self ):
        # async_embedding=None → the ctor's config value decides. Here: True.
        table, _, _ = _make( debug=True, verbose=True, async_default=True )
        repo, ctx, repo_ctx = _patch_repo()
        with ctx, repo_ctx, patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             _capture_pool_submit() as submitted, patch( "builtins.print" ):
            table.insert_io_row( input_type="t", input="q", output_raw="r", output_final="out" )
        self.assertEqual( len( submitted ), 1 )

    def test_async_worker_honors_provided_embeddings( self ):
        table, question_tbl, provider = _make( debug=True, verbose=True )
        repo, ctx, repo_ctx = _patch_repo()
        supplied = [ 0.9 ] * 768
        with ctx, repo_ctx, patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             _capture_pool_submit() as submitted, patch( "builtins.print" ):
            # only the OUTPUT embedding is missing, so the worker generates just that one
            table.insert_io_row(
                input_type="t", input="q", input_embedding=supplied,
                output_raw="r", output_final="out", async_embedding=True,
            )
            submitted[ 0 ]()
        kw = repo.insert_io_row.call_args.kwargs
        self.assertEqual( kw[ "input_embedding" ], supplied )
        question_tbl.get_embedding.assert_not_called()
        self.assertEqual( kw[ "output_final_embedding" ], _EMB )

    def test_async_worker_honors_provided_output_embedding( self ):
        table, question_tbl, provider = _make( debug=True, verbose=True )
        repo, ctx, repo_ctx = _patch_repo()
        supplied = [ 0.9 ] * 768
        with ctx, repo_ctx, patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             _capture_pool_submit() as submitted, patch( "builtins.print" ):
            table.insert_io_row(
                input_type="t", input="q", output_raw="r", output_final="out",
                output_final_embedding=supplied, async_embedding=True,
            )
            submitted[ 0 ]()
        kw = repo.insert_io_row.call_args.kwargs
        self.assertEqual( kw[ "output_final_embedding" ], supplied )
        provider.generate_embedding.assert_not_called()
        self.assertEqual( kw[ "input_embedding" ], _EMB )

    def test_async_worker_empty_output_final_is_handled( self ):
        # `output_str = str(output_final) if output_final else ""` — the falsy arc.
        table, _, _ = _make( debug=True, verbose=True )
        repo, ctx, repo_ctx = _patch_repo()
        with ctx, repo_ctx, patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             _capture_pool_submit() as submitted, patch( "builtins.print" ):
            table.insert_io_row( input_type="t", input="q", output_raw="r", output_final="", async_embedding=True )
            submitted[ 0 ]()
        repo.insert_io_row.assert_called_once()

    def test_async_worker_failure_is_counted_not_raised( self ):
        table, question_tbl, _ = _make( debug=True )
        question_tbl.get_embedding.side_effect = Exception( "Embedding generation failed" )
        with patch( "cosa.memory.input_and_output_table.Stopwatch" ), \
             _capture_pool_submit() as submitted, \
             patch( "cosa.memory.input_and_output_table.du.print_banner" ), \
             patch( "cosa.memory.input_and_output_table.du.print_stack_trace" ) as trace, \
             patch( "builtins.print" ):
            table.insert_io_row(
                input_type="t", input="q", output_raw="r", output_final="out", async_embedding=True,
            )
            submitted[ 0 ]()      # must NOT raise
        trace.assert_called_once()
        kwargs = trace.call_args.kwargs
        self.assertEqual( kwargs[ "explanation" ], "Async embedding generation failed" )
        self.assertEqual( kwargs[ "caller" ], "insert_io_row async thread" )
        self.assertEqual( table.async_failure_count, 1 )


class TestRowCount( unittest.TestCase ):
    """_row_count() delegates to the repository."""

    def test_delegates( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.count.return_value = 42
        with ctx, repo_ctx:
            self.assertEqual( table._row_count(), 42 )


class TestGetKnnByInput( unittest.TestCase ):
    """get_knn_by_input() — shape mapping, distance math, empty-embedding short circuit."""

    def test_maps_shape( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        entity = Mock( input="q", output_final="a", input_embedding=_EMB )
        repo.get_knn_by_input.return_value = [ ( 90.0, entity ) ]
        with ctx, repo_ctx:
            result = table.get_knn_by_input( "q", k=3 )
        self.assertEqual( result[ 0 ][ "input" ], "q" )
        self.assertEqual( result[ 0 ][ "output_final" ], "a" )
        self.assertAlmostEqual( result[ 0 ][ "_distance" ], 1.0 - 0.9 )   # 1 - pct/100

    def test_empty_embedding_short_circuits( self ):
        table, question_tbl, _ = _make()
        question_tbl.get_embedding.return_value = []       # no embedding → skip search
        with patch( "cosa.memory.input_and_output_table.du.print_banner" ), patch( "builtins.print" ):
            self.assertEqual( table.get_knn_by_input( "q" ), [] )

    def test_null_embedding_entity_returns_empty_list_field( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        entity = Mock( input="q", output_final="a", input_embedding=None )
        repo.get_knn_by_input.return_value = [ ( 100.0, entity ) ]
        with ctx, repo_ctx:
            result = table.get_knn_by_input( "q" )
        self.assertEqual( result[ 0 ][ "input_embedding" ], [] )


class TestScans( unittest.TestCase ):
    """get_all_io / get_io_stats_by_input_type / get_all_qnr delegate and project."""

    def test_get_all_io_maps_dicts( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_all_io.return_value = [ Mock( date="d", time="t", input_type="it", input="i", output_final="o" ) ]
        with ctx, repo_ctx:
            rows = table.get_all_io( max_rows=10 )
        self.assertEqual( rows, [ { "date": "d", "time": "t", "input_type": "it", "input": "i", "output_final": "o" } ] )

    def test_get_io_stats_delegates( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_io_stats_by_input_type.return_value = { "math": 2 }
        with ctx, repo_ctx:
            self.assertEqual( table.get_io_stats_by_input_type(), { "math": 2 } )

    def test_get_all_qnr_maps_dicts( self ):
        table, _, _ = _make()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_all_qnr.return_value = [ Mock( date="d", time="t", input_type="agent router go to x", input="i", output_final="o" ) ]
        with ctx, repo_ctx:
            rows = table.get_all_qnr()
        self.assertEqual( rows[ 0 ][ "input_type" ], "agent router go to x" )


class TestNoLancedbSurface( unittest.TestCase ):
    """The removal itself, pinned."""

    def test_module_does_not_import_lancedb( self ):
        import cosa.memory.input_and_output_table as mod
        self.assertFalse( hasattr( mod, "lancedb" ) )
        self.assertFalse( hasattr( mod, "pa" ) )

    def test_lancedb_only_members_are_gone( self ):
        for name in ( "_validate_embedding_dimensions", "_create_table_if_needed",
                      "init_tbl", "_pg_get_knn_by_input", "_pg_get_all_io" ):
            self.assertFalse( hasattr( InputAndOutputTable, name ), f"{name} should be deleted" )


if __name__ == "__main__":
    unittest.main()
