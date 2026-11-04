"""
The frozen copy of the index and vector set, and the refusal of a differing run.

The index and the build info come from the real producers (needset_freeze_helpers), so the hashes are the real ones.
"""
import json
import os
import stat

import pytest

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates import freshness as fr
from lupin_mcp.reuse_needset import freeze, run
from lupin_mcp.reuse_needset import errors as er
from tests.unit.needset_freeze_helpers import built_pair
from tests.unit.test_reuse_needset_run import make_env, table


def code_of( call ):
    """Return the NeedsetError code a call raises."""
    with pytest.raises( er.NeedsetError ) as e: call()
    return e.value.code


def test_the_identity_reads_the_header_and_the_build_info_of_the_real_producers( tmp_path ):
    gen, vec = built_pair( tmp_path )
    got      = freeze.identity( gen, vec )
    header   = sx_build.read_header( gen )
    assert set( got ) == set( freeze.IDENTITY_KEYS )
    assert got[ "symbols_sha" ] == header[ "symbols_sha" ] and got[ "index_manifest" ] == fr.index_manifest( header ) == fr.read_build_info( vec )[ "index_manifest" ]
    assert got[ "vector_build_info_sha" ] == __import__( "hashlib" ).sha256( ( vec / "build-info.json" ).read_bytes() ).hexdigest()


def test_the_same_tree_built_later_changes_only_the_vector_hash_and_another_tree_changes_the_index_hashes( tmp_path ):
    first = freeze.identity( *built_pair( tmp_path, "one" ) )
    later = freeze.identity( *built_pair( tmp_path, "two", built_at="2026-10-26T12:00:00+00:00" ) )
    other = freeze.identity( *built_pair( tmp_path, "three", extra_source="def added_later():\n    return 1\n" ) )
    assert later[ "symbols_sha" ] == first[ "symbols_sha" ] and later[ "vector_build_info_sha" ] != first[ "vector_build_info_sha" ]
    assert other[ "symbols_sha" ] != first[ "symbols_sha" ] and other[ "index_manifest" ] != first[ "index_manifest" ]


def test_an_unreadable_header_or_build_info_and_a_set_from_another_index_are_named( tmp_path ):
    gen, vec = built_pair( tmp_path, "ok" )
    empty    = tmp_path / "empty"
    empty.mkdir()
    assert code_of( lambda: freeze.identity( empty, vec ) ) == er.FREEZE_INCOMPLETE
    assert code_of( lambda: freeze.identity( gen, empty ) ) == er.FREEZE_INCOMPLETE
    other_gen, _ = built_pair( tmp_path, "other", extra_source="def added_later():\n    return 1\n" )
    assert code_of( lambda: freeze.identity( other_gen, vec ) ) == er.VECTORS_NOT_FROM_INDEX


def test_the_freeze_writes_a_read_only_copy_with_the_same_identity( tmp_path ):
    gen, vec = built_pair( tmp_path )
    dest     = tmp_path / "out" / "frozen"
    got      = freeze.freeze( gen, vec, dest )
    assert got == freeze.identity( gen, vec ) == json.loads( ( dest / freeze.IDENTITY_FILE ).read_text() )
    files = [ os.path.join( r, f ) for r, _, fs in os.walk( dest ) for f in fs ]
    dirs  = [ r for r, _, _ in os.walk( dest ) ]
    assert files and all( stat.S_IMODE( os.stat( f ).st_mode ) == 0o444 for f in files ) and all( stat.S_IMODE( os.stat( d ).st_mode ) == 0o555 for d in dirs )
    with pytest.raises( PermissionError ): ( dest / freeze.VECTOR_SUBDIR / "build-info.json" ).write_text( "x" )
    for r, _, _ in os.walk( dest ): os.chmod( r, 0o755 )          # so pytest can clean up


