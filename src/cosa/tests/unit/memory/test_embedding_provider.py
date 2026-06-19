"""
Unit tests for cosa.memory.embedding_provider.EmbeddingProvider.

EmbeddingProvider is a thread-safe singleton routing layer that dispatches
embedding generation to: the OpenAI EmbeddingManager, the in-process GPU
engines (when this process declared ownership), or an HTTP fallback to the
FastAPI / lupin-model-server embeddings endpoints. Tests cover:

- Singleton identity + double-checked __init__ / __new__ guards
- declare_in_process_engine_owner class-flag flip
- Lazy engine accessors (_get_openai/_code/_prose_engine)
- URL/key resolvers (_resolve_server_url / _resolve_model_server_url /
  _http_api_key / _resolve_http_target)
- HTTP fallbacks (_generate_embedding_via_http + batch): no-key / RequestException
  / non-200 / success / malformed-json arms
- generate_embedding + generate_embeddings_batch routing matrix
  (openai prose/code-warning, in-process owner code/prose, non-owner HTTP,
  empty-embedding metric edge, debug+verbose log)
- provider / dimensions / code_dimensions properties
- _record_metric (new + existing key), get_metrics_summary (normal + count==0 /
  min==inf defensive arms), reset_metrics
- get_embedding_provider module function

SINGLETON HYGIENE: _instance + class-level _is_in_process_engine_owner are reset
in setUp/tearDown so tests are order-independent and do not leak owner state.

ConfigurationManager / engine imports / requests / du.get_api_key all mocked at
the boundary — no real config, GPU, network, or key-file dependency.

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, memory group, provider/engine lane).
"""

import unittest
from unittest.mock import Mock, patch

from cosa.memory.embedding_provider import EmbeddingProvider, get_embedding_provider

_VEC = [ 0.1 ] * 768


def _reset_singleton():
    EmbeddingProvider._instance                   = None
    EmbeddingProvider._is_in_process_engine_owner = False


def _build_provider( provider_value="openai", owner=False, debug=False, verbose=False ):
    """Construct a fresh EmbeddingProvider with ConfigurationManager mocked."""
    _reset_singleton()
    EmbeddingProvider._is_in_process_engine_owner = owner
    mock_cfg = Mock()
    mock_cfg.get.side_effect = lambda key, default=None, **kw: {
        "embedding provider"   : provider_value,
        "embedding dimensions" : "768",
    }.get( key, default )
    with patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=mock_cfg ):
        return EmbeddingProvider( debug=debug, verbose=verbose )


class TestSingletonInitAndOwner( unittest.TestCase ):
    """Singleton/init guards + owner flag + lazy engines."""

    def setUp( self ):
        _reset_singleton()

    def tearDown( self ):
        _reset_singleton()

    def test_singleton_identity( self ):
        """get_embedding_provider returns the cached singleton."""
        a = _build_provider()
        b = get_embedding_provider()        # __init__ guard early-returns
        self.assertIs( a, b )

    def test_init_idempotent( self ):
        """A second __init__ on the cached instance is a no-op (config read once)."""
        _reset_singleton()
        mock_cfg = Mock()
        mock_cfg.get.side_effect = lambda key, default=None, **kw: {
            "embedding provider": "local", "embedding dimensions": "768"
        }.get( key, default )
        with patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=mock_cfg ) as mock_cm:
            first  = EmbeddingProvider()
            second = EmbeddingProvider()
        self.assertIs( first, second )
        mock_cm.assert_called_once()
        self.assertEqual( first._provider, "local" )

    def test_init_debug_prints( self ):
        """debug=True logs the init line."""
        _reset_singleton()
        mock_cfg = Mock()
        mock_cfg.get.side_effect = lambda key, default=None, **kw: { "embedding provider": "openai" }.get( key, default )
        with patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=mock_cfg ), \
             patch( "builtins.print" ) as mock_print:
            EmbeddingProvider( debug=True )
        self.assertTrue( mock_print.called )

    def test_new_double_checked_lock_inner_guard( self ):
        """Inner double-checked guard: instance appears while acquiring the lock."""
        _reset_singleton()
        sentinel = Mock()

        class _SettingLock:
            def __enter__( self_lock ):
                EmbeddingProvider._instance = sentinel
                return self_lock

            def __exit__( self_lock, *exc ):
                return False

        with patch.object( EmbeddingProvider, "_lock", _SettingLock() ):
            result = EmbeddingProvider()
        self.assertIs( result, sentinel )

    def test_declare_in_process_engine_owner( self ):
        """declare_in_process_engine_owner flips the class flag True."""
        _reset_singleton()
        EmbeddingProvider.declare_in_process_engine_owner()
        self.assertTrue( EmbeddingProvider._is_in_process_engine_owner )

    def test_lazy_openai_engine( self ):
        """_get_openai_engine lazy-loads once and caches."""
        provider = _build_provider()
        with patch( "cosa.memory.embedding_manager.EmbeddingManager", return_value=Mock() ) as mock_em:
            e1 = provider._get_openai_engine()
            e2 = provider._get_openai_engine()
        self.assertIs( e1, e2 )
        mock_em.assert_called_once()

    def test_lazy_code_engine( self ):
        """_get_code_engine lazy-loads via get_code_engine once."""
        provider = _build_provider()
        with patch( "cosa.memory.local_embedding_engine.get_code_engine", return_value=Mock() ) as mock_get:
            e1 = provider._get_code_engine()
            e2 = provider._get_code_engine()
        self.assertIs( e1, e2 )
        mock_get.assert_called_once()

    def test_lazy_prose_engine( self ):
        """_get_prose_engine lazy-loads via get_prose_engine once."""
        provider = _build_provider()
        with patch( "cosa.memory.local_embedding_engine.get_prose_engine", return_value=Mock() ) as mock_get:
            e1 = provider._get_prose_engine()
            e2 = provider._get_prose_engine()
        self.assertIs( e1, e2 )
        mock_get.assert_called_once()


