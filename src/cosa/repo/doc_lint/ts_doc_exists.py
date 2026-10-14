"""
Existence check for doc comments on exported TypeScript and JavaScript symbols.

The wording linter reads the comments that exist. This module lists the exported top-level symbols
that have none. It counts them per file and holds each count to a table that may fall and may not rise.
The files come from tsdoc_lint, so there is one scope decision. The comment tokens come from
ts_doc_extract.mjs, through src/scripts/ts_export_extract.mjs, which pairs them with the exports.
The table format, the stamp and the checks are those of counts.py.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import namedtuple

from . import counts, tsdoc_lint
from .cli import shown
from .word_list import configure_root

TABLE_PATH       = "src/conf/doc-lint-ts-exports-counts.json"
STAMP_FILES      = (
    "src/cosa/repo/doc_lint/ts_doc_exists.py",
    "src/cosa/repo/doc_lint/tsdoc_lint.py",
    "src/scripts/ts_export_extract.mjs",
    "src/scripts/ts_doc_extract.mjs",
)
EXTRACTOR_REL    = "src/scripts/ts_export_extract.mjs"
# Folders that tsdoc_lint reads and this check does not: R&D notes and probes, and the built Flutter web bundle.
EXCLUDED_PREFIXES = ( "src/rnd/", "src/cosa/rnd/", "src/lupin_app/static/lupin-mobile-test/" )
CHUNK_SIZE       = tsdoc_lint.CHUNK_SIZE
EXIT_TIGHT       = counts.EXIT_TIGHT
EXIT_MISMATCH    = counts.EXIT_MISMATCH
EXIT_NOT_CHECKED = counts.EXIT_NOT_CHECKED

Census = namedtuple( "Census", [ "found", "missing", "walked", "symbols", "undocumented", "reexports", "unparsed" ] )


def counted_paths( root ):
    """
    List the tracked files whose exports are checked.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the files tsdoc_lint reads, less those under EXCLUDED_PREFIXES
        - tsdoc_lint.in_scope is not changed, so the wording linter still reads the excluded folders

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    return [ p for p in tsdoc_lint.tracked_files( root ) if not p.startswith( EXCLUDED_PREFIXES ) ]


def run_extractor( root, files, source_root=None ):
    """
    Run the export extractor over files and group its records by file.

    Requires:
        - root is a git working tree that holds the extractor script
        - files is a list of repo-relative paths
        - source_root is the directory the files are read from, or None for root

    Ensures:
        - returns { path: record } with a key for every file asked for
        - files go to Node in batches of CHUNK_SIZE, one process per batch
        - an empty list starts no process

    Raises:
        - RuntimeError when Node cannot start, exits non-zero or prints a line that is not JSON
        - RuntimeError naming each file that came back without a record, since such a file was not read
    """
    by_file = {}
    script  = os.path.join( str( root ), EXTRACTOR_REL )
    for i in range( 0, len( files ), CHUNK_SIZE ):
        cmd = [ "node", script, "--repo-root", str( root if source_root is None else source_root ), *files[ i : i + CHUNK_SIZE ] ]
        try:
            res = subprocess.run( cmd, capture_output=True, text=True, encoding="utf-8" )
        except OSError as err:
            raise RuntimeError( f"cannot run node: {err}" ) from err
        if res.returncode != 0: raise RuntimeError( f"export extractor failed: {res.stderr.strip()}" )
        for raw in res.stdout.split( "\n" ):
            if not raw.strip(): continue
            try:
                record = json.loads( raw )
            except json.JSONDecodeError as err:
                raise RuntimeError( f"export extractor printed a line that is not JSON: {raw[ : 80 ]!r}" ) from err
            by_file[ record[ "file" ] ] = record
    unread = [ path for path in files if path not in by_file ]
    if unread: raise RuntimeError( f"export extractor returned no record for {len( unread )} of {len( files )} files, so they were NOT checked: {', '.join( shown( p ) for p in unread[ : 5 ] )}" )
    return by_file


def missing( record ):
    """
    List the exported symbols of one file record that have no doc comment.

    Requires:
        - record is an extractor record with a symbols list

    Ensures:
        - returns the undocumented symbols in source order

    Raises:
        - nothing
    """
    return [ s for s in record[ "symbols" ] if not s[ "documented" ] ]


def census( root, run=None ):
    """
    Check every counted file of a tree.

    Requires:
        - root is a git working tree
        - run( root, files ) returns { path: record }, or None for run_extractor

    Ensures:
        - returns a Census: found maps each path with an undocumented export to its count, missing to the symbols
        - walked, symbols and undocumented are totals, so a census over nothing says so
        - reexports counts names that are not symbols of the file; unparsed lists the files the compiler could not parse

    Raises:
        - RuntimeError from git or the extractor
    """
    paths   = counted_paths( root )
    by_file = ( run if run is not None else run_extractor )( root, paths )
    gaps    = { p: missing( by_file[ p ] ) for p in paths }
    gaps    = { p: g for p, g in gaps.items() if g }
    return Census(
        found        = { p: len( g ) for p, g in gaps.items() },
        missing      = gaps,
        walked       = len( paths ),
        symbols      = sum( len( by_file[ p ][ "symbols" ] ) for p in paths ),
        undocumented = sum( len( g ) for g in gaps.values() ),
        reexports    = sum( by_file[ p ][ "reexports" ] for p in paths ),
        unparsed     = [ p for p in paths if by_file[ p ][ "parse_errors" ] ]
    )


