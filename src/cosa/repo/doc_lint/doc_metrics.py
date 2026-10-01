"""
Documentation metrics per package: tokens and marker rates, before and after a change.

A package is a directory prefix. Its text is every Python docstring and every Dart doc block
under it. Counting is done by marker_counts, so this tool and the linters cannot disagree.
Tokens are the words marker_counts counts. Output is JSON or a markdown table.
"""

import argparse
import json
import subprocess
import sys

from .cli import in_scope
from .dartdoc_lint import doc_blocks
from .docstring_lint import extract_docstrings
from .marker_counts import MARKER_COLUMNS, add_counts, count_markers, empty_counts, rates_per_thousand
from .word_list import configure_root

SUFFIXES = ( ".py", ".dart" )


def _git( root, *args ):
    """
    Run git in root and return stdout.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the decoded stdout

    Raises:
        - RuntimeError naming the git error when the command fails
    """
    res = subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git {' '.join( args )} failed: {res.stderr.strip()}" )
    return res.stdout


def package_files( root, package, rev=None ):
    """
    List the in-scope .py and .dart files under a package at a revision.

    Requires:
        - root is a git working tree; package is a repo-relative directory
        - rev is a revision, or None for the files tracked now

    Ensures:
        - returns sorted repo-relative paths that cli.in_scope accepts
        - the population comes from git, never from a disk walk

    Raises:
        - RuntimeError from git when the listing fails
    """
    args = [ "ls-tree", "-r", "--name-only", rev, "--", package ] if rev else [ "ls-files", "--", package ]
    return sorted( p for p in _git( root, *args ).split( "\n" ) if p.endswith( SUFFIXES ) and in_scope( p ) )


def _read( root, rev, path ):
    """
    Read one file at a revision, or from the working tree when rev is None.

    Requires:
        - path is tracked at that revision, or on disk

    Ensures:
        - returns the text

    Raises:
        - RuntimeError from git, or OSError from the disk read
    """
    if rev is None:
        with open( f"{root}/{path}", encoding="utf-8" ) as handle: return handle.read()
    return _git( root, "show", f"{rev}:{path}" )


def doc_texts( path, source ):
    """
    List the documentation texts in one file.

    Requires:
        - path ends in .py or .dart; source is its text

    Ensures:
        - returns the docstrings of a .py file or the doc blocks of a .dart file
        - a .py file that does not parse returns None, so the caller can count it

    Raises:
        - nothing
    """
    if path.endswith( ".dart" ): return [ text for _, text in doc_blocks( source ) ]
    try:
        return [ text for _, _, _, text in extract_docstrings( source ) ]
    except SyntaxError:
        return None


def package_metrics( root, package, rev=None ):
    """
    Measure one package at one revision.

    Requires:
        - root is a git working tree whose word list configure_root can find

    Ensures:
        - returns { files, unparsed, tokens, counts, rates }; counts holds the summed raw markers
        - rates are per 1,000 tokens, computed from the summed counts

    Raises:
        - RuntimeError from git when a listing or read fails
    """
    total, unparsed, paths = empty_counts(), 0, package_files( root, package, rev )
    for path in paths:
        texts = doc_texts( path, _read( root, rev, path ) )
        if texts is None:
            unparsed += 1
            continue
        for text in texts: add_counts( total, count_markers( text ) )
    return { "files": len( paths ), "unparsed": unparsed, "tokens": total[ "words" ], "counts": total, "rates": rates_per_thousand( total ) }


def compare( before, after ):
    """
    Judge one package's before and after metrics.

    Requires:
        - both are package_metrics results

    Ensures:
        - returns True when every marker rate is at or below its before value and tokens are lower
        - a package with no tokens before cannot get lower, so it is never improved

    Raises:
        - nothing
    """
    return after[ "tokens" ] < before[ "tokens" ] and all( after[ "rates" ][ c ] <= before[ "rates" ][ c ] for c in MARKER_COLUMNS )


def build_report( root, packages, base, head=None ):
    """
    Measure every package at base and at head.

    Requires:
        - packages is a list of repo-relative directories; base is a revision
        - head is a revision, or None for the working tree

    Ensures:
        - returns { package: { before, after, improved } }

    Raises:
        - RuntimeError from git when a listing or read fails
    """
    report = {}
    for package in packages:
        before, after = package_metrics( root, package, base ), package_metrics( root, package, head )
        report[ package ] = { "before" : before, "after" : after, "improved" : compare( before, after ) }
    return report


def render_table( report ):
    """
    Render the report as a markdown table, one row per package.

    Requires:
        - report is the dict build_report returns

    Ensures:
        - returns a str with tokens and each marker rate as "before -> after", and an improved column

    Raises:
        - nothing
    """
    head = [ "package", "tokens", *MARKER_COLUMNS, "improved" ]
    rows = [ "| " + " | ".join( head ) + " |", "| " + " | ".join( "---" for _ in head ) + " |" ]
    for package, r in report.items():
        cells = [ f"{r[ 'before' ][ 'tokens' ]} -> {r[ 'after' ][ 'tokens' ]}" ]
        cells += [ f"{r[ 'before' ][ 'rates' ][ c ]} -> {r[ 'after' ][ 'rates' ][ c ]}" for c in MARKER_COLUMNS ]
        rows.append( "| " + " | ".join( [ package, *cells, "yes" if r[ "improved" ] else "no" ] ) + " |" )
    return "\n".join( rows ) + "\n"


def main( argv=None, out=None ):
    """
    Command-line entry: print the per-package metrics.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - prints the markdown table, or JSON with --format json
        - returns 1 when --strict is given and any package is not improved, otherwise 0

    Raises:
        - RuntimeError from git when a listing or read fails
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Per-package documentation tokens and marker rates, before and after" )
    parser.add_argument( "packages", nargs="+", help="repo-relative package directories" )
    parser.add_argument( "--base", required=True, help="revision for the before numbers" )
    parser.add_argument( "--head", help="revision for the after numbers; default is the working tree" )
    parser.add_argument( "--format", choices=( "table", "json" ), default="table" )
    parser.add_argument( "--strict", action="store_true", help="exit 1 when any package is not improved" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    args = parser.parse_args( argv )
    configure_root( args.repo_root )
    report = build_report( args.repo_root, args.packages, args.base, args.head )
    if args.format == "json":
        json.dump( report, out, indent=2 )
        out.write( "\n" )
    else:
        out.write( render_table( report ) )
    return 1 if args.strict and not all( r[ "improved" ] for r in report.values() ) else 0


if __name__ == "__main__": sys.exit( main() )  # pragma: no cover -- script entry, main() is tested
