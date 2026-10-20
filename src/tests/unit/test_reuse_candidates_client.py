"""
The candidate stage client: upload once, search by key, cached vectors, named failures.

The client talks to the real router and the real resident search through a urllib stand-in.
A hand-made vector set is used, so a status or a body the client misreads fails here.
"""
import io
import json
import urllib.error

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError
from cosa.repo.symindex.candidates.resident import ResidentSearch
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import reuse_candidates as router
from lupin_mcp import reuse_candidates as rcand
from tests.unit.test_candidates_resident import ENTRIES, FakeSet, Loader

ENGINE = { "model": "m", "revision": "r1", "dtype": "float16", "device": "cuda", "query_prefix": "q: ", "document_prefix": "d: ", "dimensions": 2 }
SMALL  = { "k": 60, "depth": 100, "head": 0 }                          # a head of 5 per list does not fit in a K of 2
PAGES  = [ { "slug": "profiles", "text": "user profile pages", "pins": [ "py:b" ], "scope": [] } ]


class Bridge:
    """A urlopen stand-in that sends each request to the router in process and keeps what it saw."""

    def __init__( self, app, down=None ):
        self.http, self.seen, self.down = TestClient( app ), [], down

    def __call__( self, request, timeout=None ):
        if self.down is not None: raise self.down
        body = json.loads( request.data )
        self.seen.append( ( request.get_method(), request.full_url.split( "/api/", 1 )[ 1 ], body, dict( request.header_items() ) ) )
        r = self.http.request( request.get_method(), request.full_url.split( "://", 1 )[ 1 ].split( "/", 1 )[ 1 ].join( [ "/", "" ] ), content=request.data, headers=dict( request.header_items() ) )
        if r.status_code >= 400: raise urllib.error.HTTPError( request.full_url, r.status_code, "x", {}, io.BytesIO( r.content ) )
        return types_response( r )


def types_response( r ):
    class Out:
        status = r.status_code
        def read( self ): return r.content
        def __enter__( self ): return self
        def __exit__( self, *a ): return False
    return Out()


class Embedder:
    """Counts embeds and reports engines that match the manifest."""

    def __init__( self ): self.embeds, self.engines = [], { "code": dict( ENGINE, model="code-m" ), "prose": dict( ENGINE, model="prose-m" ), "device_class": "gpu" }
    def embed( self, texts, content_type, role ):
        self.embeds.append( ( tuple( texts ), content_type, role ) )
        return [ [ 1.0, 0.0 ] if content_type == "prose" else [ 0.0, 1.0 ] for _ in texts ]
    def info( self ): return { "engines": self.engines }


