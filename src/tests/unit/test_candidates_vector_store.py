"""
Unit tests for the stored vector set: seal, load, swap, engine check and query cache.

The fake client's vectors depend on the text, the engine and the role.
So a wrong role or a wrong text changes the stored bytes, and a test sees it.
"""
import copy
import hashlib
import json

import numpy as np
import pytest

from cosa.repo.symindex.candidates import vector_build as vb
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import (
    CandidateError, DEPENDENCY_MISSING, ENGINE_MISMATCH, ENGINE_NOT_LOADED, VECTOR_SET_UNAVAILABLE, VECTOR_SET_CORRUPT )

DIM = 4


def vec( content_type, role, text ):
    """A vector that depends on all three inputs."""
    d = hashlib.sha256( f"{content_type}|{role}|{text}".encode() ).digest()
    return [ d[ i ] / 255.0 for i in range( DIM ) ]


def engines_block( revision="rev1", **override ):
    code  = { "model": "code-m", "revision": revision, "dtype": "float16", "device": "cuda:0", "query_prefix": "Q:", "document_prefix": "", "dimensions": DIM, "loaded": True }
    prose = { "model": "prose-m", "revision": revision, "dtype": "float16", "device": "cuda:0", "query_prefix": "search_query:", "document_prefix": "search_document:", "dimensions": DIM, "loaded": True }
    code.update( override.get( "code", {} ) )
    prose.update( override.get( "prose", {} ) )
    return { "code": code, "prose": prose, "device_class": override.get( "device_class", "RTX 4090, sm_89" ), "libraries": { "numpy": "2.4.4" } }


class FakeClient:
    def __init__( self, engines=None ):
        self.engines = engines if engines is not None else engines_block()
        self.calls   = []
        self.infos   = 0

    def embed( self, texts, content_type, role ):
        self.calls.append( ( content_type, role, list( texts ) ) )
        return [ vec( content_type, role, t ) for t in texts ]

    def info( self ):
        self.infos += 1
        return copy.deepcopy( { "provider": "local", "dimensions": DIM, "status": "ready", "engines": self.engines } )


def entries():
    return [
        { "id": "m.b", "file": "m.py", "name": "b", "sig": "(x)", "doc": "Does b.", "pin": "pb" },
        { "id": "m.a", "file": "m.py", "name": "a", "sig": "()",  "doc": "",        "pin": "pa" }
    ]


PURPOSES = { "pa": { "pin": "pa", "purpose": "Return a.", "prompt_hash": "ph", "writer_version": "w1" } }


@pytest.fixture
def built( tmp_path ):
    client   = FakeClient()
    out      = tmp_path / "new"
    manifest = vb.build_vectors( entries(), PURPOSES, client, out, pause_seconds=0, sleep=lambda s: None )
    return { "dir": out, "manifest": manifest, "client": client, "root": tmp_path }


# ── seal and load ───────────────────────────────────────────────────────────


def test_seal_writes_ids_hashes_and_a_self_consistent_manifest_hash( built ):
    m = built[ "manifest" ]
    assert ( built[ "dir" ] / "ids.txt" ).read_text() == "m.a\nm.b\n"
    assert set( m[ "files" ] ) == { "ids.txt", "prose.f32", "code.f32", "concat.f32", "row_texts.jsonl" }
    assert m[ "manifest_hash" ] == vs.manifest_hash( m )
    on_disk = json.loads( ( built[ "dir" ] / "manifest.json" ).read_text() )
    assert on_disk == m


def test_load_returns_rows_in_id_order_as_float32( built ):
    s = vs.load_vectors( built[ "dir" ] )
    assert s.ids == [ "m.a", "m.b" ]
    assert s.manifest_hash == built[ "manifest" ][ "manifest_hash" ]
    assert s.matrices[ "code" ].shape == ( 2, DIM )
    assert s.matrices[ "code" ].dtype == np.dtype( "<f4" )
    # row 0 is m.a: its code text is path::name+sig and was embedded as a code document
    expected = np.asarray( vec( "code", "document", "m.py::a()" ), dtype="<f4" )
    assert np.array_equal( s.matrices[ "code" ][ 0 ], expected )


def test_load_without_a_manifest_is_vector_set_unavailable( tmp_path ):
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( tmp_path / "none" )
    assert e.value.code == VECTOR_SET_UNAVAILABLE


