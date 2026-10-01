"""
Docs-only diff check: proves a documentation rewrite left the code unchanged.

Python files pass when their ASTs are identical once docstrings are removed (comments never
reach the AST). Dart files pass when every non-comment token is identical. A failure names the
first differing node or token. Stdlib only.
"""

import argparse
import ast
import re
import subprocess
import sys

from .dartdoc_lint import QUOTES, _skip_string

IDENT_REGEX = re.compile( r"[A-Za-z0-9_$]+" )
SUFFIXES    = ( ".py", ".dart" )


class _DocstringStripper( ast.NodeTransformer ):
    """Removes the docstring from each module, class and function body."""

    def _strip( self, node ):
        self.generic_visit( node )
        body = node.body
        if body and isinstance( body[ 0 ], ast.Expr ) and isinstance( body[ 0 ].value, ast.Constant ) and isinstance( body[ 0 ].value.value, str ):
            node.body = body[ 1 : ] or [ ast.Pass() ]
        return node

    visit_Module           = _strip
    visit_ClassDef         = _strip
    visit_FunctionDef      = _strip
    visit_AsyncFunctionDef = _strip


def _describe( node ):
    """
    Name a node for a failure message.

    Requires:
        - node is an ast node

    Ensures:
        - returns a short string with the class, the name when it has one, and the line when it has one

    Raises:
        - nothing
    """
    label = type( node ).__name__
    for field in ( "name", "id", "attr" ):
        if hasattr( node, field ):
            label += f"({getattr( node, field )})"
            break
    if hasattr( node, "lineno" ): label += f" line {node.lineno}"
    return label


def first_difference( old, new, path="Module" ):
    """
    Find the first place two ASTs differ.

    Requires:
        - old and new are ast nodes, lists of them, or plain field values

    Ensures:
        - returns None when they are identical, ignoring positions
        - otherwise returns a string naming the path to the first differing node and both sides

    Raises:
        - nothing
    """
    if isinstance( old, ast.AST ) and isinstance( new, ast.AST ):
        if type( old ) is not type( new ): return f"{path}: {_describe( old )} became {_describe( new )}"
        for field in old._fields:
            found = first_difference( getattr( old, field, None ), getattr( new, field, None ), f"{path}.{field}" )
            if found is not None: return found
        return None
    if isinstance( old, list ) and isinstance( new, list ):
        for i, ( a, b ) in enumerate( zip( old, new ) ):
            found = first_difference( a, b, f"{path}[{i}]" )
            if found is not None: return found
        if len( old ) != len( new ):
            longer = old if len( old ) > len( new ) else new
            side   = "removed" if longer is old else "added"
            return f"{path}: {side} {_describe( longer[ min( len( old ), len( new ) ) ] )}"
        return None
    if old != new: return f"{path}: {old!r} became {new!r}"
    return None


def python_difference( old_source, new_source ):
    """
    Compare two Python sources with docstrings stripped.

    Requires:
        - both arguments are str

    Ensures:
        - returns None when the stripped ASTs are identical
        - otherwise returns the first-difference string, or a syntax-error string naming the side

    Raises:
        - nothing
    """
    trees = []
    for side, source in ( ( "old", old_source ), ( "new", new_source ) ):
        try:
            trees.append( _DocstringStripper().visit( ast.parse( source ) ) )
        except SyntaxError as err:
            return f"{side} file does not parse: {err.msg} at line {err.lineno}"
    return first_difference( trees[ 0 ], trees[ 1 ] )


def dart_tokens( source ):
    """
    Split Dart source into non-comment tokens.

    Requires:
        - source is Dart text

    Ensures:
        - returns [ ( line, text ) ] for identifiers, numbers, string literals and punctuation
        - whitespace and every kind of comment, including nested block comments, are dropped
        - a comment marker inside a string literal stays part of the string

    Raises:
        - nothing
    """
    tokens = []
    i, n, line = 0, len( source ), 1
    while i < n:
        c = source[ i ]
        if c.isspace():
            line += c == "\n"
            i += 1
        elif source.startswith( "//", i ):
            end = source.find( "\n", i )
            i = n if end == -1 else end
        elif source.startswith( "/*", i ):
            depth, i = 1, i + 2
            while i < n and depth:
                if source.startswith( "/*", i ): depth, i = depth + 1, i + 2
                elif source.startswith( "*/", i ): depth, i = depth - 1, i + 2
                else:
                    line += source[ i ] == "\n"
                    i += 1
        elif c in QUOTES or ( c == "r" and i + 1 < n and source[ i + 1 ] in QUOTES ):
            raw   = c == "r"
            end   = _skip_string( source, i + 1 if raw else i, raw )
            tokens.append( ( line, source[ i : end ] ) )
            line += source.count( "\n", i, end )
            i = end
        else:
            m   = IDENT_REGEX.match( source, i )
            end = m.end() if m else i + 1
            tokens.append( ( line, source[ i : end ] ) )
            i = end
    return tokens


