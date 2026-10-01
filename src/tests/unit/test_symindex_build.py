"""
Unit tests for cosa.repo.symindex.build: publication, freshness, concurrency, missing tools, Dart hook.
"""
import json
import multiprocessing
import os
import pathlib
import sys
import time
import types

import pytest

from cosa.repo.symindex import build as bd
from cosa.repo.symindex import extractor_contract as ec
from cosa.repo.symindex import js_index as ji
from cosa.repo.symindex import paths as pa
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.errors import DependencyMissing
from tests.unit.symindex_helpers import make_repo

REPO_ROOT = sp.git_toplevel( pathlib.Path( __file__ ).resolve().parent )


@pytest.fixture( autouse=True )
def _typescript_lookup( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )


def test_build_publishes_one_complete_generation_with_every_file( tmp_path ):
    root = make_repo( tmp_path )
    out  = tmp_path / "out"
    res  = bd.build( root, out )
    gen  = res[ "gen_dir" ]
    assert bd.current_generation( out ) == gen.resolve()
    assert sorted( p.name for p in gen.iterdir() ) == [ "header.json", "routes.md", "symbols-all.jsonl", "symbols.jsonl", "symbols.md" ]
    head = bd.read_header( gen )
    assert head[ "pin_algorithm" ].startswith( f"py{sys.version_info.major}.{sys.version_info.minor}.x{bd.EXTRACTOR_LOGIC}/ts" )
    assert head[ "counts" ][ "symbols" ] == len( bd.read_symbols( gen ) ) < len( bd.read_symbols( gen, all_symbols=True ) ) == head[ "counts" ][ "all" ]
    md = ( gen / "symbols.md" ).read_text( encoding="utf-8" ).splitlines()
    assert len( md ) == head[ "counts" ][ "symbols" ]
    assert any( l.startswith( "pkg/util.py::public_fn(a, b=1) -> int — Adds things. [repo:pkg.util.public_fn@" ) for l in md )
    assert any( "web/app.ts::Box.get(k: string): T | undefined — Gets it. [repo:web.app.Box.get@" in l for l in md )
    assert not any( "skipped_in_tests" in l or "skippedDep" in l for l in md )
    assert head[ "symbols_sha" ] and head[ "missing_dependencies" ] == [] and head[ "unparsed" ] == []


def test_a_rebuild_replaces_current_and_prunes_old_generations( tmp_path ):
    root = make_repo( tmp_path )
    out  = tmp_path / "out"
    seen = []
    for i in range( 5 ):
        ( root / "pkg" / f"mod{i}.py" ).write_text( f"def f{i}():\n    return {i}\n", encoding="utf-8" )
        res = bd.build( root, out ); seen.append( res[ "gen_dir" ].name )
        time.sleep( 0.01 )
    gens = [ g.name for g in out.glob( "gen-*" ) ]
    assert len( set( seen ) ) == 5 and len( gens ) == bd.KEEP_GENERATIONS
    assert bd.current_generation( out ).name == seen[ -1 ]
    marker = bd.current_generation( out ) / "marker"; marker.write_text( "kept", encoding="utf-8" )
    bd.build( root, out )                                                       # same tree again: the existing generation is kept, not rewritten
    assert bd.current_generation( out ).name == seen[ -1 ] and marker.read_text( encoding="utf-8" ) == "kept"


def test_current_generation_is_none_before_any_build_and_for_a_dangling_link( tmp_path ):
    assert bd.current_generation( tmp_path / "nothing" ) is None
    out = tmp_path / "o"; out.mkdir(); os.symlink( "gen-missing", out / "current" )
    assert bd.current_generation( out ) is None


def test_freshness_sees_added_deleted_and_edited_files( tmp_path ):
    root = make_repo( tmp_path ); spec = sp.spec_for( root ); out = tmp_path / "out"
    assert bd.is_fresh( spec, out ) is False                                    # nothing published
    bd.build( root, out )
    assert bd.is_fresh( spec, out ) is True
    extra = root / "pkg" / "extra.py"
    extra.write_text( "def e():\n    return 1\n", encoding="utf-8" )
    assert bd.is_fresh( spec, out ) is False                                    # added
    bd.build( root, out ); assert bd.is_fresh( spec, out )
    extra.unlink()
    assert bd.is_fresh( spec, out ) is False                                    # DELETED: the prototype's newer-file check missed this
    bd.build( root, out )
    ( root / "pkg" / "tests" / "test_skip.py" ).write_text( "def other():\n    return 9\n", encoding="utf-8" )
    assert bd.is_fresh( spec, out ) is True                                     # a test edit does not stale the index