def test_load_without_numpy_is_dependency_missing( built, monkeypatch ):
    import builtins
    real = builtins.__import__

    def no_numpy( name, *a, **k ):
        if name == "numpy": raise ImportError( "no numpy here" )
        return real( name, *a, **k )

    monkeypatch.setattr( builtins, "__import__", no_numpy )
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( built[ "dir" ] )
    assert e.value.code == DEPENDENCY_MISSING


def test_a_changed_manifest_field_is_corrupt( built ):
    p = built[ "dir" ] / "manifest.json"
    m = json.loads( p.read_text() )
    m[ "rows" ] = 99
    p.write_text( json.dumps( m ) )
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( built[ "dir" ] )
    assert e.value.code == VECTOR_SET_CORRUPT
    assert "manifest_hash" in e.value.detail


@pytest.mark.parametrize( "name", [ "prose.f32", "code.f32", "concat.f32", "ids.txt" ] )
def test_a_changed_file_is_corrupt_and_the_manifest_hash_changes_with_any_file( built, name ):
    ( built[ "dir" ] / name ).write_bytes( ( built[ "dir" ] / name ).read_bytes()[ :-1 ] + b"\x00" )
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( built[ "dir" ] )
    assert e.value.code == VECTOR_SET_CORRUPT
    assert name in e.value.detail


def test_a_deleted_file_is_corrupt( built ):
    ( built[ "dir" ] / "code.f32" ).unlink()
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( built[ "dir" ] )
    assert e.value.code == VECTOR_SET_CORRUPT


def test_a_matrix_of_the_wrong_size_is_corrupt_even_when_hashes_match( built ):
    d = built[ "dir" ]
    ( d / "code.f32" ).write_bytes( b"\x00" * 4 * DIM )          # one row instead of two
    m = json.loads( ( d / "manifest.json" ).read_text() )
    m[ "files" ][ "code.f32" ] = vs.file_sha256( d / "code.f32" )
    m[ "manifest_hash" ]       = vs.manifest_hash( m )
    ( d / "manifest.json" ).write_text( json.dumps( m ) )
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( d )
    assert e.value.code == VECTOR_SET_CORRUPT
    assert "code.f32" in e.value.detail


def test_manifest_hash_ignores_its_own_field_and_sees_every_other( built ):
    m = built[ "manifest" ]
    assert vs.manifest_hash( { **m, "manifest_hash": "x" } ) == m[ "manifest_hash" ]
    changed = copy.deepcopy( m )
    changed[ "engines" ][ "code" ][ "revision" ] = "other"
    assert vs.manifest_hash( changed ) != m[ "manifest_hash" ]


@pytest.mark.parametrize( "name", [ "ids.txt", "prose.f32", "code.f32", "concat.f32" ] )
def test_manifest_hash_changes_when_any_file_hash_changes( built, name ):
    m       = built[ "manifest" ]
    changed = copy.deepcopy( m )
    changed[ "files" ][ name ] = "0" * 64
    assert changed[ "files" ][ name ] != m[ "files" ][ name ]
    assert vs.manifest_hash( changed ) != m[ "manifest_hash" ]


# ── the swap ────────────────────────────────────────────────────────────────


def test_swap_in_replaces_the_live_set_and_removes_the_old_one( built ):
    live = built[ "root" ] / "vectors"
    live.mkdir()
    ( live / "marker" ).write_text( "old" )
    vs.swap_in( built[ "dir" ], live )
    assert not built[ "dir" ].exists()
    assert not ( built[ "root" ] / "vectors.old" ).exists()
    assert not ( live / "marker" ).exists()
    assert vs.load_vectors( live ).ids == [ "m.a", "m.b" ]


def test_swap_in_with_no_live_set_just_moves_the_new_one( built ):
    live = built[ "root" ] / "vectors"
    vs.swap_in( built[ "dir" ], live )
    assert vs.load_vectors( live ).ids == [ "m.a", "m.b" ]


def test_swap_in_clears_a_leftover_aside_folder( built ):
    live  = built[ "root" ] / "vectors"
    aside = built[ "root" ] / "vectors.old"
    aside.mkdir()
    ( aside / "junk" ).write_text( "x" )
    vs.swap_in( built[ "dir" ], live )
    assert not aside.exists()


