"""
Local GPU-based embedding engines for code and prose content.

Provides two singleton engines:
- CodeEmbeddingEngine: Uses SentenceTransformer("nomic-ai/CodeRankEmbed") for code search
- ProseEmbeddingEngine: Uses raw transformers for nomic-embed-text-v1.5 with Matryoshka support

Both engines support lazy GPU loading, L2-normalized output, and configurable via lupin-app.ini.
"""

import gc

import torch
import numpy as np
from threading import Lock
from typing import List, Optional, Dict, Any

import cosa.utils.util as du
import cosa.utils.util_stopwatch as sw
from cosa.config.configuration_manager import ConfigurationManager


class CodeEmbeddingEngine:
    """
    Singleton engine for code embedding using nomic-ai/CodeRankEmbed.

    Uses SentenceTransformer for model loading. Produces fixed 768-dim,
    L2-normalized embeddings. Supports asymmetric search with query prefix.
    """

    _instance        = None
    _lock            = Lock()
    _inference_lock  = Lock()

    def __new__( cls, debug=False, verbose=False ):
        """
        Create or return singleton instance.

        Requires:
            - Nothing

        Ensures:
            - Returns the single instance of CodeEmbeddingEngine
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
        Initialize the code embedding engine with lazy GPU loading.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set
            - sentence-transformers package is installed

        Ensures:
            - Reads config for model name, device, dtype, prefix
            - Does NOT load model yet (lazy loading on first encode call)

        Raises:
            - ConfigurationManager errors if env var not set
        """
        if self._initialized:
            return

        self.debug   = debug
        self.verbose = verbose

        self._config_mgr   = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._model_name   = self._config_mgr.get( "local embedding code model name" )
        self._device       = self._config_mgr.get( "local embedding device" )
        self._dtype_str    = self._config_mgr.get( "local embedding dtype" )
        self._dimensions   = int( self._config_mgr.get( "local embedding code model dimensions" ) )
        self._query_prefix = self._config_mgr.get( "local embedding code query prefix" )
        self._model        = None

        if self.debug: print( f"CodeEmbeddingEngine configured: model={self._model_name}, device={self._device}, dims={self._dimensions}" )

        self._initialized = True

    def _load_model( self ):
        """
        Lazy-load the SentenceTransformer model onto GPU.

        Requires:
            - Model is downloaded and available in local HuggingFace cache

        Ensures:
            - self._model is a loaded SentenceTransformer
            - Model is on the configured device with configured dtype
            - Thread-safe via double-checked locking on _inference_lock
            - Never contacts HuggingFace Hub (local_files_only=True).
              Without this, SentenceTransformer checks the Hub on every
              load — problematic during rapid restart cycles in testing
              and when the network is unreliable.
        """
        if self._model is not None:
            return

        with self._inference_lock:
            if self._model is not None:
                return

            timer = sw.Stopwatch( msg=f"Loading CodeRankEmbed onto {self._device}..." )

            from sentence_transformers import SentenceTransformer

            dtype_map = { "float16": torch.float16, "float32": torch.float32, "bfloat16": torch.bfloat16 }
            model_dtype = dtype_map.get( self._dtype_str, torch.float16 )

            self._model = SentenceTransformer(
                self._model_name,
                trust_remote_code=True,
                local_files_only=True,
                device=self._device,
                model_kwargs={ "torch_dtype": model_dtype }
            )

            timer.print( "Done!", use_millis=True )

            if self.debug and self._device.startswith( "cuda" ):
                vram = vram_report( self._device )
                print( f"  VRAM after load: allocated={vram[ 'allocated_gb' ]:.2f} GB, peak={vram[ 'peak_gb' ]:.2f} GB" )

    def _run_with_cuda_retry( self, fn ):
        """
        Run fn() with single CUDA OOM retry.

        Requires:
            - fn is a callable performing GPU inference
            - Called within self._inference_lock

        Ensures:
            - Returns fn() result on success
            - On CUDA OOM: gc.collect + empty_cache, retries once
            - Non-CUDA RuntimeErrors re-raised immediately
        """
        try:
            return fn()
        except ( torch.cuda.OutOfMemoryError, RuntimeError ) as e:
            if "CUDA" not in str( e ) and "CUBLAS" not in str( e ):
                raise
            if self.debug: print( f"[WARN] CUDA OOM in {self.__class__.__name__}, clearing cache and retrying..." )
            gc.collect()
            torch.cuda.empty_cache()
            return fn()

    def encode_query( self, queries: List[ str ] ) -> List[ List[ float ] ]:
        """
        Encode query strings with the code query prefix.

        Requires:
            - queries is a list of non-empty strings

        Ensures:
            - Returns list of 768-dim L2-normalized embeddings
            - Prepends query prefix to each query
            - Thread-safe: serializes inference via _inference_lock
            - CUDA OOM: gc.collect + empty_cache, retries once

        Args:
            queries: List of query strings to encode

        Returns:
            List of embedding vectors (each 768 floats)
        """
        self._load_model()

        prefixed = [ f"{self._query_prefix} {q}" for q in queries ]

        if self.debug and self.verbose:
            timer = sw.Stopwatch( msg=f"Encoding {len( queries )} code queries..." )

        with self._inference_lock:
            embeddings = self._run_with_cuda_retry( lambda: self._model.encode( prefixed, normalize_embeddings=True ) )

        if self.debug and self.verbose:
            timer.print( "Done!", use_millis=True )

        return embeddings.tolist()

    def encode_code( self, code_snippets: List[ str ] ) -> List[ List[ float ] ]:
        """
        Encode code snippets (documents) without prefix.

        Requires:
            - code_snippets is a list of non-empty strings

        Ensures:
            - Returns list of 768-dim L2-normalized embeddings
            - No prefix applied (asymmetric: documents have no prefix)
            - Thread-safe: serializes inference via _inference_lock
            - CUDA OOM: gc.collect + empty_cache, retries once

        Args:
            code_snippets: List of code strings to encode

        Returns:
            List of embedding vectors (each 768 floats)
        """
        self._load_model()

        if self.debug and self.verbose:
            timer = sw.Stopwatch( msg=f"Encoding {len( code_snippets )} code snippets..." )

        with self._inference_lock:
            embeddings = self._run_with_cuda_retry( lambda: self._model.encode( code_snippets, normalize_embeddings=True ) )

        if self.debug and self.verbose:
            timer.print( "Done!", use_millis=True )

        return embeddings.tolist()

    def unload( self ):
        """Unload model from GPU to free VRAM. Thread-safe via _inference_lock."""
        with self._inference_lock:
            if self._model is not None:
                del self._model
                self._model = None
                torch.cuda.empty_cache()
                if self.debug: print( "CodeEmbeddingEngine: model unloaded" )

    @property
    def dimensions( self ):
        """Return the output embedding dimensions."""
        return self._dimensions

    @property
    def model_name( self ):
        """Return the model name."""
        return self._model_name

    @property
    def is_loaded( self ):
        """Return whether the model is loaded on GPU."""
        return self._model is not None


