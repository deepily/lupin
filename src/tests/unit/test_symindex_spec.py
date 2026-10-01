"""
Unit tests for cosa.repo.symindex.spec: roots, skip rules, file population, manifest.
"""
import os
import pathlib
import time

import pytest

from cosa.repo.symindex import spec as sp
from tests.unit.symindex_helpers import make_repo


def test_skipped_matches_directory_components_only():
    assert sp.skipped( "src/tests/x.py", sp.SKIP_PARTS ) is True
    assert sp.skipped( "src/cosa/x.py", sp.SKIP_PARTS ) is False
    assert sp.skipped( "src/cosa/tests.py", sp.SKIP_PARTS ) is False          # a file NAMED tests.py is not a tests directory
    assert sp.skipped( "web/a.d.ts", sp.SKIP_PARTS ) is True
    assert sp.skipped( "web/a.min.js", sp.SKIP_PARTS ) is True
    assert sp.skipped( "lib/a.g.dart", sp.SKIP_PARTS ) is True


def test_fixture_root_under_a_tests_directory_is_still_indexed( tmp_path ):
    """Positive control for the absolute-path bug: the ROOT sits under tests/, its files must still be seen."""
    root = make_repo( tmp_path / "tests" / "fixtures" )
    spec = sp.spec_for( root )
    names = [ p.relative_to( root ).as_posix() for p in sp.all_files( spec ) ]
    assert "pkg/util.py" in names
    assert "web/app.ts" in names
    assert "pkg/tests/test_skip.py" not in names                                # a tests/ dir INSIDE the root is skipped
    assert not any( n.startswith( "node_modules" ) for n in names )


def test_spec_for_lupin_tree_uses_the_lupin_layout( tmp_path ):
    for d in ( "src/cosa", "src/lupin_mcp", "src/lupin_app/static/js" ): ( tmp_path / d ).mkdir( parents=True )
    spec = sp.spec_for( tmp_path )
    assert sp.is_lupin_tree( tmp_path )
    assert spec.module_base == tmp_path.resolve() / "src"
    assert [ p.name for p in spec.py_roots ] == [ "cosa", "lupin_mcp", "lupin_app" ]
    assert spec.js_roots[ 0 ].as_posix().endswith( "src/lupin_app/static/js" )


def test_spec_for_flutter_tree_indexes_lib_as_dart( tmp_path ):
    ( tmp_path / "lib" / "generated" ).mkdir( parents=True )
    ( tmp_path / "pubspec.yaml" ).write_text( "name: m\n", encoding="utf-8" )
    ( tmp_path / "lib" / "a.dart" ).write_text( "class A {}\n", encoding="utf-8" )
    ( tmp_path / "lib" / "generated" / "b.dart" ).write_text( "class B {}\n", encoding="utf-8" )
    spec = sp.spec_for( tmp_path )
    assert spec.dart_roots and not spec.py_roots
    assert [ p.name for p in sp.all_files( spec ) ] == [ "a.dart" ]


def test_iter_files_deduplicates_overlapping_roots( tmp_path ):
    root = make_repo( tmp_path )
    spec = sp.spec_for( root )
    files = sp.iter_files( spec, [ root, root / "pkg" ], { ".py" } )
    assert len( files ) == len( set( files ) )


def test_manifest_changes_on_add_delete_touch_and_resize( tmp_path ):
    root = make_repo( tmp_path )
    spec = sp.spec_for( root )
    m0   = sp.manifest( spec )
    assert sp.manifest( spec ) == m0
    extra = root / "pkg" / "extra.py"
    extra.write_text( "def e():\n    return 1\n", encoding="utf-8" )
    m1 = sp.manifest( spec )
    assert m1 != m0
    os.utime( extra, ns=( time.time_ns() + 10**9, time.time_ns() + 10**9 ) )
    m2 = sp.manifest( spec )
    assert m2 != m1
    extra.unlink()
    assert sp.manifest( spec ) == m0                                            # a deleted file leaves the original population
    ( root / "pkg" / "tests" / "ignored_edit.py" ).write_text( "x = 1\n", encoding="utf-8" )
    before = sp.manifest( spec )
    ( root / "pkg" / "tests" / "ignored_edit.py" ).write_text( "x = 22222\n", encoding="utf-8" )
    assert sp.manifest( spec ) == before                                        # an edit under tests/ never triggers a rebuild


def test_git_toplevel_finds_this_worktree_and_refuses_a_plain_directory( tmp_path ):
    top = sp.git_toplevel( pathlib.Path( __file__ ).resolve().parent )
    assert ( top / "src" / "cosa" ).is_dir()
    assert sp.git_toplevel().is_dir()                                           # default start: the cwd
    with pytest.raises( sp.NotARepo ): sp.git_toplevel( tmp_path )
