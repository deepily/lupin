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


def _build_ex( config_values, normalized_gist="normalized text", debug=False, verbose=False,
               file_dict=None, file_raises=False ):
    """Like _build but with debug/verbose + control over the dictionary-file load."""
    EmbeddingManager._instance = None
    cfg        = _cfg( config_values )
    cache      = Mock()
    normalizer = Mock()
    normalizer.get_normalized_gist.return_value = normalized_gist
    gfad_kwargs = ( { "side_effect": RuntimeError( "dict file missing" ) } if file_raises
                    else { "return_value": file_dict if file_dict is not None else {} } )
    with patch( "cosa.memory.embedding_manager.ConfigurationManager", return_value=cfg ), \
         patch( "cosa.memory.embedding_manager.EmbeddingCacheTable", return_value=cache ), \
         patch( "cosa.memory.embedding_manager.GistNormalizer", return_value=normalizer ), \
         patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
         patch( "cosa.utils.util.get_file_as_dictionary", **gfad_kwargs ), \
         patch( "cosa.memory.embedding_manager.du.print_stack_trace" ), \
         patch( "builtins.print" ):
        mgr = EmbeddingManager( debug=debug, verbose=verbose )
    return mgr, cfg, cache, normalizer


class TestInitAndLoadBranches( _Base ):
    """__new__ double-checked lock + _load_reverse_mappings debug/exception arcs."""

    def test_double_checked_lock_returns_instance_set_under_lock( self ):
        # Simulate another thread setting _instance between the outer check and the
        # lock acquisition: the inner `if _instance is None` takes its False arc.
        sentinel = object.__new__( EmbeddingManager )
        sentinel._initialized = True

        class Gate:
            def __enter__( self ):
                EmbeddingManager._instance = sentinel
                return self
            def __exit__( self, *a ):
                return False

        EmbeddingManager._instance = None
        EmbeddingManager._lock     = Gate()
        result = EmbeddingManager()
        self.assertIs( result, sentinel )

    def test_load_reverse_mappings_debug_prints( self ):
        mgr, *_ = _build_ex( {}, debug=True, file_dict={ "and": "&" } )
        self.assertEqual( mgr._reverse_punctuation, { "&": "and" } )

    def test_load_reverse_mappings_exception_falls_back_to_empty( self ):
        mgr, *_ = _build_ex( {}, debug=True, file_raises=True )
        self.assertEqual( mgr._reverse_punctuation, {} )
        self.assertEqual( mgr._reverse_numbers, {} )
        self.assertEqual( mgr._reverse_domains, {} )


class TestNormalizeBranches( _Base ):
    """normalize_text_for_cache expansion loops + debug + exception arcs."""

    def test_explicit_expand_applies_reverse_maps( self ):
        mgr, *_ = _build_ex( {}, normalized_gist="2 + 2 .com", debug=True, verbose=True )
        # Each map mixes a present token (replaced) with an absent one (loop-continues).
        mgr._reverse_punctuation = { "+": "plus", " ": "space", "@": "at" }   # space skipped, @ absent
        mgr._reverse_numbers     = { "2": "two", "9": "nine" }                # 9 absent
        mgr._reverse_domains     = { ".com": "dot com", ".org": "dot org" }   # .org absent
        with patch( "builtins.print" ):
            result = mgr.normalize_text_for_cache( "2 + 2 .com", expand_symbols_to_words=True )
        self.assertIn( "plus", result )
        self.assertIn( "two", result )

    def test_debug_verbose_prints_normalization( self ):
        mgr, *_ = _build_ex( { "expand symbols to words": False }, debug=True, verbose=True )
        with patch( "builtins.print" ):
            result = mgr.normalize_text_for_cache( "hello" )
        self.assertEqual( result, "normalized text" )

    def test_normalization_exception_returns_lowered_text( self ):
        mgr, _, _, normalizer = _build_ex( {}, debug=True, verbose=True )
        normalizer.get_normalized_gist.side_effect = RuntimeError( "spaCy down" )
        with patch( "cosa.memory.embedding_manager.du.print_stack_trace" ), patch( "builtins.print" ):
            result = mgr.normalize_text_for_cache( "MixedCase" )
        self.assertEqual( result, "mixedcase" )


