"""
Per-file finding counts for the TypeScript and JavaScript files.

Every tracked TypeScript or JavaScript file in the linter's scope is counted. Its count may fall
and may not rise. A committed table records each count. This module measures counts, reads and
writes the table and checks it, and the commit gate imports it.

The table and the checks are those of counts.py. Only the files, the comment linter and the
rules stamp differ.
"""

import argparse
import os
import shutil
import sys
import tempfile

from . import counts, tsdoc_lint
from .waivers import waiver_state
from .word_list import configure_root

TABLE_PATH       = "src/conf/doc-lint-ts-counts.json"
STAMP_FILES      = counts.STAMP_FILES + ( "src/cosa/repo/doc_lint/tsdoc_lint.py", "src/scripts/ts_doc_extract.mjs" )
EXIT_TIGHT       = counts.EXIT_TIGHT
EXIT_MISMATCH    = counts.EXIT_MISMATCH
EXIT_NOT_CHECKED = counts.EXIT_NOT_CHECKED


def counted_paths( root ):
    """
    List the tracked TypeScript and JavaScript files that are counted.

    Requires:
        - root is a git working tree

    Ensures:
        - returns sorted repo-relative posix paths, each one tsdoc_lint.in_scope accepts
        - the population comes from git, never from a disk walk

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    return tsdoc_lint.tracked_files( root )


def extract( root, texts ):
    """
    Run the Node extractor over given texts instead of the working-tree files.

    Requires:
        - root is a git working tree that holds the extractor script
        - texts maps repo-relative paths to file text

    Ensures:
        - returns the extractor records grouped by path, as tsdoc_lint.run_extractor does
        - the texts are written to a scratch tree and read from there, so a staged text is judged, not the disk copy
        - the scratch tree is removed afterwards, also when the extractor fails
        - no texts start no process

    Raises:
        - RuntimeError from the extractor
    """
    if not texts: return {}
    scratch = tempfile.mkdtemp( prefix="ts-counts-" )
    try:
        for path, text in texts.items():
            full = os.path.join( scratch, path )
            os.makedirs( os.path.dirname( full ), exist_ok=True )
            with open( full, "w", encoding="utf-8" ) as handle: handle.write( text )
        return tsdoc_lint.run_extractor( root, list( texts ), source_root=scratch )
    finally:
        shutil.rmtree( scratch, ignore_errors=True )


def count_records( path, records, source, root=None ):
    """
    Count the comment-lint findings in one file that no waiver covers.

    Requires:
        - path is the repo-relative path used in findings
        - records is the extractor output for that file
        - source is the file text
        - root is the repo working tree, or None to skip checks that need it

    Ensures:
        - returns a counts.FileCount of the count, the unwaived findings and the waivers honoured
        - a file that does not parse adds one parse-error finding, and its comments are still counted

    Raises:
        - nothing
    """
    findings = tsdoc_lint.lint_comments( path, records, root )
    lines    = source.split( "\n" )
    kept     = [ f for f in findings if waiver_state( f, lines[ f.line - 1 ] ) != "honoured" ]
    return counts.FileCount( len( kept ), kept, len( findings ) - len( kept ) )


def counts_for( root, texts ):
    """
    Count the findings of several texts with one extractor run.

    Requires:
        - root is a git working tree
        - texts maps repo-relative paths to file text

    Ensures:
        - returns { path: counts.FileCount } for every path given

    Raises:
        - RuntimeError from the extractor
    """
    by_file = extract( root, texts )
    return { path: count_records( path, by_file[ path ], text, root ) for path, text in texts.items() }


def census( root, read=None ):
    """
    Count every counted file of a tree.

    Requires:
        - root is a git working tree
        - read( path ) returns the text of a counted path, or None to read the working tree

    Ensures:
        - returns ( found, walked ), where found maps each path with a nonzero count to it
        - walked is the number of counted files read, so a census over nothing says so
        - a file that is not UTF-8 counts as one finding
        - with no reader the working-tree text is read

    Raises:
        - RuntimeError from git or the extractor
        - OSError when a counted file cannot be read
    """
    paths = counted_paths( root )
    found = {}
    texts = {}
    for path in paths:
        try:
            texts[ path ] = read( path ) if read is not None else _disk_text( root, path )
        except UnicodeDecodeError as err:
            found[ path ] = counts.unreadable_count( path, err ).count
    found.update( { path: r.count for path, r in counts_for( root, texts ).items() if r.count } )
    return dict( sorted( found.items() ) ), len( paths )


def _disk_text( root, path ):
    """
    Read a file from the working tree, dropping a leading byte-order mark.

    Requires:
        - root is a directory

    Ensures:
        - returns the text, or raises UnicodeDecodeError for bytes that are not UTF-8

    Raises:
        - OSError when the file cannot be read
    """
    with open( f"{root}/{path}", encoding="utf-8-sig" ) as handle: return handle.read()


def rules_stamp( root, read=None ):
    """
    Hash the files that decide what a TypeScript or JavaScript finding is.

    Requires:
        - root is a working tree that holds every file in STAMP_FILES
        - read( path ) returns a rule file's bytes, or None to read the working tree

    Ensures:
        - returns the stamp counts.rules_stamp gives over STAMP_FILES, so the same rule files give the same stamp

    Raises:
        - OSError when a rule file is missing
    """
    return counts.rules_stamp( root, read, STAMP_FILES )


def main( argv=None, out=None ):
    """
    Command-line entry point: write the table or check it.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]
        - out is a writable text stream, or None for sys.stdout

    Ensures:
        - --write rewrites TABLE_PATH from a census and returns EXIT_TIGHT
        - --check returns EXIT_TIGHT when the table is exact and EXIT_MISMATCH when it is not
        - EXIT_NOT_CHECKED when the table cannot be read or the tree cannot be measured, so a run that checked nothing is never read as clean
        - every run prints the number of counted files walked

    Raises:
        - nothing
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Write or check the per-file TypeScript and JavaScript finding counts." )
    mode   = parser.add_mutually_exclusive_group( required=True )
    mode.add_argument( "--write", action="store_true", help="rewrite the table from the tree" )
    mode.add_argument( "--check", action="store_true", help="exit 1 unless the table is exact" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    args = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    root = args.repo_root
    try:
        configure_root( root )
        found, walked = census( root )
        stamp         = rules_stamp( root )
        if args.write:
            with open( f"{root}/{TABLE_PATH}", "w", encoding="utf-8" ) as handle: handle.write( counts.table_text( found, stamp ) )
            out.write( f"wrote {len( found )} entries from {walked} counted files\n" )
            return EXIT_TIGHT
        with open( f"{root}/{TABLE_PATH}", encoding="utf-8" ) as handle: table = counts.parse_table( handle.read() )
    except ( OSError, RuntimeError, counts.TableError ) as err:
        out.write( f"not checked: {type( err ).__name__}: {err}\n" )
        return EXIT_NOT_CHECKED
    problems = counts.check_table( table, found, stamp )
    for line in problems: out.write( line + "\n" )
    out.write( f"{walked} counted files walked, {len( problems )} problems\n" )
    return EXIT_MISMATCH if problems else EXIT_TIGHT


if __name__ == "__main__":
    sys.exit( main() )