def test_ensure_builds_when_missing_or_stale_and_reuses_when_fresh( tmp_path ):
    root = make_repo( tmp_path ); out = tmp_path / "out"
    g1 = bd.ensure( root, out )
    assert g1 == bd.ensure( root, out )
    ( root / "pkg" / "new.py" ).write_text( "def n():\n    return 1\n", encoding="utf-8" )
    assert bd.ensure( root, out ) != g1


def test_default_root_is_the_git_toplevel_of_the_cwd( tmp_path, monkeypatch ):
    root = make_repo( tmp_path )
    monkeypatch.setattr( sp, "git_toplevel", lambda start=None: root )
    gen = bd.ensure( out_dir=tmp_path / "o" )
    assert pathlib.Path( bd.read_header( gen )[ "index_root" ] ) == root
    assert pathlib.Path( bd.build( out_dir=tmp_path / "o2" )[ "header" ][ "index_root" ] ) == root


def test_a_worktree_indexes_its_own_tree_not_the_main_checkout( tmp_path ):
    """The index root is the tree that was asked about, so two trees give two different shas."""
    a = make_repo( tmp_path, "a" ); b = make_repo( tmp_path, "b" )
    ( b / "pkg" / "only_in_b.py" ).write_text( "def only_in_b():\n    return 1\n", encoding="utf-8" )
    ha = bd.build( a, tmp_path / "oa" )[ "header" ]; hb = bd.build( b, tmp_path / "ob" )[ "header" ]
    assert ha[ "symbols_sha" ] != hb[ "symbols_sha" ]
    assert hb[ "index_root" ].endswith( "/b" ) and ha[ "index_root" ].endswith( "/a" )


def _rebuild_loop( root, out, n ):
    for _ in range( n ): bd.build( root, out )


def test_two_processes_rebuilding_never_expose_a_partial_index( tmp_path ):
    root = make_repo( tmp_path ); out = tmp_path / "out"
    bd.build( root, out )
    ctx   = multiprocessing.get_context( "fork" )
    procs = [ ctx.Process( target=_rebuild_loop, args=( root, out, 6 ) ) for _ in range( 2 ) ]
    for p in procs: p.start()
    reads = 0
    while any( p.is_alive() for p in procs ):
        gen = bd.current_generation( out )
        if gen is None: continue
        head = bd.read_header( gen )
        assert head[ "counts" ][ "symbols" ] == len( bd.read_symbols( gen ) )          # a reader always sees a complete generation
        assert len( ( gen / "symbols.md" ).read_text( encoding="utf-8" ).splitlines() ) == head[ "counts" ][ "symbols" ]
        reads += 1
    for p in procs:
        p.join(); assert p.exitcode == 0
    assert reads > 0


def test_missing_node_is_recorded_not_fatal_and_ts_pin_algorithm_is_dropped( tmp_path, monkeypatch ):
    root = make_repo( tmp_path )
    def boom( *a, **k ): raise DependencyMissing( "node" )
    monkeypatch.setattr( bd, "find_node", boom )
    res = bd.build( root, tmp_path / "out" )
    assert res[ "header" ][ "missing_dependencies" ] == [ "node" ]
    assert "ts" not in res[ "header" ][ "pin_algorithm" ]
    assert any( r[ "lang" ] == "py" for r in bd.read_symbols( res[ "gen_dir" ] ) ) and not any( r[ "lang" ] == "ts" for r in bd.read_symbols( res[ "gen_dir" ] ) )


def test_a_tree_without_js_needs_no_node( tmp_path, monkeypatch ):
    root = make_repo( tmp_path )
    for p in ( root / "web" ).iterdir(): p.unlink()
    def boom( *a, **k ): raise AssertionError( "node must not be looked up" )
    monkeypatch.setattr( bd, "find_node", boom ); monkeypatch.setattr( ji, "find_node", boom )
    res = bd.build( root, tmp_path / "out" )
    assert res[ "header" ][ "missing_dependencies" ] == [] and res[ "header" ][ "pin_algorithm" ] == f"py{sys.version_info.major}.{sys.version_info.minor}.x{bd.EXTRACTOR_LOGIC}"


