"""
The search process of the candidate stage.

It reads one JSON request on standard input and writes one JSON answer on standard output.
It holds no state between calls. This module imports numpy only when it ranks by cosine.
"""
import json
import pathlib
import sys

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates import candidate_stage as cs
from cosa.repo.symindex.candidates import rank_fusion as rf
from cosa.repo.symindex.candidates.errors import CandidateError, DEPENDENCY_MISSING, VECTOR_SET_CORRUPT, VECTOR_SET_UNAVAILABLE
from cosa.repo.symindex.candidates.bm25 import SCORE_DIGITS

REQUEST_ERROR        = "BAD_SEARCH_REQUEST"
INDEX_UNREADABLE     = "INDEX_UNREADABLE"
VECTOR_IDS_NOT_INDEX = "VECTOR_IDS_NOT_IN_INDEX"
FUSION_KEYS          = ( "k", "depth", "head" )
FLOAT32_MAX          = 3.4028234663852886e38


def is_count( value, minimum ):
    """
    Say whether a value is an integer of at least minimum, and not a bool.

    Ensures:
        - returns True only for an int that is not a bool and is at least minimum
    """
    return isinstance( value, int ) and not isinstance( value, bool ) and value >= minimum


def validate_request( request ):
    """
    Check the shape of a request before any work is done.

    Requires:
        - request is a dict

    Ensures:
        - returns None when need is a string, K a positive int, index_dir a string
        - checks fusion, when present, holds k and depth as positive ints and head as an int from 0 to depth
        - checks purposes, vectors_dir and wiki when present are a string, a string and a list of strings
        - checks query_vectors is a non-empty dict of lists of numbers, each finite and within float32 range, when vectors_dir is set
        - compares each value with the float32 limit directly, so a 400-digit integer is refused and never converted

    Raises:
        - CandidateError BAD_SEARCH_REQUEST naming the first key that is wrong
    """
    def bad( detail ): raise CandidateError( REQUEST_ERROR, detail )
    for key in ( "need", "K", "index_dir" ):
        if key not in request: bad( f"missing {key}" )
    if not isinstance( request[ "need" ], str ): bad( "need is not a string" )
    if not is_count( request[ "K" ], 1 ): bad( "K is not a positive integer" )
    if not isinstance( request[ "index_dir" ], str ): bad( "index_dir is not a string" )
    if request.get( "purposes" ) is not None and not isinstance( request[ "purposes" ], str ): bad( "purposes is not a string" )
    wiki = request.get( "wiki" )
    if wiki is not None and not ( isinstance( wiki, list ) and all( isinstance( w, str ) for w in wiki ) ): bad( "wiki is not a list of strings" )
    if "fusion" in request:
        fusion = request[ "fusion" ]
        if not isinstance( fusion, dict ) or set( fusion ) != set( FUSION_KEYS ): bad( f"fusion must hold exactly {', '.join( FUSION_KEYS )}" )
        if not is_count( fusion[ "k" ], 1 ) or not is_count( fusion[ "depth" ], 1 ): bad( "fusion k and depth must be positive integers" )
        if not is_count( fusion[ "head" ], 0 ) or fusion[ "head" ] > fusion[ "depth" ]: bad( "fusion head must be an integer from 0 to depth" )
    if request.get( "vectors_dir" ) is None: return
    if not isinstance( request[ "vectors_dir" ], str ): bad( "vectors_dir is not a string" )
    vectors = request.get( "query_vectors" )
    if not isinstance( vectors, dict ) or not vectors: bad( "query_vectors is missing or empty" )
    for name, vector in vectors.items():
        numbers = isinstance( vector, list ) and vector and all( isinstance( v, ( int, float ) ) and not isinstance( v, bool ) for v in vector )
        if not numbers: bad( f"query vector {name} is not a non-empty list of numbers" )
        if not all( abs( v ) <= FLOAT32_MAX for v in vector ): bad( f"query vector {name} holds a value that is not finite or is beyond float32 range" )


def cosine_ranked( ids, matrix, query ):
    """
    Rank rows of a matrix by cosine similarity to a query vector.

    Requires:
        - matrix has one float32 row per id
        - query is a list of floats with one value per column

    Ensures:
        - scores are cosine similarity, with a zero row or a zero query scoring 0.0
        - each score is rounded to SCORE_DIGITS places before the sort
        - returns ( id, score ) pairs ordered by ( -rounded score, id )

    Raises:
        - CandidateError BAD_SEARCH_REQUEST when a score is not finite
        - CandidateError DEPENDENCY_MISSING when numpy is not importable
    """
    try:
        import numpy as np
    except ImportError as e:
        raise CandidateError( DEPENDENCY_MISSING, f"numpy is not importable in this process: {e}" )
    q = np.asarray( query, dtype=np.float32 )
    with np.errstate( all="ignore" ):
        norms = np.linalg.norm( matrix, axis=1 ) * np.linalg.norm( q )
        dots  = matrix @ q
        flat  = np.divide( dots, norms, out=np.zeros( len( ids ), dtype=np.float32 ), where=norms > 0 )
    if not np.isfinite( norms ).all(): raise CandidateError( REQUEST_ERROR, "a cosine norm is not finite, the query vector is too large" )
    pairs = [ ( doc_id, round( float( s ), SCORE_DIGITS ) ) for doc_id, s in zip( ids, flat ) ]
    return sorted( pairs, key=lambda p: ( -p[ 1 ], p[ 0 ] ) )


