"""
Census: every script file is indexed, skipped by a named rule, or listed with a reason.

Requires:
    - git is on the path and the tree is a git checkout

Ensures:
    - a new .js, .mjs, .cjs, .ts or .tsx file outside every index root turns this red until it is listed
    - a listed prefix that matches no tracked file turns it red too, so the list cannot go stale
"""
import subprocess

import cosa.utils.util as cu
from cosa.repo.symindex import spec as sp

NESTED            = ( "src/lupin-plugin-firefox/", )                    # a separate repository, never read from here
UNINDEXED_REASONS = {
    "src/tests/"                                  : "test files: indexed on request by the tests spec, never in the main index",
    "src/rnd/"                                    : "R&D probes and assets: the rnd skip part",
    "src/lupin_app/static/lupin-mobile-test/"     : "generated Flutter web build output, vendored",
    "src/lupin_app/static/html/"                  : "page-local scripts of the admin and auth pages, outside the roots the plan names",
    "src/lupin_mcp/reuse_needset/needset_strip.js": "a compiler script that strip.py runs as a program over stdin and stdout; nothing imports it, so it offers no function to reuse",
}


def tracked_scripts():
    """
    List the tracked script files of the tree.

    Ensures:
        - returns repo-relative paths from git, not from a disk walk
        - nested repositories are left out
    """
    out = subprocess.run( [ "git", "ls-files", "src" ], cwd=cu.get_project_root(), capture_output=True, text=True, check=True ).stdout.split( "\n" )
    return [ p for p in out if p.endswith( sp.SCRIPT_SUFFIXES ) and not p.startswith( NESTED ) ]


def under_a_root( path ):
    """Ensures: returns True when the path lies under one of the LUPIN_JS_DIRS roots."""
    return any( path.startswith( d + "/" ) for d in sp.LUPIN_JS_DIRS )


def unaccounted( paths, reasons ):
    """
    Find the script files nothing accounts for.

    Ensures:
        - a file under a root is accounted for: indexed, or dropped by a named skip rule
        - any other file is accounted for only when a key of `reasons` is a prefix of its path
        - returns the rest, in input order
    """
    return [ p for p in paths if not under_a_root( p ) and not p.startswith( tuple( reasons ) ) ]


def test_every_tracked_script_file_is_indexed_skipped_by_a_rule_or_listed_with_a_reason():
    found = tracked_scripts()
    assert any( under_a_root( p ) and sp.skip_rule( p, sp.SKIP_PARTS ) is None for p in found )     # the instrument finds an indexed file
    assert unaccounted( found, UNINDEXED_REASONS ) == [], "a script file outside every index root: add its root to LUPIN_JS_DIRS or list it in UNINDEXED_REASONS"


def test_every_listed_prefix_matches_a_tracked_file():
    found = tracked_scripts()
    assert [ k for k in UNINDEXED_REASONS if not any( p.startswith( k ) for p in found ) ] == []
    assert all( UNINDEXED_REASONS.values() )


def test_the_census_goes_red_for_a_stray_mjs_in_a_new_folder_and_not_for_one_under_a_root():
    stray = [ "src/newtool/run.mjs", "src/scripts/ok.mjs", "src/tests/unit/a.test.ts", "src/lupin_app/static/js/vendor/x.js" ]
    assert unaccounted( stray, UNINDEXED_REASONS ) == [ "src/newtool/run.mjs" ]
    assert unaccounted( [ "src/newtool/run.mjs" ], reasons={ "src/newtool/": "scratch" } ) == []


def test_tracked_scripts_reads_git_keeps_script_suffixes_and_drops_a_nested_repository( monkeypatch ):
    listing = "src/newtool/run.mjs\nsrc/a.py\nsrc/lupin-plugin-firefox/x.js\nsrc/scripts/ok.cjs\n"
    monkeypatch.setattr( subprocess, "run", lambda *a, **k: subprocess.CompletedProcess( a, 0, stdout=listing ) )
    found = tracked_scripts()
    assert found == [ "src/newtool/run.mjs", "src/scripts/ok.cjs" ] and unaccounted( found, UNINDEXED_REASONS ) == [ "src/newtool/run.mjs" ]       # the stray one, found in a fake tree, is red
