"""
Documentation metrics per package: tokens and marker rates, before and after a change.

A package is a directory prefix. Its text is every Python docstring and every Dart doc block
under it. Counting is done by marker_counts, so this tool and the linters cannot disagree.
Tokens are the words marker_counts counts. Output is JSON or a markdown table.

Improved means tokens fell, no file stopped parsing, and no marker rate rose, compared exactly
and not on the rounded display values. Deleting documentation lowers tokens too, so a package
reads as improved only for as long as contract_diff and the claim judge also pass.

The dashboard command writes the generated page at DASHBOARD_PATH and checks it. Its rows are the
directories that hold swept files, each owning only its direct files. Its before is BASE_SHA.
"""

import argparse
import json
import os
import subprocess
import sys

from fractions import Fraction

import cosa.utils.util as cu

from .cli import in_scope
from .dartdoc_lint import doc_blocks
from .docstring_lint import extract_docstrings
from .marker_counts import MARKER_COLUMNS, add_counts, count_markers, empty_counts, rates_per_thousand
from .sweep_packages import split_packages
from .swept_scope import is_swept
from .word_list import configure_root

SUFFIXES         = ( ".py", ".dart" )
# The commit the documentation spec measured. The dashboard's before values are computed at it.
BASE_SHA         = "456422492f308a60dafa36325102229947c44147"
DASHBOARD_PATH   = "src/docs/doc-metrics-dashboard.md"
# The values the dashboard check compares. To compare the token count as well, add "tokens" to this tuple.
COMPARED_METRICS = MARKER_COLUMNS
EXIT_OK          = 0
EXIT_ROSE        = 1
EXIT_NOT_CHECKED = 2
EXIT_PAGE_STALE  = 3
MODULE_COMMAND   = "PYTHONPATH=src python3 -m cosa.repo.doc_lint.doc_metrics dashboard"
BEFORE_LINE      = "- Before: commit `{}`"


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
        - with rev None it is the tracked files still on disk plus untracked files git does not ignore, so
          a file the rewrite added or deleted is counted as it stands

    Raises:
        - RuntimeError from git when the listing fails
    """
    if rev:
        names = _git( root, "ls-tree", "-r", "--name-only", "-z", rev, "--", package ).split( "\0" )
    else:
        names  = _git( root, "ls-files", "-z", "--", package ).split( "\0" )
        names += _git( root, "ls-files", "--others", "--exclude-standard", "-z", "--", package ).split( "\0" )
        names  = [ n for n in names if os.path.exists( f"{root}/{n}" ) ]
    return sorted( { p for p in names if p.endswith( SUFFIXES ) and in_scope( p ) } )


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
        - returns { files, paths, unparsed, unparsed_paths, tokens, counts, rates }; counts holds the summed raw markers
        - rates are per 1,000 tokens, computed from the summed counts

    Raises:
        - RuntimeError from git when a listing or read fails
    """
    return files_metrics( root, package_files( root, package, rev ), rev )


def files_metrics( root, paths, rev=None ):
    """
    Measure a list of files at one revision.

    Requires:
        - root is a git working tree whose word list configure_root can find
        - paths is a list of repo-relative .py or .dart files that exist at rev, or on disk when rev is None

    Ensures:
        - returns { files, paths, unparsed, unparsed_paths, tokens, counts, rates }; counts holds the summed raw markers
        - rates are per 1,000 tokens, computed from the summed counts
        - only the listed files are read, so the caller decides whether a subdirectory is included

    Raises:
        - RuntimeError from git, or OSError from a disk read
    """
    total, unparsed = empty_counts(), []
    for path in paths:
        texts = doc_texts( path, _read( root, rev, path ) )
        if texts is None:
            unparsed.append( path )
            continue
        for text in texts: add_counts( total, count_markers( text ) )
    return { "files": len( paths ), "paths": paths, "unparsed": len( unparsed ), "unparsed_paths": unparsed, "tokens": total[ "words" ], "counts": total, "rates": rates_per_thousand( total ) }


