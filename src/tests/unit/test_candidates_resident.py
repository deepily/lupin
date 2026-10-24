"""
The resident search: held stages and vector sets, confinement and folder-path answers.

The vectors are three hand-made rows, as in the search-process tests.
"""
import json
import os
import threading

import numpy as np
import pytest

from cosa.repo.symindex.candidates import resident, search
from cosa.repo.symindex.candidates.errors import (
    CandidateError, BAD_STAGE_UPLOAD, PATH_REFUSED, STAGE_UNKNOWN, VECTOR_SET_REPLACED, VECTOR_SET_UNAVAILABLE )
from tests.unit.test_candidates_search_process import ENTRIES, FakeSet

QUERY = { "prose": [ 1.0, 0.0 ], "code": [ 0.0, 1.0 ], "concat": [ 1.0, 0.0 ] }


class Loader:
    """Counts loads and returns a fresh FakeSet, optionally under another manifest hash."""

    def __init__( self, manifest_hash="hash-1" ):
        self.calls, self.manifest_hash = [], manifest_hash

    def __call__( self, folder ):
        self.calls.append( folder )
        loaded               = FakeSet()
        loaded.manifest_hash = self.manifest_hash
        return loaded


@pytest.fixture
def root( tmp_path ):
    folder = tmp_path / "data"
    ( folder / "vectors" ).mkdir( parents=True )
    ( folder / "vectors" / "manifest.json" ).write_text( "{}", encoding="utf-8" )
    return folder


@pytest.fixture
def held( root ):
    loader = Loader()
    rs     = resident.ResidentSearch( root, loader )
    rs.put_stage( "k1", ENTRIES )
    return rs, loader, root


def ask( root, **more ):
    return dict( { "stage_key": "k1", "need": "profile", "K": 3 }, **more )


def with_vectors( root, **more ):
    return ask( root, vectors_dir=str( root / "vectors" ), query_vectors=QUERY, **more )


def test_a_held_stage_answers_what_the_folder_path_answers( held, tmp_path ):
    rs, loader, root = held
    gen = tmp_path / "gen"
    gen.mkdir()
    ( gen / "symbols.jsonl" ).write_text( "\n".join( json.dumps( e ) for e in ENTRIES ) + "\n", encoding="utf-8" )
    ( gen / "symbols-all.jsonl" ).write_text( "\n".join( json.dumps( e ) for e in ENTRIES ) + "\n", encoding="utf-8" )
    wanted = search.answer( { "need": "profile", "K": 3, "index_dir": str( gen ), "vectors_dir": str( root / "vectors" ), "query_vectors": QUERY, "wiki": [ "py:c" ] }, loader )
    got    = rs.search( with_vectors( root, wiki=[ "py:c" ] ) )
    assert got == resident.trim_lists( wanted ) and got[ "shortlist" ] == sorted( got[ "shortlist" ] )
    assert got[ "shortlist" ] == wanted[ "shortlist" ] and got[ "ranking" ] == wanted[ "ranking" ]


def test_the_lists_are_cut_to_their_head_and_their_sizes_are_kept():
    full = { "shortlist": [ "a" ], "ranking": [ "a" ], "lists": { "code": [ f"id{i}" for i in range( 30 ) ], "wiki": [ "x" ] },
             "scores": { "code": [ 1.0 ] * 30, "wiki": [] } }
    cut  = resident.trim_lists( full, head=5 )
    assert cut[ "lists" ] == { "code": [ f"id{i}" for i in range( 5 ) ], "wiki": [ "x" ] } and cut[ "scores" ][ "code" ] == [ 1.0 ] * 5
    assert cut[ "list_sizes" ] == { "code": 30, "wiki": 1 } and cut[ "shortlist" ] == [ "a" ] and len( full[ "lists" ][ "code" ] ) == 30
    assert len( resident.trim_lists( full )[ "lists" ][ "code" ] ) == resident.LIST_HEAD


def test_a_search_with_no_vectors_is_bm25_only_and_loads_nothing( held ):
    rs, loader, root = held
    out = rs.search( ask( root ) )
    assert out[ "manifest_hash" ] is None and out[ "shortlist" ] == [ "py:a" ] and loader.calls == []


def test_an_unknown_stage_is_a_named_error( held ):
    rs, _, root = held
    with pytest.raises( CandidateError ) as e: rs.search( dict( ask( root ), stage_key="other" ) )
    assert e.value.code == STAGE_UNKNOWN and e.value.detail == "other"


def test_a_request_without_a_stage_key_or_with_a_bad_one_is_refused( held ):
    rs, _, root = held
    for bad in ( { "need": "x", "K": 1 }, { "stage_key": "", "need": "x", "K": 1 }, { "stage_key": 7, "need": "x", "K": 1 } ):
        with pytest.raises( CandidateError ) as e: rs.search( bad )
        assert e.value.code == search.REQUEST_ERROR
    with pytest.raises( CandidateError ) as e: rs.search( dict( ask( root ), K=0 ) )
    assert e.value.code == search.REQUEST_ERROR


