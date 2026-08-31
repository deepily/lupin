"""
Unit tests for cosa.memory.query_log_table.QueryLogTable.

REWRITTEN 2026-08-17 by Pocholo 📣 (LanceDB total-removal sweep, Lane A, rows
5ff7b8f5 / 8098838f). The LanceDB path is gone, and with it the ctor's
connect/validate/create/open branches, _get_schema and the `.search().where()`
query chains. The tests that covered them were testing deleted code and were
DELETED, not skipped.

What remains is the Postgres path, which was already the only one running in
every INI section: a config-only ctor plus three methods that open a short-lived
get_db() session and delegate to QueryLogRepository, preserving the same return
contracts (query_id or "", newest-first rows, percentage stats).
"""
import contextlib
import unittest
from unittest.mock import Mock, MagicMock, patch

from cosa.memory.query_log_table import QueryLogTable


def _cfg():
    m = Mock()
    m.get.side_effect = lambda key, default=None, **kw: {
        "normalization version":            "v2.0",
        "llm spec key for gist generation": "gpt-x",
        "embedding dimensions":             "768",
    }.get( key, default )
    return m


def _make_table( debug=False, verbose=False ):
    """Build a QueryLogTable with config mocked; no I/O occurs."""
    with patch( "cosa.memory.query_log_table.ConfigurationManager", return_value=_cfg() ):
        return QueryLogTable( debug=debug, verbose=verbose )


def _patch_repo():
    """Patch get_db (ctx mgr → mock session) + the repo class; return (repo_instance, ctx, repo_ctx)."""
    session   = MagicMock()
    repo_inst = MagicMock()

    @contextlib.contextmanager
    def fake_get_db():
        yield session

    ctx      = patch( "cosa.rest.db.database.get_db", fake_get_db )
    repo_ctx = patch( "cosa.rest.db.repositories.query_log_repository.QueryLogRepository",
                      return_value=repo_inst )
    return repo_inst, ctx, repo_ctx


class TestInit( unittest.TestCase ):
    """__init__ — config-only; reads the embedding dimension, opens nothing."""

    def test_reads_config( self ):
        table = _make_table( debug=True, verbose=True )
        self.assertEqual( table._embedding_dim, 768 )
        self.assertTrue( table.debug )
        self.assertTrue( table.verbose )


class TestLogQuery( unittest.TestCase ):
    """log_query() — field mapping, defaults, id contract, error swallow."""

    def test_maps_fields_and_returns_id( self ):
        table = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        with ctx, repo_ctx, \
             patch( "cosa.memory.query_log_table.du.get_current_datetime", return_value="QID" ), \
             patch( "cosa.memory.query_log_table.du.get_timestamp_ms", return_value="TS" ):
            qid = table.log_query(
                query_verbatim="v", query_normalized="n", query_gist="g", user_id="u",
                embeddings={ "verbatim": [ 1.0 ], "normalized": [ 2.0 ] },
                match_result={ "snapshot_id": "s1", "type": "similarity", "confidence": 0.8 },
                processing_time_ms=12, cache_hits={ "verbatim": True, "normalized": False },
            )
        self.assertEqual( qid, "QID" )
        kw = repo.log_query.call_args.kwargs
        self.assertEqual( kw[ "id" ], "QID" )
        self.assertEqual( kw[ "matched_snapshot_id" ], "s1" )
        self.assertEqual( kw[ "embedding_verbatim" ], [ 1.0 ] )
        self.assertTrue( kw[ "cache_hit_verbatim" ] )
        self.assertEqual( kw[ "normalization_version" ], "v2.0" )

    def test_defaults_when_optional_none( self ):
        table = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        with ctx, repo_ctx, \
             patch( "cosa.memory.query_log_table.du.get_current_datetime", return_value="QID" ), \
             patch( "cosa.memory.query_log_table.du.get_timestamp_ms", return_value="TS" ):
            table.log_query( query_verbatim="v", query_normalized="n", query_gist="g", user_id="u" )
        kw = repo.log_query.call_args.kwargs
        # CHANGED 2026-08-30 (row 0e7c9214, symptom 4). This used to assert `[]`, and that
        # assertion ENDORSED the defect: `[]` is the value pgvector refuses. The repository's
        # own contract is "dim-768 lists or None", so absent must arrive as None.
        self.assertIsNone( kw[ "embedding_verbatim" ] )
        self.assertIsNone( kw[ "embedding_normalized" ] )
        self.assertEqual( kw[ "match_type" ], "none" )
        self.assertEqual( kw[ "matched_snapshot_id" ], "" )
        self.assertEqual( kw[ "match_confidence" ], 0.0 )
        self.assertFalse( kw[ "cache_hit_verbatim" ] )
        self.assertFalse( kw[ "cache_hit_normalized" ] )

    def test_error_returns_empty_id( self ):
        table = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        repo.log_query.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, \
             patch( "cosa.memory.query_log_table.du.get_current_datetime", return_value="QID" ), \
             patch( "cosa.memory.query_log_table.du.get_timestamp_ms", return_value="TS" ), \
             patch( "cosa.memory.query_log_table.du.print_stack_trace" ) as trace:
            self.assertEqual( table.log_query( "v", "n", "g", "u" ), "" )
        trace.assert_called_once()


