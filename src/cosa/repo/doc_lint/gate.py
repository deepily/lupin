"""
Pre-commit gate for the documentation standard (plan 1, section 4.2).

Lints the staged lines of Python and markdown files with ruff, markdownlint-cli2 and the
doc_lint rules and prints the findings to stderr. It exits 0 on its own crash too.
The hook is shared by every worktree, and a crashing gate must not block every seat.
A missing tool prints a loud warning. It does not read PLANNING_IS_PROMPTING_ROOT.

Two refusals break warn mode, and both exit REFUSAL_EXIT.

1. The swept scope, defined once in swept_scope.is_swept. A staged Python file for which it is True is refused when its docstring
   lint holds any finding on any line, touched or not, from any rule. The refusal names the file,
   line, rule, the text and where that text belongs. A finding is waived by a same-line marker,
   "doc-lint: waive <rule> -- <reason>". The reason needs a word of three letters or more.
   A marker without one waives nothing. A swept file that does not parse is refused and cannot be waived.
2. BLOCKING_PACKAGES. A staged file inside a listed package is refused for a mechanical history
   finding on any line. The list starts empty.

Every run prints the denominator: files checked, docstrings checked, findings, waivers honoured.
Everything else stays warn mode: findings on staged lines are printed and the commit goes through.
"""

import argparse
import ast
import re
import subprocess
import sys
import traceback

from . import comment_lint, docstring_lint, md_lint
from .changed_ranges import changed_line_ranges, filter_findings
from .cli import in_scope
from .rule_lists import BARE_SHA_REGEX, ID_REF_EXTENDED_REGEX
from .swept_scope import is_swept
from .tool_runners import run_markdownlint, run_ruff
from .word_list import configure_root

# Repo-relative directory prefixes, each ending in a slash, for example "src/cosa/agents/".
BLOCKING_PACKAGES = ()
REFUSAL_EXIT      = 3
BARE_PREFIX       = "bare reference "
MECHANICAL_RULES  = frozenset( { "dated-banner", "iso-date", "agent-imperative" } )
REASON_WORD      = re.compile( r"[A-Za-z]{3,}" )
WAIVER_REGEX     = re.compile( r"doc-lint: waive (\S+)(?: -- (.*))?" )
TEXT_LIMIT       = 120
HISTORY_HOME      = {
    "dated-banner"     : "the commit message or the Decisions Log",
    "iso-date"         : "the commit message or the Decisions Log",
    "bare-ref"         : "the commit message, the task row or a post-game",
    "agent-imperative" : "a prompt or skill file; the docstring states what the code does",
}

FIX_HOME = {
    **HISTORY_HOME,
    "caps"            : "the same words in lower case; bold carries emphasis in a doc, capitals do not",
    "glyph"           : "plain words; an emphasis glyph does not belong in a docstring",
    "tic"             : "a plain statement of what the code does, without the stock phrase",
    "sentence-length" : "two or more shorter sentences",
    "summary-length"  : "a shorter first paragraph; detail goes after the blank line",
    "preface-length"  : "fewer lines before the contract; move the detail below Requires and Ensures",
    "docstring-length": "a shorter docstring; move the history and background to a design doc and link it",
    "dead-design"     : "a Design: path that exists, or no Design: line",
    "parse-error"     : "valid Python; the file must parse before its docstrings can be checked",
}


def waiver_state( finding, source_line ):
    """
    Read the waiver marker on the finding's own source line.

    Requires:
        - finding is a Finding
        - source_line is the text of the file line the finding sits on

    Ensures:
        - returns "honoured" when a marker names finding.rule and its reason holds a word of three letters or more
        - returns "no-reason" when a marker names the rule and its reason holds no such word
        - returns "none" otherwise, including a marker that names a different rule

    Raises:
        - nothing
    """
    state = "none"
    for m in WAIVER_REGEX.finditer( source_line ):
        if m.group( 1 ).strip( "\"'" ) != finding.rule: continue
        if REASON_WORD.search( m.group( 2 ) or "" ): return "honoured"
        state = "no-reason"
    return state


