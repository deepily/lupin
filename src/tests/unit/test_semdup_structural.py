"""Unit tests for semdup.structural: jscpd reports and dups pairs mapped to definitions."""
import json
import os
import pathlib
import shutil
import types

import pytest

import cosa.utils.util as cu
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import extract as ex
from cosa.repo.semdup import structural as st
from cosa.repo.symindex import dups, js_index
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

JS_COPY = """function {name}( items, factor ) {{
    let total = 0;
    const scaled = [];
    for ( const item of items ) {{
        if ( item > 10 ) {{
            scaled.push( item * factor );
        }} else {{
            scaled.push( item + factor );
        }}
    }}
    for ( const s of scaled ) {{
        total += s;
    }}
    return total;
}}
"""

JSCPD_CFG = { "jscpd": { "version": "5.3.3", "min_tokens": 50, "min_lines": 5, "max_size": "5mb", "chosen_in": "test" } }


def nested_tree( tmp_path ):
    """Write the fixture under client/ of a nested root and one.ts under other/; return both."""
    fixture = json.loads( ( HERE / "semdup_jscpd_fixture.json" ).read_text( encoding="utf-8" ) )
    root    = tmp_path / "nest"
    paths   = []
    extra   = [ ( "other/one.ts", fixture[ "src/one.ts" ] ), ( "client/lib/a.js", JS_COPY.format( name="sumUp" ) ), ( "client/lib/b.js", JS_COPY.format( name="sumDown" ) ) ]
    for name, text in [ ( f"client/{n}", t ) for n, t in fixture.items() ] + extra:
        p = root / name
        p.parent.mkdir( parents=True, exist_ok=True )
        p.write_text( text, encoding="utf-8" )
        paths.append( p )
    return root, paths


def named_pairs( root, paths, report ):
    """Return the ( names, size ) of each pair parse_jscpd finds, as sorted 'file#name' strings."""
    defs = ex.extract_tree( root, paths, "new" )[ "definitions" ]
    name = { d[ "id" ]: f"{d[ 'file' ]}#{d[ 'name' ]}" for d in defs }
    return sorted( ( sorted( name[ i ] for i in p[ "ids" ] ), p[ "size" ] ) for p in st.parse_jscpd( report, defs, 0.5 ) )


def test_the_live_jscpd_finds_exactly_the_expected_pairs_in_a_nested_root_and_keeps_only_the_given_folders(tmp_path):
    launcher = pathlib.Path( cu.get_project_root() ) / "node_modules" / ".bin" / "jscpd"
    assert launcher.is_file(), f"{launcher} is missing: node_modules is linked by link-worktree-artifacts.sh, or run npm ci"
    assert shutil.which( "node" ) is not None or os.environ.get( "LUPIN_NODE" ), "node is missing"
    root, paths = nested_tree( tmp_path )
    inside      = named_pairs( root, paths, st.run_jscpd( root, [ "client" ], JSCPD_CFG ) )
    both        = named_pairs( root, paths, st.run_jscpd( root, [ "client", "other" ], JSCPD_CFG ) )
    ts_pair = ( [ "client/src/one.ts#scaleAndSum", "client/src/two.ts#scaleThenSum" ], 84 )
    js_pair = ( [ "client/lib/a.js#sumUp", "client/lib/b.js#sumDown" ], 72 )
    assert inside == [ js_pair, ts_pair ]
    assert both == [ js_pair, ts_pair, ( [ "client/src/one.ts#scaleAndSum", "other/one.ts#scaleAndSum" ], 87 ) ]
    assert named_pairs( root, paths, st.run_jscpd( root, [ "client" ], at_tokens( 80 ) ) ) == [ ts_pair ]
    assert named_pairs( root, paths, st.run_jscpd( root, [ "client" ], at_tokens( 90 ) ) ) == []


def at_tokens( n ):
    """Return the test configuration with jscpd's minimum token count set to n."""
    return { "jscpd": { **JSCPD_CFG[ "jscpd" ], "min_tokens": n } }


