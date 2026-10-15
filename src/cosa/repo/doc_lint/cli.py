"""
Command-line driver shared by the docstring, doc-comment and markdown linters.

Each linter supplies a function that turns one file's source into findings. This module finds
the files, applies the three modes (--report, --changed, --strict) and prints the result.
"""

import argparse
import json
import os
import re
import subprocess
import sys

from .changed_ranges import changed_line_ranges, filter_findings
from .text_rules import Finding
from .word_list import configure_root

SKIP_SEGMENTS = frozenset( { "tests", ".venv", "node_modules", "site-packages", "__pycache__", "rnd" } )
SURROGATE     = re.compile( "[\ud800-\udfff]" )
# What ends a line. Python's parser counts these three. The TypeScript compiler counts two more.
PYTHON_BREAKS = re.compile( "\r\n|\r|\n" )
SCRIPT_BREAKS = re.compile( "\r\n|[\r\n\u2028\u2029]" )


def split_names( raw ):
    """
    Read the file names of a git listing made with -z.

    Requires:
        - raw is the bytes git wrote, one name after another, each ended by a NUL byte

    Ensures:
        - returns the names in git's order, each decoded as the file system decodes a name
        - a name that is not UTF-8 keeps its bytes, so it can be handed back to git or opened

    Raises:
        - nothing
    """
    return [ os.fsdecode( name ) for name in raw.split( b"\0" ) if name ]


def crosses_as_text( name ):
    """
    Say whether a file name survives being handed to a tool that reads names as UTF-8 text.

    Requires:
        - name is a str as split_names gives it

    Ensures:
        - False when the name holds a byte that is not UTF-8, which Python keeps as a stand-in character
        - True for every other name
        - a tool written for Node or in Rust replaces such a byte, so it opens another file or names another file in its output

    Raises:
        - nothing
    """
    return SURROGATE.search( name ) is None


def split_lines( source, breaks=PYTHON_BREAKS ):
    """
    Split a source text into lines the way its parser numbers them.

    Requires:
        - source is a str; breaks is PYTHON_BREAKS for Python text and SCRIPT_BREAKS for TypeScript or JavaScript text

    Ensures:
        - returns the lines without their line ends, so line n of the parser is item n - 1
        - a bare carriage return ends a line, as it does for the parser that gave a finding its line number

    Raises:
        - nothing
    """
    return breaks.split( source )


def line_text( lines, number ):
    """
    Return the text of one numbered line.

    Requires:
        - lines is the list split_lines gives; number is a 1-based line number

    Ensures:
        - returns the line, or an empty string for a number the text does not reach
        - so a line number from a parser that counts lines another way waives nothing and crashes nothing

    Raises:
        - nothing
    """
    return lines[ number - 1 ] if 0 < number <= len( lines ) else ""


def shown( text ):
    """
    Make a file name, or a line that holds one, safe to print on one line.

    Requires:
        - text is a str, which may hold the stand-ins Python uses for bytes that are not UTF-8

    Ensures:
        - a byte that is not UTF-8 is written as a backslash, an x and two hex digits
        - a control character, a newline or a tab among them, is written as its backslash escape
        - every other character is kept, so a name of printable characters comes back unchanged
        - the result can be written to a strict UTF-8 stream

    Raises:
        - nothing
    """
    def one( ch ):
        if 0xDC80 <= ord( ch ) <= 0xDCFF: return f"\\x{ord( ch ) - 0xDC00:02x}"
        return ch if ch.isprintable() else ch.encode( "unicode_escape" ).decode( "ascii" )
    return "".join( one( ch ) for ch in text )


def in_scope( path ):
    """
    Say whether a repo-relative path is documentation-standard territory.

    Requires:
        - path is a posix repo-relative path

    Ensures:
        - False for test files, vendored trees and the R&D directory
        - True otherwise

    Raises:
        - nothing
    """
    parts = path.split( "/" )
    if any( p in SKIP_SEGMENTS for p in parts[ : -1 ] ): return False
    name = parts[ -1 ]
    return not ( name.startswith( "test_" ) or name == "conftest.py" )


