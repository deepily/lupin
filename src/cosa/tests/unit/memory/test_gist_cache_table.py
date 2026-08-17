"""
Unit tests for cosa.memory.gist_cache_table.GistCacheTable.

REWRITTEN 2026-08-17 by Pocholo 📣 (LanceDB total-removal sweep, Lane A, rows
5ff7b8f5 / 8098838f). The LanceDB path is gone, and with it the ctor's
connect/create/open/corruption branches, _create_table, _is_table_corrupted,
_get_cached_by_verbatim / _get_cached_by_normalized and the caller-supplied
db_uri (which resolve_lancedb_path already refused under postgres). The tests
that covered them were testing deleted code and were DELETED, not skipped.

What remains is the Postgres path, which was already the only one running in
every INI section: a ctor that only builds a Normalizer, and five methods that
open a short-lived get_db() session and delegate to GistCacheRepository — with
the two-tier verbatim-then-normalized lookup preserved here.

Exercises:
- __init__          — stores table_name/flags, builds the Normalizer
- has_cached_gist   — verbatim existence, true and false
- get_cached_gist   — verbatim tier hit, normalized tier hit, both miss
- cache_gist        — new insert with metadata / duplicate skip
- get_statistics    — populated / empty (no divide-by-zero)
- clear_cache       — debug no-op print / debug-off silence
"""

import contextlib
import unittest
from unittest.mock import MagicMock, patch

from cosa.memory.gist_cache_table import GistCacheTable


def _build( debug=False, verbose=False ):
    """Build a GistCacheTable with the Normalizer mocked. Returns (cache, mock_normalizer)."""
    with patch( "cosa.memory.gist_cache_table.Normalizer" ) as norm:
        cache = GistCacheTable( debug=debug, verbose=verbose )
    return cache, norm.return_value


def _patch_repo():
    """Patch get_db (ctx mgr → mock session) + the repo class; return (repo_instance, ctx, repo_ctx)."""
    session   = MagicMock()
    repo_inst = MagicMock()

    @contextlib.contextmanager
    def fake_get_db():
        yield session

    ctx      = patch( "cosa.rest.db.database.get_db", fake_get_db )
    repo_ctx = patch( "cosa.rest.db.repositories.gist_cache_repository.GistCacheRepository",
                      return_value=repo_inst )
    return repo_inst, ctx, repo_ctx


class TestInit( unittest.TestCase ):
    """__init__ — flags + table name + normalizer; no connection of its own."""

    def test_stores_flags_and_table_name( self ):
        cache, norm = _build( debug=True, verbose=True )
        self.assertTrue( cache.debug )
        self.assertTrue( cache.verbose )
        self.assertEqual( cache.table_name, "gist_cache" )
        self.assertIs( cache._normalizer, norm )

    def test_table_name_is_overridable( self ):
        with patch( "cosa.memory.gist_cache_table.Normalizer" ):
            cache = GistCacheTable( table_name="other_cache" )
        self.assertEqual( cache.table_name, "other_cache" )


class TestHasCachedGist( unittest.TestCase ):
    """has_cached_gist() — verbatim existence via the repository."""

    def test_true_and_false( self ):
        cache, _ = _build()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_by_verbatim.return_value = object()
        with ctx, repo_ctx:
            self.assertTrue( cache.has_cached_gist( "q" ) )
        repo.get_by_verbatim.return_value = None
        with ctx, repo_ctx:
            self.assertFalse( cache.has_cached_gist( "q" ) )


