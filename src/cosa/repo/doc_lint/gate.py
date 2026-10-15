"""
Pre-commit gate for the documentation standard (plan 1, section 4.2).

Lints the staged lines of Python and markdown files with ruff, markdownlint-cli2 and the
doc_lint rules and prints the findings to stderr. It exits 0 on its own crash.
The hook is shared by every worktree, and a crashing gate must not block every seat.
A missing tool prints a loud warning. It does not read PLANNING_IS_PROMPTING_ROOT.
A staged gitlink, which is a submodule entry, holds no text and is named as not checked.
A markdown file whose name markdownlint-cli2 cannot be given is refused when that tool is installed.
With --blocking, a staged Python or markdown file git treats as binary refuses the commit, and so does a linter that fails on its files.

With --blocking, which the commit hook passes, a finding on a staged line refuses the commit.
Three kinds of finding are printed and let through instead. One is a finding in a file is_warn_only names.
One is a page-level finding (PAGE_LEVEL_RULES) that the last commit's copy of the page already had, no worse.
A page moved to another path is compared with the copy at its old path, whether or not the move also edits it.
One is a finding on a line that came in unchanged with the commit a merge or a cherry-pick is concluding.
Five more refusals apply with or without --blocking. Every refusal exits REFUSAL_EXIT.

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
3. The TypeScript and JavaScript counted scope: every tracked file tsdoc_lint accepts. The same rule as the Python
   counted scope, with its own table (ts_counts.TABLE_PATH) and its own rules stamp. A staged file is counted from
   the index through the Node extractor, in one run for the commit. A commit that stages none runs no extractor.
4. The exported-symbol scope: ts_doc_exists's files, its own table and stamp. A refusal says to add the doc comment, since a waiver has no line.
5. BLOCKING_PACKAGES. A staged file inside a listed package is refused for a mechanical history
   finding on any line. The list starts empty.

Before any of these, a tracked rule file that differs between the index and the working tree refuses the commit.
The rule files are every tracked file in the doc_lint package, the word list, the chain script and the extractor script.
The findings would be counted under rules that are not the ones being committed.

Every run prints the denominator for all four scopes: files checked, docstrings or counts, waivers honoured.
Without --blocking, every other finding on a staged line is printed and the commit goes through.
"""

import argparse
import ast
import os
import re
import subprocess
import sys
import traceback

from . import comment_lint, docstring_lint, md_lint
from collections import namedtuple

from . import counts, ts_counts, ts_doc_exists, tsdoc_lint
from .changed_ranges import PAGE_LEVEL_RULES, changed_line_ranges, filter_findings
from .cli import SURROGATE, in_scope, line_text, shown, split_lines, split_names
from .rule_lists import BARE_SHA_REGEX, ID_REF_EXTENDED_REGEX
from .swept_scope import is_swept
from .tool_runners import Unchecked, markdownlint_unnamed, run_markdownlint, run_ruff
from .waivers import waiver_state
from .word_list import configure_root

# Repo-relative directory prefixes, each ending in a slash, for example "src/cosa/agents/".
BLOCKING_PACKAGES = ()
REFUSAL_EXIT      = 3
# The locations --blocking leaves in warn mode. WARN_ONLY_PATHS holds exact repo-relative paths.
# A file of the same name in any other folder, src/cosa/history.md among them, is held like every other page.
# WARN_ONLY_PREFIXES holds folders, each ending in a slash and matched from the repo root.
# So src/cosa/history/ is not among them, and neither is a history/ folder below the root.
# Rick's ruling on the card "María: four rulings", task-store row id=486cc499: history/ and todo-history/ stay warn-only as a
# standing exception ("Yes, standing exception"), because 18,649 findings sit on archive text nobody will rewrite.
WARN_ONLY_PATHS    = ()
WARN_ONLY_PREFIXES = ( "history/", "todo-history/" )
# The root record files. They block, judged on added lines, under rule set B of the same ruling ("I'll go with your
# recommended set B"): the rules in RECORD_RULES_OFF and RECORD_DATE_RULES, and a bare-ref of the row-id-or-sha kind,
# do not apply to them, since a record is where dates, rows and commits are cited. Every other rule blocks.
RECORD_PATHS       = ( "history.md", "TODO.md", "bug-fix-queue.md" )
RECORD_DATE_RULES  = frozenset( { "iso-date", "dated-banner" } )
# Rick ruled these two off for now, and said they come back once the writing rules are fixed (row 8188ff76).
# To turn them back on, make this frozenset() and nothing else changes.
RECORD_RULES_OFF   = frozenset( { "caps", "sentence-length" } )
WARN_ONLY_MARK     = " (warn mode, commit allowed)"
PREDATES_MARK      = " (warn mode, commit allowed: this condition predates the commit)"
MERGED_MARK        = " (warn mode, commit allowed: this line came in with the merged or picked commit)"
# The files git keeps in its directory while a merge or a cherry-pick waits to be concluded. A revert is not among them.
INCOMING_HEADS     = ( "MERGE_HEAD", "CHERRY_PICK_HEAD" )
UNBOUNDED          = 1 << 60       # the end of a range that holds every line of a file
FULL_SHA           = re.compile( r"[0-9a-f]{40,64}" )
# A carriage return that no line feed follows. Python's parser ends a line there and git does not.
BARE_RETURN        = re.compile( "\r(?!\n)" )
# The mode git records for a submodule entry. Such an entry names a commit of another repository and holds no text.
GITLINK_MODE       = "160000"
# The mode git records for a symbolic link. Its blob is the target path, so it is no page and no source file.
SYMLINK_MODE       = "120000"
NUMBER             = re.compile( r"\d+" )
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
    "dead-design"     : "a Design: path that exists in the tree, or one outside it (not judged), or no Design: line",
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
        f"[doc-lint] REFUSED {shown( finding.path )}:{finding.line}: {finding.rule}: {finding.message}; line: {text!r}; "
        f"fix: {FIX_HOME.get( finding.rule, 'plain wording that states what the code does' )}; "
        f"to waive, end the line with: doc-lint: waive {finding.rule} -- <reason>{note}"
    )


