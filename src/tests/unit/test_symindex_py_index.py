"""
Unit tests for cosa.repo.symindex.py_index: public-symbol rules, pins, ids.
"""
import ast

import pytest

from cosa.repo.symindex import py_index as pi
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.build import collect
from tests.unit.symindex_helpers import make_repo


def _extract( tmp_path, include_all=False, rel="pkg/util.py" ):
    root = make_repo( tmp_path )
    spec = sp.spec_for( root )
    return pi.extract_python( spec, root / rel, include_all )


def _names( recs ): return [ r[ "name" ] for r in recs ]


def test_public_symbols_follow_the_documented_rule( tmp_path ):
    names = _names( _extract( tmp_path ) )
    assert names == [ "public_fn", "Widget", "Widget.__init__", "Widget.render", "Widget.size", "Widget.size",
                      "conditional_fn", "conditional_fn", "fallback_fn" ]
    assert "_private_fn" not in names and "Widget._hidden" not in names and "_PrivateClass.method" not in names


def test_include_all_adds_private_and_nested_helpers( tmp_path ):
    recs  = _extract( tmp_path, include_all=True )
    names = _names( recs )
    for n in ( "_private_fn", "_private_fn.<locals>.nested_helper", "Widget._hidden", "_PrivateClass", "_PrivateClass.method" ):
        assert n in names
    flags = { r[ "name" ]: r[ "public" ] for r in recs }
    assert flags[ "public_fn" ] is True and flags[ "Widget.__init__" ] is True
    assert flags[ "_private_fn.<locals>.nested_helper" ] is False and flags[ "Widget._hidden" ] is False
    assert flags[ "_PrivateClass.method" ] is False


def test_kinds_signature_doc_and_line( tmp_path ):
    by = { r[ "name" ]: r for r in _extract( tmp_path ) }
    assert by[ "public_fn" ][ "kind" ] == "function" and by[ "Widget" ][ "kind" ] == "class" and by[ "Widget.render" ][ "kind" ] == "method"
    assert by[ "public_fn" ][ "sig" ] == "(a, b=1) -> int"
    assert by[ "Widget" ][ "sig" ] == "" and by[ "Widget.render" ][ "sig" ] == "(self)"
    assert by[ "public_fn" ][ "doc" ] == "Adds things." and by[ "Widget.__init__" ][ "doc" ] == ""
    assert by[ "public_fn" ][ "line" ] == 5 and by[ "public_fn" ][ "module" ] == "pkg.util"


def test_init_module_name_drops_the_init_suffix( tmp_path ):
    root = make_repo( tmp_path )
    ( root / "pkg" / "__init__.py" ).write_text( "def exported():\n    return 1\n", encoding="utf-8" )
    recs = pi.extract_python( sp.spec_for( root ), root / "pkg" / "__init__.py" )
    assert recs[ 0 ][ "module" ] == "pkg"


def test_pin_ignores_docstrings_and_whitespace_but_not_code():
    base   = ast.parse( 'def f( a ):\n    """old doc"""\n    return a + 1\n' ).body[ 0 ]
    doc    = ast.parse( 'def f( a ):\n    """NEW doc\n\n    more"""\n    return   a+1\n' ).body[ 0 ]
    nodoc  = ast.parse( 'def f( a ):\n    return a + 1\n' ).body[ 0 ]
    code   = ast.parse( 'def f( a ):\n    """old doc"""\n    return a + 2\n' ).body[ 0 ]
    assert pi.pin( base ) == pi.pin( doc ) == pi.pin( nodoc )
    assert pi.pin( base ) != pi.pin( code )
    assert len( pi.pin( base ) ) == 10


def test_strip_docs_leaves_pass_when_a_body_was_only_a_docstring():
    node = ast.parse( 'class C:\n    """only doc"""\n' ).body[ 0 ]
    assert isinstance( pi.strip_docs( node ).body[ 0 ], ast.Pass )
    assert isinstance( node.body[ 0 ], ast.Expr )                               # the input is not mutated


def test_ids_are_unique_even_for_setters_and_conditional_redefinitions( tmp_path ):
    data = collect( sp.spec_for( make_repo( tmp_path ) ) )
    ids  = [ r[ "id" ] for r in data[ "all_symbols" ] ]
    assert len( ids ) == len( set( ids ) )
    assert "repo:pkg.util.Widget.size" in ids and "repo:pkg.util.Widget.size#2" in ids
    assert "repo:pkg.util.conditional_fn#2" in ids


def test_unparseable_file_is_listed_not_fatal( tmp_path ):
    root = make_repo( tmp_path )
    ( root / "pkg" / "broken.py" ).write_text( "def broken(:  # APIRouter\n", encoding="utf-8" )       # the route scan must survive it too
    ( root / "pkg" / "binary.py" ).write_bytes( b"\xff\xfe\x00bad" )
    data = collect( sp.spec_for( root ) )
    assert sorted( data[ "unparsed" ] ) == [ "pkg/binary.py", "pkg/broken.py" ]
    assert any( r[ "name" ] == "public_fn" for r in data[ "symbols" ] )