def swept_refusal_line( finding, source_line, state ):
    """
    Format one swept-scope refusal as a single line.

    The line gives the place, the text the rule matched, where that text belongs and how to waive it.

    Requires:
        - finding is a Finding
        - source_line is the text of the file line the finding sits on
        - state is a waiver_state result

    Ensures:
        - returns one line that starts with the [doc-lint] tag and the word refused in capitals
        - the line carries the file line's text, cut to TEXT_LIMIT characters
        - a no-reason state adds that the marker on the line gives no reason and waives nothing

    Raises:
        - nothing
    """
    text   = source_line.strip()
    text   = text if len( text ) <= TEXT_LIMIT else text[ : TEXT_LIMIT ] + "..."
    note   = "; a waiver marker is on this line but gives no reason, so it waives nothing" if state == "no-reason" else ""
    return (
        f"[doc-lint] REFUSED {finding.path}:{finding.line}: {finding.rule}: {finding.message}; line: {text!r}; "
        f"fix: {FIX_HOME.get( finding.rule, 'plain wording that states what the code does' )}; "
        f"to waive, end the line with: doc-lint: waive {finding.rule} -- <reason>{note}"
    )


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
        - a leading byte-order mark is dropped, so such a file parses like any other

    Raises:
        - RuntimeError naming the git error when the read fails
    """
    res = subprocess.run( [ "git", "-C", root, "show", f":{path}" ], capture_output=True, text=True, encoding="utf-8-sig" )
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
        - returns ( findings, warnings, refusal_lines, tally ); refusal_lines are the printable lines
        - findings are limited to lines the staged diff touched, minus anything already in refusals
        - refusals hold every mechanical finding anywhere in a staged file inside BLOCKING_PACKAGES
        - refusals also hold every docstring finding anywhere in a staged swept file that no waiver covers
        - a swept file that does not parse is refused, counted in tally["unparsed"], and cannot be waived
        - tally is the denominator: files, docstrings, findings, waivers, unparsed
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
    swept      = []
    tally      = { "files": 0, "docstrings": 0, "findings": 0, "waivers": 0, "unparsed": 0 }
    waived     = []
    refusals   = []
    warnings   = []
    for path in paths:
        if path.endswith( ".py" ):
            source = staged_source( root, path )
            py_sources[ path ] = source
            doc_findings = docstring_lint.lint_source( path, source, root )
            findings += doc_findings + comment_lint.lint_source( path, source, root )
            if is_swept( path ): swept.append( ( path, source, doc_findings ) )
        elif path.endswith( ".md" ):
            findings += md_lint.lint_source( path, staged_source( root, path ), root )
    py, md   = [ p for p in paths if p.endswith( ".py" ) ], [ p for p in paths if p.endswith( ".md" ) ]
    ruff_findings, ruff_warnings = run_ruff( root, py, sources=py_sources )
    md_findings, md_warnings     = run_markdownlint( root, md )
    findings += ruff_findings + md_findings
    refusals = [ f for f in findings if in_blocking_package( f.path, BLOCKING_PACKAGES ) and is_mechanical( f ) ]
    lines_out = [ refusal_line( f ) for f in refusals ]
    for path, source, doc_findings in swept:
        lines = source.split( "\n" )
        tally[ "files" ] += 1
        if doc_findings and doc_findings[ 0 ].rule == "parse-error":
            tally[ "unparsed" ] += 1
            refusals.append( doc_findings[ 0 ] )
            lines_out.append( f"[doc-lint] REFUSED {path}:{doc_findings[ 0 ].line}: parse-error: {doc_findings[ 0 ].message}; fix: {FIX_HOME[ 'parse-error' ]}; this cannot be waived" )
            continue
        tally[ "docstrings" ] += len( docstring_lint.extract_docstrings( source ) )
        tally[ "findings" ]   += len( doc_findings )
        for f in doc_findings:
            state = waiver_state( f, lines[ f.line - 1 ] )
            if state == "honoured":
                tally[ "waivers" ] += 1
                waived.append( f )
            elif f not in refusals:
                refusals.append( f )
                lines_out.append( swept_refusal_line( f, lines[ f.line - 1 ], state ) )
    kept     = [ f for f in filter_findings( findings, ranges ) if f not in refusals and f not in waived ]
    return kept, ruff_warnings + md_warnings + warnings, lines_out, tally


def main( argv=None, err=None ):
    """
    Run the gate.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]
        - err is a writable text stream, or None for sys.stderr

    Ensures:
        - returns REFUSAL_EXIT when a staged swept file holds an unwaived docstring finding, or a staged file in a listed package holds a mechanical history finding
        - prints the swept-scope denominator on every run that does not crash
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
        root                                = git_toplevel( args.repo_root )
        findings, warnings, refusals, tally = collect( root )
    except Exception as exc:
        err.write( f"[doc-lint] GATE CRASHED, commit allowed: {type( exc ).__name__}: {exc}\n" )
        err.write( traceback.format_exc() )
        return 0
    for warning in warnings: err.write( warning + "\n" )
    for f in findings: err.write( f"[doc-lint] {f.path}:{f.line}: {f.rule}: {f.message}\n" )
    for line in refusals: err.write( line + "\n" )
    err.write( f"[doc-lint] swept scope: {tally[ 'files' ]} files checked, {tally[ 'docstrings' ]} docstrings checked, {tally[ 'findings' ]} findings, {tally[ 'waivers' ]} waivers honoured, {tally[ 'unparsed' ]} unparsed\n" )
    if refusals:
        err.write( f"[doc-lint] {len( refusals )} refusals, commit REFUSED\n" )
        return REFUSAL_EXIT
    err.write( f"[doc-lint] {len( findings )} findings on staged lines ({'blocking' if args.blocking else 'warn mode, commit allowed'})\n" )
    return 1 if args.blocking and findings else 0


if __name__ == "__main__":
    sys.exit( main() )
