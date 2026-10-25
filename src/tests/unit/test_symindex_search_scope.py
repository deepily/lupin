"""
Unit tests for the searchable listing: scope, end_line, search_sha and script suffixes.
"""
import json
import pathlib
import subprocess

import pytest

from cosa.repo.symindex import build as bd
from cosa.repo.symindex import extractor_contract as ec
from cosa.repo.symindex import spec as sp
from tests.unit.symindex_helpers import make_repo

REPO_ROOT = sp.git_toplevel( pathlib.Path( __file__ ).resolve().parent )


@pytest.fixture( autouse=True )
def _typescript_lookup( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )


def _rec( **kw ):
    base = { "id": "r:m.f", "pin": "p1", "sig": "()", "doc": "First line.", "file": "pkg/m.py", "name": "f", "public": True }
    return { **base, **kw }


def test_script_suffixes_cover_every_script_kind_and_map_to_a_language():
    assert sp.SCRIPT_SUFFIXES == ( ".js", ".mjs", ".cjs", ".ts", ".tsx" )
    assert { s: sp.SUFFIX_LANG[ s ] for s in sp.SCRIPT_SUFFIXES } == { s: "ts" for s in sp.SCRIPT_SUFFIXES }
    assert sp.SUFFIX_LANG[ ".py" ] == "py" and sp.SUFFIX_LANG[ ".dart" ] == "dart"


def test_is_test_path_matches_a_tests_directory_and_never_the_file_name():
    assert sp.is_test_path( "src/tests/unit/x.py" ) is True
    assert sp.is_test_path( "tests/x.py" ) is True
    assert sp.is_test_path( "src/cosa/tests.py" ) is False
    assert sp.is_test_path( "src/cosa/tests" ) is False                            # the last part is the file name, never a directory
    assert sp.is_test_path( "src/cosa/x.py" ) is False


def test_all_files_and_environment_see_an_mjs_file( tmp_path ):
    root = make_repo( tmp_path )
    ( root / "web" / "tool.mjs" ).write_text( "export function tool() { return 1; }\n", encoding="utf-8" )
    spec = sp.spec_for( root )
    assert "tool.mjs" in [ p.name for p in sp.all_files( spec ) ]
    for p in ( root / "web" ).iterdir():
        if p.suffix != ".mjs": p.unlink()
    assert any( a.startswith( "ts" ) for a in bd.environment( spec )[ 0 ].split( "/" ) )   # an only-.mjs tree still asks for typescript


def test_scope_of_has_four_branches():
    assert bd.scope_of( _rec( file="src/tests/unit/x.py", public=True ) ) == "test"
    assert bd.scope_of( _rec( public=True ) ) == "public"
    assert bd.scope_of( _rec( public=False, name="f.<locals>.g" ) ) == "nested"
    assert bd.scope_of( _rec( public=False, name="_f" ) ) == "private"


def test_judge_doc_prefers_the_whole_docstring():
    assert bd.judge_doc( _rec( doc_full="First line.\n\nMore." ) ) == "First line.\n\nMore."
    assert bd.judge_doc( _rec() ) == "First line."


def test_search_sha_is_order_independent_and_moves_with_each_field():
    a, b = _rec(), _rec( id="r:m.g", name="g" )
    sha  = bd.search_sha( [ a, b ] )
    assert len( sha ) == 40 and sha == bd.search_sha( [ b, a ] )
    for change in ( { "pin": "p2" }, { "sig": "( x )" }, { "doc": "Other." }, { "doc_full": "Other." } ):
        assert bd.search_sha( [ { **a, **change }, b ] ) != sha, change


def test_every_record_carries_a_scope_and_python_records_an_end_line( tmp_path ):
    res  = bd.build( make_repo( tmp_path ), tmp_path / "out" )
    recs = bd.read_symbols( res[ "gen_dir" ], all_symbols=True )
    assert recs and all( r[ "scope" ] in ( "public", "private", "nested", "test" ) for r in recs )
    by_name = { r[ "name" ]: r for r in recs if r[ "lang" ] == "py" }
    assert by_name[ "public_fn" ][ "scope" ] == "public"
    assert by_name[ "_private_fn" ][ "scope" ] == "private"
    assert by_name[ "_private_fn.<locals>.nested_helper" ][ "scope" ] == "nested"
    assert by_name[ "public_fn" ][ "end_line" ] > by_name[ "public_fn" ][ "line" ]


