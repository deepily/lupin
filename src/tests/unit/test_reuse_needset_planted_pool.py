"""
The planted pool: the search over in-memory rewrites, with the live vector set unchanged.
"""
import hashlib
import pathlib

import numpy as np
import pytest

from cosa.repo.symindex.candidates import vector_build as vb
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp.reuse_needset import planted_pool as pp
from tests.unit.test_candidates_vector_build import FakeClient, entry, vec

REWRITE = { "id": "d-rew0", "file": "src/new/zq_wrapper.py", "name": "zqwrapper", "lang": "py", "sig": "(x)", "text": "def zqwrapper(x): return x", "line": 3, "end_line": 4, "public": True }


def live_entries():
    """Return five index entries with words of their own."""
    return [ entry( n, f"pin{n}", sig="(a)", doc=f"{n} routine" ) for n in ( "alpha", "bravo", "charlie", "delta", "echo" ) ]


def build_live( tmp_path, client ):
    """Build a real sealed vector set of the five entries and return its folder."""
    out = tmp_path / "vectors"
    vb.build_vectors( live_entries(), {}, client, out, pause_seconds=0, sleep=lambda s: None )
    return out


def folder_digest( folder ):
    """Return the sha256 of every file in the folder, by name."""
    return { p.name: hashlib.sha256( p.read_bytes() ).hexdigest() for p in sorted( pathlib.Path( folder ).iterdir() ) }


def planted_stage( tmp_path, client=None ):
    """Return ( stage, live folder, planted entry ) for the five entries plus the rewrite."""
    client = client or FakeClient()
    live   = build_live( tmp_path, client )
    extra  = pp.planted_entry( REWRITE )
    vectors = pp.PlantedVectors( vs.load_vectors( live ), [ REWRITE[ "id" ] ], pp.embed_rows( [ extra ], client ) )
    stage  = pp.PlantedCandidateStage( live, tmp_path / "qcache", client, vectors, K=6, arm="B1" )
    return stage, live, extra


def test_a_rewrite_becomes_an_index_record_with_the_fields_the_judge_and_the_search_read():
    e = pp.planted_entry( REWRITE )
    assert e == { "id": "d-rew0", "file": "src/new/zq_wrapper.py", "lang": "py", "module": "src.new.zq_wrapper", "name": "zqwrapper", "sig": "(x)", "doc": "",
                  "pin": hashlib.sha256( REWRITE[ "text" ].encode() ).hexdigest()[ :10 ], "scope": "public", "line": 3, "end_line": 4 }
    bare = pp.planted_entry( { "id": "d-x", "file": "a.py", "name": "n", "lang": "py", "sig": "()", "public": False } )
    assert bare[ "scope" ] == "private" and bare[ "line" ] == 1 and bare[ "end_line" ] == 1 and bare[ "pin" ] == hashlib.sha256( b"" ).hexdigest()[ :10 ]
    assert pp.planted_entry( { "id": "d-y", "file": "a.py", "name": "n", "lang": "ts", "sig": "()" } )[ "scope" ] == "public"
    assert pp.planted_entry( { "id": "d-z", "file": "x.js", "name": "n", "lang": "ts", "sig": "()" } )[ "lang" ] == "ts"      # the rewrite's own language: the real planted file has a TypeScript rewrite in a .js file


def test_the_rewrites_are_embedded_as_the_build_does_and_those_are_embedding_calls_only():
    client = FakeClient()
    rows   = pp.embed_rows( [ pp.planted_entry( REWRITE ) ], client )
    texts  = vb.entry_texts( pp.planted_entry( REWRITE ), "" )
    assert sorted( rows ) == sorted( vs.MATRICES )
    for name in vs.MATRICES:
        content_type, role = vs.DOCUMENT_ROLES[ name ]
        assert rows[ name ] == [ vec( content_type, role, texts[ name ] ) ]


def test_the_planted_vectors_stack_the_rows_under_the_live_ones_and_leave_the_live_ones_alone( tmp_path ):
    client = FakeClient()
    base   = vs.load_vectors( build_live( tmp_path, client ) )
    rows_before = len( base.ids )
    planted = pp.PlantedVectors( base, [ "d-rew0" ], pp.embed_rows( [ pp.planted_entry( REWRITE ) ], client ) )
    assert planted.ids == [ *base.ids, "d-rew0" ] and planted.manifest_hash == base.manifest_hash
    assert all( m.shape[ 0 ] == rows_before + 1 for m in planted.matrices.values() ) and len( base.ids ) == rows_before and base.matrices[ "concat" ].shape[ 0 ] == rows_before


def test_the_planted_stage_finds_the_rewrite_in_both_halves_and_leaves_the_live_folder_alone( tmp_path ):
    stage, live, extra = planted_stage( tmp_path )
    before  = folder_digest( live )
    entries = [ *live_entries(), extra ]
    got     = stage.shortlist( "zqwrapper", entries, "sha", [] )
    assert "d-rew0" in got[ "ids" ] and "d-rew0" in got[ "lists" ][ "code" ][ "head" ]
    assert "d-rew0" in got[ "lists" ][ "vector_concat" ][ "head" ] and got[ "lists" ][ "vector_concat" ][ "size" ] == 6
    assert folder_digest( live ) == before and not [ p for p in tmp_path.rglob( "*" ) if p.name.endswith( ".tmp" ) ]
    assert list( ( tmp_path / "qcache" ).glob( "*.json" ) ), "the query vectors are cached in the folder the stage was given, and nowhere else"


