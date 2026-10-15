"""
The candidate stage as the lookup sees it: one need in, one shortlist of entry ids out.

The cosa-voice process cannot import numpy, so the search runs on the Lupin server (the
resident search). This module redacts nothing and ranks nothing. It gets the query vectors from
the cache or the embeddings endpoints and builds the wiki list. It uploads the entries once per
index and asks for the shortlist by key. A failure is a named CandidateError and never a silent sweep.
"""
import hashlib
import json
import pathlib
import urllib.error
import urllib.request

from cosa.repo.symindex.candidates import search as cs_search
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates import wiki_list
from cosa.repo.symindex.candidates.errors import CandidateError

CANDIDATE_SEARCH_FAILED = "CANDIDATE_SEARCH_FAILED"
QUERY_VECTOR_MISSING    = "QUERY_VECTOR_MISSING"
VECTOR_SET_REPLACED     = "VECTOR_SET_REPLACED"
EMPTY_NEED              = "EMPTY_NEED"
STAGE_UNKNOWN           = "STAGE_UNKNOWN"
STAGE_VERSION           = "1"
DEFAULT_K               = 128
DEFAULT_ARM             = "B2w"
ARMS                    = { "B1": ( "concat", ), "B2": ( "prose", "code" ), "B2w": ( "prose", "code" ) }     # the matrices each arm asks about
WIKI_ARMS               = ( "B2w", )
TIMEOUT_SECONDS         = 60


def canonical( obj ):
    """Ensures: returns sorted-key JSON with no spaces after separators."""
    return json.dumps( obj, sort_keys=True, separators=( ",", ":" ), ensure_ascii=True )


