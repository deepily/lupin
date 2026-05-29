"""
Embedding provider routing layer with performance metrics.

Routes embedding generation to the configured engine:
- "openai" -> existing EmbeddingManager (768 dims via MRL truncation)
- "local"  -> CodeEmbeddingEngine or ProseEmbeddingEngine (768 dims)
- "local" + non-FastAPI process -> HTTP route to /api/embeddings/{generate,batch}

Callers specify content_type="prose" or content_type="code" to route
to the appropriate engine when provider is "local".

Process-aware routing (added 2026-04-28):
    Inside the FastAPI process — which loaded the GPU engine singletons at
    startup — `generate_embedding()` calls those singletons directly. In any
    OTHER process (scripts, tests, CC subagents, MCP), the same call routes
    via HTTP to the FastAPI server's /api/embeddings/{generate,batch}
    endpoints. The server URL is resolved at call time from the
    LUPIN_APP_SERVER_URL environment variable so a test running on the
    :8000 test server hits :8000 (not the :7999 dev server).

    The toggle is the class-level flag `_is_in_process_engine_owner`,
    flipped True by FastAPI's main.py at startup after engines are loaded.
    Default False everywhere else means no caller accidentally grabs GPU.
"""

import os
from threading import Lock
from typing import List, Dict, Any, Optional

import cosa.utils.util as du
import cosa.utils.util_stopwatch as sw
from cosa.config.configuration_manager import ConfigurationManager


