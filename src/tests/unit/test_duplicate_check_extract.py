"""Unit tests for semdup.extract: Python and script definitions, accounts and refusals."""
import ast
import json
import pathlib

import pytest

import cosa.utils.util as cu
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import extract as ex
from cosa.repo.symindex import js_index, py_index
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.errors import DependencyMissing

PY_SOURCE = '''import os


def top( a, /, b, *rest, key=1, **extra ):
    """Doc."""
    total = a + b
    for item in rest:
        total += helper( item )
    with open( key ) as handle:
        data = handle.read().strip()
    try:
        value = ( last := data )
    except ValueError as problem:
        raise
    squares = [ q * q for q in rest ]
    items[ 0 ]()
    factory()()
    return total


class Widget:
    def render( self, mode ):
        def inner( z ):
            return z
        return inner( mode )

    def _hidden( self ):
        return 0

    async def fetch( self ):
        return await self.client.get()

    @property
    def size( self ):
        return 1


def twin():
    return 1
'''


def tree( tmp_path, files ):
    """Write the files under a fresh root and return the root and the absolute paths in order."""
    root = tmp_path / "repo"
    root.mkdir( parents=True )
    paths = []
    for name, text in files.items():
        p = root / name
        p.parent.mkdir( parents=True, exist_ok=True )
        p.write_text( text, encoding="utf-8" )
        paths.append( p )
    return root, paths


def by_name( records ):
    return { r[ "name" ]: r for r in records }


def test_python_records_hold_every_field_and_leave_classes_out(tmp_path):
    root, ( path, ) = tree( tmp_path, { "m.py": PY_SOURCE } )
    records = ex.extract_python( root, path, "new" )
    got = by_name( records )
    assert sorted( got ) == [ "Widget._hidden", "Widget.fetch", "Widget.render", "Widget.render.<locals>.inner", "Widget.size", "top", "twin" ]
    top = got[ "top" ]
    assert ( top[ "origin" ], top[ "lang" ], top[ "file" ], top[ "line" ], top[ "end_line" ], top[ "public" ] ) == ( "new", "py", "m.py", 4, 18, True )
    assert top[ "text" ].startswith( "def top( a, /, b" ) and top[ "text" ].endswith( "return total" )
    assert top[ "nodes" ] == sum( 1 for _ in ast.walk( ast.parse( PY_SOURCE ).body[ 1 ] ) )
    assert top[ "id" ] == ex.definition_id( "new", "m.py", "top", top[ "text" ] )
    assert got[ "Widget._hidden" ][ "public" ] is False and got[ "Widget.render.<locals>.inner" ][ "public" ] is False
    assert got[ "Widget.fetch" ][ "text" ].startswith( "async def fetch" )


def test_the_same_body_has_the_same_text_in_a_class_and_at_the_top_of_a_file(tmp_path):
    body = "( self, x ):\n        y = x + 1\n        return y"
    root, ( path, ) = tree( tmp_path, { "m.py": f"class K:\n    def f{body}\n\n\ndef f( self, x ):\n    y = x + 1\n    return y\n" } )
    got = ex.extract_python( root, path, "new" )
    assert [ r[ "name" ] for r in got ] == [ "K.f", "f" ] and got[ 0 ][ "text" ] == got[ 1 ][ "text" ] == "def f( self, x ):\n    y = x + 1\n    return y"
    assert got[ 0 ][ "id" ] != got[ 1 ][ "id" ]                                                    # the file and name still tell them apart only through the id's other fields


def test_a_line_inside_a_multi_line_string_that_does_not_start_with_the_indent_is_left_alone(tmp_path):
    src = 'class K:\n    def f( self ):\n        return """\nraw at column zero\n    """\n'
    root, ( path, ) = tree( tmp_path, { "m.py": src } )
    assert ex.extract_python( root, path, "new" )[ 0 ][ "text" ] == 'def f( self ):\n    return """\nraw at column zero\n"""'


def test_the_python_signature_is_the_one_py_index_builds(tmp_path):
    root, ( path, ) = tree( tmp_path, { "m.py": PY_SOURCE } )
    theirs = { r[ "name" ]: r[ "sig" ] for r in py_index.extract_python( sp.spec_for( root ), path, include_all=True ) if r[ "kind" ] != "class" }
    assert { r[ "name" ]: r[ "sig" ] for r in ex.extract_python( root, path, "new" ) } == theirs
    assert theirs[ "top" ] == "(a, /, b, *rest, key=1, **extra)"


def test_python_calls_are_the_distinct_called_names_and_skip_unnamed_calls(tmp_path):
    root, ( path, ) = tree( tmp_path, { "m.py": PY_SOURCE } )
    got = by_name( ex.extract_python( root, path, "new" ) )
    assert got[ "top" ][ "calls" ] == [ "helper", "open", "strip", "factory", "read" ]            # ast.walk order; items[ 0 ]() and factory()() add no name of their own
    assert got[ "Widget.fetch" ][ "calls" ] == [ "get" ]
    assert got[ "twin" ][ "calls" ] == []


