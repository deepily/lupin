"""
The seed pool: reader, test paths, measuring, eligibility, id mapping, twin groups, cells.
"""
import pathlib

import pytest

from cosa.repo.symindex import build as bd
from cosa.repo.symindex import dups as dp
from cosa.repo.symindex import spec as sp
from lupin_mcp.reuse_needset import pool

REPO_ROOT = sp.git_toplevel( pathlib.Path( __file__ ).resolve().parent )

BODY = '''def {name}( items ):
    """{doc}"""
    total = 0
    for item in items:
        if item > {k}:
            total += item * 2
        else:
            total -= 1
    return total
'''

SMALL = '''def tiny( x ):
    """Adds."""
    return x + 1
'''

TS_TWINS = '''/** Sums the rows. */
export function tsOne( rows: number[] ): number {
    let acc = 0;
    for ( const row of rows ) {
        if ( row > 3 ) { acc += row * 2; } else { acc -= 1; }
    }
    return acc;
}

/** Totals the cells. */
export function tsTwo( cells: number[] ): number {
    let sum = 0;
    for ( const cell of cells ) {
        if ( cell > 9 ) { sum += cell * 2; } else { sum -= 1; }
    }
    return sum;
}

/** Holds rows. */
export class Holder {
    keep( rows: number[] ): number {
        const seen = new Set<number>();
        let acc = 0;
        while ( acc < rows.length ) {
            seen.add( rows[ acc ] );
            acc += 1;
        }
        return seen.size + rows.length;
    }
}
'''


def ts_line( needle ):
    """Return the 1-based line of the TypeScript fixture that holds the needle."""
    return next( i for i, l in enumerate( TS_TWINS.splitlines(), 1 ) if needle in l )


@pytest.fixture( autouse=True )
def _typescript_lookup( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )


def write_tree( tmp_path ):
    """Write a small tree of Python twins, odd ones out, a test file and TypeScript twins."""
    ( tmp_path / "pkg" ).mkdir()
    ( tmp_path / "tests" ).mkdir()
    ( tmp_path / "web" ).mkdir()
    ( tmp_path / "pkg" / "a.py" ).write_text( BODY.format( name="twin_a", doc="Sums items.", k=3 ) + "\n\n" + BODY.format( name="twin_b", doc="Totals rows.", k=7 )
                                              + "\n\n" + BODY.format( name="nodoc", doc="", k=5 ) + "\n\n" + SMALL, encoding="utf-8" )
    ( tmp_path / "pkg" / "lone.py" ).write_text( BODY.format( name="lone", doc="Alone.", k=1 ).replace( "total -= 1", "total = total ** 2 - len( items )" ), encoding="utf-8" )
    ( tmp_path / "tests" / "test_a.py" ).write_text( BODY.format( name="test_thing", doc="A test.", k=2 ), encoding="utf-8" )
    ( tmp_path / "web" / "m.ts" ).write_text( TS_TWINS, encoding="utf-8" )
    return tmp_path


def def_line( path, name ):
    """Return the 1-based line where a Python function of the given name is defined in a file."""
    lines = pathlib.Path( path ).read_text( encoding="utf-8" ).splitlines()
    return next( i for i, l in enumerate( lines, 1 ) if l.startswith( f"def {name}(" ) )


def rec( id, file, name, lang="py", doc="Docs.", kind="function", line=1 ):
    """Return a minimal index record."""
    return { "id": id, "file": file, "name": name, "lang": lang, "doc": doc, "kind": kind, "line": line }


def test_the_pool_reads_the_searchable_listing_and_names_that_reader( monkeypatch ):
    monkeypatch.setattr( bd, "read_searchable", lambda gen: [ "S", gen ] )
    monkeypatch.setattr( bd, "read_symbols", lambda *a, **k: pytest.fail( "the public-only reader was used" ) )
    assert pool.read_pool_symbols( "g" ) == ( [ "S", "g" ], "read_searchable" ) and pool.READER == "read_searchable"


def test_test_paths_are_found_by_directory_and_by_file_name():
    for path in ( "src/tests/unit/x.py", "a/test/x.py", "web/__tests__/x.ts", "pkg/test_x.py", "web/x.test.ts", "web/x.spec.js" ):
        assert pool.is_test_path( path ), path
    for path in ( "pkg/x.py", "src/testing_tools/x.py", "web/x.ts", "pkg/tests.py" ):
        assert not pool.is_test_path( path ), path