def _dart_repo( tmp_path ):
    root = tmp_path / "mobile"; ( root / "lib" / "core" ).mkdir( parents=True )
    ( root / "pubspec.yaml" ).write_text( "name: m\n", encoding="utf-8" )
    ( root / "lib" / "core" / "x.dart" ).write_text( "class Foo { void bar() {} }\n", encoding="utf-8" )
    return root


def _fake_dart( monkeypatch, extract, algo="dart9.9/fake", check=lambda root: None ):
    mod = types.ModuleType( "cosa.repo.symindex.dart_extractor" ); mod.extract_dart = extract; mod.PIN_ALGORITHM = algo; mod.check_dependencies = check
    monkeypatch.setitem( sys.modules, "cosa.repo.symindex.dart_extractor", mod )
    import cosa.repo.symindex as pkg
    monkeypatch.setattr( pkg, "dart_extractor", mod, raising=False )
    return mod


def test_dart_records_are_validated_hashed_namespaced_and_algorithm_recorded( tmp_path, monkeypatch ):
    root  = _dart_repo( tmp_path ); seen = {}
    def fake( r, files, data_root, unparsed=None ):
        seen.update( root=r, files=[ f.name for f in files ], data_root=data_root )
        return [ { "lang": "dart", "file": "lib/core/x.dart", "name": "Foo", "kind": "class", "sig": "", "doc": "A Foo.", "pin_text": "class Foo { }", "line": 1, "public": True },
                 { "lang": "dart", "file": "lib/core/x.dart", "name": "Foo.bar", "kind": "method", "sig": "()", "doc": "", "pin": "abcdef0123", "line": 1, "public": True },
                 { "lang": "dart", "file": "lib/core/x.dart", "name": "_p", "kind": "function", "sig": "()", "doc": "", "pin_text": "x", "line": 2, "public": False } ]
    _fake_dart( monkeypatch, fake )
    res  = bd.build( root, tmp_path / "out" )
    syms = bd.read_symbols( res[ "gen_dir" ] ); all_ = bd.read_symbols( res[ "gen_dir" ], True )
    assert seen[ "files" ] == [ "x.dart" ] and seen[ "data_root" ] == pa.data_dir( root )
    assert [ s[ "id" ] for s in syms ] == [ "mobile:lib.core.x.Foo", "mobile:lib.core.x.Foo.bar" ]
    assert syms[ 0 ][ "pin" ] == bd._hash_text( "class Foo { }" ) and syms[ 1 ][ "pin" ] == "abcdef0123"
    assert "pin_text" not in syms[ 0 ] and len( all_ ) == 3
    assert res[ "header" ][ "pin_algorithm" ].endswith( "/dart9.9/fake" ) and res[ "header" ][ "unparsed" ] == []


def test_a_dart_file_the_extractor_skips_is_listed_in_the_header_unparsed( tmp_path, monkeypatch ):
    root = _dart_repo( tmp_path ); ( root / "lib" / "core" / "bad.dart" ).write_text( "class {{{\n", encoding="utf-8" )
    def fake( r, files, data_root, unparsed=None ):
        names = sorted( f.name for f in files )
        for f in files:
            if f.name == "bad.dart": unparsed.append( f.relative_to( r ).as_posix() )
        return [ { "lang": "dart", "file": "lib/core/x.dart", "name": "Foo", "kind": "class", "sig": "", "doc": "A Foo.", "pin_text": "c", "line": 1, "public": True } ] if names else []
    _fake_dart( monkeypatch, fake )
    res = bd.build( root, tmp_path / "out" )
    assert res[ "header" ][ "unparsed" ] == [ "lib/core/bad.dart" ]
    assert [ s[ "id" ] for s in bd.read_symbols( res[ "gen_dir" ] ) ] == [ "mobile:lib.core.x.Foo" ]          # the good file is still indexed


