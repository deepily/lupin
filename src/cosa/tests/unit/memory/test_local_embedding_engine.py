"""
Unit tests for cosa.memory.local_embedding_engine.

Covers the two GPU singleton engines (CodeEmbeddingEngine, ProseEmbeddingEngine)
plus the module-level helpers (get_code_engine, get_prose_engine, vram_report):

- Singleton identity + double-checked __new__/__init__ + _load_model guards
- _load_model lazy load (mocked SentenceTransformer / AutoModel+AutoTokenizer),
  including the debug+cuda VRAM-report branch and the already-loaded short-circuit
- _run_with_cuda_retry: success / non-CUDA-reraise / CUDA-OOM-retry arms
- encode_query / encode_code / encode_document (debug+verbose timer arms)
- ProseEmbeddingEngine._mean_pooling + _encode_batch on real CPU tensors
- unload (loaded + already-unloaded), dimensions / model_name / is_loaded props
- vram_report: cuda-unavailable / "cuda:N" / "cuda" / int-device arms

GPU HYGIENE: every torch.cuda mutation (empty_cache, OOM) is mocked; models and
tokenizers are mocked; _encode_batch runs the REAL torch math on tiny CPU tensors
(device="cpu"). No real GPU, model download, or network. Singletons reset per test.

quick_smoke_test() is excluded from coverage via pyproject exclude_also.

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, memory group, provider/engine lane).
"""

import unittest
from unittest.mock import Mock, patch

import numpy as np
import torch

from cosa.memory.local_embedding_engine import (
    CodeEmbeddingEngine,
    ProseEmbeddingEngine,
    get_code_engine,
    get_prose_engine,
    vram_report,
)

_VEC768 = [ 0.1 ] * 768


def _reset():
    CodeEmbeddingEngine._instance  = None
    ProseEmbeddingEngine._instance = None


def _build_code( device="cpu", debug=False, verbose=False ):
    _reset()
    cfg = Mock()
    cfg.get.side_effect = lambda key, default=None, **kw: {
        "local embedding code model name"       : "nomic-ai/CodeRankEmbed",
        "local embedding device"                : device,
        "local embedding dtype"                 : "float16",
        "local embedding code model dimensions" : "768",
        "local embedding code query prefix"     : "search_query:",
    }.get( key, default )
    with patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=cfg ):
        return CodeEmbeddingEngine( debug=debug, verbose=verbose )


def _build_prose( device="cpu", debug=False, verbose=False, matryoshka="768" ):
    _reset()
    cfg = Mock()
    cfg.get.side_effect = lambda key, default=None, **kw: {
        "local embedding prose model name"        : "nomic-ai/nomic-embed-text-v1.5",
        "local embedding device"                  : device,
        "local embedding dtype"                   : "float16",
        "local embedding prose model dimensions"  : "768",
        "local embedding prose matryoshka dim"    : matryoshka,
        "local embedding prose query prefix"      : "search_query:",
        "local embedding prose document prefix"   : "search_document:",
    }.get( key, default )
    with patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=cfg ):
        return ProseEmbeddingEngine( debug=debug, verbose=verbose )


