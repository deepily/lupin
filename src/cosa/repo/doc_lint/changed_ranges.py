"""
Changed line ranges from a git diff, used to filter linter findings to touched lines.

Ruff has no changed-lines mode, so one touched file would otherwise drag in every
legacy finding in it. Each linter runs on the changed files and its findings are then kept only
when they sit on a line the diff touched.
"""

import re
import subprocess

HUNK_HEADER   = re.compile( r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@" )
FILE_PREFIX   = "+++ "
# The one-letter escapes git writes inside a quoted file name, each with the byte it stands for.
QUOTE_ESCAPES = { "a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92 }

# A whole-page finding sits at line 1 whatever was edited, so it is kept whenever the file was touched.
PAGE_LEVEL_RULES = frozenset( { "reference-length", "capability-length", "runbook-template" } )


def unquote_path( raw ):
    """
    Turn a file name as a diff header writes it into the name itself.

    Git puts a name in double quotes when it holds a quote, a backslash, a control character or,
    by default, a byte above ASCII. It writes a tab after a name that holds a space.

    Requires:
        - raw is the text after the +++ and the space of a diff header line, as git wrote it

    Ensures:
        - a name in double quotes is returned without them, with each escape turned back into its byte
        - an octal escape is one byte, and the bytes are read together as UTF-8
        - one trailing tab is dropped first
        - any other text is returned as it is

    Raises:
        - nothing
    """
    name = raw[ : -1 ] if raw.endswith( "\t" ) else raw
    if len( name ) < 2 or not ( name.startswith( '"' ) and name.endswith( '"' ) ): return name
    out, body, i = bytearray(), name[ 1 : -1 ], 0
    while i < len( body ):
        if body[ i ] != "\\":
            out += body[ i ].encode( "utf-8" )
            i   += 1
        elif body[ i + 1 ] in QUOTE_ESCAPES:
            out.append( QUOTE_ESCAPES[ body[ i + 1 ] ] )
            i += 2
        else:
            out.append( int( body[ i + 1 : i + 4 ], 8 ) )
            i += 4
    return out.decode( "utf-8", "replace" )


def parse_diff_ranges( diff_text ):
    """
    Turn a zero-context unified diff into touched line ranges per file.

    Requires:
        - diff_text is the output of a zero-context git diff

    Ensures:
        - returns { path: [ ( first, last ), ... ] } with 1-based inclusive new-file lines
        - a pure deletion hunk adds no range
        - a deleted file, whose header reads +++ /dev/null, adds no entry
        - a file name git wrote in quotes is keyed by the name itself, as unquote_path reads it

    Raises:
        - nothing
    """
    ranges = {}
    current = None
    for raw in diff_text.split( "\n" ):
        if raw.startswith( FILE_PREFIX ):
            name    = unquote_path( raw[ len( FILE_PREFIX ) : ] )
            current = name[ 2 : ] if name.startswith( "b/" ) else None
            if current is not None: ranges.setdefault( current, [] )
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
        - a byte that is not UTF-8 is replaced, since only the hunk headers are read

    Raises:
        - RuntimeError naming the git error when the diff command fails
    """
    cmd = [ "git", "-C", str( repo_root ), "diff", "-U0", "--no-color", "--no-ext-diff" ]
    cmd += [ "--cached" ] if cached else [ base ]
    cmd += [ "--", ":/" ]
    res = subprocess.run( cmd, capture_output=True, text=True, encoding="utf-8", errors="replace" )
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