class TestUrlAndKeyResolvers( unittest.TestCase ):
    """_resolve_server_url / _resolve_model_server_url / _http_api_key / _resolve_http_target."""

    def test_resolve_server_url_env_and_default( self ):
        """Env value wins (stripped); blank/unset → localhost:7999 default."""
        with patch.dict( "os.environ", { "LUPIN_APP_SERVER_URL": "  http://x:8000  " } ):
            self.assertEqual( EmbeddingProvider._resolve_server_url(), "http://x:8000" )
        with patch.dict( "os.environ", { "LUPIN_APP_SERVER_URL": "" } ):
            self.assertEqual( EmbeddingProvider._resolve_server_url(), "http://localhost:7999" )

    def test_resolve_model_server_url_env( self ):
        """LUPIN_MODEL_SERVER_URL set → returned."""
        with patch.dict( "os.environ", { "LUPIN_MODEL_SERVER_URL": "http://ms:7998" } ):
            self.assertEqual( EmbeddingProvider._resolve_model_server_url(), "http://ms:7998" )

    def test_resolve_model_server_url_ini( self ):
        """Env unset, INI set → INI value."""
        mock_cfg = Mock()
        mock_cfg.get.return_value = "http://ini-ms:7998"
        with patch.dict( "os.environ", { "LUPIN_MODEL_SERVER_URL": "" } ), \
             patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=mock_cfg ):
            self.assertEqual( EmbeddingProvider._resolve_model_server_url(), "http://ini-ms:7998" )

    def test_resolve_model_server_url_none_when_ini_blank( self ):
        """Env unset, INI blank → None (legacy FastAPI fallback)."""
        mock_cfg = Mock()
        mock_cfg.get.return_value = "   "
        with patch.dict( "os.environ", { "LUPIN_MODEL_SERVER_URL": "" } ), \
             patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=mock_cfg ):
            self.assertIsNone( EmbeddingProvider._resolve_model_server_url() )

    def test_resolve_model_server_url_none_on_exception( self ):
        """ConfigurationManager raising → None (never raises)."""
        with patch.dict( "os.environ", { "LUPIN_MODEL_SERVER_URL": "" } ), \
             patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=Exception( "boom" ) ):
            self.assertIsNone( EmbeddingProvider._resolve_model_server_url() )

    def test_http_api_key_success_and_failure( self ):
        """du.get_api_key success → key; raising → None."""
        with patch( "cosa.memory.embedding_provider.du.get_api_key", return_value="ck_live_x" ):
            self.assertEqual( EmbeddingProvider._http_api_key(), "ck_live_x" )
        with patch( "cosa.memory.embedding_provider.du.get_api_key", side_effect=Exception( "no file" ) ):
            self.assertIsNone( EmbeddingProvider._http_api_key() )

    def test_resolve_http_target_model_server( self ):
        """Model-server URL present → (model_url, key, '/embeddings')."""
        with patch.object( EmbeddingProvider, "_resolve_model_server_url", return_value="http://ms:7998" ), \
             patch.object( EmbeddingProvider, "_http_api_key", return_value="k" ):
            base, key, prefix = EmbeddingProvider._resolve_http_target()
        self.assertEqual( ( base, key, prefix ), ( "http://ms:7998", "k", "/embeddings" ) )

    def test_resolve_http_target_fastapi_fallback( self ):
        """Model-server URL absent → (fastapi_url, key, '/api/embeddings')."""
        with patch.object( EmbeddingProvider, "_resolve_model_server_url", return_value=None ), \
             patch.object( EmbeddingProvider, "_resolve_server_url", return_value="http://localhost:7999" ), \
             patch.object( EmbeddingProvider, "_http_api_key", return_value="k" ):
            base, key, prefix = EmbeddingProvider._resolve_http_target()
        self.assertEqual( ( base, key, prefix ), ( "http://localhost:7999", "k", "/api/embeddings" ) )


