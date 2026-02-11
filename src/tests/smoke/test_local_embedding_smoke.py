"""
GPU smoke test for local embedding engines (CodeRankEmbed + nomic-embed-text-v1.5).

Requires:
- GPU with CUDA support (~1.1-1.4 GB VRAM combined)
- Downloaded models (nomic-ai/CodeRankEmbed, nomic-ai/nomic-embed-text-v1.5)
- LUPIN_CONFIG_MGR_CLI_ARGS environment variable set

Run: pytest src/tests/smoke/test_local_embedding_smoke.py -v -s
"""

import pytest
import numpy as np
import os

# Skip entire module if no GPU or config env not set
pytestmark = [
    pytest.mark.skipif(
        not os.environ.get( "LUPIN_CONFIG_MGR_CLI_ARGS" ),
        reason="LUPIN_CONFIG_MGR_CLI_ARGS not set"
    ),
]


def _cosine_similarity( a, b ):
    """Compute cosine similarity between two vectors."""
    a = np.array( a )
    b = np.array( b )
    return float( np.dot( a, b ) / ( np.linalg.norm( a ) * np.linalg.norm( b ) ) )


class TestCodeEmbeddingEngineSmoke:
    """Smoke tests for CodeEmbeddingEngine on real GPU."""

    def test_load_and_encode_code( self ):
        """Load CodeRankEmbed and verify 768-dim output."""
        from cosa.memory.local_embedding_engine import get_code_engine
        engine = get_code_engine( debug=True, verbose=True )

        snippets = [ "def quicksort( arr ):\n    if len( arr ) <= 1: return arr" ]
        embeddings = engine.encode_code( snippets )

        assert len( embeddings ) == 1
        assert len( embeddings[ 0 ] ) == 768
        print( f"  Code embedding dims: {len( embeddings[ 0 ] )}" )

    def test_code_query_vs_snippet_similarity( self ):
        """Verify code queries rank relevant snippets higher."""
        from cosa.memory.local_embedding_engine import get_code_engine
        engine = get_code_engine( debug=False )

        query_emb = engine.encode_query( [ "sorting algorithm implementation" ] )[ 0 ]

        code_relevant   = engine.encode_code( [ "def bubble_sort( arr ):\n    for i in range( len( arr ) ):\n        for j in range( len( arr ) - 1 ):\n            if arr[ j ] > arr[ j + 1 ]: arr[ j ], arr[ j + 1 ] = arr[ j + 1 ], arr[ j ]" ] )[ 0 ]
        code_irrelevant = engine.encode_code( [ "def connect_db( host, port ):\n    return psycopg2.connect( host=host, port=port )" ] )[ 0 ]

        sim_relevant   = _cosine_similarity( query_emb, code_relevant )
        sim_irrelevant = _cosine_similarity( query_emb, code_irrelevant )

        print( f"  Similarity (sorting query vs sort code):     {sim_relevant:.4f}" )
        print( f"  Similarity (sorting query vs db code):       {sim_irrelevant:.4f}" )
        assert sim_relevant > sim_irrelevant, "Relevant code should rank higher"


