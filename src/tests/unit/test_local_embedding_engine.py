"""
Unit tests for local embedding engines and embedding provider routing.

Tests CodeEmbeddingEngine, ProseEmbeddingEngine, and EmbeddingProvider
with all GPU operations mocked — runs without GPU.
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock, PropertyMock


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reset_singletons():
    """Reset all singleton instances so each test starts clean."""
    from cosa.memory.local_embedding_engine import CodeEmbeddingEngine, ProseEmbeddingEngine
    from cosa.memory.embedding_provider import EmbeddingProvider

    CodeEmbeddingEngine._instance  = None
    ProseEmbeddingEngine._instance = None
    EmbeddingProvider._instance    = None


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
        "debug_local_embedding"                  : "False",
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
    """Test suite for EmbeddingProvider routing and metrics."""

    def setup_method( self ):
        _reset_singletons()

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
        """dimensions property should return 1536 when provider=openai."""
        from cosa.memory.embedding_provider import EmbeddingProvider
        provider = EmbeddingProvider( debug=False )
        assert provider.dimensions == 1536

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
