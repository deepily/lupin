"""
Python symbol extraction from the AST.

A public symbol is a class or function (sync or async) whose name does not start with an
underscore, found at module level or under module-level if/try/with/for/while blocks, plus the
public methods of public classes (and `__init__`). `__all__` is ignored. With include_all the
private names, every dunder, and helpers nested inside functions are returned too.
"""
import ast
import copy
import hashlib

_DEFS = ( ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef )


def strip_docs( node ):
    """
    Ensures:
        - returns a deep copy of node with every docstring removed
        - a body emptied by the removal holds a single `pass`
    """
    n = copy.deepcopy( node )
    for x in ast.walk( n ):
        body = getattr( x, "body", None )
        if isinstance( body, list ) and body and isinstance( body[ 0 ], ast.Expr ) \
           and isinstance( body[ 0 ].value, ast.Constant ) and isinstance( body[ 0 ].value.value, str ):
            x.body = body[ 1: ] or [ ast.Pass() ]
    return n


def pin( node ):
    """
    Ensures:
        - returns 10 hex characters hashing the node with docstrings stripped
        - a docstring or comment edit never changes it; a code edit does
        - whitespace cannot matter because the AST is hashed, not the text
    """
    return hashlib.sha1( ast.dump( strip_docs( node ) ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def first_doc_line( node ):
    """
    Ensures:
        - returns the first non-empty docstring line, stripped, or an empty string
    """
    return next( ( l.strip() for l in ( ast.get_docstring( node ) or "" ).splitlines() if l.strip() ), "" )


def _blocks( stmt ):
    """
    Ensures:
        - returns the nested statement lists of a compound statement that is NOT a def,
          covering if/for/while/with/try (handlers, orelse, finalbody) and match cases
    """
    out = []
    for field in ( "body", "orelse", "finalbody" ):
        val = getattr( stmt, field, None )
        if isinstance( val, list ): out.append( val )
    for h in getattr( stmt, "handlers", [] ): out.append( h.body )
    for c in getattr( stmt, "cases", [] ): out.append( c.body )
    return out


def _walk_scope( body, prefix, in_class, include_all ):
    """
    Yield (qualified parts, node, defined inside a class) for the definitions in one scope.

    Requires:
        - body is a list of ast statements
    """
    for st in body:
        if isinstance( st, _DEFS ):
            public = not st.name.startswith( "_" ) or ( in_class and st.name == "__init__" )
            if public or include_all:
                yield prefix + [ st.name ], st, in_class
                if isinstance( st, ast.ClassDef ):
                    yield from _walk_scope( st.body, prefix + [ st.name ], True, include_all )
                elif include_all:
                    yield from _walk_scope( st.body, prefix + [ st.name, "<locals>" ], False, include_all )
        else:
            for blk in _blocks( st ):
                yield from _walk_scope( blk, prefix, in_class, include_all )


def module_name( spec, path ):
    """
    Ensures:
        - returns the dotted module name of a file relative to spec.module_base
        - a package's __init__.py is named after the package; a top-level __init__.py is ""
    """
    mod = path.relative_to( spec.module_base ).with_suffix( "" ).as_posix().replace( "/", "." )
    if mod == "__init__": return ""
    return mod[ :-len( ".__init__" ) ] if mod.endswith( ".__init__" ) else mod


def extract_python( spec, path, include_all=False ):
    """
    Extract the symbols of one Python file.

    Requires:
        - path lies under spec.module_base
    Ensures:
        - returns a list of dicts (lang, file, name, kind, sig, doc, pin, line, public)
        - `module` is the dotted module name relative to spec.module_base, for id building
        - a file that does not parse raises SyntaxError; the caller records it
    Raises:
        - SyntaxError, UnicodeDecodeError on an unreadable source file
    """
    text = path.read_text( encoding="utf-8" )
    tree = ast.parse( text, str( path ) )
    mod  = module_name( spec, path )
    rel  = path.relative_to( spec.root ).as_posix()
    out  = []
    for parts, node, in_class in _walk_scope( tree.body, [], False, include_all ):
        is_class = isinstance( node, ast.ClassDef )
        kind     = "class" if is_class else ( "method" if in_class else "function" )
        ret = f" -> {ast.unparse( node.returns )}" if not is_class and node.returns is not None else ""
        public   = "<locals>" not in parts and not any( p.startswith( "_" ) and p != "__init__" for p in parts )
        out.append( { "lang"   : "py",
                      "file"   : rel,
                      "module" : mod,
                      "name"   : ".".join( parts ),
                      "kind"   : kind,
                      "sig"    : "" if is_class else f"({ast.unparse( node.args )}){ret}",
                      "doc"    : first_doc_line( node ),
                      "pin"    : pin( node ),
                      "line"   : node.lineno,
                      "public" : public,
                      "_node"  : node } )
    return out
