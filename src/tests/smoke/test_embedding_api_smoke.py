"""
Smoke test for the server's batch embedding endpoint.

Locks in the HTTP contract that the GCS integration tests depend on:
tests route embeddings through :8000's POST /api/embeddings/batch rather
than instantiating ProseEmbeddingEngine in-process (which would OOM the GPU).

See `src/rnd/v0.1.6/2026.04.22-tfe-model-flip-and-lancedb-cuda-oom-plan.md`
and feedback memory `feedback_tests_call_server_api_not_instantiate` for
the design rationale.

Requires:
    - Test server running at LUPIN_TEST_BASE_URL (default http://localhost:8000)
    - Test server in [Lupin: Testing] mode (companion users seeded)
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/PASSWORD env vars set

Ensures:
    - POST /api/embeddings/batch returns 200
    - Response has 'embeddings' (list of vectors), 'dimensions' (int), 'count' (int)
    - Each vector is 768 floats (nomic-embed-text-v1.5 dimensionality)
"""

import os
import pytest
import requests


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )


@pytest.fixture( scope="module" )
def auth_token():
    """Log in as the interactive test companion user and return the access token."""
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip(
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and "
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD must be set"
        )

    try:
        resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={ "email": email, "password": password },
            timeout=5,
        )
    except requests.exceptions.ConnectionError:
        pytest.skip( f"Test server not reachable at {BASE_URL}" )

    assert resp.status_code == 200, (
        f"Login failed: {resp.status_code} {resp.text}"
    )
    return resp.json()[ "tokens" ][ "access_token" ]


def test_batch_embedding_prose_returns_768_dim_vector( auth_token ):
    """Lock in the contract: single-text prose embedding is 768-dim."""
    resp = requests.post(
        f"{BASE_URL}/api/embeddings/batch",
        json={
            "texts"        : [ "How do I sort a list in Python?" ],
            "content_type" : "prose",
        },
        headers={ "Authorization": f"Bearer {auth_token}" },
        timeout=30,
    )
    assert resp.status_code == 200, (
        f"Batch embedding endpoint returned {resp.status_code}: {resp.text}"
    )

    body = resp.json()
    assert "embeddings" in body, f"Response missing 'embeddings': {body}"
    assert "dimensions" in body, f"Response missing 'dimensions': {body}"
    assert "count"      in body, f"Response missing 'count': {body}"

    assert body[ "count" ]      == 1,   f"Expected count=1, got {body[ 'count' ]}"
    assert body[ "dimensions" ] == 768, f"Expected 768-dim, got {body[ 'dimensions' ]}"

    vectors = body[ "embeddings" ]
    assert len( vectors )    == 1,   f"Expected 1 vector, got {len( vectors )}"
    assert len( vectors[0] ) == 768, f"Expected 768 floats, got {len( vectors[0] )}"
    assert all( isinstance( v, float ) for v in vectors[0][:10] ), \
        "Vector should contain floats"


def test_batch_embedding_multi_text_returns_matching_count( auth_token ):
    """Three input texts → three output vectors, all 768-dim."""
    texts = [
        "What is the factorial of 5?",
        "How do I sort a list?",
        "How do I use Python's f-strings?",
    ]
    resp = requests.post(
        f"{BASE_URL}/api/embeddings/batch",
        json={ "texts": texts, "content_type": "prose" },
        headers={ "Authorization": f"Bearer {auth_token}" },
        timeout=30,
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body[ "count" ] == len( texts )
    assert len( body[ "embeddings" ] ) == len( texts )
    for i, vec in enumerate( body[ "embeddings" ] ):
        assert len( vec ) == 768, f"Vector {i} has {len( vec )} dims, expected 768"


if __name__ == "__main__":
    pytest.main( [ __file__, "-v", "-s" ] )
