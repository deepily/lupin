"""
Unit tests for the wider script roots, the skip rules and the purpose lines on records.
"""
import pathlib

from cosa.repo.symindex import build as bd
from cosa.repo.symindex import spec as sp
from tests.unit.symindex_helpers import make_lupin_repo, make_repo


def test_a_lupin_tree_reads_the_widened_script_roots_that_exist( tmp_path ):
    root = make_lupin_repo( tmp_path )
    assert sp.LUPIN_JS_DIRS == ( "src/lupin_app/static/js", "src/scripts", "src/cosa/repo/symindex", "src/conf" )
    assert sp.spec_for( root ).js_roots == ()                                          # none of the four exists in the fixture
    for d in ( "src/scripts", "src/conf" ): ( root / d ).mkdir( parents=True )
    ( root / "src" / "scripts" / "tool.mjs" ).write_text( "export function tool() { return 1; }\n", encoding="utf-8" )
    spec = sp.spec_for( root )
    assert [ p.relative_to( root.resolve() ).as_posix() for p in spec.js_roots ] == [ "src/scripts", "src/conf" ]
    assert "tool.mjs" in [ p.name for p in sp.all_files( spec ) ]


def test_skip_rule_names_the_directory_or_the_suffix_and_skipped_follows_it():
    parts = sp.SKIP_PARTS
    assert sp.skip_rule( "a/node_modules/tests/x.js", parts ) == "node_modules"        # the first directory in path order
    assert sp.skip_rule( "a/tests/x.py", parts ) == "tests"
    assert sp.skip_rule( "a/b/x.d.ts", parts ) == ".d.ts" and sp.skip_rule( "a/b/x.min.js", parts ) == ".min.js"
    assert sp.skip_rule( "a/tests", parts ) is None and sp.skip_rule( "a/b/x.py", parts ) is None      # a file name is never a directory
    assert sp.skipped( "a/tests/x.py", parts ) is True and sp.skipped( "a/b/x.py", parts ) is False


def test_iter_files_reports_each_dropped_file_once_under_its_rule( tmp_path ):
    spec  = sp.spec_for( make_repo( tmp_path ) )
    drops = {}
    kept  = sp.iter_files( spec, [ spec.root, spec.root ], { ".py", ".js" }, drops )      # overlapping roots: still once
    assert drops == { "pkg/tests/test_skip.py": "tests", "node_modules/dep/x.js": "node_modules" }
    assert all( p.name not in ( "test_skip.py", "x.js" ) for p in kept ) and sp.iter_files( spec, [ spec.root ], { ".py" } ) == [ p for p in kept if p.suffix == ".py" ]


def test_the_header_counts_the_skipped_files_per_rule( tmp_path ):
    root = make_repo( tmp_path )
    ( root / "web" / "gen.d.ts" ).write_text( "export declare const x: number;\n", encoding="utf-8" )
    ( root / "pkg" / "tests" / "more.py" ).write_text( "def more():\n    return 1\n", encoding="utf-8" )
    head = bd.build( root, tmp_path / "out" )[ "header" ]
    assert head[ "skipped_files" ] == { ".d.ts": 1, "node_modules": 1, "tests": 2 } and list( head[ "skipped_files" ] ) == sorted( head[ "skipped_files" ] )
    assert bd.collect( sp.spec_for( root ) )[ "skipped_files" ] == head[ "skipped_files" ]


def test_attach_purposes_copies_only_the_records_whose_pin_has_a_line():
    a, b = { "pin": "p1", "id": "a" }, { "pin": "p2", "id": "b" }
    out  = bd.attach_purposes( [ a, b ], { "p1": "does a" } )
    assert out == [ { "pin": "p1", "id": "a", "purpose": "does a" }, b ] and out[ 1 ] is b and "purpose" not in a
    assert [ a, b ] == [ { "pin": "p1", "id": "a" }, { "pin": "p2", "id": "b" } ]           # neither input record was changed in place
    assert bd.attach_purposes( [ a ], None ) == [ a ] and bd.attach_purposes( [ a ], {} ) == [ a ]
    assert bd.attach_purposes( [ a ], None ) is not bd.attach_purposes( [ a ], None )       # a new list each time


def test_searchable_jsonl_carries_the_purpose_when_given( tmp_path ):
    gen = bd.build( make_lupin_repo( tmp_path ), tmp_path / "out" )[ "gen_dir" ]
    one = bd.read_searchable( gen )[ 0 ]
    assert "purpose" not in bd.searchable_jsonl( gen )
    assert '"purpose": "reads feeds"'.replace( ": ", ":" ) in bd.searchable_jsonl( gen, purposes={ one[ "pin" ]: "reads feeds" } ).replace( ": ", ":" )
