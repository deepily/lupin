"""
Unit tests for cosa.memory.embedding_manager.EmbeddingManager (singleton).

REWRITTEN 2026-05-31 by Sam 🎙️ (memory takeover, CoSA coverage campaign). The
prior tests patched EmbeddingCacheTable / GistNormalizer on their SOURCE modules
(cosa.memory.embedding_cache_table / cosa.memory.gist_normalizer) — but
embedding_manager binds them locally, so those patches never took and __init__
did real cache/spaCy I/O. Fixed to patch the MODULE-BOUND names
(cosa.memory.embedding_manager.{EmbeddingCacheTable,GistNormalizer}). Also
corrected the stale embeddings.create assertion (the real call passes
`dimensions=<embedding dim>`).

The singleton is reset in setUp/tearDown for isolation; the full ctor dep chain
(ConfigurationManager [per-key], EmbeddingCacheTable, GistNormalizer,
_load_reverse_mappings file reads) is mocked. Reviewed by Mr. Radio (no
self-audit).
"""
import threading
import unittest
from unittest.mock import Mock, patch

from cosa.memory.embedding_manager import (
    EmbeddingManager, get_embedding_manager, generate_embedding,
)


def _cfg( values ):
    m = Mock()
    m.get.side_effect = lambda key, default=None, **kw: values.get( key, default )
    return m


def _build( config_values, normalized_gist="normalized text" ):
    """Construct a fresh EmbeddingManager with the full ctor chain mocked."""
    EmbeddingManager._instance = None
    cfg = _cfg( config_values )
    cache = Mock()
    normalizer = Mock()
    normalizer.get_normalized_gist.return_value = normalized_gist
    with patch( "cosa.memory.embedding_manager.ConfigurationManager", return_value=cfg ), \
         patch( "cosa.memory.embedding_manager.EmbeddingCacheTable", return_value=cache ), \
         patch( "cosa.memory.embedding_manager.GistNormalizer", return_value=normalizer ), \
         patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
         patch( "cosa.utils.util.get_file_as_dictionary", return_value={} ), \
         patch( "builtins.print" ):
        mgr = EmbeddingManager( debug=False )
    return mgr, cfg, cache, normalizer


class _Base( unittest.TestCase ):
    def setUp( self ):
        EmbeddingManager._instance = None
        EmbeddingManager._lock = threading.Lock()

    def tearDown( self ):
        EmbeddingManager._instance = None


class TestSingleton( _Base ):
    """__new__ enforces a single shared instance, thread-safely."""

    def test_same_instance_returned( self ):
        mgr1, *_ = _build( { "expand symbols to words": False } )
        mgr2 = EmbeddingManager()                  # already initialized → same object
        self.assertIs( mgr1, mgr2 )
        self.assertTrue( mgr1._initialized )

    def test_thread_safety_single_instance( self ):
        EmbeddingManager._instance = None
        instances = []
        with patch( "cosa.memory.embedding_manager.ConfigurationManager", return_value=_cfg( {} ) ), \
             patch( "cosa.memory.embedding_manager.EmbeddingCacheTable", return_value=Mock() ), \
             patch( "cosa.memory.embedding_manager.GistNormalizer", return_value=Mock() ), \
             patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
             patch( "cosa.utils.util.get_file_as_dictionary", return_value={} ), \
             patch( "builtins.print" ):
            def make():
                instances.append( EmbeddingManager() )
            threads = [ threading.Thread( target=make ) for _ in range( 5 ) ]
            for t in threads: t.start()
            for t in threads: t.join()
        self.assertEqual( len( instances ), 5 )
        for inst in instances[ 1: ]:
            self.assertIs( inst, instances[ 0 ] )


class TestNormalizeTextForCache( _Base ):
    """normalize_text_for_cache delegates to GistNormalizer + config-gated expansion."""

    def test_without_expansion_returns_gist( self ):
        mgr, cfg, _, normalizer = _build( { "expand symbols to words": False } )
        result = mgr.normalize_text_for_cache( "What's the time?" )
        normalizer.get_normalized_gist.assert_called_once_with( "What's the time?" )
        self.assertEqual( result, "normalized text" )
        cfg.get.assert_called_with( "expand symbols to words", default=False, return_type="boolean" )

    def test_with_expansion_completes( self ):
        mgr, _, _, normalizer = _build( { "expand symbols to words": True }, normalized_gist="what is 2+2" )
        result = mgr.normalize_text_for_cache( "What is 2+2?" )
        normalizer.get_normalized_gist.assert_called_once_with( "What is 2+2?" )
        self.assertIsInstance( result, str )


