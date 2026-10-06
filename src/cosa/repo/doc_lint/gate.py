"""
Pre-commit gate for the documentation standard (plan 1, section 4.2).

Lints the staged lines of Python and markdown files with ruff, markdownlint-cli2 and the
doc_lint rules, prints the findings to stderr and exits 0. It exits 0 on its own crash too.
The hook is shared by every worktree, and a crashing gate must not block every seat.
A missing tool prints a loud warning. It does not read PLANNING_IS_PROMPTING_ROOT.

One exception to warn mode applies. A staged file inside a package listed in BLOCKING_PACKAGES is
refused for a mechanical history finding on any line, touched or not. The gate then exits
REFUSAL_EXIT. The list starts empty. No package is refused until it is added here.
"""

import argparse
import ast
import subprocess
import sys
import traceback

from . import comment_lint, docstring_lint, md_lint
from .changed_ranges import changed_line_ranges, filter_findings
from .cli import in_scope
from .rule_lists import BARE_SHA_REGEX, ID_REF_EXTENDED_REGEX
from .tool_runners import run_markdownlint, run_ruff
from .word_list import configure_root

# Repo-relative directory prefixes, each ending in a slash, for example "src/cosa/agents/".
BLOCKING_PACKAGES = ()
REFUSAL_EXIT      = 3
BARE_PREFIX       = "bare reference "
MECHANICAL_RULES  = frozenset( { "dated-banner", "iso-date", "agent-imperative" } )
HISTORY_HOME      = {
    "dated-banner"     : "the commit message or the Decisions Log",
    "iso-date"         : "the commit message or the Decisions Log",
    "bare-ref"         : "the commit message, the task row or a post-game",
    "agent-imperative" : "a prompt or skill file; the docstring states what the code does",
}


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


def in_blocking_package( path, packages ):
    """
    Say whether a repo-relative path sits inside a listed package.

    Requires:
        - path is a posix repo-relative path
        - packages is an iterable of directory prefixes that end in a slash

    Ensures:
        - True when the path starts with one of the prefixes, False otherwise

    Raises:
        - nothing
    """
    return any( path.startswith( prefix ) for prefix in packages )


def is_mechanical( finding ):
    """
    Say whether a finding is a history kind that a pattern decides.

    The kinds are a date, a dated banner, text addressed to a model, and a bare row, ticket, task or commit id.

    Requires:
        - finding is a Finding

    Ensures:
        - True for dated-banner, iso-date and agent-imperative
        - True for a bare-ref whose quoted text is a row, ticket or commit id
        - False for every other rule, and for a bare-ref that is a section, ruling, AC, step or label reference

    Raises:
        - nothing
    """
    if finding.rule in MECHANICAL_RULES: return True
    if finding.rule != "bare-ref" or not finding.message.startswith( BARE_PREFIX ): return False
    quoted = ast.literal_eval( finding.message[ len( BARE_PREFIX ) : ] )
    return bool( ID_REF_EXTENDED_REGEX.fullmatch( quoted ) or BARE_SHA_REGEX.fullmatch( quoted ) )


def refusal_line( finding ):
    """
    Format one refusal: the file, the line, the kind, and where the history goes instead.

    Requires:
        - finding is a mechanical Finding

    Ensures:
        - returns one line that starts with the [doc-lint] tag and the word "refused"

    Raises:
        - nothing
    """
    return f"[doc-lint] REFUSED {finding.path}:{finding.line}: {finding.rule}: {finding.message}; this history belongs in {HISTORY_HOME[ finding.rule ]}"


def collect( root ):
    """
    Gather the findings, warnings and refusals for the staged files.

    Requires:
        - root is a git working tree

    Ensures:
        - returns ( findings, warnings, refusals )
        - findings are limited to lines the staged diff touched, minus anything already in refusals
        - refusals hold every mechanical finding anywhere in a staged file inside BLOCKING_PACKAGES
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
    refusals = [ f for f in findings if in_blocking_package( f.path, BLOCKING_PACKAGES ) and is_mechanical( f ) ]
    kept     = [ f for f in filter_findings( findings, ranges ) if f not in refusals ]
    return kept, ruff_warnings + md_warnings, refusals


def main( argv=None, err=None ):
    """
    Run the gate.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]
        - err is a writable text stream, or None for sys.stderr

    Ensures:
        - returns REFUSAL_EXIT when a staged file in a listed package holds a mechanical history finding
        - otherwise returns 0 unless --blocking is given and findings remain
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
        root                         = git_toplevel( args.repo_root )
        findings, warnings, refusals = collect( root )
    except Exception as exc:
        err.write( f"[doc-lint] GATE CRASHED, commit allowed: {type( exc ).__name__}: {exc}\n" )
        err.write( traceback.format_exc() )
        return 0
    for warning in warnings: err.write( warning + "\n" )
    for f in findings: err.write( f"[doc-lint] {f.path}:{f.line}: {f.rule}: {f.message}\n" )
    for f in refusals: err.write( refusal_line( f ) + "\n" )
    if refusals:
        err.write( f"[doc-lint] {len( refusals )} history findings in listed packages, commit REFUSED\n" )
        return REFUSAL_EXIT
    err.write( f"[doc-lint] {len( findings )} findings on staged lines ({'blocking' if args.blocking else 'warn mode, commit allowed'})\n" )
    return 1 if args.blocking and findings else 0


if __name__ == "__main__":
    sys.exit( main() )