class TestCodeEmbeddingEngine( unittest.TestCase ):
    """CodeEmbeddingEngine singleton, load, retry, encode, unload, props."""

    def setUp( self ):
        _reset()

    def tearDown( self ):
        _reset()

    def test_singleton_and_config( self ):
        """get_code_engine returns the singleton; config values stored."""
        a = _build_code( debug=True )
        with patch( "builtins.print" ):
            b = get_code_engine()
        self.assertIs( a, b )
        self.assertEqual( a.model_name, "nomic-ai/CodeRankEmbed" )
        self.assertEqual( a.dimensions, 768 )
        self.assertFalse( a.is_loaded )

    def test_init_idempotent( self ):
        """A second __init__ on the cached instance is a no-op."""
        _reset()
        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, **kw: {
            "local embedding code model dimensions": "768",
        }.get( key, default )
        with patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=cfg ) as mock_cm:
            CodeEmbeddingEngine()
            CodeEmbeddingEngine()
        mock_cm.assert_called_once()

    def test_new_double_checked_inner_guard( self ):
        """__new__ inner guard returns the already-created instance."""
        _reset()
        sentinel = Mock()

        class _SettingLock:
            def __enter__( self_lock ):
                CodeEmbeddingEngine._instance = sentinel
                return self_lock

            def __exit__( self_lock, *exc ):
                return False

        with patch.object( CodeEmbeddingEngine, "_lock", _SettingLock() ):
            result = CodeEmbeddingEngine()
        self.assertIs( result, sentinel )

    def test_load_model_loads_once_with_cuda_vram( self ):
        """_load_model builds the SentenceTransformer; debug+cuda triggers vram_report."""
        engine = _build_code( device="cuda:0", debug=True )
        fake_model = Mock()
        with patch( "sentence_transformers.SentenceTransformer", return_value=fake_model ) as mock_st, \
             patch( "cosa.memory.local_embedding_engine.vram_report",
                    return_value={ "allocated_gb": 1.0, "peak_gb": 2.0 } ) as mock_vram, \
             patch( "builtins.print" ):
            engine._load_model()
        self.assertIs( engine._model, fake_model )
        mock_st.assert_called_once()
        mock_vram.assert_called_once()

    def test_load_model_cpu_no_vram_branch( self ):
        """_load_model on a CPU device (debug off) skips the VRAM-report branch."""
        engine = _build_code( device="cpu", debug=False )
        with patch( "sentence_transformers.SentenceTransformer", return_value=Mock() ) as mock_st, \
             patch( "cosa.memory.local_embedding_engine.vram_report" ) as mock_vram:
            engine._load_model()
        mock_st.assert_called_once()
        mock_vram.assert_not_called()                            # 126->exit (debug/cuda false)

    def test_load_model_short_circuits_when_loaded( self ):
        """_load_model returns immediately when the model is already set."""
        engine = _build_code()
        engine._model = Mock()
        with patch( "sentence_transformers.SentenceTransformer" ) as mock_st:
            engine._load_model()
        mock_st.assert_not_called()

    def test_load_model_inner_guard( self ):
        """Inner double-checked guard: model appears while acquiring the lock."""
        engine = _build_code()

        class _SettingLock:
            def __enter__( self_lock ):
                engine._model = Mock()
                return self_lock

            def __exit__( self_lock, *exc ):
                return False

        engine._inference_lock = _SettingLock()
        with patch( "sentence_transformers.SentenceTransformer" ) as mock_st:
            engine._load_model()
        mock_st.assert_not_called()

    def test_run_with_cuda_retry_success( self ):
        """fn succeeds → result returned, no retry."""
        engine = _build_code()
        self.assertEqual( engine._run_with_cuda_retry( lambda: "ok" ), "ok" )

    def test_run_with_cuda_retry_non_cuda_reraises( self ):
        """A non-CUDA RuntimeError is re-raised, not retried."""
        engine = _build_code()
        def _boom():
            raise RuntimeError( "some unrelated error" )
        with self.assertRaises( RuntimeError ):
            engine._run_with_cuda_retry( _boom )

    def test_run_with_cuda_retry_oom_retries_once( self ):
        """A CUDA OOM clears cache and retries once (debug logs)."""
        engine = _build_code( debug=True )
        calls = { "n": 0 }
        def _fn():
            calls[ "n" ] += 1
            if calls[ "n" ] == 1:
                raise RuntimeError( "CUDA out of memory" )
            return "recovered"
        with patch( "torch.cuda.empty_cache" ) as mock_empty, \
             patch( "gc.collect" ) as mock_collect, \
             patch( "builtins.print" ):
            result = engine._run_with_cuda_retry( _fn )
        self.assertEqual( result, "recovered" )
        mock_empty.assert_called_once()
        mock_collect.assert_called_once()

    def test_encode_query_prefixes_and_returns_list( self ):
        """encode_query loads, prefixes queries, returns list (debug+verbose timer)."""
        engine = _build_code( debug=True, verbose=True )
        fake_model = Mock()
        fake_model.encode.return_value = np.array( [ _VEC768 ] )
        with patch.object( engine, "_load_model" ), \
             patch( "builtins.print" ):
            engine._model = fake_model
            result = engine.encode_query( [ "sort a list" ] )
        self.assertEqual( result, [ _VEC768 ] )
        # query prefix prepended
        called_arg = fake_model.encode.call_args[ 0 ][ 0 ]
        self.assertEqual( called_arg, [ "search_query: sort a list" ] )

    def test_encode_query_no_debug_skips_timer( self ):
        """encode_query with debug off skips the timer branches."""
        engine = _build_code( debug=False )
        fake_model = Mock()
        fake_model.encode.return_value = np.array( [ _VEC768 ] )
        with patch.object( engine, "_load_model" ):
            engine._model = fake_model
            result = engine.encode_query( [ "q" ] )
        self.assertEqual( result, [ _VEC768 ] )

    def test_encode_code_no_prefix( self ):
        """encode_code loads and encodes documents without a prefix (debug off)."""
        engine = _build_code()
        fake_model = Mock()
        fake_model.encode.return_value = np.array( [ _VEC768 ] )
        with patch.object( engine, "_load_model" ):
            engine._model = fake_model
            result = engine.encode_code( [ "x = sorted( y )" ] )
        self.assertEqual( result, [ _VEC768 ] )
        self.assertEqual( fake_model.encode.call_args[ 0 ][ 0 ], [ "x = sorted( y )" ] )

    def test_encode_code_debug_verbose_timer( self ):
        """encode_code with debug+verbose exercises the timer branches."""
        engine = _build_code( debug=True, verbose=True )
        fake_model = Mock()
        fake_model.encode.return_value = np.array( [ _VEC768 ] )
        with patch.object( engine, "_load_model" ), \
             patch( "builtins.print" ):
            engine._model = fake_model
            result = engine.encode_code( [ "x = 1" ] )
        self.assertEqual( result, [ _VEC768 ] )

    def test_unload_loaded_and_unloaded( self ):
        """unload frees the model when loaded; no-op when already unloaded."""
        engine = _build_code( debug=True )
        engine._model = Mock()
        with patch( "torch.cuda.empty_cache" ) as mock_empty, patch( "builtins.print" ):
            engine.unload()
        self.assertIsNone( engine._model )
        mock_empty.assert_called_once()
        # second unload is a no-op (model already None)
        with patch( "torch.cuda.empty_cache" ) as mock_empty2:
            engine.unload()
        mock_empty2.assert_not_called()