class TestAbsentEmbeddingsAreStorableNulls( unittest.TestCase ):
    """
    An embedding this caller does not have must reach storage as NULL, never as `[]`.

    Row 0e7c9214, symptom 4, measured live on :7999 2026-08-30. `v2.flow.FlowEngine._log_query`
    passes no embeddings — deliberately, with its reasons in its own docstring. This class
    turned that absence into `[]`, pgvector refused it, and the whole INSERT died inside the
    caught-and-printed except block. The dev query_log's newest row is 2026-08-21.
    """

    def _kwargs_for( self, **log_kwargs ):
        table = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        with ctx, repo_ctx, \
             patch( "cosa.memory.query_log_table.du.get_current_datetime", return_value="QID" ), \
             patch( "cosa.memory.query_log_table.du.get_timestamp_ms", return_value="TS" ):
            table.log_query( query_verbatim="v", query_normalized="n", query_gist="g",
                             user_id="u", **log_kwargs )
        return repo.log_query.call_args.kwargs

    def test_no_embeddings_argument_at_all_becomes_null( self ):
        """The v2 shape: the caller passes nothing."""
        kw = self._kwargs_for()
        self.assertIsNone( kw[ "embedding_verbatim" ] )
        self.assertIsNone( kw[ "embedding_normalized" ] )

    def test_an_explicitly_empty_vector_becomes_null( self ):
        """
        The v1 shape when generation comes back empty. v1 computes its cache-hit flags as
        `len( embedding ) > 0`, so it already anticipates an empty vector — and would have
        handed that straight through to the same refusal.
        """
        kw = self._kwargs_for( embeddings={ "verbatim": [], "normalized": [] } )
        self.assertIsNone( kw[ "embedding_verbatim" ] )
        self.assertIsNone( kw[ "embedding_normalized" ] )

    def test_one_present_one_absent_are_treated_separately( self ):
        """
        A real vector must survive unchanged. Guards the opposite over-correction — mapping
        every embedding to None would also make this class's writes succeed, and would
        silently stop storing the vectors it does have.
        """
        kw = self._kwargs_for( embeddings={ "verbatim": [ 0.5 ] * 768 } )
        self.assertEqual( kw[ "embedding_verbatim" ], [ 0.5 ] * 768 )
        self.assertIsNone( kw[ "embedding_normalized" ] )

    def test_what_we_pass_is_what_pgvector_accepts( self ):
        """
        The discriminating case, and the reason the three tests above are not enough on their
        own: they assert against a MagicMock, which would accept `[]` just as happily as None.
        This one puts both values through the REAL pgvector binder for the real column width,
        so the assertion is about the storage contract rather than about our own fake.

        The `[]` arm reproduces the production error verbatim — `expected 768 dimensions,
        not 0` — which is the string the live server printed four times.
        """
        from pgvector.utils import Vector
        from cosa.memory.query_log_table import QueryLogTable

        with self.assertRaises( ValueError ) as caught:
            Vector._to_db( [], 768 )
        self.assertIn( "expected 768 dimensions, not 0", str( caught.exception ) )

        for embeddings in ( None, {}, { "verbatim": [] } ):
            value = QueryLogTable._vector_or_none( embeddings, "verbatim" )
            self.assertIsNone( Vector._to_db( value, 768 ),
                               f"{embeddings!r} produced {value!r}, which pgvector will not store" )