class ProseEmbeddingEngine:
    """
    Singleton engine for prose embedding using nomic-ai/nomic-embed-text-v1.5.

    Uses raw transformers (AutoModel + AutoTokenizer) for full Matryoshka
    dimension control. Supports asymmetric search with query/document prefixes.
    Produces L2-normalized embeddings at configurable dimensions (64-768).
    """

    _instance        = None
    _lock            = Lock()
    _inference_lock  = Lock()

    def __new__( cls, debug=False, verbose=False ):
        """
        Create or return singleton instance.

        Requires:
            - Nothing

        Ensures:
            - Returns the single instance of ProseEmbeddingEngine
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
        Initialize the prose embedding engine with lazy GPU loading.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set
            - transformers package is installed

        Ensures:
            - Reads config for model name, device, dtype, prefixes, Matryoshka dim
            - Does NOT load model yet (lazy loading on first encode call)

        Raises:
            - ConfigurationManager errors if env var not set
        """
        if self._initialized:
            return

        self.debug   = debug
        self.verbose = verbose

        self._config_mgr       = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        self._model_name       = self._config_mgr.get( "local embedding prose model name" )
        self._device           = self._config_mgr.get( "local embedding device" )
        self._dtype_str        = self._config_mgr.get( "local embedding dtype" )
        self._max_dimensions   = int( self._config_mgr.get( "local embedding prose model dimensions" ) )
        self._matryoshka_dim   = int( self._config_mgr.get( "local embedding prose matryoshka dim" ) )
        self._query_prefix     = self._config_mgr.get( "local embedding prose query prefix" )
        self._document_prefix  = self._config_mgr.get( "local embedding prose document prefix" )
        self._model            = None
        self._tokenizer        = None

        if self.debug: print( f"ProseEmbeddingEngine configured: model={self._model_name}, device={self._device}, matryoshka_dim={self._matryoshka_dim}" )

        self._initialized = True

    def _load_model( self ):
        """
        Lazy-load the transformers model and tokenizer onto GPU.

        Requires:
            - Model is available on HuggingFace or locally cached
            - bert-base-uncased tokenizer is available

        Ensures:
            - self._model is a loaded AutoModel in eval mode
            - self._tokenizer is a loaded AutoTokenizer
            - Model is on the configured device with configured dtype
            - Thread-safe via double-checked locking on _inference_lock
        """
        if self._model is not None:
            return

        with self._inference_lock:
            if self._model is not None:
                return

            timer = sw.Stopwatch( msg=f"Loading nomic-embed-text-v1.5 onto {self._device}..." )

            from transformers import AutoModel, AutoTokenizer

            dtype_map = { "float16": torch.float16, "float32": torch.float32, "bfloat16": torch.bfloat16 }
            model_dtype = dtype_map.get( self._dtype_str, torch.float16 )

            self._tokenizer = AutoTokenizer.from_pretrained( "bert-base-uncased" )
            self._model = AutoModel.from_pretrained(
                self._model_name,
                trust_remote_code=True,
                torch_dtype=model_dtype
            ).to( self._device ).eval()

            timer.print( "Done!", use_millis=True )

            if self.debug and self._device.startswith( "cuda" ):
                vram = vram_report( self._device )
                print( f"  VRAM after load: allocated={vram[ 'allocated_gb' ]:.2f} GB, peak={vram[ 'peak_gb' ]:.2f} GB" )

    def _mean_pooling( self, model_output, attention_mask ):
        """
        Apply mean pooling to token embeddings using attention mask.

        Requires:
            - model_output is a transformers BaseModelOutput with last_hidden_state
            - attention_mask is a tensor matching the token dimensions

        Ensures:
            - Returns mean-pooled tensor of shape (batch_size, hidden_dim)
            - Properly masks padding tokens
        """
        token_embeddings = model_output[ 0 ]
        input_mask_expanded = attention_mask.unsqueeze( -1 ).expand( token_embeddings.size() ).float()
        return torch.sum( token_embeddings * input_mask_expanded, 1 ) / torch.clamp( input_mask_expanded.sum( 1 ), min=1e-9 )

    def _encode_batch( self, texts: List[ str ] ) -> np.ndarray:
        """
        Encode a batch of texts through the model pipeline.

        Requires:
            - texts is a list of non-empty strings (already prefixed)
            - Model is loaded

        Ensures:
            - Returns numpy array of shape (batch_size, matryoshka_dim)
            - Applies mean pooling, layer norm, Matryoshka truncation, L2 normalization

        Args:
            texts: List of prefixed text strings

        Returns:
            numpy array of L2-normalized embeddings
        """
        encoded = self._tokenizer(
            texts, padding=True, truncation=True, max_length=8192, return_tensors="pt"
        ).to( self._device )

        with torch.no_grad():
            model_output = self._model( **encoded )

        embeddings = self._mean_pooling( model_output, encoded[ "attention_mask" ] )

        # Layer norm (as required by nomic-embed-text-v1.5)
        embeddings = torch.nn.functional.layer_norm( embeddings, normalized_shape=( embeddings.shape[ 1 ], ) )

        # Matryoshka truncation
        embeddings = embeddings[ :, :self._matryoshka_dim ]

        # L2 normalize
        embeddings = torch.nn.functional.normalize( embeddings, p=2, dim=1 )

        return embeddings.cpu().numpy()

    def _run_with_cuda_retry( self, fn ):
        """
        Run fn() with single CUDA OOM retry.

        Requires:
            - fn is a callable performing GPU inference
            - Called within self._inference_lock

        Ensures:
            - Returns fn() result on success
            - On CUDA OOM: gc.collect + empty_cache, retries once
            - Non-CUDA RuntimeErrors re-raised immediately
        """
        try:
            return fn()
        except ( torch.cuda.OutOfMemoryError, RuntimeError ) as e:
            if "CUDA" not in str( e ) and "CUBLAS" not in str( e ):
                raise
            if self.debug: print( f"[WARN] CUDA OOM in {self.__class__.__name__}, clearing cache and retrying..." )
            gc.collect()
            torch.cuda.empty_cache()
            return fn()

    def encode_query( self, queries: List[ str ] ) -> List[ List[ float ] ]:
        """
        Encode query strings with the query prefix.

        Requires:
            - queries is a list of non-empty strings

        Ensures:
            - Returns list of matryoshka_dim L2-normalized embeddings
            - Prepends query prefix to each query
            - Thread-safe: serializes inference via _inference_lock
            - CUDA OOM: gc.collect + empty_cache, retries once

        Args:
            queries: List of query strings to encode

        Returns:
            List of embedding vectors
        """
        self._load_model()

        prefixed = [ f"{self._query_prefix} {q}" for q in queries ]

        if self.debug and self.verbose:
            timer = sw.Stopwatch( msg=f"Encoding {len( queries )} prose queries..." )

        with self._inference_lock:
            result = self._run_with_cuda_retry( lambda: self._encode_batch( prefixed ) )

        if self.debug and self.verbose:
            timer.print( "Done!", use_millis=True )

        return result.tolist()

    def encode_document( self, documents: List[ str ] ) -> List[ List[ float ] ]:
        """
        Encode document strings with the document prefix.

        Requires:
            - documents is a list of non-empty strings

        Ensures:
            - Returns list of matryoshka_dim L2-normalized embeddings
            - Prepends document prefix to each document
            - Thread-safe: serializes inference via _inference_lock
            - CUDA OOM: gc.collect + empty_cache, retries once

        Args:
            documents: List of document strings to encode

        Returns:
            List of embedding vectors
        """
        self._load_model()

        prefixed = [ f"{self._document_prefix} {d}" for d in documents ]

        if self.debug and self.verbose:
            timer = sw.Stopwatch( msg=f"Encoding {len( documents )} prose documents..." )

        with self._inference_lock:
            result = self._run_with_cuda_retry( lambda: self._encode_batch( prefixed ) )

        if self.debug and self.verbose:
            timer.print( "Done!", use_millis=True )

        return result.tolist()

    def unload( self ):
        """Unload model and tokenizer from GPU to free VRAM. Thread-safe via _inference_lock."""
        with self._inference_lock:
            if self._model is not None:
                del self._model
                del self._tokenizer
                self._model     = None
                self._tokenizer = None
                torch.cuda.empty_cache()
                if self.debug: print( "ProseEmbeddingEngine: model unloaded" )

    @property
    def dimensions( self ):
        """Return the output embedding dimensions (Matryoshka dim)."""
        return self._matryoshka_dim

    @property
    def model_name( self ):
        """Return the model name."""
        return self._model_name

    @property
    def is_loaded( self ):
        """Return whether the model is loaded on GPU."""
        return self._model is not None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def get_code_engine( debug=False, verbose=False ):
    """
    Get singleton instance of CodeEmbeddingEngine.

    Requires:
        - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set

    Ensures:
        - Returns singleton CodeEmbeddingEngine instance
    """
    return CodeEmbeddingEngine( debug=debug, verbose=verbose )


