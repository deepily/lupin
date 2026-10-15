"""
Unit tests for the vector build: the text, engine and role of each call, and row order.

The client is a fake whose vectors depend on the text, the engine and the role. The provider and
the HTTP getter are fakes too, so nothing here loads a model or opens a socket.
"""
import hashlib

import numpy as np
import pytest

from cosa.repo.symindex.candidates import vector_build as vb
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError, EMBEDDING_SHAPE, ENGINE_NOT_LOADED

DIM = 4


def vec( content_type, role, text ):
    d = hashlib.sha256( f"{content_type}|{role}|{text}".encode() ).digest()
    return [ d[ i ] / 255.0 for i in range( DIM ) ]


def engines( revision="rev1" ):
    base = { "dtype": "float16", "device": "cuda:0", "dimensions": DIM, "loaded": True, "revision": revision }
    return {
        "code"         : { **base, "model": "code-m",  "query_prefix": "Q:", "document_prefix": "" },
        "prose"        : { **base, "model": "prose-m", "query_prefix": "search_query:", "document_prefix": "search_document:" },
        "device_class" : "RTX 4090, sm_89",
        "libraries"    : { "numpy": "2.4.4" }
    }


class FakeClient:
    def __init__( self, revision="rev1", short=False, ragged=False, wide_for=None ):
        self.revision = revision
        self.short    = short
        self.ragged   = ragged
        self.wide_for = wide_for
        self.calls    = []

    def embed( self, texts, content_type, role ):
        self.calls.append( ( content_type, role, list( texts ) ) )
        out = [ vec( content_type, role, t ) for t in texts ]
        if self.short and len( texts ) > 1: out = out[ :-1 ]
        if self.ragged and len( texts ) > 1: out[ -1 ] = out[ -1 ][ :-1 ]
        if self.wide_for == ( content_type, role ) and texts != [ vb.WARM_TEXT ]: out = [ v + [ 0.0 ] for v in out ]
        return out

    def info( self ):
        return { "engines": engines( self.revision ) }


def entry( name, pin, sig="()", doc="", body=None ):
    e = { "id": f"m.{name}", "file": "m.py", "name": name, "sig": sig, "doc": doc, "pin": pin }
    if body is not None: e[ "body" ] = body
    return e


def test_entry_texts_hold_name_path_signature_docstring_and_purpose_only():
    t = vb.entry_texts( entry( "f", "p", sig="(x, y)", doc="Does f.", body="SECRET_BODY_TOKEN" ), "Return f." )
    assert t[ "code" ]   == "m.py::f(x, y)"
    assert t[ "prose" ]  == "f. Return f. Does f."
    assert t[ "concat" ] == "m.py::f(x, y)\nf. Return f. Does f."
    assert all( "SECRET_BODY_TOKEN" not in v for v in t.values() )


def test_entry_texts_without_a_purpose_or_docstring_have_no_gaps():
    t = vb.entry_texts( entry( "f", "p" ), "" )
    assert t[ "prose" ] == "f."


def test_build_embeds_each_matrix_with_the_document_role_and_never_a_body( tmp_path ):
    client  = FakeClient()
    entries = [ entry( "b", "pb", doc="Does b.", body="SECRET_BODY_TOKEN" ), entry( "a", "pa", body="SECRET_BODY_TOKEN" ) ]
    purposes = { "pa": { "pin": "pa", "purpose": "Return a.", "prompt_hash": "ph", "writer_version": "w1" } }
    m = vb.build_vectors( entries, purposes, client, tmp_path / "n", pause_seconds=0, sleep=lambda s: None )

    pairs = [ ( c[ 0 ], c[ 1 ] ) for c in client.calls ]
    assert pairs == [ ( "code", "document" ), ( "prose", "document" ),                  # the warm-up
                      ( "prose", "document" ), ( "code", "document" ), ( "prose", "document" ) ]
    assert all( role == "document" for _, role in pairs )
    assert not any( "SECRET_BODY_TOKEN" in t for c in client.calls for t in c[ 2 ] )
    assert m[ "document_roles" ] == { "prose": [ "prose", "document" ], "code": [ "code", "document" ], "concat": [ "prose", "document" ] }
    assert m[ "query_roles" ][ "concat" ] == [ "prose", "query" ]
    assert m[ "purpose_writers" ] == [ { "prompt_hash": "ph", "writer_version": "w1" } ]
    assert m[ "rows" ] == 2 and m[ "dimension" ] == DIM


def test_rows_are_in_id_order_and_carry_the_right_text_and_engine( tmp_path ):
    entries  = [ entry( "b", "pb", doc="Does b." ), entry( "a", "pa" ) ]
    purposes = { "pa": { "pin": "pa", "purpose": "Return a.", "prompt_hash": "ph", "writer_version": "w1" } }
    m = vb.build_vectors( entries, purposes, FakeClient(), tmp_path / "n", pause_seconds=0, sleep=lambda s: None )
    s = vs.load_vectors( tmp_path / "n" )
    assert s.ids == [ "m.a", "m.b" ]
    f = lambda name: np.asarray( name, dtype="<f4" )
    assert np.array_equal( s.matrices[ "prose" ][ 0 ],  f( vec( "prose", "document", "a. Return a." ) ) )
    assert np.array_equal( s.matrices[ "prose" ][ 1 ],  f( vec( "prose", "document", "b. Does b." ) ) )
    assert np.array_equal( s.matrices[ "code" ][ 1 ],   f( vec( "code", "document", "m.py::b()" ) ) )
    assert np.array_equal( s.matrices[ "concat" ][ 0 ], f( vec( "prose", "document", "m.py::a()\na. Return a." ) ) )
    assert m[ "manifest_hash" ] == s.manifest_hash