def test_the_last_path_part_is_not_read_as_a_directory():
    assert not pool.is_test_path( "pkg/tests" )


def test_measure_counts_nodes_for_both_languages_and_skips_what_it_cannot_read( tmp_path ):
    root    = write_tree( tmp_path )
    ( root / "pkg" / "broken.py" ).write_text( "def (:\n", encoding="utf-8" )
    ( root / "pkg" / "binary.py" ).write_bytes( b"\xff\xfe\x00" )
    where   = root / "pkg" / "a.py"
    records = [ rec( "pkg.a.twin_a", "pkg/a.py", "twin_a", line=def_line( where, "twin_a" ) ), rec( "pkg.a.twin_b", "pkg/a.py", "twin_b", line=def_line( where, "twin_b" ) ),
                rec( "pkg.a.tiny", "pkg/a.py", "tiny", line=def_line( where, "tiny" ) ),
                rec( "pkg.broken.x", "pkg/broken.py", "x" ), rec( "pkg.binary.y", "pkg/binary.py", "y" ), rec( "pkg.gone.z", "pkg/gone.py", "z" ),
                rec( "pkg.a.missing_name", "pkg/a.py", "missing_name" ),
                rec( "web.m.tsOne", "web/m.ts", "tsOne", "ts" ), rec( "web.m.tsTwo", "web/m.ts", "tsTwo", "ts" ), rec( "web.m.absent", "web/m.ts", "absent", "ts" ),
                rec( "web.m.Holder", "web/m.ts", "Holder", "ts", kind="class", line=ts_line( "export class Holder" ) ),
                rec( "web.m.Ghost", "web/m.ts", "Ghost", "ts", kind="class", line=999 ) ]
    out     = pool.measure( root, records )
    assert sorted( out ) == [ "pkg.a.tiny", "pkg.a.twin_a", "pkg.a.twin_b", "web.m.Holder", "web.m.tsOne", "web.m.tsTwo" ]
    assert ( out[ "web.m.Holder" ].nodes, len( out[ "web.m.Holder" ].shingles ) ) == ( 52, 48 ), "a script class is measured over its whole tree, as a Python class is"
    assert out[ "pkg.a.twin_a" ].nodes == out[ "pkg.a.twin_b" ].nodes >= dp.DEFAULT_MIN_NODE > out[ "pkg.a.tiny" ].nodes
    assert out[ "pkg.a.twin_a" ].shingles == out[ "pkg.a.twin_b" ].shingles and out[ "pkg.a.twin_a" ].shingles
    assert out[ "web.m.tsOne" ].nodes >= dp.DEFAULT_MIN_NODE and out[ "web.m.tsOne" ].shingles == out[ "web.m.tsTwo" ].shingles


def test_a_name_defined_twice_in_a_file_gets_one_measure_per_record( tmp_path ):
    ( tmp_path / "web" ).mkdir()
    ( tmp_path / "dup.py" ).write_text( "class K:\n    def m( self ):\n        return 1\n\n    def m( self, a ):\n        if a:\n            return a + 1\n        return a * 2\n", encoding="utf-8" )
    ( tmp_path / "web" / "d.ts" ).write_text( "export class D {\n    get v() { return 1; }\n    set v( x ) { if ( x ) { this.w = x; } this.w = 0; }\n}\n", encoding="utf-8" )
    recs = [ rec( "dup.K.m", "dup.py", "K.m", line=2 ), rec( "dup.K.m#2", "dup.py", "K.m", line=5 ),
             rec( "web.d.D.v", "web/d.ts", "D.v", "ts", kind="method", line=2 ), rec( "web.d.D.v#2", "web/d.ts", "D.v", "ts", kind="method", line=3 ),
             rec( "dup.K.m#3", "dup.py", "K.m", line=9 ) ]
    out  = pool.measure( tmp_path, recs )
    assert sorted( out ) == [ "dup.K.m", "dup.K.m#2", "web.d.D.v", "web.d.D.v#2" ], "the third record has no third definition"
    assert out[ "dup.K.m" ].nodes < out[ "dup.K.m#2" ].nodes and out[ "web.d.D.v" ].nodes < out[ "web.d.D.v#2" ].nodes
    assert pool.measure( tmp_path, list( reversed( recs ) ) ).keys() == out.keys(), "record order does not matter, line order does"
    first = "class K:\n    def m( self ):\n        return 1\n"
    ( tmp_path / "solo.py" ).write_text( first, encoding="utf-8" )
    ( tmp_path / "one.py" ).write_text( first + "\n    def m( self, a ):\n        return a * 2 + 1\n", encoding="utf-8" )
    both = pool.measure( tmp_path, [ rec( "solo.K.m", "solo.py", "K.m", line=2 ), rec( "one.K.m", "one.py", "K.m", line=2 ) ] )
    assert both[ "one.K.m" ].nodes == both[ "solo.K.m" ].nodes, "a definition with no record of its own changes no other record"
    ( tmp_path / "late.py" ).write_text( first + "\n    def m( self, a ):\n        return a * 2 + 1\n", encoding="utf-8" )
    late = pool.measure( tmp_path, [ rec( "late.K.m#2", "late.py", "K.m", line=5 ) ] )
    assert late[ "late.K.m#2" ].nodes > both[ "solo.K.m" ].nodes, "a Python record whose earlier twin is missing from the index keeps its own definition"