def test_a_failed_second_rename_puts_the_old_set_back( built, monkeypatch ):
    live = built[ "root" ] / "vectors"
    live.mkdir()
    ( live / "marker" ).write_text( "old" )
    real = vs.os.rename

    def flaky( src, dst ):
        if str( src ) == str( built[ "dir" ] ): raise OSError( "disk said no" )
        return real( src, dst )

    monkeypatch.setattr( vs.os, "rename", flaky )
    with pytest.raises( OSError ):
        vs.swap_in( built[ "dir" ], live )
    assert ( live / "marker" ).read_text() == "old"
    assert built[ "dir" ].exists()


def test_a_failed_rename_with_no_old_set_leaves_nothing_live( built, monkeypatch ):
    live = built[ "root" ] / "vectors"

    def always( src, dst ): raise OSError( "disk said no" )

    monkeypatch.setattr( vs.os, "rename", always )
    with pytest.raises( OSError ):
        vs.swap_in( built[ "dir" ], live )
    assert not live.exists()


# ── the engine check ────────────────────────────────────────────────────────


def test_check_engines_passes_when_everything_agrees( built ):
    assert vs.check_engines( built[ "manifest" ], built[ "client" ].info() ) is None


@pytest.mark.parametrize( "kind, field, value", [
    ( "code",  "model",           "other-model" ),
    ( "code",  "revision",        "rev2" ),
    ( "code",  "dtype",           "float32" ),
    ( "code",  "device",          "cuda:1" ),
    ( "code",  "query_prefix",    "Other:" ),
    ( "code",  "document_prefix", "doc:" ),
    ( "code",  "dimensions",      DIM * 2 ),
    ( "prose", "model",           "other-model" ),
    ( "prose", "revision",        "rev2" ),
    ( "prose", "query_prefix",    "q:" ),
    ( "prose", "document_prefix", "d:" )
] )
def test_every_engine_field_difference_is_an_engine_mismatch( built, kind, field, value ):
    info = built[ "client" ].info()
    info[ "engines" ][ kind ][ field ] = value
    with pytest.raises( CandidateError ) as e:
        vs.check_engines( built[ "manifest" ], info )
    assert e.value.code == ENGINE_MISMATCH
    assert f"{kind}.{field}" in e.value.detail


def test_a_different_device_class_is_an_engine_mismatch( built ):
    info = built[ "client" ].info()
    info[ "engines" ][ "device_class" ] = "A100, sm_80"
    with pytest.raises( CandidateError ) as e:
        vs.check_engines( built[ "manifest" ], info )
    assert e.value.code == ENGINE_MISMATCH
    assert "device_class" in e.value.detail


@pytest.mark.parametrize( "key", [ "document_roles", "query_roles" ] )
def test_a_manifest_with_other_roles_is_refused( built, key ):
    m = copy.deepcopy( built[ "manifest" ] )
    m[ key ][ "code" ] = [ "code", "query" if key == "document_roles" else "document" ]
    with pytest.raises( CandidateError ) as e:
        vs.check_engines( m, built[ "client" ].info() )
    assert e.value.code == ENGINE_MISMATCH
    assert key in e.value.detail


@pytest.mark.parametrize( "kind", [ "code", "prose" ] )
def test_a_null_revision_is_engine_not_loaded_and_not_a_match( built, kind ):
    info = built[ "client" ].info()
    info[ "engines" ][ kind ][ "revision" ] = None
    with pytest.raises( CandidateError ) as e:
        vs.check_engines( built[ "manifest" ], info )
    assert e.value.code == ENGINE_NOT_LOADED


# ── the query cache ─────────────────────────────────────────────────────────


def test_query_vectors_on_a_miss_embed_each_pair_once_with_the_manifest_roles( built, tmp_path ):
    client = FakeClient()
    cache  = tmp_path / "qc"
    got    = vs.query_vectors( "find the thing", client, cache, built[ "manifest" ] )
    assert client.calls == [ ( "prose", "query", [ "find the thing" ] ), ( "code", "query", [ "find the thing" ] ) ]
    assert got[ "prose" ] == vec( "prose", "query", "find the thing" )
    assert got[ "code" ] == vec( "code", "query", "find the thing" )
    assert got[ "concat" ] == got[ "prose" ]
    assert client.infos == 1


