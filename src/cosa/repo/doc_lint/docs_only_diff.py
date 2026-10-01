"""
Docs-only diff check: proves a documentation rewrite left the code unchanged.

Python files pass when their ASTs are identical once docstrings are removed and their directive
comments (pragma, noqa, type:, coding, shebang) match. Dart files pass when every non-comment
token is identical and their directive comments (@dart, ignore, coverage) match. A failure names
the first difference. Every other changed file type, a mode change and an untracked new file
fail too, except markdown, which is the documentation itself. Stdlib only.

What "docs-only" means here, and does not:
    - no AST change besides docstrings; a docstring is a runtime value, so code that reads
      __doc__ (FastAPI route descriptions, MCP tool text) sees a docstring change
    - Dart is compared as a token list, so whitespace that changes meaning, as in `a - -b` against
      `a--b`, passes; the compiler gate catches it
    - a comment that merely looks like a directive, such as "# type: the kind", also fails; that
      errs toward a failure
"""

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize

from .dartdoc_lint import QUOTES, _skip_string

IDENT_REGEX = re.compile( r"[A-Za-z0-9_$]+" )
SUFFIXES    = ( ".py", ".dart" )
DOC_SUFFIX  = ".md"

PY_DIRECTIVE   = re.compile( r"^#(!|\s*(pragma\b|noqa\b|type\s*:|fmt\s*:|pylint\s*:|mypy\s*:|pyright\s*:|isort\s*:|ruff\s*:|flake8\s*:|yapf\s*:|-\*-|.*coding[:=]))" )
DART_DIRECTIVE = re.compile( r"^(//+|/\*+)\s*(@dart\b|ignore\s*:|ignore_for_file\s*:|coverage\s*:|dart\s+format\s+(off|on)\b)" )


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


def directive_difference( old, new ):
    """
    Compare two ordered lists of directive comments.

    Requires:
        - old and new are lists of str

    Ensures:
        - returns None when they are equal
        - otherwise returns a string naming the first directive that was removed, added or changed

    Raises:
        - nothing
    """
    for a, b in zip( old, new ):
        if a != b: return f"directive comment {a!r} became {b!r}"
    if len( old ) == len( new ): return None
    longer = old if len( old ) > len( new ) else new
    return f"directive comment {'removed' if longer is old else 'added'}: {longer[ min( len( old ), len( new ) ) ]!r}"


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
    if type( old ) is not type( new ) or repr( old ) != repr( new ): return f"{path}: {old!r} became {new!r}"
    return None


def python_directives( source ):
    """
    List the directive comments of a Python source, in order.

    Requires:
        - source is Python text that tokenizes

    Ensures:
        - returns the stripped text of each comment that PY_DIRECTIVE matches: pragma, noqa,
          type:, fmt:, linter switches, a coding line and a shebang
        - a hash inside a string literal is not a comment

    Raises:
        - tokenize.TokenError or SyntaxError when the source does not tokenize
    """
    comments = ( t.string.strip() for t in tokenize.generate_tokens( io.StringIO( source ).readline ) if t.type == tokenize.COMMENT )
    return [ c for c in comments if PY_DIRECTIVE.match( c ) ]


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
    found = first_difference( trees[ 0 ], trees[ 1 ] )
    if found is not None: return found
    return directive_difference( python_directives( old_source ), python_directives( new_source ) )


def dart_tokens( source, directives=None ):
    """
    Split Dart source into non-comment tokens.

    Requires:
        - source is Dart text
        - directives is a list, or None when the caller does not want directive comments

    Ensures:
        - returns [ ( line, text ) ] for identifiers, numbers, string literals and punctuation
        - whitespace and every kind of comment, including nested block comments, are dropped
        - a comment marker inside a string literal stays part of the string
        - when directives is a list, each comment that DART_DIRECTIVE matches is appended to it, stripped

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
            end = n if end == -1 else end
            if directives is not None and DART_DIRECTIVE.match( source[ i : end ] ): directives.append( source[ i : end ].strip() )
            i = end
        elif source.startswith( "/*", i ):
            start, depth, i = i, 1, i + 2
            while i < n and depth:
                if source.startswith( "/*", i ): depth, i = depth + 1, i + 2
                elif source.startswith( "*/", i ): depth, i = depth - 1, i + 2
                else:
                    line += source[ i ] == "\n"
                    i += 1
            if directives is not None and DART_DIRECTIVE.match( source[ start : i ] ): directives.append( source[ start : i ].strip() )
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
        - returns None when every changed token is a comment token and the directive comments match
        - otherwise returns a string naming the first differing token and its new-file line

    Raises:
        - nothing
    """
    old_dirs, new_dirs = [], []
    old, new = dart_tokens( old_source, old_dirs ), dart_tokens( new_source, new_dirs )
    for ( _, a ), ( line, b ) in zip( old, new ):
        if a != b: return f"line {line}: token {a!r} became {b!r}"
    if len( old ) != len( new ):
        longer = old if len( old ) > len( new ) else new
        line, text = longer[ min( len( old ), len( new ) ) ]
        return f"{'removed' if longer is old else 'added'} token {text!r} at line {line}"
    return directive_difference( old_dirs, new_dirs )


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