def test_run_jscpd_passes_the_frozen_thresholds_and_both_script_formats_on_the_command_line(tmp_path, monkeypatch):
    calls = fake_jscpd( monkeypatch, tmp_path, "5.3.3", 0, True )
    st.run_jscpd( tmp_path, [ "x" ], { "jscpd": { "version": "5.3.3", "min_tokens": 61, "min_lines": 7, "max_size": "7mb", "chosen_in": "t" } } )
    cmd, kw = calls[ -1 ]
    assert cmd[ cmd.index( "--min-tokens" ) + 1 ] == "61" and cmd[ cmd.index( "--min-lines" ) + 1 ] == "7" and cmd[ cmd.index( "--max-size" ) + 1 ] == "7mb"
    assert cmd[ cmd.index( "--format" ) + 1 ] == "typescript,javascript" and cmd[ -1 ] == "." and kw[ "cwd" ] == str( tmp_path )


def test_a_file_over_jscpds_default_size_is_skipped_without_a_word_unless_the_frozen_max_size_allows_it(tmp_path):
    """The monolith is 1.4 MB and jscpd skips files over 100 kb, reporting no clone and no error."""
    body = JS_COPY.format( name="sumUp" ) + "\n" + JS_COPY.format( name="sumDown" ) + "\n" + "// padding line to pass the default size limit of jscpd\n" * 3000
    path = tmp_path / "client" / "big.js"
    path.parent.mkdir( parents=True )
    path.write_text( body, encoding="utf-8" )
    assert path.stat().st_size > 100 * 1024
    allowed = st.run_jscpd( tmp_path, [ "client" ], JSCPD_CFG )
    default = st.run_jscpd( tmp_path, [ "client" ], { "jscpd": { **JSCPD_CFG[ "jscpd" ], "max_size": "100kb" } } )
    assert len( allowed[ "duplicates" ] ) >= 1 and default[ "duplicates" ] == []


def test_run_jscpd_names_a_missing_launcher_and_a_missing_node(tmp_path, monkeypatch):
    monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
    with pytest.raises( err.SemdupError ) as bare: st.run_jscpd( tmp_path, [ "x" ], JSCPD_CFG )
    assert bare.value.code == err.DEPENDENCY_MISSING and "node_modules" in bare.value.detail
    ( tmp_path / "node_modules" / ".bin" ).mkdir( parents=True )
    ( tmp_path / "node_modules" / ".bin" / "jscpd" ).write_text( "", encoding="utf-8" )
    def no_node(): raise js_index.DependencyMissing( "node", "gone" )
    monkeypatch.setattr( js_index, "find_node", no_node )
    with pytest.raises( err.SemdupError ) as nonode: st.run_jscpd( tmp_path, [ "x" ], JSCPD_CFG )
    assert nonode.value.code == err.DEPENDENCY_MISSING and "node" in nonode.value.detail


def fake_jscpd( monkeypatch, tmp_path, version, returncode, write_report, report='{"duplicates": []}' ):
    """Point run_jscpd at a launcher stub and a fake subprocess that answers version and scan."""
    ( tmp_path / "node_modules" / ".bin" ).mkdir( parents=True )
    ( tmp_path / "node_modules" / ".bin" / "jscpd" ).write_text( "", encoding="utf-8" )
    monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( js_index, "find_node", lambda: "node" )
    calls = []
    def run( cmd, **kwargs ):
        calls.append( ( cmd, kwargs ) )
        if cmd[ -1 ] == "--version": return types.SimpleNamespace( stdout=f"jscpd {version}\n", stderr="", returncode=0 )
        if write_report: ( pathlib.Path( cmd[ cmd.index( "--output" ) + 1 ] ) / "jscpd-report.json" ).write_text( report, encoding="utf-8" )
        return types.SimpleNamespace( stdout="", stderr="boom", returncode=returncode )
    monkeypatch.setattr( st.subprocess, "run", run )
    return calls


def test_run_jscpd_refuses_another_installed_version(tmp_path, monkeypatch):
    fake_jscpd( monkeypatch, tmp_path, "5.4.0", 0, True )
    with pytest.raises( err.SemdupError ) as caught: st.run_jscpd( tmp_path, [ "x" ], JSCPD_CFG )
    assert caught.value.code == err.DEPENDENCY_MISSING and "5.3.3" in caught.value.detail and "5.4.0" in caught.value.detail


