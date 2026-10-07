"""
Per-file finding counts for the Python files the sweep did not reach.

A counted file is a tracked Python file that swept_scope does not hold to zero. Its count may fall
and may not rise. A committed table records each count. This module measures counts, reads and
writes the table and checks it, and the commit gate and the merge gate both import it.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from collections import namedtuple

from . import docstring_lint
from .swept_scope import is_swept
from .text_rules import Finding
from .waivers import waiver_state
from .word_list import configure_root

TABLE_PATH       = "src/conf/doc-lint-counts.json"
TABLE_FORMAT     = 1
STAMP_FILES      = (
    "src/cosa/repo/doc_lint/text_rules.py",
    "src/cosa/repo/doc_lint/rule_lists.py",
    "src/cosa/repo/doc_lint/docstring_lint.py",
    "src/cosa/repo/doc_lint/marker_counts.py",
    "src/cosa/repo/doc_lint/links.py",
    "src/cosa/repo/doc_lint/waivers.py",
    "src/conf/dm-tutor-lowercase-words.txt",
)
EXIT_TIGHT       = 0
EXIT_MISMATCH    = 1
EXIT_NOT_CHECKED = 2

FileCount = namedtuple( "FileCount", [ "count", "findings", "waivers" ] )
Table     = namedtuple( "Table", [ "stamp", "files" ] )


class TableError( ValueError ):
    """The count table is malformed."""


def file_count( path, source, root=None ):
    """
    Count the docstring-lint findings in one file that no waiver covers.

    Requires:
        - path is the repo-relative path used in findings
        - source is the file text
        - root is the repo working tree, or None to skip checks that need it

    Ensures:
        - returns a FileCount of the count, the unwaived findings and the waivers honoured
        - a file that does not parse counts as one finding, and its waivers are not read

    Raises:
        - nothing
    """
    findings = docstring_lint.lint_source( path, source, root )
    if findings and findings[ 0 ].rule == "parse-error": return FileCount( 1, findings[ : 1 ], 0 )
    lines = source.split( "\n" )
    kept  = [ f for f in findings if waiver_state( f, lines[ f.line - 1 ] ) != "honoured" ]
    return FileCount( len( kept ), kept, len( findings ) - len( kept ) )


def unreadable_count( path, err ):
    """
    Count a file whose bytes are not UTF-8 as one finding.

    Requires:
        - err is the UnicodeDecodeError raised by the read

    Ensures:
        - returns a FileCount of one finding on line 1 and no waivers

    Raises:
        - nothing
    """
    return FileCount( 1, [ Finding( path, 1, "not-utf-8", f"not UTF-8: {err}" ) ], 0 )


def counted_paths( root ):
    """
    List the tracked Python files that are counted, not swept.

    Requires:
        - root is a git working tree

    Ensures:
        - returns sorted repo-relative posix paths, each a .py file that is_swept rejects
        - the population comes from git, never from a disk walk

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    res = subprocess.run( [ "git", "-C", str( root ), "ls-files", "--", ":/" ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git ls-files failed: {res.stderr.strip()}" )
    return sorted( p for p in res.stdout.split( "\n" ) if p.endswith( ".py" ) and not is_swept( p ) )


def _read_disk( root ):
    """
    Build a reader that returns a file's text from the working tree.

    Requires:
        - root is a directory

    Ensures:
        - the reader drops a leading byte-order mark and raises UnicodeDecodeError for other bytes

    Raises:
        - nothing
    """
    def read( path ):
        with open( f"{root}/{path}", encoding="utf-8-sig" ) as handle: return handle.read()
    return read


def census( root, read=None ):
    """
    Count every counted file of a tree.

    Requires:
        - root is a git working tree
        - read( path ) returns the text of a counted path, or None to read the working tree

    Ensures:
        - returns ( counts, walked ), where counts maps each path with a nonzero count to it
        - walked is the number of counted files read, so a census over nothing says so
        - a file that is not UTF-8 counts as one finding

    Raises:
        - RuntimeError from git when the listing fails
        - OSError when a counted file cannot be read
    """
    read   = read if read is not None else _read_disk( root )
    counts = {}
    paths  = counted_paths( root )
    for path in paths:
        try:
            result = file_count( path, read( path ), root )
        except UnicodeDecodeError as err:
            result = unreadable_count( path, err )
        if result.count: counts[ path ] = result.count
    return counts, len( paths )


def rules_stamp( root ):
    """
    Hash the files that decide what a finding is.

    Requires:
        - root is a working tree that holds every file in STAMP_FILES

    Ensures:
        - returns the first 16 hex characters of a sha256 over each path and its bytes
        - reads the working tree, the files whose code counts the findings, so an unstaged edit to a rule file moves the stamp
        - the same rule files always give the same stamp

    Raises:
        - OSError when a rule file is missing
    """
    digest = hashlib.sha256()
    for path in STAMP_FILES:
        with open( f"{root}/{path}", "rb" ) as handle: data = handle.read()
        digest.update( path.encode( "utf-8" ) + b"\0" + data + b"\0" )
    return digest.hexdigest()[ : 16 ]


def table_text( files, stamp ):
    """
    Render the table as text, one entry per line and sorted by path.

    Requires:
        - files maps repo-relative paths to counts above zero
        - stamp is a str

    Ensures:
        - returns JSON text that ends in a newline
        - one entry per line, so two edits to different files merge without a conflict

    Raises:
        - nothing
    """
    lines = [ "{", f'  "format": {TABLE_FORMAT},', f"  \"rules_stamp\": {json.dumps( stamp )},", '  "files": {' ]
    lines.append( ",\n".join( f"    {json.dumps( path )}: {count}" for path, count in sorted( files.items() ) ) )
    lines += [ "  }", "}" ]
    return "\n".join( line for line in lines if line ) + "\n"


def parse_table( text ):
    """
    Read the table text.

    Requires:
        - text is a str

    Ensures:
        - returns a Table of the stamp and a dict of path to count
        - every count is an integer above zero, since a file at zero has no entry

    Raises:
        - TableError naming what is wrong when the text is not a valid table
    """
    try:
        data = json.loads( text )
    except ValueError as err:
        raise TableError( f"table is not JSON: {err}" ) from err
    if not isinstance( data, dict ) or data.get( "format" ) != TABLE_FORMAT: raise TableError( f"table format is not {TABLE_FORMAT}" )
    if not isinstance( data.get( "rules_stamp" ), str ): raise TableError( "table has no rules_stamp" )
    files = data.get( "files" )
    if not isinstance( files, dict ): raise TableError( "table has no files object" )
    for path, count in files.items():
        if isinstance( count, bool ) or not isinstance( count, int ) or count < 1: raise TableError( f"{path}: count {count!r} is not an integer above zero" )
    return Table( data[ "rules_stamp" ], files )


def allowance( path, files, renamed_from ):
    """
    Return the count a staged counted path may hold.

    Requires:
        - files maps paths to counts
        - renamed_from maps a new path to the path it was renamed from

    Ensures:
        - the entry for the path when there is one
        - else the entry of the path it was renamed from, so a move keeps its count
        - else zero

    Raises:
        - nothing
    """
    if path in files: return files[ path ]
    return files.get( renamed_from.get( path ), 0 )


def table_raises( staged_files, head_files ):
    """
    List the entries a staged table raises above the committed one.

    Requires:
        - both arguments map paths to counts

    Ensures:
        - returns sorted ( path, old, new ) for each path whose new count is above its old one
        - a path with no committed entry has old count zero
        - a lowered or deleted entry is not listed

    Raises:
        - nothing
    """
    return sorted( ( path, head_files.get( path, 0 ), count ) for path, count in staged_files.items() if count > head_files.get( path, 0 ) )


def check_table( table, counts, current_stamp ):
    """
    Compare a table with a census and list every disagreement.

    Requires:
        - table is a Table
        - counts is the dict from census
        - current_stamp is the stamp computed from the rule files now

    Ensures:
        - returns a list of problem lines, empty when the table is exact
        - a table is exact when it matches the census in both directions, names no swept path and carries the current stamp

    Raises:
        - nothing
    """
    problems = []
    if table.stamp != current_stamp: problems.append( f"rules_stamp {table.stamp} is not the current {current_stamp}: regenerate the table" )
    for path in sorted( set( table.files ) | set( counts ) ):
        have, want = table.files.get( path, 0 ), counts.get( path, 0 )
        if have != want: problems.append( f"{path}: table {have}, census {want}" )
    problems += [ f"{path}: swept, so no entry is allowed" for path in sorted( table.files ) if is_swept( path ) ]
    return problems


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
    parser = argparse.ArgumentParser( description="Write or check the per-file finding counts." )
    mode   = parser.add_mutually_exclusive_group( required=True )
    mode.add_argument( "--write", action="store_true", help="rewrite the table from the tree" )
    mode.add_argument( "--check", action="store_true", help="exit 1 unless the table is exact" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    args = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    root = args.repo_root
    try:
        configure_root( root )
        counts, walked = census( root )
        stamp          = rules_stamp( root )
        if args.write:
            with open( f"{root}/{TABLE_PATH}", "w", encoding="utf-8" ) as handle: handle.write( table_text( counts, stamp ) )
            out.write( f"wrote {len( counts )} entries from {walked} counted files\n" )
            return EXIT_TIGHT
        with open( f"{root}/{TABLE_PATH}", encoding="utf-8" ) as handle: table = parse_table( handle.read() )
    except ( OSError, RuntimeError, TableError ) as err:
        out.write( f"not checked: {type( err ).__name__}: {err}\n" )
        return EXIT_NOT_CHECKED
    problems = check_table( table, counts, stamp )
    for line in problems: out.write( line + "\n" )
    out.write( f"{walked} counted files walked, {len( problems )} problems\n" )
    return EXIT_MISMATCH if problems else EXIT_TIGHT


if __name__ == "__main__":
    sys.exit( main() )