def is_warn_only( path ):
    """
    Say whether --blocking leaves a file's findings in warn mode.

    Requires:
        - path is a posix repo-relative path

    Ensures:
        - True when path equals an entry of WARN_ONLY_PATHS, or starts with an entry of WARN_ONLY_PREFIXES
        - a file named like a listed path, at any other path, is False
        - a folder whose name only starts with the letters of a listed folder is False, since an entry ends in a slash
        - a folder of a listed name below the root is False, since a prefix is matched from the start of the path

    Raises:
        - nothing
    """
    return path in WARN_ONLY_PATHS or path.startswith( WARN_ONLY_PREFIXES )


def is_record_exempt( finding ):
    """
    Say whether rule set B drops a finding in a root record file.

    Requires:
        - finding is a Finding

    Ensures:
        - False for a file outside RECORD_PATHS, whatever the rule
        - True for a rule in RECORD_DATE_RULES or RECORD_RULES_OFF
        - True for a bare-ref whose quoted text is a row, ticket or commit id
        - False for every other rule, a bare-ref of the section or label kind and agent-imperative included

    Raises:
        - nothing
    """
    if finding.path not in RECORD_PATHS: return False
    if finding.rule in RECORD_DATE_RULES or finding.rule in RECORD_RULES_OFF: return True
    return finding.rule == "bare-ref" and is_mechanical( finding )


def page_condition( finding ):
    """
    Name the condition a page-level finding reports, apart from how large it is.

    Requires:
        - finding is a Finding whose rule is in PAGE_LEVEL_RULES

    Ensures:
        - returns ( key, measure )
        - key is the rule and the message with each number replaced by #, so two sizes of one condition share a key
        - measure is the first number in the message, or None when the message holds none

    Raises:
        - nothing
    """
    numbers = NUMBER.findall( finding.message )
    return ( finding.rule, NUMBER.sub( "#", finding.message ) ), ( int( numbers[ 0 ] ) if numbers else None )


def predating( root, findings, renamed_from ):
    """
    Pick the page-level findings whose condition the last commit's copy already had.

    Requires:
        - root is a git working tree
        - findings are the findings on staged lines; renamed_from is the map staged_changes gives

    Ensures:
        - returns the findings in PAGE_LEVEL_RULES that HEAD's copy of the page also has, with a measure that did not rise
        - a renamed page is compared with the page it was renamed from, linted under the path it had at HEAD
        - so a page moved to a path that brings a limit has no earlier condition, and the commit that moved it created it
        - a page moved out of a folder the gate does not judge, such as src/rnd, has no earlier condition either: it was never judged there
        - a page HEAD does not hold has no earlier condition, so none of its findings is returned
        - HEAD's copy is linted under the rules of this commit
        - a finding outside PAGE_LEVEL_RULES is never returned

    Raises:
        - nothing
    """
    kept, before = [], {}
    for f in findings:
        if f.rule not in PAGE_LEVEL_RULES: continue
        if f.path not in before:
            old  = renamed_from.get( f.path, f.path )
            text = head_table_text( root, old ) if in_scope( old ) else None
            before[ f.path ] = dict( page_condition( h ) for h in md_lint.lint_source( old, text, root ) if h.rule in PAGE_LEVEL_RULES ) if text is not None else {}
        key, measure = page_condition( f )
        if key in before[ f.path ] and ( measure is None or measure <= before[ f.path ][ key ] ): kept.append( f )
    return kept


def incoming_commits( root ):
    """
    Name every commit that a merge or a cherry-pick in progress is bringing in.

    Requires:
        - root is a git working tree, the main one or a linked one

    Ensures:
        - returns ( shas, warnings )
        - shas holds each line of the first INCOMING_HEADS file found in this working tree's own git directory that names a commit, in order: an octopus merge has one line per merged parent
        - shas is [] when no such file exists, which is every ordinary commit
        - a file with no line that names a commit in the repository is ignored, and warnings then holds one loud line that says so
        - a file that cannot be read is ignored the same way, with a line that names the error
        - an ignored file lets no finding off, so every finding is enforced
        - a revert in progress is not looked at

    Raises:
        - nothing
    """
    warnings = []
    for name in INCOMING_HEADS:
        res  = subprocess.run( [ "git", "-C", root, "rev-parse", "--path-format=absolute", "--git-path", name ], capture_output=True )
        path = os.fsdecode( res.stdout ).strip( "\n" )
        if not os.path.isfile( path ): continue
        try:
            with open( path, encoding="utf-8", errors="replace" ) as handle: lines = [ ln.strip() for ln in handle.read().split( "\n" ) ]
        except OSError as err:
            warnings.append( f"[doc-lint] WARNING: {name} could not be read ({type( err ).__name__}), so it was ignored and every finding is enforced" )
            continue
        shas = [ ln for ln in lines if FULL_SHA.fullmatch( ln ) and subprocess.run( [ "git", "-C", root, "cat-file", "-e", f"{ln}^{{commit}}" ], capture_output=True ).returncode == 0 ]
        if shas: return shas, warnings
        warnings.append( f"[doc-lint] WARNING: {name} names no commit in this repository, so it was ignored and every finding is enforced" )
    return [], warnings


def incoming_commit( root ):
    """
    Name the first commit that a merge or a cherry-pick in progress is bringing in.

    Requires:
        - root is a git working tree, the main one or a linked one

    Ensures:
        - returns ( sha, warnings ) as incoming_commits gives them, sha being its first commit or None when it gives none

    Raises:
        - nothing
    """
    shas, warnings = incoming_commits( root )
    return ( shas[ 0 ] if shas else None ), warnings