def test_python_calls_stop_at_fifty_names(tmp_path):
    body = "\n".join( f"    c{i}()" for i in range( 60 ) )
    root, ( path, ) = tree( tmp_path, { "many.py": f"def many():\n{body}\n" } )
    calls = ex.extract_python( root, path, "new" )[ 0 ][ "calls" ]
    assert len( calls ) == 50 and set( calls ) <= { f"c{i}" for i in range( 60 ) }


def test_python_declared_holds_parameters_assigned_loop_with_walrus_and_except_names_once(tmp_path):
    root, ( path, ) = tree( tmp_path, { "m.py": PY_SOURCE } )
    got = by_name( ex.extract_python( root, path, "new" ) )
    assert got[ "top" ][ "declared" ] == [ "a", "b", "rest", "key", "extra", "total", "item", "problem", "squares", "handle", "data", "value", "last", "q" ]
    assert "top" not in got[ "top" ][ "declared" ]
    assert got[ "Widget.render" ][ "declared" ] == [ "self", "mode", "z" ]
    assert got[ "twin" ][ "declared" ] == []


def test_a_python_file_that_does_not_parse_raises_from_extract_python(tmp_path):
    root, ( path, ) = tree( tmp_path, { "bad.py": "def (:\n" } )
    with pytest.raises( SyntaxError ):
        ex.extract_python( root, path, "new" )


def test_an_unreadable_python_file_is_not_skipped_quietly(tmp_path):
    root, ( path, ) = tree( tmp_path, { "ok.py": "x = 1\n" } )
    path.write_bytes( b"\xff\xfe\x00bad" )
    with pytest.raises( UnicodeDecodeError ):
        ex.extract_tree( root, [ path ], "new" )


@pytest.mark.parametrize( "call", [ lambda r, p: ex.extract_python( r, p, "old" ), lambda r, p: ex.extract_script( r, [ p ], "old" ), lambda r, p: ex.extract_tree( r, [], "old" ) ] )
def test_an_origin_other_than_new_or_server_is_refused_even_with_nothing_to_extract(tmp_path, call):
    root, ( path, ) = tree( tmp_path, { "m.py": "x = 1\n" } )
    with pytest.raises( ValueError, match="origin must be one of" ):
        call( root, path )


def test_a_file_that_is_neither_python_nor_script_is_refused(tmp_path):
    root, ( path, ) = tree( tmp_path, { "notes.md": "text\n" } )
    with pytest.raises( ValueError, match="neither Python nor script" ):
        ex.extract_tree( root, [ path ], "new" )


def test_the_id_depends_on_each_of_its_four_fields_and_is_d_plus_ten_hex():
    base = ex.definition_id( "new", "f.py", "g", "def g(): pass" )
    assert base.startswith( "d-" ) and len( base ) == 12 and int( base[ 2: ], 16 ) >= 0
    for other in ( ( "server", "f.py", "g", "def g(): pass" ), ( "new", "h.py", "g", "def g(): pass" ), ( "new", "f.py", "k", "def g(): pass" ), ( "new", "f.py", "g", "def g(): return" ) ):
        assert ex.definition_id( *other ) != base


def test_extract_tree_skips_a_python_file_that_does_not_parse_and_still_extracts_the_rest(tmp_path):
    root, paths = tree( tmp_path, { "good.py": "def a():\n    return 1\n", "bad.py": "def (:\n" } )
    report = ex.extract_tree( root, paths, "server" )
    assert report[ "skipped_python" ] == [ "bad.py" ] and [ d[ "name" ] for d in report[ "definitions" ] ] == [ "a" ]
    assert report[ "definitions" ][ 0 ][ "origin" ] == "server"
    ex.completeness( report )                                             # a skipped Python file does not make the extraction incomplete
    root2, paths2 = tree( tmp_path / "again", { "good.py": "def a():\n    return 1\n", "bad.py": "def b():\n    return 2\n" } )
    assert ex.extract_tree( root2, paths2, "new" )[ "skipped_python" ] == []            # positive control: the repaired file is read


def test_a_definition_repeated_with_the_same_text_is_listed_and_kept_once(tmp_path):
    src = "if True:\n    def same():\n        return 1\nelse:\n    def same():\n        return 1\n"
    root, paths = tree( tmp_path, { "r.py": src } )
    report = ex.extract_tree( root, paths, "new" )
    assert [ d[ "line" ] for d in report[ "definitions" ] ] == [ 2 ]
    assert [ ( r[ "name" ], r[ "line" ] ) for r in report[ "repeated_ids" ] ] == [ ( "same", 5 ) ]


# ---- script files, through the real compiler ----------------------------------------------------------------------

