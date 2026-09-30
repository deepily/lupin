"""
Changed line ranges from a git diff, used to filter linter findings to touched lines.

Ruff has no changed-lines mode, so one touched file would otherwise drag in every
legacy finding in it. Each linter runs on the changed files and its findings are then kept only
when they sit on a line the diff touched.
"""

import re
import subprocess

HUNK_HEADER = re.compile( r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@" )
FILE_HEADER = re.compile( r"^\+\+\+ b/(.+)$" )

# A whole-page finding sits at line 1 whatever was edited, so it is kept whenever the file was touched.
PAGE_LEVEL_RULES = frozenset( { "reference-length", "capability-length", "runbook-template" } )


def parse_diff_ranges( diff_text ):
    """
    Turn a zero-context unified diff into touched line ranges per file.

    Requires:
        - diff_text is the output of a zero-context git diff

    Ensures:
        - returns { path: [ ( first, last ), ... ] } with 1-based inclusive new-file lines
        - a pure deletion hunk adds no range
        - a deleted file, whose header reads +++ /dev/null, adds no entry

    Raises:
        - nothing
    """
    ranges = {}
    current = None
    for raw in diff_text.split( "\n" ):
        m = FILE_HEADER.match( raw )
        if m:
            current = m.group( 1 )
            ranges.setdefault( current, [] )
            continue
        if raw.startswith( "+++ " ):
            current = None
            continue
        m = HUNK_HEADER.match( raw )
        if m and current is not None:
            start = int( m.group( 1 ) )
            count = 1 if m.group( 2 ) is None else int( m.group( 2 ) )
            if count > 0: ranges[ current ].append( ( start, start + count - 1 ) )
    return ranges


def changed_line_ranges( repo_root, base, cached=False ):
    """
    Ask git which lines changed against base.

    Requires:
        - repo_root is a git working tree
        - base is a revision git can resolve; with cached=True it is ignored and the staged
          changes are read instead

    Ensures:
        - returns the dict from parse_diff_ranges
        - the diff is anchored at repo_root, so the caller's directory does not matter

    Raises:
        - RuntimeError naming the git error when the diff command fails
    """
    cmd = [ "git", "-C", str( repo_root ), "diff", "-U0", "--no-color", "--no-ext-diff" ]
    cmd += [ "--cached" ] if cached else [ base ]
    cmd += [ "--", ":/" ]
    res = subprocess.run( cmd, capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git diff failed: {res.stderr.strip()}" )
    return parse_diff_ranges( res.stdout )


def in_ranges( line, ranges ):
    """
    Say whether a line falls in any of the ranges.

    Requires:
        - ranges is a list of ( first, last ) pairs

    Ensures:
        - True when first <= line <= last for some pair

    Raises:
        - nothing
    """
    return any( first <= line <= last for first, last in ranges )


def filter_findings( findings, ranges_by_path ):
    """
    Keep the findings that sit on a touched line.

    Requires:
        - findings carry .path and .line
        - ranges_by_path is the dict from changed_line_ranges

    Ensures:
        - a finding on a file with no entry is dropped
        - a page-level finding (PAGE_LEVEL_RULES) is kept when the file has any touched line
        - order is preserved

    Raises:
        - nothing
    """
    return [ f for f in findings if in_ranges( f.line, ranges_by_path.get( f.path, [] ) ) or ( f.rule in PAGE_LEVEL_RULES and ranges_by_path.get( f.path ) ) ]