class TestGenerateEmbedding( _Base ):
    """generate_embedding — cache hit, cache miss → OpenAI, no-normalize, errors."""

    def test_cache_hit_skips_api( self ):
        mgr, _, cache, _ = _build( { "expand symbols to words": False } )
        cache.get_cached_embedding.return_value = [ 0.1, 0.2, 0.3 ]
        result = mgr.generate_embedding( "Hello!" )
        cache.get_cached_embedding.assert_called_once_with( "normalized text" )
        self.assertEqual( result, [ 0.1, 0.2, 0.3 ] )
        cache.cache_embedding.assert_not_called()

    def test_cache_miss_calls_openai_and_caches( self ):
        mgr, _, cache, _ = _build( {
            "expand symbols to words": False,
            "embedding model name": "text-embedding-3-small",
            "embedding dimensions": "768",
        } )
        cache.get_cached_embedding.return_value = None
        embedding = [ 0.4, 0.5, 0.6 ]
        response = Mock()
        response.data = [ Mock( embedding=embedding ) ]
        with patch( "cosa.utils.util.get_api_key", return_value="sk-test" ), \
             patch( "openai.OpenAI" ) as openai_cls:
            client = Mock()
            client.embeddings.create.return_value = response
            openai_cls.return_value = client
            result = mgr.generate_embedding( "Hello!" )
        client.embeddings.create.assert_called_once_with(
            input="normalized text", model="text-embedding-3-small", dimensions=768
        )
        self.assertEqual( result, embedding )
        cache.cache_embedding.assert_called_once_with( "normalized text", embedding )

    def test_no_normalization_uses_exact_text( self ):
        mgr, _, cache, normalizer = _build( {
            "embedding model name": "text-embedding-3-small",
            "embedding dimensions": "768",
        } )
        cache.get_cached_embedding.return_value = None
        embedding = [ 0.7, 0.8 ]
        response = Mock()
        response.data = [ Mock( embedding=embedding ) ]
        with patch( "cosa.utils.util.get_api_key", return_value="sk-test" ), \
             patch( "openai.OpenAI" ) as openai_cls:
            client = Mock()
            client.embeddings.create.return_value = response
            openai_cls.return_value = client
            result = mgr.generate_embedding( "Hello World!", normalize_for_cache=False )
        cache.get_cached_embedding.assert_called_once_with( "Hello World!" )
        client.embeddings.create.assert_called_once_with(
            input="Hello World!", model="text-embedding-3-small", dimensions=768
        )
        normalizer.get_normalized_gist.assert_not_called()
        self.assertEqual( result, embedding )

    def test_missing_model_returns_empty( self ):
        mgr, _, cache, _ = _build( { "expand symbols to words": False } )   # no "embedding model name"
        cache.get_cached_embedding.return_value = None
        with patch( "builtins.print" ):
            result = mgr.generate_embedding( "Hello!" )
        self.assertEqual( result, [] )

    def test_api_error_returns_empty( self ):
        mgr, _, cache, _ = _build( {
            "expand symbols to words": False,
            "embedding model name": "text-embedding-3-small",
            "embedding dimensions": "768",
        } )
        cache.get_cached_embedding.return_value = None
        with patch( "cosa.utils.util.get_api_key", return_value="sk-test" ), \
             patch( "openai.OpenAI" ) as openai_cls, \
             patch( "builtins.print" ):
            client = Mock()
            client.embeddings.create.side_effect = RuntimeError( "api down" )
            openai_cls.return_value = client
            result = mgr.generate_embedding( "Hello!" )
        self.assertEqual( result, [] )


class TestConvenienceFunctions( _Base ):
    """get_embedding_manager + module-level generate_embedding."""

    def test_get_embedding_manager_returns_singleton( self ):
        mgr1, *_ = _build( { "expand symbols to words": False } )
        with patch( "cosa.memory.embedding_manager.ConfigurationManager", return_value=_cfg( {} ) ), \
             patch( "cosa.memory.embedding_manager.EmbeddingCacheTable", return_value=Mock() ), \
             patch( "cosa.memory.embedding_manager.GistNormalizer", return_value=Mock() ), \
             patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
             patch( "cosa.utils.util.get_file_as_dictionary", return_value={} ), \
             patch( "builtins.print" ):
            mgr2 = get_embedding_manager()
        self.assertIs( mgr1, mgr2 )

    def test_module_generate_embedding_delegates( self ):
        mgr, _, cache, _ = _build( { "expand symbols to words": False } )
        cache.get_cached_embedding.return_value = [ 9.0 ]
        result = generate_embedding( "Hello!" )       # reuses the singleton built above
        self.assertEqual( result, [ 9.0 ] )


if __name__ == "__main__":
    unittest.main()