@pytest.mark.parametrize( "kwargs", [
    { "key": "" }, { "key": 3 }, { "entries": [] }, { "entries": "no" }, { "entries": [ { "name": "x" } ] }, { "entries": [ "py:a" ] },
    { "purposes": [ "x" ] }, { "fusion": { "k": 1 } }, { "fusion": "no" },
] )
def test_a_bad_stage_upload_is_refused_and_holds_nothing( root, kwargs ):
    rs   = resident.ResidentSearch( root, Loader() )
    args = dict( { "key": "k", "entries": ENTRIES }, **kwargs )
    with pytest.raises( CandidateError ) as e: rs.put_stage( **args )
    assert e.value.code == BAD_STAGE_UPLOAD
    with pytest.raises( CandidateError ) as e: rs.search( { "stage_key": "k", "need": "x", "K": 1 } )
    assert e.value.code == STAGE_UNKNOWN


def test_the_oldest_stage_is_pushed_out_and_a_reupload_replaces_in_place( root ):
    rs = resident.ResidentSearch( root, Loader(), max_stages=2 )
    for key in ( "a", "b", "c" ): rs.put_stage( key, ENTRIES )
    with pytest.raises( CandidateError ) as e: rs.search( { "stage_key": "a", "need": "profile", "K": 3 } )
    assert e.value.code == STAGE_UNKNOWN
    assert rs.search( { "stage_key": "b", "need": "profile", "K": 3 } )[ "shortlist" ] == [ "py:a" ]
    assert rs.put_stage( "b", ENTRIES[ :1 ] ) == { "key": "b", "entries": 1 }
    rs.put_stage( "d", ENTRIES )                                                    # b was just refreshed, so c goes
    with pytest.raises( CandidateError ): rs.search( { "stage_key": "c", "need": "profile", "K": 3 } )
    assert rs.search( { "stage_key": "b", "need": "profile", "K": 3 } )[ "shortlist" ] == [ "py:a" ]


def test_the_vector_set_is_loaded_once_and_again_only_when_its_manifest_changes( held ):
    rs, loader, root = held
    rs.search( with_vectors( root ) )
    rs.search( with_vectors( root ) )
    assert len( loader.calls ) == 1
    manifest = root / "vectors" / "manifest.json"
    manifest.write_text( "{ }", encoding="utf-8" )
    rs.search( with_vectors( root ) )
    assert len( loader.calls ) == 2
    os.utime( manifest, ns=( 1, 1 ) )
    rs.search( with_vectors( root ) )
    assert len( loader.calls ) == 3


def test_a_missing_manifest_is_the_loaders_error_and_nothing_is_held( root ):
    def failing( folder ): raise OSError( "gone" )
    rs = resident.ResidentSearch( root, failing )
    rs.put_stage( "k1", ENTRIES )
    ( root / "empty" ).mkdir()
    with pytest.raises( CandidateError ) as e: rs.search( ask( root, vectors_dir=str( root / "empty" ), query_vectors=QUERY ) )
    assert e.value.code == VECTOR_SET_UNAVAILABLE


def test_the_oldest_vector_set_is_pushed_out( root, tmp_path ):
    loader = Loader()
    rs     = resident.ResidentSearch( root, loader, max_vector_sets=1 )
    rs.put_stage( "k1", ENTRIES )
    other = root / "other"
    other.mkdir()
    ( other / "manifest.json" ).write_text( "{}", encoding="utf-8" )
    rs.search( with_vectors( root ) )
    rs.search( dict( with_vectors( root ), vectors_dir=str( other ) ) )
    rs.search( with_vectors( root ) )
    assert len( loader.calls ) == 3


def test_a_vectors_folder_outside_the_root_or_beside_it_or_through_a_link_is_refused( held, tmp_path ):
    rs, _, root = held
    sibling = tmp_path / "data-evil"
    sibling.mkdir()
    ( sibling / "manifest.json" ).write_text( "{}", encoding="utf-8" )
    link = root / "escape"
    link.symlink_to( sibling )
    for folder in ( tmp_path, sibling, link, root / ".." ):
        with pytest.raises( CandidateError ) as e: rs.search( dict( with_vectors( root ), vectors_dir=str( folder ) ) )
        assert e.value.code == PATH_REFUSED, folder
    assert rs.search( dict( with_vectors( root ), vectors_dir=str( root ) ) )[ "manifest_hash" ] == "hash-1"     # the root itself is allowed


def test_an_expected_manifest_hash_must_match_the_set_on_disk( held ):
    rs, _, root = held
    assert rs.search( with_vectors( root, expect_manifest_hash="hash-1" ) )[ "manifest_hash" ] == "hash-1"
    with pytest.raises( CandidateError ) as e: rs.search( with_vectors( root, expect_manifest_hash="hash-0" ) )
    assert e.value.code == VECTOR_SET_REPLACED
    with pytest.raises( CandidateError ) as e: rs.search( with_vectors( root, expect_manifest_hash=5 ) )
    assert e.value.code == search.REQUEST_ERROR


def test_concurrent_searches_get_the_same_answer_and_one_load( held ):
    rs, loader, root = held
    out = []
    def run(): out.append( rs.search( with_vectors( root ) ) )
    threads = [ threading.Thread( target=run ) for _ in range( 8 ) ]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len( out ) == 8 and all( o == out[ 0 ] for o in out ) and len( loader.calls ) == 1


def test_a_set_whose_manifest_cannot_be_read_is_loaded_every_time_and_never_held( root ):
    loader = Loader()
    rs     = resident.ResidentSearch( root, loader )
    rs.put_stage( "k1", ENTRIES )
    ( root / "bare" ).mkdir()
    request = ask( root, vectors_dir=str( root / "bare" ), query_vectors=QUERY )
    rs.search( request )
    rs.search( request )
    assert len( loader.calls ) == 2
