"""
Duplicate detection over Python definitions: an exact structural pass and a near pass.

Exact pass: two functions are clones when their ASTs are equal after docstrings are removed.
Every name, attribute and constant is erased first. Near pass: the pre-order sequence of AST
node types is cut into overlapping shingles. Two functions are reported when the Jaccard
similarity of their shingle sets reaches the threshold. The report holds structural
similarity only. Behaviour that matches under different vocabulary is found by review.
"""
import ast
import collections
import hashlib

from cosa.repo.symindex.errors import DependencyMissing
from cosa.repo.symindex.js_index import extract_js_shapes
from cosa.repo.symindex.py_index import _walk_scope, module_name, strip_docs

SHINGLE          = 5
SEEDS            = 12             # each definition is compared only with those sharing one of its rarest shingles
DEFAULT_MIN_NODE = 25            # a 3-5 statement helper is 25-40 nodes; below 25 a 5-long shingle set holds under 21 members
DEFAULT_THRESH   = 0.85
LANGUAGES        = ( "python", )   # always read; "javascript" and "typescript" are added when a file of that kind parsed
PY_LANG          = "py"            # the grouping tag of a Python definition; a script definition carries SCRIPT_LANG
SCRIPT_LANG      = "script"        # JavaScript and TypeScript share one node vocabulary, so they may group together
TS_SUFFIXES      = ( ".ts", ".tsx" )


class _Norm( ast.NodeTransformer ):
    """Erase names and constants so two renamed copies normalise to the same tree."""

    def visit_Name( self, n ):      return ast.copy_location( ast.Name( id="_", ctx=n.ctx ), n )
    def visit_arg( self, n ):       n.arg, n.annotation = "_", None; return n
    def visit_Constant( self, n ):  return ast.copy_location( ast.Constant( 0 ), n )
    def visit_Attribute( self, n ): self.generic_visit( n ); n.attr = "_"; return n


def normalised( node ):
    """
    Return a normalised copy of a function definition, used to compare structure only.

    Ensures:
        - returns a copy of a def with docstrings, names, constants, decorators and its own name erased
    """
    m = _Norm().visit( strip_docs( node ) )
    m.name = "_"; m.decorator_list = []
    return m


def _preorder_types( node ):
    """Ensures: returns the node type names of the tree in pre-order."""
    out = [ type( node ).__name__ ]
    for child in ast.iter_child_nodes( node ): out.extend( _preorder_types( child ) )
    return out


def shingles( node ):
    """
    Return the shingle set of a definition.

    Ensures:
        - returns the set of SHINGLE-long windows over the pre-order node types, each hashed to an int
    """
    return shingles_of( _preorder_types( normalised( node ) ) )


def shingles_of( seq ):
    """Ensures: returns the hashed SHINGLE-long windows over a list of node type names."""
    return { hash( tuple( seq[ i:i + SHINGLE ] ) ) for i in range( max( len( seq ) - SHINGLE + 1, 1 ) ) }


def _functions( spec, paths, scanned, include_private=False ):
    """
    Yield every function and method in the given Python files.

    Requires:
        - scanned is a list

    Ensures:
        - yields ( id, node ) for every public function and method of the given files, ids as in the index;
          with include_private also the underscore-named ones and the functions nested inside functions
          (id parts joined with <locals>, as the index names them)
        - appends to scanned each file that was read and parsed, once, before its definitions are yielded;
          a file that does not parse is skipped and is not appended
    """
    for p in paths:
        try:
            tree = ast.parse( p.read_text( encoding="utf-8" ), str( p ) )
        except ( SyntaxError, UnicodeDecodeError ):
            continue
        scanned.append( p )
        mod = module_name( spec, p )
        for parts, node, _ in _walk_scope( tree.body, [], False, include_private ):
            if not isinstance( node, ast.ClassDef ): yield ".".join( x for x in ( mod, *parts ) if x ), node


