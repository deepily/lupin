"""
Census guard: no function in a tracked src Python file has a mutable default argument.

A default is evaluated once, when the function is defined.
A list, dict or set there is one object shared by every call that leaves the argument out. The scan reads the tracked files with ast and reports each such default.
It must find files, must find a planted default, and must find none in the tree.
"""
import ast
import os
import subprocess
import warnings

import pytest

EXCLUDED      = ( "/.venv/", "node_modules", "site-packages" )

# A call is allowed as a default only when it provably returns an immutable value, or is a framework marker.
ALLOWED_CALLS = {
    "Depends"   : "FastAPI marker, read once at route definition by design",
    "Query"     : "FastAPI marker, read once at route definition by design",
    "Header"    : "FastAPI marker, read once at route definition by design",
    "Body"      : "FastAPI marker, read once at route definition by design",
    "Form"      : "FastAPI marker, read once at route definition by design",
    "File"      : "FastAPI marker, read once at route definition by design",
    "frozenset" : "an immutable set",
    "tuple"     : "an immutable sequence",
    "str"       : "an immutable string",
    "int"       : "an immutable number",
    "float"     : "an immutable number",
    "bool"      : "an immutable flag",
    "bytes"     : "an immutable byte string",
    "datetime"  : "an immutable timestamp built from literals",
    "timedelta" : "an immutable duration built from literals",
    "_dt"       : "an import alias of datetime.datetime in one unit test",
}


def _root():
    """Return the working tree this test runs in: LUPIN_ROOT when set, else the git top level."""
    root = os.environ.get( "LUPIN_ROOT" )
    if root: return root
    return subprocess.run( [ "git", "rev-parse", "--show-toplevel" ], capture_output=True, text=True, check=True ).stdout.strip()


def tracked_sources( root ):
    """
    List the tracked Python files under src.

    Ensures:
        - returns repo-relative paths from git, never from a disk walk
        - a vendored environment or package folder is left out
    """
    out = subprocess.run( [ "git", "ls-files", "--", "src/*.py" ], cwd=root, capture_output=True, text=True, check=True ).stdout.split( "\n" )
    return sorted( p for p in out if p and not any( bit in p for bit in EXCLUDED ) )


def is_mutable( default ):
    """Return True for a container literal or a call not on ALLOWED_CALLS."""
    if isinstance( default, ( ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp ) ): return True
    if isinstance( default, ast.Call ):
        func = default.func
        name = func.id if isinstance( func, ast.Name ) else func.attr if isinstance( func, ast.Attribute ) else ""
        return name not in ALLOWED_CALLS
    return False


def mutable_defaults( source, path="<source>" ):
    """
    Find the mutable defaults in one source text.

    Ensures:
        - returns [ ( path, line, function, argument, default text ) ] for every positional and keyword-only default
        - a lambda's defaults are included
    """
    found = []
    with warnings.catch_warnings():
        warnings.simplefilter( "ignore" )                      # a scanned file may hold an invalid escape; that is its own finding
        tree = ast.parse( source )
    for node in ast.walk( tree ):
        if not isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda ) ): continue
        args  = node.args
        pos   = args.posonlyargs + args.args
        pairs = list( zip( pos[ len( pos ) - len( args.defaults ): ], args.defaults ) )
        pairs += [ ( arg, d ) for arg, d in zip( args.kwonlyargs, args.kw_defaults ) if d is not None ]
        name  = getattr( node, "name", "<lambda>" )
        found += [ ( path, node.lineno, name, arg.arg, ast.unparse( d ) ) for arg, d in pairs if is_mutable( d ) ]
    return found


class TestScan:
    """The scanner finds what it should, so a clean tree means something."""

    PLANTED = (
        "def a( x=[] ): pass\n"
        "def b( *, y={} ): pass\n"
        "async def c( z={ 1 } ): pass\n"
        "class K:\n"
        "    def __init__( self, w=OrderedDict(), v=list() ): pass\n"
        "f = lambda q=[]: q\n"
        "def g( p=get_default_stats_dict(), r=du.get_current_date(), m=np.zeros( 3 ) ): pass\n"
        "def fine( n=None, s='x', t=(), u=frozenset(), v=Depends( f ) ): pass\n"
    )

    def test_a_planted_default_of_each_kind_is_found( self ):
        found = mutable_defaults( self.PLANTED )
        assert sorted( ( f[ 2 ], f[ 3 ] ) for f in found ) == [ ( "<lambda>", "q" ), ( "__init__", "v" ), ( "__init__", "w" ),
                                                               ( "a", "x" ), ( "b", "y" ), ( "c", "z" ),
                                                               ( "g", "m" ), ( "g", "p" ), ( "g", "r" ) ]

    def test_immutable_defaults_are_not_reported( self ):
        assert mutable_defaults( "def fine( n=None, s='x', t=(), u=frozenset(), k=1, d=Depends( f ), q=Query( 1 ) ): pass\n" ) == []

    def test_every_allowed_call_names_its_reason( self ):
        assert ALLOWED_CALLS and all( isinstance( why, str ) and why for why in ALLOWED_CALLS.values() )


class TestTree:
    """The tracked tree holds none."""

    def test_the_scan_reads_the_tracked_sources( self ):
        files = tracked_sources( _root() )
        assert len( files ) > 1000
        assert "src/cosa/memory/solution_snapshot.py" in files
        assert not any( bit in p for p in files for bit in EXCLUDED )

    def test_no_function_has_a_mutable_default( self ):
        root, found = _root(), []
        for path in tracked_sources( root ):
            with open( os.path.join( root, path ), encoding="utf-8" ) as handle:
                found += mutable_defaults( handle.read(), path )
        assert found == [], "mutable defaults:\n" + "\n".join( f"  {p}:{n} {fn}( {a}={d} )" for p, n, fn, a, d in found )
