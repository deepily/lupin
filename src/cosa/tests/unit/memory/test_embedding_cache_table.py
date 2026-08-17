"""
Unit tests for cosa.memory.embedding_cache_table.EmbeddingCacheTable.

REWRITTEN 2026-08-17 by Pocholo 📣 (LanceDB total-removal sweep, Lane A, rows
5ff7b8f5 / 8098838f). The LanceDB path is gone — with it went the ctor's
connect/create/open/corruption branches, _validate_embedding_dimensions,
_is_table_corrupted, _create_table_if_needed and init_tbl. The tests that
covered them were testing deleted code and were DELETED, not skipped.

What remains is the Postgres path, which was already the only one running in
every INI section: a config-only ctor plus three methods that each open a
short-lived get_db() session and delegate to EmbeddingCacheRepository.
"""
import contextlib
import unittest
from unittest.mock import Mock, MagicMock, patch

from cosa.memory.embedding_cache_table import EmbeddingCacheTable

_EMB = [ 0.1 ] * 768


def _cfg():
    m = Mock()
    m.get.side_effect = lambda key, default=None, **kw: {
        "embedding dimensions": "768",
    }.get( key, default )
    return m


def _make_table( debug=False, verbose=False ):
    """Build an EmbeddingCacheTable with config mocked; no I/O occurs."""
    with patch( "cosa.memory.embedding_cache_table.ConfigurationManager", return_value=_cfg() ):
        return EmbeddingCacheTable( debug=debug, verbose=verbose )


def _patch_repo():
    """Patch get_db (ctx mgr → mock session) + the repo class; return (repo_instance, ctx, repo_ctx)."""
    session   = MagicMock()
    repo_inst = MagicMock()

    @contextlib.contextmanager
    def fake_get_db():
        yield session

    ctx = patch.multiple(
        "cosa.rest.db.database",
        get_db = fake_get_db,
    )
    repo_ctx = patch(
        "cosa.rest.db.repositories.embedding_cache_repository.EmbeddingCacheRepository",
        return_value=repo_inst,
    )
    return repo_inst, ctx, repo_ctx


class TestInit( unittest.TestCase ):
    """__init__ — config-only; reads the embedding dimension, opens nothing."""

    def test_reads_embedding_dimension_from_config( self ):
        table = _make_table()
        self.assertEqual( table._embedding_dim, 768 )

    def test_flags_are_stored( self ):
        table = _make_table( debug=True, verbose=True )
        self.assertTrue( table.debug )
        self.assertTrue( table.verbose )


class TestHasCachedEmbedding( unittest.TestCase ):
    """has_cached_embedding() delegates to the repository."""

    def test_true_when_found( self ):
        table = _make_table()
        repo_inst, ctx, repo_ctx = _patch_repo()
        repo_inst.has_cached_embedding.return_value = True
        with ctx, repo_ctx:
            self.assertTrue( table.has_cached_embedding( "what time is it" ) )
        repo_inst.has_cached_embedding.assert_called_once_with( "what time is it" )

    def test_false_when_absent( self ):
        table = _make_table()
        repo_inst, ctx, repo_ctx = _patch_repo()
        repo_inst.has_cached_embedding.return_value = False
        with ctx, repo_ctx:
            self.assertFalse( table.has_cached_embedding( "nope" ) )


class TestGetCachedEmbedding( unittest.TestCase ):
    """get_cached_embedding() delegates to the repository."""

    def test_returns_embedding_on_hit( self ):
        table = _make_table()
        repo_inst, ctx, repo_ctx = _patch_repo()
        repo_inst.get_cached_embedding.return_value = _EMB
        with ctx, repo_ctx:
            self.assertEqual( table.get_cached_embedding( "q" ), _EMB )
        repo_inst.get_cached_embedding.assert_called_once_with( "q" )

    def test_returns_none_on_miss( self ):
        table = _make_table()
        repo_inst, ctx, repo_ctx = _patch_repo()
        repo_inst.get_cached_embedding.return_value = None
        with ctx, repo_ctx:
            self.assertIsNone( table.get_cached_embedding( "q" ) )


class TestCacheEmbedding( unittest.TestCase ):
    """cache_embedding() delegates to the repository."""

    def test_writes_through_the_repo( self ):
        table = _make_table()
        repo_inst, ctx, repo_ctx = _patch_repo()
        with ctx, repo_ctx:
            self.assertIsNone( table.cache_embedding( "q", _EMB ) )
        repo_inst.cache_embedding.assert_called_once_with( "q", _EMB )


class TestNoLancedbSurface( unittest.TestCase ):
    """
    The removal itself, pinned. Importing this module must not drag in lancedb,
    and the LanceDB-only members must be gone rather than lying dormant.
    """

    def test_module_does_not_import_lancedb( self ):
        import cosa.memory.embedding_cache_table as mod
        self.assertFalse( hasattr( mod, "lancedb" ) )
        self.assertFalse( hasattr( mod, "pa" ) )

    def test_lancedb_only_members_are_gone( self ):
        for name in ( "_is_table_corrupted", "_validate_embedding_dimensions",
                      "_create_table_if_needed", "init_tbl", "_pg_has_cached_embedding" ):
            self.assertFalse( hasattr( EmbeddingCacheTable, name ), f"{name} should be deleted" )


if __name__ == "__main__":
    unittest.main()
