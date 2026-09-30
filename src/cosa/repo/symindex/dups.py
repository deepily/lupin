"""
Duplicate detection over Python definitions: an exact structural pass and a near pass.

Exact pass: two functions are clones when their ASTs are equal after docstrings are removed
and every name, attribute and constant is erased. Near pass: the pre-order sequence of AST
node types is cut into overlapping shingles, and two functions are reported when the Jaccard
similarity of their shingle sets reaches the threshold. The report holds structural
similarity only; behaviour that matches under different vocabulary is found by review.
"""
import ast
import collections
import hashlib

from cosa.repo.symindex.py_index import _walk_scope, module_name, strip_docs

SHINGLE          = 5
SEEDS            = 12             # each definition is compared only with those sharing one of its rarest shingles
DEFAULT_MIN_NODE = 40
DEFAULT_THRESH   = 0.85


class _Norm( ast.NodeTransformer ):
    """Erase names and constants so two renamed copies normalise to the same tree."""

    def visit_Name( self, n ):      return ast.copy_location( ast.Name( id="_", ctx=n.ctx ), n )
    def visit_arg( self, n ):       n.arg, n.annotation = "_", None; return n
    def visit_Constant( self, n ):  return ast.copy_location( ast.Constant( 0 ), n )
    def visit_Attribute( self, n ): self.generic_visit( n ); n.attr = "_"; return n


def normalised( node ):
    """
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
    """Ensures: returns the set of SHINGLE-long windows over the pre-order node types, each hashed to an int."""
    seq = _preorder_types( normalised( node ) )
    return { hash( tuple( seq[ i:i + SHINGLE ] ) ) for i in range( max( len( seq ) - SHINGLE + 1, 1 ) ) }


def _functions( spec, paths ):
    """
    Ensures:
        - yields ( id, node ) for every public function and method of the given files, ids as in the index
    """
    for p in paths:
        try:
            tree = ast.parse( p.read_text( encoding="utf-8" ), str( p ) )
        except ( SyntaxError, UnicodeDecodeError ):
            continue
        mod = module_name( spec, p )
        for parts, node, _ in _walk_scope( tree.body, [], False, False ):
            if not isinstance( node, ast.ClassDef ): yield ".".join( x for x in ( mod, *parts ) if x ), node


def find_duplicates( spec, paths, min_nodes=DEFAULT_MIN_NODE, threshold=DEFAULT_THRESH ):
    """
    Find exact and near duplicate functions.

    Requires:
        - paths are Python files under spec.root
        - 0 < threshold <= 1 and min_nodes >= 1
    Ensures:
        - returns { "provenance", "exact", "near" }
        - exact is a list of id lists (size >= 2), largest first
        - near is a list of { "ids": [a, b], "jaccard": float } for pairs at or above the
          threshold whose normalised trees are NOT identical (candidates are pairs sharing a rare shingle), sorted by similarity then ids
        - only definitions with at least min_nodes AST nodes take part
    """
    groups, sets = collections.defaultdict( list ), {}
    for fid, node in _functions( spec, paths ):
        if sum( 1 for _ in ast.walk( node ) ) < min_nodes: continue
        key = hashlib.sha1( ast.dump( normalised( node ) ).encode( "utf-8" ) ).hexdigest()
        groups[ key ].append( fid )
        sets[ fid ] = ( key, shingles( node ) )
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
            if okey == key or ( fid, other ) in seen: continue
            seen.add( ( fid, other ) )
            jac = len( s & os_ ) / float( len( s | os_ ) )
            if jac >= threshold: near.append( { "ids": [ fid, other ], "jaccard": round( jac, 4 ) } )
    near.sort( key=lambda d: ( -d[ "jaccard" ], d[ "ids" ] ) )
    prov = { "index_root": str( spec.root ), "min_nodes": min_nodes, "threshold": threshold, "shingle": SHINGLE,
             "considered": len( sets ), "kind": "structural only: exact clones and near pass; not an evaluation set by itself" }
    return { "provenance": prov, "exact": exact, "near": near }