def fixture_files():
    """Return the shared TypeScript fixture, name to source."""
    return json.loads( pathlib.Path( cu.get_project_root() + "/src/tests/unit/ts_extract/bodies-fixture.json" ).read_text( encoding="utf-8" ) )


def test_script_records_come_from_the_compiler_with_origin_lang_and_the_closed_account(tmp_path):
    root, paths = tree( tmp_path, fixture_files() )
    report = ex.extract_tree( root, paths, "new" )
    got = { f"{d[ 'file' ]}#{d[ 'name' ]}": d for d in report[ "definitions" ] }
    assert len( got ) == 14 and all( d[ "lang" ] == "ts" and d[ "origin" ] == "new" for d in got.values() )
    pub = got[ "m.ts#Box.pub" ]
    assert ( pub[ "line" ], pub[ "end_line" ], pub[ "sig" ], pub[ "public" ], pub[ "nodes" ] ) == ( 4, 10, "(a: number, b: number): number", True, 51 )
    assert pub[ "id" ] == ex.definition_id( "new", "m.ts", "Box.pub", pub[ "text" ] )
    assert got[ "m.ts#Box.priv" ][ "public" ] is False and got[ "m.ts#Box.cb" ][ "nodes" ] == 9
    assert report[ "skipped_script" ] == [] and report[ "repeated_ids" ] == []
    assert report[ "script_accounts" ] == [ { "file": "m.ts", "function_like_total": 13, "anonymous_walked": 1, "reported": 12 },
                                            { "file": "p.js", "function_like_total": 3, "anonymous_walked": 1, "reported": 2 } ]
    ex.completeness( report )


def test_python_definitions_come_before_script_ones(tmp_path):
    root, paths = tree( tmp_path, { "a.ts": "function s() { return 1; }\n", "b.py": "def p():\n    return 1\n" } )
    assert [ ( d[ "lang" ], d[ "name" ] ) for d in ex.extract_tree( root, paths, "new" )[ "definitions" ] ] == [ ( "py", "p" ), ( "ts", "s" ) ]


def test_a_script_file_that_does_not_parse_makes_the_extraction_incomplete_and_a_repaired_one_does_not(tmp_path):
    root, paths = tree( tmp_path, { "good.js": "function a( x ) { return x; }\n", "bad.js": "function ( {{{ broken\n" } )
    report = ex.extract_tree( root, paths, "new" )
    assert report[ "skipped_script" ] == [ "bad.js" ]
    with pytest.raises( err.SemdupError, match="bad.js did not parse" ) as caught:
        ex.completeness( report )
    assert caught.value.code == err.EXTRACT_INCOMPLETE
    root2, paths2 = tree( tmp_path / "fixed", { "good.js": "function a( x ) { return x; }\n", "bad.js": "function b( y ) { return y; }\n" } )
    ex.completeness( ex.extract_tree( root2, paths2, "new" ) )


def test_an_account_one_short_is_refused_and_names_the_file():
    report = { "skipped_script": [], "script_accounts": [ { "file": "ok.ts", "function_like_total": 2, "anonymous_walked": 1, "reported": 1 },
                                                       { "file": "short.ts", "function_like_total": 5, "anonymous_walked": 1, "reported": 3 } ] }
    with pytest.raises( err.SemdupError ) as caught:
        ex.completeness( report )
    assert caught.value.code == err.EXTRACT_INCOMPLETE and "short.ts: 3 reported + 1 anonymous != 5" in caught.value.detail and "ok.ts" not in caught.value.detail


def test_completeness_passes_a_closed_account_and_ignores_skipped_python():
    ex.completeness( { "skipped_script": [], "skipped_python": [ "x.py" ], "script_accounts": [ { "file": "a.ts", "function_like_total": 3, "anonymous_walked": 1, "reported": 2 } ] } )


def test_a_missing_compiler_is_reported_by_its_named_code(tmp_path, monkeypatch):
    def gone( *a, **k ): raise DependencyMissing( "node", "not installed" )
    monkeypatch.setattr( js_index, "extract_js_shapes", gone )
    root, paths = tree( tmp_path, { "a.ts": "function s() { return 1; }\n" } )
    with pytest.raises( err.SemdupError ) as caught:
        ex.extract_tree( root, paths, "new" )
    assert caught.value.code == err.DEPENDENCY_MISSING and "node is missing" in caught.value.detail


def test_with_no_script_files_node_is_never_started(tmp_path, monkeypatch):
    def boom( *a, **k ): raise AssertionError( "node was started" )
    monkeypatch.setattr( js_index, "extract_js_shapes", boom )
    root, paths = tree( tmp_path, { "b.py": "def p():\n    return 1\n" } )
    assert [ d[ "name" ] for d in ex.extract_tree( root, paths, "new" )[ "definitions" ] ] == [ "p" ]