def test_the_header_counts_the_searchable_records_and_holds_search_sha( tmp_path ):
    res   = bd.build( make_repo( tmp_path ), tmp_path / "out" )
    gen   = res[ "gen_dir" ]
    head  = bd.read_header( gen )
    found = bd.read_searchable( gen )
    assert head[ "counts" ][ "searchable" ] == len( found ) > head[ "counts" ][ "symbols" ]
    assert head[ "counts" ][ "searchable" ] < head[ "counts" ][ "all" ]
    assert head[ "search_sha" ] == bd.search_sha( found )


def test_read_searchable_returns_public_and_private_never_nested_and_tests_only_on_request( tmp_path ):
    gen = bd.build( make_repo( tmp_path ), tmp_path / "out" )[ "gen_dir" ]
    assert { r[ "scope" ] for r in bd.read_searchable( gen ) } == { "public", "private" }
    assert not any( "<locals>" in r[ "name" ] for r in bd.read_searchable( gen, tests=True ) )
    rows = bd.read_symbols( gen, all_symbols=True ) + [ _rec( file="src/tests/x.py", scope="test", id="r:t.f" ) ]
    ( gen / "symbols-all.jsonl" ).write_text( bd._jsonl( rows ), encoding="utf-8" )
    assert "test" not in { r[ "scope" ] for r in bd.read_searchable( gen ) }
    assert "test" in { r[ "scope" ] for r in bd.read_searchable( gen, tests=True ) }


def test_searchable_jsonl_is_the_listing_as_jsonl_text( tmp_path ):
    gen  = bd.build( make_repo( tmp_path ), tmp_path / "out" )[ "gen_dir" ]
    text = bd.searchable_jsonl( gen )
    assert [ json.loads( l ) for l in text.splitlines() ] == bd.read_searchable( gen )
    rows = bd.read_symbols( gen, all_symbols=True ) + [ _rec( file="src/tests/x.py", scope="test", id="r:t.f" ) ]
    ( gen / "symbols-all.jsonl" ).write_text( bd._jsonl( rows ), encoding="utf-8" )
    assert "r:t.f" not in bd.searchable_jsonl( gen ) and "r:t.f" in bd.searchable_jsonl( gen, tests=True )


def test_a_changed_private_method_moves_search_sha_while_the_public_listing_does_not( tmp_path ):
    root = make_repo( tmp_path )
    one  = bd.build( root, tmp_path / "o1" )[ "header" ]
    src  = root / "pkg" / "util.py"
    src.write_text( src.read_text( encoding="utf-8" ).replace( "def method( self ):\n        return 1", "def method( self ):\n        return 2" ), encoding="utf-8" )
    two  = bd.build( root, tmp_path / "o2" )[ "header" ]
    assert one[ "symbols_sha" ] == two[ "symbols_sha" ]
    assert one[ "search_sha" ] != two[ "search_sha" ]


def test_validate_record_accepts_optional_keys_and_refuses_builder_keys():
    good = { "lang": "py", "file": "a", "name": "A", "kind": "class", "sig": "", "doc": "", "line": 1, "public": True, "pin": "0123456789" }
    assert ec.validate_record( { **good, "end_line": 4, "doc_full": "Whole." } ) is None
    with pytest.raises( ValueError, match="end_line must be a int" ): ec.validate_record( { **good, "end_line": "4" } )
    with pytest.raises( ValueError, match="end_line must be a int" ): ec.validate_record( { **good, "end_line": True } )
    with pytest.raises( ValueError, match="doc_full must be a str" ): ec.validate_record( { **good, "doc_full": 3 } )
    with pytest.raises( ValueError, match="scope is computed" ): ec.validate_record( { **good, "scope": "public" } )
    with pytest.raises( ValueError, match="id is computed" ): ec.validate_record( { **good, "id": "x" } )