class TestGenerateEmbeddingBranches( _Base ):
    """generate_embedding debug prints + NotFoundError handler arcs."""

    _MODEL_CFG = {
        "expand symbols to words": False,
        "embedding model name": "text-embedding-3-small",
        "embedding dimensions": "768",
    }

    def test_debug_verbose_cache_miss_success_prints( self ):
        mgr, _, cache, _ = _build_ex( self._MODEL_CFG, debug=True, verbose=True )
        cache.get_cached_embedding.return_value = None
        response = Mock(); response.data = [ Mock( embedding=[ 0.1, 0.2 ] ) ]
        with patch( "cosa.utils.util.get_api_key", return_value="sk-test" ), \
             patch( "openai.OpenAI" ) as cls, patch( "builtins.print" ):
            cls.return_value.embeddings.create.return_value = response
            result = mgr.generate_embedding( "Hello!" )
        self.assertEqual( result, [ 0.1, 0.2 ] )

    def test_debug_verbose_cache_hit_prints( self ):
        mgr, _, cache, _ = _build_ex( { "expand symbols to words": False }, debug=True, verbose=True )
        cache.get_cached_embedding.return_value = [ 0.9 ]
        with patch( "builtins.print" ):
            result = mgr.generate_embedding( "Hello!" )
        self.assertEqual( result, [ 0.9 ] )

    def test_debug_verbose_exact_key_no_normalize( self ):
        mgr, _, cache, _ = _build_ex( { "expand symbols to words": False }, debug=True, verbose=True )
        cache.get_cached_embedding.return_value = [ 0.5 ]
        with patch( "builtins.print" ):
            result = mgr.generate_embedding( "Hello!", normalize_for_cache=False )
        cache.get_cached_embedding.assert_called_once_with( "Hello!" )
        self.assertEqual( result, [ 0.5 ] )

    def test_not_found_error_returns_empty( self ):
        mgr, _, cache, _ = _build_ex( self._MODEL_CFG )
        cache.get_cached_embedding.return_value = None

        class FakeNotFound( Exception ):
            pass

        with patch( "openai.NotFoundError", FakeNotFound ), \
             patch( "cosa.utils.util.get_api_key", return_value="sk-test" ), \
             patch( "openai.OpenAI" ) as cls, patch( "builtins.print" ):
            cls.return_value.embeddings.create.side_effect = FakeNotFound( "404" )
            result = mgr.generate_embedding( "Hello!" )
        self.assertEqual( result, [ ] )

    def test_not_found_error_config_reread_failure( self ):
        # In the NotFound handler the model re-read can itself fail → "[UNKNOWN...]".
        EmbeddingManager._instance = None
        state = { "n": 0 }

        def cfg_get( key, default=None, **kw ):
            if key == "embedding model name":
                state[ "n" ] += 1
                if state[ "n" ] >= 2:
                    raise RuntimeError( "config gone" )
                return "text-embedding-3-small"
            return { "expand symbols to words": False, "embedding dimensions": "768" }.get( key, default )

        cfg = Mock(); cfg.get.side_effect = cfg_get
        cache = Mock(); cache.get_cached_embedding.return_value = None
        normalizer = Mock(); normalizer.get_normalized_gist.return_value = "n"

        class FakeNotFound( Exception ):
            pass

        with patch( "cosa.memory.embedding_manager.ConfigurationManager", return_value=cfg ), \
             patch( "cosa.memory.embedding_manager.EmbeddingCacheTable", return_value=cache ), \
             patch( "cosa.memory.embedding_manager.GistNormalizer", return_value=normalizer ), \
             patch( "cosa.utils.util.get_project_root", return_value="/test" ), \
             patch( "cosa.utils.util.get_file_as_dictionary", return_value={} ), \
             patch( "builtins.print" ):
            mgr = EmbeddingManager( debug=False )
            with patch( "openai.NotFoundError", FakeNotFound ), \
                 patch( "cosa.utils.util.get_api_key", return_value="sk-test" ), \
                 patch( "openai.OpenAI" ) as cls:
                cls.return_value.embeddings.create.side_effect = FakeNotFound( "404" )
                result = mgr.generate_embedding( "Hello!" )
        self.assertEqual( result, [ ] )


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