def test_query_vectors_on_a_hit_make_no_call_at_all( built, tmp_path ):
    cache = tmp_path / "qc"
    vs.query_vectors( "need", FakeClient(), cache, built[ "manifest" ] )
    second = FakeClient()
    got    = vs.query_vectors( "need", second, cache, built[ "manifest" ] )
    assert second.calls == [] and second.infos == 0
    assert got[ "code" ] == vec( "code", "query", "need" )


def test_a_cache_file_of_another_manifest_hash_is_ignored_and_replaced( built, tmp_path ):
    cache = tmp_path / "qc"
    vs.query_vectors( "need", FakeClient(), cache, built[ "manifest" ] )
    other = { **built[ "manifest" ], "manifest_hash": "another" }
    client = FakeClient()
    vs.query_vectors( "need", client, cache, other )
    assert len( client.calls ) == 2
    stored = json.loads( ( cache / f"{vs.query_key( 'need' )}.json" ).read_text() )
    assert stored[ "manifest_hash" ] == "another"


def test_query_vectors_check_the_engines_before_embedding( built, tmp_path ):
    client = FakeClient( engines_block( revision="rev-new" ) )
    with pytest.raises( CandidateError ) as e:
        vs.query_vectors( "need", client, tmp_path / "qc", built[ "manifest" ] )
    assert e.value.code == ENGINE_MISMATCH
    assert client.calls == []
    assert not ( tmp_path / "qc" ).exists()


@pytest.mark.parametrize( "content", [ "{not json", "{}" ] )
def test_a_corrupt_cache_file_is_a_named_error_and_nothing_is_recomputed( built, tmp_path, content ):
    cache = tmp_path / "qc"
    cache.mkdir()
    path = cache / f"{vs.query_key( 'need' )}.json"
    path.write_text( content )
    client = FakeClient()
    with pytest.raises( CandidateError ) as e:
        vs.query_vectors( "need", client, cache, built[ "manifest" ] )
    assert e.value.code == vs.QUERY_CACHE_CORRUPT
    assert path.name in e.value.detail
    assert client.calls == [] and client.infos == 0
    assert path.read_text() == content


def test_query_key_is_the_sha256_of_the_text():
    assert vs.query_key( "abc" ) == hashlib.sha256( b"abc" ).hexdigest()


def test_clear_stale_queries_removes_other_hashes_and_unreadable_files( built, tmp_path ):
    cache = tmp_path / "qc"
    vs.query_vectors( "keep me", FakeClient(), cache, built[ "manifest" ] )
    vs.query_vectors( "drop me", FakeClient(), cache, { **built[ "manifest" ], "manifest_hash": "old" } )
    ( cache / "garbage.json" ).write_text( "not json" )
    ( cache / "nokey.json" ).write_text( "{}" )
    assert vs.clear_stale_queries( cache, built[ "manifest" ][ "manifest_hash" ] ) == 3
    assert [ p.name for p in cache.glob( "*.json" ) ] == [ f"{vs.query_key( 'keep me' )}.json" ]


def test_clear_stale_queries_of_a_missing_folder_is_zero( tmp_path ):
    assert vs.clear_stale_queries( tmp_path / "none", "h" ) == 0


# ── the row-texts sidecar: sealed, checked on load, and a corrupt one is named ──


def test_a_set_made_without_the_sidecar_seals_and_loads_with_no_row_texts( tmp_path ):
    import numpy as np
    out = tmp_path / "old"
    out.mkdir()
    for name in vs.MATRICES: np.zeros( ( 2, DIM ), dtype="<f4" ).tofile( out / vs.MATRIX_FILES[ name ] )
    sealed = vs.seal( out, [ "m.a", "m.b" ], { "dimension": DIM } )
    assert "row_texts.jsonl" not in sealed[ "files" ]
    assert vs.load_vectors( out ).row_texts is None


def test_the_sidecar_names_each_row_text_by_hash_and_loads_in_id_order( built ):
    s = vs.load_vectors( built[ "dir" ] )
    assert s.ids == [ "m.a", "m.b" ]
    assert s.row_texts[ "code" ][ 0 ] == vs.text_hash( "m.py::a()" )
    assert set( s.row_texts ) == set( vs.MATRICES ) and all( len( v ) == 2 for v in s.row_texts.values() )