def test_measure_of_python_only_records_never_starts_node( tmp_path, monkeypatch ):
    root = write_tree( tmp_path )
    monkeypatch.setattr( pool.js_index, "extract_js_shapes", lambda *a, **k: pytest.fail( "node was started for a Python-only list" ) )
    assert list( pool.measure( root, [ rec( "pkg.a.twin_a", "pkg/a.py", "twin_a" ) ] ) ) == [ "pkg.a.twin_a" ]


def test_eligible_drops_by_the_first_reason_that_applies_and_counts_them():
    big, small = pool.Measure( 40, frozenset() ), pool.Measure( 5, frozenset() )
    records    = [ rec( "z.keep", "pkg/z.py", "keep" ), rec( "a.keep", "pkg/a.py", "keep" ),
                   rec( "d.dart", "lib/d.dart", "d", "dart" ),
                   rec( "t.test", "tests/t.py", "t" ),
                   rec( "u.unmeasured", "pkg/u.py", "u" ),
                   rec( "s.small", "pkg/s.py", "s" ),
                   rec( "n.nodoc", "pkg/n.py", "n", doc="" ),
                   rec( "x.testsmall", "tests/x.py", "x" ) ]
    measures   = { "z.keep": big, "a.keep": big, "d.dart": big, "t.test": big, "s.small": small, "n.nodoc": big, "x.testsmall": small }
    kept, dropped = pool.eligible( records, measures )
    assert [ r[ "id" ] for r in kept ] == [ "a.keep", "z.keep" ]
    assert dropped == { "other_language": 1, "test": 2, "unmeasured": 1, "small": 1, "no_docstring": 1 }
    kept2, dropped2 = pool.eligible( records, measures, min_nodes=3 )
    assert "small" not in dropped2 and len( kept2 ) == 3


def test_eligible_with_nothing_to_drop_returns_an_empty_count():
    assert pool.eligible( [], {} ) == ( [], {} )


def test_a_dups_id_becomes_the_index_id():
    assert pool.index_id( "pkg.mod.fn" ) == "pkg.mod.fn"
    assert pool.index_id( "pkg.mod.Cls.m~2" ) == "pkg.mod.Cls.m#2"
    assert pool.index_id( "web/static/js/app.ts#Box.get" ) == "web.static.js.app.Box.get"
    assert pool.index_id( "web/app.js#fn~3" ) == "web.app.fn#3"
    assert pool.index_id( "pkg.mod.fn", prefix="x." ) == "x.pkg.mod.fn"


def test_the_manifest_maps_every_member_and_keeps_both_lists():
    result = { "exact": [ [ "a.f", "b/c.ts#g" ] ], "near": [ { "ids": [ "a.h", "a.h~2" ], "jaccard": 0.9 } ] }
    man    = pool.dups_manifest( result )
    assert man == { "exact": [ { "members": [ { "id": "a.f" }, { "id": "b.c.g" } ] } ], "near": [ { "members": [ { "id": "a.h" }, { "id": "a.h#2" } ] } ] }
    assert pool.dups_manifest( { "exact": [], "near": [] } ) == { "exact": [], "near": [] }


