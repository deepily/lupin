"""
Unit tests for the vector set's build info and the build lock.

Venue: :7999-eligible. Nothing here touches a model, the network or the shared data folder.
"""
import json
import re

import pytest

from cosa.repo.symindex.candidates import freshness as fr
from cosa.repo.symindex.candidates.errors import CandidateError, BUILD_LOCK_HELD

HEADER = { "manifest": { "a.py": [ 10, 1 ], "b.py": [ 20, 2 ] }, "symbols_sha": "abc123" }


def test_index_manifest_is_the_sha256_of_the_canonical_manifest_and_ignores_key_order():
    one = fr.index_manifest( HEADER )
    assert re.fullmatch( r"[0-9a-f]{64}", one )
    assert fr.index_manifest( { "manifest": { "b.py": [ 20, 2 ], "a.py": [ 10, 1 ] } } ) == one
    assert fr.index_manifest( { "manifest": { "a.py": [ 10, 1 ], "b.py": [ 20, 3 ] } } ) != one


def test_utc_now_is_an_iso_string_in_utc_to_the_second():
    assert re.fullmatch( r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", fr.utc_now() )


def test_build_info_round_trips_and_names_the_manifest_the_symbols_and_the_time( tmp_path ):
    written = fr.write_build_info( tmp_path, HEADER, "2026-10-15T14:00:00+00:00" )
    assert written == { "index_manifest": fr.index_manifest( HEADER ), "symbols_sha": "abc123", "built_at": "2026-10-15T14:00:00+00:00",
                        "unwritten_pins": [] }
    assert fr.read_build_info( tmp_path ) == written


@pytest.mark.parametrize( "text", [ None, "{not json", "[1]", "5", json.dumps( "index_manifest built_at" ),
                                   json.dumps( { "built_at": "t" } ), json.dumps( { "index_manifest": "m" } ) ] )
def test_build_info_reads_as_none_when_absent_unreadable_or_incomplete( tmp_path, text ):
    if text is not None: ( tmp_path / fr.BUILD_INFO_FILE ).write_text( text )
    assert fr.read_build_info( tmp_path ) is None


def test_the_manifest_reads_without_hashing_and_is_none_for_absent_bad_or_non_object( tmp_path ):
    assert fr.read_manifest( tmp_path ) is None
    ( tmp_path / "manifest.json" ).write_text( "{bad" )
    assert fr.read_manifest( tmp_path ) is None
    ( tmp_path / "manifest.json" ).write_text( "[1]" )
    assert fr.read_manifest( tmp_path ) is None
    ( tmp_path / "manifest.json" ).write_text( json.dumps( { "rows": 2 } ) )
    assert fr.read_manifest( tmp_path ) == { "rows": 2 }


def test_the_lock_is_held_inside_the_block_refused_to_a_second_holder_and_free_after( tmp_path ):
    path = tmp_path / "sub" / fr.LOCK_FILE
    with fr.refresh_lock( path ):
        with pytest.raises( CandidateError ) as held:
            with fr.refresh_lock( path ): pytest.fail( "a second holder got in" )
        assert held.value.code == BUILD_LOCK_HELD and str( path ) in held.value.detail
    with fr.refresh_lock( path ): pass


def test_the_lock_is_released_when_the_block_raises( tmp_path ):
    path = tmp_path / fr.LOCK_FILE
    with pytest.raises( KeyError ):
        with fr.refresh_lock( path ): raise KeyError( "boom" )
    with fr.refresh_lock( path ): pass


HOLDER = """
import sys, time
from cosa.repo.symindex.candidates import freshness as fr
with fr.refresh_lock( sys.argv[ 1 ] ):
    print( "held", flush=True )
    time.sleep( 60 )
"""


def test_the_lock_holds_across_processes_and_a_killed_holder_leaves_no_stale_lock( tmp_path ):
    import subprocess, sys
    path = tmp_path / fr.LOCK_FILE
    proc = subprocess.Popen( [ sys.executable, "-c", HOLDER, str( path ) ], stdout=subprocess.PIPE, text=True )
    try:
        assert proc.stdout.readline().strip() == "held"
        with pytest.raises( CandidateError ):
            with fr.refresh_lock( path ): pass
    finally:
        proc.kill()
        proc.wait()
    with fr.refresh_lock( path ): pass


def test_build_info_keeps_the_unwritten_pins_sorted_and_once_each( tmp_path ):
    pins = [ f"p{n}" for n in range( 9, -1, -1 ) ]
    fr.write_build_info( tmp_path, HEADER, "t", pins + [ "p3" ] )
    assert fr.read_build_info( tmp_path )[ "unwritten_pins" ] == sorted( pins )
    assert fr.read_build_info( tmp_path )[ "unwritten_pins" ][ :3 ] == [ "p0", "p1", "p2" ]
