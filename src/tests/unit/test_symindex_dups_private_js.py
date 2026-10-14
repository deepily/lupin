"""
Unit tests for the duplicate finder: private and nested helpers, and the script pass.
"""
import pathlib

import pytest

from cosa.repo.symindex import __main__ as cli
from cosa.repo.symindex import dups as dp
from cosa.repo.symindex import js_index as ji
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.errors import DependencyMissing

REPO_ROOT = sp.git_toplevel( pathlib.Path( __file__ ).resolve().parent )

PY_PRIVATE = '''
def _helper_a( items ):
    total = 0
    for item in items:
        if item > 3:
            total += item * 2
    return total


def _helper_b( rows ):
    acc = 0
    for row in rows:
        if row > 9:
            acc += row * 5
    return acc


def outer( things ):
    def inner_one( xs ):
        n = 0
        for x in xs:
            if x > 1:
                n += x * 3
        return n
    return inner_one( things )


class K:
    def _p( self, zs ):
        m = 0
        for z in zs:
            if z > 2:
                m += z * 7
        return m

    def _q( self, ws ):
        c = 0
        for w in ws:
            if w > 8:
                c += w * 4
        return c
'''

TS_CLONES = '''
export class Store {
    private _sumA( xs: number[] ): number {
        let t = 0;
        for ( const x of xs ) { if ( x > 3 ) { t += x * 2; } }
        return t;
    }
    public sumB( ys: number[] ): number {
        let u = 0;
        for ( const y of ys ) { if ( y > 8 ) { u += y * 5; } }
        return u;
    }
    #secret( zs: number[] ): number {
        let v = 0;
        for ( const z of zs ) { if ( z > 1 ) { v += z * 9; } }
        return v;
    }
}

export function wrapper( list: number[] ) {
    function nestedSum( ws: number[] ) {
        let q = 0;
        for ( const w of ws ) { if ( w > 4 ) { q += w * 6; } }
        return q;
    }
    return list.map( ( e ) => { function deep( ds: number[] ) { let r = 0; for ( const d of ds ) { if ( d > 4 ) { r += d * 6; } } return r; } return deep( [ e ] ); } );
}

const Anon = class { held( ks: number[] ) { let s = 0; for ( const k of ks ) { if ( k > 2 ) { s += k * 4; } } return s; } };
const table = { member: function ( ps: number[] ) { let o = 0; for ( const p of ps ) { if ( p > 2 ) { o += p * 4; } } return o; } };
'''


@pytest.fixture( autouse=True )
def _node_modules( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )


def _repo( tmp_path ):
    root = tmp_path / "r"; root.mkdir()
    ( root / "p.py" ).write_text( PY_PRIVATE, encoding="utf-8" )
    ( root / "t.ts" ).write_text( TS_CLONES, encoding="utf-8" )
    return root, sp.spec_for( root )


def _flat( rep ): return sorted( i for g in rep[ "exact" ] for i in g )


def test_private_and_nested_python_helpers_are_seen_by_default_and_hidden_by_public_only( tmp_path ):
    root, spec = _repo( tmp_path )
    full = dp.find_duplicates( spec, [ root / "p.py" ], min_nodes=10 )
    assert full[ "exact" ] == [ [ "p._helper_a", "p._helper_b", "p.outer.<locals>.inner_one" ], [ "p.K._p", "p.K._q" ] ]   # a method has a self parameter: its own group
    pub = dp.find_duplicates( spec, [ root / "p.py" ], min_nodes=10, include_private=False )
    assert pub[ "exact" ] == [] and pub[ "provenance" ][ "considered" ] == 1          # only `outer` is public
    assert full[ "provenance" ][ "include_private" ] is True and pub[ "provenance" ][ "include_private" ] is False


def test_typescript_private_nested_and_anonymous_class_members_are_compared( tmp_path ):
    root, spec = _repo( tmp_path )
    rep = dp.find_duplicates( spec, [], js_files=[ root / "t.ts" ], min_nodes=10 )
    ids = _flat( rep )
    assert "t.ts#Store._sumA" in ids and "t.ts#Store.sumB" in ids                    # private modifier is seen
    assert "t.ts#Store.#secret" in ids                                              # #private is seen
    assert "t.ts#wrapper.<locals>.nestedSum" in ids                                 # nested named function
    assert "t.ts#wrapper.<locals>.deep" in ids                             # nested under an anonymous callback: walked
    assert "t.ts#Store.sumB" in rep[ "exact" ][ 0 ]
    names = { d[ "name" ] for d in ji.extract_js_shapes( root, [ root / "t.ts" ] )[ "defs" ] }
    assert "held" in names                                                          # a nameless class contributes its members
    assert "member" in names                                                        # property-assigned function expression
    assert names == { "Store._sumA", "Store.sumB", "Store.#secret", "wrapper", "wrapper.<locals>.nestedSum", "wrapper.<locals>.deep", "held", "member" }   # the .map callback is not reported