def compare( before, after ):
    """
    Judge one package's before and after metrics.

    Requires:
        - both are package_metrics results

    Ensures:
        - returns True when tokens are lower, no file fails to parse that parsed before, and every marker
          rate is at or below its before value
        - the unparsed files are compared as a set of paths, so one file breaking while another is fixed
          is still a refusal
        - rates are compared as exact fractions of the raw counts, so a rise too small to show in the
          one-decimal display still counts
        - a package with no tokens before cannot get lower, so it is never improved

    Raises:
        - nothing
    """
    if after[ "tokens" ] >= before[ "tokens" ] or not set( after[ "unparsed_paths" ] ) <= set( before[ "unparsed_paths" ] ): return False
    return all( after[ "counts" ][ c ] * before[ "tokens" ] <= before[ "counts" ][ c ] * after[ "tokens" ] for c in MARKER_COLUMNS )


def build_report( root, packages, base, head=None ):
    """
    Measure every package at base and at head.

    Requires:
        - packages is a list of repo-relative directories; base is a revision
        - head is a revision, or None for the working tree

    Ensures:
        - returns { package: { before, after, added, removed, improved } }
        - added and removed list the files that are in only one of the two populations

    Raises:
        - RuntimeError from git when a listing or read fails
    """
    report = {}
    for package in packages:
        before, after = package_metrics( root, package, base ), package_metrics( root, package, head )
        report[ package ] = {
            "before"   : before,
            "after"    : after,
            "added"    : sorted( set( after[ "paths" ] ) - set( before[ "paths" ] ) ),
            "removed"  : sorted( set( before[ "paths" ] ) - set( after[ "paths" ] ) ),
            "improved" : compare( before, after )
        }
    return report


def render_table( report ):
    """
    Render the report as a markdown table, one row per package.

    Requires:
        - report is the dict build_report returns

    Ensures:
        - returns a str with files, files that fail to parse, tokens and each marker rate as "before -> after",
          an improved column, and a closing note that fewer tokens can mean deleted documentation

    Raises:
        - nothing
    """
    head = [ "package", "files", "unparsed", "tokens", *MARKER_COLUMNS, "improved" ]
    rows = [ "| " + " | ".join( head ) + " |", "| " + " | ".join( "---" for _ in head ) + " |" ]
    for package, r in report.items():
        cells = [
            f"{r[ 'before' ][ 'files' ]} -> {r[ 'after' ][ 'files' ]} (+{len( r[ 'added' ] )}/-{len( r[ 'removed' ] )})",
            f"{r[ 'before' ][ 'unparsed' ]} -> {r[ 'after' ][ 'unparsed' ]}",
            f"{r[ 'before' ][ 'tokens' ]} -> {r[ 'after' ][ 'tokens' ]}"
        ]
        cells += [ f"{r[ 'before' ][ 'rates' ][ c ]} -> {r[ 'after' ][ 'rates' ][ c ]}" for c in MARKER_COLUMNS ]
        rows.append( "| " + " | ".join( [ package, *cells, "yes" if r[ "improved" ] else "no" ] ) + " |" )
    rows.append( "" )
    rows.append( "Fewer tokens also happen when documentation is deleted; read this table beside contract_diff and the claim judge." )
    return "\n".join( rows ) + "\n"


def swept_at( root, rev=None ):
    """
    List the swept files at a revision, or in the working tree.

    Requires:
        - root is a git working tree; rev is a revision, or None for the tree

    Ensures:
        - returns sorted repo-relative paths, each one accepted by swept_scope.is_swept
        - with rev None it is the tracked files still on disk; an untracked file is not listed

    Raises:
        - RuntimeError from git when the listing fails
    """
    if rev:
        names = _git( root, "ls-tree", "-r", "--name-only", "-z", rev ).split( "\0" )
    else:
        names = [ n for n in _git( root, "ls-files", "-z" ).split( "\0" ) if os.path.exists( f"{root}/{n}" ) ]
    return sorted( n for n in names if is_swept( n ) )