class TestProseEmbeddingEngineSmoke:
    """Smoke tests for ProseEmbeddingEngine on real GPU."""

    def test_load_and_encode_query( self ):
        """Load nomic-embed-text-v1.5 and verify Matryoshka-dim output."""
        from cosa.memory.local_embedding_engine import get_prose_engine
        engine = get_prose_engine( debug=True, verbose=True )

        embeddings = engine.encode_query( [ "What time is it right now?" ] )

        assert len( embeddings ) == 1
        assert len( embeddings[ 0 ] ) == engine._matryoshka_dim
        print( f"  Prose embedding dims: {len( embeddings[ 0 ] )}" )

    def test_prose_query_vs_document_similarity( self ):
        """Verify prose queries rank relevant documents higher."""
        from cosa.memory.local_embedding_engine import get_prose_engine
        engine = get_prose_engine( debug=False )

        query_emb = engine.encode_query( [ "What is the weather forecast?" ] )[ 0 ]

        doc_relevant   = engine.encode_document( [ "Today's weather forecast shows partly cloudy skies with a high of 75 degrees." ] )[ 0 ]
        doc_irrelevant = engine.encode_document( [ "The Python programming language was created by Guido van Rossum in 1991." ] )[ 0 ]

        sim_relevant   = _cosine_similarity( query_emb, doc_relevant )
        sim_irrelevant = _cosine_similarity( query_emb, doc_irrelevant )

        print( f"  Similarity (weather query vs weather doc):   {sim_relevant:.4f}" )
        print( f"  Similarity (weather query vs python doc):    {sim_irrelevant:.4f}" )
        assert sim_relevant > sim_irrelevant, "Relevant document should rank higher"


class TestVramSmoke:
    """Smoke tests for VRAM reporting with both models loaded."""

    def test_vram_report_after_both_models( self ):
        """Check combined VRAM after loading both engines."""
        from cosa.memory.local_embedding_engine import get_code_engine, get_prose_engine, vram_report

        # Ensure both models are loaded
        get_code_engine( debug=False ).encode_code( [ "test" ] )
        get_prose_engine( debug=False ).encode_query( [ "test" ] )

        report = vram_report( "cuda:0" )
        print( f"\n  Combined VRAM report:" )
        print( f"    Allocated: {report[ 'allocated_gb' ]:.2f} GB" )
        print( f"    Reserved:  {report[ 'reserved_gb' ]:.2f} GB" )
        print( f"    Peak:      {report[ 'peak_gb' ]:.2f} GB" )

        assert report[ "allocated_gb" ] > 0, "Should have some VRAM allocated"


class TestEmbeddingProviderSmoke:
    """Smoke tests for EmbeddingProvider routing layer."""

    def test_provider_routes_to_local_prose( self ):
        """Verify EmbeddingProvider routes prose to local engine."""
        from cosa.memory.embedding_provider import get_embedding_provider
        provider = get_embedding_provider( debug=True, verbose=True )

        if provider._provider != "local":
            pytest.skip( "Provider not set to 'local' in config" )

        embedding = provider.generate_embedding( "What is the meaning of life?", content_type="prose" )
        assert len( embedding ) == provider.dimensions
        print( f"  Provider prose dims: {len( embedding )}" )

    def test_provider_routes_to_local_code( self ):
        """Verify EmbeddingProvider routes code to local engine."""
        from cosa.memory.embedding_provider import get_embedding_provider
        provider = get_embedding_provider( debug=False )

        if provider._provider != "local":
            pytest.skip( "Provider not set to 'local' in config" )

        embedding = provider.generate_embedding( "def hello(): print( 'hi' )", content_type="code" )
        assert len( embedding ) == provider.code_dimensions
        print( f"  Provider code dims: {len( embedding )}" )

    def test_metrics_collection( self ):
        """Verify metrics are collected after embedding generation."""
        from cosa.memory.embedding_provider import get_embedding_provider
        provider = get_embedding_provider( debug=False )

        if provider._provider != "local":
            pytest.skip( "Provider not set to 'local' in config" )

        provider.reset_metrics()
        provider.generate_embedding( "test prose", content_type="prose" )
        provider.generate_embedding( "def test():", content_type="code" )

        metrics = provider.get_metrics_summary()
        print( f"\n  Metrics summary:" )
        for key, stats in metrics.items():
            print( f"    {key}: count={stats[ 'count' ]}, avg_ms={stats[ 'avg_ms' ]:.1f}" )

        assert "local_prose" in metrics
        assert "local_code" in metrics
        assert metrics[ "local_prose" ][ "count" ] == 1
        assert metrics[ "local_code" ][ "count" ] == 1
