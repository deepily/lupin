"""Unit tests for semdup.structural: jscpd reports and dups pairs mapped to definitions."""
import json
import pathlib

import pytest

import cosa.utils.util as cu
from cosa.repo.semdup import extract as ex
from cosa.repo.semdup import structural as st
from cosa.repo.symindex import dups
from cosa.repo.symindex import spec as sp

HERE = pathlib.Path( cu.get_project_root() ) / "src" / "tests" / "unit"

CLONES = '''
def alpha( items ):
    out = []
    for item in items:
        if item > 10:
            out.append( item * 2 )
        else:
            out.append( item + 1 )
    total = 0
    for o in out:
        total += o
    return total


def beta( rows ):
    acc = []
    for row in rows:
        if row > 99:
            acc.append( row * 7 )
        else:
            acc.append( row + 5 )
    s = 0
    for a in acc:
        s += a
    return s


def gamma( items ):
    out = []
    for item in items:
        if item > 10:
            out.append( item * 2 )
        else:
            out.append( item + 1 )
    total = 0
    for o in out:
        total += o
    print( total )
    return total


def distinct( path ):
    with open( path ) as fh:
        data = fh.read()
    parts = data.split( "," )
    cleaned = [ p.strip() for p in parts if p ]
    return {"n": len( cleaned ), "first": cleaned[ 0 ] if cleaned else None, "all": cleaned, "path": path, "raw": data}
'''


def definition( did, file, line, end_line, nodes=50 ):
    """Build the part of a definition record that structural reads."""
    return { "id": did, "file": file, "line": line, "end_line": end_line, "nodes": nodes }


def clone( first, second, tokens=80 ):
    """Build a jscpd clone from two ( file, start, end ) fragments."""
    return { "firstFile": { "name": first[ 0 ], "start": first[ 1 ], "end": first[ 2 ] }, "secondFile": { "name": second[ 0 ], "start": second[ 1 ], "end": second[ 2 ] }, "tokens": tokens }


def tree( tmp_path, files ):
    """Write the files under a fresh root; return the root and the paths in order."""
    root = tmp_path / "repo"
    root.mkdir( parents=True )
    paths = []
    for name, text in files.items():
        p = root / name
        p.write_text( text, encoding="utf-8" )
        paths.append( p )
    return root, paths


# ---- jscpd ------------------------------------------------------------------------------------------------------

def test_the_real_jscpd_report_pairs_the_two_clone_functions_and_not_the_lookalikes(tmp_path):
    fixture = json.loads( ( HERE / "semdup_jscpd_fixture.json" ).read_text( encoding="utf-8" ) )
    report  = json.loads( ( HERE / "semdup_jscpd_report_5.3.3.json" ).read_text( encoding="utf-8" ) )
    root    = tmp_path / "tree"
    paths   = []
    for name, text in fixture.items():
        p = root / name
        p.parent.mkdir( parents=True, exist_ok=True )
        p.write_text( text, encoding="utf-8" )
        paths.append( p )
    defs = ex.extract_tree( root, paths, "new" )[ "definitions" ]
    ids  = { f"{d[ 'file' ]}#{d[ 'name' ]}": d[ "id" ] for d in defs }
    assert sorted( k.split( "#" )[ 1 ] for k in ids ) == [ "distinct", "lead", "scaleAndSum", "scaleThenSum", "small" ]
    pairs = st.parse_jscpd( report, defs, 0.5 )
    assert pairs == [ { "ids": sorted( [ ids[ "src/one.ts#scaleAndSum" ], ids[ "src/two.ts#scaleThenSum" ] ] ), "size": 84, "source": "jscpd" } ]


@pytest.mark.parametrize( "start, end, linked", [ ( 1, 49, False ), ( 1, 50, True ), ( 51, 100, True ), ( 52, 100, False ) ] )
def test_a_fragment_covering_49_percent_of_a_definition_links_nothing_and_50_percent_links( start, end, linked ):
    defs   = [ definition( "big", "a.ts", 1, 100 ), definition( "other", "b.ts", 1, 10 ) ]
    report = { "duplicates": [ clone( ( "a.ts", start, end ), ( "b.ts", 1, 10 ) ) ] }
    assert ( st.parse_jscpd( report, defs, 0.5 ) != [] ) is linked