def test_the_sidecar_hash_is_in_the_manifest_hash_so_any_edit_is_corrupt( built ):
    path = built[ "dir" ] / "row_texts.jsonl"
    path.write_text( path.read_text().replace( "a", "b", 1 ) )
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( built[ "dir" ] )
    assert e.value.code == VECTOR_SET_CORRUPT and "row_texts.jsonl" in e.value.detail


def reseal_with_sidecar( built, text ):
    """Replace the sidecar and reseal, so only the content check can refuse it."""
    ( built[ "dir" ] / "row_texts.jsonl" ).write_text( text )
    manifest = { k: v for k, v in built[ "manifest" ].items() if k not in ( "files", "manifest_hash" ) }
    vs.seal( built[ "dir" ], [ "m.a", "m.b" ], manifest )


GOOD = vs.text_hash( "x" )


@pytest.mark.parametrize( "text, why", [
    ( "{not json\n",                                                                                                     "not JSON lines" ),
    ( '[1, 2]\n[3]\n',                                                                                                  "does not name the ids" ),
    ( json.dumps( { "id": "m.b", "prose": GOOD, "code": GOOD, "concat": GOOD } ) + "\n" +
      json.dumps( { "id": "m.a", "prose": GOOD, "code": GOOD, "concat": GOOD } ) + "\n",                                 "does not name the ids" ),
    ( json.dumps( { "id": "m.a", "prose": GOOD, "code": GOOD, "concat": GOOD } ) + "\n",                                 "does not name the ids" ),
    ( json.dumps( { "id": "m.a", "prose": GOOD, "code": GOOD, "concat": GOOD } ) + "\n" +
      json.dumps( { "id": "m.b", "prose": GOOD, "code": GOOD } ) + "\n",                                                 "bad concat hash" ),
    ( json.dumps( { "id": "m.a", "prose": "xyz", "code": GOOD, "concat": GOOD } ) + "\n" +
      json.dumps( { "id": "m.b", "prose": GOOD, "code": GOOD, "concat": GOOD } ) + "\n",                                 "bad prose hash" ),
    ( json.dumps( { "id": "m.a", "prose": GOOD[ :-1 ], "code": GOOD, "concat": GOOD } ) + "\n" +
      json.dumps( { "id": "m.b", "prose": GOOD, "code": GOOD, "concat": GOOD } ) + "\n",                                 "bad prose hash" ),
    ( json.dumps( { "id": "m.a", "prose": GOOD.upper(), "code": GOOD, "concat": GOOD } ) + "\n" +
      json.dumps( { "id": "m.b", "prose": GOOD, "code": GOOD, "concat": GOOD } ) + "\n",                                 "bad prose hash" ),
] )
def test_a_sidecar_that_hashes_right_but_does_not_match_the_ids_or_holds_a_bad_hash_is_corrupt( built, text, why ):
    reseal_with_sidecar( built, text )
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( built[ "dir" ] )
    assert e.value.code == VECTOR_SET_CORRUPT and why in e.value.detail


def test_a_manifest_that_is_not_json_is_corrupt_not_a_value_error( built ):
    ( built[ "dir" ] / "manifest.json" ).write_text( "{bad" )
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( built[ "dir" ] )
    assert e.value.code == VECTOR_SET_CORRUPT and "not JSON" in e.value.detail


def test_text_hash_is_the_sha256_of_the_utf8_bytes():
    import hashlib
    assert vs.text_hash( "é" ) == hashlib.sha256( "é".encode( "utf-8" ) ).hexdigest()


@pytest.mark.parametrize( "text", [ "{}", "[]", "5", "null", json.dumps( { "manifest_hash": "x" } ),
                                    json.dumps( { "manifest_hash": 1, "files": {}, "dimension": 4 } ),
                                    json.dumps( { "manifest_hash": "x", "files": [], "dimension": 4 } ),
                                    json.dumps( { "manifest_hash": "x", "files": {}, "dimension": "4" } ) ] )
def test_a_manifest_that_is_json_but_not_a_sealed_manifest_is_corrupt_not_a_key_error( built, text ):
    ( built[ "dir" ] / "manifest.json" ).write_text( text )
    with pytest.raises( CandidateError ) as e:
        vs.load_vectors( built[ "dir" ] )
    assert e.value.code == VECTOR_SET_CORRUPT and "not a sealed manifest" in e.value.detail