def changed_files( root, base, head=None ):
    """
    List every path that differs between base and head, with its modes.

    Requires:
        - root is a git working tree; base is a revision
        - head is a revision, or None for the working tree

    Ensures:
        - returns { path: ( old_mode, new_mode ) } read with -z, so a non-ASCII name is not quoted
        - renames count as a delete plus an add
        - in working-tree mode, untracked files that git does not ignore are included with
          old mode "000000", since they are new files

    Raises:
        - RuntimeError from git when a command fails
    """
    args  = [ "diff", "--raw", "-z", "--no-renames", base ] + ( [ head ] if head else [] )
    parts = _git( root, *args ).split( "\0" )
    found = { path : ( meta.split()[ 0 ][ 1: ], meta.split()[ 1 ] ) for meta, path in zip( parts[ 0::2 ], parts[ 1::2 ] ) }
    if head is None:
        for path in _git( root, "ls-files", "--others", "--exclude-standard", "-z" ).split( "\0" ):
            if path: found[ path ] = ( "000000", "100644" )
    return found


def path_difference( path, modes, old_source, new_source ):
    """
    Judge one changed path.

    Requires:
        - modes is ( old_mode, new_mode ) from changed_files
        - old_source and new_source are the file text on each side, or None when absent

    Ensures:
        - a file type other than .py and .dart fails as unchecked
        - a mode change on a file present on both sides fails
        - otherwise the answer is file_difference

    Raises:
        - nothing
    """
    if not path.endswith( SUFFIXES ): return "file type not checked, only .py and .dart are compared"
    old_mode, new_mode = modes
    if "000000" not in modes and old_mode != new_mode: return f"mode changed {old_mode} -> {new_mode}"
    return file_difference( path, old_source, new_source )


def check_diff( root, base, head=None, paths=None ):
    """
    Check every changed file between base and head.

    Requires:
        - root is a git working tree; base is a revision
        - head is a revision, or None for the working tree
        - paths is a list of repo-relative prefixes, or None for every changed file

    Ensures:
        - returns [ ( path, None or failure string ) ] sorted by path, one entry per changed
          file that is not markdown
        - with paths given, only files under one of those prefixes are checked; a prefix matches whole
          directory names, so "lib/a" does not match "lib/ab"
        - a path that is not .py or .dart is a failure, never a silent skip
        - renames count as a delete plus an add, so a moved file fails

    Raises:
        - RuntimeError from git when a command fails
    """
    results = []
    for path, modes in sorted( changed_files( root, base, head ).items() ):
        if path.endswith( DOC_SUFFIX ): continue
        if paths is not None and not any( path == p or path.startswith( p.rstrip( "/" ) + "/" ) for p in paths ): continue
        results.append( ( path, path_difference( path, modes, _show( root, base, path ), _show( root, head, path ) ) ) )
    return results


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
    parser.add_argument( "--paths", nargs="+", help="check only files under these repo-relative directories or files" )
    args    = parser.parse_args( argv )
    results = check_diff( args.repo_root, args.base, args.head, args.paths )
    for path, failure in results: out.write( f"PASS {path}\n" if failure is None else f"FAIL {path}: {failure}\n" )
    failed = sum( 1 for _, failure in results if failure is not None )
    out.write( f"{len( results ) - failed} passed, {failed} failed (docs-only means no AST change besides docstrings)\n" )
    return 1 if failed else 0


if __name__ == "__main__": sys.exit( main() )  # pragma: no cover -- script entry, main() is tested
