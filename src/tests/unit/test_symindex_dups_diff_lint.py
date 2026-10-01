"""
Unit tests for cosa.repo.symindex.dups, diff and wiki_lint, and the command line.
"""
import json
import pathlib

import pytest

from cosa.repo.symindex import __main__ as cli
from cosa.repo.symindex import build as bd
from cosa.repo.symindex import dups as dp
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.diff import diff_generations, diff_symbols
from cosa.repo.symindex.wiki_lint import queue
from tests.unit.symindex_helpers import make_repo

REPO_ROOT = sp.git_toplevel( pathlib.Path( __file__ ).resolve().parent )

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
    """Renamed clone of alpha: same structure, other names and constants."""
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


def tiny():
    return 1
'''


def _clone_repo( tmp_path ):
    root = tmp_path / "clones"; root.mkdir()
    ( root / "c.py" ).write_text( CLONES, encoding="utf-8" )
    return sp.spec_for( root ), [ root / "c.py" ]


def test_exact_clone_renamed_clone_and_distinct_lookalike_are_told_apart( tmp_path ):
    spec, files = _clone_repo( tmp_path )
    rep = dp.find_duplicates( spec, files, min_nodes=20, threshold=0.6 )
    assert rep[ "exact" ] == [ [ "c.alpha", "c.beta" ] ]                        # renamed clone: exact under name/constant erasure
    near_pairs = [ tuple( n[ "ids" ] ) for n in rep[ "near" ] ]
    assert ( "c.alpha", "c.gamma" ) in near_pairs                               # one extra call: near, not exact
    assert not any( "c.distinct" in p for p in near_pairs )                     # the look-alike is not reported
    assert not any( "c.tiny" in p for g in rep[ "exact" ] for p in g )          # below min_nodes
    assert rep[ "provenance" ][ "considered" ] == 4 and "structural only" in rep[ "provenance" ][ "kind" ]
    assert all( 0.6 <= n[ "jaccard" ] <= 1 for n in rep[ "near" ] )


def test_near_pass_does_not_repeat_an_exact_pair_and_respects_threshold( tmp_path ):
    spec, files = _clone_repo( tmp_path )
    rep = dp.find_duplicates( spec, files, min_nodes=20, threshold=0.6 )
    assert ( "c.alpha", "c.beta" ) not in [ tuple( n[ "ids" ] ) for n in rep[ "near" ] ]
    none = dp.find_duplicates( spec, files, min_nodes=20, threshold=1.0 )
    assert none[ "near" ] == []


def test_dups_skips_unparseable_files_and_handles_class_methods( tmp_path ):
    root = tmp_path / "r"; root.mkdir()
    ( root / "bad.py" ).write_text( "def x(:\n", encoding="utf-8" )
    ( root / "__init__.py" ).write_text( "class K:\n    def m( self, xs ):\n        t = 0\n        for x in xs:\n            t += x\n        return t\n    def n( self, ys ):\n        u = 0\n        for y in ys:\n            u += y\n        return u\n", encoding="utf-8" )
    spec = sp.spec_for( root )
    rep = dp.find_duplicates( spec, [ root / "bad.py", root / "__init__.py" ], min_nodes=10 )
    assert rep[ "exact" ] == [ [ "K.m", "K.n" ] ]


def _gen( tmp_path, name, extra=None, edit=None ):
    root = make_repo( tmp_path / name )
    if extra: ( root / "pkg" / "extra.py" ).write_text( extra, encoding="utf-8" )
    if edit: ( root / "pkg" / "util.py" ).write_text( ( root / "pkg" / "util.py" ).read_text( encoding="utf-8" ).replace( "a + b", edit ), encoding="utf-8" )
    return bd.build( root, tmp_path / f"out-{name}" )[ "gen_dir" ]


def test_diff_lists_added_removed_and_changed_public_symbols( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    old = _gen( tmp_path, "o" )
    new = _gen( tmp_path, "n", extra="def added_one():\n    return 1\n\n\ndef _private_added():\n    return 2\n", edit="a - b" )
    d = diff_generations( old, new )
    assert d[ "added" ] == [ "repo:pkg.extra.added_one" ] and d[ "removed" ] == []
    assert [ c[ "id" ] for c in d[ "changed" ] ] == [ "repo:pkg.util.public_fn" ]
    da = diff_generations( old, new, all_symbols=True )
    assert da[ "added" ] == [ "repo:pkg.extra._private_added", "repo:pkg.extra.added_one" ]     # --all sees private helpers
    back = diff_generations( new, old )
    assert back[ "removed" ] == [ "repo:pkg.extra.added_one" ]


def test_diff_reports_an_algorithm_change_once_instead_of_every_symbol( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    old = _gen( tmp_path, "o" ); new = _gen( tmp_path, "n" )
    head = json.loads( ( new / "header.json" ).read_text( encoding="utf-8" ) ); head[ "pin_algorithm" ] = "py9.99"
    ( new / "header.json" ).write_text( json.dumps( head ), encoding="utf-8" )
    assert diff_generations( old, new ) == { "algorithm_changed": { "was": head[ "pin_algorithm" ].replace( "py9.99", json.loads( ( old / "header.json" ).read_text( encoding="utf-8" ) )[ "pin_algorithm" ] ), "now": "py9.99" } }


def test_diff_symbols_compares_pins_by_id():
    o = [ { "id": "a", "pin": "1" }, { "id": "b", "pin": "2" }, { "id": "c", "pin": "3" } ]
    n = [ { "id": "a", "pin": "1" }, { "id": "b", "pin": "9" }, { "id": "d", "pin": "4" } ]
    assert diff_symbols( o, n ) == { "added": [ "d" ], "removed": [ "c" ], "changed": [ { "id": "b", "was": "2", "now": "9" } ] }


WIKI_INDEX = "# Index\n- [[good-page]]\n- [[alg-page]]\n- [[dangling-page]]\n"


def _page( wiki, name, pins, algo=None ):
    ( wiki / "capabilities" ).mkdir( parents=True, exist_ok=True )
    front = "---\ncovers:\n" + "".join( f"  - {q}@{h}\n" for q, h in pins ) + ( f"pin_algorithm: {algo}\n" if algo else "" ) + "---\nbody\n"
    ( wiki / "capabilities" / f"{name}.md" ).write_text( front, encoding="utf-8" )


def _live( gen ): return { r[ "id" ]: r[ "pin" ] for r in bd.read_symbols( gen ) }


def _algo( gen ): return bd.read_header( gen )[ "pin_algorithm" ]


def test_every_seeded_wiki_finding_fires( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    gen  = _gen( tmp_path, "g" ); live = _live( gen )
    wiki = tmp_path / "wiki"; wiki.mkdir()
    ( wiki / "INDEX.md" ).write_text( WIKI_INDEX, encoding="utf-8" )
    _page( wiki, "good-page", [ ( "repo:pkg.util.public_fn", live[ "repo:pkg.util.public_fn" ] ) ], algo=_algo( gen ) )
    _page( wiki, "stale-page", [ ( "repo:pkg.util.Widget", "0000000000" ) ], algo=_algo( gen ) )   # stale + unindexed
    _page( wiki, "dangling-page", [ ( "repo:pkg.util.gone_fn", "1111111111" ) ], algo=_algo( gen ) )
    kinds = { ( f[ "kind" ], f.get( "page" ), f.get( "symbol" ) ) for f in queue( wiki, gen ) }
    assert ( "stale", "stale-page", "repo:pkg.util.Widget" ) in kinds
    assert ( "unindexed", "stale-page", None ) in kinds
    assert ( "dangling", "dangling-page", "repo:pkg.util.gone_fn" ) in kinds
    assert ( "orphan", None, "repo:pkg.util.Widget.render" ) in kinds                               # package "repo:pkg"... has a page, symbol uncovered
    assert not any( k[ 0 ] in ( "stale", "unindexed", "dangling" ) and k[ 1 ] == "good-page" for k in kinds )


def test_orphans_are_counted_per_package_until_the_package_has_a_page( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    gen  = _gen( tmp_path, "g" )
    out  = queue( tmp_path / "no-wiki-at-all", gen )                                               # empty wiki: no crash
    assert out and all( f[ "kind" ] == "orphan_package" for f in out )
    assert { f[ "package" ] for f in out } == { "pkg.util", "pkg.router", "web.app", "web.lib" }
    assert sum( f[ "count" ] for f in out ) == len( bd.read_symbols( gen ) )


def test_pin_algorithm_change_is_decided_once_before_any_page_and_suppresses_stale( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    gen  = _gen( tmp_path, "g" ); wiki = tmp_path / "wiki"; wiki.mkdir()
    ( wiki / "INDEX.md" ).write_text( WIKI_INDEX, encoding="utf-8" )
    cur  = _algo( gen )
    _page( wiki, "alg-page", [ ( "repo:pkg.util.public_fn", "0000000000" ), ( "repo:pkg.util.Widget", "0000000000" ) ], algo="py0.0" )
    _page( wiki, "a-first-page", [ ( "repo:pkg.util.render_none", "0000000000" ) ], algo=cur )       # sorts BEFORE the mismatched page
    out = queue( wiki, gen )
    changed = [ f for f in out if f[ "kind" ] == "pin_algorithm_changed" ]
    assert len( changed ) == 1 and changed[ 0 ][ "pages" ] == [ "alg-page" ] and changed[ 0 ][ "was" ] == [ "py0.0" ] and changed[ 0 ][ "now" ] == cur
    assert not any( f[ "kind" ] == "stale" for f in out )                                          # not even for the page that sorts first
    _page( wiki, "alg-page", [ ( "repo:pkg.util.public_fn", "0000000000" ) ], algo=cur )
    assert any( f[ "kind" ] == "stale" for f in queue( wiki, gen ) )                                # same algorithm everywhere: stale is reported again


def test_a_pinned_page_without_a_pin_algorithm_is_one_finding_not_one_stale_per_symbol( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    gen = _gen( tmp_path, "g" ); wiki = tmp_path / "wiki"; wiki.mkdir()
    ( wiki / "INDEX.md" ).write_text( WIKI_INDEX, encoding="utf-8" )
    _page( wiki, "good-page", [ ( "repo:pkg.util.public_fn", "0000000000" ), ( "repo:pkg.util.Widget", "0000000000" ) ] )     # no pin_algorithm line
    out = queue( wiki, gen )
    missing = [ f for f in out if f[ "kind" ] == "pin_algorithm_missing" ]
    assert len( missing ) == 1 and missing[ 0 ][ "pages" ] == [ "good-page" ]
    assert not any( f[ "kind" ] == "stale" for f in out )


def test_page_without_frontmatter_pins_nothing( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    gen = _gen( tmp_path, "g" ); wiki = tmp_path / "wiki"; ( wiki / "capabilities" ).mkdir( parents=True )
    ( wiki / "capabilities" / "bare.md" ).write_text( "no frontmatter\n", encoding="utf-8" )
    assert [ f[ "kind" ] for f in queue( wiki, gen ) if f.get( "page" ) ] == [ "unindexed" ]


def _main( argv, capsys ):
    rc = cli.main( argv ); cap = capsys.readouterr(); return rc, cap.out, cap.err


def test_cli_build_fresh_dups_lint_and_diff( tmp_path, monkeypatch, capsys ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    root = make_repo( tmp_path ); out = tmp_path / "out"
    rc, o, e = _main( [ "build", "--root", str( root ), "--out", str( out ) ], capsys )
    assert rc == 0 and "symbols" in o
    assert _main( [ "fresh", "--root", str( root ), "--out", str( out ) ], capsys )[ 0 ] == 0
    ( root / "pkg" / "x.py" ).write_text( "def x():\n    return 1\n", encoding="utf-8" )
    assert _main( [ "fresh", "--root", str( root ), "--out", str( out ) ], capsys )[ 0 ] == 1
    rc, o, e = _main( [ "lint", "--root", str( root ), "--out", str( out ), "--wiki", str( tmp_path / "w" ) ], capsys )
    assert rc == 1 and json.loads( o.splitlines()[ 0 ] )[ "kind" ] == "orphan_package"
    ( root / "pkg" / "clone1.py" ).write_text( CLONES, encoding="utf-8" )
    rc, o, e = _main( [ "dups", "--root", str( root ), "--min-nodes", "20", "--threshold", "0.6" ], capsys )
    assert rc == 1 and "EXACT x2: pkg.clone1.alpha == pkg.clone1.beta" in o and "NEAR" in o and "exact groups" in e
    rc, o, e = _main( [ "dups", "--root", str( root ), "--min-nodes", "20", "--json" ], capsys )
    assert json.loads( o )[ "exact" ]
    rc, o, e = _main( [ "dups", "--root", str( root ), "--min-nodes", "9999" ], capsys )
    assert rc == 0 and o == ""
    g1 = bd.current_generation( out ); bd.build( root, out ); g2 = bd.current_generation( out )
    rc, o, e = _main( [ "diff", str( g1 ), str( g2 ), "--all" ], capsys )
    assert rc == 0 and "added" in json.loads( o )


def test_cli_build_with_a_missing_tool_exits_3_and_warns( tmp_path, monkeypatch, capsys ):
    root = make_repo( tmp_path )
    def boom( *a, **k ): raise bd.DependencyMissing( "node" )
    monkeypatch.setattr( bd, "find_node", boom ); monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    rc, o, e = _main( [ "build", "--root", str( root ), "--out", str( tmp_path / "out" ) ], capsys )
    assert rc == 3 and "WARNING missing dependencies: node" in e


def test_cli_lint_defaults_to_the_repo_wiki_and_a_clean_wiki_exits_0( tmp_path, monkeypatch, capsys ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    root = tmp_path / "tiny"; root.mkdir()
    ( root / "a.py" ).write_text( "def a():\n    return 1\n", encoding="utf-8" )
    wiki = root / "src" / "docs" / "wiki"; ( wiki / "capabilities" ).mkdir( parents=True )
    gen  = bd.build( root, tmp_path / "out" )[ "gen_dir" ]; live = _live( gen )
    ( wiki / "INDEX.md" ).write_text( "- [[cap]]\n", encoding="utf-8" )
    ( wiki / "capabilities" / "cap.md" ).write_text( "---\ncovers:\n  - " + f"tiny:a.a@{live[ 'tiny:a.a' ]}" + f"\npin_algorithm: {_algo( gen )}\n---\n", encoding="utf-8" )
    rc, o, e = _main( [ "lint", "--root", str( root ), "--out", str( tmp_path / "out" ) ], capsys )
    assert rc == 0 and o == ""


def test_cli_uses_the_cwd_git_toplevel_by_default( tmp_path, monkeypatch, capsys ):
    monkeypatch.chdir( pathlib.Path( __file__ ).resolve().parent ); monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    monkeypatch.setattr( cli, "spec_for", lambda root: ( _ for _ in () ).throw( StopIteration( str( root ) ) ) )
    with pytest.raises( StopIteration ) as e: cli.main( [ "fresh" ] )
    assert pathlib.Path( str( e.value ) ) == REPO_ROOT
