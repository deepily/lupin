"""
The resident search: stages and vector sets held between lookups.

A search process that starts for every lookup pays for the BM25 build and the matrix load each time.
This holds both, keyed by what they were built from, so a lookup costs one cosine pass per matrix.
It reads no index folder: the caller uploads the entries once per index and searches by key.
It reads a vectors folder only under the root it was given, and names the manifest hash it served.
"""
import os
import pathlib
import threading

from cosa.repo.symindex.candidates import candidate_stage as cs
from cosa.repo.symindex.candidates import search
from cosa.repo.symindex.candidates.errors import (
    CandidateError, BAD_STAGE_UPLOAD, PATH_REFUSED, STAGE_UNKNOWN, VECTOR_SET_REPLACED )

MAX_STAGES      = 2
MAX_VECTOR_SETS = 2
MANIFEST_NAME   = "manifest.json"


class ResidentSearch:
    """
    Held stages and vector sets, and the one search that uses them.

    Requires:
        - allowed_root is the folder every vectors folder must sit under
        - load_vectors takes a folder and returns an object with ids, matrices and manifest_hash

    Ensures:
        - a stage is held under its key until MAX_STAGES newer ones push it out
        - a vector set is held under its folder and the size and mtime of its manifest, until MAX_VECTOR_SETS newer ones push it out
        - one call is one search; no state of one search reaches another
    """

    def __init__( self, allowed_root, load_vectors=search.default_loader, max_stages=MAX_STAGES, max_vector_sets=MAX_VECTOR_SETS ):
        """Hold the root, the loader and the limits, with nothing loaded."""
        self._root     = os.path.realpath( allowed_root )
        self._load     = load_vectors
        self._max_s    = max_stages
        self._max_v    = max_vector_sets
        self._stages   = {}
        self._vectors  = {}
        self._lock     = threading.Lock()

    def put_stage( self, key, entries, purposes=None, fusion=None ):
        """
        Build a stage from uploaded entries and hold it.

        Requires:
            - key is a non-empty string the caller derives from the entries and the purpose lines
            - entries is a list of index records, each with an id
            - purposes is None or a mapping of pin to purpose line
            - fusion is None or { k, depth, head }

        Ensures:
            - returns { key, entries } with the count of entries held
            - uploading a key that is held again replaces it with the same stage

        Raises:
            - CandidateError BAD_STAGE_UPLOAD for a shape that is wrong, naming the first thing that is
        """
        def bad( detail ): raise CandidateError( BAD_STAGE_UPLOAD, detail )
        if not isinstance( key, str ) or not key: bad( "key is not a non-empty string" )
        if not isinstance( entries, list ) or not entries: bad( "entries is not a non-empty list" )
        if not all( isinstance( e, dict ) and isinstance( e.get( "id" ), str ) for e in entries ): bad( "an entry is not a dict with a string id" )
        if purposes is not None and not isinstance( purposes, dict ): bad( "purposes is not a mapping" )
        if fusion is not None and ( not isinstance( fusion, dict ) or set( fusion ) != set( search.FUSION_KEYS ) ): bad( f"fusion must hold exactly {', '.join( search.FUSION_KEYS )}" )
        kw    = { k: fusion[ k ] for k in search.FUSION_KEYS } if fusion is not None else {}
        stage = cs.build_stage( entries, purposes or {}, **kw )
        with self._lock:
            self._stages.pop( key, None )
            self._stages[ key ] = stage
            while len( self._stages ) > self._max_s: self._stages.pop( next( iter( self._stages ) ) )
        return { "key": key, "entries": len( entries ) }

    def _confined( self, folder ):
        """
        Resolve a vectors folder and refuse one outside the root.

        Ensures:
            - returns the resolved folder as a string when it is the root or sits under it

        Raises:
            - CandidateError PATH_REFUSED otherwise
        """
        resolved = os.path.realpath( folder )
        if resolved != self._root and not resolved.startswith( self._root + os.sep ):
            raise CandidateError( PATH_REFUSED, f"{folder} is not under the allowed root" )
        return resolved

    def _vectors_for( self, folder ):
        """
        Return the held vector set of a folder, loading it when it is new or its manifest changed.

        Ensures:
            - a manifest whose size or mtime changed is loaded again, and the old set is dropped
        """
        manifest = pathlib.Path( folder ) / MANIFEST_NAME
        try:
            st  = manifest.stat()
            sig = ( st.st_size, st.st_mtime_ns )
        except OSError:
            sig = None                                                              # the loader names the missing set
        with self._lock:
            held = self._vectors.get( folder )
            if held is not None and sig is not None and held[ 0 ] == sig:
                vectors = held[ 1 ]
            else:
                vectors = self._load( folder )
                if sig is not None:
                    self._vectors.pop( folder, None )
                    self._vectors[ folder ] = ( sig, vectors )
                    while len( self._vectors ) > self._max_v: self._vectors.pop( next( iter( self._vectors ) ) )
        return vectors

    def search( self, request ):
        """
        Answer one search against a held stage.

        Requires:
            - request holds stage_key, need and K, and may hold vectors_dir with query_vectors, wiki and expect_manifest_hash

        Ensures:
            - returns what search.answer_for_stage returns
            - a request with expect_manifest_hash is refused when the set it would read has another hash

        Raises:
            - CandidateError BAD_SEARCH_REQUEST for a malformed request
            - CandidateError STAGE_UNKNOWN when no stage is held under stage_key
            - CandidateError PATH_REFUSED for a vectors folder outside the allowed root
            - CandidateError VECTOR_SET_REPLACED when the set on disk is not the one the caller expected
            - everything search.answer_for_stage raises
        """
        search.validate_request( request, with_index=False )
        key = request.get( "stage_key" )
        if not isinstance( key, str ) or not key: raise CandidateError( search.REQUEST_ERROR, "stage_key is missing or not a string" )
        with self._lock: stage = self._stages.get( key )
        if stage is None: raise CandidateError( STAGE_UNKNOWN, key )
        if request.get( "vectors_dir" ) is not None: request = dict( request, vectors_dir=self._confined( request[ "vectors_dir" ] ) )
        expected = request.get( "expect_manifest_hash" )
        if expected is not None and not isinstance( expected, str ): raise CandidateError( search.REQUEST_ERROR, "expect_manifest_hash is not a string" )

        def loader( folder ):
            vectors = self._vectors_for( folder )
            if expected is not None and vectors.manifest_hash != expected:
                raise CandidateError( VECTOR_SET_REPLACED, f"expected {expected[ :12 ]}, the set on disk is {vectors.manifest_hash[ :12 ]}" )
            return vectors

        return search.answer_for_stage( request, stage, loader )
