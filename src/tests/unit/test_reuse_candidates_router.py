"""
The candidate search router: upload a stage once, search by key, failures with statuses.

The router is mounted on a small app with the auth dependency replaced.
The resident search holds hand-made vectors, so each answer is one the search-process tests work out by hand.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.repo.symindex.candidates import errors as ce
from cosa.repo.symindex.candidates.errors import CandidateError
from cosa.repo.symindex.candidates.resident import ResidentSearch
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import reuse_candidates as rc
from tests.unit.test_candidates_resident import ENTRIES, Loader, QUERY


def app_with( override_auth=True ):
    app = FastAPI()
    app.include_router( rc.router )
    if override_auth: app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return app


@pytest.fixture
def client( tmp_path, monkeypatch ):
    ( tmp_path / "vectors" ).mkdir()
    ( tmp_path / "vectors" / "manifest.json" ).write_text( "{}", encoding="utf-8" )
    monkeypatch.setitem( rc._held, "search", ResidentSearch( tmp_path, Loader() ) )
    return TestClient( app_with() ), tmp_path


def upload( c, key="k1", **more ): return c.put( "/api/reuse-candidates/stage", json=dict( { "key": key, "entries": ENTRIES }, **more ) )


def test_an_upload_is_held_and_a_search_by_its_key_answers_with_the_shortlist( client ):
    c, root = client
    r = upload( c )
    assert ( r.status_code, r.json() ) == ( 200, { "key": "k1", "entries": 3 } )
    r = c.post( "/api/reuse-candidates/search", json={ "stage_key": "k1", "need": "profile", "K": 3, "vectors_dir": str( root / "vectors" ), "query_vectors": QUERY } )
    body = r.json()
    assert r.status_code == 200 and body[ "shortlist" ] == sorted( body[ "shortlist" ] ) and body[ "manifest_hash" ] == "hash-1" and body[ "K" ] == 3


def test_the_purpose_lines_and_the_fusion_constants_travel_with_the_upload( client ):
    c, _ = client
    r = upload( c, purposes={ "pb": "load settings from a file" }, fusion={ "k": 60, "depth": 100, "head": 2 } )
    assert r.status_code == 200
    body = c.post( "/api/reuse-candidates/search", json={ "stage_key": "k1", "need": "settings from a file", "K": 3 } ).json()
    assert body[ "ranking" ][ 0 ] == "py:b" and body[ "bm25" ][ "fusion" ] == { "k": 60, "depth": 100, "head": 2 }


@pytest.mark.parametrize( "more, status, error", [
    ( { "entries": [] }, 422, ce.BAD_STAGE_UPLOAD ),
    ( { "fusion": { "k": 1 } }, 422, ce.BAD_STAGE_UPLOAD ),
] )
def test_a_bad_upload_answers_422_with_its_named_error( client, more, status, error ):
    c, _ = client
    r = c.put( "/api/reuse-candidates/stage", json=dict( { "key": "k", "entries": ENTRIES }, **more ) )
    assert ( r.status_code, r.json()[ "error" ] ) == ( status, error )


def test_each_named_failure_answers_its_own_status( client ):
    c, root = client
    upload( c )
    base = { "stage_key": "k1", "need": "profile", "K": 3, "vectors_dir": str( root / "vectors" ), "query_vectors": QUERY }
    cases = [ ( dict( base, stage_key="zz" ), 409, ce.STAGE_UNKNOWN ),
              ( dict( base, expect_manifest_hash="other" ), 409, ce.VECTOR_SET_REPLACED ),
              ( dict( base, vectors_dir=str( root.parent ) ), 403, ce.PATH_REFUSED ),
              ( dict( base, K=0 ), 422, "BAD_SEARCH_REQUEST" ) ]
    for body, status, error in cases:
        r = c.post( "/api/reuse-candidates/search", json=body )
        assert ( r.status_code, r.json()[ "error" ] ) == ( status, error ), body
        assert r.json()[ "detail" ]


def test_a_service_side_failure_answers_503( client, monkeypatch ):
    c, root = client
    upload( c )
    def broken( self, request ): raise CandidateError( ce.VECTOR_SET_CORRUPT, "a hash does not match" )
    monkeypatch.setattr( ResidentSearch, "search", broken )
    r = c.post( "/api/reuse-candidates/search", json={ "stage_key": "k1", "need": "x", "K": 1 } )
    assert ( r.status_code, r.json() ) == ( 503, { "error": ce.VECTOR_SET_CORRUPT, "detail": "a hash does not match" } )


def test_no_credentials_means_no_search( tmp_path, monkeypatch ):
    monkeypatch.setitem( rc._held, "search", ResidentSearch( tmp_path, Loader() ) )
    c = TestClient( app_with( override_auth=False ) )
    assert c.put( "/api/reuse-candidates/stage", json={ "key": "k", "entries": ENTRIES } ).status_code in ( 401, 403 )
    assert c.post( "/api/reuse-candidates/search", json={ "stage_key": "k", "need": "x", "K": 1 } ).status_code in ( 401, 403 )


def test_the_resident_search_is_made_once_under_the_servers_data_directory( tmp_path, monkeypatch ):
    monkeypatch.setitem( rc._held, "search", None )
    monkeypatch.setattr( rc, "data_root", lambda: str( tmp_path ) )
    first = rc.resident()
    assert isinstance( first, ResidentSearch ) and rc.resident() is first


def test_data_root_is_the_reuse_review_directory_of_this_repository( monkeypatch ):
    import cosa.repo.symindex.paths as paths
    import cosa.utils.util as du
    monkeypatch.setattr( du, "get_project_root", lambda: "/repo" )
    monkeypatch.setattr( paths, "data_dir", lambda root: f"{root}/data/reuse-review" )
    assert rc.data_root() == "/repo/data/reuse-review"
