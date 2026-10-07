"""
Whole-scope gate for the documentation standard: every swept file must have zero findings.

The commit gate reads the files one commit stages. This gate reads every swept file in the tree.
So it also catches a finding that arrived by a merge, or by a commit made without the hook.
The merge pyramid and the pre-push hook both run it.

It exits 0 when the scope is clean and 1 when a finding remains. It exits 2 when it could not
check, so a gate that looked at nothing is never read as a clean tree.
"""

import argparse
import sys

from . import docstring_lint
from .swept_scope import swept_files
from .text_rules import Finding
from .word_list import configure_root

EXIT_CLEAN       = 0
EXIT_FINDINGS    = 1
EXIT_NOT_CHECKED = 2


def check( root, words_root=None ):
    """
    Lint every swept file of a working tree.

    Requires:
        - root is a git working tree
        - words_root is a directory that holds the word list, or None to use root

    Ensures:
        - returns a dict with the keys files, docstrings and findings
        - files is the number of swept files read, and docstrings is the number of docstrings in them
        - findings is a list of Finding in path order
        - a file that cannot be read as UTF-8 yields one unreadable finding and is still counted
        - the word list is read from words_root, so the tree being checked cannot change the rules

    Raises:
        - RuntimeError naming the git error when the file listing fails
        - OSError when the word list cannot be read
    """
    configure_root( words_root if words_root is not None else root )
    paths, docstrings, findings = swept_files( root ), 0, []
    for path in paths:
        try:
            with open( f"{root}/{path}", encoding="utf-8" ) as handle: source = handle.read()
        except ( OSError, UnicodeDecodeError ) as err:
            findings.append( Finding( path, 1, "unreadable", f"could not be read: {err}" ) )
            continue
        found = docstring_lint.lint_source( path, source, root )
        findings += found
        if not any( f.rule == "parse-error" for f in found ): docstrings += len( docstring_lint.extract_docstrings( source ) )
    return { "files": len( paths ), "docstrings": docstrings, "findings": findings }


def report( result, out ):
    """
    Print the findings and the summary block the test-suite job reads.

    Requires:
        - result is the dict check returns
        - out is a writable text stream

    Ensures:
        - one line per finding, then the counts
        - the unit of Total, Passed and Failed is files; the finding count is on its own Errors line
        - returns the number of files that hold a finding

    Raises:
        - nothing
    """
    findings = result[ "findings" ]
    failed   = len( { f.path for f in findings } )
    for f in findings: out.write( f"    {f.path}:{f.line}: {f.rule}: {f.message}\n" )
    out.write( f"Docstrings checked: {result[ 'docstrings' ]}\n" )
    out.write( f"Total Tests: {result[ 'files' ]}\n" )
    out.write( f"Passed: {result[ 'files' ] - failed}\n" )
    out.write( f"Failed: {failed}\n" )
    out.write( f"Errors: {len( findings )}\n" )
    return failed


def main( argv=None, out=None ):
    """
    Run the gate and return its exit code.

    Requires:
        - argv is a list of arguments, or None for the process arguments
        - out is a writable text stream, or None for standard output

    Ensures:
        - returns 0 when every swept file is clean
        - returns 1 when a finding remains, after printing each one
        - returns 2 when no swept file was found, the listing failed or the word list is missing, after printing why

    Raises:
        - nothing
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Documentation-standard gate over the whole swept scope." )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    parser.add_argument( "--words-root", default=None, help="tree that holds the word list; default is the tree being read" )
    args = parser.parse_args( argv )
    try:
        result = check( args.repo_root, args.words_root )
    except ( RuntimeError, OSError ) as err:
        out.write( f"REFUSING: the gate could not run. Nothing was checked. {err}\n" )
        return EXIT_NOT_CHECKED
    if result[ "files" ] == 0:
        out.write( f"REFUSING: no swept file found under {args.repo_root}. Nothing was checked.\n" )
        return EXIT_NOT_CHECKED
    failed = report( result, out )
    if failed:
        out.write( f"DOCLINT GATE FAILED: {len( result[ 'findings' ] )} findings in {failed} of {result[ 'files' ]} files.\n" )
        return EXIT_FINDINGS
    out.write( f"DOCLINT GATE PASSED: all {result[ 'files' ]} files clean.\n" )
    return EXIT_CLEAN


if __name__ == "__main__":  # pragma: no cover - entry point, exercised by the runner script
    sys.exit( main() )