class TestGetCachedGist( unittest.TestCase ):
    """get_cached_gist() — two-tier lookup."""

    def test_verbatim_tier( self ):
        cache, _ = _build()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_cached_gist.return_value = "hit"
        with ctx, repo_ctx:
            self.assertEqual( cache.get_cached_gist( "q" ), "hit" )
        repo.get_cached_gist.assert_called_once_with( question_verbatim="q" )

    def test_normalized_tier( self ):
        cache, norm = _build()
        norm.normalize.return_value = "q norm"
        repo, ctx, repo_ctx = _patch_repo()
        # verbatim tier misses (None), normalized tier hits.
        repo.get_cached_gist.side_effect = [ None, "hit_norm" ]
        with ctx, repo_ctx:
            self.assertEqual( cache.get_cached_gist( "q" ), "hit_norm" )
        norm.normalize.assert_called_once_with( "q" )
        self.assertEqual( repo.get_cached_gist.call_args_list[ 1 ].kwargs,
                          { "question_normalized": "q norm" } )

    def test_both_tiers_miss( self ):
        cache, norm = _build()
        norm.normalize.return_value = "q norm"
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_cached_gist.side_effect = [ None, None ]
        with ctx, repo_ctx:
            self.assertIsNone( cache.get_cached_gist( "q" ) )


class TestCacheGist( unittest.TestCase ):
    """cache_gist() — insert with metadata, dedupe on verbatim."""

    def test_inserts_when_absent( self ):
        cache, _ = _build()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_by_verbatim.return_value = None
        with ctx, repo_ctx, patch( "cosa.memory.gist_cache_table.time.strftime", return_value="TS" ):
            cache.cache_gist( "q", "g", "n" )
        repo.cache_gist.assert_called_once_with(
            question_verbatim="q", question_gist="g", question_normalized="n",
            created_date="TS", access_count=0, last_accessed="TS",
        )

    def test_skips_duplicate( self ):
        cache, _ = _build()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_by_verbatim.return_value = object()      # already present
        with ctx, repo_ctx:
            cache.cache_gist( "q", "g", "n" )
        repo.cache_gist.assert_not_called()


class TestGetStatistics( unittest.TestCase ):
    """get_statistics() — averages, and no divide-by-zero on an empty table."""

    def test_populated_and_empty( self ):
        cache, _ = _build()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_statistics.return_value = { "total_entries": 4, "total_access_count": 10 }
        with ctx, repo_ctx:
            stats = cache.get_statistics()
        self.assertEqual( stats[ "total_entries" ], 4 )
        self.assertEqual( stats[ "avg_access_count" ], 2.5 )
        self.assertEqual( stats[ "sample_size" ], 4 )
        self.assertEqual( stats[ "table_name" ], "gist_cache" )

        repo.get_statistics.return_value = { "total_entries": 0, "total_access_count": 0 }
        with ctx, repo_ctx:
            empty = cache.get_statistics()
        self.assertEqual( empty[ "avg_access_count" ], 0 )


class TestClearCache( unittest.TestCase ):
    """clear_cache() — a logged no-op under debug, silent otherwise."""

    def test_noop_debug_on_and_off( self ):
        cache_dbg, _ = _build( debug=True )
        with patch( "builtins.print" ) as p:
            cache_dbg.clear_cache()
        p.assert_called_once()

        cache_off, _ = _build( debug=False )
        with patch( "builtins.print" ) as p2:
            cache_off.clear_cache()
        p2.assert_not_called()


class TestNoLancedbSurface( unittest.TestCase ):
    """The removal itself, pinned."""

    def test_module_does_not_import_lancedb( self ):
        import cosa.memory.gist_cache_table as mod
        self.assertFalse( hasattr( mod, "lancedb" ) )
        self.assertFalse( hasattr( mod, "pa" ) )

    def test_lancedb_only_members_are_gone( self ):
        for name in ( "_create_table", "_is_table_corrupted", "_get_cached_by_verbatim",
                      "_get_cached_by_normalized", "_pg_has_cached_gist" ):
            self.assertFalse( hasattr( GistCacheTable, name ), f"{name} should be deleted" )

    def test_ctor_takes_no_db_uri( self ):
        import inspect
        params = list( inspect.signature( GistCacheTable.__init__ ).parameters )
        self.assertNotIn( "db_uri", params )


if __name__ == "__main__":
    unittest.main()
