"""
Unit tests for the embeddings router (`cosa.rest.routers.embeddings`).

Exposes the server's warm GPU embedding model over HTTP. Three endpoints:
- POST /generate — single-text embedding
- POST /batch    — multi-text embedding (400 on empty list)
- GET  /info     — provider metadata

Covers all three endpoints + the request/response models + both arms of the
batch `dimensions` ternary. Zero external dependencies — `get_embedding_provider`
is boundary-mocked so NO GPU model is loaded and no VRAM is touched; the
`require_api_key_or_jwt` dependency is bypassed by passing the authenticated
user id explicitly on the direct call.
"""

import unittest
from unittest.mock import patch, MagicMock
import asyncio
import time

from fastapi import HTTPException

from cosa.rest.routers.embeddings import (
    router,
    generate_embedding,
    generate_embeddings_batch,
    get_info,
    EmbedRequest,
    EmbedBatchRequest,
    EmbedResponse,
    EmbedBatchResponse,
    EmbedInfoResponse,
)


class TestEmbeddingsRouter( unittest.TestCase ):
    """
    Unit tests for the embeddings endpoints.

    Requires:
        - cosa.rest.routers.embeddings importable
        - get_embedding_provider boundary-mocked (no GPU/VRAM)

    Ensures:
        - single + batch + info endpoints return correctly-shaped responses
        - empty batch raises 400
        - the batch dimensions ternary covers both the populated + empty arms
    """

    # ---- /generate ----------------------------------------------------------

    def test_generate_embedding_returns_vector_and_dims( self ):
        """
        Ensures:
            - The provider's vector is returned with its length as dimensions
            - content_type from the request is threaded to the provider
        """
        provider = MagicMock()
        provider.generate_embedding.return_value = [ 0.1, 0.2, 0.3 ]

        with patch( "cosa.rest.routers.embeddings.get_embedding_provider", return_value=provider ):
            resp = asyncio.run( generate_embedding(
                request               = EmbedRequest( text="hello", content_type="code" ),
                authenticated_user_id = "user_1",
            ) )

        self.assertIsInstance( resp, EmbedResponse )
        self.assertEqual( resp.embedding, [ 0.1, 0.2, 0.3 ] )
        self.assertEqual( resp.dimensions, 3 )
        provider.generate_embedding.assert_called_once_with( "hello", content_type="code" )

    # ---- /batch -------------------------------------------------------------

    def test_batch_empty_texts_raises_400( self ):
        """
        Ensures:
            - An empty `texts` list raises HTTPException 400 before the provider call
        """
        provider = MagicMock()
        with patch( "cosa.rest.routers.embeddings.get_embedding_provider", return_value=provider ):
            with self.assertRaises( HTTPException ) as ctx:
                asyncio.run( generate_embeddings_batch(
                    request               = EmbedBatchRequest( texts=[] ),
                    authenticated_user_id = "user_1",
                ) )

        self.assertEqual( ctx.exception.status_code, 400 )
        provider.generate_embeddings_batch.assert_not_called()

    def test_batch_returns_embeddings_with_dims_and_count( self ):
        """
        Ensures:
            - Non-empty batch returns all vectors, count, and dims from vector[0]
        """
        provider = MagicMock()
        provider.generate_embeddings_batch.return_value = [ [ 1.0, 2.0 ], [ 3.0, 4.0 ] ]

        with patch( "cosa.rest.routers.embeddings.get_embedding_provider", return_value=provider ):
            resp = asyncio.run( generate_embeddings_batch(
                request               = EmbedBatchRequest( texts=[ "a", "b" ], content_type="prose" ),
                authenticated_user_id = "user_1",
            ) )

        self.assertIsInstance( resp, EmbedBatchResponse )
        self.assertEqual( resp.embeddings, [ [ 1.0, 2.0 ], [ 3.0, 4.0 ] ] )
        self.assertEqual( resp.dimensions, 2 )
        self.assertEqual( resp.count, 2 )
        provider.generate_embeddings_batch.assert_called_once_with( [ "a", "b" ], content_type="prose" )

    def test_batch_provider_returns_empty_dims_zero( self ):
        """
        Ensures:
            - When the texts list is non-empty but the provider returns no vectors,
              `dimensions` is 0 (covers the `else 0` arm of the ternary)
        """
        provider = MagicMock()
        provider.generate_embeddings_batch.return_value = []

        with patch( "cosa.rest.routers.embeddings.get_embedding_provider", return_value=provider ):
            resp = asyncio.run( generate_embeddings_batch(
                request               = EmbedBatchRequest( texts=[ "a" ] ),
                authenticated_user_id = "user_1",
            ) )

        self.assertEqual( resp.dimensions, 0 )
        self.assertEqual( resp.count, 0 )
        self.assertEqual( resp.embeddings, [] )

    # ---- /info --------------------------------------------------------------

    def test_get_info_returns_provider_metadata( self ):
        """
        Ensures:
            - /info reports the provider name, dimensions, and 'ready' status
        """
        provider = MagicMock()
        provider.provider_name = "local_nomic"
        provider.dimensions    = 768

        with patch( "cosa.rest.routers.embeddings.get_embedding_provider", return_value=provider ):
            resp = asyncio.run( get_info( authenticated_user_id="user_1" ) )

        self.assertIsInstance( resp, EmbedInfoResponse )
        self.assertEqual( resp.provider, "local_nomic" )
        self.assertEqual( resp.dimensions, 768 )
        self.assertEqual( resp.status, "ready" )

    # ---- models / registration ----------------------------------------------

    def test_request_model_defaults( self ):
        """
        Ensures:
            - EmbedRequest / EmbedBatchRequest default content_type to 'prose'
        """
        self.assertEqual( EmbedRequest( text="x" ).content_type, "prose" )
        self.assertEqual( EmbedBatchRequest( texts=[ "x" ] ).content_type, "prose" )

    def test_router_prefix_and_routes( self ):
        """
        Ensures:
            - Router carries /api/embeddings prefix with all three routes registered
        """
        self.assertEqual( router.prefix, "/api/embeddings" )
        paths = { route.path for route in router.routes }
        self.assertEqual(
            paths,
            { "/api/embeddings/generate", "/api/embeddings/batch", "/api/embeddings/info" },
        )


def isolated_unit_test():
    """
    Run the embeddings router unit tests in isolation.

    Ensures:
        - Executes the TestCase and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        suite  = unittest.TestLoader().loadTestsFromTestCase( TestEmbeddingsRouter )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL EMBEDDINGS ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME EMBEDDINGS ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 EMBEDDINGS ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Embeddings router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
