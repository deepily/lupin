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
# The key is the qualified name: an import is followed, so `from fastapi import Depends` is "fastapi.Depends".
ALLOWED_CALLS = {
    "fastapi.Depends"    : "FastAPI marker, read once at route definition by design",
    "fastapi.Query"      : "FastAPI marker, read once at route definition by design",
    "fastapi.Header"     : "FastAPI marker, read once at route definition by design",
    "fastapi.Body"       : "FastAPI marker, read once at route definition by design",
    "fastapi.Form"       : "FastAPI marker, read once at route definition by design",
    "fastapi.File"       : "FastAPI marker, read once at route definition by design",
    "frozenset"          : "an immutable set",
    "tuple"              : "an immutable sequence",
    "str"                : "an immutable string",
    "int"                : "an immutable number",
    "float"              : "an immutable number",
    "bool"               : "an immutable flag",
    "bytes"              : "an immutable byte string",
    "datetime.datetime"  : "an immutable timestamp built from literals",
    "datetime.timedelta" : "an immutable duration built from literals",
}
CONTAINER_CALLS = ( "list", "dict", "set", "OrderedDict", "defaultdict", "deque", "Counter", "bytearray" )


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


def module_names( tree ):
    """Return ( assigned, imported ): name to value node, and name to dotted source."""
    assigned, imported = { }, { }
    for node in tree.body:
        if isinstance( node, ast.Assign ):
            for target in node.targets:
                if isinstance( target, ast.Name ): assigned[ target.id ] = node.value
        elif isinstance( node, ast.AnnAssign ) and isinstance( node.target, ast.Name ) and node.value is not None: assigned[ node.target.id ] = node.value
        elif isinstance( node, ast.Import ):
            for alias in node.names: imported[ alias.asname or alias.name.split( "." )[ 0 ] ] = alias.name if alias.asname else alias.name.split( "." )[ 0 ]
        elif isinstance( node, ast.ImportFrom ) and node.module:
            for alias in node.names: imported[ alias.asname or alias.name ] = f"{node.module}.{alias.name}"
    return assigned, imported


def qualified( func, imported ):
    """Return the dotted name of a callee, following an import, or an empty string."""
    if isinstance( func, ast.Name ): return imported.get( func.id, func.id )
    if isinstance( func, ast.Attribute ):
        head = qualified( func.value, imported )
        return f"{head}.{func.attr}" if head else ""
    return ""


def is_container( value ):
    """Return True for a list, dict or set literal, comprehension or constructor call."""
    if isinstance( value, ( ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp ) ): return True
    if isinstance( value, ast.Call ) and isinstance( value.func, ( ast.Name, ast.Attribute ) ):
        name = value.func.id if isinstance( value.func, ast.Name ) else value.func.attr
        return name in CONTAINER_CALLS
    return False


def is_mutable( default, assigned=None, imported=None, lookup=None, depth=0 ):
    """
    Return True when a default is built once and may be shared.

    Ensures:
        - a container literal or comprehension is mutable
        - a call is mutable unless its qualified name is on ALLOWED_CALLS
        - a name is followed to its module-level value, in the file or through an import by lookup( module, name ),
          and is mutable when that value is a container
    """
    assigned, imported = assigned or { }, imported or { }
    if is_container( default ): return True
    if isinstance( default, ast.Call ): return qualified( default.func, imported ) not in ALLOWED_CALLS
    if isinstance( default, ast.Name ) and depth < 4:
        if default.id in assigned:
            value = assigned[ default.id ]
            return is_container( value ) or ( isinstance( value, ast.Name ) and is_mutable( value, assigned, imported, lookup, depth + 1 ) )
        if default.id in imported and lookup is not None:
            module, _, name = imported[ default.id ].rpartition( "." )
            return lookup( module, name, depth + 1 )
    return False


