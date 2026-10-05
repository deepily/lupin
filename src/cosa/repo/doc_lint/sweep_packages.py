"""
Package lister for the docs-rewrite sweep: which packages to rewrite first.

Lists every Python package with its docstring count and its linter findings, ordered by
findings per docstring, highest first. The population comes from git, and the files that sit in
no package are reported on their own.
"""

import argparse
import json
import subprocess
import sys

from .cli import tracked_files
from .docstring_lint import extract_docstrings, lint_source
from .marker_counts import count_markers
from .text_rules import Finding
from .word_list import configure_root

COUNT_KEYS = ( "files", "docstrings", "flagged", "findings", "words_flagged", "unparsed", "unreadable" )


def _git( root, *args ):
    """
    Run git in root and return stdout.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the decoded stdout, stripped

    Raises:
        - RuntimeError naming the git error when the command fails
    """
    res = subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git {' '.join( args )} failed: {res.stderr.strip()}" )
    return res.stdout.strip()


def split_packages( paths ):
    """
    Split repo-relative .py paths into packages and files that sit in no package.

    Requires:
        - paths is a list of posix repo-relative paths ending in .py

    Ensures:
        - a package is a directory holding an __init__.py, and owns only the files directly in it
        - returns ( packages, orphans ): packages maps directory to its sorted files, orphans is the sorted rest
        - a file in the repo root has directory "" and is an orphan unless the root holds an __init__.py

    Raises:
        - nothing
    """
    by_dir = {}
    for path in paths:
        directory = path.rpartition( "/" )[ 0 ]
        by_dir.setdefault( directory, [] ).append( path )
    packages = { d: sorted( files ) for d, files in by_dir.items() if any( f.rpartition( "/" )[ 2 ] == "__init__.py" for f in files ) }
    orphans  = sorted( f for d, files in by_dir.items() if d not in packages for f in files )
    return packages, orphans


def measure_file( path, source, root ):
    """
    Count one file's docstrings and the linter findings on them.

    Requires:
        - path is the repo-relative path, source its text, root the working tree the linter reads

    Ensures:
        - returns a dict with the COUNT_KEYS, files being 1
        - flagged counts docstrings that hold at least one finding, found by line range
        - words_flagged is the word count of those docstrings
        - a file that does not parse has no docstrings, one finding and unparsed 1

    Raises:
        - nothing
    """
    counts   = dict.fromkeys( COUNT_KEYS, 0 )
    counts[ "files" ] = 1
    findings = lint_source( path, source, root )
    counts[ "findings" ] = len( findings )
    try:
        docstrings = extract_docstrings( source )
    except SyntaxError:
        counts[ "unparsed" ] = 1
        return counts
    counts[ "docstrings" ] = len( docstrings )
    lines = [ f.line for f in findings ]
    for _, _, first_line, text in docstrings:
        last_line = first_line + text.count( "\n" )
        if any( first_line <= line <= last_line for line in lines ):
            counts[ "flagged" ]       += 1
            counts[ "words_flagged" ] += count_markers( text )[ "words" ]
    return counts


def _read_counts( root, path ):
    """
    Measure one tracked file read from the working tree.

    Requires:
        - path is tracked under root

    Ensures:
        - returns measure_file's counts
        - a file that cannot be read, such as one tracked but deleted from the tree, or not UTF-8, has one finding, no docstrings and unreadable 1, never unparsed

    Raises:
        - nothing
    """
    try:
        with open( f"{root}/{path}", encoding="utf-8" ) as handle: source = handle.read()
    except ( OSError, UnicodeDecodeError ):
        counts = dict.fromkeys( COUNT_KEYS, 0 )
        counts.update( files=1, findings=1, unreadable=1 )
        return counts
    return measure_file( path, source, root )


def _sum_counts( rows ):
    """
    Add the COUNT_KEYS of several rows.

    Requires:
        - rows is a list of dicts that carry every COUNT_KEYS entry

    Ensures:
        - returns a dict of the sums; an empty list gives zeros

    Raises:
        - nothing
    """
    return { key: sum( row[ key ] for row in rows ) for key in COUNT_KEYS }


