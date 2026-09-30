"""
FastAPI route extraction by AST, with router prefixes resolved.

A route's path is the `prefix=` literal of the APIRouter it hangs on, plus any
`include_router( x, prefix= )` literal that names that router, plus the decorator's path.
The app's live route table is never imported, because that would import the whole server.
"""
import ast

HTTP = { "get", "post", "put", "patch", "delete", "websocket" }


def _lit( node ):
    """Ensures: returns the str value of a string-constant node, else None."""
    return node.value if isinstance( node, ast.Constant ) and isinstance( node.value, str ) else None


def _call_name( func ):
    """Ensures: returns the called name of `f(...)` or `x.f(...)`, else an empty string."""
    if isinstance( func, ast.Name ): return func.id
    return func.attr if isinstance( func, ast.Attribute ) else ""


def _kw_prefix( call ):
    """Ensures: returns the `prefix=` literal of a call, else None."""
    for kw in call.keywords:
        if kw.arg == "prefix": return _lit( kw.value )
    return None


def scan_file( tree ):
    """
    Scan one parsed module.

    Ensures:
        - returns ( routers, includes, imports ): routers maps variable name to its prefix literal,
          includes is a list of ( base, attr, prefix ) from include_router calls, and imports maps an
          imported alias to ( module name, original name ) so an include can be traced to its router
    """
    routers, includes, imports = {}, [], {}
    for n in ast.walk( tree ):
        if isinstance( n, ast.ImportFrom ):
            for a in n.names: imports[ a.asname or a.name ] = ( ( n.module or "" ).split( "." )[ -1 ], a.name )
        elif isinstance( n, ast.Import ):
            for a in n.names:
                parts = a.name.split( "." )
                imports[ a.asname or parts[ 0 ] ] = ( parts[ -2 ] if len( parts ) > 1 else "", parts[ -1 ] )
        if isinstance( n, ast.Assign ) and isinstance( n.value, ast.Call ) and _call_name( n.value.func ) == "APIRouter":
            for t in n.targets:
                if isinstance( t, ast.Name ): routers[ t.id ] = _kw_prefix( n.value ) or ""
        elif isinstance( n, ast.Call ) and isinstance( n.func, ast.Attribute ) and n.func.attr == "include_router" and n.args:
            a = n.args[ 0 ]
            if isinstance( a, ast.Attribute ) and isinstance( a.value, ast.Name ):
                includes.append( ( a.value.id, a.attr, _kw_prefix( n ) or "" ) )
            elif isinstance( a, ast.Name ):
                includes.append( ( None, a.id, _kw_prefix( n ) or "" ) )
    return routers, includes, imports


def route_decorators( node ):
    """
    Ensures:
        - returns [ ( receiver name, HTTP method, path literal ) ] for each route decorator of a def
        - a decorator whose first argument is not a string literal is skipped
    """
    out = []
    for d in getattr( node, "decorator_list", [] ):
        if isinstance( d, ast.Call ) and isinstance( d.func, ast.Attribute ) and d.func.attr in HTTP \
           and isinstance( d.func.value, ast.Name ) and d.args and _lit( d.args[ 0 ] ) is not None:
            out.append( ( d.func.value.id, d.func.attr, _lit( d.args[ 0 ] ) ) )
    return out


def resolve( per_file ):
    """
    Compute full route strings.

    Requires:
        - per_file is a list of dicts: { "file", "stem", "routers", "includes", "imports", "decorated" }
          where decorated is [ ( receiver, method, path, symbol id ) ]
    Ensures:
        - returns a sorted list of strings "METHOD /full/path -> symbol  (file)"
        - an include prefix applies to exactly the router it names: `m.r` reaches router `r` in the
          module `m` (an import alias is followed to the module's name); a bare `r` reaches the router
          in the same file, or the one its import alias names; other routers get no extra prefix
        - a receiver that is not a known router produces no route
    """
    extra = {}
    for f in per_file:
        for base, attr, prefix in f[ "includes" ]:
            if base is not None:
                stem = f[ "imports" ][ base ][ 1 ] if base in f[ "imports" ] else base
                extra.setdefault( ( stem, attr ), prefix )
            elif attr in f[ "routers" ]:
                extra.setdefault( ( f[ "stem" ], attr ), prefix )
            elif attr in f[ "imports" ]:
                mod, name = f[ "imports" ][ attr ]
                extra.setdefault( ( mod, name ), prefix )
    lines = []
    for f in per_file:
        for recv, method, path, sym in f[ "decorated" ]:
            own = f[ "routers" ].get( recv )
            if own is None: continue
            lines.append( f"{method.upper()} {extra.get( ( f[ 'stem' ], recv ), '' )}{own}{path} -> {sym}  ({f[ 'file' ]})" )
    return sorted( lines )
