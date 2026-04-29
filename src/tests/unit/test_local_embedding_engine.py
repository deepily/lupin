"""
Unit tests for local embedding engines and embedding provider routing.

Tests CodeEmbeddingEngine, ProseEmbeddingEngine, and EmbeddingProvider
with all GPU operations mocked — runs without GPU.
"""

import os
import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock, PropertyMock


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reset_singletons():
    """Reset all singleton instances so each test starts clean.

    Also resets the class-level `_is_in_process_engine_owner` flag (added
    2026-04-28 with the process-aware HTTP-routing refactor) and clears
    LUPIN_APP_SERVER_URL, so each test gets a hermetic starting state.
    """
    from cosa.memory.local_embedding_engine import CodeEmbeddingEngine, ProseEmbeddingEngine
    from cosa.memory.embedding_provider import EmbeddingProvider

    CodeEmbeddingEngine._instance  = None
    ProseEmbeddingEngine._instance = None
    EmbeddingProvider._instance    = None

    # New: reset the process-aware routing flag and any URL override.
    EmbeddingProvider._is_in_process_engine_owner = False
    os.environ.pop( "LUPIN_APP_SERVER_URL", None )


def _make_prose_mocks( torch, batch_size=1, seq_len=10, hidden_dim=768 ):
    """
    Build mock tokenizer + model that mimic the ProseEmbeddingEngine pipeline.

    Returns (mock_tokenizer, mock_model) ready to be assigned to engine._tokenizer, engine._model.
    """
    class FakeEncoded( dict ):
        """Dict subclass supporting .to() for device transfer."""
        def to( self, device ):
            return self

    encoded_dict = {
        "input_ids"     : torch.zeros( batch_size, seq_len, dtype=torch.long ),
        "attention_mask" : torch.ones( batch_size, seq_len, dtype=torch.long ),
    }
    mock_encoded = FakeEncoded( encoded_dict )

    mock_tokenizer = Mock()
    mock_tokenizer.return_value = mock_encoded

    # Model output must support [0] (HuggingFace convention: output[0] == last_hidden_state)
    fake_hidden = torch.randn( batch_size, seq_len, hidden_dim )

    class FakeModelOutput:
        def __init__( self, hidden ):
            self.last_hidden_state = hidden
        def __getitem__( self, idx ):
            if idx == 0:
                return self.last_hidden_state
            raise IndexError( idx )

    mock_model = Mock()
    mock_model.return_value = FakeModelOutput( fake_hidden )

    return mock_tokenizer, mock_model


def _make_fake_config( overrides=None ):
    """Return a mock ConfigurationManager with sensible defaults."""
    defaults = {
        "local embedding code model name"       : "nomic-ai/CodeRankEmbed",
        "local embedding code model dimensions"  : "768",
        "local embedding prose model name"       : "nomic-ai/nomic-embed-text-v1.5",
        "local embedding prose model dimensions" : "768",
        "local embedding prose matryoshka dim"    : "768",
        "local embedding device"                 : "cuda:0",
        "local embedding dtype"                  : "float16",
        "local embedding code query prefix"      : "Represent this query for searching relevant code:",
        "local embedding prose query prefix"     : "search_query:",
        "local embedding prose document prefix"  : "search_document:",
        "embedding provider"                     : "local",
        "embedding dimensions"                   : "768",
        "debug local embedding"                  : "False",
    }
    if overrides:
        defaults.update( overrides )

    mock_cfg = Mock()
    mock_cfg.get = lambda key, default=None: defaults.get( key, default if default is not None else "" )
    return mock_cfg