def dashboard_rows( paths ):
    """
    Group swept files into the rows of the dashboard, one row per directory.

    Requires:
        - paths is a sorted list of repo-relative .py paths

    Ensures:
        - returns { directory: { kind, paths } }, the repo root being "."
        - a row owns only the files directly in its directory, so every path is in exactly one row
        - kind is "package" when the directory holds an __init__.py, as sweep_packages.split_packages decides, and "loose" otherwise

    Raises:
        - nothing
    """
    packages, loose = split_packages( paths )
    rows = { directory or ".": { "kind": "package", "paths": files } for directory, files in packages.items() }
    for path in loose:
        rows.setdefault( path.rpartition( "/" )[ 0 ] or ".", { "kind": "loose", "paths": [] } )[ "paths" ].append( path )
    return rows


def metric_value( metrics, name ):
    """
    Return one compared value of a measured side as an exact fraction.

    Requires:
        - metrics carries tokens and counts; name is "tokens" or a MARKER_COLUMNS name

    Ensures:
        - "tokens" gives the token count
        - a marker name gives its raw count divided by the tokens, not the rounded display rate
        - a side with no tokens has every marker rate 0, as rates_per_thousand shows it

    Raises:
        - nothing
    """
    if name == "tokens": return Fraction( metrics[ "tokens" ] )
    return Fraction( metrics[ "counts" ][ name ], metrics[ "tokens" ] ) if metrics[ "tokens" ] else Fraction( 0 )


def risen( before, after ):
    """
    List the compared values that are higher after than before.

    Requires:
        - both are files_metrics results

    Ensures:
        - returns the names in COMPARED_METRICS whose after value is above its before value, in that order
        - COMPARED_METRICS is read on each call
        - an equal value is not a rise

    Raises:
        - nothing
    """
    return [ name for name in COMPARED_METRICS if metric_value( after, name ) > metric_value( before, name ) ]


def build_dashboard( root, base, head=None ):
    """
    Measure every dashboard row at the base commit and at head.

    Requires:
        - root is a git working tree; base is a revision
        - head is a revision, or None for the working tree

    Ensures:
        - returns { base, head, head_is_tree, changed, files_before, files_after, rows }; base and head are full commit ids
        - with head None, head is the commit the tree is checked out at and changed counts the swept files that differ from it
        - rows are those of head, sorted by directory, each { package, kind, before, after, rose, status }
        - a directory with no swept file at base has before None and status "new", and nothing is compared for it
        - status is "rose" when risen names a value, otherwise "ok"

    Raises:
        - RuntimeError from git when a revision does not resolve or a read fails
    """
    base_sha  = _git( root, "rev-parse", "--verify", f"{base}^{{commit}}" ).strip()
    head_sha  = _git( root, "rev-parse", "--verify", f"{head or 'HEAD'}^{{commit}}" ).strip()
    changed   = [] if head else [ n for n in _git( root, "diff", "--name-only", "-z", "HEAD", "--" ).split( "\0" ) if is_swept( n ) ]
    old_paths = swept_at( root, base_sha )
    new_paths = swept_at( root, head )
    old, new  = dashboard_rows( old_paths ), dashboard_rows( new_paths )
    rows      = []
    for name in sorted( new ):
        row    = new[ name ]
        before = files_metrics( root, old[ name ][ "paths" ], base_sha ) if name in old else None
        after  = files_metrics( root, row[ "paths" ], head )
        rose   = [] if before is None else risen( before, after )
        status = "new" if before is None else ( "rose" if rose else "ok" )
        rows.append( { "package": name, "kind": row[ "kind" ], "before": before, "after": after, "rose": rose, "status": status } )
    return {
        "base"         : base_sha,
        "head"         : head_sha,
        "head_is_tree" : head is None,
        "changed"      : len( changed ),
        "files_before" : len( old_paths ),
        "files_after"  : len( new_paths ),
        "rows"         : rows
    }