class CandidateStage:
    """
    The client of the resident search for one vector set, query cache and purpose file.

    Requires:
        - base_url is the Lupin server's URL, api_key its X-API-Key value
        - vectors_dir holds the live vector set, as the server sees the same path
        - embed_client has embed( texts, content_type, role ) and info()
        - arm is one of the names in the arms tuple, and K a positive integer

    Ensures:
        - holds no state between lookups except the fact that a stage key was uploaded
    """

    def __init__( self, base_url, api_key, vectors_dir, query_cache_dir, embed_client, purposes_path=None, K=DEFAULT_K, arm=DEFAULT_ARM,
                  fusion=None, timeout=TIMEOUT_SECONDS, urlopen=urllib.request.urlopen ):
        """Hold the endpoints, folders and settings, and check the arm and K."""
        if arm not in ARMS: raise ValueError( f"arm must be one of {sorted( ARMS )}, got {arm!r}" )
        if not isinstance( K, int ) or isinstance( K, bool ) or K < 1: raise ValueError( f"K must be a positive integer, got {K!r}" )
        self.base_url, self.api_key = base_url.rstrip( "/" ), api_key
        self.vectors_dir, self.query_cache_dir = str( vectors_dir ), str( query_cache_dir )
        self.embed_client, self.purposes_path = embed_client, purposes_path
        self.K, self.arm, self.fusion = K, arm, fusion
        self.timeout, self._urlopen = timeout, urlopen
        self._uploaded = set()

    def manifest( self ):
        """
        Read the live vector set's manifest and check that it hashes to itself.

        Ensures:
            - returns the manifest mapping

        Raises:
            - CandidateError VECTOR_SET_UNAVAILABLE when there is no manifest
            - CandidateError VECTOR_SET_CORRUPT when the manifest does not hash to its manifest_hash
        """
        path = pathlib.Path( self.vectors_dir ) / vs.MANIFEST_FILE
        try:
            manifest = json.loads( path.read_text( encoding="utf-8" ) )
        except OSError as e:
            raise CandidateError( vs.VECTOR_SET_UNAVAILABLE, f"no manifest in {self.vectors_dir}: {e}" )
        except ValueError as e:
            raise CandidateError( vs.VECTOR_SET_CORRUPT, f"the manifest is not JSON: {e}" )
        if vs.manifest_hash( manifest ) != manifest.get( "manifest_hash" ):
            raise CandidateError( vs.VECTOR_SET_CORRUPT, "the manifest does not hash to its manifest_hash" )
        return manifest

    def _vectors( self, ranking_text, manifest, cache_only ):
        """
        Return the query vectors the arm asks about.

        Ensures:
            - with cache_only, a vector that is not cached under this manifest hash is QUERY_VECTOR_MISSING and nothing is embedded
            - otherwise the vectors come from the cache or from the embeddings endpoints, as query_vectors does
            - returns { matrix name: vector } for the arm's matrices only
        """
        if cache_only:
            path = pathlib.Path( self.query_cache_dir ) / f"{vs.query_key( ranking_text )}.json"
            try:
                stored = json.loads( path.read_text( encoding="utf-8" ) )
                held   = stored[ "manifest_hash" ] == manifest[ "manifest_hash" ]
                every  = stored[ "vectors" ]
            except ( OSError, ValueError, KeyError ):
                held, every = False, None
            if not held: raise CandidateError( QUERY_VECTOR_MISSING, f"no cached query vector for {vs.query_key( ranking_text )[ :12 ]} under this vector set" )
        else:
            every = vs.query_vectors( ranking_text, self.embed_client, self.query_cache_dir, manifest )
        return { name: every[ name ] for name in ARMS[ self.arm ] }

    def _call( self, method, path, body ):
        """
        Send one JSON request to the resident search.

        Ensures:
            - returns ( status, parsed body ) for any HTTP answer, including an error status

        Raises:
            - CandidateError CANDIDATE_SEARCH_FAILED when the server cannot be reached or answers something that is not JSON
        """
        request = urllib.request.Request( self.base_url + path, data=canonical( body ).encode( "utf-8" ), method=method,
                                          headers={ "Content-Type": "application/json", "X-API-Key": self.api_key or "" } )
        try:
            with self._urlopen( request, timeout=self.timeout ) as response:
                return response.status, json.loads( response.read() )
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads( e.read() )
            except ValueError: raise CandidateError( CANDIDATE_SEARCH_FAILED, f"the server answered {e.code} with a body that is not JSON" )
        except ( urllib.error.URLError, OSError, ValueError ) as e:
            raise CandidateError( CANDIDATE_SEARCH_FAILED, f"{type( e ).__name__}: {e}" )

    def _stage_key( self, index_sha, entries, purposes ):
        """Ensures: returns the key that holds an index, its purposes and the fusion constants."""
        return hashlib.sha256( canonical( { "v": STAGE_VERSION, "index_sha": index_sha, "entries": len( entries ),
                                            "purposes": hashlib.sha256( canonical( purposes ).encode( "utf-8" ) ).hexdigest(), "fusion": self.fusion } ).encode( "utf-8" ) ).hexdigest()[ :32 ]

    def shortlist( self, ranking_text, entries, index_sha, pages, exclude_id=None, cache_only=False, wiki_ids=None ):
        """
        Choose the candidates for a need.

        Requires:
            - ranking_text is the redacted need with its redacted spans removed
            - entries are the sendable index entries, each with an id and a pin
            - index_sha identifies those entries, and pages is the list page_candidates returns
            - wiki_ids is None, or the wiki list a receipt recorded, which then replaces the one built from pages

        Ensures:
            - returns { ids, ranking, lists, manifest_hash, embed_models, arm, K, widened, stage_key, wiki, wiki_ids, ranking_hash }
            - ids are the shortlist sorted by id, without exclude_id, at most K of them
            - ranking is the fused order of those ids
            - lists names each list that fed the fusion with its size and its first ids
            - the wiki list is used only by the arms that take it
            - cache_only never embeds and never uploads: it is the replay's read

        Raises:
            - CandidateError EMPTY_NEED when the ranking text holds no word
            - CandidateError VECTOR_SET_UNAVAILABLE or VECTOR_SET_CORRUPT from the manifest
            - CandidateError QUERY_VECTOR_MISSING in cache_only mode
            - CandidateError ENGINE_MISMATCH or ENGINE_NOT_LOADED from the engine check
            - CandidateError CANDIDATE_SEARCH_FAILED for any failure of the call, naming the server's error
        """
        if not ranking_text.strip(): raise CandidateError( EMPTY_NEED, "the need holds no word once the redacted spans are removed" )
        manifest = self.manifest()
        vectors  = self._vectors( ranking_text, manifest, cache_only )
        wiki     = ( wiki_list.wiki_ranked_ids( ranking_text, pages ) if wiki_ids is None else list( wiki_ids ) ) if self.arm in WIKI_ARMS else []
        purposes = cs_search.read_purposes( self.purposes_path ) if self.purposes_path is not None and pathlib.Path( self.purposes_path ).is_file() else {}
        key      = self._stage_key( index_sha, entries, purposes )
        asked    = self.K + ( 1 if exclude_id is not None else 0 )
        body     = { "stage_key": key, "need": ranking_text, "K": asked, "vectors_dir": self.vectors_dir, "query_vectors": vectors, "wiki": wiki,
                     "expect_manifest_hash": manifest[ "manifest_hash" ] }
        status, answer = self._call( "POST", "/api/reuse-candidates/search", body )
        if status == 409 and answer.get( "error" ) == STAGE_UNKNOWN and not cache_only:
            upload = { "key": key, "entries": entries, "purposes": purposes or None, "fusion": self.fusion }
            up_status, up_answer = self._call( "PUT", "/api/reuse-candidates/stage", upload )
            if up_status != 200: raise CandidateError( CANDIDATE_SEARCH_FAILED, f"{up_answer.get( 'error' )}: {up_answer.get( 'detail' )}" )
            status, answer = self._call( "POST", "/api/reuse-candidates/search", body )
        if status == 409 and answer.get( "error" ) == VECTOR_SET_REPLACED:
            raise CandidateError( VECTOR_SET_REPLACED, answer.get( "detail", "" ) )
        if status != 200: raise CandidateError( CANDIDATE_SEARCH_FAILED, f"{answer.get( 'error' )}: {answer.get( 'detail' )}" )
        ranking = [ i for i in answer[ "ranking" ] if i != exclude_id ][ :self.K ]
        lists   = { name: { "size": answer[ "list_sizes" ][ name ], "head": answer[ "lists" ][ name ] } for name in sorted( answer[ "lists" ] ) }
        return { "ids": sorted( ranking ), "ranking": ranking, "lists": lists, "manifest_hash": answer[ "manifest_hash" ],
                 "embed_models": { kind: manifest[ "engines" ][ kind ][ "model" ] for kind in ( "code", "prose" ) },
                 "arm": self.arm, "K": self.K, "widened": False, "stage_key": key, "wiki": len( wiki ), "wiki_ids": wiki,
                 "ranking_hash": hashlib.sha256( ranking_text.encode( "utf-8" ) ).hexdigest() }