# ─────────────────────────────────────────────────────────────────────────────
# CodeEmbeddingEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestCodeEmbeddingEngine:
    """Test suite for CodeEmbeddingEngine singleton and encode methods."""

    def setup_method( self ):
        _reset_singletons()

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_singleton_returns_same_instance( self, mock_cm ):
        """Two instantiations should return the same object."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        a = CodeEmbeddingEngine( debug=False )
        b = CodeEmbeddingEngine( debug=False )
        assert a is b

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_init_reads_config_keys( self, mock_cm ):
        """__init__ should read model name, device, dtype, dimensions, prefix from config."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )
        assert engine._model_name   == "nomic-ai/CodeRankEmbed"
        assert engine._device       == "cuda:0"
        assert engine._dtype_str    == "float16"
        assert engine._dimensions   == 768
        assert "Represent this query" in engine._query_prefix

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_model_is_none_before_first_encode( self, mock_cm ):
        """Model should be lazily loaded — None right after init."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )
        assert engine._model is None

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_encode_query_applies_prefix( self, mock_cm ):
        """encode_query should prepend the configured query prefix."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )

        # Mock the model
        mock_model = Mock()
        fake_out   = np.random.randn( 1, 768 ).astype( np.float32 )
        mock_model.encode.return_value = fake_out
        engine._model = mock_model  # skip lazy loading

        result = engine.encode_query( [ "find sorting algorithm" ] )
        call_args = mock_model.encode.call_args[ 0 ][ 0 ]  # positional arg #1
        assert any( "Represent this query" in s for s in call_args )
        assert len( result ) == 1
        assert len( result[ 0 ] ) == 768

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_encode_code_no_prefix( self, mock_cm ):
        """encode_code should NOT prepend any prefix."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )

        mock_model = Mock()
        fake_out   = np.random.randn( 2, 768 ).astype( np.float32 )
        mock_model.encode.return_value = fake_out
        engine._model = mock_model

        result = engine.encode_code( [ "def foo():", "class Bar:" ] )
        call_args = mock_model.encode.call_args[ 0 ][ 0 ]
        assert call_args == [ "def foo():", "class Bar:" ]
        assert len( result ) == 2

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_encode_code_returns_list_of_lists( self, mock_cm ):
        """Output should be a plain list of lists (not numpy)."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )

        mock_model = Mock()
        fake_out   = np.random.randn( 1, 768 ).astype( np.float32 )
        mock_model.encode.return_value = fake_out
        engine._model = mock_model

        result = engine.encode_code( [ "print( 'hello' )" ] )
        assert isinstance( result, list )
        assert isinstance( result[ 0 ], list )
        assert all( isinstance( v, float ) for v in result[ 0 ] )


# ─────────────────────────────────────────────────────────────────────────────
# ProseEmbeddingEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestProseEmbeddingEngine:
    """Test suite for ProseEmbeddingEngine singleton and Matryoshka support."""

    def setup_method( self ):
        _reset_singletons()

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_singleton_returns_same_instance( self, mock_cm ):
        """Two instantiations should return the same object."""
        from cosa.memory.local_embedding_engine import ProseEmbeddingEngine
        a = ProseEmbeddingEngine( debug=False )
        b = ProseEmbeddingEngine( debug=False )
        assert a is b

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_init_reads_config_keys( self, mock_cm ):
        """__init__ should read model name, device, matryoshka dim, prefixes."""
        from cosa.memory.local_embedding_engine import ProseEmbeddingEngine
        engine = ProseEmbeddingEngine( debug=False )
        assert engine._model_name     == "nomic-ai/nomic-embed-text-v1.5"
        assert engine._matryoshka_dim == 768
        assert engine._query_prefix   == "search_query:"
        assert engine._document_prefix     == "search_document:"

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_model_is_none_before_first_encode( self, mock_cm ):
        """Model should be lazily loaded — None right after init."""
        from cosa.memory.local_embedding_engine import ProseEmbeddingEngine
        engine = ProseEmbeddingEngine( debug=False )
        assert engine._model is None
        assert engine._tokenizer is None

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_encode_query_applies_query_prefix( self, mock_cm ):
        """encode_query should prepend 'search_query:' to each input."""
        from cosa.memory.local_embedding_engine import ProseEmbeddingEngine
        engine = ProseEmbeddingEngine( debug=False )

        import torch
        engine._tokenizer, engine._model = _make_prose_mocks( torch, batch_size=1 )

        result = engine.encode_query( [ "what time is it" ] )

        # Verify prefix was applied
        call_args = engine._tokenizer.call_args[ 0 ][ 0 ]
        assert all( s.startswith( "search_query:" ) for s in call_args )
        assert len( result ) == 1

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_encode_document_applies_doc_prefix( self, mock_cm ):
        """encode_document should prepend 'search_document:' to each input."""
        from cosa.memory.local_embedding_engine import ProseEmbeddingEngine
        engine = ProseEmbeddingEngine( debug=False )

        import torch
        engine._tokenizer, engine._model = _make_prose_mocks( torch, batch_size=1 )

        result = engine.encode_document( [ "The time is 3pm" ] )
        call_args = engine._tokenizer.call_args[ 0 ][ 0 ]
        assert all( s.startswith( "search_document:" ) for s in call_args )

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config( { "local embedding prose matryoshka dim": "256" } ) )
    def test_matryoshka_truncation_respects_config( self, mock_cm ):
        """Output should be truncated to the configured matryoshka dimension."""
        from cosa.memory.local_embedding_engine import ProseEmbeddingEngine
        engine = ProseEmbeddingEngine( debug=False )
        assert engine._matryoshka_dim == 256

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_encode_query_returns_list_of_lists( self, mock_cm ):
        """Output should be plain Python lists (not tensors or numpy)."""
        from cosa.memory.local_embedding_engine import ProseEmbeddingEngine
        engine = ProseEmbeddingEngine( debug=False )

        import torch
        engine._tokenizer, engine._model = _make_prose_mocks( torch, batch_size=1 )

        result = engine.encode_query( [ "test query" ] )
        assert isinstance( result, list )
        assert isinstance( result[ 0 ], list )