def read_purposes( path ):
    """
    Read the stored purpose lines.

    Requires:
        - path is a purpose.jsonl file of { pin, purpose } rows, or None

    Ensures:
        - returns { pin: purpose }, empty when path is None
        - the first row stored for a pin wins, as the writer's own reader does
    """
    if path is None: return {}
    rows = [ json.loads( line ) for line in pathlib.Path( path ).read_text( encoding="utf-8" ).splitlines() if line ]
    purposes = {}
    for row in rows: purposes.setdefault( row[ "pin" ], row[ "purpose" ] )
    return purposes


def answer( request, load_vectors ):
    """
    Answer one search request.

    Requires:
        - request has passed the shape rules of validate_request
        - load_vectors takes a folder and returns an object with ids, matrices and manifest_hash

    Ensures:
        - ranks by BM25 over code and prose, by cosine over each stored matrix, and by the wiki list
        - names the cosine sources vector_prose, vector_code and vector_concat
        - returns { shortlist, ranking, lists, scores, K, manifest_hash, bm25, index_ids_without_vectors }
        - manifest_hash is the vector set's, or None when no vectors were asked for
        - index_ids_without_vectors counts index entries the set has no row for, or is None without vectors
        - the shortlist holds at most K ids

    Raises:
        - CandidateError BAD_SEARCH_REQUEST for a malformed request, an unknown matrix or a wrong vector width
        - CandidateError INDEX_UNREADABLE when the index folder or the purpose file cannot be read
        - CandidateError VECTOR_SET_UNAVAILABLE when the loader raises an OSError
        - CandidateError VECTOR_SET_CORRUPT when a matrix has a different row count from the ids
        - CandidateError VECTOR_IDS_NOT_IN_INDEX when the set holds an id the index lacks
        - CandidateError HEAD_EXCEEDS_LIMIT when the heads of the lists do not fit in K
    """
    validate_request( request )
    try:
        entries  = sx_build.read_symbols( request[ "index_dir" ] )
        purposes = read_purposes( request.get( "purposes" ) )
        stage    = cs.build_stage( entries, purposes, **{ k: request[ "fusion" ][ k ] for k in FUSION_KEYS } if "fusion" in request else {} )
    except ( OSError, ValueError, KeyError, TypeError ) as e:
        raise CandidateError( INDEX_UNREADABLE, f"{type( e ).__name__}: {e}" )
    extra, scores, manifest_hash, without_vectors = {}, {}, None, None
    if request.get( "vectors_dir" ) is not None:
        try:
            vectors = load_vectors( request[ "vectors_dir" ] )
        except OSError as e:
            raise CandidateError( VECTOR_SET_UNAVAILABLE, f"{type( e ).__name__}: {e}" )
        manifest_hash = vectors.manifest_hash
        index_ids     = set( stage.ids )
        ghosts        = sorted( i for i in vectors.ids if i not in index_ids )
        if ghosts: raise CandidateError( VECTOR_IDS_NOT_INDEX, f"{len( ghosts )} vector ids are not in the index, first {ghosts[ :3 ]}" )
        without_vectors = len( index_ids.difference( vectors.ids ) )
        for name in sorted( request[ "query_vectors" ] ):
            if name not in vectors.matrices: raise CandidateError( REQUEST_ERROR, f"the vector set has no matrix {name}" )
            rows, width = vectors.matrices[ name ].shape
            if rows != len( vectors.ids ):
                raise CandidateError( VECTOR_SET_CORRUPT, f"matrix {name} has {rows} rows for {len( vectors.ids )} ids" )
            if len( request[ "query_vectors" ][ name ] ) != width:
                raise CandidateError( REQUEST_ERROR, f"query vector {name} has {len( request[ 'query_vectors' ][ name ] )} values, the matrix has {width}" )
            pairs          = cosine_ranked( vectors.ids, vectors.matrices[ name ], request[ "query_vectors" ][ name ] )
            extra[ f"vector_{name}" ]  = [ doc_id for doc_id, _ in pairs ]
            scores[ f"vector_{name}" ] = [ score for _, score in pairs ]
    if request.get( "wiki" ): extra[ "wiki" ] = list( request[ "wiki" ] )
    result = cs.shortlist( request[ "need" ], stage, request[ "K" ], extra )
    result[ "scores" ].update( scores )
    result.update( { "K": request[ "K" ], "manifest_hash": manifest_hash, "bm25": stage.manifest(), "index_ids_without_vectors": without_vectors } )
    return result


def default_loader( vectors_dir ):
    """
    Load the stored vector set through the package's own reader.

    Ensures:
        - returns whatever vector_store.load_vectors returns for the folder
    """
    from cosa.repo.symindex.candidates import vector_store
    return vector_store.load_vectors( vectors_dir )


def main( stdin=None, stdout=None, load_vectors=default_loader ):
    """
    Run one request from standard input to standard output.

    Ensures:
        - writes the answer as sorted-key JSON and returns 0
        - writes { error, detail } and returns 2 when a CandidateError stops the search
        - writes BAD_SEARCH_REQUEST and returns 2 when the input is not a JSON object
        - never ends in a traceback for a malformed request
    """
    stdin  = sys.stdin  if stdin  is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    try:
        request = json.loads( stdin.read() )
        if not isinstance( request, dict ): raise CandidateError( REQUEST_ERROR, "the request is not a JSON object" )
        body, code = answer( request, load_vectors ), 0
    except json.JSONDecodeError as e:
        body, code = { "error": REQUEST_ERROR, "detail": str( e ) }, 2
    except CandidateError as e:
        body, code = { "error": e.code, "detail": e.detail }, 2
    stdout.write( json.dumps( body, sort_keys=True, separators=( ",", ":" ), ensure_ascii=True ) )
    return code


if __name__ == "__main__":    # pragma: no cover -- process entry, main() is tested
    sys.exit( main() )