class TestHttpFallbacks( unittest.TestCase ):
    """_generate_embedding_via_http + _generate_embeddings_batch_via_http arms."""

    def setUp( self ):
        self.provider = _build_provider( provider_value="local", owner=False )

    def tearDown( self ):
        _reset_singleton()

    # ---- single ----
    def test_single_no_key_raises( self ):
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", None, "/api/embeddings" ) ):
            with self.assertRaises( RuntimeError ):
                self.provider._generate_embedding_via_http( "hi", "prose" )

    def test_single_request_exception_raises( self ):
        import requests
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", "k", "/api/embeddings" ) ), \
             patch( "requests.post", side_effect=requests.RequestException( "down" ) ):
            with self.assertRaises( RuntimeError ):
                self.provider._generate_embedding_via_http( "hi", "prose" )

    def test_single_non_200_raises( self ):
        bad = Mock(); bad.status_code = 500; bad.text = "err"
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", "k", "/api/embeddings" ) ), \
             patch( "requests.post", return_value=bad ):
            with self.assertRaises( RuntimeError ):
                self.provider._generate_embedding_via_http( "hi", "prose" )

    def test_single_success( self ):
        ok = Mock(); ok.status_code = 200; ok.json.return_value = { "embedding": _VEC }
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", "k", "/api/embeddings" ) ), \
             patch( "requests.post", return_value=ok ):
            result = self.provider._generate_embedding_via_http( "hi", "prose" )
        self.assertEqual( result, _VEC )

    def test_single_malformed_raises( self ):
        ok = Mock(); ok.status_code = 200; ok.json.return_value = { "nope": 1 }
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", "k", "/api/embeddings" ) ), \
             patch( "requests.post", return_value=ok ):
            with self.assertRaises( RuntimeError ):
                self.provider._generate_embedding_via_http( "hi", "prose" )

    # ---- batch ----
    def test_batch_no_key_raises( self ):
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", None, "/api/embeddings" ) ):
            with self.assertRaises( RuntimeError ):
                self.provider._generate_embeddings_batch_via_http( [ "a" ], "prose" )

    def test_batch_request_exception_raises( self ):
        import requests
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", "k", "/api/embeddings" ) ), \
             patch( "requests.post", side_effect=requests.RequestException( "down" ) ):
            with self.assertRaises( RuntimeError ):
                self.provider._generate_embeddings_batch_via_http( [ "a" ], "prose" )

    def test_batch_non_200_raises( self ):
        bad = Mock(); bad.status_code = 503; bad.text = "err"
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", "k", "/api/embeddings" ) ), \
             patch( "requests.post", return_value=bad ):
            with self.assertRaises( RuntimeError ):
                self.provider._generate_embeddings_batch_via_http( [ "a" ], "prose" )

    def test_batch_success( self ):
        ok = Mock(); ok.status_code = 200; ok.json.return_value = { "embeddings": [ _VEC, _VEC ] }
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", "k", "/api/embeddings" ) ), \
             patch( "requests.post", return_value=ok ):
            result = self.provider._generate_embeddings_batch_via_http( [ "a", "b" ], "prose" )
        self.assertEqual( result, [ _VEC, _VEC ] )

    def test_batch_malformed_raises( self ):
        ok = Mock(); ok.status_code = 200; ok.json.return_value = { "nope": 1 }
        with patch.object( self.provider, "_resolve_http_target", return_value=( "http://h", "k", "/api/embeddings" ) ), \
             patch( "requests.post", return_value=ok ):
            with self.assertRaises( RuntimeError ):
                self.provider._generate_embeddings_batch_via_http( [ "a" ], "prose" )