def merged_in( root, findings, incoming ):
    """
    Pick the findings on lines that came in unchanged with a commit being merged or picked.

    Requires:
        - root is a git working tree
        - findings are the findings on staged lines; incoming is a sha incoming_commit gave, a list of them from incoming_commits, or None

    Ensures:
        - returns [] when incoming is None or empty
        - else returns each finding whose line is the same in the index and in the copy of the file of at least one incoming commit
        - a line that differs from every incoming copy, such as one written while resolving a conflict, is not returned
        - a page-level finding is returned only when the whole file is the same as an incoming commit's copy

    Raises:
        - RuntimeError from git when the diff against an incoming commit fails
    """
    shas = [] if incoming is None else [ incoming ] if isinstance( incoming, str ) else list( incoming )
    if not shas: return []
    came = set()
    for sha in shas:
        differs = { id( f ) for f in filter_findings( findings, changed_line_ranges( root, None, cached=True, against=sha ) ) }
        came   |= { id( f ) for f in findings if id( f ) not in differs }
    return [ f for f in findings if id( f ) in came ]


def staged_entries( root, against=None ):
    """
    List the staged changes that leave a path in the index, with the gitlinks apart.

    Requires:
        - root is a git working tree
        - against is a commit to compare the index with in place of HEAD, or None

    Ensures:
        - the changes are additions, copies, modifications, renames and type changes
        - returns ( names, renamed_from, gitlinks, changed, symlinks ), names being the new path of every change that is neither a gitlink nor a symbolic link, in git's order
        - changed is the set of new paths whose staged blob id is not the old side's, so a move or a change of mode alone is not in it
        - the old side of a rename is the path it came from; with against no rename is followed, so the old side is that commit's same path
        - renamed_from maps the new path of each rename to the path it came from; a copy is seen as an addition, since only renames are detected, and inherits nothing
        - gitlinks holds the new path of every change whose staged entry is a submodule entry, which has no text to read
        - symlinks holds the new path of every change whose staged entry is a symbolic link, whose blob is its target path and not a page
        - a type change is listed, so a link replaced by a file is read and a file replaced by a gitlink is named
        - names are read apart at the NUL byte and decoded as the file system decodes them

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    compared = [ "-M" ] if against is None else [ "--no-renames", against ]
    res      = subprocess.run( [ "git", "-C", root, "diff", "--cached", *compared, "--raw", "-z", "--no-abbrev", "--diff-filter=ACMRT", "--", ":/" ], capture_output=True )
    if res.returncode != 0: raise RuntimeError( f"git diff --cached failed: {res.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    tokens = res.stdout.split( b"\0" )
    names, renamed_from, gitlinks, changed, symlinks, i = [], {}, [], set(), [], 0
    while i < len( tokens ) and tokens[ i ]:
        fields = tokens[ i ].decode( "ascii" ).split( " " )
        if fields[ 4 ][ 0 ] == "R":
            old, new, i = os.fsdecode( tokens[ i + 1 ] ), os.fsdecode( tokens[ i + 2 ] ), i + 3
            renamed_from[ new ] = old
        else:
            new, i = os.fsdecode( tokens[ i + 1 ] ), i + 2
        ( gitlinks if fields[ 1 ] == GITLINK_MODE else symlinks if fields[ 1 ] == SYMLINK_MODE else names ).append( new )
        if fields[ 2 ] != fields[ 3 ]: changed.add( new )
    return names, renamed_from, gitlinks, changed, symlinks


def staged_binary( root ):
    """
    List the staged files whose change git treats as binary.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the new path of every addition, modification and type change for which git counts no lines, in git's order
        - the verdict is git's own, the one that makes its diff carry no line numbers for the file
        - a rename is read as an addition, so a moved file is named by its new path

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    res = subprocess.run( [ "git", "-C", root, "diff", "--cached", "--no-renames", "--numstat", "-z", "--diff-filter=ACMRT", "--", ":/" ], capture_output=True )
    if res.returncode != 0: raise RuntimeError( f"git diff --cached failed: {res.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    return [ os.fsdecode( entry[ 4 : ] ) for entry in res.stdout.split( b"\0" ) if entry.startswith( b"-\t-\t" ) ]


def staged_changes( root ):
    """
    List the staged changes the gate reads as files.

    Requires:
        - root is a git working tree

    Ensures:
        - returns ( names, renamed_from ) as staged_entries gives them, so no gitlink and no symbolic link is among the names

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    return staged_entries( root )[ : 2 ]


def staged_counted( root ):
    """
    List the staged counted Python files, with their renames and whether the table is staged.

    Requires:
        - root is a git working tree

    Ensures:
        - returns ( paths, renamed_from, table_staged )
        - paths holds every added, copied, modified or renamed .py file that is not swept, with no in_scope filter
        - renamed_from is the map staged_changes gives
        - table_staged is True when counts.TABLE_PATH is among the staged files

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    names, renamed_from = staged_changes( root )
    return [ n for n in names if n.endswith( ".py" ) and not is_swept( n ) ], renamed_from, counts.TABLE_PATH in names


def staged_ts_counted( root ):
    """
    List the staged TypeScript and JavaScript files, with renames and the table flag.

    Requires:
        - root is a git working tree

    Ensures:
        - returns ( paths, renamed_from, table_staged )
        - paths holds every added, copied, modified or renamed file that tsdoc_lint.in_scope accepts
        - renamed_from is the map staged_changes gives
        - table_staged is True when ts_counts.TABLE_PATH is among the staged files

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    names, renamed_from = staged_changes( root )
    return [ n for n in names if tsdoc_lint.in_scope( n ) ], renamed_from, ts_counts.TABLE_PATH in names


def staged_exports_counted( root ):
    """
    List the staged script files whose exports are counted, with renames and the table flag.

    Requires:
        - root is a git working tree

    Ensures:
        - returns ( paths, renamed_from, table_staged )
        - paths holds the files staged_ts_counted lists, less those under ts_doc_exists.EXCLUDED_PREFIXES
        - renamed_from is the map staged_changes gives
        - table_staged is True when ts_doc_exists.TABLE_PATH is among the staged files

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    names, renamed_from = staged_changes( root )
    paths = [ n for n in names if tsdoc_lint.in_scope( n ) and not n.startswith( ts_doc_exists.EXCLUDED_PREFIXES ) ]
    return paths, renamed_from, ts_doc_exists.TABLE_PATH in names


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


def head_table_text( root, table_path=counts.TABLE_PATH ):
    """
    Read a count table, or any other file, as the last commit has it.

    Requires:
        - root is a git working tree
        - table_path is the file's repo-relative path, the Python table by default

    Ensures:
        - returns the text, or None when HEAD has no such file or there is no HEAD yet

    Raises:
        - nothing
    """
    res = subprocess.run( [ "git", "-C", root, "show", f"HEAD:{table_path}" ], capture_output=True )
    return res.stdout.decode( "utf-8", "replace" ) if res.returncode == 0 else None


REGENERATE_COMMAND = 'LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" python3 -m cosa.repo.doc_lint.counts --repo-root "$PWD" --write'
REGENERATE_TS      = 'LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" python3 -m cosa.repo.doc_lint.ts_counts --repo-root "$PWD" --write'
REGENERATE_EXPORTS = 'LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" python3 -m cosa.repo.doc_lint.ts_doc_exists --repo-root "$PWD" --write'
TS_NAME            = "TypeScript and JavaScript"
EXPORTS_NAME       = "exported-symbol doc"
EXPORTS_ADVICE     = "add a doc comment to each exported symbol listed below"


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
    return split_names( res.stdout )


def counted_refusal( path, result, allowed, ranges, gone=(), advice=None ):
    """
    Format the refusal for a counted file whose count rose above its entry.

    Requires:
        - result is a counts.FileCount with result.count above allowed
        - ranges is the staged diff's changed-line map

    Ensures:
        - returns one string: a header line, then up to SHOWN_FINDINGS findings with the touched ones first
        - the header names the count, the entry, and how to waive, or advice when advice is given
        - gone lists deleted paths that had entries; when it is not empty the header says the file may be a rename
          that git no longer pairs, and names the way out
        - advice replaces the waiver sentence for a count that has no line to carry a waiver marker

    Raises:
        - nothing
    """
    touched = filter_findings( result.findings, ranges )
    ordered = touched + [ f for f in result.findings if f not in touched ]
    lines   = [
        f"[doc-lint] REFUSED {shown( path )}: {result.count} findings, the count table allows {allowed} (+{result.count - allowed}); "
        f"{advice if advice is not None else 'reword the text you added, or waive a finding on its own line with: doc-lint: waive <rule> -- <reason>'}"
        + ( f"; this commit also deletes {', '.join( shown( g ) for g in gone[ : 3 ] )}, which had an entry: if this file is a rename that git no longer pairs because too much changed, rename it in one commit and rewrite it in the next" if gone else "" )
    ]
    lines += [ f"[doc-lint]   {shown( f.path )}:{f.line}: {f.rule}: {f.message}" for f in ordered[ : SHOWN_FINDINGS ] ]
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
        f"[doc-lint] REFUSED: rule file {', '.join( shown( d ) for d in differing )} is not the same staged and in the working tree, so the findings were counted "
        f"under rules that are not the ones being committed; stage the edit with git add, or restore the file with git checkout, then commit again "
        f"({len( differing )} of {compared} rule files differ)"
    )


