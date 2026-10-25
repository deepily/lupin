"""Candidate duplicate pairs in the monolith script, each tagged with its source."""
import hashlib

import numpy as np

from cosa.repo.semdup import errors as err

SOURCES = ( "structural", "neighbour", "nominated" )


def blob_sha( path ):
    """
    Return the git blob sha of a file, so a pair list can be pinned to one version of it.

    Requires:
        - path names a readable file

    Ensures:
        - returns the 40 hex digits git hash-object gives the file
    """
    data = open( path, "rb" ).read()
    return hashlib.sha1( b"blob " + str( len( data ) ).encode( "ascii" ) + b"\0" + data ).hexdigest()


def check_pin( path, expected ):
    """
    Refuse a monolith that is not the pinned version.

    Requires:
        - expected is the blob sha the pair list was made from

    Raises:
        - ValueError if the file's blob sha differs, naming both
    """
    actual = blob_sha( path )
    if actual != expected: raise ValueError( f"{path} is blob {actual}, but the pairs are pinned to {expected}" )


def _neighbours( defs, vectors ):
    """Return every pair of definitions with its cosine, most similar first, ties by ids."""
    ordered = sorted( defs, key=lambda d: d[ "id" ] )
    matrix  = np.array( [ vectors[ d[ "id" ] ] for d in ordered ], dtype=np.float64 )
    norms   = np.linalg.norm( matrix, axis=1 )
    matrix  = matrix / np.where( norms == 0.0, 1.0, norms )[ :, None ]
    sims    = matrix @ matrix.T
    pairs   = [ ( round( float( sims[ i, j ] ), 6 ), ordered[ i ][ "id" ], ordered[ j ][ "id" ] ) for i in range( len( ordered ) ) for j in range( i + 1, len( ordered ) ) ]
    return sorted( pairs, key=lambda p: ( -p[ 0 ], p[ 1 ], p[ 2 ] ) )


def candidate_pairs( defs, structural, vectors, nominated, per_source, total=None ):
    """
    Collect candidate pairs from the three sources.

    Requires:
        - defs are the monolith's definition records; vectors maps each id to its vector
        - structural is a list of clone pairs { ids, size, source } from structural.clone_pairs
        - nominated is the list of [ a, b ] id pairs a person named, or empty; per_source is the most pairs taken from each source
        - total is None, or the size the list is to reach: the neighbour source then takes what is left of it after the structural and nominated pairs

    Ensures:
        - returns { ids, source } records with ids sorted and source one of the three source names, each pair once
        - structural: the largest clones whose two definitions are both in defs
        - neighbour: the most similar pairs by cosine that structural does not list, so a pair is never tagged by a source that is already the structural list; with total, as many as bring the list to total, never fewer than none
        - nominated: every pair a person named, whatever its similarity
        - a pair found by more than one source keeps the first source in the order structural, neighbour, nominated

    Raises:
        - ValueError if per_source is below 1, or a nominated pair names an id not in defs or pairs a definition with itself
    """
    if per_source < 1: raise ValueError( f"per_source must be 1 or more, got {per_source}" )
    ids   = { d[ "id" ] for d in defs }
    taken = {}
    found = [ tuple( sorted( p[ "ids" ] ) ) for p in sorted( structural, key=lambda p: ( -p[ "size" ], p[ "ids" ] ) ) if set( p[ "ids" ] ) <= ids ]
    for pair in found[ :per_source ]: taken.setdefault( pair, "structural" )
    linked = set( found )
    close  = [ ( a, b ) for _, a, b in _neighbours( defs, vectors ) if ( a, b ) not in linked ]
    room   = per_source if total is None else max( total - len( taken ) - len( { tuple( sorted( n ) ) for n in nominated } ), 0 )
    for pair in close[ :room ]: taken.setdefault( pair, "neighbour" )
    for a, b in nominated:
        if a == b or a not in ids or b not in ids: raise ValueError( f"nominated pair {a}, {b} is not two distinct definitions of the monolith" )
        taken.setdefault( tuple( sorted( ( a, b ) ) ), "nominated" )
    return [ { "ids": list( pair ), "source": source } for pair, source in sorted( taken.items(), key=lambda kv: ( SOURCES.index( kv[ 1 ] ), kv[ 0 ] ) ) ]


def assemble_pairs( tagged ):
    """
    Check the tags of a pair list and return it in a fixed order.

    Requires:
        - tagged is a list of { ids, source } records

    Ensures:
        - returns the records ordered by source (structural, neighbour, nominated) and then by ids
        - every pair appears once

    Raises:
        - SemdupError BAD_PAIR_SOURCE if a pair has no source tag or a tag outside the three
        - ValueError if a pair is listed twice
    """
    seen = set()
    for p in tagged:
        if p.get( "source" ) not in SOURCES: raise err.SemdupError( err.BAD_PAIR_SOURCE, f"pair {p.get( 'ids' )} has source {p.get( 'source' )!r}, not one of {SOURCES}" )
        key = tuple( sorted( p[ "ids" ] ) )
        if key in seen: raise ValueError( f"pair {key} is listed twice" )
        seen.add( key )
    return sorted( ( { "ids": sorted( p[ "ids" ] ), "source": p[ "source" ] } for p in tagged ), key=lambda p: ( SOURCES.index( p[ "source" ] ), p[ "ids" ] ) )