def test_dart_dependency_missing_and_absent_extractor_are_recorded( tmp_path, monkeypatch ):
    root = _dart_repo( tmp_path )
    def gone( root ): raise DependencyMissing( "dart" )
    def never( *a ): raise AssertionError( "extract_dart must not run when a tool is missing" )
    _fake_dart( monkeypatch, never, check=gone )
    res = bd.build( root, tmp_path / "o1" )
    assert res[ "header" ][ "missing_dependencies" ] == [ "dart" ] and res[ "header" ][ "pin_algorithm" ] == f"py{sys.version_info.major}.{sys.version_info.minor}.x{bd.EXTRACTOR_LOGIC}"
    import cosa.repo.symindex as pkg
    monkeypatch.delattr( pkg, "dart_extractor" )
    monkeypatch.setitem( sys.modules, "cosa.repo.symindex.dart_extractor", None )          # import raises ImportError
    assert bd.build( root, tmp_path / "o2" )[ "header" ][ "missing_dependencies" ] == [ "dart_extractor" ]


def test_a_bad_dart_record_fails_loudly( tmp_path, monkeypatch ):
    root = _dart_repo( tmp_path )
    _fake_dart( monkeypatch, lambda r, f, d, unparsed=None: [ { "lang": "dart" } ] )
    with pytest.raises( ValueError, match="missing key" ): bd.build( root, tmp_path / "out" )


def test_validate_record_rejects_each_contract_violation():
    good = { "lang": "dart", "file": "a", "name": "A", "kind": "class", "sig": "", "doc": "", "line": 1, "public": True, "pin": "0123456789" }
    assert ec.validate_record( good ) is None
    with pytest.raises( ValueError, match="unknown kind" ): ec.validate_record( { **good, "kind": "weird" } )
    with pytest.raises( ValueError, match="line" ): ec.validate_record( { **good, "line": 0 } )
    with pytest.raises( ValueError, match="line" ): ec.validate_record( { **good, "line": "1" } )
    with pytest.raises( ValueError, match="public" ): ec.validate_record( { **good, "public": 1 } )
    no_pin = dict( good ); del no_pin[ "pin" ]
    with pytest.raises( ValueError, match="pin" ): ec.validate_record( no_pin )
    assert ec.validate_record( { **no_pin, "pin_text": "x" } ) is None


def test_default_out_dir_for_lupin_and_for_other_roots( tmp_path, monkeypatch ):
    lupin = tmp_path / "lupin"
    for d in ( "src/cosa", "src/lupin_mcp" ): ( lupin / d ).mkdir( parents=True )
    assert pa.default_out_dir( lupin ) == lupin / "src" / "docs" / "index"
    monkeypatch.setattr( "lupin_cli.claude_code.hooks.lib.heartbeat_hold.fleet_data_root", lambda r: tmp_path / "data" / pathlib.Path( r ).name )
    other = tmp_path / "mobile"
    assert pa.default_out_dir( other ) == tmp_path / "data" / "mobile" / "reuse-review" / "index" / "mobile"
    assert pa.data_dir( other ) == tmp_path / "data" / "mobile" / "reuse-review"


def test_installing_a_missing_tool_makes_a_published_index_stale_and_ensure_rebuilds( tmp_path, monkeypatch ):
    """An index built while typescript was absent must not stay fresh once it is installed."""
    root = make_repo( tmp_path ); spec = sp.spec_for( root ); out = tmp_path / "out"
    monkeypatch.delenv( "LUPIN_ROOT" )                                                   # no typescript reachable
    g1 = bd.ensure( root, out )
    assert bd.read_header( g1 )[ "missing_dependencies" ] == [ "typescript" ] and not any( r[ "lang" ] == "ts" for r in bd.read_symbols( g1 ) )
    assert bd.is_fresh( spec, out ) is True                                              # nothing changed yet
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )                                 # typescript appears
    assert bd.is_fresh( spec, out ) is False
    g2 = bd.ensure( root, out )
    assert g2 != g1                                                                      # a new generation, not the stale one renamed
    assert bd.read_header( g2 )[ "missing_dependencies" ] == [] and any( r[ "lang" ] == "ts" for r in bd.read_symbols( g2 ) )
    assert bd.is_fresh( spec, out ) is True


def test_a_changed_pin_algorithm_makes_a_published_index_stale( tmp_path, monkeypatch ):
    root = make_repo( tmp_path ); spec = sp.spec_for( root ); out = tmp_path / "out"
    bd.build( root, out )
    assert bd.is_fresh( spec, out ) is True
    monkeypatch.setattr( bd, "typescript_version", lambda d: "0.0.1" )                   # the compiler was upgraded
    assert bd.is_fresh( spec, out ) is False


