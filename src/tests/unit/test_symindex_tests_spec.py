"""
Unit tests for the tests spec: roots, own generation, a main build that holds still.
"""
import json
import pathlib

from cosa.repo.symindex import build as bd
from cosa.repo.symindex import spec as sp
from tests.unit.symindex_helpers import make_lupin_repo, make_repo

GOLDEN = pathlib.Path( __file__ ).resolve().parent.parent / "fixtures" / "symindex_build_golden"
HELPER = 'def helper_for_tests( x ):\n    """Help a test."""\n    return x\n'


def with_tests( root ):
    """Add a Python helper under src/tests/unit of a lupin fixture tree and return its path."""
    unit = root / "src" / "tests" / "unit"
    unit.mkdir( parents=True )
    ( unit / "support.py" ).write_text( HELPER, encoding="utf-8" )
    return unit / "support.py"


def test_the_tests_spec_of_a_lupin_tree_reads_the_existing_test_roots_and_publishes_scope_test( tmp_path ):
    root = make_lupin_repo( tmp_path )
    assert sp.tests_spec( root ).py_roots == ()                                      # neither folder exists yet: nothing is read, nothing is invented
    with_tests( root )
    ( root / "src" / "cosa" / "tests" ).mkdir()
    spec = sp.tests_spec( root )
    assert [ p.relative_to( root.resolve() ).as_posix() for p in spec.py_roots ] == [ "src/tests", "src/cosa/tests" ] and spec.js_roots == spec.py_roots       # the literal pair, not the constant
    assert spec.scopes == ( "test", ) and spec.module_base == root.resolve() / "src" and spec.dart_roots == ()
    assert "tests" not in spec.skip_parts and spec.skip_parts == sp.SKIP_PARTS - { "tests" }
    assert sp.spec_for( root ).scopes is None and "tests" in sp.spec_for( root ).skip_parts       # the main spec keeps skipping tests


def test_the_tests_spec_of_another_tree_reads_a_tests_directory_when_it_has_one_and_nothing_otherwise( tmp_path ):
    plain = make_repo( tmp_path )
    assert sp.tests_spec( plain ).py_roots == ()                                      # pkg/tests is not a root of the tests spec
    ( plain / "tests" ).mkdir()
    ( plain / "src" / "tests" ).mkdir( parents=True )
    spec = sp.tests_spec( plain )
    assert [ p.relative_to( plain.resolve() ).as_posix() for p in spec.py_roots ] == [ "tests", "src/tests" ] and spec.module_base == plain.resolve()


def test_the_tests_generation_holds_test_records_under_its_own_folder_and_the_main_one_holds_none( tmp_path ):
    root = make_lupin_repo( tmp_path )
    with_tests( root )
    main  = bd.build( root, tmp_path / "out" )
    tests = bd.build( root, tmp_path / "out" / "tests", sp.tests_spec( root ) )
    assert main[ "gen_dir" ].parent == tmp_path / "out" and tests[ "gen_dir" ].parent == tmp_path / "out" / "tests"
    ids = lambda gen, t: [ r[ "id" ] for r in bd.read_searchable( gen, tests=t ) ]
    assert "tests.unit.support.helper_for_tests" not in ids( main[ "gen_dir" ], True )
    assert ids( tests[ "gen_dir" ], True ) == [ "tests.unit.support.helper_for_tests" ]
    assert { r[ "scope" ] for r in bd.read_symbols( tests[ "gen_dir" ], all_symbols=True ) } == { "test" }
    assert tests[ "header" ][ "search_sha" ] != main[ "header" ][ "search_sha" ] and tests[ "header" ][ "counts" ][ "searchable" ] == 1


def test_a_test_edit_leaves_the_main_hashes_alone_and_moves_the_tests_hash( tmp_path ):
    root   = make_lupin_repo( tmp_path )
    helper = with_tests( root )
    before = bd.build( root, tmp_path / "o1" )[ "header" ]
    t_one  = bd.build( root, tmp_path / "t1", sp.tests_spec( root ) )[ "header" ]
    helper.write_text( HELPER.replace( "Help a test.", "Help another test." ), encoding="utf-8" )
    after  = bd.build( root, tmp_path / "o2" )[ "header" ]
    t_two  = bd.build( root, tmp_path / "t2", sp.tests_spec( root ) )[ "header" ]
    assert ( before[ "symbols_sha" ], before[ "search_sha" ] ) == ( after[ "symbols_sha" ], after[ "search_sha" ] ) and before[ "manifest" ] == after[ "manifest" ]
    assert t_one[ "search_sha" ] != t_two[ "search_sha" ] and t_one[ "manifest" ] != t_two[ "manifest" ]


def test_ensure_with_the_tests_spec_rebuilds_when_a_test_file_changes_and_not_otherwise( tmp_path ):
    root   = make_lupin_repo( tmp_path )
    helper = with_tests( root )
    spec   = sp.tests_spec( root )
    out    = tmp_path / "out" / "tests"
    first  = bd.ensure( root, out, spec )
    assert bd.ensure( root, out, spec ) == first and bd.is_fresh( spec, out )          # nothing moved: the same generation, not a rebuild
    helper.write_text( HELPER + "\n\ndef second_helper():\n    return 2\n", encoding="utf-8" )
    assert not bd.is_fresh( spec, out )
    second = bd.ensure( root, out, spec )
    assert second != first and "tests.unit.support.second_helper" in [ r[ "id" ] for r in bd.read_searchable( second, tests=True ) ]


def test_ensure_and_build_without_a_spec_use_the_repositorys_own_spec( tmp_path ):
    root = make_lupin_repo( tmp_path )
    gen  = bd.ensure( root, tmp_path / "out" )
    assert bd.ensure( root, tmp_path / "out" ) == gen and bd.read_header( gen )[ "repo" ] == "lupin"


def test_a_build_with_no_spec_writes_the_bytes_it_wrote_before_the_change( tmp_path ):
    # The golden was captured from the code at d31b9d11f, the last commit before the spec argument (the plan names d0bd4f604,
    # but 2cd5ec759 changed the output after it). Red when the no-spec path writes anything different.
    gen = bd.build( make_repo( tmp_path ), tmp_path / "out" )[ "gen_dir" ]
    for name in ( "symbols.md", "routes.md", "symbols.jsonl", "symbols-all.jsonl" ):
        assert ( gen / name ).read_bytes() == ( GOLDEN / name ).read_bytes(), name
    head = bd.read_header( gen )
    for key in ( "manifest", "pin_algorithm", "index_root" ): head.pop( key )
    assert head.pop( "skipped_files" ) == { "node_modules": 1, "tests": 1 }          # the one key 1.7 added: pkg/tests/test_skip.py and node_modules/dep/x.js
    assert head == json.loads( ( GOLDEN / "header-content.json" ).read_text( encoding="utf-8" ) )