Scope = namedtuple( "Scope", [ "noun", "table_path", "staged", "count_many", "census", "stamp", "regenerate", "advice" ], defaults=[ None ] )


def _python_counts( root, paths ):
    """
    Count the findings of staged counted Python files, read from the index.

    Requires:
        - root is a git working tree; paths are staged Python files

    Ensures:
        - returns { path: counts.FileCount }; a file that is not UTF-8 counts as one finding

    Raises:
        - RuntimeError from git when a read fails
    """
    found = {}
    for path in paths:
        try:
            found[ path ] = counts.file_count( path, staged_source( root, path ), root )
        except UnicodeDecodeError as err:
            found[ path ] = counts.unreadable_count( path, err )
    return found


def _ts_counts( root, paths ):
    """
    Count the findings of staged TypeScript and JavaScript files, read from the index.

    Requires:
        - root is a git working tree; paths are staged TypeScript or JavaScript files

    Ensures:
        - returns { path: counts.FileCount }; a file that is not UTF-8 counts as one finding
        - one extractor run covers every readable file

    Raises:
        - RuntimeError from git or the extractor
    """
    found, texts = {}, {}
    for path in paths:
        try:
            texts[ path ] = staged_source( root, path )
        except UnicodeDecodeError as err:
            found[ path ] = counts.unreadable_count( path, err )
    found.update( ts_counts.counts_for( root, texts ) if texts else {} )
    return found


def _exports_counts( root, paths ):
    """
    Count the undocumented exports of staged script files, read from the index.

    Requires:
        - root is a git working tree; paths are staged TypeScript or JavaScript files

    Ensures:
        - returns { path: counts.FileCount }; a file that is not UTF-8 counts as one finding
        - one extractor run covers every readable file

    Raises:
        - RuntimeError from git or the extractor
    """
    found, texts = {}, {}
    for path in paths:
        try:
            texts[ path ] = staged_source( root, path )
        except UnicodeDecodeError as err:
            found[ path ] = counts.unreadable_count( path, err )
    found.update( ts_doc_exists.counts_for( root, texts ) if texts else {} )
    return found


def _python_stamp( root, read ):
    """Return the Python rules stamp, looked up when called."""
    return counts.rules_stamp( root, read=read )


def _python_census( root, read ):
    """Return the Python census, looked up when called."""
    return counts.census( root, read=read )


def _ts_stamp( root, read ):
    """Return the TypeScript and JavaScript rules stamp, looked up when called."""
    return ts_counts.rules_stamp( root, read=read )


def _ts_census( root, read ):
    """Return the TypeScript and JavaScript census, looked up when called."""
    return ts_counts.census( root, read=read )


def _exports_stamp( root, read ):
    """Return the exports rules stamp, looked up when called."""
    return ts_doc_exists.rules_stamp( root, read=read )


