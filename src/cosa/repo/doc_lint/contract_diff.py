"""
Contract diff: counts the Requires, Ensures and Raises items of every Python function before
and after a change, and lists each item that was dropped.

A docstring rewrite may reword a clause, but it may not lose one unnoticed. This tool makes
every loss visible so a merge can declare it. Stdlib only.
"""

import argparse
import ast
import inspect
import json
import sys

from .docs_only_diff import _git, _show

SECTIONS = ( "Requires", "Ensures", "Raises" )


def parse_contract( docstring ):
    """
    Read the Requires, Ensures and Raises items out of one docstring.

    Requires:
        - docstring is a str, or None for a function without one

    Ensures:
        - returns { section: [ item text, ... ] } with all three section keys present
        - an item is a line starting with "- "; its indented continuation lines join it with single spaces
        - a section ends at a blank line, at the next section header, or at the first line back at header indent

    Raises:
        - nothing
    """
    contract = { name : [] for name in SECTIONS }
    if not docstring: return contract
    current, indent = None, 0
    for raw in inspect.cleandoc( docstring ).split( "\n" ):
        line  = raw.strip()
        depth = len( raw ) - len( raw.lstrip() )
        if line.rstrip( ":" ) in SECTIONS and line.endswith( ":" ):
            current, indent = line[ :-1 ], depth
        elif not line or ( current is not None and depth <= indent ):
            current = None
        elif current is not None and line.startswith( "- " ):
            contract[ current ].append( line[ 2: ].strip() )
        elif current is not None and contract[ current ]:
            contract[ current ][ -1 ] += " " + line
    return contract


def function_contracts( source ):
    """
    Map each function's qualified name to its parsed contract.

    Requires:
        - source is Python text that parses

    Ensures:
        - returns { "Class.method": contract } for every def, nested ones included
        - a function with no docstring maps to an empty contract

    Raises:
        - SyntaxError when source does not parse
    """
    found = {}

    def walk( node, prefix ):
        for child in ast.iter_child_nodes( node ):
            if isinstance( child, ( ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef ) ):
                name = prefix + child.name
                if not isinstance( child, ast.ClassDef ): found[ name ] = parse_contract( ast.get_docstring( child, clean=False ) )
                walk( child, name + "." )
            else:
                walk( child, prefix )

    walk( ast.parse( source ), "" )
    return found


def diff_contracts( old_source, new_source ):
    """
    Compare the contracts of two versions of one file.

    Requires:
        - both sources are str or None (None means the file is absent on that side)

    Ensures:
        - returns one row per function that existed before: { function, section, before, after, dropped }
          for each section that had items before or has items after
        - dropped lists the old items whose text is absent after, in old order; a removed function drops them all
        - a function that only exists after has no row, since nothing was lost

    Raises:
        - SyntaxError when a present side does not parse
    """
    old = function_contracts( old_source ) if old_source is not None else {}
    new = function_contracts( new_source ) if new_source is not None else {}
    rows = []
    for name in sorted( old ):
        for section in SECTIONS:
            before, after = old[ name ][ section ], new.get( name, { section : [] } )[ section ]
            if not before and not after: continue
            rows.append( {
                "function" : name,
                "section"  : section,
                "before"   : len( before ),
                "after"    : len( after ),
                "dropped"  : [ item for item in before if item not in after ]
            } )
    return rows


def check_diff( root, base, head=None ):
    """
    Diff the contracts of every changed .py file between base and head.

    Requires:
        - root is a git working tree; base is a revision
        - head is a revision, or None for the working tree

    Ensures:
        - returns { path: rows } sorted by path, for each changed .py file that has at least one row

    Raises:
        - RuntimeError from git when the diff fails
        - SyntaxError when a changed file does not parse
    """
    args  = [ "diff", "--name-only", "--no-renames", base ] + ( [ head ] if head else [] )
    names = sorted( p for p in _git( root, *args ).split( "\n" ) if p.endswith( ".py" ) )
    found = {}
    for path in names:
        rows = diff_contracts( _show( root, base, path ), _show( root, head, path ) )
        if rows: found[ path ] = rows
    return found


def render_table( results ):
    """
    Render the results as a markdown table, one row per function and section.

    Requires:
        - results is the dict check_diff returns

    Ensures:
        - returns a str with a header row and one line per row; a dropped cell lists each item
        - a row with nothing dropped shows "-" in the dropped cell

    Raises:
        - nothing
    """
    lines = [ "| file | function | section | before | after | dropped |", "| --- | --- | --- | --- | --- | --- |" ]
    for path, rows in results.items():
        for r in rows:
            dropped = "; ".join( r[ "dropped" ] ) if r[ "dropped" ] else "-"
            lines.append( f"| {path} | {r[ 'function' ]} | {r[ 'section' ]} | {r[ 'before' ]} | {r[ 'after' ]} | {dropped} |" )
    return "\n".join( lines ) + "\n"


def main( argv=None, out=None ):
    """
    Command-line entry: print the contract table, or JSON with --json.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - returns 1 when --strict is given and any item was dropped, otherwise 0
        - the report is printed either way

    Raises:
        - RuntimeError from git when the diff fails
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="List the contract clauses a change dropped" )
    parser.add_argument( "--base", required=True, help="revision to compare from" )
    parser.add_argument( "--head", help="revision to compare to; default is the working tree" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    parser.add_argument( "--json", action="store_true", help="print rows as JSON" )
    parser.add_argument( "--strict", action="store_true", help="exit 1 when any item was dropped" )
    args    = parser.parse_args( argv )
    results = check_diff( args.repo_root, args.base, args.head )
    if args.json:
        json.dump( results, out, indent=2 )
        out.write( "\n" )
    else:
        out.write( render_table( results ) )
    dropped = sum( len( r[ "dropped" ] ) for rows in results.values() for r in rows )
    return 1 if args.strict and dropped else 0


if __name__ == "__main__": sys.exit( main() )  # pragma: no cover -- script entry, main() is tested