def _git_files( pattern ):
    out = subprocess.run( [ "git", "grep", "-n", "-F", pattern, "--", "src" ], cwd=REPO_ROOT, capture_output=True, text=True, check=False )
    return [ l for l in out.stdout.splitlines() if l.split( ":", 1 )[ 0 ].endswith( ".py" ) ]


ALLOWED_READ_SYMBOLS = ( "src/cosa/repo/symindex/build.py", "src/cosa/repo/symindex/wiki_lint.py", "src/cosa/repo/symindex/diff.py" )


ID_LOOKUP_READERS = ( "src/lupin_mcp/reuse_tools.py", )     # the fetch_similar entry lookup


def _stray_calls( lines ):
    keep = []
    for l in lines:
        path, _, rest = l.split( ":", 2 )
        if path.startswith( "src/tests/" ) or path in ALLOWED_READ_SYMBOLS: continue
        if "def read_symbols" in rest or "read_searchable" in rest: continue
        if "all_symbols=True" in rest and path in ID_LOOKUP_READERS: continue                   # an id lookup among every definition, not a search
        keep.append( l )
    return keep


def test_every_read_symbols_call_in_src_is_an_allowed_one():
    lines = _git_files( "read_symbols(" )
    assert any( "build.py" in l for l in lines )                                        # the instrument finds the definition
    assert _stray_calls( lines ) == [], "a search reads read_searchable, not read_symbols"


def test_the_census_goes_red_for_a_stray_caller():
    stray = "src/cosa/somewhere.py:12:    recs = bd.read_symbols( gen )"
    assert _stray_calls( [ stray ] ) == [ stray ]


END_LINE_SOURCE = '''def one(): return 1


def multi( a,
           b ):
    x = a + b
    return x
    # a trailing comment is not part of the definition


@decorator
def decorated():
    """Doc
    over lines."""


class K:
    def m( self ):
        return 1

    def n( self ): pass
'''


def test_end_line_is_the_exact_last_line_of_each_python_definition( tmp_path ):
    # red when: end_line is off by one either way, or is the start line (the 24 October mutation arms)
    root = make_repo( tmp_path )
    ( root / "pkg" / "spans.py" ).write_text( END_LINE_SOURCE, encoding="utf-8" )
    from cosa.repo.symindex import py_index as pi
    got = { r[ "name" ]: ( r[ "line" ], r[ "end_line" ] ) for r in pi.extract_python( sp.spec_for( root ), root / "pkg" / "spans.py", include_all=True ) }
    assert got == { "one": ( 1, 1 ), "multi": ( 4, 7 ), "decorated": ( 12, 14 ), "K": ( 17, 21 ), "K.m": ( 18, 19 ), "K.n": ( 21, 21 ) }


def test_the_fixture_tree_shows_each_kind_of_member_in_its_scope( tmp_path ):
    gen      = bd.build( make_repo( tmp_path ), tmp_path / "out" )[ "gen_dir" ]
    found    = { ( r[ "lang" ], r[ "name" ] ): r[ "scope" ] for r in bd.read_searchable( gen ) }
    public   = { ( r[ "lang" ], r[ "name" ] ) for r in bd.read_symbols( gen ) }
    hidden   = [ ( "py", "Widget._hidden" ), ( "py", "_private_fn" ), ( "ts", "Box.hidden" ), ( "ts", "Box.#secret" ) ]
    assert all( found[ k ] == "private" for k in hidden )                                       # searchable, class named in the name
    assert not any( k in public for k in hidden )                                               # and still not in the public listing
    assert ( "ts", "Box.get" ) in public and found[ ( "ts", "Box.get" ) ] == "public"
    assert not any( "<locals>" in name for _, name in found )                                   # a nested helper is never searchable
    assert ( "py", "_private_fn.<locals>.nested_helper" ) in { ( r[ "lang" ], r[ "name" ] ) for r in bd.read_symbols( gen, all_symbols=True ) }      # positive control: it is in the full listing