class TestGetRecentQueries( unittest.TestCase ):
    """get_recent_queries() — delegation + error fallback on both debug arcs."""

    def test_delegates( self ):
        table = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_recent_queries.return_value = [ "row" ]
        with ctx, repo_ctx:
            self.assertEqual( table.get_recent_queries( limit=5, user_id="u" ), [ "row" ] )
        repo.get_recent_queries.assert_called_once_with( limit=5, user_id="u" )

    def test_error_returns_empty_debug_on( self ):
        table = _make_table( debug=True )
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_recent_queries.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "builtins.print" ) as p:
            self.assertEqual( table.get_recent_queries(), [] )
        p.assert_called_once()

    def test_error_returns_empty_debug_off( self ):
        table = _make_table( debug=False )
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_recent_queries.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx:
            self.assertEqual( table.get_recent_queries(), [] )


class TestGetCacheHitStats( unittest.TestCase ):
    """get_cache_hit_stats() — rate math, empty window, error fallback on both debug arcs."""

    def test_rates_and_empty_window( self ):
        table = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_cache_hit_stats.return_value = {
            "total_queries": 4, "verbatim_hit_rate": 0.5, "normalized_hit_rate": 0.25, "gist_hit_rate": 0.0,
        }
        with ctx, repo_ctx:
            stats = table.get_cache_hit_stats( days=3 )
        self.assertEqual( stats, { "verbatim": 50.0, "normalized": 25.0, "total_queries": 4 } )

        repo.get_cache_hit_stats.return_value = {
            "total_queries": 0, "verbatim_hit_rate": 0.0, "normalized_hit_rate": 0.0, "gist_hit_rate": 0.0,
        }
        with ctx, repo_ctx:
            self.assertEqual( table.get_cache_hit_stats(), { "verbatim": 0.0, "normalized": 0.0 } )

    def test_error_returns_default_debug_on( self ):
        table = _make_table( debug=True )
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_cache_hit_stats.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "builtins.print" ) as p:
            self.assertEqual( table.get_cache_hit_stats(), { "verbatim": 0.0, "normalized": 0.0 } )
        p.assert_called_once()

    def test_error_returns_default_debug_off( self ):
        table = _make_table( debug=False )
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_cache_hit_stats.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx:
            self.assertEqual( table.get_cache_hit_stats(), { "verbatim": 0.0, "normalized": 0.0 } )


class TestNoLancedbSurface( unittest.TestCase ):
    """The removal itself, pinned."""

    def test_module_does_not_import_lancedb( self ):
        import cosa.memory.query_log_table as mod
        self.assertFalse( hasattr( mod, "lancedb" ) )
        self.assertFalse( hasattr( mod, "pa" ) )

    def test_lancedb_only_members_are_gone( self ):
        for name in ( "_validate_embedding_dimensions", "_create_table_if_needed",
                      "_get_schema", "_pg_log_query" ):
            self.assertFalse( hasattr( QueryLogTable, name ), f"{name} should be deleted" )


if __name__ == "__main__":
    unittest.main()