class TestGenerateEmbeddingRouting( unittest.TestCase ):
    """generate_embedding routing matrix + metric/log edges."""

    def tearDown( self ):
        _reset_singleton()

    def test_openai_prose_debug_verbose( self ):
        """provider=openai, prose, debug+verbose → OpenAI engine + log line."""
        provider = _build_provider( provider_value="openai", debug=True, verbose=True )
        engine = Mock(); engine.generate_embedding.return_value = _VEC
        with patch.object( provider, "_get_openai_engine", return_value=engine ), \
             patch( "builtins.print" ):
            result = provider.generate_embedding( "hello", content_type="prose" )
        self.assertEqual( result, _VEC )
        engine.generate_embedding.assert_called_once()

    def test_openai_code_warns( self ):
        """provider=openai, code → prints the unsupported-code warning, still embeds."""
        provider = _build_provider( provider_value="openai" )
        engine = Mock(); engine.generate_embedding.return_value = _VEC
        with patch.object( provider, "_get_openai_engine", return_value=engine ), \
             patch( "builtins.print" ) as mock_print:
            result = provider.generate_embedding( "x=1", content_type="code" )
        self.assertEqual( result, _VEC )
        self.assertTrue( mock_print.called )

    def test_owner_code_uses_code_engine( self ):
        """provider=local + owner + code → in-process code engine."""
        provider = _build_provider( provider_value="local", owner=True )
        engine = Mock(); engine.encode_code.return_value = [ _VEC ]
        with patch.object( provider, "_get_code_engine", return_value=engine ):
            result = provider.generate_embedding( "x=1", content_type="code" )
        self.assertEqual( result, _VEC )
        engine.encode_code.assert_called_once_with( [ "x=1" ] )

    def test_owner_prose_uses_prose_engine( self ):
        """provider=local + owner + prose → in-process prose engine (encode_query)."""
        provider = _build_provider( provider_value="local", owner=True )
        engine = Mock(); engine.encode_query.return_value = [ _VEC ]
        with patch.object( provider, "_get_prose_engine", return_value=engine ):
            result = provider.generate_embedding( "hello", content_type="prose" )
        self.assertEqual( result, _VEC )
        engine.encode_query.assert_called_once_with( [ "hello" ] )

    def test_non_owner_routes_http( self ):
        """provider=local + non-owner → HTTP fallback."""
        provider = _build_provider( provider_value="local", owner=False )
        with patch.object( provider, "_generate_embedding_via_http", return_value=_VEC ) as mock_http:
            result = provider.generate_embedding( "hello", content_type="prose" )
        self.assertEqual( result, _VEC )
        mock_http.assert_called_once_with( "hello", "prose" )

    def test_empty_embedding_records_zero_dims( self ):
        """An empty embedding result → metric records 0 dims (falsy-embedding arm)."""
        provider = _build_provider( provider_value="local", owner=False )
        with patch.object( provider, "_generate_embedding_via_http", return_value=[] ):
            result = provider.generate_embedding( "hello", content_type="prose" )
        self.assertEqual( result, [] )
        self.assertEqual( provider.get_metrics_summary()[ "local_prose" ][ "dims" ], 0 )


