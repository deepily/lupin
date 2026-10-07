"""
Pre-commit gate for the documentation standard (plan 1, section 4.2).

Lints the staged lines of Python and markdown files with ruff, markdownlint-cli2 and the
doc_lint rules and prints the findings to stderr. It exits 0 on its own crash too.
The hook is shared by every worktree, and a crashing gate must not block every seat.
A missing tool prints a loud warning. It does not read PLANNING_IS_PROMPTING_ROOT.

Three refusals break warn mode, and all exit REFUSAL_EXIT.

1. The swept scope, defined once in swept_scope.is_swept. A staged Python file for which it is True is refused when its docstring
   lint holds any finding on any line, touched or not, from any rule. The refusal names the file,
   line, rule, the text and where that text belongs. A finding is waived by a same-line marker,
   "doc-lint: waive <rule> -- <reason>". The reason needs a word of three letters or more.
   A marker without one waives nothing. A swept file that does not parse, or is not UTF-8, is refused and cannot be waived.
2. The counted scope: every other tracked Python file. Its finding count may not rise above its entry
   in the committed count table (counts.TABLE_PATH), and a new file starts at zero. A staged table may
   not raise an entry, except in the one commit that regenerates it under changed rules. A table cut
   under other rules refuses a commit that stages a counted file. With no table anywhere the scope is
   reported as not checked. The same waiver marker lowers a count.
3. BLOCKING_PACKAGES. A staged file inside a listed package is refused for a mechanical history
   finding on any line. The list starts empty.

Before any of these, a tracked rule file that differs between the index and the working tree refuses the commit.
The rule files are every tracked file in the doc_lint package, the word list and the chain script.
The findings would be counted under rules that are not the ones being committed.

Every run prints the denominator for both scopes: files checked, docstrings or counts, waivers honoured.
Everything else stays warn mode: findings on staged lines are printed and the commit goes through.
"""

import argparse
import ast
import subprocess
import sys
import traceback

from . import comment_lint, docstring_lint, md_lint
from . import counts
from .changed_ranges import changed_line_ranges, filter_findings
from .cli import in_scope
from .rule_lists import BARE_SHA_REGEX, ID_REF_EXTENDED_REGEX
from .swept_scope import is_swept
from .tool_runners import run_markdownlint, run_ruff
from .waivers import waiver_state
from .word_list import configure_root

# Repo-relative directory prefixes, each ending in a slash, for example "src/cosa/agents/".
BLOCKING_PACKAGES = ()
REFUSAL_EXIT      = 3
BARE_PREFIX       = "bare reference "
MECHANICAL_RULES  = frozenset( { "dated-banner", "iso-date", "agent-imperative" } )
TEXT_LIMIT       = 120
SHOWN_FINDINGS   = 10
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
    "not-utf-8"       : "UTF-8; save the file as UTF-8 so its docstrings can be checked",
    "parse-error"     : "valid Python; the file must parse before its docstrings can be checked",
}


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


