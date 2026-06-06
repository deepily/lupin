"""
Embedding generation API endpoints.

Exposes the server's already-warm GPU embedding model via HTTP so that
external scripts (e.g. seed_proxy_decisions.py) can generate embeddings
without loading a second copy of the model into VRAM.

Generated on: 2026-02-24
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Annotated, List

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.memory.embedding_provider import get_embedding_provider

router = APIRouter( prefix="/api/embeddings", tags=[ "embeddings" ] )


# ============================================================================
# Request/Response Models
# ============================================================================

class EmbedRequest( BaseModel ):
    """Request body for single-text embedding generation."""
    text         : str
    content_type : str = "prose"    # "prose" or "code"


class EmbedBatchRequest( BaseModel ):
    """Request body for batch embedding generation."""
    texts        : List[ str ]
    content_type : str = "prose"


class EmbedResponse( BaseModel ):
    """Response for single embedding."""
    embedding  : List[ float ]
    dimensions : int


class EmbedBatchResponse( BaseModel ):
    """Response for batch embeddings."""
    embeddings : List[ List[ float ] ]
    dimensions : int
    count      : int


class EmbedInfoResponse( BaseModel ):
    """Response for provider info."""
    provider   : str
    dimensions : int
    status     : str


# ============================================================================
# Endpoints
# ============================================================================

@router.post(
    "/generate",
    response_model = EmbedResponse,
    summary        = "Generate embedding",
    description    = "Generate an embedding vector for a single text string using the GPU model."
)
async def generate_embedding(
    request             : EmbedRequest,
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ] = None
):
    """
    Generate an embedding vector for a single text string.

    Uses the server's already-loaded GPU model (singleton).
    """
    # FM-7 event-loop offload: GPU inference is blocking; run it OFF the event
    # loop so this endpoint (reachable as the prediction engine's HTTP fallback)
    # never freezes the loop — which would otherwise self-deadlock against the
    # caller and stall /health.
    provider  = get_embedding_provider()
    embedding = await asyncio.to_thread( provider.generate_embedding, request.text, content_type=request.content_type )

    return EmbedResponse(
        embedding  = embedding,
        dimensions = len( embedding )
    )


@router.post(
    "/batch",
    response_model = EmbedBatchResponse,
    summary        = "Batch generate embeddings",
    description    = "Generate embedding vectors for multiple texts in a single call."
)
async def generate_embeddings_batch(
    request             : EmbedBatchRequest,
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ] = None
):
    """
    Generate embedding vectors for a list of texts.

    Uses the server's already-loaded GPU model (singleton).
    """
    if not request.texts:
        raise HTTPException( status_code=400, detail="texts list must not be empty" )

    # FM-7 event-loop offload: batch GPU inference is blocking; run it OFF the
    # event loop so this endpoint never freezes the loop.
    provider   = get_embedding_provider()
    embeddings = await asyncio.to_thread( provider.generate_embeddings_batch, request.texts, content_type=request.content_type )

    return EmbedBatchResponse(
        embeddings = embeddings,
        dimensions = len( embeddings[ 0 ] ) if embeddings else 0,
        count      = len( embeddings )
    )


@router.get(
    "/info",
    response_model = EmbedInfoResponse,
    summary        = "Get embedding info",
    description    = "Return provider name, dimensions, and readiness status of the embedding model."
)
async def get_info(
    authenticated_user_id : Annotated[ str, Depends( require_api_key_or_jwt ) ] = None
):
    """
    Return metadata about the active embedding provider.
    """
    provider = get_embedding_provider()

    return EmbedInfoResponse(
        provider   = provider.provider_name,
        dimensions = provider.dimensions,
        status     = "ready"
    )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test to validate embeddings router imports and models."""
    import cosa.utils.util as du

    du.print_banner( "Embeddings Router Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import the router
        print( "Testing router import..." )
        assert router is not None
        assert router.prefix == "/api/embeddings"
        print( "✓ Router imported successfully" )

        # Test 2: Test Pydantic models
        print( "\nTesting Pydantic models..." )

        req = EmbedRequest( text="hello world" )
        assert req.text == "hello world"
        assert req.content_type == "prose"
        print( "✓ EmbedRequest works" )

        batch_req = EmbedBatchRequest( texts=[ "hello", "world" ] )
        assert len( batch_req.texts ) == 2
        print( "✓ EmbedBatchRequest works" )

        resp = EmbedResponse( embedding=[ 0.1, 0.2, 0.3 ], dimensions=3 )
        assert resp.dimensions == 3
        print( "✓ EmbedResponse works" )

        batch_resp = EmbedBatchResponse(
            embeddings=[ [ 0.1, 0.2 ], [ 0.3, 0.4 ] ],
            dimensions=2,
            count=2
        )
        assert batch_resp.count == 2
        print( "✓ EmbedBatchResponse works" )

        info_resp = EmbedInfoResponse(
            provider="local_nomic",
            dimensions=768,
            status="ready"
        )
        assert info_resp.provider == "local_nomic"
        print( "✓ EmbedInfoResponse works" )

        # Test 3: List endpoints
        print( "\nRegistered endpoints:" )
        for route in router.routes:
            print( f"  {route.methods} {route.path}" )

    except Exception as e:
        print( f"✗ Error: {e}" )
        import traceback
        traceback.print_exc()

    print( "\n✓ Embeddings router smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
