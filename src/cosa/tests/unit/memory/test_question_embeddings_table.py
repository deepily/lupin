"""
Unit tests for cosa.memory.question_embeddings_table.QuestionEmbeddingsTable.

REWRITTEN 2026-08-17 by Pocholo 📣 (LanceDB total-removal sweep, Lane A, rows
5ff7b8f5 / 8098838f). The LanceDB path is gone, and with it the ctor's
connect/validate/create/open branches, the `.search().where()` query chain and
the Stopwatch timing arcs. The tests that covered them were testing deleted
code and were DELETED, not skipped.

What remains is the Postgres path, which was already the only one running in
every INI section: a config-only ctor, storage delegated to
QuestionEmbeddingRepository per call, and generate-on-miss (never stored) kept
here in the memory layer.
"""
import contextlib
import unittest
from unittest.mock import Mock, MagicMock, patch

from cosa.memory.question_embeddings_table import QuestionEmbeddingsTable


_EMBEDDING = [ 0.1 ] * 768


def _cfg_get( key, default=None, **kwargs ):
    return {
        "embedding dimensions": "768",
    }.get( key, default )


def _make_table( debug=False, verbose=False ):
    """Build a QuestionEmbeddingsTable with its ctor dep chain mocked. Returns (table, provider)."""
    cfg = Mock()
    cfg.get.side_effect = _cfg_get
    provider = Mock()
    provider.generate_embedding.return_value = _EMBEDDING

    with patch( "cosa.memory.question_embeddings_table.ConfigurationManager", return_value=cfg ), \
         patch( "cosa.memory.question_embeddings_table.EmbeddingManager" ), \
         patch( "cosa.memory.question_embeddings_table.get_embedding_provider", return_value=provider ):
        table = QuestionEmbeddingsTable( debug=debug, verbose=verbose )
    return table, provider


def _patch_repo():
    """Patch get_db (ctx mgr → mock session) + the repo class; return (repo_instance, ctx, repo_ctx)."""
    session   = MagicMock()
    repo_inst = MagicMock()

    @contextlib.contextmanager
    def fake_get_db():
        yield session

    ctx      = patch( "cosa.rest.db.database.get_db", fake_get_db )
    repo_ctx = patch( "cosa.rest.db.repositories.question_embedding_repository.QuestionEmbeddingRepository",
                      return_value=repo_inst )
    return repo_inst, ctx, repo_ctx


class TestInitialization( unittest.TestCase ):
    """__init__ wires config + deps and opens no connection of its own."""

    def test_init_wires_dependencies( self ):
        cfg = Mock()
        cfg.get.side_effect = _cfg_get

        with patch( "cosa.memory.question_embeddings_table.ConfigurationManager", return_value=cfg ) as cfg_cls, \
             patch( "cosa.memory.question_embeddings_table.EmbeddingManager" ) as em_cls, \
             patch( "cosa.memory.question_embeddings_table.get_embedding_provider" ) as gep:
            table = QuestionEmbeddingsTable( debug=True, verbose=True )

        cfg_cls.assert_called_once_with( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        em_cls.assert_called_once_with( debug=True, verbose=True )
        gep.assert_called_once_with( debug=True, verbose=True )
        self.assertEqual( table._embedding_dim, 768 )
        self.assertTrue( table.debug )
        self.assertTrue( table.verbose )


class TestHas( unittest.TestCase ):
    """has() delegates to the repository."""

    def test_returns_true_when_found( self ):
        table, _ = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        repo.has.return_value = True
        with ctx, repo_ctx:
            self.assertTrue( table.has( "What is 2+2?" ) )
        repo.has.assert_called_once_with( "What is 2+2?" )

    def test_returns_false_when_absent( self ):
        table, _ = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        repo.has.return_value = False
        with ctx, repo_ctx:
            self.assertFalse( table.has( "nope" ) )


class TestGetEmbedding( unittest.TestCase ):
    """get_embedding() — cache hit returns stored; miss generates but does not persist."""

    def test_cache_hit_returns_stored( self ):
        table, provider = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_embedding.return_value = _EMBEDDING
        with ctx, repo_ctx:
            self.assertEqual( table.get_embedding( "q" ), _EMBEDDING )
        provider.generate_embedding.assert_not_called()

    def test_miss_generates_but_does_not_store( self ):
        table, provider = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        repo.get_embedding.return_value = None               # cache miss
        with ctx, repo_ctx:
            result = table.get_embedding( "q" )
        self.assertEqual( result, _EMBEDDING )
        provider.generate_embedding.assert_called_once_with( "q", content_type="prose" )
        repo.add_embedding.assert_not_called()


class TestAddEmbedding( unittest.TestCase ):
    """add_embedding() delegates to the repository."""

    def test_delegates( self ):
        table, _ = _make_table()
        repo, ctx, repo_ctx = _patch_repo()
        with ctx, repo_ctx:
            self.assertIsNone( table.add_embedding( "q", _EMBEDDING ) )
        repo.add_embedding.assert_called_once_with( "q", _EMBEDDING )


class TestNoLancedbSurface( unittest.TestCase ):
    """The removal itself, pinned."""

    def test_module_does_not_import_lancedb( self ):
        import cosa.memory.question_embeddings_table as mod
        self.assertFalse( hasattr( mod, "lancedb" ) )
        self.assertFalse( hasattr( mod, "pa" ) )

    def test_lancedb_only_members_are_gone( self ):
        for name in ( "_validate_embedding_dimensions", "_create_table_if_needed", "_pg_has" ):
            self.assertFalse( hasattr( QuestionEmbeddingsTable, name ), f"{name} should be deleted" )


if __name__ == "__main__":
    unittest.main()