def get_prose_engine( debug=False, verbose=False ):
    """
    Get singleton instance of ProseEmbeddingEngine.

    Requires:
        - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set

    Ensures:
        - Returns singleton ProseEmbeddingEngine instance
    """
    return ProseEmbeddingEngine( debug=debug, verbose=verbose )


def vram_report( device="cuda:0" ):
    """
    Return VRAM usage report for the given CUDA device.

    Requires:
        - device is a valid CUDA device string or int

    Ensures:
        - Returns dict with allocated_gb, reserved_gb, peak_gb keys
        - Returns zeros if CUDA is not available

    Args:
        device: CUDA device identifier (e.g., "cuda:0" or 0)

    Returns:
        Dict with VRAM statistics in GB
    """
    if not torch.cuda.is_available():
        return { "allocated_gb": 0.0, "reserved_gb": 0.0, "peak_gb": 0.0 }

    # Extract device index from string like "cuda:0"
    if isinstance( device, str ) and ":" in device:
        device_idx = int( device.split( ":" )[ 1 ] )
    elif isinstance( device, str ):
        device_idx = 0
    else:
        device_idx = device

    return {
        "allocated_gb" : torch.cuda.memory_allocated( device_idx ) / ( 1024 ** 3 ),
        "reserved_gb"  : torch.cuda.memory_reserved( device_idx ) / ( 1024 ** 3 ),
        "peak_gb"      : torch.cuda.max_memory_allocated( device_idx ) / ( 1024 ** 3 ),
    }


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def quick_smoke_test():
    """Run quick smoke test for local embedding engines."""
    du.print_banner( "Local Embedding Engine Smoke Test", prepend_nl=True )

    try:
        # Test 1: CodeEmbeddingEngine
        print( "Test 1: CodeEmbeddingEngine initialization and encoding..." )
        code_engine = get_code_engine( debug=True, verbose=True )
        print( f"  Model: {code_engine.model_name}" )
        print( f"  Dimensions: {code_engine.dimensions}" )

        # Encode query
        query_embeddings = code_engine.encode_query( [ "How to sort a list in Python" ] )
        print( f"  Query embedding: {len( query_embeddings[ 0 ] )} dims" )
        assert len( query_embeddings[ 0 ] ) == 768, f"Expected 768, got {len( query_embeddings[ 0 ] )}"
        print( "  Query embedding OK" )

        # Encode code
        code_embeddings = code_engine.encode_code( [ "sorted_list = sorted( my_list, key=lambda x: x.name )" ] )
        print( f"  Code embedding: {len( code_embeddings[ 0 ] )} dims" )
        assert len( code_embeddings[ 0 ] ) == 768, f"Expected 768, got {len( code_embeddings[ 0 ] )}"
        print( "  Code embedding OK" )

        # Verify singleton
        code_engine_2 = get_code_engine()
        assert code_engine is code_engine_2, "Singleton broken!"
        print( "  Singleton OK" )

        vram = vram_report()
        print( f"  VRAM: allocated={vram[ 'allocated_gb' ]:.2f} GB, peak={vram[ 'peak_gb' ]:.2f} GB" )
        print( "  CodeEmbeddingEngine: PASSED" )

        # Test 2: ProseEmbeddingEngine
        print( "\nTest 2: ProseEmbeddingEngine initialization and encoding..." )
        prose_engine = get_prose_engine( debug=True, verbose=True )
        print( f"  Model: {prose_engine.model_name}" )
        print( f"  Dimensions: {prose_engine.dimensions}" )

        # Encode query
        query_embeddings = prose_engine.encode_query( [ "What is machine learning?" ] )
        print( f"  Query embedding: {len( query_embeddings[ 0 ] )} dims" )
        assert len( query_embeddings[ 0 ] ) == prose_engine.dimensions, f"Dim mismatch"
        print( "  Query embedding OK" )

        # Encode document
        doc_embeddings = prose_engine.encode_document( [ "Machine learning is a subset of artificial intelligence." ] )
        print( f"  Document embedding: {len( doc_embeddings[ 0 ] )} dims" )
        assert len( doc_embeddings[ 0 ] ) == prose_engine.dimensions, f"Dim mismatch"
        print( "  Document embedding OK" )

        # Verify singleton
        prose_engine_2 = get_prose_engine()
        assert prose_engine is prose_engine_2, "Singleton broken!"
        print( "  Singleton OK" )

        vram = vram_report()
        print( f"  VRAM (both models): allocated={vram[ 'allocated_gb' ]:.2f} GB, peak={vram[ 'peak_gb' ]:.2f} GB" )
        print( "  ProseEmbeddingEngine: PASSED" )

        # Test 3: Cosine similarity sanity check
        print( "\nTest 3: Cosine similarity sanity check..." )
        q_emb = np.array( prose_engine.encode_query( [ "Python programming language" ] )[ 0 ] )
        d1_emb = np.array( prose_engine.encode_document( [ "Python is a high-level programming language" ] )[ 0 ] )
        d2_emb = np.array( prose_engine.encode_document( [ "The weather in Paris is sunny today" ] )[ 0 ] )

        sim_relevant = float( np.dot( q_emb, d1_emb ) )
        sim_irrelevant = float( np.dot( q_emb, d2_emb ) )
        print( f"  Relevant similarity:   {sim_relevant:.4f}" )
        print( f"  Irrelevant similarity: {sim_irrelevant:.4f}" )
        assert sim_relevant > sim_irrelevant, "Relevant doc should be more similar!"
        print( "  Similarity ranking: PASSED" )

        print( "\nAll local embedding engine smoke tests PASSED" )

    except Exception as e:
        print( f"  Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Smoke test failed", caller="local_embedding_engine.quick_smoke_test()" )

    print( "\nLocal Embedding Engine smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