def test_a_fragment_spanning_two_definitions_links_both_and_one_touching_a_neighbour_by_a_line_does_not():
    defs   = [ definition( "one", "a.ts", 1, 10 ), definition( "two", "a.ts", 11, 20 ), definition( "edge", "a.ts", 20, 40 ), definition( "far", "b.ts", 1, 20 ) ]
    report = { "duplicates": [ clone( ( "a.ts", 1, 20 ), ( "b.ts", 1, 20 ) ) ] }
    assert [ p[ "ids" ] for p in st.parse_jscpd( report, defs, 0.5 ) ] == [ [ "far", "one" ], [ "far", "two" ] ]


def test_a_definition_is_not_paired_with_itself_and_a_file_without_definitions_pairs_nothing():
    defs = [ definition( "solo", "a.ts", 1, 30 ) ]
    assert st.parse_jscpd( { "duplicates": [ clone( ( "a.ts", 1, 30 ), ( "a.ts", 1, 30 ) ) ] }, defs, 0.5 ) == []
    assert st.parse_jscpd( { "duplicates": [ clone( ( "a.ts", 1, 30 ), ( "missing.ts", 1, 30 ) ) ] }, defs, 0.5 ) == []
    assert st.parse_jscpd( { "duplicates": [] }, defs, 0.5 ) == []


def test_a_pair_found_by_two_clones_keeps_the_larger_size_and_pairs_come_largest_first():
    defs = [ definition( "a", "a.ts", 1, 10 ), definition( "b", "b.ts", 1, 10 ), definition( "c", "c.ts", 1, 10 ) ]
    report = { "duplicates": [ clone( ( "a.ts", 1, 10 ), ( "b.ts", 1, 10 ), 60 ), clone( ( "b.ts", 1, 10 ), ( "a.ts", 1, 10 ), 90 ), clone( ( "a.ts", 1, 10 ), ( "c.ts", 1, 10 ), 70 ) ] }
    assert [ ( p[ "ids" ], p[ "size" ] ) for p in st.parse_jscpd( report, defs, 0.5 ) ] == [ ( [ "a", "b" ], 90 ), ( [ "a", "c" ], 70 ) ]


def test_the_larger_size_wins_whichever_clone_reports_it_first():
    defs = [ definition( "a", "a.ts", 1, 10 ), definition( "b", "b.ts", 1, 10 ) ]
    report = { "duplicates": [ clone( ( "a.ts", 1, 10 ), ( "b.ts", 1, 10 ), 90 ), clone( ( "a.ts", 1, 10 ), ( "b.ts", 1, 10 ), 60 ) ] }
    assert [ p[ "size" ] for p in st.parse_jscpd( report, defs, 0.5 ) ] == [ 90 ]


def test_equal_sizes_are_ordered_by_ids():
    defs   = [ definition( "a", "a.ts", 1, 10 ), definition( "b", "b.ts", 1, 10 ), definition( "c", "c.ts", 1, 10 ) ]
    report = { "duplicates": [ clone( ( "c.ts", 1, 10 ), ( "a.ts", 1, 10 ), 50 ), clone( ( "b.ts", 1, 10 ), ( "a.ts", 1, 10 ), 50 ) ] }
    assert [ p[ "ids" ] for p in st.parse_jscpd( report, defs, 0.5 ) ] == [ [ "a", "b" ], [ "a", "c" ] ]


# ---- Python ------------------------------------------------------------------------------------------------------