class EmbeddingProvider:
    """
    Routing layer that delegates embedding generation to the configured engine.

    Provides a unified interface for all embedding operations with
    content-type-aware routing and performance metrics collection.

    Config-driven toggling via 'embedding provider' key:
      - "openai" -> existing EmbeddingManager (1536 dims)
      - "local"  -> CodeEmbeddingEngine or ProseEmbeddingEngine (768 dims) when
        running inside the FastAPI process; HTTP route otherwise.
    """

    _instance = None
    _lock     = Lock()

    # Class-level flag controlling local-engine routing. Default False so any
    # process that imports this module routes via HTTP and does NOT lazy-load
    # GPU models. Flipped True only by FastAPI main.py after the in-process
    # engines have been eagerly loaded — ensures the GPU is owned by exactly
    # one process and every other caller HTTP-fetches embeddings from it.
    _is_in_process_engine_owner = False

    @classmethod
    def declare_in_process_engine_owner( cls ):
        """
        Mark this Python process as the owner of the in-process GPU engine
        singletons. Called by `src/fastapi_app/main.py` AFTER `get_code_engine()`
        and `get_prose_engine()` have completed their eager warmup.

        Effect: subsequent `generate_embedding()` / `generate_embeddings_batch()`
        calls in this process route directly to the in-process engine
        singletons. In every other process the flag stays False and routing
        falls back to HTTP via /api/embeddings/{generate,batch}.

        Idempotent — safe to call multiple times.

        Ensures:
            - Class-level flag is True after this call returns
            - All EmbeddingProvider instances in this process see the change
              (singleton + class-level flag means there's at most one instance
              and it picks up the new value at next routing decision)
        """
        cls._is_in_process_engine_owner = True

    def __new__( cls, debug=False, verbose=False ):
        """
        Create or return singleton instance.

        Requires:
            - Nothing

        Ensures:
            - Returns the single instance of EmbeddingProvider
            - Initializes components only once
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__( cls )
                    cls._instance._initialized = False
        return cls._instance

    def __init__( self, debug=False, verbose=False ):
        """
        Initialize the embedding provider routing layer.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set

        Ensures:
            - Reads 'embedding provider' from config
            - Lazily initializes the appropriate engine(s)
            - Sets up metrics collection

        Raises:
            - ConfigurationManager errors if env var not set
        """
        if self._initialized:
            return

        self.debug   = debug
        self.verbose = verbose

        self._config_mgr    = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._provider      = self._config_mgr.get( "embedding provider", default="openai" ).strip().lower()

        # Lazy engine references
        self._openai_engine = None
        self._code_engine   = None
        self._prose_engine  = None

        # Metrics storage: { "openai_prose": { "count": 0, "total_ms": 0, "min_ms": inf, "max_ms": 0 }, ... }
        self._metrics       = {}
        self._metrics_lock  = Lock()

        if self.debug:
            print( f"EmbeddingProvider initialized: provider={self._provider}" )

        self._initialized = True

    def _get_openai_engine( self ):
        """Lazy-load the OpenAI embedding manager."""
        if self._openai_engine is None:
            from cosa.memory.embedding_manager import EmbeddingManager
            self._openai_engine = EmbeddingManager( debug=self.debug, verbose=self.verbose )
        return self._openai_engine

    def _get_code_engine( self ):
        """Lazy-load the local code embedding engine."""
        if self._code_engine is None:
            from cosa.memory.local_embedding_engine import get_code_engine
            self._code_engine = get_code_engine( debug=self.debug, verbose=self.verbose )
        return self._code_engine

    def _get_prose_engine( self ):
        """Lazy-load the local prose embedding engine."""
        if self._prose_engine is None:
            from cosa.memory.local_embedding_engine import get_prose_engine
            self._prose_engine = get_prose_engine( debug=self.debug, verbose=self.verbose )
        return self._prose_engine

    @staticmethod
    def _resolve_server_url() -> str:
        """
        Resolve the FastAPI server URL at call time (NOT at module load).

        Read fresh from `LUPIN_APP_SERVER_URL` per-call so a test running
        on the :8000 test server can set the env var and have HTTP routing
        target :8000 dynamically — without restarting the Python process.
        Default is `http://localhost:7999` (host targeting dev server,
        and inside-container targeting the container's own bound port).

        Ensures:
            - Returns the env value when set and non-empty (stripped)
            - Returns "http://localhost:7999" otherwise
            - Never raises
        """
        url = os.environ.get( "LUPIN_APP_SERVER_URL", "" ).strip()
        return url if url else "http://localhost:7999"

    @staticmethod
    def _resolve_model_server_url() -> Optional[ str ]:
        """
        Resolve the lupin-model-server URL at call time. Returns None when
        BOTH env var AND INI key are unset → caller falls through to the
        legacy FastAPI HTTP-proxy path.

        Priority chain (mirrors SpeechToTextProvider._resolve_model_server_url):
            1. `LUPIN_MODEL_SERVER_URL` env var (compose-injected at container creation)
            2. `model server url` INI key (lupin-app.ini default)
            3. None → caller routes via legacy FastAPI URL

        Why both: `docker restart` doesn't re-read compose, so a fresh INI
        flip without a `docker compose up -d --force-recreate` would leave
        the env var unset in running containers. The INI fallback prevents
        that scenario from causing self-recursion (compute → compute →
        compute → timeout) on the FastAPI fallback URL.

        See: src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md

        Ensures:
            - Returns the env value when set and non-empty
            - Otherwise returns the INI value when set and non-empty
            - Otherwise returns None (legacy FastAPI fallback)
            - Never raises (ConfigurationManager errors caught + None returned)
        """
        url = os.environ.get( "LUPIN_MODEL_SERVER_URL", "" ).strip()
        if url:
            return url
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            cfg = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            ini = cfg.get( "model server url", default="", silent=True ).strip()
            return ini if ini else None
        except Exception:
            return None

    @staticmethod
    def _http_api_key() -> Optional[str]:
        """
        Load the X-API-Key value used for the embeddings HTTP endpoints.

        Mirrors the pattern in `prediction_engine._generate_embedding_via_http`
        — reads `src/conf/keys/notification-api-claude-code-dev` via the
        canonical `du.get_api_key()` helper (imported as `du` in this module).

        Ensures:
            - Returns the API key string if the file is present and readable
            - Returns None if the file is missing or empty
            - Never raises
        """
        try:
            return du.get_api_key( "notification-api-claude-code-dev" )
        except Exception:
            return None

    @classmethod
    def _resolve_http_target( cls ) -> tuple:
        """
        Pick the HTTP target for embedding fallback calls.

        Priority:
            1. lupin-model-server (when `LUPIN_MODEL_SERVER_URL` env is set)
            2. FastAPI server (existing behavior, `LUPIN_APP_SERVER_URL`)

        Both targets accept the SAME `ck_live_*` key from
        `src/conf/keys/notification-api-claude-code-dev` (per María's
        2026-05-16 brief — no parallel `ck_internal_*` namespace). So we
        call `_http_api_key()` for both branches; only the URL + endpoint
        prefix differ.

        Returns:
            tuple[str, Optional[str], str]: (base_url, api_key, endpoint_prefix)
                - base_url: where to POST
                - api_key: X-API-Key header value (or None → caller handles)
                - endpoint_prefix: "/embeddings" for model-server,
                                   "/api/embeddings" for the FastAPI path
                  (model-server omits the `/api/` prefix per its leaner routing)
        """
        model_server_url = cls._resolve_model_server_url()
        if model_server_url:
            return ( model_server_url, cls._http_api_key(), "/embeddings" )
        return ( cls._resolve_server_url(), cls._http_api_key(), "/api/embeddings" )

    def _generate_embedding_via_http( self, text: str, content_type: str ) -> List[float]:
        """
        Single-text embedding via HTTP fallback to /api/embeddings/generate.

        Used when this process is NOT the in-process engine owner — typically
        a test, script, or CC subagent. Routes through the FastAPI server's
        already-loaded GPU singleton instead of grabbing GPU here.

        Requires:
            - text is a non-empty string
            - content_type is "prose" or "code"
            - LUPIN_APP_SERVER_URL is reachable (default http://localhost:7999)
            - API key file at src/conf/keys/notification-api-claude-code-dev

        Ensures:
            - Returns list[float] embedding vector on success
            - Raises RuntimeError with a clear message on any failure
              (no API key, connection refused, non-200, malformed response)

        Raises:
            RuntimeError: when HTTP routing cannot complete the request
        """
        import requests

        # Phase 3.1 of the model-server carve-out: when LUPIN_MODEL_SERVER_URL
        # is set, this resolves to (model-server URL, ck_internal_* key,
        # "/embeddings"). Otherwise falls through to the existing FastAPI
        # path with the notification key + "/api/embeddings" prefix.
        # See: src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
        base_url, api_key, prefix = self._resolve_http_target()
        if not api_key:
            raise RuntimeError(
                "EmbeddingProvider HTTP fallback: no API key found. Expected one of: "
                "src/conf/keys/notification-api-claude-code-dev "
                "(used by both the FastAPI and lupin-model-server HTTP paths). "
                "Either provision the matching key file or call "
                "EmbeddingProvider.declare_in_process_engine_owner() from the GPU-loading process."
            )

        url = f"{base_url}{prefix}/generate"
        try:
            response = requests.post(
                url,
                json    = { "text": text, "content_type": content_type },
                headers = { "X-API-Key": api_key },
                timeout = 10
            )
        except requests.RequestException as e:
            raise RuntimeError(
                f"EmbeddingProvider HTTP fallback unreachable at {url}: {type( e ).__name__}: {e}"
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"EmbeddingProvider HTTP fallback returned {response.status_code} from {url}: "
                f"{response.text[:200]}"
            )

        try:
            return response.json()[ "embedding" ]
        except ( KeyError, ValueError ) as e:
            raise RuntimeError(
                f"EmbeddingProvider HTTP fallback: malformed response from {url}: {e}"
            )

    def _generate_embeddings_batch_via_http( self, texts: List[str], content_type: str ) -> List[List[float]]:
        """
        Batch embedding via HTTP fallback to /api/embeddings/batch.

        Same routing/auth contract as the single-text helper above, but uses
        the batch endpoint for throughput parity with in-process engine batch.

        Requires:
            - texts is a non-empty list of strings
            - content_type is "prose" or "code"

        Ensures:
            - Returns list of embedding vectors, in input order
            - Raises RuntimeError with a clear message on any failure

        Raises:
            RuntimeError: when HTTP routing cannot complete the request
        """
        import requests

        # Phase 3.1 carve-out: same resolver as the single-text path above.
        base_url, api_key, prefix = self._resolve_http_target()
        if not api_key:
            raise RuntimeError(
                "EmbeddingProvider HTTP batch fallback: no API key found. Expected one of: "
                "src/conf/keys/notification-api-claude-code-dev "
                "(used by both the FastAPI and lupin-model-server HTTP paths)."
            )

        url = f"{base_url}{prefix}/batch"
        try:
            response = requests.post(
                url,
                json    = { "texts": texts, "content_type": content_type },
                headers = { "X-API-Key": api_key },
                timeout = 30
            )
        except requests.RequestException as e:
            raise RuntimeError(
                f"EmbeddingProvider HTTP batch fallback unreachable at {url}: {type( e ).__name__}: {e}"
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"EmbeddingProvider HTTP batch fallback returned {response.status_code} from {url}: "
                f"{response.text[:200]}"
            )

        try:
            return response.json()[ "embeddings" ]
        except ( KeyError, ValueError ) as e:
            raise RuntimeError(
                f"EmbeddingProvider HTTP batch fallback: malformed response from {url}: {e}"
            )

    def generate_embedding( self, text, content_type="prose", normalize_for_cache=True ):
        """
        Route to the appropriate engine based on config, content_type, and
        whether this process owns the in-process engine singletons.

        Routing decision:
            - provider="openai" → OpenAI HTTP client (unchanged regardless of flag)
            - provider="local" + this process owns engines → in-process engine
            - provider="local" + this process does NOT own engines → HTTP route
              to /api/embeddings/generate on the FastAPI server (URL resolved
              dynamically from LUPIN_APP_SERVER_URL)

        Requires:
            - text is a non-empty string
            - content_type is "prose" or "code"
            - normalize_for_cache is boolean (passed through to OpenAI engine only)

        Ensures:
            - Returns list[float] embedding vector
            - Dimensions depend on provider (1536 for openai, 768 for local)
            - Records timing metrics for benchmarking
            - In non-owner contexts, no GPU model is loaded in this process

        Args:
            text: Input text to embed
            content_type: "prose" or "code" - determines which local engine to use
            normalize_for_cache: Passed through to OpenAI engine only

        Returns:
            list[float] - embedding vector

        Raises:
            RuntimeError: when HTTP routing cannot complete (no API key,
                connection refused, non-200 response). Clear failure beats
                silently grabbing GPU.
        """
        timer = sw.Stopwatch( silent=True )

        if self._provider == "openai":
            if content_type == "code":
                print( "WARNING: OpenAI provider does not support code-specific embeddings. "
                       "Using text-embedding-3-small for code content." )
            embedding = self._get_openai_engine().generate_embedding( text, normalize_for_cache=normalize_for_cache )
        elif self._is_in_process_engine_owner:
            # In-process owner: use the loaded engine singletons directly.
            if content_type == "code":
                embedding = self._get_code_engine().encode_code( [ text ] )[ 0 ]
            else:
                # prose - use encode_query for single-text embedding (query context)
                embedding = self._get_prose_engine().encode_query( [ text ] )[ 0 ]
        else:
            # Non-owner: HTTP route. No GPU touch in this process.
            embedding = self._generate_embedding_via_http( text, content_type )

        delta_ms = timer.get_delta_ms()
        self._record_metric( content_type, self._provider, delta_ms, len( embedding ) if embedding else 0 )

        if self.debug and self.verbose:
            print( f"[EmbeddingProvider] {self._provider}/{content_type}: {len( embedding ) if embedding else 0} dims in {delta_ms:.1f} ms" )

        return embedding

    def generate_embeddings_batch( self, texts, content_type="prose" ):
        """
        Generate embeddings for a batch of texts. Same process-aware routing
        as generate_embedding() — non-owner processes round-trip via HTTP
        to /api/embeddings/batch.

        Requires:
            - texts is a list of non-empty strings
            - content_type is "prose" or "code"

        Ensures:
            - Returns list of embedding vectors
            - More efficient than calling generate_embedding() in a loop for local engines
            - In non-owner contexts, no GPU model is loaded in this process

        Args:
            texts: List of input texts to embed
            content_type: "prose" or "code"

        Returns:
            list[list[float]] - list of embedding vectors

        Raises:
            RuntimeError: when HTTP routing cannot complete in non-owner context
        """
        timer = sw.Stopwatch( silent=True )

        if self._provider == "openai":
            if content_type == "code":
                print( "WARNING: OpenAI provider does not support code-specific embeddings. "
                       "Using text-embedding-3-small for code content." )
            # OpenAI engine doesn't support batch - loop
            embeddings = [ self._get_openai_engine().generate_embedding( t ) for t in texts ]
        elif self._is_in_process_engine_owner:
            if content_type == "code":
                embeddings = self._get_code_engine().encode_code( texts )
            else:
                embeddings = self._get_prose_engine().encode_query( texts )
        else:
            embeddings = self._generate_embeddings_batch_via_http( texts, content_type )

        delta_ms = timer.get_delta_ms()
        self._record_metric( content_type, self._provider, delta_ms, len( embeddings[ 0 ] ) if embeddings and embeddings[ 0 ] else 0 )

        return embeddings

    @property
    def provider( self ):
        """Return the current provider name."""
        return self._provider

    @property
    def dimensions( self ):
        """
        Return the standardized embedding dimension from config.

        Ensures:
            - Returns the configured embedding dimensions (default 768)
            - Same value for all providers (OpenAI uses MRL truncation)
        """
        return int( self._config_mgr.get( "embedding dimensions", default="768" ) )

    @property
    def code_dimensions( self ):
        """Return the embedding dimension for the code engine."""
        return int( self._config_mgr.get( "embedding dimensions", default="768" ) )

    def _record_metric( self, content_type, provider, delta_ms, dims ):
        """Record timing metric for a provider/content_type pair."""
        key = f"{provider}_{content_type}"
        with self._metrics_lock:
            if key not in self._metrics:
                self._metrics[ key ] = { "count": 0, "total_ms": 0.0, "min_ms": float( "inf" ), "max_ms": 0.0, "dims": dims }
            m = self._metrics[ key ]
            m[ "count" ]    += 1
            m[ "total_ms" ] += delta_ms
            m[ "min_ms" ]    = min( m[ "min_ms" ], delta_ms )
            m[ "max_ms" ]    = max( m[ "max_ms" ], delta_ms )
            m[ "dims" ]      = dims

    def get_metrics_summary( self ):
        """
        Return timing metrics as a dict for benchmarking.

        Ensures:
            - Returns dict keyed by "provider_contenttype"
            - Each value has count, avg_ms, min_ms, max_ms, dims

        Returns:
            Dict of metrics per provider/content_type pair
        """
        summary = {}
        with self._metrics_lock:
            for key, m in self._metrics.items():
                count = m[ "count" ]
                summary[ key ] = {
                    "count"  : count,
                    "avg_ms" : round( m[ "total_ms" ] / count, 1 ) if count > 0 else 0,
                    "min_ms" : round( m[ "min_ms" ], 1 ) if m[ "min_ms" ] != float( "inf" ) else 0,
                    "max_ms" : round( m[ "max_ms" ], 1 ),
                    "dims"   : m[ "dims" ],
                }
        return summary

    def reset_metrics( self ):
        """Reset all collected metrics."""
        with self._metrics_lock:
            self._metrics.clear()


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def get_embedding_provider( debug=False, verbose=False ):
    """
    Get singleton instance of EmbeddingProvider.

    Requires:
        - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set

    Ensures:
        - Returns singleton EmbeddingProvider instance
    """
    return EmbeddingProvider( debug=debug, verbose=verbose )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def quick_smoke_test():
    """Run quick smoke test for EmbeddingProvider routing layer."""
    du.print_banner( "EmbeddingProvider Smoke Test", prepend_nl=True )

    try:
        # Test 1: Initialize provider
        print( "Test 1: EmbeddingProvider initialization..." )
        provider = get_embedding_provider( debug=True, verbose=True )
        print( f"  Provider: {provider.provider}" )
        print( f"  Prose dimensions: {provider.dimensions}" )
        print( f"  Code dimensions: {provider.code_dimensions}" )
        print( "  Initialization OK" )

        # Test 2: Singleton
        print( "\nTest 2: Singleton verification..." )
        provider_2 = get_embedding_provider()
        assert provider is provider_2, "Singleton broken!"
        print( "  Singleton OK" )

        # Test 3: Prose embedding
        print( "\nTest 3: Prose embedding generation..." )
        prose_emb = provider.generate_embedding( "What time is it?", content_type="prose" )
        print( f"  Prose embedding: {len( prose_emb )} dims" )
        assert len( prose_emb ) == provider.dimensions, f"Expected {provider.dimensions}, got {len( prose_emb )}"
        print( "  Prose embedding OK" )

        # Test 4: Code embedding
        print( "\nTest 4: Code embedding generation..." )
        code_emb = provider.generate_embedding( "def hello(): return 'world'", content_type="code" )
        print( f"  Code embedding: {len( code_emb )} dims" )
        assert len( code_emb ) == provider.code_dimensions, f"Expected {provider.code_dimensions}, got {len( code_emb )}"
        print( "  Code embedding OK" )

        # Test 5: Metrics
        print( "\nTest 5: Metrics collection..." )
        # Generate a few more embeddings
        provider.generate_embedding( "Hello world", content_type="prose" )
        provider.generate_embedding( "sorted( my_list )", content_type="code" )

        metrics = provider.get_metrics_summary()
        print( f"  Metrics keys: {list( metrics.keys() )}" )
        for key, m in metrics.items():
            print( f"    {key}: count={m[ 'count' ]}, avg={m[ 'avg_ms' ]:.1f}ms, min={m[ 'min_ms' ]:.1f}ms, max={m[ 'max_ms' ]:.1f}ms, dims={m[ 'dims' ]}" )
        print( "  Metrics OK" )

        # Test 6: Batch encoding
        print( "\nTest 6: Batch encoding..." )
        batch_embs = provider.generate_embeddings_batch(
            [ "first text", "second text", "third text" ],
            content_type="prose"
        )
        print( f"  Batch result: {len( batch_embs )} embeddings, each {len( batch_embs[ 0 ] )} dims" )
        assert len( batch_embs ) == 3, f"Expected 3, got {len( batch_embs )}"
        print( "  Batch OK" )

        print( "\nAll EmbeddingProvider smoke tests PASSED" )

    except Exception as e:
        print( f"  Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Smoke test failed", caller="embedding_provider.quick_smoke_test()" )

    print( "\nEmbeddingProvider smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