def test_a_pool_with_no_planted_row_cannot_find_the_rewrite_and_a_ghost_vector_row_is_refused_by_name( tmp_path ):
    client  = FakeClient()
    live    = build_live( tmp_path, client )
    base    = vs.load_vectors( live )
    plain   = pp.PlantedCandidateStage( live, tmp_path / "q1", client, pp.PlantedVectors( base, [], { n: np.empty( ( 0, 4 ) ) for n in vs.MATRICES } ), K=6, arm="B1" )
    assert "d-rew0" not in plain.shortlist( "zqwrapper", live_entries(), "sha2", [] )[ "ids" ]
    ( tmp_path / "g" ).mkdir()
    ghost, _, _ = planted_stage( tmp_path / "g" )
    with pytest.raises( CandidateError ) as e: ghost.shortlist( "zqwrapper", live_entries(), "sha3", [] )
    assert e.value.code == "CANDIDATE_SEARCH_FAILED" and "VECTOR_IDS_NOT_IN_INDEX" in str( e.value )


def test_a_stage_that_was_never_uploaded_answers_409_and_a_foreign_folder_403_and_other_errors_503( tmp_path, monkeypatch ):
    stage, live, _ = planted_stage( tmp_path )
    status, body = stage._call( "POST", "/api/reuse-candidates/search", { "stage_key": "nope", "need": "x", "K": 3 } )
    assert status == 409 and body[ "error" ] == "STAGE_UNKNOWN"
    stage._call( "PUT", "/api/reuse-candidates/stage", { "key": "k", "entries": live_entries(), "purposes": None, "fusion": None } )
    status, body = stage._call( "POST", "/api/reuse-candidates/search", { "stage_key": "k", "need": "x", "K": 3, "vectors_dir": "/", "query_vectors": { "concat": [ 0.1, 0.2, 0.3, 0.4 ] } } )
    assert status == 403 and body[ "error" ] == "PATH_REFUSED"

    def other( *a, **k ): raise CandidateError( "SOMETHING_ELSE", "detail" )

    monkeypatch.setattr( stage._resident, "search", other )
    status, body = stage._call( "POST", "/api/reuse-candidates/search", { } )
    assert status == 503 and body == { "error": "SOMETHING_ELSE", "detail": "detail" }


def test_a_planted_stage_refuses_a_refresher_because_that_would_rebuild_the_live_set( tmp_path ):
    client = FakeClient()
    live   = build_live( tmp_path, client )
    with pytest.raises( ValueError ): pp.PlantedCandidateStage( live, tmp_path / "q", client, None, refresher=lambda: None )


def test_a_plant_with_a_purpose_line_embeds_it_as_a_real_entry_does_and_one_without_embeds_the_empty_line():
    client = FakeClient()
    plain  = pp.planted_entry( REWRITE )
    other  = pp.planted_entry( { **REWRITE, "id": "d-rew1", "text": "def other(): pass" } )
    rows   = pp.embed_rows( [ plain, other ], client, { plain[ "pin" ]: "Wraps a value so a caller can pass it on." } )
    first  = vb.entry_texts( plain, "Wraps a value so a caller can pass it on." )
    second = vb.entry_texts( other, "" )
    for name in vs.MATRICES:
        content_type, role = vs.DOCUMENT_ROLES[ name ]
        assert rows[ name ] == [ vec( content_type, role, first[ name ] ), vec( content_type, role, second[ name ] ) ]
    assert first[ "prose" ] != vb.entry_texts( plain, "" )[ "prose" ], "the line is part of the text, so a plant without it differs"


def test_the_stage_keeps_the_whole_lists_of_its_last_search_and_hands_the_caller_the_cut_ones( tmp_path ):
    stage, live, extra = planted_stage( tmp_path )
    assert stage.last_answer is None
    found = stage.shortlist( "zqwrapper", [ *live_entries(), extra ], "sha", [] )
    whole = stage.last_answer
    assert all( len( whole[ "lists" ][ n ] ) == whole[ "list_sizes" ][ n ] for n in whole[ "lists" ] ) and found[ "ids" ] == whole[ "shortlist" ]
    assert all( len( found[ "lists" ][ n ] ) <= 20 for n in found[ "lists" ] )


def test_a_list_longer_than_the_head_is_kept_whole_in_last_answer_and_cut_only_in_what_the_caller_gets( tmp_path, monkeypatch ):
    stage, live, extra = planted_stage( tmp_path )
    big = { "shortlist": [ ], "ranking": [ ], "lists": { "code": [ f"i{n}" for n in range( 30 ) ] }, "scores": { "code": [ 1.0 ] * 30 } }
    monkeypatch.setattr( stage._resident, "search", lambda body: big )
    status, body = stage._call( "POST", "/search", { } )
    assert status == 200 and len( stage.last_answer[ "lists" ][ "code" ] ) == 30 and len( body[ "lists" ][ "code" ] ) == 20 and body[ "list_sizes" ] == { "code": 30 }