class TestGenerateEmbeddingsBatchRouting( unittest.TestCase ):
    """generate_embeddings_batch routing matrix + metric edge."""

    def tearDown( self ):
        _reset_singleton()

    def test_openai_prose_loop( self ):
        """provider=openai prose → per-text loop over the OpenAI engine."""
        provider = _build_provider( provider_value="openai" )
        engine = Mock(); engine.generate_embedding.return_value = _VEC
        with patch.object( provider, "_get_openai_engine", return_value=engine ):
            result = provider.generate_embeddings_batch( [ "a", "b" ], content_type="prose" )
        self.assertEqual( result, [ _VEC, _VEC ] )
        self.assertEqual( engine.generate_embedding.call_count, 2 )

    def test_openai_code_warns( self ):
        """provider=openai code → warning + loop."""
        provider = _build_provider( provider_value="openai" )
        engine = Mock(); engine.generate_embedding.return_value = _VEC
        with patch.object( provider, "_get_openai_engine", return_value=engine ), \
             patch( "builtins.print" ) as mock_print:
            result = provider.generate_embeddings_batch( [ "x=1" ], content_type="code" )
        self.assertEqual( result, [ _VEC ] )
        self.assertTrue( mock_print.called )

    def test_owner_code_batch( self ):
        """provider=local + owner + code → code engine batch."""
        provider = _build_provider( provider_value="local", owner=True )
        engine = Mock(); engine.encode_code.return_value = [ _VEC, _VEC ]
        with patch.object( provider, "_get_code_engine", return_value=engine ):
            result = provider.generate_embeddings_batch( [ "x=1", "y=2" ], content_type="code" )
        self.assertEqual( result, [ _VEC, _VEC ] )

    def test_owner_prose_batch( self ):
        """provider=local + owner + prose → prose engine batch."""
        provider = _build_provider( provider_value="local", owner=True )
        engine = Mock(); engine.encode_query.return_value = [ _VEC ]
        with patch.object( provider, "_get_prose_engine", return_value=engine ):
            result = provider.generate_embeddings_batch( [ "hi" ], content_type="prose" )
        self.assertEqual( result, [ _VEC ] )

    def test_non_owner_batch_http( self ):
        """provider=local + non-owner → HTTP batch fallback."""
        provider = _build_provider( provider_value="local", owner=False )
        with patch.object( provider, "_generate_embeddings_batch_via_http", return_value=[ _VEC ] ) as mock_http:
            result = provider.generate_embeddings_batch( [ "hi" ], content_type="prose" )
        self.assertEqual( result, [ _VEC ] )
        mock_http.assert_called_once_with( [ "hi" ], "prose" )

    def test_empty_batch_records_zero_dims( self ):
        """Empty batch result → metric records 0 dims (falsy-embeddings arm)."""
        provider = _build_provider( provider_value="local", owner=False )
        with patch.object( provider, "_generate_embeddings_batch_via_http", return_value=[] ):
            result = provider.generate_embeddings_batch( [ "hi" ], content_type="prose" )
        self.assertEqual( result, [] )
        self.assertEqual( provider.get_metrics_summary()[ "local_prose" ][ "dims" ], 0 )


class TestPropertiesAndMetrics( unittest.TestCase ):
    """provider / dimensions / code_dimensions + metric recording/summary/reset."""

    def tearDown( self ):
        _reset_singleton()

    def test_provider_property( self ):
        provider = _build_provider( provider_value="local" )
        self.assertEqual( provider.provider, "local" )

    def test_dimensions_properties( self ):
        provider = _build_provider()
        self.assertEqual( provider.dimensions, 768 )
        self.assertEqual( provider.code_dimensions, 768 )

    def test_record_metric_new_then_existing_key( self ):
        """First record creates the key; second updates count/total/min/max."""
        provider = _build_provider()
        provider._record_metric( "prose", "openai", 10.0, 768 )
        provider._record_metric( "prose", "openai", 30.0, 768 )
        m = provider._metrics[ "openai_prose" ]
        self.assertEqual( m[ "count" ], 2 )
        self.assertEqual( m[ "total_ms" ], 40.0 )
        self.assertEqual( m[ "min_ms" ], 10.0 )
        self.assertEqual( m[ "max_ms" ], 30.0 )

    def test_get_metrics_summary_normal_and_defensive_edges( self ):
        """Normal key (count>0, min!=inf) + injected defensive key (count==0, min==inf)."""
        provider = _build_provider()
        provider._record_metric( "prose", "openai", 12.0, 768 )
        provider._metrics[ "edge_key" ] = {
            "count": 0, "total_ms": 0.0, "min_ms": float( "inf" ), "max_ms": 0.0, "dims": 0
        }
        summary = provider.get_metrics_summary()
        self.assertEqual( summary[ "openai_prose" ][ "count" ], 1 )
        self.assertEqual( summary[ "openai_prose" ][ "avg_ms" ], 12.0 )
        self.assertEqual( summary[ "edge_key" ][ "avg_ms" ], 0 )      # count==0 else arm
        self.assertEqual( summary[ "edge_key" ][ "min_ms" ], 0 )      # min==inf else arm

    def test_reset_metrics( self ):
        provider = _build_provider()
        provider._record_metric( "prose", "openai", 5.0, 768 )
        provider.reset_metrics()
        self.assertEqual( provider._metrics, {} )


if __name__ == "__main__":
    unittest.main()