def test_typescript_public_only_drops_private_members_and_nested_functions( tmp_path ):
    root, spec = _repo( tmp_path )
    rep = dp.find_duplicates( spec, [], js_files=[ root / "t.ts" ], min_nodes=1, include_private=False )
    assert rep[ "provenance" ][ "considered" ] == 4                                  # sumB, wrapper, held, member
    assert not any( "_sumA" in i or "#secret" in i or "<locals>" in i for g in rep[ "exact" ] for i in g )


def test_literal_values_and_identifier_names_do_not_separate_typescript_clones( tmp_path ):
    root, spec = _repo( tmp_path )
    shapes = ji.extract_js_shapes( root, [ root / "t.ts" ] )
    by = { d[ "name" ]: d[ "kinds" ] for d in shapes[ "defs" ] }
    assert by[ "Store._sumA" ] == by[ "Store.sumB" ]                                 # different names and constants, same kinds
    assert "NumericLiteral" not in by[ "Store.sumB" ] and "Literal" in by[ "Store.sumB" ]
    assert shapes[ "scanned" ] == [ "t.ts" ]


def test_provenance_languages_and_files_scanned_cover_both_passes( tmp_path ):
    root, spec = _repo( tmp_path )
    both = dp.find_duplicates( spec, [ root / "p.py" ], js_files=[ root / "t.ts" ], min_nodes=10 )[ "provenance" ]
    assert both[ "languages" ] == [ "python", "typescript" ] and both[ "files_scanned" ] == 2
    py = dp.find_duplicates( spec, [ root / "p.py" ], min_nodes=10 )[ "provenance" ]
    assert py[ "languages" ] == [ "python" ] and py[ "files_scanned" ] == 1          # no JS file read: no TypeScript claim
    mixed = dp.find_duplicates( spec, [ root / "p.py" ], js_files=[ root / "t.ts" ], min_nodes=10 )
    assert not any( "p.py" in i or i.startswith( "K." ) for g in mixed[ "exact" ] if any( "#" in x for x in g ) for i in g )   # the two languages do not mix in a group


def test_empty_js_list_never_starts_node( tmp_path, monkeypatch ):
    def boom( *a, **k ): raise DependencyMissing( "node" )
    monkeypatch.setattr( ji, "find_node", boom )
    assert ji.extract_js_shapes( tmp_path, [] ) == { "scanned": [], "skipped": [], "defs": [] }
    root, spec = _repo( tmp_path )
    with pytest.raises( DependencyMissing ): ji.extract_js_shapes( root, [ root / "t.ts" ] )


def test_cli_dups_reads_typescript_and_public_only_switch( tmp_path, capsys ):
    root, _ = _repo( tmp_path )
    rc = cli.main( [ "dups", "--root", str( root ), "--min-nodes", "10", "--json" ] ); out = capsys.readouterr().out
    import json
    rep = json.loads( out )
    assert rc == 1 and rep[ "provenance" ][ "languages" ] == [ "python", "typescript" ] and rep[ "provenance" ][ "include_private" ] is True
    rc = cli.main( [ "dups", "--root", str( root ), "--min-nodes", "10", "--public-only", "--json" ] ); rep2 = json.loads( capsys.readouterr().out )
    assert rep2[ "provenance" ][ "include_private" ] is False and rep2[ "provenance" ][ "considered" ] < rep[ "provenance" ][ "considered" ]


def test_default_node_minimum_is_stated_in_provenance( tmp_path ):
    root, spec = _repo( tmp_path )
    assert dp.DEFAULT_MIN_NODE == 25
    assert dp.find_duplicates( spec, [ root / "p.py" ] )[ "provenance" ][ "min_nodes" ] == 25


FIELDS = '''
export class A {
    public p = ( xs: number[] ) => { let t = 0; for ( const x of xs ) { t += x; } return t; };
    private f = ( xs: number[] ) => { let t = 0; for ( const x of xs ) { t += x; } return t; };
    #g = ( xs: number[] ) => { let t = 0; for ( const x of xs ) { t += x; } return t; };
    protected static h = function ( xs: number[] ) { let t = 0; for ( const x of xs ) { t += x; } return t; };
}
'''

BODY = "{ let t = 0; for ( const x of xs ) { if ( x > 2 ) { t += x * 3; } } return t; }"


def test_public_only_drops_private_and_protected_property_functions( tmp_path ):
    root = tmp_path / "r"; root.mkdir()
    ( root / "a.ts" ).write_text( FIELDS, encoding="utf-8" )
    spec = sp.spec_for( root )
    pub = ji.extract_js_shapes( root, [ root / "a.ts" ], public_only=True )
    assert [ d[ "name" ] for d in pub[ "defs" ] ] == [ "A.p" ]
    full = ji.extract_js_shapes( root, [ root / "a.ts" ] )
    assert [ d[ "name" ] for d in full[ "defs" ] ] == [ "A.p", "A.f", "A.#g", "A.h" ]
    rep = dp.find_duplicates( spec, [], js_files=[ root / "a.ts" ], min_nodes=5, include_private=False )
    assert rep[ "provenance" ][ "considered" ] == 1