def mutable_defaults( source, path="<source>", lookup=None ):
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
    assigned, imported = module_names( tree )
    for node in ast.walk( tree ):
        if not isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda ) ): continue
        args  = node.args
        pos   = args.posonlyargs + args.args
        pairs = list( zip( pos[ len( pos ) - len( args.defaults ): ], args.defaults ) )
        pairs += [ ( arg, d ) for arg, d in zip( args.kwonlyargs, args.kw_defaults ) if d is not None ]
        name  = getattr( node, "name", "<lambda>" )
        found += [ ( path, node.lineno, name, arg.arg, ast.unparse( d ) ) for arg, d in pairs if is_mutable( d, assigned, imported, lookup ) ]
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
        "from fastapi import Depends\n"
        "def fine( n=None, s='x', t=(), u=frozenset(), v=Depends( f ) ): pass\n"
    )

    def test_a_planted_default_of_each_kind_is_found( self ):
        found = mutable_defaults( self.PLANTED )
        assert sorted( ( f[ 2 ], f[ 3 ] ) for f in found ) == [ ( "<lambda>", "q" ), ( "__init__", "v" ), ( "__init__", "w" ),
                                                               ( "a", "x" ), ( "b", "y" ), ( "c", "z" ),
                                                               ( "g", "m" ), ( "g", "p" ), ( "g", "r" ) ]

    def test_a_name_that_points_at_a_module_level_container_is_found( self ):
        source = "TABLE = { 'a': 1 }\nLIST = [ ]\nALIAS = TABLE\nSAFE = ( 1, 2 )\nNUM = 3\n" \
                 "def f( t=TABLE ): pass\ndef g( l=LIST ): pass\ndef h( a=ALIAS ): pass\ndef k( s=SAFE, n=NUM ): pass\n"
        assert sorted( f[ 2 ] for f in mutable_defaults( source ) ) == [ "f", "g", "h" ]

    def test_a_name_imported_from_another_module_is_followed( self ):
        found = mutable_defaults( "from pkg.mod import TABLE, SAFE\ndef f( t=TABLE, s=SAFE ): pass\n", lookup=lambda module, name, depth: name == "TABLE" )
        assert [ f[ 3 ] for f in found ] == [ "t" ]

    def test_the_allow_list_matches_the_qualified_name( self ):
        assert mutable_defaults( "from fastapi import Depends\ndef f( d=Depends( x ) ): pass\n" ) == []
        assert [ f[ 3 ] for f in mutable_defaults( "from mylib import Depends\ndef f( d=Depends( x ) ): pass\n" ) ] == [ "d" ]
        assert mutable_defaults( "import datetime as _d\ndef f( n=_d.datetime( 2026, 1, 1 ) ): pass\n" ) == []
        assert [ f[ 3 ] for f in mutable_defaults( "from other import datetime\ndef f( n=datetime( 1 ) ): pass\n" ) ] == [ "n" ]

    def test_immutable_defaults_are_not_reported( self ):
        assert mutable_defaults( "from fastapi import Depends, Query\ndef fine( n=None, s='x', t=(), u=frozenset(), k=1, d=Depends( f ), q=Query( 1 ) ): pass\n" ) == []

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
        files   = tracked_sources( root )
        modules = { p[ len( "src/" ):-3 ].replace( "/", "." ): p for p in files }
        parsed  = { }
        def names_of( path ):
            if path not in parsed:
                with warnings.catch_warnings():
                    warnings.simplefilter( "ignore" )
                    with open( os.path.join( root, path ), encoding="utf-8" ) as handle: parsed[ path ] = module_names( ast.parse( handle.read() ) )
            return parsed[ path ]
        def lookup( module, name, depth ):
            path = modules.get( module )
            if path is None or depth > 4: return False
            assigned, imported = names_of( path )
            if name in assigned: return is_container( assigned[ name ] )
            return name in imported and lookup( *imported[ name ].rpartition( "." )[ ::2 ], depth + 1 )
        for path in files:
            with open( os.path.join( root, path ), encoding="utf-8" ) as handle:
                found += mutable_defaults( handle.read(), path, lookup )
        assert found == [], "mutable defaults:\n" + "\n".join( f"  {p}:{n} {fn}( {a}={d} )" for p, n, fn, a, d in found )
