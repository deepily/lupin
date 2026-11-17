"""
Tests for the provider info read, and the census of embeddings routes in service files.

Within the code-health services only embedding_provider.py reaches those routes. The getter and
the target are fakes, so nothing here loads a model, opens a socket or touches a GPU.
"""
import subprocess

import pytest

from cosa.memory.embedding_provider import EmbeddingProvider

SERVICE_DIRS = ( "src/cosa/repo/symindex/", "src/cosa/repo/duplicate_check/", "src/lupin_mcp/" )
ROUTE_PATTERNS = ( "api/embeddings", "embeddings/generate", "embeddings/info" )


class Response:
    def __init__( self, status=200, body=None ):
        self.status_code = status
        self.text        = "boom"
        self._body       = body if body is not None else {}

    def json( self ): return self._body


@pytest.fixture
def target( monkeypatch ):
    seen = {}

    def resolve( pin_fastapi=False ):
        seen[ "pinned" ] = pin_fastapi
        return ( "http://fastapi:7999", "k3y", "/api/embeddings" )

    monkeypatch.setattr( EmbeddingProvider, "_resolve_http_target", staticmethod( resolve ) )
    return seen


def test_read_info_gets_the_info_route_with_the_key_and_pin( target ):
    got = {}

    def get( url, headers, timeout ):
        got.update( url=url, headers=headers, timeout=timeout )
        return Response( 200, { "engines": {} } )

    assert EmbeddingProvider.read_info( get=get ) == { "engines": {} }
    assert got == { "url": "http://fastapi:7999/api/embeddings/info", "headers": { "X-API-Key": "k3y" }, "timeout": 30 }
    assert target[ "pinned" ] is True


def test_read_info_passes_an_unpinned_request_through( target ):
    EmbeddingProvider.read_info( pin_fastapi=False, get=lambda *a, **k: Response() )
    assert target[ "pinned" ] is False


def test_read_info_with_no_key_is_a_runtime_error( monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_resolve_http_target", staticmethod( lambda pin: ( "http://x", None, "/api/embeddings" ) ) )
    with pytest.raises( RuntimeError, match="no API key" ):
        EmbeddingProvider.read_info( get=lambda *a, **k: Response() )


def test_read_info_that_answers_non_200_is_a_runtime_error( target ):
    with pytest.raises( RuntimeError, match="answered 503" ):
        EmbeddingProvider.read_info( get=lambda *a, **k: Response( 503 ) )


def test_read_info_uses_requests_get_by_default( target, monkeypatch ):
    import requests
    monkeypatch.setattr( requests, "get", lambda url, headers, timeout: Response( 200, { "engines": { "x": 1 } } ) )
    assert EmbeddingProvider.read_info() == { "engines": { "x": 1 } }


@pytest.mark.parametrize( "pattern", ROUTE_PATTERNS )
def test_every_code_health_service_file_but_the_provider_keeps_off_the_embeddings_routes( pattern ):
    """Tracked files under the service directories hold no route string."""
    files = subprocess.run( [ "git", "ls-files", *SERVICE_DIRS ], capture_output=True, text=True, check=True ).stdout.split()
    assert len( files ) > 20    # the walk found the population
    hits  = subprocess.run( [ "git", "grep", "-l", "-F", pattern, "--", *SERVICE_DIRS ], capture_output=True, text=True ).stdout.split()
    assert hits == []


def test_the_route_census_can_find_a_hit():
    """Positive control: the same search over the provider's own file finds the route."""
    hits = subprocess.run( [ "git", "grep", "-l", "-F", "api/embeddings", "--", "src/cosa/memory/embedding_provider.py" ], capture_output=True, text=True ).stdout.split()
    assert hits == [ "src/cosa/memory/embedding_provider.py" ]