class TestProseEmbeddingEngine( unittest.TestCase ):
    """ProseEmbeddingEngine singleton, load, pooling, encode_batch, encode, unload, props."""

    def setUp( self ):
        _reset()

    def tearDown( self ):
        _reset()

    def test_singleton_and_config( self ):
        """get_prose_engine returns the singleton; config values stored."""
        a = _build_prose( debug=True )
        with patch( "builtins.print" ):
            b = get_prose_engine()
        self.assertIs( a, b )
        self.assertEqual( a.model_name, "nomic-ai/nomic-embed-text-v1.5" )
        self.assertEqual( a.dimensions, 768 )
        self.assertFalse( a.is_loaded )

    def test_init_idempotent( self ):
        """A second __init__ on the cached instance is a no-op."""
        _reset()
        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, **kw: {
            "local embedding prose model dimensions": "768",
            "local embedding prose matryoshka dim": "768",
        }.get( key, default )
        with patch( "cosa.memory.local_embedding_engine.ConfigurationManager", return_value=cfg ) as mock_cm:
            ProseEmbeddingEngine()
            ProseEmbeddingEngine()
        mock_cm.assert_called_once()

    def test_new_double_checked_inner_guard( self ):
        """__new__ inner guard returns the already-created instance."""
        _reset()
        sentinel = Mock()

        class _SettingLock:
            def __enter__( self_lock ):
                ProseEmbeddingEngine._instance = sentinel
                return self_lock

            def __exit__( self_lock, *exc ):
                return False

        with patch.object( ProseEmbeddingEngine, "_lock", _SettingLock() ):
            result = ProseEmbeddingEngine()
        self.assertIs( result, sentinel )

    def test_load_model_loads_with_cuda_vram( self ):
        """_load_model builds tokenizer + model; debug+cuda triggers vram_report."""
        engine = _build_prose( device="cuda:0", debug=True )
        fake_model = Mock()
        # .to(device).eval() chain must return the model
        fake_model.to.return_value.eval.return_value = fake_model
        with patch( "transformers.AutoTokenizer" ) as mock_tok, \
             patch( "transformers.AutoModel" ) as mock_model, \
             patch( "cosa.memory.local_embedding_engine.vram_report",
                    return_value={ "allocated_gb": 1.0, "peak_gb": 2.0 } ) as mock_vram, \
             patch( "builtins.print" ):
            mock_model.from_pretrained.return_value.to.return_value.eval.return_value = fake_model
            engine._load_model()
        self.assertIsNotNone( engine._model )
        mock_tok.from_pretrained.assert_called_once_with( "bert-base-uncased" )
        mock_vram.assert_called_once()

    def test_load_model_cpu_no_vram_branch( self ):
        """_load_model on CPU (debug off) skips the VRAM-report branch."""
        engine = _build_prose( device="cpu", debug=False )
        fake_model = Mock()
        with patch( "transformers.AutoTokenizer" ), \
             patch( "transformers.AutoModel" ) as mock_model, \
             patch( "cosa.memory.local_embedding_engine.vram_report" ) as mock_vram:
            mock_model.from_pretrained.return_value.to.return_value.eval.return_value = fake_model
            engine._load_model()
        self.assertIsNotNone( engine._model )
        mock_vram.assert_not_called()                            # 348->exit

    def test_load_model_short_circuits_when_loaded( self ):
        """_load_model returns immediately when already loaded."""
        engine = _build_prose()
        engine._model = Mock()
        with patch( "transformers.AutoModel" ) as mock_model:
            engine._load_model()
        mock_model.from_pretrained.assert_not_called()

    def test_load_model_inner_guard( self ):
        """Inner double-checked guard returns when the model appears during locking."""
        engine = _build_prose()

        class _SettingLock:
            def __enter__( self_lock ):
                engine._model = Mock()
                return self_lock

            def __exit__( self_lock, *exc ):
                return False

        engine._inference_lock = _SettingLock()
        with patch( "transformers.AutoModel" ) as mock_model:
            engine._load_model()
        mock_model.from_pretrained.assert_not_called()

    def test_mean_pooling_masks_padding( self ):
        """_mean_pooling returns the attention-masked mean over the token axis."""
        engine = _build_prose()
        # batch=1, seq=2, hidden=3; second token fully masked out
        token_embeddings = torch.tensor( [ [ [ 1.0, 1.0, 1.0 ], [ 9.0, 9.0, 9.0 ] ] ] )
        attention_mask   = torch.tensor( [ [ 1.0, 0.0 ] ] )
        pooled = engine._mean_pooling( ( token_embeddings, ), attention_mask )
        # masked mean == the first (unmasked) token's values
        self.assertTrue( torch.allclose( pooled, torch.tensor( [ [ 1.0, 1.0, 1.0 ] ] ) ) )

    def test_encode_batch_pipeline_on_cpu( self ):
        """_encode_batch runs tokenize→model→pool→layernorm→matryoshka→L2 on CPU tensors."""
        engine = _build_prose( device="cpu", matryoshka="4" )
        engine._matryoshka_dim = 4
        encoded = {
            "input_ids"      : torch.ones( ( 1, 3 ), dtype=torch.long ),
            "attention_mask" : torch.ones( ( 1, 3 ) ),
        }
        tok = Mock()
        tok.return_value.to.return_value = encoded
        engine._tokenizer = tok
        model = Mock()
        # Varied hidden values (NOT constant) so layer_norm yields a non-zero vector
        last_hidden = torch.arange( 8 ).float().reshape( 1, 1, 8 ).expand( 1, 3, 8 ).contiguous()
        model.return_value = ( last_hidden, )                    # last_hidden_state (b, seq, hidden)
        engine._model = model

        result = engine._encode_batch( [ "search_query: hello" ] )
        self.assertEqual( result.shape, ( 1, 4 ) )               # matryoshka truncation to 4
        # L2-normalized → unit norm
        self.assertAlmostEqual( float( np.linalg.norm( result[ 0 ] ) ), 1.0, places=5 )

    def test_encode_query_prefixes( self ):
        """encode_query prepends the query prefix and returns a list (debug+verbose)."""
        engine = _build_prose( debug=True, verbose=True )
        with patch.object( engine, "_load_model" ), \
             patch.object( engine, "_encode_batch", return_value=np.array( [ _VEC768 ] ) ) as mock_eb, \
             patch( "builtins.print" ):
            result = engine.encode_query( [ "what is ml" ] )
        self.assertEqual( result, [ _VEC768 ] )
        self.assertEqual( mock_eb.call_args[ 0 ][ 0 ], [ "search_query: what is ml" ] )

    def test_encode_query_no_debug_skips_timer( self ):
        """encode_query with debug off skips the timer branches."""
        engine = _build_prose( debug=False )
        with patch.object( engine, "_load_model" ), \
             patch.object( engine, "_encode_batch", return_value=np.array( [ _VEC768 ] ) ):
            result = engine.encode_query( [ "q" ] )
        self.assertEqual( result, [ _VEC768 ] )

    def test_encode_document_prefixes( self ):
        """encode_document prepends the document prefix and returns a list (debug off)."""
        engine = _build_prose()
        with patch.object( engine, "_load_model" ), \
             patch.object( engine, "_encode_batch", return_value=np.array( [ _VEC768 ] ) ) as mock_eb:
            result = engine.encode_document( [ "ml is a field" ] )
        self.assertEqual( result, [ _VEC768 ] )
        self.assertEqual( mock_eb.call_args[ 0 ][ 0 ], [ "search_document: ml is a field" ] )

    def test_encode_document_debug_verbose_timer( self ):
        """encode_document with debug+verbose exercises the timer branches."""
        engine = _build_prose( debug=True, verbose=True )
        with patch.object( engine, "_load_model" ), \
             patch.object( engine, "_encode_batch", return_value=np.array( [ _VEC768 ] ) ), \
             patch( "builtins.print" ):
            result = engine.encode_document( [ "ml is a field" ] )
        self.assertEqual( result, [ _VEC768 ] )

    def test_run_with_cuda_retry_arms( self ):
        """success / non-CUDA-reraise / CUDA-OOM-retry on the prose engine."""
        engine = _build_prose( debug=True )
        self.assertEqual( engine._run_with_cuda_retry( lambda: 7 ), 7 )

        def _non_cuda():
            raise RuntimeError( "value error not gpu" )
        with self.assertRaises( RuntimeError ):
            engine._run_with_cuda_retry( _non_cuda )

        calls = { "n": 0 }
        def _oom():
            calls[ "n" ] += 1
            if calls[ "n" ] == 1:
                raise RuntimeError( "CUBLAS failure" )
            return "ok"
        with patch( "torch.cuda.empty_cache" ), patch( "gc.collect" ), patch( "builtins.print" ):
            self.assertEqual( engine._run_with_cuda_retry( _oom ), "ok" )

    def test_unload_loaded_and_unloaded( self ):
        """unload frees model+tokenizer when loaded; no-op when already unloaded."""
        engine = _build_prose( debug=True )
        engine._model     = Mock()
        engine._tokenizer = Mock()
        with patch( "torch.cuda.empty_cache" ) as mock_empty, patch( "builtins.print" ):
            engine.unload()
        self.assertIsNone( engine._model )
        self.assertIsNone( engine._tokenizer )
        mock_empty.assert_called_once()
        with patch( "torch.cuda.empty_cache" ) as mock_empty2:
            engine.unload()
        mock_empty2.assert_not_called()