def test_an_entry_with_no_stored_line_is_embedded_and_names_no_writer( tmp_path ):
    m = vb.build_vectors( [ entry( "a", "pa" ) ], {}, FakeClient(), tmp_path / "n", pause_seconds=0, sleep=lambda s: None )
    assert m[ "purpose_writers" ] == []


def test_duplicate_ids_are_embedded_once( tmp_path ):
    m = vb.build_vectors( [ entry( "a", "p1" ), entry( "a", "p2" ) ], {}, FakeClient(), tmp_path / "n", pause_seconds=0, sleep=lambda s: None )
    assert m[ "rows" ] == 1


def test_batches_are_one_at_a_time_with_a_pause_between_them( tmp_path ):
    client = FakeClient()
    sleeps = []
    vb.build_vectors( [ entry( f"f{i}", f"p{i}" ) for i in range( 5 ) ], {}, client, tmp_path / "n",
                      batch_size=2, pause_seconds=0.25, sleep=sleeps.append )
    sizes = [ len( c[ 2 ] ) for c in client.calls[ 2: ] ]          # past the two warm-up calls
    assert sizes == [ 2, 2, 1 ] * 3
    assert sleeps == [ 0.25, 0.25 ] * 3                              # between batches, never after the last


@pytest.mark.parametrize( "client_kwargs, detail", [
    ( { "short": True },                              "asked for" ),
    ( { "ragged": True },                             "differ in length" ),
    ( { "wide_for": ( "code", "document" ) },         "columns" )
] )
def test_a_wrong_count_a_ragged_row_or_a_wrong_width_is_an_embedding_shape_error( tmp_path, client_kwargs, detail ):
    with pytest.raises( CandidateError ) as e:
        vb.build_vectors( [ entry( "a", "pa" ), entry( "b", "pb" ) ], {}, FakeClient( **client_kwargs ), tmp_path / "n",
                          pause_seconds=0, sleep=lambda s: None )
    assert e.value.code == EMBEDDING_SHAPE
    assert detail in e.value.detail


def test_a_null_revision_after_the_warm_up_stops_the_build_before_any_file( tmp_path ):
    client = FakeClient( revision=None )
    with pytest.raises( CandidateError ) as e:
        vb.build_vectors( [ entry( "a", "pa" ) ], {}, client, tmp_path / "n", pause_seconds=0, sleep=lambda s: None )
    assert e.value.code == ENGINE_NOT_LOADED
    assert len( client.calls ) == 2                                    # the warm-up only
    assert not ( tmp_path / "n" ).exists()


# ── the endpoint client ─────────────────────────────────────────────────────


class FakeProvider:
    def __init__( self ): self.calls = []

    def generate_embeddings_batch( self, texts, content_type="prose", role=None, pin_fastapi=False ):
        self.calls.append( ( list( texts ), content_type, role, pin_fastapi ) )
        return [ [ 1.0 ] for _ in texts ]


def test_embed_always_pins_the_fastapi_router_and_passes_the_role():
    p = FakeProvider()
    out = vb.EndpointClient( provider=p ).embed( [ "a", "b" ], "code", "document" )
    assert out == [ [ 1.0 ], [ 1.0 ] ]
    assert p.calls == [ ( [ "a", "b" ], "code", "document", True ) ]


def test_embed_takes_the_process_provider_when_none_is_given( monkeypatch ):
    p = FakeProvider()
    import cosa.memory.embedding_provider as ep
    monkeypatch.setattr( ep, "get_embedding_provider", lambda: p )
    vb.EndpointClient().embed( [ "a" ], "prose", "query" )
    assert p.calls == [ ( [ "a" ], "prose", "query", True ) ]


class FakeResponse:
    def __init__( self, status=200, body=None ):
        self.status_code = status
        self.text        = "boom"
        self._body       = body if body is not None else {}

    def json( self ): return self._body


@pytest.fixture
def target( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider
    seen = {}

    def resolve( pin_fastapi=False ):
        seen[ "pinned" ] = pin_fastapi
        return ( "http://fastapi:7999", "k3y", "/api/embeddings" )

    monkeypatch.setattr( EmbeddingProvider, "_resolve_http_target", staticmethod( resolve ) )
    return seen


def test_info_reads_the_fastapi_info_route_with_the_key_header( target ):
    got = {}

    def get( url, headers, timeout ):
        got.update( url=url, headers=headers )
        return FakeResponse( 200, { "engines": { "code": {} } } )

    assert vb.EndpointClient( get=get ).info() == { "engines": { "code": {} } }
    assert got == { "url": "http://fastapi:7999/api/embeddings/info", "headers": { "X-API-Key": "k3y" } }
    assert target[ "pinned" ] is True


def test_info_with_no_key_is_a_runtime_error( monkeypatch ):
    from cosa.memory.embedding_provider import EmbeddingProvider
    monkeypatch.setattr( EmbeddingProvider, "_resolve_http_target", staticmethod( lambda pin: ( "http://x", None, "/api/embeddings" ) ) )
    with pytest.raises( RuntimeError, match="no API key" ):
        vb.EndpointClient( get=lambda *a, **k: FakeResponse() ).info()


def test_info_that_answers_non_200_is_a_runtime_error( target ):
    with pytest.raises( RuntimeError, match="answered 503" ):
        vb.EndpointClient( get=lambda *a, **k: FakeResponse( 503 ) ).info()


def test_info_uses_requests_get_by_default( target, monkeypatch ):
    import requests
    seen = {}

    def fake_get( url, headers, timeout ):
        seen[ "url" ] = url
        return FakeResponse( 200, { "engines": {} } )

    monkeypatch.setattr( requests, "get", fake_get )
    assert vb.EndpointClient().info() == { "engines": {} }
    assert seen[ "url" ].endswith( "/api/embeddings/info" )
