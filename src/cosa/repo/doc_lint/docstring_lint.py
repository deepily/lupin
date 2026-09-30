"""
Docstring linter for Python: the rules that ruff cannot express (plan 1, section 4.1).

Finds every module, class and function docstring with ast and runs the shared text rules over
it, plus the length cap. The layout rules (blank line after the summary, D213 placement) belong
to ruff and are not repeated here.
"""

import ast
import sys

from .cli import run_linter
from .rule_lists import DOCSTRING_MAX_LINES
from .text_rules import Finding, lint_text

DOC_NODES = ( ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef )


def extract_docstrings( source ):
    """
    Return every docstring in a Python source with the file line of its first line.

    Requires:
        - source is valid Python text

    Ensures:
        - returns [ ( kind, name, first_line, text ) ] in tree-walk order
        - text is the raw docstring, so text.split( "\\n" )[ i ] sits on file line first_line + i
        - a node with no docstring adds nothing

    Raises:
        - SyntaxError when source does not parse
    """
    found = []
    for node in ast.walk( ast.parse( source ) ):
        if not isinstance( node, DOC_NODES ): continue
        body = node.body
        if not ( body and isinstance( body[ 0 ], ast.Expr ) and isinstance( body[ 0 ].value, ast.Constant ) and isinstance( body[ 0 ].value.value, str ) ): continue
        name = "<module>" if isinstance( node, ast.Module ) else node.name
        found.append( ( type( node ).__name__, name, body[ 0 ].value.lineno, body[ 0 ].value.value ) )
    return found


def lint_source( path, source, root=None ):
    """
    Lint every docstring in one Python file.

    Requires:
        - path is the repo-relative path used in findings
        - root is the repo working tree, or None to skip checks that need it

    Ensures:
        - returns a list of Finding, sorted by line
        - a file that does not parse yields one parse-error finding
        - a docstring of more than DOCSTRING_MAX_LINES lines yields one docstring-length finding

    Raises:
        - nothing
    """
    try:
        docstrings = extract_docstrings( source )
    except SyntaxError as err:
        return [ Finding( path, err.lineno or 1, "parse-error", f"does not parse: {err.msg}" ) ]
    findings = []
    for kind, name, first_line, text in docstrings:
        findings += lint_text( text, path, first_line )
        lines = text.strip( "\n" ).count( "\n" ) + 1
        if lines > DOCSTRING_MAX_LINES:
            findings.append( Finding( path, first_line, "docstring-length", f"{kind} {name}: {lines} lines, limit {DOCSTRING_MAX_LINES}" ) )
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
    return run_linter( "Lint Python docstrings against the eight rules.", ( ".py", ), lint_source, sys.argv[ 1: ] if argv is None else argv, out )


if __name__ == "__main__":
    sys.exit( main() )
