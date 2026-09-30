"""
Doc-comment linter for Dart: the same text rules as docstring_lint, over `///` blocks.

A small lexer finds the doc comments, because the analyzer has no hook for custom prose rules
and a regex would read `///` inside a string literal as a comment. Stdlib only, so it can be
vendored into lupin-mobile's tool/ directory with the rule modules.
"""

import sys

from .cli import run_linter
from .rule_lists import DART_BLOCK_MAX_LINES
from .text_rules import Finding, lint_text

QUOTES = "'\""


def _skip_interpolation( s, i ):
    """
    Return the index just past the brace that closes a string interpolation.

    Requires:
        - i is the index just after the opening ${

    Ensures:
        - nested braces and nested string literals are skipped
        - an unterminated interpolation returns len( s )

    Raises:
        - nothing
    """
    depth = 1
    while i < len( s ):
        c = s[ i ]
        if c in QUOTES:
            i = _skip_string( s, i, False )
            continue
        if c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0: return i + 1
        i += 1
    return i


def _skip_string( s, i, raw ):
    """
    Return the index just past a string literal.

    Requires:
        - s[ i ] is the opening quote
        - raw is True for an r'...' literal, which has no escapes or interpolation

    Ensures:
        - handles single, double and triple quotes, escapes and ${...} interpolation
        - an unterminated single-line string ends at the newline
        - an unterminated triple-quoted string returns len( s )

    Raises:
        - nothing
    """
    q = s[ i ]
    triple = s.startswith( q * 3, i )
    i += 3 if triple else 1
    while i < len( s ):
        c = s[ i ]
        if c == "\\" and not raw:
            i += 2
            continue
        if not raw and c == "$" and s.startswith( "{", i + 1 ):
            i = _skip_interpolation( s, i + 2 )
            continue
        if triple and s.startswith( q * 3, i ): return i + 3
        if not triple and c == q: return i + 1
        if not triple and c == "\n": return i
        i += 1
    return i


def doc_comment_lines( source ):
    """
    Return the doc-comment lines of a Dart source, skipping string literals.

    Requires:
        - source is Dart text

    Ensures:
        - returns [ ( line, text ) ] with line 1-based, for each `///` line and each line of a
          `/** ... */` block
        - text has the comment marker and one following space removed
        - `////` and plain `//` or `/* */` comments are not doc comments and are skipped

    Raises:
        - nothing
    """
    found = []
    i = 0
    n = len( source )
    while i < n:
        c = source[ i ]
        raw = c == "r" and i + 1 < n and source[ i + 1 ] in QUOTES and ( i == 0 or not ( source[ i - 1 ].isalnum() or source[ i - 1 ] == "_" ) )
        if raw:
            i = _skip_string( source, i + 1, True )
        elif c in QUOTES:
            i = _skip_string( source, i, False )
        elif source.startswith( "///", i ) and not source.startswith( "////", i ):
            end = source.find( "\n", i )
            end = n if end == -1 else end
            text = source[ i + 3 : end ]
            found.append( ( source.count( "\n", 0, i ) + 1, text[ 1: ] if text.startswith( " " ) else text ) )
            i = end
        elif source.startswith( "//", i ):
            end = source.find( "\n", i )
            i = n if end == -1 else end
        elif source.startswith( "/*", i ):
            end = source.find( "*/", i + 2 )
            end = n if end == -1 else end + 2
            if source.startswith( "/**", i ) and not source.startswith( "/**/", i ):
                first = source.count( "\n", 0, i ) + 1
                body = source[ i + 3 : max( i + 3, end - 2 ) ]
                for k, part in enumerate( body.split( "\n" ) ):
                    part = part.strip()
                    if part.startswith( "*" ): part = part[ 1: ].strip()
                    found.append( ( first + k, part ) )
            i = end
        else:
            i += 1
    return found


def doc_blocks( source ):
    """
    Group doc-comment lines into blocks of consecutive lines.

    Requires:
        - source is Dart text

    Ensures:
        - returns [ ( first_line, text ) ]; a block ends where the line numbers stop being consecutive
        - a block comment body is one block, since its lines are consecutive

    Raises:
        - nothing
    """
    blocks = []
    current = []
    for line, text in doc_comment_lines( source ):
        if current and line != current[ -1 ][ 0 ] + 1:
            blocks.append( current )
            current = []
        current.append( ( line, text ) )
    if current: blocks.append( current )
    return [ ( b[ 0 ][ 0 ], "\n".join( t for _, t in b ) ) for b in blocks ]


def lint_source( path, source, root=None ):
    """
    Lint every doc block in one Dart file.

    Requires:
        - path is the repo-relative path used in findings
        - root is the repo working tree, or None to skip checks that need it

    Ensures:
        - returns a list of Finding, sorted by line
        - a block of more than DART_BLOCK_MAX_LINES lines yields one dartdoc-length finding

    Raises:
        - nothing
    """
    findings = []
    for first_line, text in doc_blocks( source ):
        findings += lint_text( text, path, first_line )
        lines = text.count( "\n" ) + 1
        if lines > DART_BLOCK_MAX_LINES:
            findings.append( Finding( path, first_line, "dartdoc-length", f"doc block of {lines} lines, limit {DART_BLOCK_MAX_LINES}" ) )
    return sorted( findings, key=lambda f: ( f.line, f.rule, f.message ) )


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - returns the exit code from run_linter

    Raises:
        - nothing beyond run_linter's
    """
    return run_linter( "Lint Dart doc comments against the eight rules.", ( ".dart", ), lint_source, sys.argv[ 1: ] if argv is None else argv, out )


if __name__ == "__main__":
    sys.exit( main() )
