"""
Unit tests for the embeddings `role` field and the `engines` block of `info`.

Covers:
    - `EmbeddingProvider._encode_local`, `_check_role`, `describe_engines`
    - the HTTP helpers' payload and target
    - `CodeEmbeddingEngine.describe`, `ProseEmbeddingEngine.describe`, `device_class`
    - the three routes of `cosa.rest.routers.embeddings`

Every engine, key and server here is a fake. Nothing loads a model.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.memory.embedding_provider as ep
import cosa.memory.local_embedding_engine as lee
from cosa.memory.embedding_provider import EmbeddingProvider, EmbeddingRoleUnsupported
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import embeddings as router_module


class FakeEngine:
    """Records which encoder was called, and with which texts."""

    def __init__( self, name ):
        self.name  = name
        self.calls = []

    def _record( self, method, texts ):
        self.calls.append( ( method, list( texts ) ) )
        return [ [ 1.0, 0.0 ] for _ in texts ]

    def encode_query( self, texts ):    return self._record( "encode_query", texts )
    def encode_document( self, texts ): return self._record( "encode_document", texts )
    def encode_code( self, texts ):     return self._record( "encode_code", texts )

    def describe( self ):
        return {
            "model" : self.name, "revision" : "abc123", "dtype" : "float16", "device" : "cuda:0",
            "query_prefix" : "q:", "document_prefix" : "d:", "dimensions" : 768, "loaded" : True
        }


def make_provider( provider="local", code=None, prose=None ):
    """Build a provider without running __init__, so no ConfigurationManager is needed."""
    p                = object.__new__( EmbeddingProvider )
    p.debug          = False
    p.verbose        = False
    p._provider      = provider
    p._config_mgr    = MagicMock()
    p._openai_engine = MagicMock()
    p._code_engine   = code  if code  is not None else FakeEngine( "code-model" )
    p._prose_engine  = prose if prose is not None else FakeEngine( "prose-model" )
    p._metrics       = {}
    p._metrics_lock  = ep.Lock()
    return p


@pytest.fixture
def owner( monkeypatch ):
    """An in-process engine owner, restored after the test."""
    monkeypatch.setattr( EmbeddingProvider, "_is_in_process_engine_owner", True )


# ── in-process encoder choice ───────────────────────────────────────────────


@pytest.mark.parametrize( "content_type, role, engine_attr, method", [
    ( "code",  None,       "_code_engine",  "encode_code" ),
    ( "code",  "query",    "_code_engine",  "encode_query" ),
    ( "code",  "document", "_code_engine",  "encode_code" ),
    ( "prose", None,       "_prose_engine", "encode_query" ),
    ( "prose", "query",    "_prose_engine", "encode_query" ),
    ( "prose", "document", "_prose_engine", "encode_document" ),
] )
def test_in_process_role_picks_the_encoder( owner, content_type, role, engine_attr, method ):
    p      = make_provider()
    other  = "_prose_engine" if engine_attr == "_code_engine" else "_code_engine"

    single = p.generate_embedding( "hello", content_type=content_type, role=role )
    batch  = p.generate_embeddings_batch( [ "a", "b" ], content_type=content_type, role=role )

    assert single == [ 1.0, 0.0 ]
    assert len( batch ) == 2
    assert getattr( p, engine_attr ).calls == [ ( method, [ "hello" ] ), ( method, [ "a", "b" ] ) ]
    assert getattr( p, other ).calls == []


def test_in_process_unknown_role_is_refused( owner ):
    p = make_provider()
    with pytest.raises( ValueError, match="role must be one of" ):
        p.generate_embedding( "x", content_type="code", role="both" )
    with pytest.raises( ValueError, match="role must be one of" ):
        p.generate_embeddings_batch( [ "x" ], content_type="code", role="both" )


def test_openai_provider_refuses_a_role():
    p = make_provider( provider="openai" )
    with pytest.raises( EmbeddingRoleUnsupported, match="ROLE_UNSUPPORTED_ON_OPENAI" ):
        p.generate_embedding( "x", role="query" )
    with pytest.raises( EmbeddingRoleUnsupported, match="ROLE_UNSUPPORTED_ON_OPENAI" ):
        p.generate_embeddings_batch( [ "x" ], role="document" )


def test_openai_provider_without_a_role_is_unchanged():
    p = make_provider( provider="openai" )
    p._openai_engine.generate_embedding.return_value = [ 0.5 ]
    assert p.generate_embedding( "x" ) == [ 0.5 ]
    assert p.generate_embeddings_batch( [ "x", "y" ] ) == [ [ 0.5 ], [ 0.5 ] ]


# ── HTTP payload and target ─────────────────────────────────────────────────


class FakeResponse:
    status_code = 200
    text        = ""

    def __init__( self, body ): self._body = body
    def json( self ):           return self._body


@pytest.fixture
def http( monkeypatch ):
    """Capture what the HTTP helpers post, with the FastAPI server as the default target."""
    seen = {}

    def fake_post( self, url, payload, api_key, timeout, label ):
        seen[ "url" ]     = url
        seen[ "payload" ] = payload
        seen[ "key" ]     = api_key
        return FakeResponse( { "embedding" : [ 0.1 ], "embeddings" : [ [ 0.1 ] ] } )

    monkeypatch.setattr( EmbeddingProvider, "_post_with_retry", fake_post )
    monkeypatch.setattr( EmbeddingProvider, "_http_api_key", staticmethod( lambda: "model-server-key" ) )
    monkeypatch.setattr( EmbeddingProvider, "_fastapi_api_key", staticmethod( lambda: "fastapi-key" ) )
    monkeypatch.setattr( EmbeddingProvider, "_resolve_server_url", staticmethod( lambda: "http://fastapi:7999" ) )
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: None ) )
    monkeypatch.setattr( EmbeddingProvider, "_is_in_process_engine_owner", False )
    return seen


def test_http_payload_has_no_role_key_when_role_is_none( http ):
    p = make_provider()
    p.generate_embedding( "x", content_type="code" )
    assert http[ "payload" ] == { "text" : "x", "content_type" : "code" }
    p.generate_embeddings_batch( [ "x" ], content_type="code" )
    assert http[ "payload" ] == { "texts" : [ "x" ], "content_type" : "code" }


def test_http_payload_carries_the_role( http ):
    p = make_provider()
    p.generate_embedding( "x", content_type="prose", role="document" )
    assert http[ "payload" ] == { "text" : "x", "content_type" : "prose", "role" : "document" }
    assert http[ "url" ] == "http://fastapi:7999/api/embeddings/generate"
    p.generate_embeddings_batch( [ "x" ], content_type="prose", role="query" )
    assert http[ "payload" ] == { "texts" : [ "x" ], "content_type" : "prose", "role" : "query" }
    assert http[ "url" ] == "http://fastapi:7999/api/embeddings/batch"


def test_role_against_a_model_server_that_echoes_it_is_accepted( http, monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: "http://lupin-model-server:7998" ) )
    answers = iter( [ { "embedding" : [ 0.5 ], "role" : "query" }, { "embeddings" : [ [ 0.5 ] ], "role" : "document" } ] )
    monkeypatch.setattr( EmbeddingProvider, "_post_with_retry", lambda self, url, payload, key, timeout, label: FakeResponse( next( answers ) ) )
    p = make_provider()
    assert p.generate_embedding( "x", content_type="code", role="query" ) == [ 0.5 ]
    assert p.generate_embeddings_batch( [ "x" ], content_type="code", role="document" ) == [ [ 0.5 ] ]


def test_role_against_a_model_server_that_did_not_apply_it_is_refused_by_name( http, monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: "http://lupin-model-server:7998" ) )
    p = make_provider()                  # the fixture's fake answer has no role key, as a frozen server's would not
    with pytest.raises( EmbeddingRoleUnsupported, match="ROLE_UNSUPPORTED_ON_MODEL_SERVER.*named None" ):
        p.generate_embedding( "x", content_type="code", role="query" )
    with pytest.raises( EmbeddingRoleUnsupported, match="did not apply role 'document'" ):
        p.generate_embeddings_batch( [ "x" ], content_type="code", role="document" )


def test_a_model_server_that_answers_a_different_role_is_refused( http, monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: "http://lupin-model-server:7998" ) )
    monkeypatch.setattr( EmbeddingProvider, "_post_with_retry",
                         lambda self, url, payload, key, timeout, label: FakeResponse( { "embedding" : [ 0.1 ], "role" : "query" } ) )
    with pytest.raises( EmbeddingRoleUnsupported, match="named 'query'" ):
        make_provider().generate_embedding( "x", content_type="code", role="document" )


def test_the_fastapi_router_answer_needs_no_role_echo( http ):
    p = make_provider()                  # FastAPI target; the fake answer has no role key
    assert p.generate_embedding( "x", content_type="code", role="query" ) == [ 0.1 ]


def test_no_role_against_the_model_server_is_unchanged( http, monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: "http://lupin-model-server:7998" ) )
    p = make_provider()
    p.generate_embedding( "x", content_type="code" )
    assert http[ "url" ] == "http://lupin-model-server:7998/embeddings/generate"


def test_pin_fastapi_beats_a_model_server_url( http, monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: "http://lupin-model-server:7998" ) )
    p = make_provider()
    p.generate_embedding( "x", content_type="code", role="query", pin_fastapi=True )
    assert http[ "url" ] == "http://fastapi:7999/api/embeddings/generate"
    assert http[ "payload" ][ "role" ] == "query"
    assert http[ "key" ] == "fastapi-key"
    p.generate_embeddings_batch( [ "x" ], content_type="code", role="document", pin_fastapi=True )
    assert http[ "url" ] == "http://fastapi:7999/api/embeddings/batch"


def test_resolve_http_target_pin_skips_the_model_server_lookup( monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: "http://ms:1" ) )
    monkeypatch.setattr( EmbeddingProvider, "_resolve_server_url", staticmethod( lambda: "http://fa:2" ) )
    monkeypatch.setattr( EmbeddingProvider, "_http_api_key", staticmethod( lambda: "k" ) )
    monkeypatch.setattr( EmbeddingProvider, "_fastapi_api_key", staticmethod( lambda: "fk" ) )
    assert EmbeddingProvider._resolve_http_target() == ( "http://ms:1", "k", "/embeddings" )
    assert EmbeddingProvider._resolve_http_target( pin_fastapi=True ) == ( "http://fa:2", "fk", "/api/embeddings" )


def test_an_unpinned_call_with_no_model_server_keeps_the_model_server_key( monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: None ) )
    monkeypatch.setattr( EmbeddingProvider, "_resolve_server_url", staticmethod( lambda: "http://fa:2" ) )
    monkeypatch.setattr( EmbeddingProvider, "_http_api_key", staticmethod( lambda: "k" ) )
    monkeypatch.setattr( EmbeddingProvider, "_fastapi_api_key", staticmethod( lambda: "fk" ) )
    assert EmbeddingProvider._resolve_http_target() == ( "http://fa:2", "k", "/api/embeddings" )


def test_fastapi_api_key_reads_the_default_name_or_the_override( monkeypatch ):
    names = []
    monkeypatch.setattr( ep.du, "get_api_key", lambda name: names.append( name ) or f"key-of-{name}" )
    monkeypatch.delenv( "LUPIN_FASTAPI_API_KEY_NAME", raising=False )
    assert EmbeddingProvider._fastapi_api_key() == "key-of-notification-api-claude-code-dev"
    monkeypatch.setenv( "LUPIN_FASTAPI_API_KEY_NAME", "other-key" )
    assert EmbeddingProvider._fastapi_api_key() == "key-of-other-key"
    assert names == [ "notification-api-claude-code-dev", "other-key" ]


def test_fastapi_api_key_is_none_when_the_lookup_raises( monkeypatch ):
    def boom( name ): raise OSError( "unreadable" )

    monkeypatch.setattr( ep.du, "get_api_key", boom )
    assert EmbeddingProvider._fastapi_api_key() is None


# ── describe_engines and the engines' describe ──────────────────────────────


def test_describe_engines_reports_both_engines_device_class_and_libraries( monkeypatch ):
    monkeypatch.setattr( lee, "device_class", lambda device: f"card for {device}" )
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: None ) )
    import importlib.metadata as md
    versions = { "torch" : "2.1.0", "transformers" : "4.40.0", "numpy" : "2.4.4" }

    def fake_version( name ):
        if name in versions: return versions[ name ]
        raise md.PackageNotFoundError( name )

    monkeypatch.setattr( md, "version", fake_version )

    report = make_provider().describe_engines()

    assert report[ "code" ][ "model" ] == "code-model"
    assert report[ "prose" ][ "model" ] == "prose-model"
    assert report[ "device_class" ] == "card for cuda:0"
    assert report[ "libraries" ] == {
        "torch" : "2.1.0", "transformers" : "4.40.0", "sentence-transformers" : None, "numpy" : "2.4.4"
    }


def make_code_engine( model=None ):
    e                = object.__new__( lee.CodeEmbeddingEngine )
    e._model_name    = "nomic-ai/CodeRankEmbed"
    e._device        = "cuda:0"
    e._dtype_str     = "float16"
    e._query_prefix  = "Represent this query:"
    e._dimensions    = 768
    e._model         = model
    return e


def make_prose_engine( model=None ):
    e                  = object.__new__( lee.ProseEmbeddingEngine )
    e._model_name      = "nomic-ai/nomic-embed-text-v1.5"
    e._device          = "cuda:0"
    e._dtype_str       = "float16"
    e._query_prefix    = "search_query:"
    e._document_prefix = "search_document:"
    e._matryoshka_dim  = 512
    e._model           = model
    return e


def test_code_engine_describe_before_load_has_no_revision():
    d = make_code_engine().describe()
    assert d == {
        "model" : "nomic-ai/CodeRankEmbed", "revision" : None, "dtype" : "float16", "device" : "cuda:0",
        "query_prefix" : "Represent this query:", "document_prefix" : "", "dimensions" : 768, "loaded" : False
    }


def test_code_engine_describe_after_load_reads_the_commit_hash():
    inner = MagicMock()
    inner.auto_model.config._commit_hash = "deadbeef"
    model = MagicMock()
    model.__getitem__.return_value = inner
    d = make_code_engine( model ).describe()
    assert d[ "revision" ] == "deadbeef"
    assert d[ "loaded" ] is True
    model.__getitem__.assert_called_once_with( 0 )


def test_prose_engine_describe_before_load_has_no_revision():
    d = make_prose_engine().describe()
    assert d == {
        "model" : "nomic-ai/nomic-embed-text-v1.5", "revision" : None, "dtype" : "float16", "device" : "cuda:0",
        "query_prefix" : "search_query:", "document_prefix" : "search_document:", "dimensions" : 512, "loaded" : False
    }


def test_prose_engine_describe_after_load_reads_the_commit_hash():
    model = MagicMock()
    model.config._commit_hash = "cafe0001"
    d = make_prose_engine( model ).describe()
    assert d[ "revision" ] == "cafe0001"
    assert d[ "loaded" ] is True


def test_device_class_returns_the_string_for_cpu():
    assert lee.device_class( "cpu" ) == "cpu"


def test_device_class_returns_the_string_when_cuda_is_absent( monkeypatch ):
    monkeypatch.setattr( lee.torch.cuda, "is_available", lambda: False )
    assert lee.device_class( "cuda:0" ) == "cuda:0"


def test_device_class_names_the_card_and_capability( monkeypatch ):
    monkeypatch.setattr( lee.torch.cuda, "is_available", lambda: True )
    monkeypatch.setattr( lee.torch.cuda, "get_device_name", lambda device: "RTX 4090" )
    monkeypatch.setattr( lee.torch.cuda, "get_device_capability", lambda device: ( 8, 9 ) )
    assert lee.device_class( "cuda:0" ) == "RTX 4090, sm_89"


# ── the routes ──────────────────────────────────────────────────────────────


class RouteProvider:
    """Stands in for the provider behind the router and records the call it gets."""
    provider   = "local"
    dimensions = 2

    def __init__( self ): self.calls = []

    def generate_embedding( self, text, content_type="prose", role=None ):
        self.calls.append( ( "generate", text, content_type, role ) )
        return [ 0.1, 0.2 ]

    def generate_embeddings_batch( self, texts, content_type="prose", role=None ):
        self.calls.append( ( "batch", list( texts ), content_type, role ) )
        return [ [ 0.1, 0.2 ] for _ in texts ]

    def describe_engines( self ):
        return { "code" : { "model" : "c", "revision" : "r1" }, "prose" : { "model" : "p", "revision" : None }, "device_class" : "cpu", "libraries" : {} }


@pytest.fixture
def client( monkeypatch ):
    provider = RouteProvider()
    monkeypatch.setattr( router_module, "get_embedding_provider", lambda: provider )
    app = FastAPI()
    app.include_router( router_module.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app ), provider


@pytest.mark.parametrize( "role", [ None, "query", "document" ] )
def test_generate_passes_the_role_through( client, role ):
    c, provider = client
    body = { "text" : "hi", "content_type" : "code" }
    if role is not None: body[ "role" ] = role
    r = c.post( "/api/embeddings/generate", json=body )
    assert r.status_code == 200
    assert r.json() == { "embedding" : [ 0.1, 0.2 ], "dimensions" : 2 }
    assert provider.calls == [ ( "generate", "hi", "code", role ) ]


@pytest.mark.parametrize( "role", [ None, "query", "document" ] )
def test_batch_passes_the_role_through( client, role ):
    c, provider = client
    body = { "texts" : [ "a", "b" ], "content_type" : "prose" }
    if role is not None: body[ "role" ] = role
    r = c.post( "/api/embeddings/batch", json=body )
    assert r.status_code == 200
    assert r.json()[ "count" ] == 2
    assert provider.calls == [ ( "batch", [ "a", "b" ], "prose", role ) ]


def test_unknown_role_answers_422_and_reaches_nothing( client ):
    c, provider = client
    assert c.post( "/api/embeddings/generate", json={ "text" : "hi", "role" : "both" } ).status_code == 422
    assert c.post( "/api/embeddings/batch", json={ "texts" : [ "hi" ], "role" : "both" } ).status_code == 422
    assert provider.calls == []


def test_empty_batch_is_still_a_400( client ):
    c, _ = client
    assert c.post( "/api/embeddings/batch", json={ "texts" : [] } ).status_code == 400


def test_unsupported_role_from_the_provider_answers_422( client ):
    c, provider = client

    def refuse( *args, **kwargs ): raise EmbeddingRoleUnsupported( "ROLE_UNSUPPORTED_ON_OPENAI: no" )

    provider.generate_embedding        = refuse
    provider.generate_embeddings_batch = refuse
    r1 = c.post( "/api/embeddings/generate", json={ "text" : "hi", "role" : "query" } )
    r2 = c.post( "/api/embeddings/batch", json={ "texts" : [ "hi" ], "role" : "query" } )
    assert r1.status_code == 422 and "ROLE_UNSUPPORTED_ON_OPENAI" in r1.json()[ "detail" ]
    assert r2.status_code == 422 and "ROLE_UNSUPPORTED_ON_OPENAI" in r2.json()[ "detail" ]


def test_info_carries_the_engines_block( client ):
    c, _ = client
    r = c.get( "/api/embeddings/info" )
    assert r.status_code == 200
    body = r.json()
    assert body[ "provider" ] == "local"
    assert body[ "engines" ][ "code" ] == { "model" : "c", "revision" : "r1" }
    assert body[ "engines" ][ "prose" ][ "revision" ] is None


# ── describe_engines in a process that does not own the engines ─────────────


def _model_server_target( monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_is_in_process_engine_owner", False )
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: "http://lupin-model-server:7998" ) )
    monkeypatch.setattr( EmbeddingProvider, "_http_api_key", staticmethod( lambda: "ms-key" ) )


def test_describe_engines_asks_the_model_server_when_this_process_does_not_own_the_engines( monkeypatch ):
    import requests
    _model_server_target( monkeypatch )
    seen = {}

    class Answer:
        status_code = 200
        text        = ""
        def json( self ): return { "engines" : { "code" : { "revision" : "r1" }, "prose" : { "revision" : "r2" }, "device_class" : "card", "libraries" : {} } }

    def fake_get( url, headers, timeout ):
        seen.update( url=url, headers=headers, timeout=timeout )
        return Answer()

    monkeypatch.setattr( requests, "get", fake_get )
    p = make_provider( code=MagicMock( describe=MagicMock( side_effect=AssertionError( "local engine read" ) ) ) )
    p._config_mgr.get.return_value = "45"
    engines = p.describe_engines()
    assert engines[ "code" ][ "revision" ] == "r1" and engines[ "device_class" ] == "card"
    assert seen == { "url" : "http://lupin-model-server:7998/embeddings/info", "headers" : { "X-API-Key" : "ms-key" }, "timeout" : 45.0 }


def test_describe_engines_via_http_refuses_by_name( monkeypatch ):
    import requests
    _model_server_target( monkeypatch )
    p = make_provider()
    p._config_mgr.get.return_value = "90"

    class Answer:
        def __init__( self, status, body ): self.status_code, self._b, self.text = status, body, "boom"
        def json( self ): return self._b

    monkeypatch.setattr( requests, "get", lambda url, headers, timeout: Answer( 503, {} ) )
    with pytest.raises( RuntimeError, match="returned 503 from http://lupin-model-server:7998/embeddings/info" ):
        p.describe_engines()
    monkeypatch.setattr( requests, "get", lambda url, headers, timeout: Answer( 200, { "code_model" : "x" } ) )
    with pytest.raises( RuntimeError, match="reports no engines block; it predates role support" ):
        p.describe_engines()
    monkeypatch.setattr( EmbeddingProvider, "_http_api_key", staticmethod( lambda: None ) )
    with pytest.raises( RuntimeError, match="no API key found for lupin-model-server" ):
        p.describe_engines()


def test_describe_engines_reads_the_local_engines_when_no_model_server_resolves( monkeypatch ):
    monkeypatch.setattr( EmbeddingProvider, "_is_in_process_engine_owner", False )
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: None ) )
    monkeypatch.setattr( lee, "device_class", lambda d: "local-card" )
    assert make_provider().describe_engines()[ "device_class" ] == "local-card"


def test_describe_engines_reads_its_own_engines_when_this_process_owns_them_even_with_a_model_server_url( monkeypatch ):
    import requests
    monkeypatch.setattr( EmbeddingProvider, "_is_in_process_engine_owner", True )
    monkeypatch.setattr( EmbeddingProvider, "_resolve_model_server_url", staticmethod( lambda: "http://lupin-model-server:7998" ) )
    monkeypatch.setattr( requests, "get", lambda *a, **k: pytest.fail( "an engine owner must not ask the model server" ) )
    monkeypatch.setattr( lee, "device_class", lambda d: "own-card" )
    assert make_provider().describe_engines()[ "device_class" ] == "own-card"
