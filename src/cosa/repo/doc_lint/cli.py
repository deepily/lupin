"""
Command-line driver shared by the docstring, doc-comment and markdown linters.

Each linter supplies a function that turns one file's source into findings. This module finds
the files, applies the three modes (--report, --changed, --strict) and prints the result.
"""

import argparse
import json
import subprocess
import sys

from .changed_ranges import changed_line_ranges, filter_findings
from .text_rules import Finding
from .word_list import configure_root

SKIP_SEGMENTS = frozenset( { "tests", ".venv", "node_modules", "site-packages", "__pycache__", "rnd" } )


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


def tracked_files( repo_root, suffixes ):
    """
    List the git-tracked files with one of the suffixes.

    Requires:
        - repo_root is a git working tree
        - suffixes is a tuple of strings such as ( ".py", )

    Ensures:
        - returns sorted repo-relative posix paths that are in_scope
        - the population comes from git, never from a disk walk

    Raises:
        - RuntimeError naming the git error when ls-files fails
    """
    res = subprocess.run( [ "git", "-C", str( repo_root ), "ls-files", "--", ":/" ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git ls-files failed: {res.stderr.strip()}" )
    return sorted( p for p in res.stdout.split( "\n" ) if p.endswith( suffixes ) and in_scope( p ) )


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


def run_linter( description, suffixes, lint_source, argv, out=None ):
    """
    Run one linter over the chosen files and print its findings.

    Requires:
        - lint_source( path, source, root ) returns a list of Finding; root is the repo working tree
        - suffixes is a tuple of file suffixes

    Ensures:
        - returns 0, or 1 when --strict is given and findings remain
        - --changed and --staged keep only findings on touched lines
        - a file that cannot be read as UTF-8 is reported as one finding, not skipped

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
        for f in findings: out.write( f"{f.path}:{f.line}: {f.rule}: {f.message}\n" )
        out.write( f"{len( findings )} findings in {len( paths )} files\n" )
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