def _shown( metrics ):
    """
    List the display values of one side of a row.

    Requires:
        - metrics is a files_metrics result, or None for a row with no before

    Ensures:
        - returns files, tokens and the six one-decimal rates, or a dash for each when metrics is None

    Raises:
        - nothing
    """
    if metrics is None: return [ "-" ] * ( 2 + len( MARKER_COLUMNS ) )
    return [ metrics[ "files" ], metrics[ "tokens" ], *( metrics[ "rates" ][ c ] for c in MARKER_COLUMNS ) ]


def dashboard_table( board ):
    """
    Render the rows of a dashboard as lines of aligned text.

    Requires:
        - board is the dict build_dashboard returns

    Ensures:
        - returns a header line and one line per row, cells split by a bar and padded to one width per column
        - each value cell reads "before -> after"; the status cell names the values that rose

    Raises:
        - nothing
    """
    grid = [ [ "package", "kind", "files", "tokens", *MARKER_COLUMNS, "status" ] ]
    for row in board[ "rows" ]:
        cells  = [ f"{b} -> {a}" for b, a in zip( _shown( row[ "before" ] ), _shown( row[ "after" ] ) ) ]
        status = "rose: " + ", ".join( row[ "rose" ] ) if row[ "rose" ] else row[ "status" ]
        grid.append( [ row[ "package" ], row[ "kind" ], *cells, status ] )
    widths = [ max( len( line[ i ] ) for line in grid ) for i in range( len( grid[ 0 ] ) ) ]
    return [ " | ".join( cell.ljust( width ) for cell, width in zip( line, widths ) ).rstrip() for line in grid ]


def render_dashboard( board ):
    """
    Render the dashboard page.

    Requires:
        - board is the dict build_dashboard returns

    Ensures:
        - returns markdown that names both commits, the counts, the compared values and the two commands
        - the rows sit in a fenced text block, so the page stays under the word limit for a reference page
        - the same board always gives the same text; no clock is read

    Raises:
        - nothing
    """
    rows     = board[ "rows" ]
    packages = sum( 1 for r in rows if r[ "kind" ] == "package" )
    after    = f"working tree at commit `{board[ 'head' ]}`" if board[ "head_is_tree" ] else f"commit `{board[ 'head' ]}`"
    lines    = [
        "# Documentation metrics dashboard",
        "",
        "This page is generated by `src/cosa/repo/doc_lint/doc_metrics.py`. An edit made by hand is lost the next time it is written.",
        "",
        "It has one row for each directory that holds swept Python files. `swept_scope.is_swept` decides which files are swept.",
        "A row counts only the files directly in its directory, so a parent row leaves out its subpackages.",
        "Every swept file is counted in exactly one row.",
        "Kind `package` means the directory holds an `__init__.py`, and kind `loose` means it does not.",
        "",
        "Each cell reads before, then after. Tokens are the words `marker_counts` counts in the docstrings.",
        "The six marker columns are rates per 1,000 tokens.",
        "A row marked `new` had no swept file at the before commit, so the check compares nothing for it.",
        "",
        "## What was measured",
        "",
        BEFORE_LINE.format( board[ "base" ] ),
        f"- After: {after}",
        f"- Swept files changed since that commit: {board[ 'changed' ]}",
        f"- Rows: {len( rows )} ({packages} packages, {len( rows ) - packages} loose directories), {sum( 1 for r in rows if r[ 'status' ] == 'new' )} new",
        f"- Swept files: {board[ 'files_before' ]} before, {board[ 'files_after' ]} after",
        "- Compared by the check: " + ", ".join( f"`{name}`" for name in COMPARED_METRICS ),
        f"- Rows where a compared value rose: {sum( 1 for r in rows if r[ 'rose' ] )}",
        "",
        "## Regenerate",
        "",
        "Run both commands from the repo root. The first writes this page and the second checks it.",
        "",
        "```bash",
        f"{MODULE_COMMAND} write --base {board[ 'base' ]}",
        f"{MODULE_COMMAND} check --base {board[ 'base' ]}",
        "```",
        "",
        "The check measures the tree again and does not read the numbers on this page.",
        "It exits 0 when every row is here and no compared value rose. It exits 1 when one rose.",
        "It exits 2 when it could not check. It exits 3 when this page lacks a row or names another before commit.",
        "",
        "## Rows",
        "",
        "```text",
        *dashboard_table( board ),
        "```"
    ]
    return "\n".join( lines ) + "\n"


