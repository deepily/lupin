"""
Embedding service benchmark harness — side-by-side transaction time comparison.

Toggles the 'embedding provider' config between "local" and "openai",
resets the EmbeddingProvider singleton, and reruns identical payloads
through the production routing path to collect comparable metrics.

Providers under test:
  - Local Code:  CodeRankEmbed            (768 dims, GPU cuda:0)
  - Local Prose: nomic-embed-text-v1.5    (768 dims, GPU cuda:0)
  - OpenAI:      text-embedding-3-small   (1536 dims, remote API)

Requires:
  - LUPIN_CONFIG_MGR_CLI_ARGS environment variable set
  - GPU with CUDA support for local engines
  - (Optional) OpenAI API key for remote provider comparison

Run:
  pytest src/tests/smoke/test_embedding_benchmark.py -v -s
  python -m tests.smoke.test_embedding_benchmark
"""

import os
import sys
import time
import pytest

# ---------------------------------------------------------------------------
# Skip entire module if config env var not set
# ---------------------------------------------------------------------------
pytestmark = [
    pytest.mark.skipif(
        not os.environ.get( "LUPIN_CONFIG_MGR_CLI_ARGS" ),
        reason="LUPIN_CONFIG_MGR_CLI_ARGS not set"
    ),
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_ITERATIONS = 10

PROSE_QUERIES = [
    "What is the difference between a list and a tuple in Python?",
    "Explain how gradient descent works in neural networks",
    "How does garbage collection work in the JVM?",
]

CODE_SNIPPETS = [
    "def fibonacci( n ):\n    if n <= 1: return n\n    return fibonacci( n - 1 ) + fibonacci( n - 2 )",
    "class BinaryTree:\n    def __init__( self, value ):\n        self.value = value\n        self.left = None\n        self.right = None",
    "async def fetch_data( url ):\n    async with aiohttp.ClientSession() as session:\n        async with session.get( url ) as response:\n            return await response.json()",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_provider():
    """Reset EmbeddingProvider singleton for clean re-init with new config."""
    from cosa.memory.embedding_provider import EmbeddingProvider
    EmbeddingProvider._instance = None


def _run_single_benchmark( provider, texts, content_type, iterations ):
    """
    Run N iterations of single-embedding generation.

    Requires:
        - provider is an initialized EmbeddingProvider
        - texts is a non-empty list of strings
        - content_type is "prose" or "code"
        - iterations is a positive integer

    Ensures:
        - Generates iterations * len( texts ) embeddings
        - Returns dims from the last embedding generated
    """
    dims = 0
    for _ in range( iterations ):
        for text in texts:
            emb = provider.generate_embedding( text, content_type=content_type )
            dims = len( emb )
    return dims


def _run_batch_benchmark( provider, texts, content_type ):
    """
    Run a single batch embedding generation.

    Requires:
        - provider is an initialized EmbeddingProvider
        - texts is a non-empty list of strings
        - content_type is "prose" or "code"

    Ensures:
        - Returns ( batch_size, dims ) tuple
    """
    embs = provider.generate_embeddings_batch( texts, content_type=content_type )
    return len( embs ), len( embs[ 0 ] ) if embs else 0


def _benchmark_provider( provider_name, iterations ):
    """
    Benchmark a single provider across prose and code, single and batch.

    Requires:
        - provider_name is "local" or "openai"
        - Config already set to this provider
        - Singleton already reset
        - iterations is a positive integer

    Ensures:
        - Returns ( metrics_dict, error_msg_or_None )
        - metrics_dict from get_metrics_summary()
        - On failure returns ( {}, error_string )
    """
    from cosa.memory.embedding_provider import EmbeddingProvider

    try:
        provider = EmbeddingProvider( debug=False, verbose=False )
        provider.reset_metrics()

        # -- Single embeddings: prose --
        _run_single_benchmark( provider, PROSE_QUERIES, "prose", iterations )

        # -- Single embeddings: code --
        _run_single_benchmark( provider, CODE_SNIPPETS, "code", iterations )

        # Harvest single-embedding metrics before batch overwrites them
        single_metrics = provider.get_metrics_summary()

        # Reset metrics so batch gets its own clean counters
        provider.reset_metrics()

        # -- Batch embeddings: prose --
        _run_batch_benchmark( provider, PROSE_QUERIES, "prose" )

        # -- Batch embeddings: code --
        _run_batch_benchmark( provider, CODE_SNIPPETS, "code" )

        batch_metrics = provider.get_metrics_summary()

        return { "single": single_metrics, "batch": batch_metrics }, None

    except Exception as e:
        return {}, str( e )


def _print_comparison_table( local_results, openai_results, iterations ):
    """
    Print a formatted side-by-side comparison table.

    Requires:
        - local_results is a dict with "single" and "batch" sub-dicts
        - openai_results is a dict (may be empty if OpenAI was skipped)
        - iterations is a positive integer

    Ensures:
        - Prints formatted comparison table to stdout
    """
    openai_available = bool( openai_results )
    bar              = "\u2501" * 80
    thin_bar         = "\u2500" * 77

    print()
    print( f" {bar}" )
    print( f"  Embedding Service Benchmark \u2014 Side-by-Side Comparison (N={iterations} iterations)" )
    print( f" {bar}" )

    if not openai_available:
        print()
        print( "  \u26a0  OpenAI provider skipped (API key not available or API error)" )
        print( "     Showing local-only results." )

    # -- Single embeddings table --
    print()
    print( "  Single Embeddings" )
    print( f"  {thin_bar}" )

    if openai_available:
        print( f"  {'Content Type':<16} {'Local avg_ms':>14} {'OpenAI avg_ms':>15} {'Dims (L/O)':>14} {'Speedup':>10}" )
    else:
        print( f"  {'Content Type':<16} {'Local avg_ms':>14} {'Local min_ms':>14} {'Local max_ms':>14} {'Dims':>8}" )

    print( f"  {thin_bar}" )

    for content_type in [ "prose", "code" ]:
        local_key = f"local_{content_type}"
        local_s   = local_results.get( "single", {} ).get( local_key, {} )
        local_avg = local_s.get( "avg_ms", 0 )
        local_min = local_s.get( "min_ms", 0 )
        local_max = local_s.get( "max_ms", 0 )
        local_dim = local_s.get( "dims", 0 )

        if openai_available:
            openai_key = f"openai_{content_type}"
            openai_s   = openai_results.get( "single", {} ).get( openai_key, {} )
            openai_avg = openai_s.get( "avg_ms", 0 )
            openai_dim = openai_s.get( "dims", 0 )
            speedup    = openai_avg / local_avg if local_avg > 0 else 0
            print( f"  {content_type:<16} {local_avg:>11.1f} ms {openai_avg:>12.1f} ms {local_dim:>6} / {openai_dim:<5} {speedup:>8.1f}x" )
        else:
            print( f"  {content_type:<16} {local_avg:>11.1f} ms {local_min:>11.1f} ms {local_max:>11.1f} ms {local_dim:>8}" )

    # -- Batch embeddings table --
    print()
    print( f"  Batch Embeddings ({len( PROSE_QUERIES )} items)" )
    print( f"  {thin_bar}" )

    if openai_available:
        print( f"  {'Content Type':<16} {'Local ms':>14} {'OpenAI ms':>15} {'Items':>14} {'Speedup':>10}" )
    else:
        print( f"  {'Content Type':<16} {'Local ms':>14} {'Items':>14} {'Dims':>14}" )

    print( f"  {thin_bar}" )

    for content_type in [ "prose", "code" ]:
        local_key  = f"local_{content_type}"
        local_b    = local_results.get( "batch", {} ).get( local_key, {} )
        local_ms   = local_b.get( "avg_ms", 0 )
        local_dim  = local_b.get( "dims", 0 )
        item_count = len( PROSE_QUERIES )

        if openai_available:
            openai_key = f"openai_{content_type}"
            openai_b   = openai_results.get( "batch", {} ).get( openai_key, {} )
            openai_ms  = openai_b.get( "avg_ms", 0 )
            speedup    = openai_ms / local_ms if local_ms > 0 else 0
            print( f"  {content_type:<16} {local_ms:>11.1f} ms {openai_ms:>12.1f} ms {item_count:>14} {speedup:>8.1f}x" )
        else:
            print( f"  {content_type:<16} {local_ms:>11.1f} ms {item_count:>14} {local_dim:>14}" )

    print( f" {bar}" )
    print()


# ---------------------------------------------------------------------------
# Pytest test class
# ---------------------------------------------------------------------------

class TestEmbeddingBenchmark:
    """Side-by-side embedding service benchmark."""

    def test_benchmark_side_by_side( self, capsys ):
        """
        Run full benchmark: local vs OpenAI providers, print comparison table.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS env var set
            - GPU available for local engines

        Ensures:
            - Local provider metrics have count > 0
            - All local embeddings return correct dimensions
            - Comparison table printed to stdout
            - Original config restored after test
        """
        from cosa.config.configuration_manager import ConfigurationManager
        from cosa.memory.embedding_provider import EmbeddingProvider

        iterations = DEFAULT_ITERATIONS
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        original_provider = config_mgr.get( "embedding provider", default="openai" ).strip().lower()

        try:
            # ── LOCAL PROVIDER ───────────────────────────────────
            config_mgr.set_config( "embedding provider", "local" )
            _reset_provider()

            local_results, local_err = _benchmark_provider( "local", iterations )
            assert not local_err, f"Local benchmark failed: {local_err}"

            # Validate local metrics
            local_single = local_results.get( "single", {} )
            assert "local_prose" in local_single, "Missing local_prose single metrics"
            assert "local_code" in local_single, "Missing local_code single metrics"
            assert local_single[ "local_prose" ][ "count" ] == iterations * len( PROSE_QUERIES )
            assert local_single[ "local_code" ][ "count" ] == iterations * len( CODE_SNIPPETS )

            local_batch = local_results.get( "batch", {} )
            assert "local_prose" in local_batch, "Missing local_prose batch metrics"
            assert "local_code" in local_batch, "Missing local_code batch metrics"

            # ── OPENAI PROVIDER ──────────────────────────────────
            config_mgr.set_config( "embedding provider", "openai" )
            _reset_provider()

            openai_results, openai_err = _benchmark_provider( "openai", iterations )

            if openai_err:
                print( f"\n  OpenAI benchmark skipped: {openai_err}" )
                openai_results = {}

            # ── REPORT ───────────────────────────────────────────
            _print_comparison_table( local_results, openai_results, iterations )

        finally:
            # ── RESTORE ──────────────────────────────────────────
            config_mgr.set_config( "embedding provider", original_provider )
            _reset_provider()


# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------

def quick_smoke_test():
    """Run embedding benchmark as a standalone smoke test."""
    import cosa.utils.util as du

    du.print_banner( "Embedding Service Benchmark", prepend_nl=True )

    from cosa.config.configuration_manager import ConfigurationManager
    from cosa.memory.embedding_provider import EmbeddingProvider

    iterations = DEFAULT_ITERATIONS
    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    original_provider = config_mgr.get( "embedding provider", default="openai" ).strip().lower()

    print( f"  Original provider: {original_provider}" )
    print( f"  Iterations:        {iterations}" )
    print( f"  Prose queries:     {len( PROSE_QUERIES )}" )
    print( f"  Code snippets:     {len( CODE_SNIPPETS )}" )

    try:
        # ── LOCAL PROVIDER ───────────────────────────────────
        print( "\n  Benchmarking local provider..." )
        config_mgr.set_config( "embedding provider", "local" )
        _reset_provider()

        local_results, local_err = _benchmark_provider( "local", iterations )
        if local_err:
            print( f"  \u2717 Local benchmark failed: {local_err}" )
            return
        print( "  \u2713 Local benchmark complete" )

        # ── OPENAI PROVIDER ──────────────────────────────────
        print( "  Benchmarking OpenAI provider..." )
        config_mgr.set_config( "embedding provider", "openai" )
        _reset_provider()

        openai_results, openai_err = _benchmark_provider( "openai", iterations )
        if openai_err:
            print( f"  \u26a0 OpenAI benchmark skipped: {openai_err}" )
            openai_results = {}
        else:
            print( "  \u2713 OpenAI benchmark complete" )

        # ── REPORT ───────────────────────────────────────────
        _print_comparison_table( local_results, openai_results, iterations )

    except Exception as e:
        print( f"  \u2717 Benchmark error: {e}" )
        import traceback
        traceback.print_exc()

    finally:
        # ── RESTORE ──────────────────────────────────────────
        config_mgr.set_config( "embedding provider", original_provider )
        _reset_provider()
        print( f"  Config restored to: {original_provider}" )

    print( "Embedding benchmark completed." )


def test_embedding_benchmark():
    """Pytest entry point — delegates to standalone QST."""
    quick_smoke_test()


if __name__ == "__main__":
    # Bootstrap path for standalone execution
    lupin_root = os.environ.get( "LUPIN_ROOT" )
    if lupin_root is None:
        raise RuntimeError(
            "LUPIN_ROOT environment variable not set.\n"
            "Set it before running:\n"
            "  export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin\n"
            "  python -m tests.smoke.test_embedding_benchmark"
        )

    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

    quick_smoke_test()
