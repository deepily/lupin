"""
Row 105ff244: the tier stamp must see a served-bundle rebuild inside a run.

src/lupin_app/static/dist/ is gitignored with 0 tracked files, so `run-span=unmoved` (a HEAD
comparison) and `tracked-dirty` are blind to a rebuild: dist/multiplexer/{accordion-harness,
parity-harness,boot.19ea80639a1e}.js were rewritten at 18:34:51 EDT inside ts-e09fb548's e2e_b
window and two results became unfalsifiable. `bundle-span=` hashes the CONTENT of the served
dist/ tree at start and end and prints a token beside `run-span` when it moves.

Venue: :7999-eligible / local - tmp_path only, read-only git faked by injection, no server.
"""
import os
import subprocess
import sys

import pytest

import cosa.utils.util as cu
from cosa.utils import tree_state as ts

ROOT = cu.get_project_root()


def _dist( root, files ):
    """Create <root>/src/lupin_app/static/dist/<rel> for every ( rel, bytes ) pair."""
    base = os.path.join( str( root ), ts.BUNDLE_REL )
    for rel, data in files.items():
        path = os.path.join( base, rel )
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        with open( path, "wb" ) as f: f.write( data )
    return base


def _git( root, main=None ):
    """A fake git reader for a clean tree at `root`; `main` is the repo's first worktree."""
    answers = {
        ( "rev-parse", "--short", "HEAD" )       : "abc1234",
        ( "rev-parse", "--abbrev-ref", "HEAD" )  : "main",
        ( "rev-parse", "--show-toplevel" )       : str( root ),
        ( "rev-parse", "--abbrev-ref", "@{upstream}" ): "origin/main",
        ( "status", "--porcelain" )              : "",
        ( "rev-list", "--count", "HEAD..origin/main" ): "0",
        ( "rev-list", "--count", "origin/main..HEAD" ): "0",
        ( "worktree", "list", "--porcelain" )    : f"worktree {main or root}\nHEAD abc\nbranch refs/heads/main\n",
    }
    return lambda *args: answers.get( args )


# --- the planted rebuild ---------------------------------------------------------------

def test_a_planted_midrun_rebuild_is_reported( tmp_path ):
    base  = _dist( tmp_path, { "multiplexer/boot.aaaaaaaaaaaa.js": b"old boot", "multiplexer/accordion-harness.js": b"harness" } )
    git   = _git( tmp_path )
    start = ts.capture_start_bundle( git )
    # the rebuild lands MID-RUN: the harness is rewritten and a new content-hashed boot appears
    with open( os.path.join( base, "multiplexer/accordion-harness.js" ), "wb" ) as f: f.write( b"harness v2" )
    with open( os.path.join( base, "multiplexer/boot.bbbbbbbbbbbb.js" ), "wb" ) as f: f.write( b"new boot" )

    line = ts.tree_state_line( git, "abc1234", start )

    assert "BUNDLE REBUILT MID-RUN" in line
    assert f"bundle-span={start}..{ts.bundle_hash( tmp_path )}" in line
    assert " run-span=unmoved" in line                       # the HEAD comparison is exactly what could not see it
    assert line.index( "bundle-span=" ) < line.index( "run-span=" )   # one line, adjacent tokens, bundle first


def test_an_untouched_bundle_says_unmoved( tmp_path ):
    _dist( tmp_path, { "multiplexer/boot.aaaaaaaaaaaa.js": b"boot" } )
    git  = _git( tmp_path )
    line = ts.tree_state_line( git, "abc1234", ts.capture_start_bundle( git ) )
    assert " bundle-span=unmoved" in line and "REBUILT" not in line


def test_it_hashes_content_not_mtime( tmp_path ):
    base = _dist( tmp_path, { "boot.aaaaaaaaaaaa.js": b"same bytes" } )
    path = os.path.join( base, "boot.aaaaaaaaaaaa.js" )
    before = ts.bundle_hash( tmp_path )
    os.utime( path, ( 1_000_000_000, 1_000_000_000 ) )              # new mtime, identical bytes
    assert ts.bundle_hash( tmp_path ) == before
    with open( path, "wb" ) as f: f.write( b"other bytes" )          # new bytes ...
    os.utime( path, ( 1_000_000_000, 1_000_000_000 ) )              # ... under the OLD mtime
    assert ts.bundle_hash( tmp_path ) != before


def test_a_manifest_change_moves_the_hash_even_when_no_js_changed( tmp_path ):
    # manifest.json is the pointer naming which boot.<hash>.js a page loads: a rebuild repoints it
    base   = _dist( tmp_path, { "multiplexer/boot.aaaaaaaaaaaa.js": b"boot", "multiplexer/manifest.json": b'{"boot":"boot.aaaaaaaaaaaa.js"}' } )
    before = ts.bundle_hash( tmp_path )
    with open( os.path.join( base, "multiplexer/manifest.json" ), "wb" ) as f: f.write( b'{"boot":"boot.bbbbbbbbbbbb.js"}' )
    assert ts.bundle_hash( tmp_path ) != before


