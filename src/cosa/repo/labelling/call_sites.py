"""
W6: where a key symbol is called, shown beside its source in a Set B labelling item.

Python callers only. A call is found by the symbol's short name, so a same-named function elsewhere can appear; the reviewer sees the line.
"""
import ast
import pathlib
import subprocess

LIMIT = 5


def tracked_python_files( root ):
    """
    List the tracked Python files under root.

    Requires:
        - root is a git work tree

    Ensures:
        - returns sorted paths relative to root, from `git ls-files`

    Raises:
        - subprocess.CalledProcessError when root is not a git work tree
    """
    done = subprocess.run( [ "git", "ls-files", "*.py" ], cwd=root, capture_output=True, text=True, check=True )
    return sorted( done.stdout.splitlines() )


def is_test_path( path ):
    """Return True for a path under a tests folder or named test_*.py."""
    parts = pathlib.PurePosixPath( path ).parts
    return "tests" in parts or parts[ -1 ].startswith( "test_" )


def calls_in( source, name ):
    """
    Return the line numbers of calls to name in Python source.

    Ensures:
        - a call counts when its target is the bare name or an attribute of that name
        - returns each line number once, in order, so two calls on one line show it once
        - returns an empty list when the source does not parse
    """
    try:
        tree = ast.parse( source )
    except SyntaxError:
        return []
    lines = []
    for node in ast.walk( tree ):
        if not isinstance( node, ast.Call ): continue
        func = node.func
        if ( isinstance( func, ast.Name ) and func.id == name ) or ( isinstance( func, ast.Attribute ) and func.attr == name ): lines.append( node.lineno )
    return sorted( set( lines ) )


def find_call_sites( name, own_file, files, root, limit=LIMIT ):
    """
    Find up to limit places where a symbol is called.

    Requires:
        - name is the symbol's short name; own_file is the path that defines it, relative to root; files are paths relative to root

    Ensures:
        - returns "<path>:<line>  <source line>" strings in path then line order, at most limit of them
        - the defining file and test files are left out, and a file that cannot be read is skipped
    """
    found = []
    for path in sorted( files ):
        if path == own_file or is_test_path( path ): continue
        try:
            source = ( pathlib.Path( root ) / path ).read_text()
        except ( OSError, UnicodeDecodeError ):
            continue
        text = source.splitlines()
        for line in calls_in( source, name ):
            found.append( f"{path}:{line}  {text[ line - 1 ].strip()}" )
            if len( found ) == limit: return found
    return found