def test_run_jscpd_keeps_a_folder_name_whole_so_a_longer_name_that_starts_with_it_is_not_kept(tmp_path, monkeypatch):
    kept   = clone( ( "client/a.ts", 1, 9 ), ( "client/b.ts", 1, 9 ) )
    longer = clone( ( "clientele/a.ts", 1, 9 ), ( "clientele/b.ts", 1, 9 ) )
    fake_jscpd( monkeypatch, tmp_path, "5.3.3", 0, True, report=json.dumps( { "duplicates": [ kept, longer ] } ) )
    assert st.run_jscpd( tmp_path, [ "client/" ], JSCPD_CFG )[ "duplicates" ] == [ kept ]


@pytest.mark.parametrize( "returncode, write_report", [ ( 1, True ), ( 0, False ) ] )
def test_run_jscpd_names_a_failed_run_or_a_missing_report(tmp_path, monkeypatch, returncode, write_report):
    fake_jscpd( monkeypatch, tmp_path, "5.3.3", returncode, write_report )
    with pytest.raises( err.SemdupError ) as caught: st.run_jscpd( tmp_path, [ "x" ], JSCPD_CFG )
    assert caught.value.code == err.RUN_INCOMPLETE and "boom" in caught.value.detail


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


# ---- script_clones --------------------------------------------------------------------------------------------

SHAPE_A = "function {name}( items ) {{\n    const out = items.map( x => x + 1 ).filter( x => x > 2 );\n    let total = 0;\n    for ( const o of out ) {{\n        if ( o > 3 ) {{ total += o; }}\n    }}\n    return total;\n}}\n"
SHAPE_B = "function {name}( items ) {{\n    try {{\n        while ( items.length > 0 ) {{\n            items.pop();\n            if ( items.length === 3 ) {{ break; }}\n        }}\n    }} catch ( e ) {{\n        return [ e, items ];\n    }}\n    return items;\n}}\n"


def script_tree( tmp_path, text ):
    """Write one script file and return ( root, spec, file, definitions )."""
    root = tmp_path / "tree"
    path = root / "client" / "m.js"
    path.parent.mkdir( parents=True )
    path.write_text( text, encoding="utf-8" )
    return root, sp.spec_for( root ), path, ex.extract_tree( root, [ path ], "server" )[ "definitions" ]


def test_script_clones_pairs_definitions_of_one_shape_under_the_dups_source_and_leaves_a_different_shape_alone(tmp_path):
    root, spec, path, defs = script_tree( tmp_path, SHAPE_A.format( name="one" ) + SHAPE_A.format( name="two" ) + SHAPE_B.format( name="other" ) )
    by_name = { d[ "name" ]: d[ "id" ] for d in defs }
    got     = st.script_clones( spec, [ path ], defs, 25 )
    assert [ ( p[ "ids" ], p[ "source" ] ) for p in got ] == [ ( sorted( [ by_name[ "one" ], by_name[ "two" ] ] ), "dups" ) ] and got[ 0 ][ "size" ] > 0
    assert by_name[ "other" ] not in got[ 0 ][ "ids" ]


def test_script_clones_numbers_a_repeated_name_as_dups_does_so_the_second_copy_is_not_lost(tmp_path):
    root, spec, path, defs = script_tree( tmp_path, SHAPE_A.format( name="same" ) + SHAPE_A.format( name="same" ).replace( "o > 3", "o > 4" ) )
    assert [ d[ "name" ] for d in defs ] == [ "same", "same" ]
    keys = st._script_keys( defs )
    assert list( keys ) == [ "client/m.js#same", "client/m.js#same~2" ] and list( keys.values() ) == [ d[ "id" ] for d in defs ]
    assert [ p[ "ids" ] for p in st.script_clones( spec, [ path ], defs, 25 ) ] == [ sorted( d[ "id" ] for d in defs ) ]


def test_script_clones_refuses_an_id_dups_names_that_the_definitions_do_not_hold(tmp_path, monkeypatch):
    root, spec, path, defs = script_tree( tmp_path, SHAPE_A.format( name="one" ) )
    monkeypatch.setattr( dups, "find_duplicates", lambda *a, **k: { "exact": [ [ "client/m.js#one", "client/m.js#ghost" ] ], "near": [] } )
    with pytest.raises( ValueError, match="ghost" ): st.script_clones( spec, [ path ], defs, 25 )