def page_packages( text ):
    """
    List the row names on a dashboard page.

    Requires:
        - text is the page's markdown

    Ensures:
        - returns the first cell of every line after the header in the fenced text block
        - a page with no such block gives an empty set

    Raises:
        - nothing
    """
    block = text.partition( "```text\n" )[ 2 ].partition( "```" )[ 0 ]
    return { line.split( "|" )[ 0 ].strip() for line in block.split( "\n" )[ 1: ] if line.strip() }


def rise_line( row, name ):
    """
    Describe one risen value of one row with its raw numbers.

    Requires:
        - row is a build_dashboard row whose before is not None; name is one of its risen values

    Ensures:
        - tokens reads as the two counts
        - a marker reads as raw count over tokens on each side, then the two display rates

    Raises:
        - nothing
    """
    before, after = row[ "before" ], row[ "after" ]
    if name == "tokens": return f"ROSE {row[ 'package' ]}: tokens {before[ 'tokens' ]} -> {after[ 'tokens' ]}"
    return f"ROSE {row[ 'package' ]}: {name} {before[ 'counts' ][ name ]}/{before[ 'tokens' ]} -> {after[ 'counts' ][ name ]}/{after[ 'tokens' ]} per token ({before[ 'rates' ][ name ]} -> {after[ 'rates' ][ name ]} per 1,000)"


def check_dashboard( root, base, page ):
    """
    Check the dashboard page against a fresh measurement of the working tree.

    Requires:
        - root is a git working tree; base is a revision; page is the repo-relative path of the page

    Ensures:
        - returns ( exit code, lines to print ); the first line is the count of rows checked, new, risen and not on the page
        - the tree is measured again; of the page only its row names and its before commit are read
        - EXIT_ROSE when a compared value of any row is above its before, each one printed with its raw counts
        - EXIT_PAGE_STALE when no value rose and the page lacks a row of the tree or its Before line does not name the base commit
        - EXIT_OK otherwise

    Raises:
        - OSError when the page cannot be read
        - RuntimeError from git when the base does not resolve or a read fails
    """
    with open( f"{root}/{page}", encoding="utf-8" ) as handle: text = handle.read()
    board  = build_dashboard( root, base )
    names  = page_packages( text )

    missing = [ r[ "package" ] for r in board[ "rows" ] if r[ "package" ] not in names ]
    stale   = BEFORE_LINE.format( board[ "base" ] ) not in text.split( "\n" )
    rose    = [ r for r in board[ "rows" ] if r[ "rose" ] ]
    fresh   = sum( 1 for r in board[ "rows" ] if r[ "status" ] == "new" )
    regen   = f"{MODULE_COMMAND} write --base {board[ 'base' ]}"
    lines   = [ f"doc-metrics dashboard: {len( board[ 'rows' ] )} rows checked against base {board[ 'base' ]}, {fresh} new, {len( rose )} rose, {len( missing )} not on the page; compared: {', '.join( COMPARED_METRICS )}" ]
    lines  += [ rise_line( r, name ) for r in rose for name in r[ "rose" ] ]
    lines  += [ f"MISSING {name}: no row on {page}; regenerate with: {regen}" for name in missing ]
    if stale: lines.append( f"STALE {page}: the page does not name base {board[ 'base' ]}; regenerate with: {regen}" )
    if rose: return EXIT_ROSE, lines
    return ( EXIT_PAGE_STALE if missing or stale else EXIT_OK ), lines