def _exports_census( root, read ):
    """Return the exports census, looked up when called."""
    return ts_doc_exists.census_of_texts( root, read )


PYTHON_SCOPE = Scope( "", counts.TABLE_PATH, staged_counted, _python_counts, _python_census, _python_stamp, REGENERATE_COMMAND )
TS_SCOPE     = Scope( f"{TS_NAME} ", ts_counts.TABLE_PATH, staged_ts_counted, _ts_counts, _ts_census, _ts_stamp, REGENERATE_TS )
EXPORTS_SCOPE = Scope( f"{EXPORTS_NAME} ", ts_doc_exists.TABLE_PATH, staged_exports_counted, _exports_counts, _exports_census, _exports_stamp, REGENERATE_EXPORTS, EXPORTS_ADVICE )


def scope_check( root, ranges, scope ):
    """
    Hold the staged files of one counted scope to its count table.

    Requires:
        - root is a git working tree
        - ranges is the staged diff's changed-line map
        - scope is PYTHON_SCOPE, TS_SCOPE or EXPORTS_SCOPE

    Ensures:
        - returns ( refusals, warnings, stats ); each refusal is one printable string, stats is the denominator
        - stats holds files, at_or_below, over, waivers and table, where table is ok, stale, absent, regenerated or malformed
        - with no table at HEAD and none staged, nothing is refused and the scope is reported as not checked
        - a table at HEAD that cannot be read refuses a commit that stages a counted file and names the fix
        - the same commit passes when it stages a readable table, which is then judged as a regeneration
        - with no counted file staged, an unreadable table at HEAD is a warning
        - a staged table that raises an entry above HEAD is refused, unless it carries a new stamp
        - a new stamp must equal the stamp of the rule files now and the table must equal a census of the index
        - the current stamp is that of the staged rule files, so a staged rule edit moves it and an unstaged one does not
        - a table whose stamp is not the current one refuses a commit that stages a counted file
        - a counted file above its allowance is refused; a renamed file inherits its old entry; a new file has none
        - a commit without staged files of the scope counts nothing and runs no extractor

    Raises:
        - RuntimeError from git when a listing or read fails
        - OSError when a rule file cannot be read
    """
    paths, renamed_from, table_staged = scope.staged( root )
    noun     = scope.noun
    stats    = { "files": 0, "at_or_below": 0, "over": 0, "waivers": 0, "table": "absent" }
    refusals = []
    warnings = []
    head_text = head_table_text( root, scope.table_path )
    unreadable = None
    try:
        head = counts.parse_table( head_text ) if head_text is not None else None
    except counts.TableError as err:
        head, unreadable = None, err
    try:
        staged = counts.parse_table( staged_source( root, scope.table_path ) ) if table_staged else None
    except counts.TableError as err:
        stats[ "table" ] = "malformed"
        return [ f"[doc-lint] REFUSED {scope.table_path}: the staged table is malformed: {err}" ], [], stats
    if unreadable is not None and staged is None:
        stats[ "table" ] = "malformed"
        if not paths: return [], [ f"[doc-lint] WARNING: the {noun}count table at HEAD is malformed ({unreadable}), the {noun}counted scope was NOT checked" ], stats
        return [ f"[doc-lint] REFUSED {scope.table_path}: the {noun}count table at HEAD is malformed ({unreadable}), so no staged file can be counted; stage a regenerated one: {scope.regenerate}" ], [], stats
    table = staged if staged is not None else head
    if table is None:
        if paths: warnings.append( f"[doc-lint] WARNING: there is no {noun}count table at HEAD or staged, so the {noun}counted scope was NOT checked" )
        return refusals, warnings, stats
    current = scope.stamp( root, lambda p: staged_bytes( root, p ) )
    if staged is not None and ( head is None or staged.stamp != head.stamp ):
        found, _walked = scope.census( root, lambda p: staged_source( root, p ) )
        problems       = counts.check_table( staged, found, current )
        stats[ "table" ] = "regenerated" if not problems else "stale"
        if problems:
            shown = [ f"[doc-lint]   {line}" for line in problems[ : SHOWN_FINDINGS ] ]
            if len( problems ) > SHOWN_FINDINGS: shown.append( f"[doc-lint]   and {len( problems ) - SHOWN_FINDINGS} more" )
            refusals.append( "\n".join( [ f"[doc-lint] REFUSED {scope.table_path}: a regenerated table must equal a census of the staged tree under the current rules" ] + shown ) )
        return refusals, warnings, stats
    if staged is not None:
        for path, old, new in counts.table_raises( staged.files, head.files ):
            refusals.append( f"[doc-lint] REFUSED {scope.table_path}: {path} raised from {old} to {new}; the table may only fall" )
    stats[ "table" ] = "ok" if table.stamp == current else "stale"
    if stats[ "table" ] == "stale":
        if paths: refusals.append( f"[doc-lint] REFUSED: the {noun}count table was cut under other rules (stamp {table.stamp}, now {current}); regenerate it with: {scope.regenerate} and stage the table with the rule change; if this tree holds only part of a landed rule change, take the landed table by merging or rebasing instead" )
        return refusals, warnings, stats
    results = scope.count_many( root, paths )
    for path in paths:
        result  = results[ path ]
        allowed = counts.allowance( path, table.files, renamed_from )
        gone    = [ p for p in staged_deleted( root ) if p in table.files ] if allowed == 0 and path not in table.files and result.count > 0 else []
        stats[ "files" ]   += 1
        stats[ "waivers" ] += result.waivers
        if result.count > allowed:
            stats[ "over" ] += 1
            refusals.append( counted_refusal( path, result, allowed, ranges, gone, scope.advice ) )
        else:
            stats[ "at_or_below" ] += 1
    return refusals, warnings, stats


def counted_check( root, ranges ):
    """
    Hold the staged counted Python files to the count table.

    Requires:
        - root is a git working tree
        - ranges is the staged diff's changed-line map

    Ensures:
        - returns what scope_check returns for the Python scope

    Raises:
        - RuntimeError from git when a listing or read fails
        - OSError when a rule file cannot be read
    """
    return scope_check( root, ranges, PYTHON_SCOPE )