def test_a_repeated_definition_id_is_numbered_so_no_group_holds_one_definition_twice( tmp_path ):
    root = tmp_path / "r"; root.mkdir()
    ( root / "a.js" ).write_text( f"const o = {{ render: function ( xs ) {BODY}, render: function ( xs ) {BODY} }};\n", encoding="utf-8" )
    ( root / "w.py" ).write_text( "if FLAG:\n    def pick( xs ):\n        t = 0\n        for x in xs:\n            t += x\n        return t\n"
                                 "else:\n    def pick( xs ):\n        t = 0\n        for x in xs:\n            t += x\n        return t\n", encoding="utf-8" )
    spec = sp.spec_for( root )
    rep  = dp.find_duplicates( spec, [ root / "w.py" ], js_files=[ root / "a.js" ], min_nodes=5 )
    assert [ "a.js#render", "a.js#render~2" ] in rep[ "exact" ]
    assert [ "w.pick", "w.pick~2" ] in rep[ "exact" ]                                 # a conditional redefinition, numbered
    assert all( len( set( g ) ) == len( g ) for g in rep[ "exact" ] )


def test_without_node_the_report_is_python_only_and_names_the_missing_tool( tmp_path, monkeypatch ):
    root, spec = _repo( tmp_path )
    def boom( *a, **k ): raise DependencyMissing( "node", "not on PATH" )
    monkeypatch.setattr( ji, "find_node", boom )
    rep = dp.find_duplicates( spec, [ root / "p.py" ], js_files=[ root / "t.ts" ], min_nodes=10 )
    assert rep[ "exact" ] and rep[ "provenance" ][ "languages" ] == [ "python" ]
    assert rep[ "provenance" ][ "missing_dependencies" ] == [ "node" ] and rep[ "provenance" ][ "files_scanned" ] == 1
    ok = dp.find_duplicates( spec, [ root / "p.py" ], min_nodes=10 )                          # no script file: no tool is looked up
    assert ok[ "provenance" ][ "missing_dependencies" ] == []


def test_cli_dups_exits_3_and_still_prints_the_python_findings_when_a_tool_is_missing( tmp_path, monkeypatch, capsys ):
    root, _ = _repo( tmp_path )
    def boom( *a, **k ): raise DependencyMissing( "typescript", "no node_modules" )
    monkeypatch.setattr( ji, "find_typescript", boom )
    rc = cli.main( [ "dups", "--root", str( root ), "--min-nodes", "10" ] ); cap = capsys.readouterr()
    assert rc == 3 and "EXACT" in cap.out and "missing dependencies: typescript" in cap.err


def test_a_script_file_that_does_not_parse_is_skipped_and_not_counted( tmp_path ):
    root = tmp_path / "r"; root.mkdir()
    ( root / "good.js" ).write_text( f"function a( xs ) {BODY}\n", encoding="utf-8" )
    ( root / "bad.js" ).write_text( "function ( {{{ broken\n", encoding="utf-8" )
    ( root / "t.ts" ).write_text( f"function b( xs: number[] ) {BODY}\n", encoding="utf-8" )
    spec = sp.spec_for( root )
    res = ji.extract_js_shapes( root, [ root / "good.js", root / "bad.js" ] )
    assert res[ "scanned" ] == [ "good.js" ] and res[ "skipped" ] == [ "bad.js" ]
    prov = dp.find_duplicates( spec, [], js_files=[ root / "good.js", root / "bad.js" ], min_nodes=5 )[ "provenance" ]
    assert prov[ "files_scanned" ] == 1 and prov[ "languages" ] == [ "python", "javascript" ]
    both = dp.find_duplicates( spec, [], js_files=[ root / "good.js", root / "t.ts" ], min_nodes=5 )
    assert both[ "provenance" ][ "languages" ] == [ "python", "javascript", "typescript" ]


def test_python_and_script_definitions_are_never_grouped_or_paired( tmp_path, monkeypatch ):
    root, spec = _repo( tmp_path )
    same = dp.shingles_of( [ "A", "B", "C", "D", "E", "F", "G", "H" ] )
    def fake( *a, **k ):
        yield "py.f", 30, "same-digest", same, dp.PY_LANG
        yield "t.ts#f", 30, "same-digest", same, dp.SCRIPT_LANG
    monkeypatch.setattr( dp, "_definitions", fake )
    rep = dp.find_duplicates( spec, [], min_nodes=1, threshold=0.5 )
    assert rep[ "exact" ] == [] and rep[ "near" ] == [] and rep[ "provenance" ][ "considered" ] == 2
    def twin( *a, **k ):
        yield "t.js#f", 30, "same-digest", same, dp.SCRIPT_LANG
        yield "t.ts#f", 30, "same-digest", same, dp.SCRIPT_LANG
    monkeypatch.setattr( dp, "_definitions", twin )
    assert dp.find_duplicates( spec, [], min_nodes=1 )[ "exact" ] == [ [ "t.js#f", "t.ts#f" ] ]      # the two script languages do group