def density( counts ):
    """
    Return findings per docstring.

    Requires:
        - counts carries findings and docstrings

    Ensures:
        - returns findings divided by docstrings, or 0.0 when there are no docstrings

    Raises:
        - nothing
    """
    return counts[ "findings" ] / counts[ "docstrings" ] if counts[ "docstrings" ] else 0.0


def sweep( root ):
    """
    Measure every package and every file in no package.

    Requires:
        - root is a git working tree that holds the word list

    Ensures:
        - the population is git ls-files for .py, minus tests and src/rnd, as cli.in_scope decides
        - returns a dict with sha, tree_dirty, packages, orphans and totals
        - packages are ordered by findings per docstring, highest first, ties by path
        - totals carry packages, orphans and all, each with the COUNT_KEYS and a density

    Raises:
        - RuntimeError from git when a listing fails
    """
    configure_root( root )
    packages, orphan_paths = split_packages( tracked_files( root, ( ".py", ) ) )
    rows = []
    for directory, files in packages.items():
        row = { "package": directory or ".", **_sum_counts( [ _read_counts( root, f ) for f in files ] ) }
        row[ "density" ] = density( row )
        rows.append( row )
    rows.sort( key=lambda r: ( -r[ "density" ], r[ "package" ] ) )
    orphans = [ { "path": p, **_read_counts( root, p ) } for p in orphan_paths ]
    totals  = { "packages": _sum_counts( rows ), "orphans": _sum_counts( orphans ) }
    totals[ "packages" ][ "packages" ] = len( rows )
    totals[ "all" ] = _sum_counts( [ totals[ "packages" ], totals[ "orphans" ] ] )
    for part in totals.values(): part[ "density" ] = density( part )
    return {
        "sha"        : _git( root, "rev-parse", "HEAD" ),
        "tree_dirty" : bool( _git( root, "status", "--porcelain", "--untracked-files=no" ) ),
        "packages"   : rows,
        "orphans"    : orphans,
        "totals"     : totals
    }


def format_report( result ):
    """
    Render a sweep result as text.

    Requires:
        - result comes from sweep

    Ensures:
        - returns one line per package in the given order, then the orphan files, then the totals and the sha
        - the sha line says when tracked files had uncommitted edits

    Raises:
        - nothing
    """
    lines = [ "package  docstrings  flagged  findings  per-docstring  words-flagged" ]
    for row in result[ "packages" ]:
        lines.append( f"{row[ 'package' ]}  {row[ 'docstrings' ]}  {row[ 'flagged' ]}  {row[ 'findings' ]}  {row[ 'density' ]:.2f}  {row[ 'words_flagged' ]}" )
    lines.append( f"{len( result[ 'orphans' ] )} files in no package" )
    for row in result[ "orphans" ]:
        lines.append( f"  {row[ 'path' ]}  {row[ 'docstrings' ]}  {row[ 'flagged' ]}  {row[ 'findings' ]}" )
    for name, part in result[ "totals" ].items():
        lines.append( f"total {name}: {part[ 'files' ]} files, {part[ 'docstrings' ]} docstrings, {part[ 'flagged' ]} flagged, {part[ 'findings' ]} findings, {part[ 'density' ]:.2f} per docstring" )
    lines.append( f"ran at {result[ 'sha' ]}" + ( ", tracked files edited since" if result[ "tree_dirty" ] else "" ) )
    return "\n".join( lines ) + "\n"


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - prints the report, or JSON with --json, to out
        - returns 0

    Raises:
        - RuntimeError from git when a listing fails
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="List Python packages by docstring findings per docstring." )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    parser.add_argument( "--json", action="store_true", help="print the result as JSON" )
    args   = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    result = sweep( args.repo_root )
    if args.json:
        json.dump( result, out, indent=2 )
        out.write( "\n" )
    else:
        out.write( format_report( result ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