def ts_counted_check( root, ranges ):
    """
    Hold the staged TypeScript and JavaScript files to their count table.

    Requires:
        - root is a git working tree
        - ranges is the staged diff's changed-line map

    Ensures:
        - returns what scope_check returns for the TypeScript and JavaScript scope

    Raises:
        - RuntimeError from git or the extractor when a listing, read or extraction fails
        - OSError when a rule file cannot be read
    """
    return scope_check( root, ranges, TS_SCOPE )


def exports_counted_check( root, ranges ):
    """
    Hold the staged script files to their table of undocumented exports.

    Requires:
        - root is a git working tree
        - ranges is the staged diff's changed-line map

    Ensures:
        - returns what scope_check returns for the exported-symbol scope

    Raises:
        - RuntimeError from git or the extractor when a listing, read or extraction fails
        - OSError when a rule file cannot be read
    """
    return scope_check( root, ranges, EXPORTS_SCOPE )


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
        - names are read apart at the NUL byte, so a name git would quote is listed as it is
        - a gitlink is not among them, since it has no text

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    return [ p for p in staged_entries( root )[ 0 ] if in_scope( p ) ]


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
    return f"[doc-lint] REFUSED {shown( finding.path )}:{finding.line}: {finding.rule}: {finding.message}; this history belongs in {HISTORY_HOME[ finding.rule ]}"


