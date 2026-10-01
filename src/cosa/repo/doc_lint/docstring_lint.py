"""
Docstring linter for Python: the rules that ruff cannot express (plan 1, section 4.1).

Finds every module, class and function docstring with ast and runs the shared text rules over
it, plus the length cap. The layout rules (blank line after the summary, D213 placement) belong
to ruff and are not repeated here.
"""

import ast
import sys

from .cli import run_linter
from .links import design_path_findings
from .rule_lists import DOCSTRING_MAX_LINES
from .text_rules import Finding, lint_text

DOC_NODES = ( ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef )


def is_tool_registered( node ):
    """
    Say whether a function is registered as an MCP tool.

    Requires:
        - node is an ast node

    Ensures:
        - True for a function with a decorator named tool, bare or called, whether written
          tool, mcp.tool or server.tool( ... ); a wrapper such as _offloaded_tool does not count
        - False for everything else, including classes and modules
        - found by what the function is registered with, never by a list of names

    Raises:
        - nothing
    """
    if not isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ): return False
    for deco in node.decorator_list:
        target = deco.func if isinstance( deco, ast.Call ) else deco
        if isinstance( target, ast.Attribute ) and target.attr == "tool": return True
        if isinstance( target, ast.Name ) and target.id == "tool": return True
    return False


def _documented_nodes( source ):
    """
    Walk a Python source and yield each documented node with its docstring.

    Requires:
        - source is valid Python text

    Ensures:
        - yields ( node, first_line, text ) in tree-walk order, for nodes that have a docstring

    Raises:
        - SyntaxError when source does not parse
    """
    for node in ast.walk( ast.parse( source ) ):
        if not isinstance( node, DOC_NODES ): continue
        body = node.body
        if not ( body and isinstance( body[ 0 ], ast.Expr ) and isinstance( body[ 0 ].value, ast.Constant ) and isinstance( body[ 0 ].value.value, str ) ): continue
        yield node, body[ 0 ].value.lineno, body[ 0 ].value.value


def extract_docstrings( source ):
    """
    Return every docstring in a Python source with the file line of its first line.

    Requires:
        - source is valid Python text

    Ensures:
        - returns [ ( kind, name, first_line, text ) ] in tree-walk order
        - text is the raw docstring, so line i of the split text sits on file line first_line + i
        - a node with no docstring adds nothing

    Raises:
        - SyntaxError when source does not parse
    """
    return [
        ( type( node ).__name__, "<module>" if isinstance( node, ast.Module ) else node.name, first_line, text )
        for node, first_line, text in _documented_nodes( source )
    ]


def lint_source( path, source, root=None, stats=None ):
    """
    Lint every docstring in one Python file.

    Requires:
        - path is the repo-relative path used in findings
        - root is the repo working tree, or None to skip checks that need it
        - stats is a dict or None

    Ensures:
        - returns a list of Finding, sorted by line
        - a file that does not parse yields one parse-error finding
        - with root given, a Design: path that does not exist yields a dead-design finding
        - a registered tool's docstring is exempt from the agent-imperative rule only; every other rule applies
        - with stats given, stats["exempted"] is raised by one for each docstring so exempted
        - a docstring of more than DOCSTRING_MAX_LINES lines yields one docstring-length finding

    Raises:
        - nothing
    """
    try:
        docstrings = list( _documented_nodes( source ) )
    except SyntaxError as err:
        return [ Finding( path, err.lineno or 1, "parse-error", f"does not parse: {err.msg}" ) ]
    findings = []
    for node, first_line, text in docstrings:
        kind   = type( node ).__name__
        name   = "<module>" if isinstance( node, ast.Module ) else node.name
        exempt = is_tool_registered( node )
        if exempt and stats is not None: stats[ "exempted" ] = stats.get( "exempted", 0 ) + 1
        findings += lint_text( text, path, first_line, agent_rule=not exempt )
        if root is not None: findings += design_path_findings( text, path, first_line, root )
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
    stats = { "exempted": 0 }
    return run_linter(
        "Lint Python docstrings against the eight rules.", ( ".py", ),
        lambda path, source, root: lint_source( path, source, root, stats ),
        sys.argv[ 1: ] if argv is None else argv, out,
        footer=lambda: f"{stats[ 'exempted' ]} tool docstrings exempted from the agent-imperative rule\n"
    )


if __name__ == "__main__":
    sys.exit( main() )