def test_python_exact_and_near_pairs_are_mapped_to_definition_ids_with_a_size_that_grows_with_shared_code(tmp_path):
    root, paths = tree( tmp_path, { "c.py": CLONES } )
    defs = ex.extract_tree( root, paths, "new" )[ "definitions" ]
    ids  = { d[ "name" ]: d for d in defs }
    spec = sp.spec_for( root )
    pairs = st.python_clones( spec, paths, defs, 20, threshold=0.6 )
    by_names = { tuple( sorted( ( next( n for n, d in ids.items() if d[ "id" ] == i ) for i in p[ "ids" ] ) ) ): p for p in pairs }
    assert sorted( by_names ) == [ ( "alpha", "beta" ), ( "alpha", "gamma" ), ( "beta", "gamma" ) ]
    assert by_names[ ( "alpha", "beta" ) ][ "size" ] == min( ids[ "alpha" ][ "nodes" ], ids[ "beta" ][ "nodes" ] )              # exact: similarity 1.0
    assert by_names[ ( "alpha", "gamma" ) ][ "size" ] == round( 0.8214 * min( ids[ "alpha" ][ "nodes" ], ids[ "gamma" ][ "nodes" ] ) )
    assert all( p[ "source" ] == "dups" for p in pairs )
    assert [ p[ "size" ] for p in pairs ] == sorted( ( p[ "size" ] for p in pairs ), reverse=True )


def test_the_default_threshold_is_the_dups_near_cut_and_hides_the_082_pair(tmp_path):
    root, paths = tree( tmp_path, { "c.py": CLONES } )
    defs = ex.extract_tree( root, paths, "new" )[ "definitions" ]
    pairs = st.python_clones( sp.spec_for( root ), paths, defs, 20 )
    assert dups.DEFAULT_THRESH == 0.85 and len( pairs ) == 1


def test_min_nodes_keeps_small_definitions_out_of_the_pairs(tmp_path):
    root, paths = tree( tmp_path, { "c.py": CLONES } )
    defs = ex.extract_tree( root, paths, "new" )[ "definitions" ]
    assert st.python_clones( sp.spec_for( root ), paths, defs, 10_000, threshold=0.6 ) == []


def test_a_repeated_dups_id_is_numbered_and_mapped_in_extraction_order(tmp_path):
    twin = "if True:\n    def same( n ):\n        return [ n * k for k in range( 100 ) if k % 3 ]\nelse:\n    def same( n ):\n        return [ n * k for k in range( 200 ) if k % 7 ]\n"
    root, paths = tree( tmp_path, { "t.py": twin } )
    defs = ex.extract_tree( root, paths, "new" )[ "definitions" ]
    assert len( defs ) == 2
    pairs = st.python_clones( sp.spec_for( root ), paths, defs, 5 )
    assert [ p[ "ids" ] for p in pairs ] == [ sorted( [ defs[ 0 ][ "id" ], defs[ 1 ][ "id" ] ] ) ]


def test_a_definition_whose_file_is_not_among_the_paths_is_refused(tmp_path):
    root, paths = tree( tmp_path, { "c.py": CLONES, "d.py": "def d():\n    return 1\n" } )
    defs = ex.extract_tree( root, paths, "new" )[ "definitions" ]
    with pytest.raises( ValueError, match="d.py is not one of the Python files given" ):
        st.python_clones( sp.spec_for( root ), paths[ :1 ], defs, 5 )


def test_a_dups_name_this_package_does_not_have_is_refused(tmp_path):
    root, paths = tree( tmp_path, { "c.py": CLONES } )
    defs = [ d for d in ex.extract_tree( root, paths, "new" )[ "definitions" ] if d[ "name" ] != "beta" ]
    with pytest.raises( ValueError, match="dups reported c.beta" ):
        st.python_clones( sp.spec_for( root ), paths, defs, 20, threshold=0.6 )


# ---- merging -----------------------------------------------------------------------------------------------------

def test_clone_pairs_merges_sources_keeps_the_larger_size_and_orders_by_size_then_ids():
    script = [ { "ids": [ "a", "b" ], "size": 80, "source": "jscpd" }, { "ids": [ "c", "d" ], "size": 40, "source": "jscpd" } ]
    python = [ { "ids": [ "a", "b" ], "size": 95, "source": "dups" }, { "ids": [ "e", "f" ], "size": 40, "source": "dups" } ]
    merged = st.clone_pairs( script, python )
    assert [ ( p[ "ids" ], p[ "size" ], p[ "source" ] ) for p in merged ] == [ ( [ "a", "b" ], 95, "dups" ), ( [ "c", "d" ], 40, "jscpd" ), ( [ "e", "f" ], 40, "dups" ) ]
    assert st.clone_pairs() == [] and st.clone_pairs( [] , [] ) == []