def collect( root ):
    """
    Gather the findings, warnings and refusals for the staged files.

    Requires:
        - root is a git working tree

    Ensures:
        - returns ( findings, warnings, refusal_lines, tally ); refusal_lines are the printable lines
        - findings are limited to lines the staged diff touched, minus anything already in refusals
        - a finding is_record_exempt names is left out, so a root record file is judged under rule set B
        - a refused or waived finding is left out as that one finding; a finding of another linter with the same place and words stays
        - a docstring finding with an honoured waiver marker on its line is left out of findings, in a swept file and in any other Python file
        - refusals hold every mechanical finding anywhere in a staged file inside BLOCKING_PACKAGES
        - refusals also hold every docstring finding anywhere in a staged swept file that no waiver covers
        - a swept file that does not parse is refused, counted in tally["unparsed"], and cannot be waived
        - a swept file that is not UTF-8 is refused the same way, counted in tally["undecodable"]; any other file that is not UTF-8 is skipped with a warning
        - that warning is an Unchecked when the commit adds the file or changes its content, and is_warn_only does not name it, as for a file git treats as binary
        - tally is the denominator: files, docstrings, findings, waivers, unparsed, and one count block for each counted scope
        - ruff reads the staged text of each Python file through stdin, not the working-tree file
        - a staged gitlink whose name a linter would read adds one warning that says it was not checked, and is read by no linter
        - a staged symbolic link whose name a linter would read adds one warning the same way: its blob is a target path, not a page
        - that warning is an Unchecked when the link's name is a swept Python file or a TypeScript file and the commit adds the link or changes its target, since the language imports it as source
        - a link whose name is no source file but sits under src/ where a swept Python or TypeScript file would, is treated the same, since it can stand for a whole directory of them
        - it stays a plain warning for a link named like a page, whose target is judged as itself, and for a link the commit only moves
        - a markdown file that markdownlint_unnamed lists is refused, since that tool could not check it; this cannot be waived
        - a staged Python or markdown file that staged_binary lists adds one warning, since the diff gives no touched line for it
        - that warning is an Unchecked when the commit adds the file or changes its content, and is_warn_only does not name it
        - it is a plain warning when the staged blob is the one HEAD holds, at the path the file was renamed from if it was renamed
        - while a merge or a cherry-pick waits to be concluded, it is also plain when the staged blob is the incoming commit's at that path
        - a waiver is read from the line the parser numbers, so a file with bare carriage returns is judged and never crashes the gate
        - git does not end a line at a bare carriage return, so its line numbers for such a Python file are not the parser's
        - every line of such a file counts as touched when the commit touches any of it
        - a page moved without an edit keeps its page-level findings, since the diff reader gives a move its entry
        - a page moved without an edit from a folder the gate does not judge is judged like a new file: every line counts as touched
        - such a move also counts as created for the not-UTF-8 and binary warnings, so a page the gate cannot read is refused as a new file is
        - Python files get docstring_lint, comment_lint and ruff; markdown files get md_lint and markdownlint

    Raises:
        - RuntimeError from git when a listing, diff or read fails
    """
    configure_root( root )
    paths    = staged_paths( root )
    gitlinks = [ p for p in staged_entries( root )[ 2 ] if p.endswith( ( ".py", ".md" ) ) or tsdoc_lint.in_scope( p ) ]
    ranges   = changed_line_ranges( root, None, cached=True )
    moved_in = set()
    for new, old in staged_changes( root )[ 1 ].items():
        if not in_scope( old ) and in_scope( new ):
            ranges[ new ] = [ ( 1, UNBOUNDED ) ]
            moved_in.add( new )
    findings = []
    py_sources = {}
    swept      = []
    tally      = { "files": 0, "docstrings": 0, "findings": 0, "waivers": 0, "unparsed": 0, "undecodable": 0 }
    waived     = []
    refusals   = []
    warnings   = [ f"[doc-lint] WARNING: {shown( p )} is staged as a gitlink (a submodule entry), which holds a commit and no text, so it was NOT checked" for p in gitlinks ]
    binary     = set( staged_binary( root ) )
    incoming   = incoming_commits( root )[ 0 ]
    changed    = staged_entries( root )[ 3 ] & set.intersection( *[ staged_entries( root, sha )[ 3 ] for sha in incoming ] ) if incoming else staged_entries( root )[ 3 ]
    created    = ( changed & set( paths ) ) | moved_in
    for p in staged_entries( root )[ 4 ]:
        named_file = p.endswith( ( ".py", ".md" ) ) or tsdoc_lint.in_scope( p )
        if not named_file and not ( p.startswith( "src/" ) and ( is_swept( f"{p}/_.py" ) or ( in_scope( f"{p}/_.ts" ) and tsdoc_lint.in_scope( f"{p}/_.ts" ) ) ) ): continue
        line = f"[doc-lint] WARNING: {shown( p )} is staged as a symbolic link, its content is a target path and not a page, so it was NOT checked"
        executable = not named_file or ( p.endswith( ".py" ) and is_swept( p ) ) or tsdoc_lint.in_scope( p )
        warnings.append( Unchecked( line ) if executable and ( p in changed or p in moved_in ) and not is_warn_only( p ) else line )
    warnings  += [ ( Unchecked if p in created and not is_warn_only( p ) else str )( f"[doc-lint] WARNING: {shown( p )} could NOT be checked because git treats it as binary, so the lines this commit touches in it are not known" ) for p in paths if p in binary and p.endswith( ( ".py", ".md" ) ) ]
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
                decode_out.append( f"[doc-lint] REFUSED {shown( path )}: not UTF-8: {err}; fix: {FIX_HOME[ 'not-utf-8' ]}; this cannot be waived" )
            else:
                warnings.append( ( Unchecked if path in created and not is_warn_only( path ) else str )( f"[doc-lint] WARNING: {shown( path )} is not UTF-8, it was NOT checked" ) )
            continue
        if path.endswith( ".py" ):
            if ranges.get( path ) and BARE_RETURN.search( source ): ranges[ path ] = [ ( 1, len( split_lines( source ) ) ) ]
            py_sources[ path ] = source
            doc_findings = docstring_lint.lint_source( path, source, root )
            findings += doc_findings + comment_lint.lint_source( path, source, root )
            if is_swept( path ): swept.append( ( path, source, doc_findings ) )
            else: waived += [ f for f in doc_findings if waiver_state( f, line_text( split_lines( source ), f.line ) ) == "honoured" ]
        elif path.endswith( ".md" ):
            findings += md_lint.lint_source( path, source, root )
    py, md   = [ p for p in paths if p.endswith( ".py" ) and p not in skipped ], [ p for p in paths if p.endswith( ".md" ) and p not in skipped ]
    ruff_findings, ruff_warnings = run_ruff( root, py, sources=py_sources )
    md_findings, md_warnings     = run_markdownlint( root, md )
    decode_out += [ f"[doc-lint] REFUSED {shown( p )}: the file name is not UTF-8 or holds a line break, so markdownlint-cli2 cannot be given it and its markdown structure was NOT checked; fix: rename the file; this cannot be waived" for p in markdownlint_unnamed( root, md ) ]
    findings += ruff_findings + md_findings
    refusals = [ f for f in findings if in_blocking_package( f.path, BLOCKING_PACKAGES ) and is_mechanical( f ) ]
    lines_out = [ refusal_line( f ) for f in refusals ] + decode_out
    staged_counted_paths, _renames, table_staged = staged_counted( root )
    staged_ts_paths, _ts_renames, ts_table_staged = staged_ts_counted( root )
    staged_exports_paths, _ex_renames, exports_table_staged = staged_exports_counted( root )
    compared, differing = counts.differing_rule_files( root )
    tally[ "rules" ]    = { "compared": compared, "differing": len( differing ) }
    judged   = bool( swept ) or bool( staged_counted_paths ) or table_staged or bool( staged_ts_paths ) or ts_table_staged or bool( staged_exports_paths ) or exports_table_staged
    diverged = rule_divergence( compared, differing, judged )
    if diverged:
        lines_out.append( diverged )
        swept = []
    for path, source, doc_findings in swept:
        lines = split_lines( source )
        tally[ "files" ] += 1
        if doc_findings and doc_findings[ 0 ].rule == "parse-error":
            tally[ "unparsed" ] += 1
            refusals.append( doc_findings[ 0 ] )
            lines_out.append( f"[doc-lint] REFUSED {shown( path )}:{doc_findings[ 0 ].line}: parse-error: {doc_findings[ 0 ].message}; fix: {FIX_HOME[ 'parse-error' ]}; this cannot be waived" )
            continue
        tally[ "docstrings" ] += len( docstring_lint.extract_docstrings( source ) )
        tally[ "findings" ]   += len( doc_findings )
        for f in doc_findings:
            state = waiver_state( f, line_text( lines, f.line ) )
            if state == "honoured":
                tally[ "waivers" ] += 1
                waived.append( f )
            elif id( f ) not in { id( r ) for r in refusals }:
                refusals.append( f )
                lines_out.append( swept_refusal_line( f, line_text( lines, f.line ), state ) )
    if diverged:
        tally[ "counted" ]    = { "files": 0, "at_or_below": 0, "over": 0, "waivers": 0, "table": "diverged" }
        tally[ "ts_counted" ] = dict( tally[ "counted" ] )
        tally[ "exports_counted" ] = dict( tally[ "counted" ] )
    else:
        counted_refusals, counted_warnings, tally[ "counted" ] = counted_check( root, ranges )
        lines_out += counted_refusals
        warnings  += counted_warnings
        ts_refusals, ts_warnings, tally[ "ts_counted" ] = ts_counted_check( root, ranges )
        lines_out += ts_refusals
        warnings  += ts_warnings
        exports_refusals, exports_warnings, tally[ "exports_counted" ] = exports_counted_check( root, ranges )
        lines_out += exports_refusals
        warnings  += exports_warnings
    dropped  = { id( f ) for f in refusals + waived }
    kept     = [ f for f in filter_findings( findings, ranges ) if id( f ) not in dropped and not is_record_exempt( f ) ]
    return kept, ruff_warnings + md_warnings + warnings, lines_out, tally


