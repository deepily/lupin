"""
Command line for the symbol index:  python -m cosa.repo.symindex <command>

  - build   [--root R] [--out D]            build and publish the index; exit 3 if a tool was missing
  - fresh   [--root R] [--out D]            exit 0 when the published index matches the tree, else 1
  - dups    [--root R] [--min-nodes N] [--threshold T] [--json]
  - diff    OLD_GEN NEW_GEN [--all]         symbols added, removed or changed between two generations
  - lint    [--root R] [--out D] [--wiki W] wiki findings as JSON lines; exit 1 when any
"""
import argparse
import json
import pathlib
import sys

from cosa.repo.symindex import build as build_mod
from cosa.repo.symindex.diff import diff_generations
from cosa.repo.symindex.dups import DEFAULT_MIN_NODE, DEFAULT_THRESH, find_duplicates
from cosa.repo.symindex.paths import default_out_dir
from cosa.repo.symindex.spec import git_toplevel, iter_files, spec_for
from cosa.repo.symindex.wiki_lint import queue


def _parser():
    """Ensures: returns the argparse parser for every command."""
    ap  = argparse.ArgumentParser( prog="python -m cosa.repo.symindex", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    sub = ap.add_subparsers( dest="cmd", required=True )
    for name in ( "build", "fresh", "dups", "lint" ):
        p = sub.add_parser( name )
        p.add_argument( "--root" )
        if name != "dups": p.add_argument( "--out" )
    sub.choices[ "dups" ].add_argument( "--min-nodes", type=int, default=DEFAULT_MIN_NODE )
    sub.choices[ "dups" ].add_argument( "--threshold", type=float, default=DEFAULT_THRESH )
    sub.choices[ "dups" ].add_argument( "--json", action="store_true" )
    sub.choices[ "lint" ].add_argument( "--wiki" )
    d = sub.add_parser( "diff" )
    d.add_argument( "old" ); d.add_argument( "new" ); d.add_argument( "--all", action="store_true" )
    return ap


def main( argv=None ):
    """
    Run one command.

    Ensures:
        - returns the process exit code: 0 ok, 1 findings / stale, 3 a build finished with a missing tool
    """
    a = _parser().parse_args( argv )
    if a.cmd == "diff":
        print( json.dumps( diff_generations( a.old, a.new, a.all ), indent=2 ) ); return 0
    root = pathlib.Path( a.root ) if a.root else git_toplevel()
    spec = spec_for( root )
    if a.cmd == "build":
        res = build_mod.build( root, a.out ); h = res[ "header" ]
        print( f"symindex: {h[ 'counts' ][ 'symbols' ]} symbols, {h[ 'counts' ][ 'routes' ]} routes -> {res[ 'gen_dir' ]}" )
        if h[ "missing_dependencies" ]:
            print( f"symindex: WARNING missing dependencies: {', '.join( h[ 'missing_dependencies' ] )}", file=sys.stderr ); return 3
        return 0
    if a.cmd == "dups":
        rep = find_duplicates( spec, iter_files( spec, spec.py_roots, { ".py" } ), a.min_nodes, a.threshold )
        if a.json: print( json.dumps( rep, indent=2 ) )
        else:
            for g in rep[ "exact" ]: print( f"EXACT x{len( g )}: " + " == ".join( g ) )
            for n in rep[ "near" ]: print( f"NEAR {n[ 'jaccard' ]}: " + " ~ ".join( n[ "ids" ] ) )
        print( f"symindex: {len( rep[ 'exact' ] )} exact groups, {len( rep[ 'near' ] )} near pairs", file=sys.stderr )
        return 1 if rep[ "exact" ] or rep[ "near" ] else 0
    out   = pathlib.Path( a.out ) if a.out else default_out_dir( root )
    if a.cmd == "fresh": return 0 if build_mod.is_fresh( spec, out ) else 1
    gen   = build_mod.ensure( root, out )
    wiki  = pathlib.Path( a.wiki ) if a.wiki else root / "src" / "docs" / "wiki"
    items = queue( wiki, gen )
    for item in items: print( json.dumps( item ) )
    return 1 if items else 0


if __name__ == "__main__":
    sys.exit( main() )
