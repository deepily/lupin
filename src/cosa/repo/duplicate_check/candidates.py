"""Candidate stage: three ranked lists per definition, joined by rank fusion."""
import numpy as np

from cosa.repo.symindex.candidates import bm25, rank_fusion

LISTS         = ( "embedding", "words", "structural" )
WORD_FIELDS   = ( "name", "sig", "text" )
SCORE_DIGITS  = 6


def same_slot( a, b ):
    """
    Say whether two definitions are the same one or a redefinition of it.

    Requires:
        - a and b are definition records

    Ensures:
        - True when they have the same id, or the same file and the same name
    """
    return a[ "id" ] == b[ "id" ] or ( a[ "file" ] == b[ "file" ] and a[ "name" ] == b[ "name" ] )


def build_pool( defs, vectors ):
    """
    Gather the definitions a candidate may come from, with their unit-length vectors.

    Requires:
        - defs are the new and server definitions together, unique by id
        - vectors maps each definition id to its vector, all of one length

    Ensures:
        - returns { defs, position, matrix }: the definitions ordered by id, each id's row, and a float64 matrix of unit vectors
        - a zero vector stays zero, so it scores 0 against everything

    Raises:
        - KeyError if a definition has no vector
    """
    ordered = sorted( defs, key=lambda d: d[ "id" ] )
    matrix  = np.array( [ vectors[ d[ "id" ] ] for d in ordered ], dtype=np.float64 )
    norms   = np.linalg.norm( matrix, axis=1 )
    matrix  = matrix / np.where( norms == 0.0, 1.0, norms )[ :, None ]
    return { "defs": ordered, "position": { d[ "id" ]: i for i, d in enumerate( ordered ) }, "matrix": matrix }


def word_index( pool ):
    """
    Build the word index over the pool: name, signature and text, split into words.

    Requires:
        - pool came from build_pool

    Ensures:
        - returns a frozen BM25 index whose documents are the pool's ids
    """
    return bm25.build_bm25( [ { "id": d[ "id" ], "name": d[ "name" ], "sig": d[ "sig" ], "text": d[ "text" ] } for d in pool[ "defs" ] ], WORD_FIELDS )


def partner_map( pairs ):
    """
    Turn structural pairs into the partners of each definition, closest clone first.

    Requires:
        - pairs are { ids, size, source } already ordered by size, largest first, then by ids

    Ensures:
        - returns { id: [ partner ids ] } in the order the pairs were given, each partner once
    """
    partners = {}
    for pair in pairs:
        a, b = pair[ "ids" ]
        partners.setdefault( a, [] ).append( b )
        partners.setdefault( b, [] ).append( a )
    return { i: list( dict.fromkeys( ids ) ) for i, ids in partners.items() }


def _keep( d, ids, pool, depth ):
    """
    Take the first depth ids that are in the pool and are not d or a redefinition of it.

    Requires:
        - ids are definition ids in rank order

    Ensures:
        - returns at most depth ids, in the order given
        - an id that is not in the pool, such as the partner of a clone that a filter took out, is passed over
    """
    out = []
    for i in ids:
        if i not in pool[ "position" ]: continue
        if same_slot( d, pool[ "defs" ][ pool[ "position" ][ i ] ] ): continue
        out.append( i )
        if len( out ) == depth: break
    return out


def outside_pool( d, pool, partners ):
    """
    Count the clone partners of d that are not in the pool.

    Requires:
        - partners came from partner_map

    Ensures:
        - returns how many of d's partners the structural list passed over, so a narrowed pool is reported and not hidden
    """
    return sum( 1 for i in partners.get( d[ "id" ], [] ) if i not in pool[ "position" ] )


def embedding_list( d, pool, depth ):
    """
    List the nearest definitions by cosine of their body vectors.

    Requires:
        - d is in the pool; depth is a positive int

    Ensures:
        - returns at most depth ids, best first, never d and never a redefinition of d
        - scores are rounded to SCORE_DIGITS places before the sort and ties go to the smaller id
        - a pair in different languages is allowed

    Raises:
        - KeyError if d is not in the pool
    """
    row    = pool[ "position" ][ d[ "id" ] ]
    scores = np.round( pool[ "matrix" ] @ pool[ "matrix" ][ row ], SCORE_DIGITS )
    order  = np.lexsort( ( np.arange( len( scores ) ), -scores ) )
    return _keep( d, [ pool[ "defs" ][ i ][ "id" ] for i in order ], pool, depth )


def word_list( d, pool, index, depth ):
    """
    List the definitions sharing the most words with d, by BM25.

    Requires:
        - d is in the pool; index came from word_index( pool ); depth is a positive int

    Ensures:
        - returns at most depth ids, best first, never d and never a redefinition of d
        - only definitions that share a word with d are listed
    """
    ranked = bm25.rank( index, " ".join( [ d[ "name" ], d[ "sig" ], d[ "text" ] ] ) )
    return _keep( d, ranked, pool, depth )


def structural_list( d, pool, partners, depth ):
    """
    List the structural clones of d, closest first.

    Requires:
        - d is in the pool; partners came from partner_map; depth is a positive int

    Ensures:
        - returns at most depth ids in clone order, never d and never a redefinition of d
        - a definition with no clone gets an empty list
    """
    return _keep( d, partners.get( d[ "id" ], [] ), pool, depth )


def candidates_for( d, pool, lists, cfg ):
    """
    Fuse the three lists into the candidate row of one definition.

    Requires:
        - lists is { embedding, words, structural }, each a list of ids, best first, cut at cfg list_depth
        - cfg is the frozen configuration

    Ensures:
        - returns { id, short, candidates: [ { id, rank, from } ] }, ranks from 1 in fused order
        - from names the lists that held the candidate, in the order embedding, words, structural
        - every list keeps its top fusion_head ids, whatever their fused score
        - at most max_candidates are kept
        - short is True when fewer than min_candidates were found, which happens only when the pool holds fewer other definitions
    """
    ordered = [ lists[ name ] for name in LISTS ]
    fused   = rank_fusion.fuse( ordered, depth=cfg[ "list_depth" ], limit=cfg[ "max_candidates" ], head=cfg[ "fusion_head" ] )
    rows    = [ { "id": i, "rank": rank, "from": [ name for name in LISTS if i in lists[ name ][ :cfg[ "list_depth" ] ] ] } for rank, i in enumerate( fused, start=1 ) ]
    return { "id": d[ "id" ], "short": len( rows ) < cfg[ "min_candidates" ], "candidates": rows }


def candidate_rows( new_defs, pool, index, partners, cfg ):
    """
    Build the candidate row of every new definition.

    Requires:
        - new_defs are definitions of the pool with origin "new"; the other arguments are as for the list builders

    Ensures:
        - returns one row per definition, in the order given, each with outside_pool: the clone partners that were not in the pool

    Raises:
        - ValueError if a definition has another origin or is not in the pool, since a server definition must never be judged as the run's own
    """
    depth = cfg[ "list_depth" ]
    rows  = []
    for d in new_defs:
        if d[ "origin" ] != "new": raise ValueError( f"{d[ 'id' ]} has origin {d[ 'origin' ]!r}, only new definitions get candidate rows" )
        if d[ "id" ] not in pool[ "position" ]: raise ValueError( f"{d[ 'id' ]} is not in the pool" )
        lists = { "embedding": embedding_list( d, pool, depth ), "words": word_list( d, pool, index, depth ), "structural": structural_list( d, pool, partners, depth ) }
        rows.append( { **candidates_for( d, pool, lists, cfg ), "outside_pool": outside_pool( d, pool, partners ) } )
    return rows