def test_source_maps_are_not_part_of_the_served_bundle( tmp_path ):
    base   = _dist( tmp_path, { "boot.aaaaaaaaaaaa.js": b"boot", "boot.aaaaaaaaaaaa.js.map": b"map" } )
    before = ts.bundle_hash( tmp_path )
    with open( os.path.join( base, "boot.aaaaaaaaaaaa.js.map" ), "wb" ) as f: f.write( b"changed map" )
    assert ts.bundle_hash( tmp_path ) == before


# --- two builds of one source -------------------------------------------------------------

# Captured 2026-10-08 from two back-to-back runs of build-multiplexer.sh on one tree, 2 s apart: the
# bundle hash moved, and of the five files only manifest.json differed, in the "built" line alone.
BOOT_JS      = b"the minified boot, byte-identical across both builds"
MANIFEST_ONE = b'{\n  "boot.js" : "boot.dd2b044d0b46.js",\n  "hash"    : "dd2b044d0b46",\n  "built"   : "2026-10-08T19:03:23Z"\n}\n'
MANIFEST_TWO = MANIFEST_ONE.replace( b"19:03:23Z", b"19:03:25Z" )


def _build_tree( tmp_path, manifest, extra=None ):
    files = { "multiplexer/boot.dd2b044d0b46.js": BOOT_JS, "multiplexer/manifest.json": manifest }
    files.update( extra or { } )
    return _dist( tmp_path, files )


def _rewrite( base, rel, data ):
    with open( os.path.join( base, rel ), "wb" ) as f: f.write( data )


def test_two_builds_of_one_source_that_differ_only_in_the_build_time_hash_alike( tmp_path ):
    base   = _build_tree( tmp_path, MANIFEST_ONE )
    before = ts.bundle_hash( tmp_path )
    _rewrite( base, "multiplexer/manifest.json", MANIFEST_TWO )
    assert MANIFEST_ONE != MANIFEST_TWO, "the pair no longer differs, so the equality below proves nothing"
    assert ts.bundle_hash( tmp_path ) == before


def test_the_stamp_reads_unmoved_across_such_a_rebuild( tmp_path ):
    base  = _build_tree( tmp_path, MANIFEST_ONE )
    git   = _git( tmp_path )
    start = ts.capture_start_bundle( git )
    _rewrite( base, "multiplexer/manifest.json", MANIFEST_TWO )
    line  = ts.tree_state_line( git, "abc1234", start )
    assert "bundle-span=unmoved" in line and "REBUILT" not in line


def test_a_changed_pointer_still_moves_the_hash_when_the_build_time_changes_too( tmp_path ):
    base   = _build_tree( tmp_path, MANIFEST_ONE )
    before = ts.bundle_hash( tmp_path )
    _rewrite( base, "multiplexer/manifest.json", MANIFEST_TWO.replace( b"dd2b044d0b46.js", b"eeeeeeeeeeee.js" ) )
    assert ts.bundle_hash( tmp_path ) != before


def test_a_changed_hash_field_moves_the_hash( tmp_path ):
    base   = _build_tree( tmp_path, MANIFEST_ONE )
    before = ts.bundle_hash( tmp_path )
    _rewrite( base, "multiplexer/manifest.json", MANIFEST_ONE.replace( b'"hash"    : "dd2b044d0b46"', b'"hash"    : "ffffffffffff"' ) )
    assert ts.bundle_hash( tmp_path ) != before


def test_a_changed_script_still_moves_the_hash_under_an_unchanged_manifest( tmp_path ):
    base   = _build_tree( tmp_path, MANIFEST_ONE )
    before = ts.bundle_hash( tmp_path )
    _rewrite( base, "multiplexer/boot.dd2b044d0b46.js", BOOT_JS + b" changed" )
    assert ts.bundle_hash( tmp_path ) != before


@pytest.mark.parametrize( "first,second", [ ( b"{not json", b"{not json!" ), ( b'["built", 1]', b'["built", 2]' ) ] )
def test_a_manifest_that_is_not_a_json_object_is_hashed_as_it_is( tmp_path, first, second ):
    base   = _build_tree( tmp_path, first )
    before = ts.bundle_hash( tmp_path )
    _rewrite( base, "multiplexer/manifest.json", second )
    assert ts.bundle_hash( tmp_path ) != before