def staged_counted( root ):
    """
    List the staged counted Python files, with their renames and whether the table is staged.

    Requires:
        - root is a git working tree

    Ensures:
        - returns ( paths, renamed_from, table_staged )
        - paths holds every added, copied, modified or renamed .py file that is not swept, with no in_scope filter
        - renamed_from maps the new path of each rename to the path it came from; a copy is seen as an addition, since only renames are detected, and inherits nothing
        - table_staged is True when counts.TABLE_PATH is among the staged files

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    res = subprocess.run( [ "git", "-C", root, "diff", "--cached", "-M", "--name-status", "-z", "--diff-filter=ACMR", "--", ":/" ], capture_output=True )
    if res.returncode != 0: raise RuntimeError( f"git diff --cached failed: {res.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    tokens = res.stdout.decode( "utf-8", "replace" ).split( "\0" )
    paths, renamed_from, table_staged, i = [], {}, False, 0
    while i < len( tokens ) and tokens[ i ]:
        status = tokens[ i ]
        if status[ 0 ] == "R":
            old, new, i = tokens[ i + 1 ], tokens[ i + 2 ], i + 3
            renamed_from[ new ] = old
        else:
            new, i = tokens[ i + 1 ], i + 2
        if new == counts.TABLE_PATH: table_staged = True
        if new.endswith( ".py" ) and not is_swept( new ): paths.append( new )
    return paths, renamed_from, table_staged


def staged_bytes( root, path ):
    """
    Read a file's bytes from the index, or from the working tree when the index has none.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the staged bytes, so the stamp covers what is being committed
        - a file the index does not hold is read from the working tree, so a rule file reached through a link still counts

    Raises:
        - OSError when the file is in neither place
    """
    res = subprocess.run( [ "git", "-C", root, "show", f":{path}" ], capture_output=True )
    if res.returncode == 0: return res.stdout
    with open( f"{root}/{path}", "rb" ) as handle: return handle.read()


def head_table_text( root ):
    """
    Read the count table as the last commit has it.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the text, or None when HEAD has no table or there is no HEAD yet

    Raises:
        - nothing
    """
    res = subprocess.run( [ "git", "-C", root, "show", f"HEAD:{counts.TABLE_PATH}" ], capture_output=True )
    return res.stdout.decode( "utf-8", "replace" ) if res.returncode == 0 else None


REGENERATE_COMMAND = 'LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" python3 -m cosa.repo.doc_lint.counts --repo-root "$PWD" --write'


def staged_deleted( root ):
    """
    List the files the staged commit deletes.

    Requires:
        - root is a git working tree

    Ensures:
        - returns repo-relative paths with a staged deletion, in git's order

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    res = subprocess.run( [ "git", "-C", root, "diff", "--cached", "--name-only", "-z", "--diff-filter=D", "--", ":/" ], capture_output=True )
    if res.returncode != 0: raise RuntimeError( f"git diff --cached failed: {res.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    return [ p for p in res.stdout.decode( "utf-8", "replace" ).split( "\0" ) if p ]


def counted_refusal( path, result, allowed, ranges, gone=() ):
    """
    Format the refusal for a counted file whose count rose above its entry.

    Requires:
        - result is a counts.FileCount with result.count above allowed
        - ranges is the staged diff's changed-line map

    Ensures:
        - returns one string: a header line, then up to SHOWN_FINDINGS findings with the touched ones first
        - the header names the count, the entry, and how to waive
        - gone lists deleted paths that had entries; when it is not empty the header says the file may be a rename
          that git no longer pairs, and names the way out

    Raises:
        - nothing
    """
    touched = filter_findings( result.findings, ranges )
    ordered = touched + [ f for f in result.findings if f not in touched ]
    lines   = [
        f"[doc-lint] REFUSED {path}: {result.count} findings, the count table allows {allowed} (+{result.count - allowed}); "
        f"reword the text you added, or waive a finding on its own line with: doc-lint: waive <rule> -- <reason>"
        + ( f"; this commit also deletes {', '.join( gone[ : 3 ] )}, which had an entry: if this file is a rename that git no longer pairs because too much changed, rename it in one commit and rewrite it in the next" if gone else "" )
    ]
    lines += [ f"[doc-lint]   {f.path}:{f.line}: {f.rule}: {f.message}" for f in ordered[ : SHOWN_FINDINGS ] ]
    if len( ordered ) > SHOWN_FINDINGS: lines.append( f"[doc-lint]   and {len( ordered ) - SHOWN_FINDINGS} more" )
    return "\n".join( lines )


def rule_divergence( compared, differing, judged ):
    """
    Refuse a commit whose staged rule files differ from the working copies.

    Requires:
        - compared is the number of rule files compared, differing the sorted paths that are not the same
        - judged is True when this commit stages a Python file the gate judges, or the count table

    Ensures:
        - returns None when no judgment is being made or no rule file differs
        - else returns one refusal string naming the files, how many were compared, and both ways out
        - the rule code that counts is the working tree's, so a difference could give a wrong verdict or a wrong table

    Raises:
        - nothing
    """
    if not judged or not differing: return None
    return (
        f"[doc-lint] REFUSED: rule file {', '.join( differing )} is not the same staged and in the working tree, so the findings were counted "
        f"under rules that are not the ones being committed; stage the edit with git add, or restore the file with git checkout, then commit again "
        f"({len( differing )} of {compared} rule files differ)"
    )


def counted_check( root, ranges ):
    """
    Hold the staged counted files to the count table.

    Requires:
        - root is a git working tree
        - ranges is the staged diff's changed-line map

    Ensures:
        - returns ( refusals, warnings, stats ); each refusal is one printable string, stats is the denominator
        - stats holds files, at_or_below, over, waivers and table, where table is ok, stale, absent, regenerated or malformed
        - with no table at HEAD and none staged, nothing is refused and the scope is reported as not checked
        - a staged table that raises an entry above HEAD is refused, unless it carries a new stamp
        - a new stamp must equal the stamp of the rule files now and the table must equal a census of the index
        - the current stamp is that of the staged rule files, so a staged rule edit moves it and an unstaged one does not
        - a table whose stamp is not the current one refuses a commit that stages a counted file
        - a counted file above its allowance is refused; a renamed file inherits its old entry; a new file has none

    Raises:
        - RuntimeError from git when a listing or read fails
        - OSError when a rule file cannot be read
    """
    paths, renamed_from, table_staged = staged_counted( root )
    stats    = { "files": 0, "at_or_below": 0, "over": 0, "waivers": 0, "table": "absent" }
    refusals = []
    warnings = []
    head_text = head_table_text( root )
    try:
        head = counts.parse_table( head_text ) if head_text is not None else None
    except counts.TableError as err:
        stats[ "table" ] = "malformed"
        return [], [ f"[doc-lint] WARNING: the count table at HEAD is malformed ({err}), the counted scope was NOT checked" ], stats
    try:
        staged = counts.parse_table( staged_source( root, counts.TABLE_PATH ) ) if table_staged else None
    except counts.TableError as err:
        stats[ "table" ] = "malformed"
        return [ f"[doc-lint] REFUSED {counts.TABLE_PATH}: the staged table is malformed: {err}" ], [], stats
    table = staged if staged is not None else head
    if table is None:
        if paths: warnings.append( "[doc-lint] WARNING: there is no count table at HEAD or staged, so the counted scope was NOT checked" )
        return refusals, warnings, stats
    current = counts.rules_stamp( root, read=lambda p: staged_bytes( root, p ) )
    if staged is not None and ( head is None or staged.stamp != head.stamp ):
        found, _walked = counts.census( root, read=lambda p: staged_source( root, p ) )
        problems       = counts.check_table( staged, found, current )
        stats[ "table" ] = "regenerated" if not problems else "stale"
        if problems:
            shown = [ f"[doc-lint]   {line}" for line in problems[ : SHOWN_FINDINGS ] ]
            if len( problems ) > SHOWN_FINDINGS: shown.append( f"[doc-lint]   and {len( problems ) - SHOWN_FINDINGS} more" )
            refusals.append( "\n".join( [ f"[doc-lint] REFUSED {counts.TABLE_PATH}: a regenerated table must equal a census of the staged tree under the current rules" ] + shown ) )
        return refusals, warnings, stats
    if staged is not None:
        for path, old, new in counts.table_raises( staged.files, head.files ):
            refusals.append( f"[doc-lint] REFUSED {counts.TABLE_PATH}: {path} raised from {old} to {new}; the table may only fall" )
    stats[ "table" ] = "ok" if table.stamp == current else "stale"
    if stats[ "table" ] == "stale":
        if paths: refusals.append( f"[doc-lint] REFUSED: the count table was cut under other rules (stamp {table.stamp}, now {current}); regenerate it with: {REGENERATE_COMMAND} and stage the table with the rule change" )
        return refusals, warnings, stats
    for path in paths:
        try:
            result = counts.file_count( path, staged_source( root, path ), root )
        except UnicodeDecodeError as err:
            result = counts.unreadable_count( path, err )
        allowed = counts.allowance( path, table.files, renamed_from )
        gone    = [ p for p in staged_deleted( root ) if p in table.files ] if allowed == 0 and path not in table.files and result.count > 0 else []
        stats[ "files" ]   += 1
        stats[ "waivers" ] += result.waivers
        if result.count > allowed:
            stats[ "over" ] += 1
            refusals.append( counted_refusal( path, result, allowed, ranges, gone ) )
        else:
            stats[ "at_or_below" ] += 1
    return refusals, warnings, stats


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
        - UnicodeDecodeError when the staged bytes are not UTF-8
    """
    res = subprocess.run( [ "git", "-C", root, "show", f":{path}" ], capture_output=True )
    if res.returncode != 0: raise RuntimeError( f"git show :{path} failed: {res.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    return res.stdout.decode( "utf-8-sig" )


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
        - a swept file that is not UTF-8 is refused the same way, counted in tally["undecodable"]; any other file that is not UTF-8 is skipped with a warning
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
    tally      = { "files": 0, "docstrings": 0, "findings": 0, "waivers": 0, "unparsed": 0, "undecodable": 0 }
    waived     = []
    refusals   = []
    warnings   = []
    skipped    = []
    decode_out = []
    for path in paths:
        try:
            source = staged_source( root, path ) if path.endswith( ( ".py", ".md" ) ) else None
        except UnicodeDecodeError as err:
            skipped.append( path )
            if is_swept( path ):
                tally[ "files" ] += 1
                tally[ "undecodable" ] += 1
                decode_out.append( f"[doc-lint] REFUSED {path}: not UTF-8: {err}; fix: {FIX_HOME[ 'not-utf-8' ]}; this cannot be waived" )
            else:
                warnings.append( f"[doc-lint] WARNING: {path} is not UTF-8, it was NOT checked" )
            continue
        if path.endswith( ".py" ):
            py_sources[ path ] = source
            doc_findings = docstring_lint.lint_source( path, source, root )
            findings += doc_findings + comment_lint.lint_source( path, source, root )
            if is_swept( path ): swept.append( ( path, source, doc_findings ) )
        elif path.endswith( ".md" ):
            findings += md_lint.lint_source( path, source, root )
    py, md   = [ p for p in paths if p.endswith( ".py" ) and p not in skipped ], [ p for p in paths if p.endswith( ".md" ) and p not in skipped ]
    ruff_findings, ruff_warnings = run_ruff( root, py, sources=py_sources )
    md_findings, md_warnings     = run_markdownlint( root, md )
    findings += ruff_findings + md_findings
    refusals = [ f for f in findings if in_blocking_package( f.path, BLOCKING_PACKAGES ) and is_mechanical( f ) ]
    lines_out = [ refusal_line( f ) for f in refusals ] + decode_out
    staged_counted_paths, _renames, table_staged = staged_counted( root )
    compared, differing = counts.differing_rule_files( root )
    tally[ "rules" ]    = { "compared": compared, "differing": len( differing ) }
    diverged = rule_divergence( compared, differing, bool( swept ) or bool( staged_counted_paths ) or table_staged )
    if diverged:
        lines_out.append( diverged )
        swept = []
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
    if diverged:
        tally[ "counted" ] = { "files": 0, "at_or_below": 0, "over": 0, "waivers": 0, "table": "diverged" }
    else:
        counted_refusals, counted_warnings, tally[ "counted" ] = counted_check( root, ranges )
        lines_out += counted_refusals
        warnings  += counted_warnings
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
    err.write( f"[doc-lint] swept scope: {tally[ 'files' ]} files checked, {tally[ 'docstrings' ]} docstrings checked, {tally[ 'findings' ]} findings, {tally[ 'waivers' ]} waivers honoured, {tally[ 'unparsed' ]} unparsed, {tally[ 'undecodable' ]} undecodable\n" )
    err.write( f"[doc-lint] rule files compared: {tally[ 'rules' ][ 'compared' ]}, differing: {tally[ 'rules' ][ 'differing' ]}\n" )
    c = tally[ "counted" ]
    err.write( f"[doc-lint] counted scope: {c[ 'files' ]} files checked, {c[ 'at_or_below' ]} at or below their count, {c[ 'over' ]} over, {c[ 'waivers' ]} waivers honoured, table {c[ 'table' ]}\n" )
    if refusals:
        err.write( f"[doc-lint] {len( refusals )} refusals, commit REFUSED\n" )
        return REFUSAL_EXIT
    err.write( f"[doc-lint] {len( findings )} findings on staged lines ({'blocking' if args.blocking else 'warn mode, commit allowed'})\n" )
    return 1 if args.blocking and findings else 0


if __name__ == "__main__":
    sys.exit( main() )