def test_environment_reports_dart_tool_states( tmp_path, monkeypatch ):
    root = _dart_repo( tmp_path ); spec = sp.spec_for( root )
    _fake_dart( monkeypatch, lambda *a, **k: [], algo="dart1/x" )
    assert bd.environment( spec ) == ( f"py{sys.version_info.major}.{sys.version_info.minor}.x{bd.EXTRACTOR_LOGIC}/dart1/x", [] )


def test_a_change_of_extractor_logic_version_is_a_pin_algorithm_change( tmp_path, monkeypatch ):
    root = make_repo( tmp_path ); spec = sp.spec_for( root ); out = tmp_path / "out"
    bd.build( root, out )
    assert bd.is_fresh( spec, out ) is True
    monkeypatch.setattr( bd, "EXTRACTOR_LOGIC", "999" )                                   # someone edited extract_python and bumped it
    assert bd.is_fresh( spec, out ) is False
    assert ".x999" in bd.read_header( bd.ensure( root, out ) )[ "pin_algorithm" ]


def test_prune_removes_only_old_tmp_directories( tmp_path ):
    old = tmp_path / ".tmp-1"; new = tmp_path / ".tmp-2"; old.mkdir(); new.mkdir()
    ancient = time.time() - 7200
    os.utime( old, ( ancient, ancient ) )
    bd._prune( tmp_path, "gen-none" )
    assert not old.exists() and new.exists()


def test_the_tree_root_is_passed_to_check_dependencies_so_a_bundled_sdk_counts( tmp_path, monkeypatch ):
    root = _dart_repo( tmp_path ); seen = []
    _fake_dart( monkeypatch, lambda *a: [], check=lambda r: seen.append( r ) )
    bd.environment( sp.spec_for( root ) )
    assert seen == [ root.resolve() ]


def _extractor_sources():
    here = pathlib.Path( bd.__file__ )
    return tuple( here.with_name( n ).read_text( encoding="utf-8" ) for n in ( "py_index.py", "ts_extract.js", "dart_extract.dart" ) )


def test_the_extractor_logic_version_follows_code_not_comments():
    py = 'def f( a ):\n    """doc"""\n    return a + 1\n'
    js = "// c\nfunction g() { return 1; }\n"
    dart = "// c\nint g() { return 1; }\n"
    base = bd.logic_version( py, js, dart )
    assert len( base ) == 6
    assert bd.logic_version( py.replace( "doc", "a new docstring" ).replace( "a + 1", "a  +  1" ), "/* x */\n" + js + "// more\n", "  // x\n" + dart + "/// more\n" ) == base
    assert bd.logic_version( py.replace( "a + 1", "a + 2" ), js, dart ) != base                   # a code edit to the Python extractor
    assert bd.logic_version( py, js.replace( "return 1", "return 2" ), dart ) != base               # a code edit to the JS extractor
    assert bd.logic_version( py, js, dart.replace( "return 1", "return 2" ) ) != base               # a code edit to the Dart extractor
    assert bd.EXTRACTOR_LOGIC == bd.logic_version( *_extractor_sources() )                         # the module constant is computed from all three real files


def test_editing_the_dart_extractor_source_makes_a_built_index_stale( tmp_path, monkeypatch ):
    py, js, dart = _extractor_sources()
    root = make_repo( tmp_path ); spec = sp.spec_for( root ); out = tmp_path / "out"
    bd.build( root, out )
    assert bd.is_fresh( spec, out ) is True                                                         # control: the constant still matches the built index
    monkeypatch.setattr( bd, "EXTRACTOR_LOGIC", bd.logic_version( py, js, dart + "// a comment\n" ) )
    assert bd.is_fresh( spec, out ) is True                                                         # a comment edit leaves it fresh
    monkeypatch.setattr( bd, "EXTRACTOR_LOGIC", bd.logic_version( py, js, dart.replace( "!n.startsWith( '_' )", "n.isNotEmpty", 1 ) ) )
    assert bd.is_fresh( spec, out ) is False                                                        # a code edit to dart_extract.dart makes it stale