def _definitions( spec, paths, js_files, include_private, scanned, js_scanned, missing ):
    """
    Yield ( id, size, digest, shingles, language tag ) for each definition of both languages.

    Requires:
        - scanned, js_scanned and missing are lists; they receive the Python files read, the script files read,
          and the names of the tools a script pass needed and did not find

    Ensures:
        - the Python entries come first, then the script ones; a script id is "<file relative to the root>#<qualified name>"
        - node and the compiler are looked up only when script files were handed in
        - with a tool missing no script definition is yielded and its name is appended to missing
    """
    for fid, node in _functions( spec, paths, scanned, include_private ):
        yield fid, sum( 1 for _ in ast.walk( node ) ), hashlib.sha1( ast.dump( normalised( node ) ).encode( "utf-8" ) ).hexdigest(), shingles( node ), PY_LANG
    try:
        res = extract_js_shapes( spec.root, js_files, public_only=not include_private )
    except DependencyMissing as e:
        missing.append( e.what )
        return
    js_scanned.extend( res[ "scanned" ] )
    for d in res[ "defs" ]:
        yield f"{d[ 'file' ]}#{d[ 'name' ]}", len( d[ "kinds" ] ), hashlib.sha1( ",".join( d[ "kinds" ] ).encode( "utf-8" ) ).hexdigest(), shingles_of( d[ "kinds" ] ), SCRIPT_LANG


def find_duplicates( spec, paths, min_nodes=DEFAULT_MIN_NODE, threshold=DEFAULT_THRESH, js_files=(), include_private=True ):
    """
    Find exact and near duplicate functions.

    Requires:
        - paths are Python files under spec.root; js_files are JavaScript or TypeScript files under spec.root
        - 0 < threshold <= 1 and min_nodes >= 1
    Ensures:
        - returns { "provenance", "exact", "near" }
        - provenance names the languages the pass read (the module's language tuple, plus "javascript" and "typescript"
          for the script files that parsed) and files_scanned, the number of files that parsed; files that did not parse are
          in neither, so files_scanned can be below len( paths ) + len( js_files )
        - provenance.missing_dependencies lists the tools a script pass needed and did not find; the report is then Python only
        - with include_private (the default) private and nested definitions take part
        - a definition id that repeats (a getter and its setter, an overload) is numbered: the second is "<id>~2", the third "<id>~3"
        - Python and script definitions are never grouped together and never paired in the near pass
        - exact is a list of id lists (size >= 2), largest first
        - near is a list of { "ids": [a, b], "jaccard": float } for pairs at or above the
          threshold whose normalised trees are not identical (candidates are pairs sharing a rare shingle), sorted by similarity then ids
        - only definitions with at least min_nodes AST nodes take part
    """
    groups, sets, scanned, js_scanned, missing = collections.defaultdict( list ), {}, [], [], []
    ids = collections.Counter()
    for fid, size, digest, shs, lang in _definitions( spec, paths, js_files, include_private, scanned, js_scanned, missing ):
        ids[ fid ] += 1
        if ids[ fid ] > 1: fid = f"{fid}~{ids[ fid ]}"
        if size < min_nodes: continue
        key = ( lang, digest )
        groups[ key ].append( fid )
        sets[ fid ] = ( key, shs )
    exact  = sorted( ( sorted( g ) for g in groups.values() if len( g ) > 1 ), key=lambda g: ( -len( g ), g ) )
    df = collections.Counter( sh for _, ( _, s ) in sets.items() for sh in s )
    index = collections.defaultdict( set )
    for fid, ( _, s ) in sets.items():
        for sh in sorted( s, key=lambda x: ( df[ x ], x ) )[ :SEEDS ]: index[ sh ].add( fid )
    near, seen = [], set()
    for fid, ( key, s ) in sorted( sets.items() ):
        cands = { other for sh in sorted( s, key=lambda x: ( df[ x ], x ) )[ :SEEDS ] for other in index[ sh ] if other > fid }
        for other in cands:
            okey, os_ = sets[ other ]
            if okey == key or okey[ 0 ] != key[ 0 ] or ( fid, other ) in seen: continue
            seen.add( ( fid, other ) )
            jac = len( s & os_ ) / float( len( s | os_ ) )
            if jac >= threshold: near.append( { "ids": [ fid, other ], "jaccard": round( jac, 4 ) } )
    near.sort( key=lambda d: ( -d[ "jaccard" ], d[ "ids" ] ) )
    prov = { "index_root": str( spec.root ), "min_nodes": min_nodes, "threshold": threshold, "shingle": SHINGLE,
             "languages": list( LANGUAGES ) + [ n for n, here in ( ( "javascript", any( not f.endswith( TS_SUFFIXES ) for f in js_scanned ) ),
                                                                   ( "typescript", any( f.endswith( TS_SUFFIXES ) for f in js_scanned ) ) ) if here ],
             "files_scanned": len( scanned ) + len( js_scanned ), "include_private": include_private, "missing_dependencies": missing,
             "considered": len( sets ), "kind": "structural only: exact clones and near pass; not an evaluation set by itself" }
    return { "provenance": prov, "exact": exact, "near": near }
