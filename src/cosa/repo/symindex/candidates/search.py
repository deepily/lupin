"""
The search process of the candidate stage.

It reads one JSON request on standard input and writes one JSON answer on standard output.
It holds no state between calls. numpy is imported here and nowhere else in the package.
"""
import json
import pathlib
import sys

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates import candidate_stage as cs
from cosa.repo.symindex.candidates import rank_fusion as rf
from cosa.repo.symindex.candidates.errors import CandidateError, DEPENDENCY_MISSING
from cosa.repo.symindex.candidates.bm25 import SCORE_DIGITS

REQUEST_ERROR = "BAD_SEARCH_REQUEST"
MATRIX_SOURCES = ( "prose", "code" )


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
        - CandidateError DEPENDENCY_MISSING when numpy is not importable
    """
    try:
        import numpy as np
    except ImportError as e:
        raise CandidateError( DEPENDENCY_MISSING, f"numpy is not importable in this process: {e}" )
    q     = np.asarray( query, dtype=np.float32 )
    norms = np.linalg.norm( matrix, axis=1 ) * np.linalg.norm( q )
    dots  = matrix @ q
    flat  = np.divide( dots, norms, out=np.zeros( len( ids ), dtype=np.float32 ), where=norms > 0 )
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
        - request holds need, K and index_dir
        - when vectors_dir is set, query_vectors holds a vector for each matrix named in the set
        - load_vectors takes a folder and returns an object with ids, matrices and manifest_hash

    Ensures:
        - ranks by BM25 over code and prose, by cosine over each stored matrix, and by the wiki list
        - names the cosine sources vector_prose, vector_code and vector_concat
        - returns { shortlist, ranking, lists, scores, K, manifest_hash, bm25 }
        - manifest_hash is the vector set's, or None when no vectors were asked for

    Raises:
        - CandidateError BAD_SEARCH_REQUEST when a required key is missing
    """
    for key in ( "need", "K", "index_dir" ):
        if key not in request: raise CandidateError( REQUEST_ERROR, f"missing {key}" )
    entries = sx_build.read_symbols( request[ "index_dir" ] )
    stage   = cs.build_stage( entries, read_purposes( request.get( "purposes" ) ),
                              **{ k: request[ "fusion" ][ k ] for k in ( "k", "depth", "head" ) } if "fusion" in request else {} )
    extra, scores, manifest_hash = {}, {}, None
    if request.get( "vectors_dir" ) is not None:
        vectors       = load_vectors( request[ "vectors_dir" ] )
        manifest_hash = vectors.manifest_hash
        for name in sorted( request[ "query_vectors" ] ):
            pairs          = cosine_ranked( vectors.ids, vectors.matrices[ name ], request[ "query_vectors" ][ name ] )
            extra[ f"vector_{name}" ]  = [ doc_id for doc_id, _ in pairs ]
            scores[ f"vector_{name}" ] = [ score for _, score in pairs ]
    if request.get( "wiki" ): extra[ "wiki" ] = list( request[ "wiki" ] )
    result = cs.shortlist( request[ "need" ], stage, request[ "K" ], extra )
    result[ "scores" ].update( scores )
    result.update( { "K": request[ "K" ], "manifest_hash": manifest_hash, "bm25": stage.manifest() } )
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