def tracked_files( repo_root, suffixes, scoped=True ):
    """
    List the git-tracked files with one of the suffixes.

    Requires:
        - repo_root is a git working tree
        - suffixes is a tuple of strings such as ( ".py", ); ( "", ) lists every file
        - scoped is a bool

    Ensures:
        - returns sorted repo-relative posix paths that are in_scope; with scoped False, every path with a suffix, in scope or not
        - the population comes from git, never from a disk walk
        - names are read apart at the NUL byte, so a name git would quote is listed as it is

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    res = subprocess.run( [ "git", "-C", str( repo_root ), "ls-files", "-z", "--", ":/" ], capture_output=True )
    if res.returncode != 0: raise RuntimeError( f"git ls-files failed: {res.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    return sorted( p for p in split_names( res.stdout ) if p.endswith( suffixes ) and ( in_scope( p ) or not scoped ) )


def build_parser( description ):
    """
    Build the argument parser every linter shares.

    Requires:
        - description is a str

    Ensures:
        - the parser accepts optional paths, --changed with a base revision, --staged, --strict, --json and --repo-root

    Raises:
        - nothing
    """
    parser = argparse.ArgumentParser( description=description )
    parser.add_argument( "paths", nargs="*", help="repo-relative files; default is every tracked file" )
    parser.add_argument( "--report", action="store_true", help="whole corpus (the default)" )
    parser.add_argument( "--changed", metavar="BASE", help="only findings on lines touched since BASE" )
    parser.add_argument( "--staged", action="store_true", help="only findings on staged lines" )
    parser.add_argument( "--strict", action="store_true", help="exit 1 when any finding remains" )
    parser.add_argument( "--json", action="store_true", help="print findings as JSON" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    return parser


def run_linter( description, suffixes, lint_source, argv, out=None, footer=None ):
    """
    Run one linter over the chosen files and print its findings.

    Requires:
        - lint_source( path, source, root ) returns a list of Finding; root is the repo working tree
        - suffixes is a tuple of file suffixes
        - footer is a callable returning one extra report line, or None

    Ensures:
        - returns 0, or 1 when --strict is given and findings remain
        - --changed and --staged keep only findings on touched lines
        - a file that cannot be read as UTF-8 is reported as one finding, not skipped
        - the text report ends with the footer line; --json output carries no footer

    Raises:
        - RuntimeError from git when a diff or listing fails
    """
    out  = out if out is not None else sys.stdout
    args = build_parser( description ).parse_args( argv )
    root = args.repo_root
    configure_root( root )
    paths = [ p for p in args.paths if p.endswith( suffixes ) ] if args.paths else tracked_files( root, suffixes )
    findings = []
    for path in paths:
        try:
            with open( f"{root}/{path}", encoding="utf-8" ) as handle: source = handle.read()
        except ( OSError, UnicodeDecodeError ) as err:
            findings.append( _unreadable( path, err ) )
            continue
        findings += lint_source( path, source, root )
    if args.changed is not None or args.staged:
        findings = filter_findings( findings, changed_line_ranges( root, args.changed, cached=args.staged ) )
    if args.json:
        json.dump( [ f._asdict() for f in findings ], out, indent=2 )
        out.write( "\n" )
    else:
        for f in findings: out.write( f"{shown( f.path )}:{f.line}: {f.rule}: {f.message}\n" )
        out.write( f"{len( findings )} findings in {len( paths )} files\n" )
        if footer is not None: out.write( footer() )
    return 1 if args.strict and findings else 0


def _unreadable( path, err ):
    """
    Build the finding for a file that could not be read.

    Requires:
        - err is the exception raised by the read

    Ensures:
        - returns a Finding at line 1 with rule unreadable

    Raises:
        - nothing
    """
    return Finding( path, 1, "unreadable", f"could not read as UTF-8: {err}" )
