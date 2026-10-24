"""
The seed pool of the diagnostic set: which symbols may seed a need, and in which cell.

A symbol is eligible when it is not test code, is big enough to describe, and has a docstring.
Twin groups come from the structural duplicate finder, through the grouping that already exists.
"""
import ast
import collections
import pathlib
import re

from cosa.repo.symindex import build, dups, js_index
from cosa.repo.symindex.py_index import _walk_scope
from lupin_mcp import reuse_need_check as nc

READER_PUBLIC     = "read_symbols"
READER_SEARCHABLE = "read_searchable"
LANG_OF           = { "py": "py", "ts": "ts" }
TEST_PARTS        = frozenset( { "tests", "test", "__tests__" } )
NONE_MIN_SYMBOLS  = 3
SUFFIX_RE         = re.compile( r"~(\d+)$" )


def read_pool_symbols( gen ):
    """
    Read the pool's symbols and name the reader that supplied them.

    Requires:
        - gen is a built index generation directory

    Ensures:
        - returns ( records, reader ) where reader is READER_SEARCHABLE when the index builder has read_searchable, else READER_PUBLIC
        - the manifest records the reader, because a draw made from the public symbols differs from one made after private members are indexed
    """
    if hasattr( build, "read_searchable" ):          # absent until the index fixes of phase 1 land; the reader name is recorded either way
        return build.read_searchable( gen ), READER_SEARCHABLE
    return build.read_symbols( gen ), READER_PUBLIC


def is_test_path( path ):
    """
    Say whether a repo-relative path is test code.

    Ensures:
        - True for a path with a tests, test or __tests__ directory, a test_ file name, or a .test. or .spec. file name
    """
    p = pathlib.PurePosixPath( path )
    return bool( TEST_PARTS & set( p.parts[ :-1 ] ) ) or p.name.startswith( "test_" ) or ".test." in p.name or ".spec." in p.name


class Measure:
    """One definition's node count and structural shingles."""

    def __init__( self, nodes, shingles ):
        """Hold the node count and the frozenset of shingle hashes."""
        self.nodes    = nodes
        self.shingles = shingles


def measure( root, records ):
    """
    Count nodes and take structural shingles for the definitions of an index.

    Requires:
        - root is the index root and records are index records with lang, file and name

    Ensures:
        - returns { record id: Measure } for every record found in its source
        - Python records are measured from the AST, script records from the compiler's node kinds, as the duplicate finder does
        - a record whose source cannot be found is absent from the result
    """
    root, out = pathlib.Path( root ), {}
    by_file   = collections.defaultdict( dict )
    for r in records: by_file[ r[ "file" ] ][ r[ "name" ] ] = r
    for rel, names in sorted( by_file.items() ):
        if not rel.endswith( ".py" ): continue
        try:
            tree = ast.parse( ( root / rel ).read_text( encoding="utf-8" ), rel )
        except ( SyntaxError, UnicodeDecodeError, OSError ):
            continue
        for parts, node, _ in _walk_scope( tree.body, [], False, True ):
            rec = names.get( ".".join( parts ) )
            if rec is not None: out[ rec[ "id" ] ] = Measure( sum( 1 for _ in ast.walk( node ) ), frozenset( dups.shingles( node ) ) )
    script_files = [ root / rel for rel in sorted( by_file ) if not rel.endswith( ".py" ) ]
    if script_files:
        for d in js_index.extract_js_shapes( root, script_files )[ "defs" ]:
            rec = by_file[ d[ "file" ] ].get( d[ "name" ] )
            if rec is not None: out[ rec[ "id" ] ] = Measure( len( d[ "kinds" ] ), frozenset( dups.shingles_of( d[ "kinds" ] ) ) )
    return out