def raises( table_files, found ):
    """
    List the files whose undocumented count rose above the table.

    Requires:
        - both arguments map paths to counts

    Ensures:
        - returns sorted ( path, old, new ), old being zero for a file with no entry
        - a file that fell, or stayed, is not listed

    Raises:
        - nothing
    """
    return counts.table_raises( found, table_files )


def rules_stamp( root, read=None ):
    """
    Hash the files that decide what counts as an undocumented export.

    Requires:
        - root is a working tree that holds every file in STAMP_FILES
        - read( path ) returns a rule file's bytes, or None to read the working tree

    Ensures:
        - returns the stamp counts.rules_stamp gives over STAMP_FILES

    Raises:
        - OSError when a rule file is missing
    """
    return counts.rules_stamp( root, read, STAMP_FILES )


def report( result ):
    """
    Render a census as text: each undocumented symbol, a count table and the totals.

    Requires:
        - result is a Census

    Ensures:
        - returns text that ends in a newline
        - symbol lines read path:line: kind name, in path order
        - the count table lists the largest count first, ties by path
        - re-export and unparsed lines appear only when their number is above zero

    Raises:
        - nothing
    """
    lines = [ f"{path}:{s[ 'line' ]}: {s[ 'kind' ]} {s[ 'name' ]}" for path, group in sorted( result.missing.items() ) for s in group ]
    lines += [ "", "count  file" ]
    lines += [ f"{n:>6}  {path}" for path, n in sorted( result.found.items(), key=lambda item: ( -item[ 1 ], item[ 0 ] ) ) ]
    lines += [ "", f"{result.undocumented} of {result.symbols} exported symbols have no doc comment, in {len( result.found )} of {result.walked} files" ]
    if result.reexports: lines.append( f"re-exports not counted: {result.reexports}" )
    if result.unparsed: lines.append( f"files that did not parse: {len( result.unparsed )} ({', '.join( shown( p ) for p in result.unparsed[ : 5 ] )})" )
    return "\n".join( lines ) + "\n"


def main( argv=None, out=None ):
    """
    Command-line entry point: list the gaps, write the table or check it.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]
        - out is a writable text stream, or None for sys.stdout

    Ensures:
        - --list prints report() and returns EXIT_TIGHT, with a line naming any file that did not parse
        - --write rewrites TABLE_PATH from a census and returns EXIT_TIGHT
        - --check returns EXIT_TIGHT when the table is exact and EXIT_MISMATCH when a count differs, which includes a rise
        - EXIT_NOT_CHECKED when the table cannot be read or the tree cannot be measured
        - EXIT_NOT_CHECKED, naming the files, when a file did not parse, since a lost export would read as a fall
        - nothing here is wired into a gate

    Raises:
        - nothing
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="List exported TypeScript and JavaScript symbols with no doc comment, or hold their count." )
    mode   = parser.add_mutually_exclusive_group( required=True )
    mode.add_argument( "--list", action="store_true", help="print every undocumented export and a per-file count table" )
    mode.add_argument( "--write", action="store_true", help="rewrite the table from the tree" )
    mode.add_argument( "--check", action="store_true", help="exit 1 unless the table is exact" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    args = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    root = args.repo_root
    try:
        configure_root( root )
        result = census( root )
        stamp  = rules_stamp( root )
        if args.list:
            out.write( report( result ) )
            return EXIT_TIGHT
        if result.unparsed: raise RuntimeError( f"{len( result.unparsed )} files did not parse, so their exports were not all read: {', '.join( shown( p ) for p in result.unparsed[ : 5 ] )}" )
        if args.write:
            with open( f"{root}/{TABLE_PATH}", "w", encoding="utf-8" ) as handle: handle.write( counts.table_text( result.found, stamp ) )
            out.write( f"wrote {len( result.found )} entries from {result.walked} counted files\n" )
            return EXIT_TIGHT
        with open( f"{root}/{TABLE_PATH}", encoding="utf-8" ) as handle: table = counts.parse_table( handle.read() )
    except ( OSError, RuntimeError, counts.TableError ) as err:
        out.write( f"not checked: {type( err ).__name__}: {err}\n" )
        return EXIT_NOT_CHECKED
    problems = counts.check_table( table, result.found, stamp )
    for line in problems: out.write( shown( line ) + "\n" )
    out.write( f"{result.walked} counted files walked, {len( problems )} problems\n" )
    return EXIT_MISMATCH if problems else EXIT_TIGHT


if __name__ == "__main__":
    sys.exit( main() )
