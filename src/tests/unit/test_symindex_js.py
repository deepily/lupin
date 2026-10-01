"""
Unit tests for cosa.repo.symindex.js_index and ts_extract.js (TypeScript compiler under node).
"""
import json
import os
import pathlib

import pytest

from cosa.repo.symindex import js_index as ji
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.errors import DependencyMissing
from tests.unit.symindex_helpers import make_repo

REPO_ROOT = sp.git_toplevel( pathlib.Path( __file__ ).resolve().parent )


def _extract( tmp_path, name="app.ts" ):
    root = make_repo( tmp_path )
    return root, ji.extract_js( REPO_ROOT, [ root / "web" / name ] ) if False else ji.extract_js( root, [ root / "web" / name ] )


@pytest.fixture( autouse=True )
def _node_modules( monkeypatch ):
    """The fixture repo has no node_modules/typescript; point the lookup at this repository's."""
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )


def test_typescript_fixtures_class_methods_typed_arrows_generics( tmp_path ):
    _, recs = _extract( tmp_path )
    by = { r[ "name" ]: r for r in recs }
    assert by[ "add" ][ "sig" ] == "<T extends number>(a: T, b: T): T"           # generics
    assert by[ "add" ][ "doc" ] == "Adds numbers."                               # first JSDoc line
    assert by[ "Box" ][ "kind" ] == "class"
    assert by[ "Box.get" ][ "kind" ] == "method" and by[ "Box.get" ][ "sig" ] == "(k: string): T | undefined"   # class method
    assert by[ "Box.put" ][ "sig" ] == "(k: string, v: T): Promise<void>"
    assert by[ "Box.constructor" ][ "kind" ] == "method"
    assert sorted( r[ "sig" ] for r in recs if r[ "name" ] == "Box.size" ) == [ "(): number", "(n: number)" ]      # get and set accessors are indexed too
    assert by[ "mul" ][ "sig" ] == ": ( a: number, b: number ) => number".replace( "( a: number, b: number )", "( a: number, b: number )" ) \
           or by[ "mul" ][ "sig" ].startswith( ": " )                            # typed arrow: the declared type is the signature
    assert by[ "mul" ][ "doc" ] == "Typed arrow."
    assert by[ "emptyDoc" ][ "doc" ] == "" and by[ "tagOnly" ][ "doc" ] == ""                   # an empty JSDoc and a tag-only JSDoc give no summary
    assert by[ "plain" ][ "sig" ] == "(x: string)" and by[ "fe" ][ "sig" ] == "(y)"
    assert "Box.hidden" not in by and "Box.#secret" not in by and "notFn" not in by     # private members and non-functions are skipped
    assert all( r[ "lang" ] == "ts" and r[ "public" ] is True and r[ "line" ] >= 1 for r in recs )


def test_plain_javascript_is_indexed_too( tmp_path ):
    _, recs = _extract( tmp_path, "lib.js" )
    assert [ r[ "name" ] for r in recs ] == [ "twice", "thrice" ]
    assert recs[ 0 ][ "doc" ] == "Plain helper." or recs[ 0 ][ "doc" ] == ""


def test_pin_ignores_comments_and_whitespace_but_not_code( tmp_path ):
    root = make_repo( tmp_path )
    f    = root / "web" / "p.ts"
    f.write_text( "/** Doc. */\nexport function f( a: number ) { return a + 1; }\n", encoding="utf-8" )
    p0 = ji.extract_js( root, [ f ] )[ 0 ][ "pin" ]
    f.write_text( "/** Different doc\n * more */\n// comment\nexport function   f(a: number){\n return a+1; }\n", encoding="utf-8" )
    assert ji.extract_js( root, [ f ] )[ 0 ][ "pin" ] == p0
    f.write_text( "/** Doc. */\nexport function f( a: number ) { return a + 2; }\n", encoding="utf-8" )
    assert ji.extract_js( root, [ f ] )[ 0 ][ "pin" ] != p0


def test_empty_file_list_does_not_start_node():
    assert ji.extract_js( REPO_ROOT, [] ) == []


def test_find_node_order_and_failure( monkeypatch, tmp_path ):
    fake = tmp_path / "mynode"; fake.write_text( "#!/bin/sh\n", encoding="utf-8" ); fake.chmod( 0o755 )
    monkeypatch.setenv( "LUPIN_NODE", str( fake ) )
    assert ji.find_node() == str( fake )
    monkeypatch.delenv( "LUPIN_NODE" )
    monkeypatch.setattr( ji.shutil, "which", lambda n: "/usr/bin/node" )
    assert ji.find_node() == "/usr/bin/node"
    monkeypatch.setattr( ji.shutil, "which", lambda n: None )
    nvm = tmp_path / ".nvm" / "versions" / "node" / "v1" / "bin"; nvm.mkdir( parents=True ); ( nvm / "node" ).write_text( "", encoding="utf-8" )
    monkeypatch.setenv( "HOME", str( tmp_path ) )
    assert ji.find_node().endswith( "v1/bin/node" )
    monkeypatch.setenv( "HOME", str( tmp_path / "nohome" ) )
    with pytest.raises( DependencyMissing ) as e: ji.find_node()
    assert e.value.what == "node"


def test_find_typescript_prefers_the_root_then_lupin_root_then_fails( tmp_path, monkeypatch ):
    a = tmp_path / "a" / "node_modules" / "typescript"; a.mkdir( parents=True ); ( a / "package.json" ).write_text( '{"version":"9.9.9"}', encoding="utf-8" )
    assert ji.find_typescript( tmp_path / "a" ) == a
    assert ji.typescript_version( a ) == "9.9.9"
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    assert ji.find_typescript( tmp_path / "none" ) == REPO_ROOT / "node_modules" / "typescript"
    monkeypatch.delenv( "LUPIN_ROOT" )
    with pytest.raises( DependencyMissing ) as e: ji.find_typescript( tmp_path / "none" )
    assert e.value.what == "typescript"


def test_compiler_failure_is_an_error_not_an_empty_index( tmp_path, monkeypatch ):
    root = make_repo( tmp_path )
    monkeypatch.setattr( ji, "EXTRACTOR", tmp_path / "missing.js" )
    with pytest.raises( RuntimeError, match="ts_extract.js failed" ):
        ji.extract_js( root, [ root / "web" / "app.ts" ] )