def eligible( records, measures, min_nodes=dups.DEFAULT_MIN_NODE ):
    """
    Keep the records that may seed a need, and count why the others were dropped.

    Requires:
        - records are index records; measures comes from measure()

    Ensures:
        - returns ( kept, dropped ) with kept sorted by id and dropped mapping each reason to a count
        - a record is dropped, under the first reason that applies, as: other_language (not py or ts), test, unmeasured (no source found),
          small (fewer than min_nodes nodes) or no_docstring (an empty doc)
    """
    kept, dropped = [], collections.Counter()
    for r in sorted( records, key=lambda r: r[ "id" ] ):
        if r[ "lang" ] not in LANG_OF: dropped[ "other_language" ] += 1
        elif is_test_path( r[ "file" ] ): dropped[ "test" ] += 1
        elif r[ "id" ] not in measures: dropped[ "unmeasured" ] += 1
        elif measures[ r[ "id" ] ].nodes < min_nodes: dropped[ "small" ] += 1
        elif not r[ "doc" ]: dropped[ "no_docstring" ] += 1
        else: kept.append( r )
    return kept, dict( dropped )


def index_id( dups_id, prefix="" ):
    """
    Map an id of the duplicate finder to the id the index gives the same definition.

    Requires:
        - dups_id is "module.name" for Python or "file#name" for a script file, with "~N" for the Nth repeat

    Ensures:
        - a script id becomes its file stem with dots for slashes, a dot and the name
        - a "~N" repeat suffix becomes the index's "#N"
        - prefix is put in front, for a tree that is not the lupin tree
    """
    m    = SUFFIX_RE.search( dups_id )
    base = SUFFIX_RE.sub( "", dups_id )
    if "#" in base:
        file, name = base.split( "#", 1 )
        base = pathlib.PurePosixPath( file ).with_suffix( "" ).as_posix().replace( "/", "." ) + "." + name
    return prefix + base + ( f"#{m.group( 1 )}" if m else "" )


def dups_manifest( result, prefix="" ):
    """
    Turn the duplicate finder's output into the manifest shape that twin_groups reads.

    Requires:
        - result is the dict dups.find_duplicates returns: exact as lists of ids, near as { ids, jaccard }

    Ensures:
        - returns { "exact": [ { "members": [ { "id" } ] } ], "near": [ ... ] } with every id mapped to the index's id
    """
    def members( ids ): return { "members": [ { "id": index_id( i, prefix ) } for i in ids ] }
    return { "exact": [ members( ids ) for ids in result[ "exact" ] ], "near": [ members( pair[ "ids" ] ) for pair in result[ "near" ] ] }


def twin_map( result, prefix="" ):
    """
    Map each definition to the other members of its twin group.

    Ensures:
        - returns the answer of reuse_need_check.twin_groups over dups_manifest( result ): { id: sorted other members }
    """
    return nc.twin_groups( dups_manifest( result, prefix ) )


def cell_pool( kept, twins, all_ids ):
    """
    Build the ( kind, language ) pool that the census and the draw read.

    Requires:
        - kept comes from eligible(); twins from twin_map(); all_ids is the set of every id in the index

    Ensures:
        - near_copy: kept seeds with at least one twin that is in the index
        - work_alike and cross_language: every kept seed of that language
        - nothing: the files that hold at least NONE_MIN_SYMBOLS kept symbols of that language
        - keys of the result are ( kind, lang ) and values are sorted id lists
    """
    pool    = collections.defaultdict( list )
    per_file = collections.defaultdict( list )
    for r in kept:
        lang = LANG_OF[ r[ "lang" ] ]
        mine = twins[ r[ "id" ] ] if r[ "id" ] in twins else []
        if any( t in all_ids for t in mine ): pool[ ( "near_copy", lang ) ].append( r[ "id" ] )
        pool[ ( "work_alike", lang ) ].append( r[ "id" ] )
        pool[ ( "cross_language", lang ) ].append( r[ "id" ] )
        per_file[ ( lang, r[ "file" ] ) ].append( r[ "id" ] )
    for ( lang, file ), ids in per_file.items():
        if len( ids ) >= NONE_MIN_SYMBOLS: pool[ ( "nothing", lang ) ].append( file )
    return { cell: sorted( ids ) for cell, ids in pool.items() }