def test_only_manifest_json_loses_its_build_time( tmp_path ):
    other  = b'{"built": "2026-10-08T19:03:23Z"}'
    base   = _build_tree( tmp_path, MANIFEST_ONE, { "multiplexer/other.json": other } )
    before = ts.bundle_hash( tmp_path )
    _rewrite( base, "multiplexer/other.json", other.replace( b"19:03:23Z", b"19:03:25Z" ) )
    assert ts.bundle_hash( tmp_path ) != before


def test_the_order_of_a_manifests_keys_does_not_move_the_hash( tmp_path ):
    base   = _build_tree( tmp_path, b'{"boot.js": "boot.x.js", "hash": "x", "built": "t"}' )
    before = ts.bundle_hash( tmp_path )
    _rewrite( base, "multiplexer/manifest.json", b'{"hash": "x", "built": "t2", "boot.js": "boot.x.js"}' )
    assert ts.bundle_hash( tmp_path ) == before


# --- the other values --------------------------------------------------------------------

def test_no_dist_directory_is_named_none_not_omitted( tmp_path ):
    git  = _git( tmp_path )
    start = ts.capture_start_bundle( git )
    assert start == ts.BUNDLE_NONE
    assert " bundle=none@main bundle-span=unmoved" in ts.tree_state_line( git, "abc1234", start )


def test_an_unreadable_dist_is_UNKNOWN_never_a_silent_pass( tmp_path, monkeypatch ):
    _dist( tmp_path, { "boot.aaaaaaaaaaaa.js": b"boot" } )
    real_open = open
    def deny( path, *a, **k ):
        if str( path ).endswith( ".js" ): raise PermissionError( 13, "denied" )
        return real_open( path, *a, **k )
    monkeypatch.setattr( "builtins.open", deny )
    assert ts.bundle_hash( tmp_path ) == ts.BUNDLE_UNKNOWN


def test_an_unreadable_START_is_reported_as_unknown_not_unmoved( tmp_path ):
    _dist( tmp_path, { "boot.aaaaaaaaaaaa.js": b"boot" } )
    line = ts.tree_state_line( _git( tmp_path ), "abc1234", ts.BUNDLE_UNKNOWN )
    assert "bundle-span=UNKNOWN" in line and "unmoved" not in line.split( "bundle-span=" )[ 1 ].split( " run-span" )[ 0 ]


def test_a_start_that_could_not_find_the_root_is_UNKNOWN( ):
    assert ts.capture_start_bundle( lambda *a: None ) == ts.BUNDLE_UNKNOWN


def test_no_start_captured_adds_no_token_like_run_span( tmp_path ):
    _dist( tmp_path, { "boot.aaaaaaaaaaaa.js": b"boot" } )
    assert "bundle" not in ts.tree_state_line( _git( tmp_path ), "abc1234" )                # the node runners: no span to describe


def test_an_unknown_toplevel_makes_the_bundle_UNKNOWN( tmp_path ):
    git  = _git( tmp_path )
    blind = lambda *a: None if a == ( "rev-parse", "--show-toplevel" ) else git( *a )
    line = ts.tree_state_line( blind, "abc1234", "deadbeef0000" )
    assert "bundle=UNKNOWN@?" in line


# --- which root was hashed -----------------------------------------------------------------

def test_the_stamp_names_whether_it_hashed_the_seat_or_main( tmp_path ):
    seat = tmp_path / "seat"; main = tmp_path / "main"
    seat.mkdir(); main.mkdir()
    assert "bundle=none@seat" in ts.tree_state_line( _git( seat, main=main ), "abc1234", ts.BUNDLE_NONE )
    assert "bundle=none@main" in ts.tree_state_line( _git( main, main=main ), "abc1234", ts.BUNDLE_NONE )


def test_an_unreadable_worktree_list_names_the_root_as_question_mark( tmp_path ):
    git  = _git( tmp_path )
    blind = lambda *a: None if a[ :2 ] == ( "worktree", "list" ) else git( *a )
    assert "bundle=none@?" in ts.tree_state_line( blind, "abc1234", ts.BUNDLE_NONE )


# --- the real session ------------------------------------------------------------------------

def test_a_real_pytest_session_prints_the_bundle_token( ):
    # a REAL session through the REAL src/conftest.py, over one cheap test of THIS file (selected by -k,
    # so it cannot select itself): the summary line must carry both bundle tokens
    env = { **os.environ, "PYTHONPATH": ROOT + "/src", "LUPIN_ROOT": ROOT }
    proc = subprocess.run( [ sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             os.path.abspath( __file__ ), "-k", "test_a_start_that_could_not_find_the_root" ],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=120 )
    line = next( ( l for l in proc.stdout.splitlines() if l.startswith( "[tree-state]" ) ), "" )
    assert " bundle=" in line and " bundle-span=unmoved" in line, proc.stdout + proc.stderr