# ─────────────────────────────────────────────────────────────────────────────
# CUDA OOM Retry
# ─────────────────────────────────────────────────────────────────────────────

class TestCudaOomRetryCode:
    """Test _run_with_cuda_retry() in CodeEmbeddingEngine."""

    def setup_method( self ):
        _reset_singletons()

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_cuda_retry_success_on_first_try( self, mock_cm ):
        """fn() succeeds on first call — no retry, returns result."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )
        result = engine._run_with_cuda_retry( lambda: "success" )
        assert result == "success"

    @patch( "cosa.memory.local_embedding_engine.torch" )
    @patch( "cosa.memory.local_embedding_engine.gc" )
    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_cuda_retry_recovers_from_oom( self, mock_cm, mock_gc, mock_torch ):
        """First call raises OutOfMemoryError, second succeeds — returns result."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )

        call_count = { "n": 0 }
        def flaky():
            call_count[ "n" ] += 1
            if call_count[ "n" ] == 1:
                raise mock_torch.cuda.OutOfMemoryError( "CUDA out of memory" )
            return "recovered"

        # Make isinstance check work for the except clause
        mock_torch.cuda.OutOfMemoryError = type( "OutOfMemoryError", ( RuntimeError, ), {} )

        call_count[ "n" ] = 0
        result = engine._run_with_cuda_retry( flaky )
        assert result == "recovered"
        assert call_count[ "n" ] == 2

    @patch( "cosa.memory.local_embedding_engine.torch" )
    @patch( "cosa.memory.local_embedding_engine.gc" )
    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_cuda_retry_calls_gc_and_empty_cache( self, mock_cm, mock_gc, mock_torch ):
        """On OOM, gc.collect() and torch.cuda.empty_cache() must be called."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )

        mock_torch.cuda.OutOfMemoryError = type( "OutOfMemoryError", ( RuntimeError, ), {} )

        call_count = { "n": 0 }
        def flaky():
            call_count[ "n" ] += 1
            if call_count[ "n" ] == 1:
                raise mock_torch.cuda.OutOfMemoryError( "CUDA out of memory" )
            return "ok"

        engine._run_with_cuda_retry( flaky )
        mock_gc.collect.assert_called_once()
        mock_torch.cuda.empty_cache.assert_called_once()

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_cuda_retry_raises_non_cuda_runtime_error( self, mock_cm ):
        """Non-CUDA RuntimeError should be re-raised immediately, no retry."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )

        call_count = { "n": 0 }
        def always_fail():
            call_count[ "n" ] += 1
            raise RuntimeError( "unrelated error" )

        with pytest.raises( RuntimeError, match="unrelated error" ):
            engine._run_with_cuda_retry( always_fail )
        assert call_count[ "n" ] == 1  # no retry

    @patch( "cosa.memory.local_embedding_engine.torch" )
    @patch( "cosa.memory.local_embedding_engine.gc" )
    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_cuda_retry_handles_cublas_error( self, mock_cm, mock_gc, mock_torch ):
        """RuntimeError with 'CUBLAS' in message should trigger retry."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )

        mock_torch.cuda.OutOfMemoryError = type( "OutOfMemoryError", ( RuntimeError, ), {} )

        call_count = { "n": 0 }
        def flaky():
            call_count[ "n" ] += 1
            if call_count[ "n" ] == 1:
                raise RuntimeError( "CUBLAS error: workspace allocation failed" )
            return "recovered"

        result = engine._run_with_cuda_retry( flaky )
        assert result == "recovered"
        assert call_count[ "n" ] == 2

    @patch( "cosa.memory.local_embedding_engine.torch" )
    @patch( "cosa.memory.local_embedding_engine.gc" )
    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_cuda_retry_fails_on_second_oom( self, mock_cm, mock_gc, mock_torch ):
        """If both attempts raise OOM, exception propagates."""
        from cosa.memory.local_embedding_engine import CodeEmbeddingEngine
        engine = CodeEmbeddingEngine( debug=False )

        mock_torch.cuda.OutOfMemoryError = type( "OutOfMemoryError", ( RuntimeError, ), {} )

        def always_oom():
            raise mock_torch.cuda.OutOfMemoryError( "CUDA out of memory" )

        with pytest.raises( RuntimeError, match="CUDA out of memory" ):
            engine._run_with_cuda_retry( always_oom )


class TestCudaOomRetryProse:
    """Test _run_with_cuda_retry() in ProseEmbeddingEngine."""

    def setup_method( self ):
        _reset_singletons()

    @patch( "cosa.memory.local_embedding_engine.torch" )
    @patch( "cosa.memory.local_embedding_engine.gc" )
    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_prose_cuda_retry_recovers_from_oom( self, mock_cm, mock_gc, mock_torch ):
        """ProseEmbeddingEngine retry should recover from OOM identically."""
        from cosa.memory.local_embedding_engine import ProseEmbeddingEngine
        engine = ProseEmbeddingEngine( debug=False )

        mock_torch.cuda.OutOfMemoryError = type( "OutOfMemoryError", ( RuntimeError, ), {} )

        call_count = { "n": 0 }
        def flaky():
            call_count[ "n" ] += 1
            if call_count[ "n" ] == 1:
                raise mock_torch.cuda.OutOfMemoryError( "CUDA out of memory" )
            return "recovered"

        result = engine._run_with_cuda_retry( flaky )
        assert result == "recovered"
        mock_gc.collect.assert_called_once()
        mock_torch.cuda.empty_cache.assert_called_once()

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_prose_cuda_retry_raises_non_cuda_error( self, mock_cm ):
        """Non-CUDA RuntimeError should pass through without retry."""
        from cosa.memory.local_embedding_engine import ProseEmbeddingEngine
        engine = ProseEmbeddingEngine( debug=False )

        call_count = { "n": 0 }
        def always_fail():
            call_count[ "n" ] += 1
            raise RuntimeError( "unrelated error" )

        with pytest.raises( RuntimeError, match="unrelated error" ):
            engine._run_with_cuda_retry( always_fail )
        assert call_count[ "n" ] == 1


# ─────────────────────────────────────────────────────────────────────────────
# VramReport
# ─────────────────────────────────────────────────────────────────────────────

class TestVramReport:
    """Test vram_report() utility function."""

    @patch( "cosa.memory.local_embedding_engine.torch" )
    def test_returns_correct_keys( self, mock_torch ):
        """vram_report should return dict with allocated_gb, reserved_gb, peak_gb."""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.memory_allocated.return_value = 1073741824  # 1 GB
        mock_torch.cuda.memory_reserved.return_value  = 2147483648  # 2 GB
        mock_torch.cuda.max_memory_allocated.return_value = 1610612736  # 1.5 GB

        from cosa.memory.local_embedding_engine import vram_report
        report = vram_report( "cuda:0" )

        assert "allocated_gb" in report
        assert "reserved_gb" in report
        assert "peak_gb" in report
        assert abs( report[ "allocated_gb" ] - 1.0 ) < 0.01
        assert abs( report[ "reserved_gb" ] - 2.0 ) < 0.01
        assert abs( report[ "peak_gb" ] - 1.5 ) < 0.01

    @patch( "cosa.memory.local_embedding_engine.torch" )
    def test_returns_zeros_when_cuda_unavailable( self, mock_torch ):
        """vram_report should return zeros when CUDA is not available."""
        mock_torch.cuda.is_available.return_value = False

        from cosa.memory.local_embedding_engine import vram_report
        report = vram_report( "cuda:0" )

        assert report[ "allocated_gb" ] == 0.0
        assert report[ "reserved_gb" ] == 0.0
        assert report[ "peak_gb" ] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# EmbeddingProvider
# ─────────────────────────────────────────────────────────────────────────────

class TestEmbeddingProvider:
    """Test suite for EmbeddingProvider routing and metrics.

    These tests exercise the in-process-engine path representatively, so
    they explicitly declare the flag True in setup. The new HTTP-routing
    path is covered by TestEmbeddingProviderRoutingFlag /
    TestEmbeddingProviderHttpPath / TestEmbeddingProviderDynamicUrl below.
    """

    def setup_method( self ):
        _reset_singletons()
        # Existing routing tests assume the in-process engine path. The new
        # 2026-04-28 process-aware routing flag defaults to False (HTTP
        # path); flip it to True here so these legacy tests continue
        # exercising the local-engine code branch they were designed for.
        from cosa.memory.embedding_provider import EmbeddingProvider
        EmbeddingProvider._is_in_process_engine_owner = True

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_singleton_returns_same_instance( self, mock_cm ):
        """Two instantiations should return the same object."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        a = EmbeddingProvider( debug=False )
        b = EmbeddingProvider( debug=False )
        assert a is b

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_init_reads_provider_from_config( self, mock_cm ):
        """__init__ should read 'embedding provider' key."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )
        assert provider._provider == "local"

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config( { "embedding provider": "openai" } ) )
    def test_openai_provider_routes_to_openai_engine( self, mock_cm ):
        """When provider=openai, generate_embedding should call EmbeddingManager."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_engine = Mock()
        mock_engine.generate_embedding.return_value = [ 0.1 ] * 1536
        provider._openai_engine = mock_engine

        result = provider.generate_embedding( "test text", content_type="prose" )
        mock_engine.generate_embedding.assert_called_once()
        assert len( result ) == 1536

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_local_prose_routes_to_prose_engine( self, mock_cm ):
        """When provider=local + content_type=prose, should use ProseEmbeddingEngine."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_prose = Mock()
        mock_prose.encode_query.return_value = [ [ 0.1 ] * 768 ]
        provider._prose_engine = mock_prose

        result = provider.generate_embedding( "what time is it", content_type="prose" )
        mock_prose.encode_query.assert_called_once_with( [ "what time is it" ] )
        assert len( result ) == 768

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_local_code_routes_to_code_engine( self, mock_cm ):
        """When provider=local + content_type=code, should use CodeEmbeddingEngine."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_code = Mock()
        mock_code.encode_code.return_value = [ [ 0.2 ] * 768 ]
        provider._code_engine = mock_code

        result = provider.generate_embedding( "def foo():", content_type="code" )
        mock_code.encode_code.assert_called_once_with( [ "def foo():" ] )
        assert len( result ) == 768

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_metrics_recorded_after_generate( self, mock_cm ):
        """generate_embedding should record timing metrics."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_prose = Mock()
        mock_prose.encode_query.return_value = [ [ 0.1 ] * 768 ]
        provider._prose_engine = mock_prose

        provider.generate_embedding( "test", content_type="prose" )
        metrics = provider.get_metrics_summary()

        assert "local_prose" in metrics
        assert metrics[ "local_prose" ][ "count" ] == 1

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_dimensions_property_local( self, mock_cm ):
        """dimensions property should return matryoshka dim when provider=local."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )
        assert provider.dimensions == 768

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config( { "embedding provider": "openai" } ) )
    def test_dimensions_property_openai( self, mock_cm ):
        """dimensions property should return standardized 768 even when provider=openai (MRL truncation)."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )
        assert provider.dimensions == 768

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_reset_metrics_clears_all( self, mock_cm ):
        """reset_metrics should clear all collected metrics."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_prose = Mock()
        mock_prose.encode_query.return_value = [ [ 0.1 ] * 768 ]
        provider._prose_engine = mock_prose

        provider.generate_embedding( "test", content_type="prose" )
        assert len( provider.get_metrics_summary() ) > 0

        provider.reset_metrics()
        assert len( provider.get_metrics_summary() ) == 0

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_batch_embedding_local_prose( self, mock_cm ):
        """generate_embeddings_batch should return multiple embeddings."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_prose = Mock()
        mock_prose.encode_query.return_value = [ [ 0.1 ] * 768, [ 0.2 ] * 768 ]
        provider._prose_engine = mock_prose

        result = provider.generate_embeddings_batch( [ "hello", "world" ], content_type="prose" )
        assert len( result ) == 2
        assert len( result[ 0 ] ) == 768

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_batch_embedding_local_code( self, mock_cm ):
        """generate_embeddings_batch with code should use encode_code."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_code = Mock()
        mock_code.encode_code.return_value = [ [ 0.1 ] * 768, [ 0.2 ] * 768 ]
        provider._code_engine = mock_code

        result = provider.generate_embeddings_batch( [ "def a():", "def b():" ], content_type="code" )
        mock_code.encode_code.assert_called_once()
        assert len( result ) == 2

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config( { "embedding provider": "openai" } ) )
    def test_openai_code_warning_single( self, mock_cm, capsys ):
        """OpenAI provider + content_type=code should print a warning."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_engine = Mock()
        mock_engine.generate_embedding.return_value = [ 0.1 ] * 1536
        provider._openai_engine = mock_engine

        provider.generate_embedding( "def foo(): pass", content_type="code" )
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "code-specific" in captured.out

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config( { "embedding provider": "openai" } ) )
    def test_openai_code_warning_batch( self, mock_cm, capsys ):
        """OpenAI provider + content_type=code in batch should print a warning."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_engine = Mock()
        mock_engine.generate_embedding.return_value = [ 0.1 ] * 1536
        provider._openai_engine = mock_engine

        provider.generate_embeddings_batch( [ "def a():", "def b():" ], content_type="code" )
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "code-specific" in captured.out

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config( { "embedding provider": "openai" } ) )
    def test_openai_prose_no_warning( self, mock_cm, capsys ):
        """OpenAI provider + content_type=prose should NOT print a code warning."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )

        mock_engine = Mock()
        mock_engine.generate_embedding.return_value = [ 0.1 ] * 1536
        provider._openai_engine = mock_engine

        provider.generate_embedding( "what time is it", content_type="prose" )
        captured = capsys.readouterr()
        assert "code-specific" not in captured.out


# ─────────────────────────────────────────────────────────────────────────────
# Module-level convenience functions
# ─────────────────────────────────────────────────────────────────────────────

class TestConvenienceFunctions:
    """Test module-level factory functions."""

    def setup_method( self ):
        _reset_singletons()

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_get_code_engine_returns_singleton( self, mock_cm ):
        """get_code_engine() should return a CodeEmbeddingEngine singleton."""
        from cosa.memory.local_embedding_engine import get_code_engine, CodeEmbeddingEngine
        engine = get_code_engine( debug=False )
        assert isinstance( engine, CodeEmbeddingEngine )

    @patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=_make_fake_config() )
    def test_get_prose_engine_returns_singleton( self, mock_cm ):
        """get_prose_engine() should return a ProseEmbeddingEngine singleton."""
        from cosa.memory.local_embedding_engine import get_prose_engine, ProseEmbeddingEngine
        engine = get_prose_engine( debug=False )
        assert isinstance( engine, ProseEmbeddingEngine )

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_get_embedding_provider_returns_singleton( self, mock_cm ):
        """get_embedding_provider() should return an EmbeddingProvider singleton."""
        from cosa.memory.embedding_provider import get_embedding_provider, EmbeddingProvider
        provider = get_embedding_provider( debug=False )
        assert isinstance( provider, EmbeddingProvider )


# ─────────────────────────────────────────────────────────────────────────────
# Process-aware routing tests (added 2026-04-28)
#
# These cover the new `_is_in_process_engine_owner` flag, the HTTP-fallback
# path that activates when the flag is False, and the runtime URL resolution
# that lets a test running on the :8000 test server target :8000 dynamically
# without restarting the Python process.
# ─────────────────────────────────────────────────────────────────────────────


class TestEmbeddingProviderRoutingFlag:
    """The class-level flag controls in-process vs HTTP routing."""

    def setup_method( self ):
        _reset_singletons()  # leaves flag=False, which is what these tests want

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_owner_flag_default_is_false( self, mock_cm ):
        """Fresh process should default to HTTP routing — never grab GPU implicitly."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        # Just observe; reset_singletons already cleared it.
        assert EmbeddingProvider._is_in_process_engine_owner is False

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_declare_in_process_engine_owner_flips_flag( self, mock_cm ):
        """declare_in_process_engine_owner() flips the class-level flag True."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        EmbeddingProvider.declare_in_process_engine_owner()
        assert EmbeddingProvider._is_in_process_engine_owner is True

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_declare_in_process_engine_owner_idempotent( self, mock_cm ):
        """Calling declare twice doesn't break (idempotent)."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        EmbeddingProvider.declare_in_process_engine_owner()
        EmbeddingProvider.declare_in_process_engine_owner()
        assert EmbeddingProvider._is_in_process_engine_owner is True

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_owner_flag_true_routes_to_engine_not_http( self, mock_cm ):
        """When flag=True, generate_embedding calls the engine and NOT requests.post."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        EmbeddingProvider.declare_in_process_engine_owner()

        provider = EmbeddingProvider( debug=False )
        mock_prose = Mock()
        mock_prose.encode_query.return_value = [ [ 0.1 ] * 768 ]
        provider._prose_engine = mock_prose

        with patch( "requests.post" ) as mock_post:
            result = provider.generate_embedding( "owner-path text", content_type="prose" )

        mock_prose.encode_query.assert_called_once_with( [ "owner-path text" ] )
        mock_post.assert_not_called()
        assert len( result ) == 768

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_owner_flag_false_routes_to_http_not_engine( self, mock_cm ):
        """When flag=False, generate_embedding calls requests.post and NOT the engine."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        # flag stays False from setup

        provider = EmbeddingProvider( debug=False )
        mock_prose = Mock()
        mock_prose.encode_query.return_value = [ [ 0.99 ] * 768 ]  # would-be local result
        provider._prose_engine = mock_prose

        # Mock the HTTP path: api key + 200 response
        with patch.object( EmbeddingProvider, "_http_api_key", return_value="fake-key" ), \
             patch( "requests.post" ) as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=Mock( return_value={ "embedding": [ 0.5 ] * 768 } )
            )
            result = provider.generate_embedding( "http-path text", content_type="prose" )

        mock_prose.encode_query.assert_not_called()
        mock_post.assert_called_once()
        assert result == [ 0.5 ] * 768  # came from HTTP, not local engine