def dashboard_main( argv, out ):
    """
    Run the dashboard command: write the page, or check it.

    Requires:
        - argv is the arguments after the word dashboard; out is a text stream

    Ensures:
        - write measures the tree, or --head, against --base and writes the page at --page under --repo-root
        - check prints check_dashboard's lines and returns its code
        - returns EXIT_NOT_CHECKED with one line naming the cause when git fails or the page cannot be read or written
        - --base defaults to BASE_SHA, read when called

    Raises:
        - SystemExit with code 2 from argparse on a bad argument
    """
    parser = argparse.ArgumentParser( prog="doc_metrics dashboard", description="Write or check the per-package documentation metrics dashboard" )
    parser.add_argument( "action", choices=( "write", "check" ) )
    parser.add_argument( "--base", default=BASE_SHA, help="revision for the before numbers" )
    parser.add_argument( "--head", help="write only: revision for the after numbers; default is the working tree" )
    parser.add_argument( "--page", default=DASHBOARD_PATH, help="repo-relative path of the page" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    parser.add_argument( "--words-root", help="tree that holds the English word list; default is the lupin tree" )
    args  = parser.parse_args( argv )
    root  = args.repo_root
    words = args.words_root or cu.get_project_root()
    configure_root( words )
    try:
        if args.action == "check":
            code, lines = check_dashboard( root, args.base, args.page )
            out.write( "\n".join( lines ) + "\n" )
            return code
        board = build_dashboard( root, args.base, args.head )
        with open( f"{root}/{args.page}", "w", encoding="utf-8" ) as handle: handle.write( render_dashboard( board ) )
    except ( RuntimeError, OSError ) as err:
        out.write( f"doc-metrics dashboard: could not {args.action}: {err}\n" )
        return EXIT_NOT_CHECKED
    out.write( f"doc-metrics dashboard: wrote {args.page}, {len( board[ 'rows' ] )} rows\n" )
    return EXIT_OK


def main( argv=None, out=None ):
    """
    Command-line entry: print the per-package metrics, or run the dashboard command.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - when the first argument is the word dashboard, the rest goes to dashboard_main and its code is returned
        - prints the markdown table, or JSON with --format json
        - the English word list is read from --words-root, or from the lupin tree when that is absent, so a
          repo without the list, such as lupin-mobile, can be measured
        - returns 1 when --strict is given and any package is not improved, otherwise 0

    Raises:
        - RuntimeError from git when a listing or read fails
    """
    out    = out if out is not None else sys.stdout
    argv   = sys.argv[ 1: ] if argv is None else argv
    if argv[ : 1 ] == [ "dashboard" ]: return dashboard_main( argv[ 1: ], out )
    parser = argparse.ArgumentParser( description="Per-package documentation tokens and marker rates, before and after" )
    parser.add_argument( "packages", nargs="+", help="repo-relative package directories" )
    parser.add_argument( "--base", required=True, help="revision for the before numbers" )
    parser.add_argument( "--head", help="revision for the after numbers; default is the working tree" )
    parser.add_argument( "--format", choices=( "table", "json" ), default="table" )
    parser.add_argument( "--strict", action="store_true", help="exit 1 when any package is not improved" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    parser.add_argument( "--words-root", help="tree that holds src/conf/dm-tutor-lowercase-words.txt; default is the lupin tree, never the repo being measured" )
    args = parser.parse_args( argv )
    configure_root( args.words_root or cu.get_project_root() )
    report = build_report( args.repo_root, args.packages, args.base, args.head )
    if args.format == "json":
        json.dump( report, out, indent=2 )
        out.write( "\n" )
    else:
        out.write( render_table( report ) )
    return 1 if args.strict and not all( r[ "improved" ] for r in report.values() ) else 0


if __name__ == "__main__": sys.exit( main() )  # pragma: no cover -- script entry, main() is tested