class TestVramReport( unittest.TestCase ):
    """vram_report device-parsing + cuda-availability arms."""

    def test_cuda_unavailable_returns_zeros( self ):
        with patch( "torch.cuda.is_available", return_value=False ):
            report = vram_report()
        self.assertEqual( report, { "allocated_gb": 0.0, "reserved_gb": 0.0, "peak_gb": 0.0 } )

    def test_device_string_with_index( self ):
        """'cuda:1' → device index 1."""
        with patch( "torch.cuda.is_available", return_value=True ), \
             patch( "torch.cuda.memory_allocated", return_value=1024 ** 3 ) as mock_alloc, \
             patch( "torch.cuda.memory_reserved", return_value=2 * 1024 ** 3 ), \
             patch( "torch.cuda.max_memory_allocated", return_value=3 * 1024 ** 3 ):
            report = vram_report( "cuda:1" )
        mock_alloc.assert_called_once_with( 1 )
        self.assertAlmostEqual( report[ "allocated_gb" ], 1.0 )
        self.assertAlmostEqual( report[ "reserved_gb" ], 2.0 )
        self.assertAlmostEqual( report[ "peak_gb" ], 3.0 )

    def test_device_string_without_index( self ):
        """Bare 'cuda' → device index 0."""
        with patch( "torch.cuda.is_available", return_value=True ), \
             patch( "torch.cuda.memory_allocated", return_value=0 ) as mock_alloc, \
             patch( "torch.cuda.memory_reserved", return_value=0 ), \
             patch( "torch.cuda.max_memory_allocated", return_value=0 ):
            vram_report( "cuda" )
        mock_alloc.assert_called_once_with( 0 )

    def test_device_int( self ):
        """An int device is used directly as the index."""
        with patch( "torch.cuda.is_available", return_value=True ), \
             patch( "torch.cuda.memory_allocated", return_value=0 ) as mock_alloc, \
             patch( "torch.cuda.memory_reserved", return_value=0 ), \
             patch( "torch.cuda.max_memory_allocated", return_value=0 ):
            vram_report( 2 )
        mock_alloc.assert_called_once_with( 2 )


if __name__ == "__main__":
    unittest.main()