@pytest.fixture
def world( tmp_path, monkeypatch ):
    root = tmp_path / "data"
    ( root / "vectors" ).mkdir( parents=True )
    manifest = { "engines": { "code": dict( ENGINE, model="code-m" ), "prose": dict( ENGINE, model="prose-m" ) }, "device_class": "gpu",
                 "document_roles": { k: list( v ) for k, v in vs.DOCUMENT_ROLES.items() }, "query_roles": { k: list( v ) for k, v in vs.QUERY_ROLES.items() },
                 "dimension": 2, "rows": 3 }
    manifest[ "manifest_hash" ] = vs.manifest_hash( manifest )
    ( root / "vectors" / "manifest.json" ).write_text( json.dumps( manifest ), encoding="utf-8" )
    ( root / "purposes.jsonl" ).write_text( json.dumps( { "pin": "pb", "purpose": "load settings from a file" } ) + "\n", encoding="utf-8" )
    loader = Loader( manifest_hash=manifest[ "manifest_hash" ] )
    monkeypatch.setitem( router._held, "search", ResidentSearch( root, loader ) )
    app = FastAPI()
    app.include_router( router.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "u"
    bridge   = Bridge( app )
    embedder = Embedder()
    def make( **kw ):
        args = dict( base_url="http://lupin:7999", api_key="k", vectors_dir=root / "vectors", query_cache_dir=root / "query-cache", embed_client=embedder,
                     purposes_path=str( root / "purposes.jsonl" ), urlopen=bridge )
        return rcand.CandidateStage( **dict( args, **kw ) )
    return make, bridge, embedder, root, manifest, loader


def lookup( stage, text="profile", **kw ): return stage.shortlist( text, ENTRIES, "idx-1", PAGES, **kw )


def test_the_first_lookup_uploads_the_stage_and_the_second_does_not( world ):
    make, bridge, embedder, *_ = world
    stage = make()
    first = lookup( stage )
    kinds = [ ( m, p ) for m, p, _, _ in bridge.seen ]
    assert kinds == [ ( "POST", "reuse-candidates/search" ), ( "PUT", "reuse-candidates/stage" ), ( "POST", "reuse-candidates/search" ) ]
    bridge.seen.clear()
    second = lookup( make(), "profile" )                                                    # a new client object, the same server
    assert [ m for m, *_ in bridge.seen ] == [ "POST" ] and second[ "ids" ] == first[ "ids" ]
    assert first[ "ids" ] == sorted( first[ "ids" ] ) and set( first[ "ids" ] ) <= { e[ "id" ] for e in ENTRIES }


def test_the_key_header_and_body_carry_what_the_server_needs( world ):
    make, bridge, _, root, manifest, _ = world
    lookup( make( K=2, fusion=SMALL ) )
    method, path, body, headers = bridge.seen[ -1 ]
    assert headers[ "X-api-key" ] == "k" and body[ "K" ] == 2 and body[ "expect_manifest_hash" ] == manifest[ "manifest_hash" ]
    assert body[ "vectors_dir" ] == str( root / "vectors" ) and set( body[ "query_vectors" ] ) == { "concat" } and body[ "need" ] == "profile"


def test_the_stage_with_no_arm_given_runs_b1_and_sends_no_wiki_list( world ):
    make, bridge, *_ = world
    r = lookup( make() )
    assert rcand.DEFAULT_ARM == "B1" and r[ "arm" ] == "B1" and r[ "wiki" ] == 0 and bridge.seen[ -1 ][ 2 ][ "wiki" ] == []


def test_the_result_names_what_a_receipt_records( world ):
    make, _, _, _, manifest, _ = world
    r = lookup( make( arm="B2w" ) )
    assert r[ "manifest_hash" ] == manifest[ "manifest_hash" ] and r[ "arm" ] == "B2w" and r[ "K" ] == 128 and r[ "widened" ] is False
    assert r[ "embed_models" ] == { "code": "code-m", "prose": "prose-m" } and len( r[ "ranking_hash" ] ) == 64 and r[ "wiki" ] == 1
    assert set( r[ "lists" ] ) >= { "code", "prose", "vector_prose", "vector_code", "wiki" }
    assert r[ "lists" ][ "code" ][ "size" ] >= 1 and isinstance( r[ "lists" ][ "code" ][ "head" ], list )
    assert sorted( r[ "ranking" ] ) == r[ "ids" ]


def test_the_excluded_id_is_dropped_and_k_still_bounds_the_list( world ):
    make, bridge, *_ = world
    full = lookup( make( K=2, fusion=SMALL ) )
    cut  = lookup( make( K=2, fusion=SMALL ), exclude_id=full[ "ranking" ][ 0 ] )
    assert full[ "ranking" ][ 0 ] not in cut[ "ids" ] and len( cut[ "ids" ] ) <= 2
    assert bridge.seen[ -1 ][ 2 ][ "K" ] == 3                                              # one more is asked for, so K survive the exclusion


def test_a_k_for_one_call_replaces_the_clients_own_and_still_adds_one_for_an_exclusion( world ):
    make, bridge, *_ = world
    stage = make( K=2, fusion=SMALL )
    r     = lookup( stage, K=512 )
    assert bridge.seen[ -1 ][ 2 ][ "K" ] == 512 and r[ "K" ] == 512
    lookup( stage, exclude_id=r[ "ranking" ][ 0 ], K=512 )
    assert bridge.seen[ -1 ][ 2 ][ "K" ] == 513


def test_the_arms_ask_about_their_own_matrices_and_only_the_wiki_arm_sends_the_wiki_list( world ):
    make, bridge, *_ = world
    lookup( make( arm="B1" ) )
    body = bridge.seen[ -1 ][ 2 ]
    assert set( body[ "query_vectors" ] ) == { "concat" } and body[ "wiki" ] == []
    lookup( make( arm="B2" ) )
    assert set( bridge.seen[ -1 ][ 2 ][ "query_vectors" ] ) == { "prose", "code" } and bridge.seen[ -1 ][ 2 ][ "wiki" ] == []
    lookup( make( arm="B2w" ) )
    assert bridge.seen[ -1 ][ 2 ][ "wiki" ] == [ "py:b" ]


def test_a_cached_query_vector_is_not_embedded_again( world ):
    make, _, embedder, *_ = world
    lookup( make() )
    n = len( embedder.embeds )
    lookup( make() )
    assert n > 0 and len( embedder.embeds ) == n


def test_a_changed_engine_is_a_named_error_before_any_search( world ):
    make, bridge, embedder, *_ = world
    embedder.engines[ "prose" ][ "revision" ] = "other"
    with pytest.raises( CandidateError ) as e: lookup( make() )
    assert e.value.code == "ENGINE_MISMATCH" and bridge.seen == []


def test_cache_only_reads_the_cache_and_never_embeds_or_uploads( world ):
    make, bridge, embedder, *_ = world
    with pytest.raises( CandidateError ) as e: lookup( make(), cache_only=True )
    assert e.value.code == rcand.QUERY_VECTOR_MISSING and embedder.embeds == [] and bridge.seen == []
    lookup( make() )                                                                          # warms the cache and uploads
    bridge.seen.clear()
    again = lookup( make(), cache_only=True )
    assert again[ "ids" ] and embedder.embeds and [ m for m, *_ in bridge.seen ] == [ "POST" ]


def test_a_cached_vector_made_under_another_manifest_is_missing_in_cache_only_mode( world ):
    make, _, _, root, manifest, _ = world
    cache = root / "query-cache"
    cache.mkdir()
    ( cache / f"{vs.query_key( 'profile' )}.json" ).write_text( json.dumps( { "manifest_hash": "someone-else", "vectors": { "prose": [ 1, 0 ], "code": [ 0, 1 ], "concat": [ 1, 0 ] } } ), encoding="utf-8" )
    with pytest.raises( CandidateError ) as e: lookup( make(), cache_only=True )
    assert e.value.code == rcand.QUERY_VECTOR_MISSING


def test_cache_only_does_not_upload_a_stage_the_server_lacks( world, monkeypatch ):
    make, bridge, *_ = world
    lookup( make() )                                                                          # warm the query cache
    monkeypatch.setitem( router._held, "search", ResidentSearch( world[ 3 ], Loader( manifest_hash=world[ 4 ][ "manifest_hash" ] ) ) )     # a restarted server
    bridge.seen.clear()
    with pytest.raises( CandidateError ) as e: lookup( make(), cache_only=True )
    assert e.value.code == rcand.CANDIDATE_SEARCH_FAILED and "STAGE_UNKNOWN" in e.value.detail
    assert [ m for m, *_ in bridge.seen ] == [ "POST" ]


def test_a_replaced_vector_set_is_its_own_error( world, monkeypatch ):
    make, _, _, root, manifest, _ = world
    monkeypatch.setitem( router._held, "search", ResidentSearch( root, Loader( manifest_hash="a-rebuilt-set" ) ) )
    with pytest.raises( CandidateError ) as e: lookup( make() )
    assert e.value.code == rcand.VECTOR_SET_REPLACED


def test_an_empty_need_is_refused_before_any_work( world ):
    make, bridge, embedder, *_ = world
    with pytest.raises( CandidateError ) as e: lookup( make(), "   " )
    assert e.value.code == rcand.EMPTY_NEED and bridge.seen == [] and embedder.embeds == []


def test_a_missing_or_damaged_manifest_is_named( world ):
    make, _, _, root, manifest, _ = world
    path = root / "vectors" / "manifest.json"
    path.write_text( "not json", encoding="utf-8" )
    with pytest.raises( CandidateError ) as e: lookup( make() )
    assert e.value.code == vs.VECTOR_SET_CORRUPT
    path.write_text( json.dumps( dict( manifest, rows=999 ) ), encoding="utf-8" )
    with pytest.raises( CandidateError ) as e: lookup( make() )
    assert e.value.code == vs.VECTOR_SET_CORRUPT
    path.unlink()
    with pytest.raises( CandidateError ) as e: lookup( make() )
    assert e.value.code == vs.VECTOR_SET_UNAVAILABLE


def test_an_unreachable_server_a_bad_body_and_a_failed_upload_are_search_failures( world ):
    make, bridge, *_ = world
    for down in ( urllib.error.URLError( "refused" ), OSError( "reset" ), ValueError( "bad json" ) ):
        bridge.down = down
        with pytest.raises( CandidateError ) as e: lookup( make() )
        assert e.value.code == rcand.CANDIDATE_SEARCH_FAILED
    bridge.down = None
    bad = make()
    with pytest.raises( CandidateError ) as e: bad.shortlist( "profile", [ { "name": "no id" } ], "idx-2", PAGES )
    assert e.value.code == rcand.CANDIDATE_SEARCH_FAILED and "BAD_STAGE_UPLOAD" in e.value.detail


def test_a_server_error_with_a_body_that_is_not_json_is_a_search_failure( world ):
    make, _, _, _, _, _ = world
    def broken( request, timeout=None ): raise urllib.error.HTTPError( request.full_url, 502, "bad gateway", {}, io.BytesIO( b"<html>" ) )
    with pytest.raises( CandidateError ) as e: lookup( make( urlopen=broken ) )
    assert e.value.code == rcand.CANDIDATE_SEARCH_FAILED and "502" in e.value.detail


def test_a_server_that_answers_a_named_failure_has_it_carried_in_the_detail( world, monkeypatch ):
    make, _, _, root, *_ = world
    class Corrupt( ResidentSearch ):
        def search( self, request ): raise CandidateError( "VECTOR_SET_CORRUPT", "a hash does not match" )
    monkeypatch.setitem( router._held, "search", Corrupt( root, Loader() ) )
    with pytest.raises( CandidateError ) as e: lookup( make() )
    assert e.value.code == rcand.CANDIDATE_SEARCH_FAILED and "VECTOR_SET_CORRUPT: a hash does not match" in e.value.detail


@pytest.mark.parametrize( "kwargs", [ { "arm": "C9" }, { "K": 0 }, { "K": True }, { "K": "128" } ] )
def test_a_bad_arm_or_k_is_refused_at_construction( world, kwargs ):
    make, *_ = world
    with pytest.raises( ValueError ): make( **kwargs )


def test_the_purpose_file_is_optional_and_a_missing_one_is_an_empty_mapping( world ):
    make, bridge, *_ = world
    r = lookup( make( purposes_path=None ) )
    assert r[ "ids" ] and [ m for m, *_ in bridge.seen ][ :2 ] == [ "POST", "PUT" ]
    assert bridge.seen[ 1 ][ 2 ][ "purposes" ] is None
    r2 = make( purposes_path="/nonexistent/purposes.jsonl" ).shortlist( "settings", ENTRIES, "idx-3", PAGES )
    assert r2[ "ids" ]


# ── freshen on demand: compare the index with the set's build info before a lookup ──

from cosa.repo.symindex.candidates import freshness as fr

HEADER = { "manifest": { "m.py": [ 1, 2 ] }, "symbols_sha": "sha-1" }
INDEX  = fr.index_manifest( HEADER )


class Refresher:
    """Counts calls; each call runs `action`, set to what the build would change."""

    def __init__( self, action=None ): self.calls, self.action = 0, action
    def __call__( self ):
        self.calls += 1
        if self.action is not None: self.action()


class GhostLoader( Loader ):
    """A loader whose set holds one id the index lacks."""

    def __call__( self, folder ):
        loaded     = super().__call__( folder )
        loaded.ids = [ "py:a", "py:b", "gone::g" ]
        return loaded


def stamp( root, header=None ): fr.write_build_info( root / "vectors", HEADER if header is None else header, "2026-10-18T00:00:00+00:00" )


def test_a_set_built_from_this_index_is_fresh_and_nothing_is_refreshed( world ):
    make, bridge, _, root, *_ = world
    stamp( root )
    refresher = Refresher()
    got = lookup( make( refresher=refresher ), index_manifest=INDEX )
    assert refresher.calls == 0 and got[ "freshness" ] == { "state": "fresh" }
    assert all( "skip_lost_ids" not in body for _, _, body, _ in bridge.seen )


def test_a_set_behind_the_index_is_refreshed_before_anything_is_sent( world ):
    make, bridge, _, root, *_ = world
    stamp( root, { "manifest": { "m.py": [ 9, 9 ] }, "symbols_sha": "old" } )
    seen_at_call = []
    refresher    = Refresher( lambda: ( seen_at_call.append( len( bridge.seen ) ), stamp( root ) ) )
    got = lookup( make( refresher=refresher ), index_manifest=INDEX )
    assert refresher.calls == 1 and seen_at_call == [ 0 ] and got[ "freshness" ] == { "state": "refreshed" }
    assert all( "skip_lost_ids" not in body for _, _, body, _ in bridge.seen )


def test_a_set_with_no_build_info_counts_as_behind( world ):
    make, _, _, _, *_ = world
    refresher = Refresher()
    got = lookup( make( refresher=refresher ), index_manifest=INDEX )
    assert refresher.calls == 1 and got[ "freshness" ][ "state" ] == "refreshed"


def test_the_manifest_is_read_after_the_refresh_so_the_lookup_uses_the_fresh_set( world ):
    make, bridge, _, root, manifest, _ = world
    def rewrite():
        newer = dict( manifest, rows=4 )
        newer[ "manifest_hash" ] = vs.manifest_hash( { k: v for k, v in newer.items() if k != "manifest_hash" } )
        ( root / "vectors" / "manifest.json" ).write_text( json.dumps( newer ), encoding="utf-8" )
        stamp( root )
        self_hash.append( newer[ "manifest_hash" ] )
    self_hash = []
    try: lookup( make( refresher=Refresher( rewrite ) ), index_manifest=INDEX )
    except CandidateError: pass                                                        # the fake loader still holds the old hash; only the request body matters
    assert bridge.seen[ -1 ][ 2 ][ "expect_manifest_hash" ] == self_hash[ 0 ] != manifest[ "manifest_hash" ]


@pytest.mark.parametrize( "failure", [ CandidateError( "BUILD_LOCK_HELD", "another build holds it" ), ValueError( "a worktree" ), OSError( "disk" ), RuntimeError( "boom" ) ] )
def test_a_failed_refresh_answers_from_the_stale_set_and_counts_the_lost_ids( world, monkeypatch, failure ):
    make, bridge, _, root, manifest, _ = world
    monkeypatch.setitem( router._held, "search", ResidentSearch( root, GhostLoader( manifest_hash=manifest[ "manifest_hash" ] ) ) )
    stamp( root, { "manifest": { "m.py": [ 9, 9 ] }, "symbols_sha": "old" } )
    def fail(): raise failure
    got = lookup( make( refresher=Refresher( fail ) ), index_manifest=INDEX )
    fresh = got[ "freshness" ]
    assert fresh[ "state" ] == "stale" and type( failure ).__name__ in fresh[ "error" ]
    assert fresh[ "ids_lost" ] == 1 and fresh[ "note" ] == "answered from a stale set, 1 ids lost"
    assert "gone::g" not in got[ "ranking" ] and all( body[ "skip_lost_ids" ] is True for m, p, body, _ in bridge.seen if p.endswith( "search" ) )


def test_a_stale_set_with_nothing_lost_says_zero( world ):
    make, _, _, root, *_ = world
    def fail(): raise RuntimeError( "no" )
    got = lookup( make( refresher=Refresher( fail ) ), index_manifest=INDEX )
    assert got[ "freshness" ][ "ids_lost" ] == 0 and got[ "freshness" ][ "note" ] == "answered from a stale set, 0 ids lost"


def test_a_ghost_id_without_a_failed_refresh_is_still_refused( world, monkeypatch ):
    make, _, _, root, manifest, _ = world
    monkeypatch.setitem( router._held, "search", ResidentSearch( root, GhostLoader( manifest_hash=manifest[ "manifest_hash" ] ) ) )
    stamp( root )
    with pytest.raises( CandidateError ) as e: lookup( make( refresher=Refresher() ), index_manifest=INDEX )
    assert e.value.code == rcand.CANDIDATE_SEARCH_FAILED and "VECTOR_IDS_NOT_IN_INDEX" in e.value.detail


def test_no_refresher_no_index_manifest_or_a_replay_read_is_unchecked( world ):
    make, _, _, root, *_ = world
    refresher = Refresher()
    assert lookup( make() , index_manifest=INDEX )[ "freshness" ] == { "state": "unchecked" }
    assert lookup( make( refresher=refresher ) )[ "freshness" ] == { "state": "unchecked" }
    lookup( make( refresher=refresher ), index_manifest=INDEX )                         # warms the query cache, refreshes once
    again = refresher.calls
    assert lookup( make( refresher=refresher ), index_manifest=INDEX, cache_only=True )[ "freshness" ] == { "state": "unchecked" } and refresher.calls == again