class TestEmbeddingProviderHttpPath:
    """When HTTP is used, verify endpoint, auth, and error handling."""

    def setup_method( self ):
        _reset_singletons()  # flag stays False — HTTP path

    def _build_provider_with_api_key( self, mock_cm, api_key="test-key" ):
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )
        # Patch _http_api_key on the class so all instances see the mock
        EmbeddingProvider._http_api_key = staticmethod( lambda: api_key )
        return provider

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_http_calls_correct_endpoint_with_api_key_header( self, mock_cm ):
        """generate_embedding (non-owner) POSTs to /api/embeddings/generate with X-API-Key."""
        provider = self._build_provider_with_api_key( mock_cm, api_key="my-secret-key" )

        with patch( "requests.post" ) as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=Mock( return_value={ "embedding": [ 0.1 ] * 768 } )
            )
            provider.generate_embedding( "hello", content_type="prose" )

        assert mock_post.call_count == 1
        call = mock_post.call_args
        url = call.args[0]
        assert url.endswith( "/api/embeddings/generate" )
        assert call.kwargs[ "headers" ][ "X-API-Key" ] == "my-secret-key"
        assert call.kwargs[ "json" ] == { "text": "hello", "content_type": "prose" }

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_http_no_api_key_raises_clear_error( self, mock_cm ):
        """No API key file → RuntimeError with descriptive message."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )
        EmbeddingProvider._http_api_key = staticmethod( lambda: None )

        with pytest.raises( RuntimeError ) as exc_info:
            provider.generate_embedding( "hello", content_type="prose" )

        msg = str( exc_info.value )
        assert "API key" in msg
        assert "declare_in_process_engine_owner" in msg

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_http_connection_error_raises_clear_error( self, mock_cm ):
        """ConnectionError from requests → RuntimeError with the URL + cause."""
        import requests as _req

        provider = self._build_provider_with_api_key( mock_cm )

        with patch( "requests.post", side_effect=_req.ConnectionError( "refused" ) ):
            with pytest.raises( RuntimeError ) as exc_info:
                provider.generate_embedding( "hello", content_type="prose" )

        msg = str( exc_info.value )
        assert "unreachable" in msg
        assert "ConnectionError" in msg
        assert "/api/embeddings/generate" in msg

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_http_5xx_raises_clear_error( self, mock_cm ):
        """5xx response → RuntimeError with status code and URL."""
        provider = self._build_provider_with_api_key( mock_cm )

        with patch( "requests.post" ) as mock_post:
            mock_post.return_value = Mock(
                status_code=503,
                text="server unavailable"
            )
            with pytest.raises( RuntimeError ) as exc_info:
                provider.generate_embedding( "hello", content_type="prose" )

        msg = str( exc_info.value )
        assert "503" in msg
        assert "server unavailable" in msg

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_http_malformed_response_raises_clear_error( self, mock_cm ):
        """Response missing 'embedding' key → RuntimeError."""
        provider = self._build_provider_with_api_key( mock_cm )

        with patch( "requests.post" ) as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=Mock( return_value={ "wrong_key": "wrong" } )
            )
            with pytest.raises( RuntimeError ) as exc_info:
                provider.generate_embedding( "hello", content_type="prose" )

        assert "malformed response" in str( exc_info.value )


class TestEmbeddingProviderDynamicUrl:
    """LUPIN_APP_SERVER_URL is read at call time, not at module load.

    This is the explicit user requirement — a test running on the :8000 test
    server can set the env var and have HTTP routing target :8000 without
    restarting the Python process.
    """

    def setup_method( self ):
        _reset_singletons()

    def _build_provider_with_api_key( self, mock_cm, api_key="test-key" ):
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )
        EmbeddingProvider._http_api_key = staticmethod( lambda: api_key )
        return provider

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_default_url_when_env_unset( self, mock_cm ):
        """No LUPIN_APP_SERVER_URL → defaults to http://localhost:7999."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        os.environ.pop( "LUPIN_APP_SERVER_URL", None )
        assert EmbeddingProvider._resolve_server_url() == "http://localhost:7999"

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_custom_url_from_env( self, mock_cm ):
        """LUPIN_APP_SERVER_URL=http://localhost:8000 → resolver returns it."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        os.environ[ "LUPIN_APP_SERVER_URL" ] = "http://localhost:8000"
        try:
            assert EmbeddingProvider._resolve_server_url() == "http://localhost:8000"
        finally:
            os.environ.pop( "LUPIN_APP_SERVER_URL", None )

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_url_resolved_at_call_time_not_module_load( self, mock_cm ):
        """KEY assertion: changing env between two HTTP calls hits two different URLs."""
        provider = self._build_provider_with_api_key( mock_cm )

        os.environ[ "LUPIN_APP_SERVER_URL" ] = "http://localhost:7999"
        try:
            with patch( "requests.post" ) as mock_post:
                mock_post.return_value = Mock(
                    status_code=200,
                    json=Mock( return_value={ "embedding": [ 0.1 ] * 768 } )
                )
                provider.generate_embedding( "first", content_type="prose" )
                first_url = mock_post.call_args.args[0]

                # Mid-process URL change — the user's stated requirement
                os.environ[ "LUPIN_APP_SERVER_URL" ] = "http://localhost:8000"
                provider.generate_embedding( "second", content_type="prose" )
                second_url = mock_post.call_args.args[0]
        finally:
            os.environ.pop( "LUPIN_APP_SERVER_URL", None )

        assert first_url.startswith( "http://localhost:7999" )
        assert second_url.startswith( "http://localhost:8000" )

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_empty_env_falls_back_to_default( self, mock_cm ):
        """LUPIN_APP_SERVER_URL='' (empty string) → fallback to default."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        os.environ[ "LUPIN_APP_SERVER_URL" ] = ""
        try:
            assert EmbeddingProvider._resolve_server_url() == "http://localhost:7999"
        finally:
            os.environ.pop( "LUPIN_APP_SERVER_URL", None )


