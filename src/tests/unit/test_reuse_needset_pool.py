"""
The seed pool: reader, test paths, measuring, eligibility, id mapping, twin groups, cells.
"""
import pathlib

import numpy as np
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


class Vecs:
    """A vector set stand-in with the ids and the one matrix the screen reads."""

    def __init__( self, rows ):
        """Hold the ids and a concat matrix from { id: vector }."""
        self.ids      = list( rows )
        self.matrices = { "concat": np.array( list( rows.values() ), dtype=np.float32 ) }


def screen_world():
    """Return ( kept, measures, vectors ) with a lookalike pair and a row-less symbol."""
    kept     = [ rec( "p.a1", "pkg/p.py", "a1" ), rec( "p.a2", "pkg/p.py", "a2" ), rec( "p.a3", "pkg/p.py", "a3" ), rec( "p.norow", "pkg/p.py", "norow" ),
                 rec( "w.t1", "web/w.ts", "t1", "ts" ), rec( "w.t2", "web/w.ts", "t2", "ts" ) ]
    shingles = { "p.a1": { 1, 2, 3, 4 }, "p.a3": { 1, 2, 3, 4 }, "p.a2": { 5, 6, 7, 8 }, "p.norow": { 9 }, "w.t1": { 10, 11 }, "w.t2": { 12, 13 } }
    measures = { i: pool.Measure( 40, frozenset( sh ) ) for i, sh in shingles.items() }
    vectors  = Vecs( { "p.a1": [ 1.0, 0.0 ], "p.a2": [ 0.9, 0.436 ], "p.a3": [ 1.0, 0.01 ], "w.t1": [ 0.8, 0.6 ], "w.t2": [ 0.0, 1.0 ] } )
    return kept, measures, vectors


def test_a_seed_passes_the_screen_when_its_nearest_unlike_partner_reaches_the_floor():
    kept, measures, vectors = screen_world()
    got = pool.partner_screen( kept, measures, vectors, 0.85, 0.5, "concat" )
    assert got[ ( "work_alike", "py" ) ] == [ "p.a1", "p.a2", "p.a3" ], "a1 passes on a2 at 0.9; its lookalike a3 at 1.0 is not the partner but a3 still passes on a2"
    assert got[ ( "cross_language", "py" ) ] == [ "p.a2" ] and got[ ( "cross_language", "ts" ) ] == [ "w.t1" ] and got[ ( "work_alike", "ts" ) ] == []
    high = pool.partner_screen( kept, measures, vectors, 0.95, 0.5, "concat" )
    assert high[ ( "work_alike", "py" ) ] == [], "without the lookalike skip, a1 would pass on a3 at about 1.0"
    open_ = pool.partner_screen( kept, measures, vectors, 0.95, 1.5, "concat" )
    assert open_[ ( "work_alike", "py" ) ] == [ "p.a1", "p.a3" ], "a lookalike limit above 1 keeps every candidate, so a1 and a3 find each other"


def test_the_screen_leaves_out_a_seed_with_no_vector_row():
    kept, measures, vectors = screen_world()
    got = pool.partner_screen( kept, measures, vectors, 0.0, 0.5, "concat" )
    assert "p.norow" not in got[ ( "work_alike", "py" ) ] and "p.norow" not in got[ ( "cross_language", "py" ) ]
    assert got[ ( "cross_language", "py" ) ] == [ "p.a1", "p.a2", "p.a3" ] and got[ ( "cross_language", "ts" ) ] == [ "w.t1", "w.t2" ]


def test_the_screen_looks_only_at_the_top_neighbours_and_an_empty_target_pool_passes_nothing():
    kept, measures, vectors = screen_world()
    short = pool.partner_screen( kept, measures, vectors, 0.0, 0.5, "concat", top=1 )
    assert "p.a1" not in short[ ( "work_alike", "py" ) ], "the seed itself and its lookalike fill the two nearest places"
    assert "p.a2" in short[ ( "work_alike", "py" ) ], "top=1 reads the seed and one neighbour, so a2 finds its partner at the second place"
    py_only = [ r for r in kept if r[ "lang" ] == "py" ]
    assert pool.partner_screen( py_only, measures, vectors, 0.0, 0.5, "concat" )[ ( "cross_language", "py" ) ] == []


def test_a_cell_pool_with_a_screen_keeps_only_the_passed_seeds_of_the_two_screened_kinds():
    kept  = [ rec( "p.one", "pkg/p.py", "one" ), rec( "p.two", "pkg/p.py", "two" ), rec( "p.three", "pkg/p.py", "three" ), rec( "w.a", "web/w.ts", "a", "ts" ) ]
    twins = { "p.one": [ "p.two" ], "p.two": [ "p.one" ] }
    ids   = { r[ "id" ] for r in kept }
    screen = { ( "work_alike", "py" ): [ "p.one" ], ( "cross_language", "py" ): [ "p.three", "p.two" ], ( "work_alike", "ts" ): [], ( "cross_language", "ts" ): [ "w.a" ] }
    cells = pool.cell_pool( kept, twins, ids, screen )
    assert cells[ ( "work_alike", "py" ) ] == [ "p.one" ] and cells[ ( "cross_language", "py" ) ] == [ "p.three", "p.two" ]
    assert ( "work_alike", "ts" ) not in cells and cells[ ( "cross_language", "ts" ) ] == [ "w.a" ]
    assert cells[ ( "near_copy", "py" ) ] == [ "p.one", "p.two" ], "near_copy and nothing are not screened"
    assert pool.cell_pool( kept, twins, ids ) == pool.cell_pool( kept, twins, ids, None )


def pair_world( second ):
    """Return ( kept, measures, vectors ) for two unlike py symbols; y gets the vector."""
    kept     = [ rec( "p.x", "pkg/p.py", "x" ), rec( "p.y", "pkg/p.py", "y" ) ]
    measures = { "p.x": pool.Measure( 40, frozenset( { 1, 2 } ) ), "p.y": pool.Measure( 40, frozenset( { 3, 4 } ) ) }
    return kept, measures, Vecs( { "p.x": [ 1.0, 0.0 ], "p.y": second } )


def test_a_seed_whose_partner_scores_exactly_the_floor_passes():
    kept, measures, vectors = pair_world( [ 0.0, 1.0 ] )
    assert pool.partner_screen( kept, measures, vectors, 0.0, 0.5, "concat" )[ ( "work_alike", "py" ) ] == [ "p.x", "p.y" ], "orthogonal unit vectors score exactly 0.0"
    assert pool.partner_screen( kept, measures, vectors, 0.001, 0.5, "concat" )[ ( "work_alike", "py" ) ] == []


def test_a_zero_vector_scores_zero_with_every_partner_instead_of_not_a_number():
    kept, measures, vectors = pair_world( [ 0.0, 0.0 ] )
    got = pool.partner_screen( kept, measures, vectors, 0.0, 0.5, "concat" )
    assert got[ ( "work_alike", "py" ) ] == [ "p.x", "p.y" ], "a zero row has cosine 0.0, which reaches a floor of 0.0; a not-a-number never compares true"
