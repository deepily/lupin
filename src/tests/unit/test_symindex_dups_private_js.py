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
    assert ji.extract_js_shapes( tmp_path, [] ) == { "scanned": [], "defs": [] }
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