def test_a_second_freeze_of_the_same_source_changes_nothing_and_another_source_is_refused( tmp_path ):
    gen, vec = built_pair( tmp_path )
    dest     = tmp_path / "frozen"
    first    = freeze.freeze( gen, vec, dest )
    stamp    = os.stat( dest / freeze.IDENTITY_FILE ).st_mtime_ns
    assert freeze.freeze( gen, vec, dest ) == first and os.stat( dest / freeze.IDENTITY_FILE ).st_mtime_ns == stamp
    gen2, vec2 = built_pair( tmp_path, "later", built_at="2026-10-26T12:00:00+00:00" )
    assert code_of( lambda: freeze.freeze( gen2, vec2, dest ) ) == er.FROZEN_COPY_EXISTS
    plain = tmp_path / "plain"
    plain.mkdir()
    assert code_of( lambda: freeze.freeze( gen, vec, plain ) ) == er.FROZEN_COPY_EXISTS
    for r, _, _ in os.walk( dest ): os.chmod( r, 0o755 )


def test_a_copy_that_differs_from_its_source_is_refused( tmp_path, monkeypatch ):
    gen, vec = built_pair( tmp_path )
    real     = freeze.identity
    calls    = []
    def drifting( g, v ):
        got = real( g, v )
        calls.append( got )
        return dict( got, symbols_sha="0" * 40 ) if len( calls ) == 2 else got
    monkeypatch.setattr( freeze, "identity", drifting )
    assert code_of( lambda: freeze.freeze( gen, vec, tmp_path / "frozen" ) ) == er.FROZEN_COPY_EXISTS


LIVE = { "index_manifest": "a" * 64, "symbols_sha": "b" * 40, "vector_build_info_sha": "c" * 64 }


@pytest.mark.parametrize( "key, code", [ ( "index_manifest", er.INDEX_DIFFERS ), ( "symbols_sha", er.INDEX_DIFFERS ), ( "vector_build_info_sha", er.VECTORS_DIFFER ) ] )
def test_each_hash_that_differs_is_a_named_refusal_that_names_the_hash( key, code ):
    assert freeze.require_same( dict( LIVE ), dict( LIVE ), "arm" ) is None
    with pytest.raises( er.NeedsetError ) as e: freeze.require_same( dict( LIVE ), dict( LIVE, **{ key: "d" * 64 } ), "arm-x" )
    assert e.value.code == code and key in e.value.detail and "arm-x" in e.value.detail


@pytest.mark.parametrize( "bad", [ None, "", 7 ] )
def test_a_manifest_without_a_frozen_hash_is_incomplete_and_never_equal( bad ):
    manifest = dict( LIVE, symbols_sha=bad )
    assert code_of( lambda: freeze.require_same( manifest, dict( LIVE, symbols_sha=bad ), "arm" ) ) == er.FREEZE_INCOMPLETE
    assert code_of( lambda: freeze.require_same( { k: v for k, v in LIVE.items() if k != "symbols_sha" }, LIVE, "arm" ) ) == er.FREEZE_INCOMPLETE


def test_a_real_run_freezes_before_the_draw_and_a_resume_accepts_the_same_copy( tmp_path ):
    env = make_env( tmp_path )
    out = tmp_path / "leak"
    out.mkdir()
    first = run.run_needset( env, table(), out )
    assert first[ "frozen" ] == first[ "report" ][ "frozen" ] == freeze.identity( *env.freeze_from ) == json.loads( ( out / "frozen" / freeze.IDENTITY_FILE ).read_text() )
    assert run.run_needset( make_env( tmp_path, name="again.jsonl" ), table(), out )[ "frozen" ] == first[ "frozen" ]
    for r, _, _ in os.walk( out / "frozen" ): os.chmod( r, 0o755 )


def test_a_real_run_without_a_source_to_freeze_is_refused_and_a_smoke_run_freezes_nothing( tmp_path ):
    out = tmp_path / "leak"
    out.mkdir()
    assert code_of( lambda: run.run_needset( make_env( tmp_path, freeze_from=None ), table(), out ) ) == er.FREEZE_INCOMPLETE
    assert not ( out / "frozen" ).exists()
    ( tmp_path / "smoke_out" ).mkdir()
    smoke = run.run_needset( make_env( tmp_path, smoke=True, freeze_from=None, name="smoke.jsonl" ), table(), tmp_path / "smoke_out" )
    assert smoke[ "frozen" ] is None and not ( tmp_path / "smoke_out" / "frozen" ).exists()