def test_twin_map_joins_exact_and_near_into_groups():
    result = { "exact": [ [ "a.f", "a.g" ] ], "near": [ { "ids": [ "a.g", "a.h" ], "jaccard": 0.9 } ] }
    twins  = pool.twin_map( result )
    assert twins == { "a.f": [ "a.g", "a.h" ], "a.g": [ "a.f", "a.h" ], "a.h": [ "a.f", "a.g" ] }


def test_cells_follow_the_rules_for_each_kind():
    kept  = [ rec( "p.one", "pkg/p.py", "one" ), rec( "p.two", "pkg/p.py", "two" ), rec( "p.three", "pkg/p.py", "three" ),
              rec( "q.lone", "pkg/q.py", "lone" ), rec( "w.a", "web/w.ts", "a", "ts" ), rec( "w.b", "web/w.ts", "b", "ts" ) ]
    twins = { "p.one": [ "p.two" ], "w.a": [ "ghost" ], "p.two": [ "p.one" ] }
    cells = pool.cell_pool( kept, twins, { r[ "id" ] for r in kept } )
    assert cells[ ( "near_copy", "py" ) ] == [ "p.one", "p.two" ]
    assert ( "near_copy", "ts" ) not in cells
    assert cells[ ( "work_alike", "py" ) ] == cells[ ( "cross_language", "py" ) ] == [ "p.one", "p.three", "p.two", "q.lone" ]
    assert cells[ ( "work_alike", "ts" ) ] == cells[ ( "cross_language", "ts" ) ] == [ "w.a", "w.b" ]
    assert cells[ ( "nothing", "py" ) ] == [ "pkg/p.py" ]
    assert ( "nothing", "ts" ) not in cells


def test_a_real_tree_runs_through_the_index_the_finder_and_the_pool( tmp_path ):
    root    = write_tree( tmp_path )
    spec    = sp.spec_for( root )
    built   = bd.build( root, tmp_path / "out" )
    records, reader = pool.read_pool_symbols( built[ "gen_dir" ] )
    ids     = { r[ "id" ] for r in records }
    measures = pool.measure( root, records )
    kept, dropped = pool.eligible( records, measures )
    found   = dp.find_duplicates( spec, sorted( root.glob( "**/*.py" ) ), js_files=[ root / "web" / "m.ts" ] )
    twins   = pool.twin_map( found, prefix=f"{spec.name}:" )
    assert reader == pool.READER
    assert twins and set( twins ) - ids == { f"{spec.name}:tests.test_a.test_thing" }       # the index leaves test code out; every other twin id is an index id
    kept_ids = [ r[ "id" ].split( ":", 1 )[ 1 ] for r in kept ]
    assert "pkg.a.twin_a" in kept_ids and "pkg.lone.lone" in kept_ids
    assert "pkg.a.nodoc" not in kept_ids and "pkg.a.tiny" not in kept_ids and not any( i.startswith( "tests." ) for i in kept_ids )
    cells = pool.cell_pool( kept, twins, ids )
    assert cells[ ( "near_copy", "py" ) ] == [ f"{spec.name}:pkg.a.twin_a", f"{spec.name}:pkg.a.twin_b" ]
    assert cells[ ( "near_copy", "ts" ) ] == [ f"{spec.name}:web.m.tsOne", f"{spec.name}:web.m.tsTwo" ]
    assert f"{spec.name}:web.m.Holder" in cells[ ( "work_alike", "ts" ) ], "a documented TypeScript class seeds a need like a Python class"
    assert dropped.get( "no_docstring", 0 ) + dropped.get( "small", 0 ) >= 2


def test_a_definition_of_exactly_min_nodes_is_kept_and_one_below_is_small():
    records = [ rec( "a.edge", "pkg/a.py", "edge" ), rec( "a.below", "pkg/a.py", "below" ) ]
    measures = { "a.edge": pool.Measure( 25, frozenset() ), "a.below": pool.Measure( 24, frozenset() ) }
    kept, dropped = pool.eligible( records, measures, min_nodes=25 )
    assert [ r[ "id" ] for r in kept ] == [ "a.edge" ] and dropped == { "small": 1 }