def main( argv=None, err=None ):
    """
    Run the gate.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]
        - err is a writable text stream, or None for sys.stderr

    Ensures:
        - returns REFUSAL_EXIT when collect reports a refusal, with or without --blocking
        - with --blocking, returns REFUSAL_EXIT when a finding on a staged line is neither warn-only nor predating, and prints it as a refused line
        - a finding in a file is_warn_only names is printed with WARN_ONLY_MARK and never refuses the commit
        - a page-level finding that predating returns is printed with PREDATES_MARK and never refuses the commit
        - while a merge or a cherry-pick waits to be concluded, a finding merged_in returns is printed with MERGED_MARK and never refuses the commit
        - a Python file with a bare carriage return is let off nothing as merged in, since git's line numbers for it are not the parser's; one line says so
        - with --blocking, returns REFUSAL_EXIT when a warning is an Unchecked, and prints that warning as a refused line
        - a file name is printed through shown, so no name breaks a line or a strict output stream
        - otherwise returns 0; the gate itself never returns 1
        - prints the swept-scope denominator on every run that does not crash
        - an internal error is printed as a loud line and the exit is 0, with or without --blocking
        - every warning from a missing tool is printed

    Raises:
        - nothing
    """
    err    = err if err is not None else sys.stderr
    parser = argparse.ArgumentParser( description="Documentation-standard pre-commit gate (warn mode without --blocking)." )
    parser.add_argument( "--blocking", action="store_true", help=f"exit {REFUSAL_EXIT} when a finding on a staged line is neither warn-only nor older than the commit" )
    parser.add_argument( "--repo-root", default=".", help="directory inside the working tree" )
    args = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    def say( line ): err.write( SURROGATE.sub( lambda m: shown( m.group() ), line ) + "\n" )
    try:
        root                                = git_toplevel( args.repo_root )
        findings, warnings, refusals, tally = collect( root )
        earlier                             = predating( root, findings, staged_changes( root )[ 1 ] )
        incoming, merge_warnings            = incoming_commits( root )
        merged                              = merged_in( root, findings, incoming )
        bare                                = sorted( { f.path for f in merged if f.path.endswith( ".py" ) and BARE_RETURN.search( staged_source( root, f.path ) ) } )
    except Exception as exc:
        say( f"[doc-lint] GATE CRASHED, commit allowed: {type( exc ).__name__}: {exc}" )
        say( traceback.format_exc().rstrip( "\n" ) )
        return 0
    held      = [ w for w in warnings if args.blocking and isinstance( w, Unchecked ) ]
    for warning in warnings + merge_warnings: say( warning.replace( "WARNING:", "REFUSED:", 1 ) if warning in held else warning )
    for path in bare: say( f"[doc-lint] {shown( path )} holds a bare carriage return, so git does not number its lines as the parser does: no finding in it is let off as merged in" )
    warn_only = [ f for f in findings if is_warn_only( f.path ) ]
    merged    = [ f for f in merged if f not in warn_only and f.path not in bare ]
    earlier   = [ f for f in earlier if f not in warn_only and f not in merged ]
    blocked   = [ f for f in findings if args.blocking and f not in warn_only and f not in merged and f not in earlier ]
    for f in findings:
        mark = WARN_ONLY_MARK if f in warn_only else MERGED_MARK if f in merged else PREDATES_MARK if f in earlier else ""
        say( f"[doc-lint] {'REFUSED ' if f in blocked else ''}{shown( f.path )}:{f.line}: {f.rule}: {f.message}{mark}" )
    for line in refusals: say( line )
    say( f"[doc-lint] swept scope: {tally[ 'files' ]} files checked, {tally[ 'docstrings' ]} docstrings checked, {tally[ 'findings' ]} findings, {tally[ 'waivers' ]} waivers honoured, {tally[ 'unparsed' ]} unparsed, {tally[ 'undecodable' ]} undecodable" )
    say( f"[doc-lint] rule files compared: {tally[ 'rules' ][ 'compared' ]}, differing: {tally[ 'rules' ][ 'differing' ]}" )
    c = tally[ "counted" ]
    say( f"[doc-lint] counted scope: {c[ 'files' ]} files checked, {c[ 'at_or_below' ]} at or below their count, {c[ 'over' ]} over, {c[ 'waivers' ]} waivers honoured, table {c[ 'table' ]}" )
    t = tally[ "ts_counted" ]
    say( f"[doc-lint] {TS_NAME} counted scope: {t[ 'files' ]} files checked, {t[ 'at_or_below' ]} at or below their count, {t[ 'over' ]} over, {t[ 'waivers' ]} waivers honoured, table {t[ 'table' ]}" )
    e = tally[ "exports_counted" ]
    say( f"[doc-lint] {EXPORTS_NAME} counted scope: {e[ 'files' ]} files checked, {e[ 'at_or_below' ]} at or below their count, {e[ 'over' ]} over, {e[ 'waivers' ]} waivers honoured, table {e[ 'table' ]}" )
    if args.blocking and warn_only: say( f"[doc-lint] {len( warn_only )} findings in {' or '.join( WARN_ONLY_PATHS + WARN_ONLY_PREFIXES )}{WARN_ONLY_MARK}" )
    if args.blocking and merged: say( f"[doc-lint] {len( merged )} findings came in with the merged or picked commit{WARN_ONLY_MARK}" )
    if args.blocking and earlier: say( f"[doc-lint] {len( earlier )} page-level findings predate this commit{WARN_ONLY_MARK}" )
    if refusals: say( f"[doc-lint] {len( refusals )} refusals, commit REFUSED" )
    if blocked: say( f"[doc-lint] {len( blocked )} findings on staged lines, commit REFUSED: fix each REFUSED line above, stage the fix and commit again" )
    if held: say( f"[doc-lint] {len( held )} checks could not be made, commit REFUSED: each is a REFUSED line above that says what was not checked" )
    if refusals or blocked or held: return REFUSAL_EXIT
    remaining, mode = ( 0, "blocking" ) if args.blocking else ( len( findings ), "warn mode, commit allowed" )
    say( f"[doc-lint] {remaining} findings on staged lines ({mode})" )
    return 0

if __name__ == "__main__":
    sys.exit( main() )