class TestEmbeddingProviderBatchHttpPath:
    """Batch path mirrors single-text path through /api/embeddings/batch."""

    def setup_method( self ):
        _reset_singletons()

    def _build_provider_with_api_key( self, mock_cm, api_key="test-key" ):
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )
        EmbeddingProvider._http_api_key = staticmethod( lambda: api_key )
        return provider

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_batch_routes_to_batch_endpoint( self, mock_cm ):
        """generate_embeddings_batch (non-owner) POSTs to /api/embeddings/batch."""
        provider = self._build_provider_with_api_key( mock_cm )

        with patch( "requests.post" ) as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=Mock( return_value={ "embeddings": [ [ 0.1 ] * 768, [ 0.2 ] * 768 ] } )
            )
            result = provider.generate_embeddings_batch( [ "a", "b" ], content_type="prose" )

        url = mock_post.call_args.args[0]
        assert url.endswith( "/api/embeddings/batch" )
        assert mock_post.call_args.kwargs[ "json" ] == { "texts": [ "a", "b" ], "content_type": "prose" }
        assert len( result ) == 2

    @patch( "cosa.memory.embedding_provider.ConfigurationManager", return_value=_make_fake_config() )
    def test_batch_owner_path_unaffected( self, mock_cm ):
        """flag=True keeps batch on the in-process engine, no HTTP."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        EmbeddingProvider.declare_in_process_engine_owner()

        provider = EmbeddingProvider( debug=False )
        mock_prose = Mock()
        mock_prose.encode_query.return_value = [ [ 0.1 ] * 768, [ 0.2 ] * 768 ]
        provider._prose_engine = mock_prose

        with patch( "requests.post" ) as mock_post:
            result = provider.generate_embeddings_batch( [ "a", "b" ], content_type="prose" )

        mock_prose.encode_query.assert_called_once_with( [ "a", "b" ] )
        mock_post.assert_not_called()
        assert len( result ) == 2
