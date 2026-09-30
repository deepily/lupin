"""
Pre-commit gate for the documentation standard, in warn mode (plan 1, section 4.2).

Lints the staged lines of Python and markdown files with ruff, markdownlint-cli2 and the
doc_lint rules, prints the findings to stderr and exits 0. It exits 0 on its own crash too,
because the hook is shared by every worktree and a crashing gate must not block every seat.
A missing tool prints a loud warning. It does not read PLANNING_IS_PROMPTING_ROOT.
"""

import argparse
import subprocess
import sys
import traceback

from . import comment_lint, docstring_lint, md_lint
from .changed_ranges import changed_line_ranges, filter_findings
from .cli import in_scope
from .tool_runners import run_markdownlint, run_ruff
from .word_list import configure_root


def git_toplevel( start ):
    """
    Return the git working-tree root that holds start.

    Requires:
        - start is a directory inside a working tree

    Ensures:
        - returns the absolute path as a str

    Raises:
        - RuntimeError naming the git error when start is not in a working tree
    """
    res = subprocess.run( [ "git", "-C", start, "rev-parse", "--show-toplevel" ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"not a git working tree: {res.stderr.strip()}" )
    return res.stdout.strip()


def staged_paths( root ):
    """
    List the staged files that were added, copied, modified or renamed.

    Requires:
        - root is a git working tree

    Ensures:
        - returns repo-relative posix paths that are in_scope
        - the listing is anchored at root, so the caller's directory does not matter

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    res = subprocess.run( [ "git", "-C", root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "--", ":/" ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git diff --cached failed: {res.stderr.strip()}" )
    return [ p for p in res.stdout.split( "\n" ) if p and in_scope( p ) ]


def staged_source( root, path ):
    """
    Read a file as it is in the index, not as it is on disk.

    Requires:
        - path is staged

    Ensures:
        - returns the staged text, so findings match the line numbers of the staged diff

    Raises:
        - RuntimeError naming the git error when the read fails
    """
    res = subprocess.run( [ "git", "-C", root, "show", f":{path}" ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git show :{path} failed: {res.stderr.strip()}" )
    return res.stdout


def collect( root ):
    """
    Gather every finding and warning for the staged lines.

    Requires:
        - root is a git working tree

    Ensures:
        - returns ( findings, warnings ), findings limited to lines the staged diff touched
        - ruff reads the staged text of each Python file through stdin, not the working-tree file
        - Python files get docstring_lint, comment_lint and ruff; markdown files get md_lint and markdownlint

    Raises:
        - RuntimeError from git when a listing, diff or read fails
    """
    configure_root( root )
    paths    = staged_paths( root )
    ranges   = changed_line_ranges( root, None, cached=True )
    findings = []
    py_sources = {}
    for path in paths:
        if path.endswith( ".py" ):
            source = staged_source( root, path )
            py_sources[ path ] = source
            findings += docstring_lint.lint_source( path, source, root ) + comment_lint.lint_source( path, source, root )
        elif path.endswith( ".md" ):
            findings += md_lint.lint_source( path, staged_source( root, path ), root )
    py, md   = [ p for p in paths if p.endswith( ".py" ) ], [ p for p in paths if p.endswith( ".md" ) ]
    ruff_findings, ruff_warnings = run_ruff( root, py, sources=py_sources )
    md_findings, md_warnings     = run_markdownlint( root, md )
    findings += ruff_findings + md_findings
    return filter_findings( findings, ranges ), ruff_warnings + md_warnings


def main( argv=None, err=None ):
    """
    Run the gate.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]
        - err is a writable text stream, or None for sys.stderr

    Ensures:
        - returns 0 unless --blocking is given and findings remain
        - in warn mode an internal error is printed as a loud line and the exit is still 0
        - every warning from a missing tool is printed

    Raises:
        - nothing
    """
    err    = err if err is not None else sys.stderr
    parser = argparse.ArgumentParser( description="Documentation-standard pre-commit gate (warn mode by default)." )
    parser.add_argument( "--blocking", action="store_true", help="exit 1 when findings remain" )
    parser.add_argument( "--repo-root", default=".", help="directory inside the working tree" )
    args = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    try:
        root                 = git_toplevel( args.repo_root )
        findings, warnings   = collect( root )
    except Exception as exc:
        err.write( f"[doc-lint] GATE CRASHED, commit allowed: {type( exc ).__name__}: {exc}\n" )
        err.write( traceback.format_exc() )
        return 0
    for warning in warnings: err.write( warning + "\n" )
    for f in findings: err.write( f"[doc-lint] {f.path}:{f.line}: {f.rule}: {f.message}\n" )
    err.write( f"[doc-lint] {len( findings )} findings on staged lines ({'blocking' if args.blocking else 'warn mode, commit allowed'})\n" )
    return 1 if args.blocking and findings else 0


if __name__ == "__main__":
    sys.exit( main() )