def dart_difference( old_source, new_source ):
    """
    Compare the non-comment tokens of two Dart sources.

    Requires:
        - both arguments are str

    Ensures:
        - returns None when every changed token is a comment token
        - otherwise returns a string naming the first differing token and its new-file line

    Raises:
        - nothing
    """
    old, new = dart_tokens( old_source ), dart_tokens( new_source )
    for ( _, a ), ( line, b ) in zip( old, new ):
        if a != b: return f"line {line}: token {a!r} became {b!r}"
    if len( old ) != len( new ):
        longer = old if len( old ) > len( new ) else new
        line, text = longer[ min( len( old ), len( new ) ) ]
        return f"{'removed' if longer is old else 'added'} token {text!r} at line {line}"
    return None


def file_difference( path, old_source, new_source ):
    """
    Check one changed file.

    Requires:
        - path ends in .py or .dart
        - old_source and new_source are str, or None when the file does not exist on that side

    Ensures:
        - returns None when the change is docs-only
        - a file added or deleted is a difference, because its code appeared or vanished

    Raises:
        - nothing
    """
    if old_source is None: return "file added"
    if new_source is None: return "file deleted"
    return python_difference( old_source, new_source ) if path.endswith( ".py" ) else dart_difference( old_source, new_source )


def _git( root, *args ):
    """
    Run git in root and return stdout.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the decoded stdout

    Raises:
        - RuntimeError naming the git error when the command fails
    """
    res = subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True, text=True, encoding="utf-8" )
    if res.returncode != 0: raise RuntimeError( f"git {' '.join( args )} failed: {res.stderr.strip()}" )
    return res.stdout


def _show( root, rev, path ):
    """
    Read a file at a revision, or the working tree when rev is None.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the text, or None when the file does not exist there

    Raises:
        - nothing
    """
    if rev is None:
        try:
            with open( f"{root}/{path}", encoding="utf-8" ) as handle: return handle.read()
        except FileNotFoundError: return None
    res = subprocess.run( [ "git", "-C", str( root ), "show", f"{rev}:{path}" ], capture_output=True, text=True, encoding="utf-8" )
    return res.stdout if res.returncode == 0 else None


def check_diff( root, base, head=None ):
    """
    Check every changed .py and .dart file between base and head.

    Requires:
        - root is a git working tree; base is a revision
        - head is a revision, or None for the working tree

    Ensures:
        - returns [ ( path, None or failure string ) ] sorted by path, one entry per changed .py/.dart file
        - renames count as a delete plus an add, so a moved file fails

    Raises:
        - RuntimeError from git when the diff fails
    """
    args  = [ "diff", "--name-only", "--no-renames", base ] + ( [ head ] if head else [] )
    names = sorted( p for p in _git( root, *args ).split( "\n" ) if p.endswith( SUFFIXES ) )
    return [ ( p, file_difference( p, _show( root, base, p ), _show( root, head, p ) ) ) for p in names ]


def main( argv=None, out=None ):
    """
    Command-line entry: print a pass or fail line per changed file.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - returns 0 when every changed file is docs-only, 1 when any is not
        - an empty change list passes

    Raises:
        - RuntimeError from git when the diff fails
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Prove a diff changed only documentation" )
    parser.add_argument( "--base", required=True, help="revision to compare from" )
    parser.add_argument( "--head", help="revision to compare to; default is the working tree" )
    parser.add_argument( "--repo-root", default=".", help="git working tree to read" )
    args    = parser.parse_args( argv )
    results = check_diff( args.repo_root, args.base, args.head )
    for path, failure in results: out.write( f"PASS {path}\n" if failure is None else f"FAIL {path}: {failure}\n" )
    failed = sum( 1 for _, failure in results if failure is not None )
    out.write( f"{len( results ) - failed} passed, {failed} failed\n" )
    return 1 if failed else 0


if __name__ == "__main__": sys.exit( main() )  # pragma: no cover -- script entry, main() is tested
